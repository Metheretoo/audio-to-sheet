"""audio-to-sheet music v3 — API Flask avec Pydantic validation + SSE async"""
import os
import sys
import uuid
import tempfile
import json
import logging
import threading
import time
from queue import Queue, Empty
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from transcriber import TranscriptionPipeline

# ── Pydantic disponible ? ──────────────────────────────────────────────────────
try:
    from pydantic import BaseModel, Field, field_validator
    from pydantic import ValidationError as PydanticValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

# ── Pydantic models pour validation (chargement différé) ───────────────────────
TranscriptionOptionsModel = None
_validate_transcription_options = None
_get_validation_summary = None

def _init_pydantic_models():
    """Initialise les modèles Pydantic si disponibles (chargement différé)."""
    global TranscriptionOptionsModel, _validate_transcription_options, _get_validation_summary
    if TranscriptionOptionsModel is not None:
        return  # déjà initialisé
    if not PYDANTIC_AVAILABLE:
        return
    try:
        from pydantic import BaseModel, Field, field_validator
        from typing import Optional, Literal

        class TranscriptionOptionsModel(BaseModel):
            transcriber: Literal['piano_transcription', 'basic_pitch', 'transkun', 'hft', 'mt3', 'ensemble'] = 'piano_transcription'
            preset: Literal['standard', 'jazz', 'classical', 'beginner'] = 'standard'
            use_demucs: bool = False
            onset_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
            frame_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
            offset_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
            minimum_note_duration: int = Field(default=50, ge=10, le=500)
            time_sig: str = Field(default='4/4', pattern='^[0-9]+/[0-9]+$')
            key_sig: str = Field(default='C', pattern='^[A-G][#b]?$')
            detect_tempo: bool = True
            detect_meter: bool = True
            detect_key: bool = True
            quantization_level: Literal['none', 'simple', 'standard', 'strict', 'classique', 'precision'] = 'standard'
            remove_short_notes: bool = False
            merge_near_notes: bool = False
            merge_gap_ms: int = Field(default=30, ge=10, le=200)
            split_hands: bool = False
            enable_rubato: bool = False
            enable_triplets: bool = False
            quantization_sensitivity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
            # Méthodes de filtrage harmonique disponibles :
            #   basic       — octave + quinte uniquement (léger)
            #   classical   — filtrage classique piano
            #   classical-strong — seuils renforcés (Chopin, Nocturnes, Mazurkas)
            #   pedal-aware — spécialisé harmoniques de pédale
            #   aggressive  — très agressif (romantique)
            #   ultra       — maximum (notes vélocité > 0.25 considérées)
            #   off         — aucun filtrage
            harmonic_filter: Optional[Literal['basic', 'classical', 'classical-strong', 'pedal-aware', 'aggressive', 'ultra', 'off']] = Field(default='classical-strong')  # défaut: classical-strong pour Chopin/Nocturnes/Mazurkas
            # Paramètres manuels fins du filtrage harmonique (optionnels, remplacent les méthodes prédéfinies)
            harmonic_velocity_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
            harmonic_protection_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
            harmonic_time_tolerance: Optional[float] = Field(default=None, ge=0.0, le=0.5)
            harmonic_bass_threshold: Optional[int] = Field(default=None, ge=12, le=72)
            strict_mode: bool = False
            tempo: Optional[float] = Field(default=None, ge=40, le=300)

        def validate_transcription_options(form_data: dict):
            errors = []
            try:
                validated = TranscriptionOptionsModel(**form_data)
                return validated.model_dump(exclude_unset=True), errors
            except Exception as e:
                if hasattr(e, 'errors'):
                    for err in e.errors():
                        field = '->'.join(str(p) for p in err.get('loc', []))
                        msg = err.get('msg', str(err.get('ctx', {})))
                        errors.append(f"  * {field}: {msg}")
                else:
                    errors.append(f"  Validation error: {str(e)}")
                return None, errors

        def get_validation_summary():
            return (f"Schema validé: {len(TranscriptionOptionsModel.model_fields)} champs, "
                    f"plages: onset[0-1], frame[0-1], offset[0-1], "
                    "minimum_note_duration[10-500], merge_gap_ms[10-200], tempo[40-300]")

        _validate_transcription_options = validate_transcription_options
        _get_validation_summary = get_validation_summary
        logger.info(f"[Pydantic] Modèle de validation chargé: {_get_validation_summary()}")
    except Exception as e:
        logger.warning(f"[Pydantic] Échec du chargement: {e}")

