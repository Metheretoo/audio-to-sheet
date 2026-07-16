"""audio-to-sheet music v3 — API Flask"""
import os
import uuid
import tempfile
import json
import logging
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from transcriber import TranscriptionPipeline

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

# ---------------------------------------------------------------------------
# Compatibilité avec le frontend actuel (fetch('/api/device'))
# ---------------------------------------------------------------------------
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

    # Créer job ID et dossier temporaire
    job_id = str(uuid.uuid4())[:8]
    upload_dir = get_temp_dir(f'audio_{job_id}')
    output_dir = get_temp_dir(f'output_{job_id}')

    try:
        # Sauvegarder le fichier uploadé
        input_path = os.path.join(upload_dir, file.filename)
        file.save(input_path)

        # Extraire les options de la requête HTTP
        onset_threshold_val = float(request.form.get('onset_threshold', 0.5))
        # BUG CORRIGÉ (v4.2) : frame_threshold restait figé à 0.25 quel que soit
        # le slider "Sensibilité" (qui ne pilote en réalité que onset_threshold).
        # Résultat : à mesure que l'utilisateur déplaçait le curseur, onset et
        # frame_threshold se déséquilibraient de plus en plus, ce qui fragmente/
        # duplique les notes (une des causes probables de la "soupe de notes").
        # On dérive désormais frame_threshold proportionnellement à
        # onset_threshold (ratio ~1/3, cohérent avec les valeurs par défaut
        # documentées de la librairie : onset=0.3 / frame=0.1).
        default_frame_threshold = round(min(max(onset_threshold_val / 3.0, 0.05), 0.5), 3)

        options = {
            'transcriber': request.form.get('transcriber', 'piano_transcription'),
            'preset': request.form.get('preset', 'standard'),
            'use_demucs': request.form.get('use_demucs', 'false') == 'true',
            'onset_threshold': onset_threshold_val,
            'frame_threshold': float(request.form.get('frame_threshold', default_frame_threshold)),
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
        }
        tempo_override = request.form.get('tempo')
        if tempo_override:
            options['tempo'] = float(tempo_override)
            
        # Exécuter le pipeline de transcription avec les options
        result = pipeline.run(input_path, output_dir, options=options)

        # Le frontend (app.js handleTranscriptionResult) attend le format :
        # { success: true, score_data: { measures: [...], tempo: ..., ... } }
        # On enveloppe donc le score_data dans la clé "score_data".
        result['jobId'] = job_id  # jobId conservé dans score_data pour currentJobId

        output_files = {}
        if result.get('midi_path'):
            output_files['midi'] = result['midi_path']
        if result.get('xml_path'):
            output_files['xml'] = result['xml_path']

        return jsonify({
            'success': True,
            'score_data': result,
            'output_files': output_files,
            'processing_time': 0.0,
        }), 200

    except FileNotFoundError as e:
        logger.error(f"Fichier introuvable : {e}")
        return jsonify({'error': f'File not found: {str(e)}'}), 404
    except Exception as e:
        logger.exception("[API ERROR] Traceback complet :")
        return jsonify({'error': f'Transcription failed: {str(e)}'}), 500


@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    """Nettoie les fichiers temporiques."""
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


if __name__ == '__main__':
    print("🎵 Audio-to-Sheet Music v3.0.0")
    print("📡 Server: http://localhost:5000")
    print("📖 API Docs:")
    print("   GET    /              - Interface web")
    print("   GET    /api/health    - Health check")
    print("   GET    /api/device-info - Device info")
    print("   POST   /api/transcribe - Transcription audio")
    print("   POST   /api/cleanup   - Cleanup temp files")
    print("   POST   /api/export-midi - Export MIDI")
    print("   GET    /api/status    - Check job status")
    print("   GET    /api/midi      - Download MIDI file")
    print("   GET    /api/score     - Download MusicXML file")
    app.run(host='0.0.0.0', port=5000, debug=False)
