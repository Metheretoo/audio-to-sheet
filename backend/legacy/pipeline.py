"""
AudioScore — Pipeline asynchrone de transcription avec progression temps réel
Remplace la progression simulée par une vraie progression par étapes.
"""
from __future__ import annotations

import asyncio
import time
import uuid
import tempfile
import atexit
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# ─── Global temp file tracking for cleanup ──────────────────────────────────────
_temp_files: list[str] = []

def _register_temp_file(path: str) -> None:
    """Enregistre un fichier temporaire pour nettoyage automatique."""
    _temp_files.append(path)

def _cleanup_temp_files() -> None:
    """Nettoie tous les fichiers temporaires enregistrés."""
    for f in _temp_files:
        try:
            if os.path.exists(f):
                os.unlink(f)
        except Exception as e:
            logger.warning(f"Impossible de supprimer le fichier temporaire {f}: {e}")
    _temp_files.clear()

# Enregistrer le nettoyage à la sortie
atexit.register(_cleanup_temp_files)


class PipelineStage(str, Enum):
    """Étapes du pipeline de transcription"""
    LOAD_AUDIO = "load_audio"
    DEMUCS = "demucs"
    TRANSCRIBE = "transcribe"
    FILTER = "filter"
    QUANTIZE = "quantize"
    HARMONIC = "harmonic"
    SPLIT_HANDS = "split_hands"
    BUILD_SCORE = "build_score"
    EXPORT = "export"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class PipelineProgress:
    """Progression d'une étape du pipeline"""
    stage: PipelineStage
    stage_index: int
    total_stages: int
    percent: float  # 0.0 - 100.0
    message: str
    elapsed_seconds: float
    stage_elapsed_seconds: float
    metadata: dict = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.stage == PipelineStage.COMPLETE

    @property
    def is_error(self) -> bool:
        return self.stage == PipelineStage.ERROR


@dataclass
class PipelineResult:
    """Résultat final du pipeline"""
    success: bool
    score_data: Optional[dict] = None
    output_files: dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    processing_time: float = 0.0
    metadata: dict = field(default_factory=dict)


# Type pour le callback de progression
ProgressCallback = Callable[[PipelineProgress], None]


