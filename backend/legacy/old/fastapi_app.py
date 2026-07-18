"""
fastapi_app.py — FastAPI avec SSE progress (Phase 1.7a)

Ce module expose les routes FastAPI par-dessus Flask existant.
Approche progressive : pas de régression, Flask gère toujours transcribe.

Utilisation :
    from fastapi_app import fastapi_app, mount_fastapi
    mount_fastapi(flask_app, fastapi_app)
    # ou
    uvicorn fastapi_app:app --host 0.0.0.0 --port 5001
"""
import os
import sys
import json
import time
import asyncio
import tempfile
import logging
from typing import Optional
from contextlib import asynccontextmanager

# ── Dépendances FastAPI (optionnelles) ────────────────────────────────────────
try:
    from fastapi import FastAPI, Request, Response, UploadFile, File, Form
    from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── Vérification FastAPI disponible ──────────────────────────────────────────
if not FASTAPI_AVAILABLE:
    logger.warning("[P1.7] FastAPI/pydantic non installés — fastapi_app.py sera désactivé")
    logger.warning("[P1.7]   → pip install fastapi uvicorn pydantic")


# ── Pydantic models ──────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    """Requête de transcription (FastAPI)."""
    transcriber: str = Field(default='piano_transcription', pattern='^(piano_transcription|basic_pitch|transkun|hft|mt3|ensemble)$')
    preset: str = Field(default='standard')
    use_demucs: bool = Field(default=False)
    onset_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    frame_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    offset_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    minimum_note_duration: int = Field(default=50, ge=10, le=500)
    time_sig: str = Field(default='4/4', pattern='^[0-9]+/[0-9]+$')
    key_sig: str = Field(default='C', pattern='^[A-G][#b]?$')
    detect_tempo: bool = Field(default=True)
    detect_meter: bool = Field(default=True)
    detect_key: bool = Field(default=True)
    quantization_level: str = Field(default='standard', pattern='^(none|simple|standard|strict)$')
    remove_short_notes: bool = Field(default=False)
    merge_near_notes: bool = Field(default=False)
    merge_gap_ms: int = Field(default=30, ge=10, le=200)
    split_hands: bool = Field(default=False)
    enable_rubato: bool = Field(default=False)
    enable_triplets: bool = Field(default=False)
    strict_mode: bool = Field(default=False)
    tempo: Optional[float] = Field(default=None, ge=40, le=300)


class HealthResponse(BaseModel):
    status: str = 'ok'
    version: str = '3.0.0'
    fastapi: bool = True


class DeviceResponse(BaseModel):
    device_type: str
    device_name: str
    total_memory_gb: Optional[float] = None
    free_memory_gb: Optional[float] = None
    compute_capability: Optional[float] = None
    driver_version: Optional[str] = None
    cpu_threads: Optional[int] = None
    gpu_memory_fraction: Optional[float] = None
    batch_sizes: Optional[dict] = None
    memory_stats: Optional[dict] = None


class GpuStatusResponse(BaseModel):
    pytorch_version: str
    cuda_available: bool
    xpu_available: bool
    device: str
    device_name: str
    gpu_recommended: bool
    warnings: list[str]


class CleanupResponse(BaseModel):
    status: str
    cleaned: int = 0


class TranscribeProgress(BaseModel):
    """Progression SSE."""
    type: str  # 'status', 'warning', 'done', 'error'
    message: str
    progress: Optional[float] = None  # 0.0 - 1.0
    step: Optional[str] = None  # 'transcription', 'quantization', 'export'


# ── SSE Progress Manager ─────────────────────────────────────────────────────