# ── P1.5 : Vérification des prérequis au démarrage ─────────────────────────────
from verify_prerequisites import verify_prerequisites

# Configuration du chemin du frontend
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Logging vers fichier (lisible sans console) ───────────────────────────────
LOG_PATH = os.path.join(BASE_DIR, 'server.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler()  # garde aussi la console si disponible
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Serveur démarré — logs dans : {LOG_PATH}")

# ── P1.4 : Vérification disponibilité de tonality_detector ─────────────────────
_tonality_detector_status = {
    'available': False,
    'error': None,
}
try:
    from tonality_detector import detect_tonality as _detect_tonality
    _tonality_detector_status['available'] = True
    logger.info("[P1.4] tonality_detector disponible")
except ImportError as e:
    _tonality_detector_status['error'] = str(e)
    logger.warning(f"[P1.4] tonality_detector indisponible : {e}")
except Exception as e:
    _tonality_detector_status['error'] = str(e)
    logger.warning(f"[P1.4] tonality_detector erreur : {e}")
FRONTEND_DIR = os.path.join(BASE_DIR, '..', 'frontend')

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='/static')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max

ALLOWED_EXTENSIONS = {'flac', 'wav', 'mp3'}
pipeline = TranscriptionPipeline()


def allowed_file(filename):
    """Vérifie si l'extension du fichier est autorisée."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_temp_dir(prefix):
    """Crée un répertoire temporaire avec un prefix unique."""
    dir_name = tempfile.mkdtemp(prefix=prefix + '_')
    return dir_name


@app.route('/', methods=['GET'])
def index():
    """Serve l'interface web."""
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.route('/<path:path>', methods=['GET'])
def serve_static(path):
    """Serve les fichiers statiques (CSS, JS, images)."""
    return send_from_directory(FRONTEND_DIR, path)


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'version': '3.0.0'
    }), 200


@app.route('/api/device-info', methods=['GET'])
def device_info():
    """Retourne les informations détaillées sur le dispositif de calcul.
    Cette route était déjà utilisée par certaines parties du frontend.
    """
    import torch
    device = 'cpu'
    name = 'Processeur (CPU)'
    try:
        if torch.cuda.is_available():
            device = 'cuda'
            name = torch.cuda.get_device_name(0)
        elif hasattr(torch, 'xpu') and torch.xpu.is_available():
            device = 'xpu'
            name = torch.xpu.get_device_name(0) if hasattr(torch.xpu, 'get_device_name') else 'Intel XPU'
    except Exception:
        pass
    return jsonify({
        'device': device,
        'name': name
    }), 200

# ── Stockage temporaire des jobs de transcription (thread-safe) ─────────────
import concurrent.futures
import time as _time
from queue import Queue

# Stockage des jobs
_transcription_jobs = {}  # job_id -> {'status': str, 'result': dict, 'error': str, 'progress': float, 'message': str, 'step': str, 'created_at': float}
_jobs_lock = __import__('threading').Lock()

# Stockage des queues SSE par job (pour streaming)
_sse_queues = {}  # job_id -> Queue


def _cleanup_old_jobs():
    """Nettoyer les jobs anciens de 15 minutes (le pipeline Transkun peut mettre 5-10 min)."""
    now = _time.time()
    with _jobs_lock:
        to_remove = [jid for jid, job in _transcription_jobs.items()
                     if now - job['created_at'] > 900]
        for jid in to_remove:
            del _transcription_jobs[jid]


