"""
fastapi_transcribe.py — Endpoint transcribe FastAPI avec SSE progress (Phase 1.7b)
                        + Validation Pydantic (Phase 1.8)

Migration de /api/transcribe depuis app.py (Flask) vers FastAPI async.
Intègre le SSE progress pour la progression temps réel.
"""
import os
import sys
import uuid
import tempfile
import asyncio
import logging
import io
import threading
from typing import Optional

# ── Dépendances FastAPI (optionnelles) ────────────────────────────────────────
try:
    from fastapi import UploadFile, File, Form
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)


# ── SSE Progress Manager import ──────────────────────────────────────────────
if FASTAPI_AVAILABLE:
    try:
        from fastapi_app import progress_manager, sse_format
    except ImportError:
        progress_manager = None
        sse_format = None
        logger.warning("[P1.7b] Impossible d'importer SSE progress manager")
else:
    progress_manager = None
    sse_format = None

# ── Models Pydantic import (Phase 1.8) ───────────────────────────────────────
if FASTAPI_AVAILABLE:
    try:
        from models import TranscriptionOptions, validate_options, apply_preset, PRESET_VALUES
        MODELS_AVAILABLE = True
    except ImportError:
        MODELS_AVAILABLE = False
        logger.warning("[P1.8] Impossible d'importer models Pydantic")
else:
    MODELS_AVAILABLE = False


# ── Constants ────────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {'flac', 'wav', 'mp3'}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB


def allowed_file(filename: str) -> bool:
    """Vérifie si l'extension du fichier est autorisée."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Transcribe endpoint ──────────────────────────────────────────────────────

async def transcribe_fastapi(
    file: UploadFile = File(...),
    transcriber: str = 'piano_transcription',
    preset: str = 'standard',
    use_demucs: bool = False,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.1,
    offset_threshold: float = 0.3,
    minimum_note_duration: int = 50,
    time_sig: str = '4/4',
    key_sig: str = 'C',
    detect_tempo: bool = True,
    detect_meter: bool = True,
    detect_key: bool = True,
    quantization_level: str = 'standard',
    remove_short_notes: bool = False,
    merge_near_notes: bool = False,
    merge_gap_ms: int = 30,
    split_hands: bool = False,
    enable_rubato: bool = False,
    enable_triplets: bool = False,
    strict_mode: bool = False,
    tempo: Optional[float] = None,
):
    """
    Endpoint FastAPI pour la transcription audio → partition.
    
    Retourne d'abord un job_id, puis le frontend peut souscrire au SSE progress.
    """
    if not FASTAPI_AVAILABLE:
        return {"error": "FastAPI non disponible"}
    
    # Vérifier le fichier
    if not file.filename:
        return {"error": "No file provided"}
    
    if not allowed_file(file.filename):
        return {"error": f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"}
    
    # ── Validation Pydantic (Phase 1.8) ────────────────────────────────
    options_data = {
        'transcriber': transcriber,
        'preset': preset,
        'use_demucs': use_demucs,
        'onset_threshold': onset_threshold,
        'frame_threshold': frame_threshold,
        'offset_threshold': offset_threshold,
        'minimum_note_duration': minimum_note_duration,
        'time_sig': time_sig,
        'key_sig': key_sig,
        'detect_tempo': detect_tempo,
        'detect_meter': detect_meter,
        'detect_key': detect_key,
        'quantization_level': quantization_level,
        'remove_short_notes': remove_short_notes,
        'merge_near_notes': merge_near_notes,
        'merge_gap_ms': merge_gap_ms,
        'split_hands': split_hands,
        'enable_rubato': enable_rubato,
        'enable_triplets': enable_triplets,
        'strict_mode': strict_mode,
    }
    if tempo:
        options_data['tempo'] = float(tempo)
    
    validated_options = None
    validation_errors = []
    
    if MODELS_AVAILABLE:
        validated_options, validation_errors = validate_options(options_data)
        if validation_errors:
            msg = "Options invalides:\n" + "\n".join(validation_errors)
            logger.warning(f"[P1.8] Validation échouée: {msg}")
            return {"error": msg}
        logger.info(f"[P1.8] Options validées: {validated_options.summary()}")
    else:
        # Fallback sans validation Pydantic
        logger.warning("[P1.8] Validation Pydantic indisponible, fallback brut")
    
    # Créer job ID et dossiers temporaires
    job_id = str(uuid.uuid4())[:8]
    upload_dir = tempfile.mkdtemp(prefix=f'audio_{job_id}_')
    output_dir = tempfile.mkdtemp(prefix=f'output_{job_id}_')
    
    # Souscrire au SSE progress
    sse_queue = await progress_manager.subscribe(job_id) if progress_manager else None
    
    try:
        # ── Publier début de transcription ───────────────────────────────
        await _publish_progress(job_id, 'status', f'Démarrage de la transcription...', 0.0, 'init')
        
        # ── Sauvegarder le fichier uploadé ────────────────────────────────
        input_path = os.path.join(upload_dir, file.filename)
        content = await file.read()
        with open(input_path, 'wb') as f:
            f.write(content)
        
        # ── Construire les options finales ────────────────────────────────
        options = validated_options.to_dict() if validated_options else options_data
        
        # ── Publier étape 1 : Prétraitement ───────────────────────────────
        await _publish_progress(job_id, 'status', 'Prétraitement audio...', 0.1, 'preprocess')
        
        # ── Lancer le pipeline en thread séparé avec callback SSE ───────
        # Le pipeline TranscriptionPipeline accepte un progress_cb qui publie
        # des événements SSE depuis l'intérieur de chaque étape.
        result = None
        error = None
        
        # ── Thread dédié pour le pipeline + SSE ──────────────────────────
        # Le pipeline doit être exécuté dans un thread avec SON PROPRE event loop.
        # Chaque étape du pipeline appelle progress_cb(step, message, progress)
        # qui envoie directement un événement SSE via sse_queue.
        
        sse_queue = asyncio.Queue()  # queue pour ce job
        
        def _run_pipeline_sync(progress_cb):
            """Pipeline synchrone avec progress_cb. Exécuté dans Thread."""
            try:
                import importlib
                transcriber_mod = importlib.import_module('transcriber')
                TranscriptionPipeline = transcriber_mod.TranscriptionPipeline
                pipeline = TranscriptionPipeline()
                return pipeline.run(input_path, output_dir, options=options, progress_cb=progress_cb)
            except Exception as e:
                logger.exception(f"[Pipeline] Error in _run_pipeline_sync: {e}")
                raise
        
        def _progress_cb_sync(step: str, message: str, progress: float):
            """Callback synchrone → écrit directement dans la queue SSE."""
            event = {
                'type': 'status',
                'message': message,
                'progress': progress,
                'step': step,
            }
            try:
                sse_queue.put_nowait(event)
            except Exception as e:
                logger.debug(f"[SSE] queue put error: {e}")
        
        def _progress_cb_done():
            """Appelé quand le pipeline est terminé → marque la fin."""
            try:
                sse_queue.put_nowait({'type': 'done', 'message': 'done'})
            except Exception:
                pass
        
        # Lancer le pipeline dans un Thread (sans event loop)
        pipeline_thread = None
        pipeline_result = [None]
        pipeline_error = [None]
        
        def _run_and_capture():
            try:
                pipeline_result[0] = _run_pipeline_sync(_progress_cb_sync)
            except Exception as e:
                pipeline_error[0] = str(e)
        
        pipeline_thread = threading.Thread(target=_run_and_capture, daemon=True)
        pipeline_thread.start()
        
        # ── Boucle SSE : envoie les events de la queue vers le frontend ──
        heartbeat_count = 0
        while True:
            try:
                event = await asyncio.wait_for(sse_queue.get(), timeout=15.0)
                await _publish_progress(
                    job_id, event.get('type', 'status'),
                    event.get('message', ''),
                    event.get('progress'),
                    event.get('step'),
                )
                if event.get('type') == 'done':
                    break
            except asyncio.TimeoutError:
                heartbeat_count += 1
                await _publish_progress(job_id, 'heartbeat', 'keepalive', None, None)
                if heartbeat_count > 20:
                    break
        
        # Attendre la fin du pipeline
        pipeline_thread.join(timeout=300)
        
        result = pipeline_result[0]
        error = pipeline_error[0]
        
        # ── Publier fin de transcription ──────────────────────────────────
        if result:
            await _publish_progress(job_id, 'status', 'Export des fichiers...', 0.9, 'export')
            
            midi_path = result.get('midi_path')
            xml_path = result.get('xml_path')
            
            output_files = {}
            if midi_path and os.path.exists(midi_path):
                output_files['midi'] = midi_path
            if xml_path and os.path.exists(xml_path):
                output_files['xml'] = xml_path
            
            await _publish_progress(job_id, 'done', 'Transcription terminée avec succès!', 1.0, 'done')
            
            return {
                'success': True,
                'score_data': result,
                'output_files': output_files,
                'processing_time': 0.0,
                'jobId': job_id,
            }
        else:
            await _publish_progress(job_id, 'error', f'Transcription échouée: {error}', None, 'error')
            return {'error': f'Transcription failed: {error}'}
    
    finally:
        if sse_queue:
            await progress_manager.unsubscribe(job_id)
        try:
            import shutil
            shutil.rmtree(upload_dir, ignore_errors=True)
        except Exception:
            pass


async def _publish_progress(job_id: str, event_type: str, message: str,
                            progress: float = None, step: str = None):
    """Publie un événement de progression SSE."""
    if progress_manager:
        try:
            await asyncio.wait_for(
                progress_manager.publish(job_id, {
                    'type': event_type,
                    'message': message,
                    'progress': progress,
                    'step': step,
                }),
                timeout=1.0
            )
        except Exception as e:
            logger.debug(f"[P1.7b] SSE publish error: {e}")


# ── SSE streaming response ──────────────────────────────────────────────────

async def sse_progress_stream(job_id: str):
    """Génère le stream SSE pour la progression."""
    if not progress_manager:
        return
    
    try:
        queue = await progress_manager.subscribe(job_id)
        heartbeat_count = 0
        
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield sse_format(event.get('type', 'message'), event)
                
                if event.get('type') in ('done', 'error'):
                    break
            except asyncio.TimeoutError:
                heartbeat_count += 1
                yield sse_format('heartbeat', {'time': __import__('time').time()})
                if heartbeat_count > 20:
                    break
    finally:
        await progress_manager.unsubscribe(job_id)