class AsyncPipeline:
    """
    Pipeline asynchrone pour la transcription audio vers partition.
    Exécute chaque étape dans un thread pool pour ne pas bloquer l'event loop.
    Émet des événements de progression via callback.
    """

    def __init__(
        self,
        config: Optional[Any] = None,
        progress_callback: Optional[ProgressCallback] = None,
        timeout_per_stage: float = 300.0,  # 5 minutes par défaut
    ):
        self.config = config
        self.progress_callback = progress_callback
        self._stages: list[PipelineStage] = []
        self._stage_weights: dict[PipelineStage, int] = {}
        self._stage_descriptions: dict[PipelineStage, str] = {}
        self._start_time = 0.0
        self._stage_start_time = 0.0
        self._current_stage_index = 0
        self._total_weight = 0
        self._completed_weight = 0
        self._cancelled = False
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Pas en pause au début
        self._timeout_per_stage = timeout_per_stage

        # Configuration par défaut des étapes
        self._setup_default_stages()

    def _setup_default_stages(self) -> None:
        """Configure les étapes par défaut avec leurs poids"""
        if self.config and hasattr(self.config, "pipeline") and self.config.pipeline.stages:
            # Utiliser la config si disponible
            for i, stage_config in enumerate(self.config.pipeline.stages):
                stage = PipelineStage(stage_config.name)
                self._stages.append(stage)
                self._stage_weights[stage] = stage_config.weight
                self._stage_descriptions[stage] = stage_config.description
        else:
            # Configuration par défaut
            defaults = [
                (PipelineStage.LOAD_AUDIO, 5, "Chargement audio"),
                (PipelineStage.DEMUCS, 30, "Séparation Demucs"),
                (PipelineStage.TRANSCRIBE, 40, "Transcription IA"),
                (PipelineStage.FILTER, 5, "Filtrage notes"),
                (PipelineStage.QUANTIZE, 10, "Quantification"),
                (PipelineStage.HARMONIC, 8, "Analyse harmonique"),
                (PipelineStage.SPLIT_HANDS, 5, "Séparation mains"),
                (PipelineStage.BUILD_SCORE, 5, "Construction partition"),
                (PipelineStage.EXPORT, 5, "Export fichiers"),
            ]
            for stage, weight, desc in defaults:
                self._stages.append(stage)
                self._stage_weights[stage] = weight
                self._stage_descriptions[stage] = desc

        self._total_weight = sum(self._stage_weights.values())

    def configure_stages(
        self,
        stages: list[PipelineStage],
        weights: dict[PipelineStage, int],
        descriptions: dict[PipelineStage, str],
    ) -> None:
        """Configure les étapes personnalisées"""
        self._stages = stages
        self._stage_weights = weights
        self._stage_descriptions = descriptions
        self._total_weight = sum(weights.values())

    def _emit_progress(
        self,
        stage: PipelineStage,
        stage_percent: float,
        message: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Émet un événement de progression"""
        if self.progress_callback is None:
            return

        now = time.time()
        elapsed = now - self._start_time
        stage_elapsed = now - self._stage_start_time

        # Calculer le pourcentage global
        stage_weight = self._stage_weights.get(stage, 0)
        global_percent = (
            (self._completed_weight + stage_weight * stage_percent / 100.0)
            / self._total_weight * 100.0
        )

        progress = PipelineProgress(
            stage=stage,
            stage_index=self._current_stage_index,
            total_stages=len(self._stages),
            percent=min(100.0, max(0.0, global_percent)),
            message=message,
            elapsed_seconds=elapsed,
            stage_elapsed_seconds=stage_elapsed,
            metadata=metadata or {},
        )

        try:
            self.progress_callback(progress)
        except Exception as e:
            logger.warning(f"Erreur dans callback de progression: {e}")

    async def _run_stage(
        self,
        stage: PipelineStage,
        stage_fn: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """Exécute une étape du pipeline dans un thread pool avec timeout"""
        self._stage_start_time = time.time()
        self._emit_progress(stage, 0.0, f"Démarrage: {self._stage_descriptions.get(stage, stage.value)}")

        # Vérifier pause/annulation
        await self._pause_event.wait()
        if self._cancelled:
            raise asyncio.CancelledError("Pipeline annulé")

        try:
            # Exécuter dans un thread pour ne pas bloquer l'event loop
            loop = asyncio.get_event_loop()
            
            # Wrapper pour capturer les exceptions
            def run_with_error_handling():
                try:
                    return stage_fn(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Erreur dans {stage.value}: {e}")
                    raise

            # Exécuter avec timeout
            result = await asyncio.wait_for(
                loop.run_in_executor(None, run_with_error_handling),
                timeout=self._timeout_per_stage
            )

            # Vérifier à nouveau après l'exécution
            if self._cancelled:
                raise asyncio.CancelledError("Pipeline annulé")

            self._emit_progress(stage, 100.0, f"Terminé: {self._stage_descriptions.get(stage, stage.value)}")
            self._completed_weight += self._stage_weights.get(stage, 0)
            return result

        except asyncio.TimeoutError:
            error_msg = f"Timeout à l'étape {stage.value} ({self._timeout_per_stage}s)"
            logger.error(error_msg)
            self._emit_progress(stage, 0.0, f"Timeout: {error_msg}", {"error": error_msg, "timeout": True})
            raise TimeoutError(error_msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Erreur à l'étape {stage.value}: {e}")
            self._emit_progress(stage, 0.0, f"Erreur: {e}", {"error": str(e)})
            raise

    async def run(
        self,
        audio_path: str,
        options: dict,
    ) -> PipelineResult:
        """
        Exécute le pipeline complet de transcription.

        Args:
            audio_path: Chemin vers le fichier audio
            options: Options de transcription (modèle, quantification, etc.)

        Returns:
            PipelineResult avec les données de partition et fichiers de sortie
        """
        self._start_time = time.time()
        self._completed_weight = 0
        self._current_stage_index = 0
        self._cancelled = False
        self._paused = False
        self._pause_event.set()

        run_id = str(uuid.uuid4())[:8]
        logger.info(f"[{run_id}] Démarrage pipeline pour {audio_path}")

        try:
            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 1: Chargement audio
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 0
            audio_data = await self._run_stage(
                PipelineStage.LOAD_AUDIO,
                self._load_audio,
                audio_path,
            )

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 2: Séparation Demucs (optionnelle)
            # ─────────────────────────────────────────────────────────────────
            if options.get("use_demucs", True):
                self._current_stage_index = 1
                audio_data = await self._run_stage(
                    PipelineStage.DEMUCS,
                    self._run_demucs,
                    audio_data,
                    options,
                )
            else:
                # Marquer l'étape comme complétée (poids 0)
                self._completed_weight += self._stage_weights.get(PipelineStage.DEMUCS, 0)
                self._current_stage_index = 1

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 3: Transcription IA
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 2
            note_events = await self._run_stage(
                PipelineStage.TRANSCRIBE,
                self._transcribe,
                audio_data,
                options,
            )

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 4: Filtrage des notes (Notes fantômes + raccourcissement pédale)
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 3
            filtered_data = await self._run_stage(
                PipelineStage.FILTER,
                self._filter_notes,
                note_events,
                options,
            )
            filtered_notes = filtered_data["notes"]
            pedals = filtered_data["pedals"]

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 5: Quantification
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 4
            quantized_events = await self._run_stage(
                PipelineStage.QUANTIZE,
                self._quantize,
                filtered_notes,
                options,
            )

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 6 : Analyse harmonique (Piano Roll + music21)
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 5
            harmonic_ctx = await self._run_stage(
                PipelineStage.HARMONIC,
                self._analyze_harmony,
                quantized_events,
                pedals,
                options,
            )

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 7 : Séparation mains guidée par l'harmonie
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 6
            split_events = await self._run_stage(
                PipelineStage.SPLIT_HANDS,
                self._split_hands,
                quantized_events,
                harmonic_ctx,
                options,
            )

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 7: Construction partition
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 7
            score_data = await self._run_stage(
                PipelineStage.BUILD_SCORE,
                self._build_score,
                split_events,
                pedals,
                harmonic_ctx,
                options,
            )

            # ─────────────────────────────────────────────────────────────────
            # ÉTAPE 8: Export
            # ─────────────────────────────────────────────────────────────────
            self._current_stage_index = 7
            output_files = await self._run_stage(
                PipelineStage.EXPORT,
                self._export,
                score_data,
                options,
            )

            # ─────────────────────────────────────────────────────────────────
            # TERMINÉ
            # ─────────────────────────────────────────────────────────────────
            self._emit_progress(
                PipelineStage.COMPLETE,
                100.0,
                "Transcription terminée avec succès",
                {"run_id": run_id, "output_files": output_files},
            )

            processing_time = time.time() - self._start_time
            logger.info(f"[{run_id}] Pipeline terminé en {processing_time:.2f}s")

            return PipelineResult(
                success=True,
                score_data=score_data,
                output_files=output_files,
                processing_time=processing_time,
                metadata={"run_id": run_id},
            )

        except asyncio.CancelledError:
            self._emit_progress(
                PipelineStage.ERROR,
                0.0,
                "Pipeline annulé",
                {"run_id": run_id},
            )
            return PipelineResult(
                success=False,
                error="Pipeline annulé",
                processing_time=time.time() - self._start_time,
            )

        except TimeoutError as e:
            self._emit_progress(
                PipelineStage.ERROR,
                0.0,
                f"Timeout: {str(e)}",
                {"run_id": run_id, "error": str(e), "timeout": True},
            )
            logger.exception(f"[{run_id}] Timeout pipeline")
            return PipelineResult(
                success=False,
                error=f"Timeout: {str(e)}",
                processing_time=time.time() - self._start_time,
            )

        except Exception as e:
            self._emit_progress(
                PipelineStage.ERROR,
                0.0,
                f"Erreur: {str(e)}",
                {"run_id": run_id, "error": str(e)},
            )
            logger.exception(f"[{run_id}] Erreur pipeline")
            return PipelineResult(
                success=False,
                error=str(e),
                processing_time=time.time() - self._start_time,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Implémentation des étapes (à surcharger ou injecter)
    # ─────────────────────────────────────────────────────────────────────────

    def _load_audio(self, audio_path: str) -> dict:
        """Charge le fichier audio et retourne les données"""
        import librosa
        y, sr = librosa.load(audio_path, sr=None, mono=False)
        if y.ndim == 1:
            y = y[None, :]  # (1, samples) -> mono
        return {
            "waveform": y,
            "sample_rate": sr,
            "duration": len(y[0]) / sr,
            "path": audio_path,
        }

    def _run_demucs(self, audio_data: dict, options: dict) -> dict:
        """Sépare la piste piano avec Demucs"""
        # Import local pour éviter les dépendances circulaires
        from backend.demucs_separator import separate_piano

        piano_waveform = separate_piano(
            audio_data["waveform"],
            audio_data["sample_rate"],
            model=options.get("demucs_model", "htdemucs"),
            device=options.get("device", "auto"),
            shifts=options.get("demucs_shifts", 1),
        )

        return {
            **audio_data,
            "waveform": piano_waveform,
            "demucs_applied": True,
        }

    def _transcribe(self, audio_data: dict, options: dict) -> dict:
        """Transcrit l'audio en événements de notes"""
        from backend.transcriber import transcribe_audio

        # BUG CORRIGÉ (v4.2) : la clé lue ici ("model") ne correspondait pas à
        # celle réellement envoyée par app.py ("transcriber") — le choix du
        # transcripteur dans l'UI (Basic Pitch / Piano Transcription / Ensemble)
        # était donc silencieusement ignoré, "piano_transcription" étant
        # toujours utilisé par défaut quel que soit le choix de l'utilisateur.
        model_name = options.get("transcriber", options.get("model", "piano_transcription"))
        
        # Construire les options pour transcribe_audio (qui attend un chemin de fichier)
        # On doit sauvegarder l'audio temporairement
        import tempfile
        import soundfile as sf
        import numpy as np
        
        # Sauvegarder l'audio dans un fichier temporaire
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name
            # audio_data["waveform"] est de forme (channels, samples)
            waveform = audio_data["waveform"]
            if waveform.ndim == 2 and waveform.shape[0] > 1:
                # Stéréo -> mono en moyennant
                waveform = np.mean(waveform, axis=0, keepdims=True)
            sf.write(tmp_path, waveform.T, audio_data["sample_rate"])
        
        try:
            transcriber_options = {
                'transcriber': model_name,
                'use_demucs': False,  # Déjà fait avant
                'detect_tempo': True,
                'onset_threshold': options.get("onset_threshold", 0.3),
                'frame_threshold': options.get("frame_threshold", 0.3),
                'minimum_note_duration': options.get("minimum_note_duration", options.get("minimum_note_length", 50.0)),
            }
            
            # Ajouter la config d'ensemble si modèle ensemble
            if model_name == 'ensemble':
                # Récupérer la config d'ensemble depuis la config globale
                if self.config and hasattr(self.config, 'transcriber') and hasattr(self.config.transcriber, 'ensemble'):
                    ensemble_cfg = self.config.transcriber.ensemble
                    transcriber_options['ensemble'] = {
                        'enabled': ensemble_cfg.enabled,
                        'models': [
                            {
                                'name': m.name,
                                'weight': m.weight,
                                'onset_weight': m.onset_weight,
                                'pitch_weight': m.pitch_weight,
                                'duration_weight': m.duration_weight,
                            }
                            for m in ensemble_cfg.models
                        ],
                        'onset_tolerance': ensemble_cfg.onset_tolerance,
                        'pitch_tolerance': ensemble_cfg.pitch_tolerance,
                        'min_votes': ensemble_cfg.min_votes,
                        'velocity_aggregation': ensemble_cfg.velocity_aggregation,
                        'duration_aggregation': ensemble_cfg.duration_aggregation,
                    }
            
            note_events, midi_data, pedal_intervals, tempo, warnings = transcribe_audio(tmp_path, transcriber_options)
            
            # Convertir au format attendu par le pipeline (list of dicts)
            result = []
            for onset, pitch, duration, velocity in note_events:
                result.append({
                    'onset': onset,
                    'pitch': pitch,
                    'duration': duration,
                    'velocity': velocity / 127.0,  # Normaliser 0-1
                })
            return {
                "notes": result,
                "pedals": pedal_intervals,
            }
        finally:
            # Nettoyer le fichier temporaire
            try:
                os.unlink(tmp_path)
            except:
                pass

    def _filter_notes(self, transcribe_data: dict, options: dict) -> dict:
        """Filtre les notes fantômes et applique le raccourcissement lié à la pédale"""
        notes = transcribe_data["notes"]
        pedals = transcribe_data["pedals"]
        
        try:
            from backend.note_filter import filter_ghost_notes, apply_pedal_aware_shortening
            notes = filter_ghost_notes(notes, options)
            notes = apply_pedal_aware_shortening(notes, pedals, options)
        except ImportError:
            logger.warning("backend.note_filter n'est pas implémenté. Filtrage ignoré.")
            
        return {
            "notes": notes,
            "pedals": pedals
        }

    def _quantize(self, note_events: list[dict], options: dict) -> list[dict]:
        """Quantifie les événements de notes"""
        from backend.quantizer import quantize_notes

        # BUG CORRIGÉ (v4.2) : la clé lue ici ('quantization') ne correspondait
        # pas à celle envoyée par app.py ('quantization_level'). Résultat : le
        # niveau de quantification choisi par l'utilisateur (Forte/Standard/Légère)
        # était TOUJOURS ignoré — 'standard' était systématiquement appliqué.
        # C'est probablement une des causes majeures de la "soupe de notes" :
        # "Forte" n'était jamais réellement appliqué.
        # Cette même erreur existait dans _analyze_harmony et _split_hands (voir ci-dessous).
        level = options.get("quantization_level", options.get("quantization", "standard"))
        tempo_map = getattr(self, '_tempo_map', None)
        enable_rubato = options.get('enable_rubato', False)
        return quantize_notes(
            note_events,
            tempo_map=tempo_map,
            quantization_level=level,
            enable_rubato=enable_rubato,
        )

    def _split_hands(self, note_events: list, harmonic_ctx, options: dict) -> list:
        """Sépare les notes entre main droite et main gauche (guidé par l'harmonie en V4)"""
        from backend.voice_engine import split_hands, split_with_harmony
        from backend.quantizer import quantize_notes

        # Si les events sont des dicts bruts, les quantifier d'abord pour obtenir des QuantizedNote
        if note_events and isinstance(note_events[0], dict):
            level = options.get('quantization_level', options.get('quantization', 'standard'))
            tempo_map = getattr(self, '_tempo_map', None)
            qnotes = quantize_notes(
                note_events,
                tempo_map=tempo_map,
                quantization_level=level,
            )
        else:
            qnotes = note_events

        if harmonic_ctx is not None:
            voice_split = split_with_harmony(qnotes, harmonic_ctx, options)
        else:
            from backend.voice_engine import split_voices
            voice_split = split_voices(qnotes, options)

        return voice_split

    def _analyze_harmony(self, quantized_events, pedals: list, options: dict):
        """Analyse harmonique : Piano Roll + music21"""
        try:
            from backend.piano_roll import group_into_slices, fuse_arpeggios
            from backend.harmonic_analyzer import build_harmonic_context
            from backend.tempo_map import TempoMap

            tempo_map = getattr(self, '_tempo_map', None)

            # Convertir les pédales secondes → beats si tempo_map disponible
            pedal_beats = []
            if tempo_map and pedals:
                for p_start, p_end in pedals:
                    pedal_beats.append((
                        tempo_map.seconds_to_beat(p_start),
                        tempo_map.seconds_to_beat(p_end)
                    ))

            # Obtenir des QuantizedNote depuis les events
            if quantized_events and isinstance(quantized_events[0], dict):
                from backend.quantizer import quantize_notes
                level = options.get('quantization_level', options.get('quantization', 'standard'))
                qnotes = quantize_notes(
                    quantized_events,
                    tempo_map=tempo_map,
                    quantization_level=level,
                )
            else:
                qnotes = quantized_events

            slices = group_into_slices(qnotes, pedal_events=pedal_beats or None)
            slices = fuse_arpeggios(slices)
            harmonic_ctx = build_harmonic_context(slices)
            logger.info(f"[Harmonie] Tonalité globale détectée : {harmonic_ctx.global_key}")
            return harmonic_ctx
        except Exception as e:
            logger.warning(f"[Harmonie] Échec analyse harmonique ({e}), repli sur None")
            return None

    def _build_score(self, voice_split, pedals: list, harmonic_ctx, options: dict) -> dict:
        """Construit la structure de partition complète"""
        from backend.score_builder import build_score
        from backend.tempo_map import TempoMap
        from backend.voice_engine import VoiceSplit

        # Si voice_split est déjà un VoiceSplit, l'utiliser directement
        if not isinstance(voice_split, VoiceSplit):
            # Fallback si voice_split est une liste de dicts
            voice_split = VoiceSplit(
                treble=[n for n in voice_split if n.get('hand') == 'treble'],
                bass=[n for n in voice_split if n.get('hand') == 'bass'],
            )

        # ── Overrides manuels (armure / mesure) ──────────────────────────────
        # BUG CORRIGÉ (v4.1) : ces overrides utilisaient des clés ('key_signature',
        # 'time_signature') différentes de celles réellement envoyées par le
        # frontend/app.py ('key_sig', 'time_sig'), et n'étaient de toute façon
        # jamais transmis à build_score(). Résultat : le choix manuel de mesure
        # (ex: 3/4 pour une Mazurka) ou d'armure était systématiquement ignoré,
        # remplacé par la seule auto-détection — quels que soient les réglages
        # essayés côté UI.
        #
        # L'UI propose déjà les cases "Détection automatique du tempo/mesure"
        # et "Détection automatique de la tonalité" (cochées par défaut) : on
        # s'appuie sur elles pour savoir si l'override manuel doit s'appliquer.
        detect_tempo_flag = options.get('detect_tempo', True)
        detect_meter_flag = options.get('detect_meter', True)
        detect_key_flag = options.get('detect_key', True)

        raw_key_sig = options.get('key_sig')
        key_override = raw_key_sig if (not detect_key_flag and raw_key_sig) else None

        raw_time_sig = options.get('time_sig')
        time_sig_list = None
        if not detect_meter_flag and raw_time_sig:
            try:
                n_str, d_str = str(raw_time_sig).split('/')
                time_sig_list = [int(n_str), int(d_str)]
            except Exception:
                time_sig_list = None

        tempo_map = getattr(self, '_tempo_map', None)
        if tempo_map is None:
            import numpy as np
            bpm = float(options.get('tempo', 120))
            beat_times = np.array([i * 60.0 / bpm for i in range(800)])
            tempo_map = TempoMap(
                beat_times=beat_times,
                downbeat_times=beat_times[::4],
                estimated_meter=tuple(time_sig_list or [4, 4]),
                global_bpm=bpm,
                method='fallback'
            )

        build_options = {
            'detect_key':      key_override is None,
            'detect_tempo':    detect_tempo_flag,   # BPM uniquement
            'detect_meter':    detect_meter_flag,   # mesure uniquement
            'write_chord_symbols': True,
            'detect_dynamics': True,
        }
        if time_sig_list is not None:
            build_options['time_sig'] = time_sig_list

        return build_score(
            voices=voice_split,
            tempo_map=tempo_map,
            key_sig=key_override or 'C',
            options=build_options,
            harmonic_ctx=harmonic_ctx,
            pedals=pedals or [],
        )

    def _export(self, score_data: dict, options: dict) -> dict[str, str]:
        """Exporte la partition dans les formats demandés"""
        from backend.exporters import export_all_formats

        formats = options.get("export_formats", ["pdf", "midi", "musicxml"])
        output_dir = options.get("output_dir", "outputs")
        base_name = options.get("base_name", "transcription")

        # score_data contient la partition construite; export_all_formats
        # attend score_data directement (plus voice_split séparément).
        return export_all_formats(score_data, output_dir, base_name, formats)

    # ─────────────────────────────────────────────────────────────────────────
    # Contrôle du pipeline
    # ─────────────────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Annule le pipeline en cours"""
        self._cancelled = True
        self._pause_event.set()  # Débloquer si en pause

    def pause(self) -> None:
        """Met le pipeline en pause"""
        self._paused = True
        self._pause_event.clear()

    def resume(self) -> None:
        """Reprend le pipeline après pause"""
        self._paused = False
        self._pause_event.set()

    @property
    def is_running(self) -> bool:
        return self._start_time > 0 and not self._cancelled

    @property
    def is_paused(self) -> bool:
        return self._paused


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline avec progression SSE (Server-Sent Events)
# ─────────────────────────────────────────────────────────────────────────────

class SSEPipeline(AsyncPipeline):
    """
    Pipeline qui émet la progression via un générateur asynchrone
    compatible Server-Sent Events (SSE).
    """

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config, progress_callback=None)
        self._progress_queue: asyncio.Queue = asyncio.Queue()
        self.progress_callback = self._queue_progress

    async def _queue_progress(self, progress: PipelineProgress) -> None:
        """Met la progression dans la queue pour SSE"""
        await self._progress_queue.put(progress)

    async def progress_stream(self) -> AsyncGenerator[str, None]:
        """
        Générateur asynchrone pour SSE.
        Yield des lignes formatées: "data: {json}\n\n"
        """
        import json

        # Envoyer un heartbeat initial
        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"

        while True:
            try:
                # Attendre la progression avec timeout pour heartbeat
                progress = await asyncio.wait_for(
                    self._progress_queue.get(),
                    timeout=15.0  # Heartbeat interval
                )

                data = {
                    "type": "progress",
                    "stage": progress.stage.value,
                    "stage_index": progress.stage_index,
                    "total_stages": progress.total_stages,
                    "percent": round(progress.percent, 1),
                    "message": progress.message,
                    "elapsed": round(progress.elapsed_seconds, 1),
                    "stage_elapsed": round(progress.stage_elapsed_seconds, 1),
                    "metadata": progress.metadata,
                }
                yield f"data: {json.dumps(data)}\n\n"

                if progress.is_complete or progress.is_error:
                    break

            except asyncio.TimeoutError:
                # Heartbeat
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"

    async def run_with_sse(
        self,
        audio_path: str,
        options: dict,
    ) -> tuple[PipelineResult, AsyncGenerator[str, None]]:
        """
        Lance le pipeline et retourne le résultat + le stream SSE.

        Usage:
            pipeline = SSEPipeline(config)
            result, stream = await pipeline.run_with_sse(audio_path, options)
            async for event in stream:
                send_to_client(event)
        """
        # Lancer le pipeline en arrière-plan
        task = asyncio.create_task(self.run(audio_path, options))

        # Retourner le stream immédiatement
        stream = self.progress_stream()

        # Attendre la fin du pipeline
        result = await task

        return result, stream


# ─────────────────────────────────────────────────────────────────────────────
# Fonction utilitaire pour exécution simple
# ─────────────────────────────────────────────────────────────────────────────

async def run_transcription_pipeline(
    audio_path: str,
    options: dict,
    config: Optional[Any] = None,
    progress_callback: Optional[ProgressCallback] = None,
    timeout_per_stage: float = 300.0,
) -> PipelineResult:
    """
    Fonction utilitaire pour lancer une transcription complète.

    Args:
        audio_path: Chemin du fichier audio
        options: Options de transcription
        config: Configuration optionnelle
        progress_callback: Callback optionnel pour la progression
        timeout_per_stage: Timeout par étape en secondes

    Returns:
        PipelineResult
    """
    pipeline = AsyncPipeline(config, progress_callback, timeout_per_stage)
    return await pipeline.run(audio_path, options)


def run_transcription_sync(
    audio_path: str,
    options: dict,
    config: Optional[Any] = None,
    progress_callback: Optional[ProgressCallback] = None,
    timeout_per_stage: float = 300.0,
) -> PipelineResult:
    """
    Version synchrone pour compatibilité avec l'ancien code.
    """
    return asyncio.run(run_transcription_pipeline(audio_path, options, config, progress_callback, timeout_per_stage))