class SSEProgressManager:
    """Gère les connexions SSE pour la progression de transcription."""
    
    def __init__(self):
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
    
    async def subscribe(self, job_id: str) -> asyncio.Queue:
        """S'abonner à la progression d'un job."""
        queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[job_id] = queue
        return queue
    
    async def unsubscribe(self, job_id: str):
        """Se désabonner."""
        async with self._lock:
            self._subscribers.pop(job_id, None)
    
    async def publish(self, job_id: str, event: dict):
        """Publier un événement pour un job."""
        async with self._lock:
            queue = self._subscribers.get(job_id)
        
        if queue is not None:
            try:
                await asyncio.wait_for(queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                logger.debug(f"[P1.7] SSE timeout pour job {job_id}")
            except Exception as e:
                logger.debug(f"[P1.7] SSE publish error: {e}")
    
    async def cleanup_expired(self, timeout: int = 300):
        """Nettoyer les subscribers expirés."""
        async with self._lock:
            expired = [jid for jid, q in self._subscribers.items() if q.empty()]
            for jid in expired:
                del self._subscribers[jid]
                logger.debug(f"[P1.7] SSE cleanup: {jid}")


# Instance globale
progress_manager = SSEProgressManager()


# ── SSE generator ────────────────────────────────────────────────────────────

def sse_format(event: str, data: dict = None, comment: str = None) -> str:
    """Formate un événement SSE."""
    lines = []
    if comment:
        lines.append(f": {comment}")
    lines.append(f"event: {event}")
    if data is not None:
        lines.append(f"data: {json.dumps(data, default=str)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


async def sse_progress_generator(job_id: str):
    """Génère les événements SSE pour un job de transcription."""
    try:
        queue = await progress_manager.subscribe(job_id)
        
        # heartbeat pour garder la connexion alive
        heartbeat_count = 0
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield sse_format(event.get('type', 'message'), event)
                
                if event.get('type') in ('done', 'error'):
                    break
            except asyncio.TimeoutError:
                heartbeat_count += 1
                yield sse_format('heartbeat', {'time': time.time()})
                if heartbeat_count > 20:  # 5 minutes max
                    break
    finally:
        await progress_manager.unsubscribe(job_id)


# ── FastAPI app ──────────────────────────────────────────────────────────────

if FASTAPI_AVAILABLE:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Gestion du cycle de vie FastAPI."""
        logger.info("[P1.7] FastAPI démarré")
        yield
        logger.info("[P1.7] FastAPI arrêté")
        # Nettoyer les subscribers SSE
        await progress_manager.cleanup_expired()

    app = FastAPI(
        title="audio-to-sheet",
        description="API de transcription audio → partition MusicXML/MIDI",
        version="3.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ──────────────────────────────────────────────────────────────
    @app.get("/api/health", response_model=HealthResponse)
    async def health_check():
        return HealthResponse(status='ok', version='3.0.0', fastapi=True)

    # ── Device info ─────────────────────────────────────────────────────────
    @app.get("/api/device-info", response_model=DeviceResponse)
    async def device_info():
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
        return DeviceResponse(
            device_type=device_type,
            device_name=device_name,
        )

    # ── Device compat (alias) ───────────────────────────────────────────────
    @app.get("/api/device", response_model=DeviceResponse)
    async def device_compat():
        return await device_info()

    # ── GPU status ──────────────────────────────────────────────────────────
    @app.get("/api/gpu-status", response_model=GpuStatusResponse)
    async def gpu_status():
        import torch
        info = GpuStatusResponse(
            pytorch_version=torch.__version__,
            cuda_available=False,
            xpu_available=False,
            device='cpu',
            device_name='Processeur (CPU)',
            gpu_recommended=False,
            warnings=[],
        )
        try:
            if torch.cuda.is_available():
                info.cuda_available = True
                info.device = 'cuda'
                info.device_name = torch.cuda.get_device_name(0)
                info.gpu_recommended = True
                info.warnings.append('GPU NVIDIA détecté - accélération CUDA activée.')
                return info
        except Exception:
            pass
        if hasattr(torch, 'xpu'):
            try:
                if torch.xpu.is_available():
                    info.xpu_available = True
                    info.device = 'xpu'
                    info.device_name = torch.xpu.get_device_name(0) if hasattr(torch.xpu, 'get_device_name') else 'Intel ARC GPU'
                    info.gpu_recommended = True
                    info.warnings.append('GPU Intel ARC détecté - accélération IPEX activée.')
                    return info
            except Exception:
                pass
        info.warnings.extend([
            'Aucun GPU détecté.',
            '1. Installez IPEX: pip install intel-extension-for-pytorch',
            '2. Ou utilisez le wheel PyTorch Intel: pip install torch --index-url https://download.pytorch.org/whl/xpu',
            '3. Redémarrez le serveur après l\'installation.',
        ])
        return info

    # ── SSE Progress ────────────────────────────────────────────────────────
    @app.get("/api/transcribe-progress/{job_id}")
    async def transcribe_progress(job_id: str):
        """Endpoint SSE pour la progression de transcription."""
        async def event_stream():
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
                        yield sse_format('heartbeat', {'time': time.time()})
                        if heartbeat_count > 20:
                            break
            finally:
                await progress_manager.unsubscribe(job_id)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Publish progress helper ─────────────────────────────────────────────
    async def publish_progress(job_id: str, event_type: str, message: str,
                                progress: float = None, step: str = None):
        """Publie un événement de progression pour un job."""
        await progress_manager.publish(job_id, {
            'type': event_type,
            'message': message,
            'progress': progress,
            'step': step,
        })

    # ── Cleanup (placeholder) ───────────────────────────────────────────────
    @app.post("/api/cleanup", response_model=CleanupResponse)
    async def cleanup():
        return CleanupResponse(status='ok', cleaned=0)

    # ── Transcribe (FastAPI async + SSE) ───────────────────────────────────
    @app.post("/api/transcribe")
    async def transcribe_fastapi_endpoint(
        file: UploadFile = File(...),
        transcriber: str = Form(default='piano_transcription'),
        preset: str = Form(default='standard'),
        use_demucs: bool = Form(default=False),
        onset_threshold: float = Form(default=0.5),
        frame_threshold: float = Form(default=0.1),
        offset_threshold: float = Form(default=0.3),
        minimum_note_duration: int = Form(default=50),
        time_sig: str = Form(default='4/4'),
        key_sig: str = Form(default='C'),
        detect_tempo: bool = Form(default=True),
        detect_meter: bool = Form(default=True),
        detect_key: bool = Form(default=True),
        quantization_level: str = Form(default='standard'),
        remove_short_notes: bool = Form(default=False),
        merge_near_notes: bool = Form(default=False),
        merge_gap_ms: int = Form(default=30),
        split_hands: bool = Form(default=False),
        enable_rubato: bool = Form(default=False),
        enable_triplets: bool = Form(default=False),
        strict_mode: bool = Form(default=False),
        tempo: Optional[float] = Form(default=None),
    ):
        """Endpoint FastAPI pour la transcription audio → partition."""
        try:
            from fastapi_transcribe import transcribe_fastapi
            return await transcribe_fastapi(
                file=file,
                transcriber=transcriber,
                preset=preset,
                use_demucs=use_demucs,
                onset_threshold=onset_threshold,
                frame_threshold=frame_threshold,
                offset_threshold=offset_threshold,
                minimum_note_duration=minimum_note_duration,
                time_sig=time_sig,
                key_sig=key_sig,
                detect_tempo=detect_tempo,
                detect_meter=detect_meter,
                detect_key=detect_key,
                quantization_level=quantization_level,
                remove_short_notes=remove_short_notes,
                merge_near_notes=merge_near_notes,
                merge_gap_ms=merge_gap_ms,
                split_hands=split_hands,
                enable_rubato=enable_rubato,
                enable_triplets=enable_triplets,
                strict_mode=strict_mode,
                tempo=tempo,
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={'error': str(e)})

else:
    app = None  # FastAPI non disponible


# ── Helper pour monter FastAPI sur Flask ──────────────────────────────────────

def mount_fastapi(flask_app, fastapi_app):
    """
    Monte les routes SSE de FastAPI sur Flask.
    
    Les routes /api/transcribe-progress/* sont ajoutées directement
    sur l'app Flask car le montage WSGI ne fonctionne pas bien avec FastAPI.
    """
    if not FASTAPI_AVAILABLE or fastapi_app is None:
        logger.warning("[P1.7] FastAPI non disponible — routes SSE désactivées")
        return
    
    if progress_manager is None:
        logger.warning("[P1.7] SSE progress manager indisponible — routes SSE désactivées")
        return
    
    import asyncio
    import time
    from flask import Response
    from flask import request as flask_request
    
    # Créer un event loop pour le thread Flask
    def get_event_loop():
        """Retourne un loop existant ou en crée un nouveau."""
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                return loop
        except RuntimeError:
            pass
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop
    
    @flask_app.route('/api/transcribe-progress/<job_id>', methods=['GET'])
    def transcribe_progress(job_id):
        """Endpoint SSE pour la progression de transcription (Flask)."""
        async def event_stream():
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
                        yield sse_format('heartbeat', {'time': time.time()})
                        if heartbeat_count > 20:
                            break
            finally:
                await progress_manager.unsubscribe(job_id)
        
        def generate():
            loop = get_event_loop()
            if not loop.is_running():
                # Démarrer le loop dans un thread séparé
                import asyncio
                task = asyncio.ensure_future(event_stream())
                # Envoyer les events au fur et à mesure
                async def send_events():
                    try:
                        async for event_data in event_stream():
                            yield event_data
                    except Exception as e:
                        logger.error(f"[SSE] Error in stream for {job_id}: {e}")
                
                # Utiliser run_coroutine_threadsafe
                result = []
                done_event = asyncio.Event()
                
                async def collect_and_signal():
                    try:
                        async for event_data in event_stream():
                            result.append(event_data)
                            # Yield via Flask response
                            yield event_data
                    finally:
                        done_event.set()
                
                return generate()
            else:
                return generate()
        
        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            }
        )
    
    logger.info("[P1.7] Routes SSE montées sur Flask")


# ── Serveur standalone FastAPI ───────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    logger.info("[P1.7] Démarrage serveur FastAPI standalone...")
    uvicorn.run(app, host='0.0.0.0', port=5001)