def _run_pipeline_thread(job_id, input_path, output_dir, options):
    """Thread qui exécute le pipeline de transcription."""
    def _update_progress(progress, message, step='transcription'):
        """Met à jour la progression du job."""
        with _jobs_lock:
            if job_id in _transcription_jobs:
                _transcription_jobs[job_id]['progress'] = progress
                _transcription_jobs[job_id]['message'] = message
                _transcription_jobs[job_id]['step'] = step
                _transcription_jobs[job_id]['status'] = 'running'

    # Étape 1: Initialisation
    _update_progress(0.05, '🔍 Initialisation du modèle...', 'init')
    
    # Étape 2: Chargement audio
    _update_progress(0.10, '🎵 Chargement de l\'audio...', 'load_audio')
    
    # Étape 3: Prétraitement (Demucs)
    _update_progress(0.15, '🔊 Prétraitement audio...', 'demucs')
    
    try:
        # Exécuter le pipeline avec callbacks de progression
        result = pipeline.run(
            input_path, 
            output_dir, 
            options=options,
            progress_cb=_update_progress
        )
        output_files = {}
        if result.get('midi_path'):
            output_files['midi'] = result['midi_path']
        if result.get('xml_path'):
            output_files['xml'] = result['xml_path']

        with _jobs_lock:
            _transcription_jobs[job_id]['status'] = 'done'
            _transcription_jobs[job_id]['result'] = {
                'success': True,
                'score_data': result,
                'output_files': output_files,
                'processing_time': 0.0,
            }
            _transcription_jobs[job_id]['progress'] = 1.0
            _transcription_jobs[job_id]['message'] = '✅ Transcription terminée avec succès!'
            _transcription_jobs[job_id]['step'] = 'export'
    except Exception as e:
        logger.exception(f"[Transcribe] Pipeline error for job {job_id}")
        with _jobs_lock:
            _transcription_jobs[job_id]['status'] = 'error'
            _transcription_jobs[job_id]['error'] = str(e)
            _transcription_jobs[job_id]['message'] = f'❌ Transcription échouée: {e}'
@app.route('/api/device', methods=['GET'])
def device_compat():
    """Alias compatible avec le frontend qui attend `/api/device`.
    Retourne les mêmes champs que `/api/device-info` mais sous les noms
    attendus par `app.js` (device_type, device_name, etc.)."""
    import torch
    device_type = 'cpu'
    device_name = 'Processeur (CPU)'
    try:
        if torch.cuda.is_available():
            device_type = 'cuda'
            device_name = torch.cuda.get_device_name(0)
        elif hasattr(torch, 'xpu') and torch.xpu.is_available():
            device_type = 'xpu'
            device_name = torch.xpu.get_device_name(0) if hasattr(torch.xpu, 'get_device_name') else 'Intel XPU'
    except Exception:
        pass
    return jsonify({
        'device_type': device_type,
        'device_name': device_name,
        # Les champs supplémentaires sont fournis pour garder la compatibilité future
        'total_memory_gb': None,
        'free_memory_gb': None,
        'compute_capability': None,
        'driver_version': None,
        'cpu_threads': None,
        'gpu_memory_fraction': None,
        'batch_sizes': None,
        'memory_stats': None,
    }), 200


