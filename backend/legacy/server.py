"""
AudioScore — Serveur Flask + SSE pour transcription temps réel
Remplace l'ancien serveur avec progression simulée par vraie progression.
"""
from __future__ import annotations

import os
import uuid
import threading
import logging
import json
import asyncio
from pathlib import Path
from typing import Optional
from functools import wraps

from flask import Flask, request, jsonify, Response, send_file, send_from_directory
from flask_cors import CORS

# Imports locaux (legacy/old/ — fichiers obsolètes déplacés)
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'old'))

from config import get_config, AppConfig
from device_manager import get_device_manager, print_device_summary
from model_cache import get_model_cache
from pipeline import (
    AsyncPipeline,
    SSEPipeline,
    PipelineProgress,
    PipelineResult,
    PipelineStage,
    run_transcription_sync,
)

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Constantes de validation ──────────────────────────────────────────────────
ALLOWED_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.aac', '.wma'}
MAX_AUDIO_DURATION_SECONDS = 300  # 5 minutes max
MAX_FILE_SIZE_MB = 100

# ─── Création de l'application Flask ───────────────────────────────────────────

def create_app(config: Optional[AppConfig] = None) -> Flask:
    """Factory pattern pour créer l'app Flask"""
    app = Flask(__name__)

    # Charger la config
    if config is None:
        config = get_config()

    app.config["AUDIOSCORE_CONFIG"] = config

    # CORS
    CORS(app, origins=config.server.cors_origins)

    # Limite taille upload
    app.config["MAX_CONTENT_LENGTH"] = config.server.max_content_length

    # Dossiers
    config.ensure_dirs()

    # Initialiser device manager
    device_manager = get_device_manager()
    device_manager.apply_config(config.device)
    print_device_summary()

    # Initialiser model cache
    model_cache = get_model_cache()
    model_cache.apply_config(config.model_cache)

    # ─── Routes API ─────────────────────────────────────────────────────────────

    @app.route("/api/health", methods=["GET"])
    def health_check():
        """Health check endpoint"""
        dm = get_device_manager()
        mc = get_model_cache()
        return jsonify({
            "status": "ok",
            "version": "3.0.0",
            "device": dm.device_type,
            "device_name": dm.device_info.device_name,
            "gpu_available": dm.is_gpu,
            "models_cached": mc.get_stats()["cached_models"],
            "memory": dm.get_memory_stats(),
        })

    @app.route("/api/config", methods=["GET"])
    def get_config_endpoint():
        """Retourne la configuration actuelle (sans chemins sensibles)"""
        cfg = app.config["AUDIOSCORE_CONFIG"]
        return jsonify({
            "transcriber": {
                "default": cfg.transcriber.default,
                "available": list(cfg.transcriber.models.keys()),
            },
            "demucs": {
                "enabled": cfg.demucs.enabled,
                "models": ["htdemucs", "htdemucs_ft", "mdx_extra"],
            },
            "quantization": {
                "default": cfg.quantization.default,
                "levels": list(cfg.quantization.levels.keys()),
            },
            "hand_split": {
                "methods": ["fixed", "dynamic", "ml"],
                "default": cfg.hand_split.method,
            },
            "export": {
                "formats": cfg.export.formats,
            },
            "frontend": {
                "languages": cfg.frontend.supported_languages,
                "default_language": cfg.frontend.default_language,
            },
        })

    @app.route("/api/models/status", methods=["GET"])
    def models_status():
        """Statut des modèles en cache"""
        mc = get_model_cache()
        return jsonify(mc.get_stats())

    @app.route("/api/models/preload", methods=["POST"])
    def preload_models():
        """Précharge des modèles"""
        data = request.get_json() or {}
        model_names = data.get("models", [])
        if not model_names:
            return jsonify({"error": "Liste de modèles requise"}), 400

        mc = get_model_cache()
        mc.preload_models(model_names)
        return jsonify({"status": "preload_started", "models": model_names})

    @app.route("/api/device", methods=["GET"])
    def device_info():
        """Informations sur le dispositif de calcul"""
        dm = get_device_manager()
        return jsonify({
            "device_type": dm.device_type,
            "device_name": dm.device_info.device_name,
            "total_memory_gb": dm.device_info.total_memory_gb,
            "free_memory_gb": dm.device_info.free_memory_gb,
            "compute_capability": dm.device_info.compute_capability,
            "driver_version": dm.device_info.driver_version,
            "cpu_threads": dm.cpu_threads,
            "gpu_memory_fraction": dm.gpu_memory_fraction,
            "batch_sizes": dm._batch_sizes,
            "memory_stats": dm.get_memory_stats(),
        })

    @app.route("/api/device", methods=["POST"])
    def set_device_preference():
        """Change la préférence de dispositif"""
        data = request.get_json() or {}
        preference = data.get("preference", "auto")
        dm = get_device_manager()

        if preference not in ("auto", "cuda", "mps", "cpu"):
            return jsonify({"error": "Préférence invalide"}), 400

        try:
            dm._force_device(preference)
            return jsonify({"status": "ok", "device": dm.device_type})
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400

    # ─── Validation helpers ────────────────────────────────────────────────────

    def validate_audio_file(file) -> tuple[bool, Optional[str]]:
        """Valide un fichier audio uploadé"""
        if not file or file.filename == "":
            return False, "Aucun fichier sélectionné"

        # Vérifier l'extension
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            return False, f"Format non supporté: {ext}. Formats acceptés: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}"

        # Vérifier la taille (approximative via content_length)
        if request.content_length and request.content_length > MAX_FILE_SIZE_MB * 1024 * 1024:
            return False, f"Fichier trop volumineux (max {MAX_FILE_SIZE_MB} MB)"

        return True, None

    def validate_audio_duration(audio_path: str) -> tuple[bool, Optional[str]]:
        """Valide la durée du fichier audio"""
        try:
            import librosa
            duration = librosa.get_duration(path=audio_path)
            if duration > MAX_AUDIO_DURATION_SECONDS:
                return False, f"Audio trop long: {duration:.1f}s (max {MAX_AUDIO_DURATION_SECONDS}s)"
            return True, None
        except Exception as e:
            logger.warning(f"Impossible de valider la durée: {e}")
            return True, None  # Ne pas bloquer si on ne peut pas vérifier

    # ─── Transcription - Version synchrone (compatibilité) ─────────────────────

    @app.route("/api/transcribe", methods=["POST"])
    def transcribe_sync():
        """
        Transcription synchrone (bloquante).
        Pour compatibilité avec l'ancien frontend.
        """
        if "audio" not in request.files:
            return jsonify({"error": "Fichier audio requis"}), 400

        audio_file = request.files["audio"]
        valid, error = validate_audio_file(audio_file)
        if not valid:
            return jsonify({"error": error}), 400

        # Sauvegarder le fichier
        upload_id = str(uuid.uuid4())
        upload_path = config.uploads_dir / f"{upload_id}_{audio_file.filename}"
        audio_file.save(upload_path)

        # Valider la durée
        valid, error = validate_audio_duration(str(upload_path))
        if not valid:
            try:
                upload_path.unlink()
            except Exception:
                pass
            return jsonify({"error": error}), 400

        try:
            # Options depuis form data
            options = _parse_transcription_options(request.form)

            # Lancer transcription synchrone
            result = run_transcription_sync(
                str(upload_path),
                options,
                config=config,
            )

            # Nettoyer upload
            try:
                upload_path.unlink()
            except Exception:
                pass

            if result.success:
                return jsonify({
                    "success": True,
                    "score_data": result.score_data,
                    "output_files": result.output_files,
                    "processing_time": result.processing_time,
                })
            else:
                return jsonify({
                    "success": False,
                    "error": result.error,
                    "processing_time": result.processing_time,
                }), 500

        except Exception as e:
            logger.exception("Erreur transcription synchrone")
            try:
                upload_path.unlink()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 500

    # ─── Transcription - Version asynchrone avec SSE ───────────────────────────

    @app.route("/api/transcribe/start", methods=["POST"])
    def transcribe_start():
        """
        Démarre une transcription asynchrone.
        Retourne un job_id pour suivre la progression via SSE.
        """
        if "audio" not in request.files:
            return jsonify({"error": "Fichier audio requis"}), 400

        audio_file = request.files["audio"]
        valid, error = validate_audio_file(audio_file)
        if not valid:
            return jsonify({"error": error}), 400

        # Sauvegarder le fichier
        job_id = str(uuid.uuid4())
        upload_path = config.uploads_dir / f"{job_id}_{audio_file.filename}"
        audio_file.save(upload_path)

        # Valider la durée
        valid, error = validate_audio_duration(str(upload_path))
        if not valid:
            try:
                upload_path.unlink()
            except Exception:
                pass
            return jsonify({"error": error}), 400

        # Options
        options = _parse_transcription_options(request.form)
        options["job_id"] = job_id

        # Stocker le job pour SSE
        job_data = {
            "id": job_id,
            "audio_path": str(upload_path),
            "options": options,
            "status": "queued",
            "result": None,
            "error": None,
        }
        with _jobs_lock:
            _jobs[job_id] = job_data

        # Lancer en arrière-plan
        thread = threading.Thread(target=_run_transcription_job, args=(job_id,), daemon=True)
        thread.start()

        return jsonify({
            "job_id": job_id,
            "status": "queued",
            "sse_url": f"/api/transcribe/progress/{job_id}",
        })

    @app.route("/api/transcribe/progress/<job_id>", methods=["GET"])
    def transcribe_progress(job_id: str):
        """
        Server-Sent Events pour progression temps réel.
        """
        if job_id not in _jobs:
            return jsonify({"error": "Job introuvable"}), 404

        def event_stream():
            pipeline = _job_pipelines.get(job_id)
            if pipeline is None:
                # Pipeline pas encore démarré, attendre
                import time
                for _ in range(50):  # 5 secondes max
                    time.sleep(0.1)
                    pipeline = _job_pipelines.get(job_id)
                    if pipeline:
                        break

            if pipeline is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Pipeline non démarré'})}\n\n"
                return

            # Stream depuis le pipeline SSE
            async def stream_generator():
                async for event in pipeline.progress_stream():
                    yield event

            # Exécuter le générateur asynchrone
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                gen = stream_generator()
                while True:
                    try:
                        event = loop.run_until_complete(gen.__anext__())
                        yield event
                    except StopAsyncIteration:
                        break
            finally:
                loop.close()

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Désactiver buffering nginx
                "Connection": "keep-alive",
            }
        )

    @app.route("/api/transcribe/result/<job_id>", methods=["GET"])
    def transcribe_result(job_id: str):
        """Récupère le résultat final d'un job"""
        if job_id not in _jobs:
            return jsonify({"error": "Job introuvable"}), 404

        job = _jobs[job_id]
        if job["status"] != "completed":
            return jsonify({"status": job["status"]}), 202

        return jsonify(job["result"])

    @app.route("/api/transcribe/cancel/<job_id>", methods=["POST"])
    def transcribe_cancel(job_id: str):
        """Annule un job en cours"""
        if job_id not in _jobs:
            return jsonify({"error": "Job introuvable"}), 404

        pipeline = _job_pipelines.get(job_id)
        if pipeline:
            pipeline.cancel()

        with _jobs_lock:
            _jobs[job_id]["status"] = "cancelled"
        return jsonify({"status": "cancelled"})

    # ─── Téléchargement fichiers de sortie ─────────────────────────────────────

    @app.route("/api/download/<path:filename>", methods=["GET"])
    def download_file(filename: str):
        """Télécharge un fichier de sortie"""
        file_path = config.outputs_dir / filename
        if not file_path.exists():
            return jsonify({"error": "Fichier introuvable"}), 404
        return send_file(file_path, as_attachment=True)

    @app.route("/api/outputs", methods=["GET"])
    def list_outputs():
        """Liste les fichiers de sortie"""
        files = []
        for f in config.outputs_dir.glob("*"):
            if f.is_file():
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "url": f"/api/download/{f.name}",
                })
        return jsonify({"files": sorted(files, key=lambda x: x["modified"], reverse=True)})

    # ─── Frontend statique ─────────────────────────────────────────────────────

    @app.route("/", methods=["GET"])
    def index():
        """Sert le frontend"""
        return send_from_directory("../frontend", "index.html")

    @app.route("/<path:path>", methods=["GET"])
    def static_files(path: str):
        """Sert les fichiers statiques du frontend"""
        return send_from_directory("../frontend", path)

    # ─── Gestion des jobs en arrière-plan ──────────────────────────────────────

    _jobs: dict[str, dict] = {}
    _job_pipelines: dict[str, SSEPipeline] = {}
    _jobs_lock = threading.Lock()

    def _run_transcription_job(job_id: str) -> None:
        """Exécute le job de transcription en arrière-plan"""
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"

        try:
            # Créer pipeline SSE
            pipeline = SSEPipeline(config)
            with _jobs_lock:
                _job_pipelines[job_id] = pipeline

            # Lancer le pipeline
            result, _ = asyncio.run(pipeline.run_with_sse(
                job["audio_path"],
                job["options"],
            ))

            with _jobs_lock:
                job["status"] = "completed" if result.success else "failed"
                job["result"] = {
                    "success": result.success,
                    "score_data": result.score_data,
                    "output_files": result.output_files,
                    "error": result.error,
                    "processing_time": result.processing_time,
                }

            # Nettoyer fichier upload
            try:
                Path(job["audio_path"]).unlink()
            except Exception:
                pass

        except Exception as e:
            logger.exception(f"Erreur job {job_id}")
            with _jobs_lock:
                job["status"] = "failed"
                job["error"] = str(e)
        finally:
            with _jobs_lock:
                _job_pipelines.pop(job_id, None)

    def _parse_transcription_options(form_data) -> dict:
        """Parse les options de transcription depuis form data"""
        options = {}

        # Modèle
        if "model" in form_data:
            options["model"] = form_data["model"]

        # Demucs
        options["use_demucs"] = form_data.get("use_demucs", "true").lower() == "true"
        if "demucs_model" in form_data:
            options["demucs_model"] = form_data["demucs_model"]
        if "demucs_shifts" in form_data:
            options["demucs_shifts"] = int(form_data["demucs_shifts"])

        # Quantification
        if "quantization" in form_data:
            options["quantization"] = form_data["quantization"]

        # Séparation mains
        if "hand_split_method" in form_data:
            options["hand_split_method"] = form_data["hand_split_method"]
        if "hand_split_point" in form_data:
            options["hand_split_point"] = int(form_data["hand_split_point"])

        # Tempo/tonalité
        if "tempo" in form_data:
            options["tempo"] = int(form_data["tempo"])
        if "time_signature" in form_data:
            parts = form_data["time_signature"].split("/")
            if len(parts) == 2:
                options["time_signature"] = [int(parts[0]), int(parts[1])]
        if "key_signature" in form_data:
            options["key_signature"] = form_data["key_signature"]

        # Export
        if "export_formats" in form_data:
            options["export_formats"] = form_data["export_formats"].split(",")
        if "base_name" in form_data:
            options["base_name"] = form_data["base_name"]

        # Device
        options["device"] = form_data.get("device", "auto")

        # Ensemble voting options
        if "ensemble_enabled" in form_data:
            options["ensemble_enabled"] = form_data["ensemble_enabled"].lower() == "true"
        if "ensemble_models" in form_data:
            # Format: "piano_transcription:1.5,basic_pitch:1.0,transkun:1.3"
            models_str = form_data["ensemble_models"]
            models = []
            for m in models_str.split(","):
                parts = m.split(":")
                if len(parts) == 2:
                    models.append({"name": parts[0], "weight": float(parts[1])})
            options["ensemble_models"] = models
        if "ensemble_onset_tolerance" in form_data:
            options["ensemble_onset_tolerance"] = float(form_data["ensemble_onset_tolerance"])
        if "ensemble_pitch_tolerance" in form_data:
            options["ensemble_pitch_tolerance"] = int(form_data["ensemble_pitch_tolerance"])
        if "ensemble_min_votes" in form_data:
            options["ensemble_min_votes"] = int(form_data["ensemble_min_votes"])
        if "ensemble_velocity_aggregation" in form_data:
            options["ensemble_velocity_aggregation"] = form_data["ensemble_velocity_aggregation"]
        if "ensemble_duration_aggregation" in form_data:
            options["ensemble_duration_aggregation"] = form_data["ensemble_duration_aggregation"]

        return options

    return app


# ─── Point d'entrée pour exécution directe ─────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    config = get_config()
    app = create_app(config)
    app.run(
        host=config.server.host,
        port=config.server.port,
        debug=config.server.debug,
        threaded=True,
    )