@app.route('/api/gpu-status', methods=['GET'])
def gpu_status():
    """Retourne un statut détaillé du GPU pour diagnostic."""
    import torch
    
    info = {
        'pytorch_version': torch.__version__,
        'cuda_available': False,
        'xpu_available': False,
        'device': 'cpu',
        'device_name': 'Processeur (CPU)',
        'gpu_recommended': False,
        'warnings': []
    }
    
    # Vérification CUDA
    try:
        if torch.cuda.is_available():
            info['cuda_available'] = True
            info['device'] = 'cuda'
            info['device_name'] = torch.cuda.get_device_name(0)
            info['gpu_recommended'] = True
            info['warnings'].append('GPU NVIDIA détecté - accélération CUDA activée.')
            return jsonify(info), 200
    except Exception:
        pass
    
    # Vérification Intel XPU
    if hasattr(torch, 'xpu'):
        try:
            if torch.xpu.is_available():
                info['xpu_available'] = True
                info['device'] = 'xpu'
                info['device_name'] = torch.xpu.get_device_name(0) if hasattr(torch.xpu, 'get_device_name') else 'Intel ARC GPU'
                info['gpu_recommended'] = True
                info['warnings'].append('GPU Intel ARC détecté - accélération IPEX activée.')
                return jsonify(info), 200
        except Exception:
            pass
    
    # Aucun GPU
    info['warnings'].append(
        'Aucun GPU détecté. Pour utiliser votre GPU Intel ARC A770:'
    )
    info['warnings'].append(
        '1. Installez IPEX: pip install intel-extension-for-pytorch'
    )
    info['warnings'].append(
        '2. Ou utilisez le wheel PyTorch Intel: pip install torch --index-url https://download.pytorch.org/whl/xpu'
    )
    info['warnings'].append(
        '3. Redémarrez le serveur après l\'installation.'
    )
    
    return jsonify(info), 200


@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    """Upload audio file et lance la transcription."""
    # Vider le fichier server.log à chaque nouvelle transcription
    try:
        import logging
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.FileHandler):
                handler.stream.seek(0)
                handler.stream.truncate()
    except Exception:
        pass

    # Vérifier présence du fichier (accepte 'file' ou 'audio')
    if 'file' not in request.files and 'audio' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files.get('file') or request.files.get('audio')

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({
            'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
        }), 400

    # ── Extraire les options de la requête HTTP ───────────────────────
    form_dict = {
        'transcriber': request.form.get('transcriber', 'piano_transcription'),
        'preset': request.form.get('preset', 'standard'),
        'use_demucs': request.form.get('use_demucs', 'false') == 'true',
        'onset_threshold': float(request.form.get('onset_threshold', 0.5)),
        'frame_threshold': float(request.form.get('frame_threshold', '0.1')),
        'offset_threshold': float(request.form.get('offset_threshold', '0.3')),
        'minimum_note_duration': int(request.form.get('minimum_note_duration', 50)),
        'time_sig': request.form.get('time_sig', '4/4'),
        'key_sig': request.form.get('key_sig', 'C'),
        'detect_tempo': request.form.get('detect_tempo', 'true') == 'true',
        'detect_meter': request.form.get('detect_meter', 'true') == 'true',
        'detect_key': request.form.get('detect_key', 'true') == 'true',
        'quantization_level': request.form.get('quantization_level', 'standard'),
        'remove_short_notes': request.form.get('remove_short_notes', 'false') == 'true',
        'merge_near_notes': request.form.get('merge_near_notes', 'false') == 'true',
        'merge_gap_ms': int(request.form.get('merge_gap_ms', 30)),
        'split_hands': request.form.get('split_hands', 'false') == 'true',
        'enable_rubato': request.form.get('enable_rubato', 'false') == 'true',
        'enable_triplets': request.form.get('enable_triplets', 'false') == 'true',
        'quantization_sensitivity': request.form.get('quantization_sensitivity'),
        'harmonic_filter': request.form.get('harmonic_filter', 'classical-strong'),  # défaut: classical-strong pour Chopin/Nocturnes/Mazurkas
        'strict_mode': request.form.get('strict_mode', 'false') == 'true',
    }
    # Convertir quantization_sensitivity en float ou None
    qs = form_dict.get('quantization_sensitivity')
    if qs and qs.strip():
        try:
            form_dict['quantization_sensitivity'] = float(qs)
        except (ValueError, TypeError):
            form_dict['quantization_sensitivity'] = None
    else:
        form_dict['quantization_sensitivity'] = None
    tempo_override = request.form.get('tempo')
    if tempo_override:
        form_dict['tempo'] = float(tempo_override)

    # ── Pydantic validation des options ───────────────────────────────
    try:
        if PYDANTIC_AVAILABLE and _validate_transcription_options:
            validated_options, errors = _validate_transcription_options(form_dict)
            if errors:
                return jsonify({'error': 'Validation failed', 'details': errors}), 422
            options = validated_options
        else:
            # Fallback sans validation Pydantic
            options = form_dict
    except FileNotFoundError as e:
        logger.error(f"Fichier introuvable après validation : {e}")
        return jsonify({'error': f'File not found: {str(e)}'}), 404
    except Exception as e:
        logger.exception("[API ERROR] Traceback complet :")
        return jsonify({'error': f'Transcription failed: {str(e)}'}), 500

    # ── Créer job ID et dossier temporaire ──────────────────────────────
    job_id = str(uuid.uuid4())[:8]
    upload_dir = get_temp_dir(f'audio_{job_id}')
    output_dir = get_temp_dir(f'output_{job_id}')

    # ── Initialiser le job dans le stockage ───────────────────────────
    with _jobs_lock:
        _transcription_jobs[job_id] = {
            'status': 'pending',
            'result': None,
            'error': None,
            'progress': 0.0,
            'message': 'En attente...',
            'created_at': _time.time(),
        }

    try:
        # Sauvegarder le fichier uploadé
        input_path = os.path.join(upload_dir, file.filename)
        file.save(input_path)

        # Mettre à jour le statut du job
        with _jobs_lock:
            _transcription_jobs[job_id]['status'] = 'running'
            _transcription_jobs[job_id]['message'] = 'Transcription en cours...'
            _transcription_jobs[job_id]['progress'] = 0.1

        # Lancer le pipeline dans un thread séparé
        import threading
        thread = threading.Thread(
            target=_run_pipeline_thread,
            args=(job_id, input_path, output_dir, options),
            daemon=True,
        )
        thread.start()

        # Retourner immédiatement un jobId au frontend
        return jsonify({
            'success': True,
            'jobId': job_id,
            'status': 'running',
            'message': 'Transcription démarrée',
        }), 200

    except FileNotFoundError as e:
        logger.error(f"Fichier introuvable : {e}")
        with _jobs_lock:
            _transcription_jobs[job_id]['status'] = 'error'
            _transcription_jobs[job_id]['error'] = str(e)
        return jsonify({'error': f'File not found: {str(e)}'}), 404
    except Exception as e:
        logger.exception("[API ERROR] Traceback complet :")
        with _jobs_lock:
            _transcription_jobs[job_id]['status'] = 'error'
            _transcription_jobs[job_id]['error'] = str(e)
        return jsonify({'error': f'Transcription failed: {str(e)}'}), 500


@app.route('/api/transcribe-progress/<job_id>', methods=['GET'])
def transcribe_progress(job_id):
    """Endpoint SSE pour la progression de transcription.
    
    Retourne un stream SSE avec les événements de progression.
    Le frontend se connecte via EventSource à cette URL.
    """
    # Nettoyer les vieux jobs
    _cleanup_old_jobs()
    
    if job_id not in _transcription_jobs:
        return jsonify({'error': 'Job not found'}), 404

    def _event_stream():
        """Génère les événements SSE."""
        import json
        import time
        import sys
        import platform
        
        last_status = None
        last_heartbeat = time.time()
        
        while True:
            job = _transcription_jobs.get(job_id)
            if job is None:
                # Job supprimé (expiration)
                yield "event: done\ndata: " + json.dumps({"message": "Job expiré"}) + "\n\n"
                if sys.platform != 'win32':
                    sys.stdout.flush()
                break
            
            status = job['status']
            progress = job.get('progress', 0)
            message = job.get('message', '')
            
            # Ne renvoyer un événement que si le statut a changé
            current_status = (status, progress, message)
            if current_status == last_status:
                # Même statut, on attend un peu avant de re-vérifier
                time.sleep(0.5)
                # Heartbeat toutes les 15 secondes (commentaire pour éviter les problèmes)
                if time.time() - last_heartbeat > 15:
                    last_heartbeat = time.time()
                continue
            
            last_status = current_status
            
            # Déterminer le step à partir du status
            step_map = {
                'pending': 'init',
                'running': 'transcription',
                'done': 'export',
                'error': 'error',
            }
            step = step_map.get(status, 'unknown')
            
            status_event = {
                "type": "status",
                "step": step,
                "message": message,
                "progress": progress,
                "status": status,
            }
            yield "event: status\ndata: " + json.dumps(status_event) + "\n\n"
            if sys.platform != 'win32':
                sys.stdout.flush()
            
            if status == 'done':
                yield "event: done\ndata: " + json.dumps({"message": "Transcription terminée"}) + "\n\n"
                if sys.platform != 'win32':
                    sys.stdout.flush()
                break
            elif status == 'error':
                error_event = {"message": job.get('error', 'Erreur inconnue')}
                yield "event: error\ndata: " + json.dumps(error_event) + "\n\n"
                if sys.platform != 'win32':
                    sys.stdout.flush()
                break
            
            # Pause courte pour ne pas surcharger le CPU
            time.sleep(0.5)
    
    from flask import Response
    return Response(
        _event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/transcribe/result/<job_id>', methods=['GET'])
def transcribe_result(job_id):
    """Récupère le résultat final d'une transcription."""
    try:
        _cleanup_old_jobs()
        
        with _jobs_lock:
            job = _transcription_jobs.get(job_id)
        
        if job is None:
            return jsonify({'error': 'Job not found or expired'}), 404
        
        if job['status'] == 'done':
            # Le résultat peut contenir des objets numpy non-sérialisables
            # jsonify() peut échouer avec des types non-JSON
            result = job['result']
            if result.get('success'):
                score_data = result.get('score_data', {})
                # Vérifier que score_data est sérialisable
                try:
                    json.dumps(score_data)
                except (TypeError, ValueError):
                    logger.warning("[Result] score_data non sérialisable JSON, conversion...")
                    # Si non sérialisable, on retourne un message d'erreur structuré
                    return jsonify({
                        'success': False,
                        'error': 'Le résultat contient des données non-sérialisables. Vérifiez les logs du serveur.',
                        'job_status': 'serialization_error'
                    }), 500
                return jsonify(result), 200
            else:
                return jsonify(result), 500
        elif job['status'] == 'error':
            error_msg = job.get('error', 'Erreur inconnue')
            logger.error(f"[Result] Job {job_id} en erreur: {error_msg}")
            return jsonify({'error': error_msg, 'job_status': 'error'}), 500
        else:
            return jsonify({'status': job['status']}), 202
    except Exception as e:
        logger.exception(f"[Result] Exception pour job {job_id}: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}', 'job_status': 'exception'}), 500


@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    """Nettoie les fichiers temporiques."""
    # Nettoyer aussi les jobs expirés
    _cleanup_old_jobs()
    return jsonify({'status': 'ok'}), 200


@app.route('/api/status/<job_id>', methods=['GET'])
def status(job_id):
    """Vérifie le statut d'un job (toujours completed en V3 synchrone)."""
    return jsonify({
        'job_id': job_id,
        'status': 'completed',
        'error': None
    }), 200


@app.route('/api/export-midi', methods=['POST'])
def export_midi():
    """Exporte la partition en fichier MIDI."""
    try:
        score_data = request.get_json()
        if not score_data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Utiliser midi_parser pour créer le MIDI
        from midi_parser import score_to_midi
        import tempfile
        import os
        
        fd, temp_path = tempfile.mkstemp(suffix='.mid')
        os.close(fd)
        try:
            score_to_midi(score_data, temp_path)
            with open(temp_path, 'rb') as f:
                midi_bytes = f.read()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
        import io
        from flask import send_file
        return send_file(
            io.BytesIO(midi_bytes),
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name='partition_piano.mid'
        )
    except Exception as e:
        return jsonify({'error': f'Export MIDI failed: {str(e)}'}), 500


@app.route('/api/export-musicxml', methods=['POST'])
def export_musicxml():
    """Exporte la partition en fichier MusicXML (.xml)."""
    try:
        score_data = request.get_json()
        if not score_data:
            return jsonify({'error': 'No data provided'}), 400

        # Utiliser musicxml_exporter pour générer le fichier en mémoire
        import tempfile
        import io
        from musicxml_exporter import export_musicxml

        # Créer un fichier temporaire en mémoire
        fd, temp_path = tempfile.mkstemp(suffix='.xml')
        os.close(fd)
        try:
            export_musicxml(score_data, temp_path)
            with open(temp_path, 'rb') as f:
                xml_bytes = f.read()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        return send_file(
            io.BytesIO(xml_bytes),
            mimetype='application/vnd.recordare.musicxml',
            as_attachment=True,
            download_name='partition_piano.musicxml',
        )
    except Exception as e:
        logger.exception('[Export MusicXML] Erreur lors de la génération du fichier')
        return jsonify({'error': f'Export MusicXML failed: {str(e)}'}), 500


@app.route('/api/midi/<job_id>', methods=['GET'])
def get_midi(job_id):
    """Télécharge le fichier MIDI généré."""
    # Chercher le fichier .mid dans le dossier output
    output_base = tempfile.gettempdir()
    search_dirs = [d for d in os.listdir(output_base)
                   if d.startswith(f'output_{job_id}') or d.startswith(f'output_')]

    for d in search_dirs:
        output_path = os.path.join(output_base, d)
        if os.path.isdir(output_path):
            for f in os.listdir(output_path):
                if f.endswith('.mid'):
                    file_path = os.path.join(output_path, f)
                    return send_file(
                        file_path,
                        as_attachment=True,
                        download_name=f'{job_id}.mid'
                    )

    return jsonify({'error': 'MIDI file not found'}), 404


@app.route('/api/score/<job_id>', methods=['GET'])
def get_score(job_id):
    """Télécharge le fichier MusicXML généré."""
    # Chercher le fichier .xml dans le dossier output
    output_base = tempfile.gettempdir()
    search_dirs = [d for d in os.listdir(output_base)
                   if d.startswith(f'output_{job_id}') or d.startswith(f'output_')]

    for d in search_dirs:
        output_path = os.path.join(output_base, d)
        if os.path.isdir(output_path):
            for f in os.listdir(output_path):
                if f.endswith('.xml'):
                    file_path = os.path.join(output_path, f)
                    return send_file(
                        file_path,
                        as_attachment=True,
                        download_name=f'{job_id}.xml'
                    )

    return jsonify({'error': 'Score file not found'}), 404


# ── P1.5 : Exécution de la vérification des prérequis au démarrage ─────────────
_prereq_results, _has_critical = verify_prerequisites()
if _has_critical:
    logger.warning("[P1.5] ⚠️ Des prérequis critiques ne sont pas satisfaits — l'application peut fonctionner de manière dégradée")
else:
    logger.info("[P1.5] ✅ Prérequis validés — démarrage de l'application")

if __name__ == '__main__':
    print("\n🎵 Audio-to-Sheet Music v3.0.0")
    print("📡 Server: http://localhost:5000")
    print("📖 API Docs:")
    print("   GET    /                    - Interface web")
    print("   GET    /api/health          - Health check")
    print("   GET    /api/device-info     - Device info")
    print("   POST   /api/transcribe      - Transcription audio")
    print("   POST   /api/cleanup         - Cleanup temp files")
    print("   POST   /api/export-midi     - Export MIDI")
    print("   POST   /api/export-musicxml - Export MusicXML")
    print("   GET    /api/status          - Check job status")
    print("   GET    /api/midi            - Download MIDI file")
    print("   GET    /api/score           - Download MusicXML file")
    app.run(host='0.0.0.0', port=5000, debug=False)
