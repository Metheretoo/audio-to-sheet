"""
ensemble_voter.py — Ensemble voting entre plusieurs modèles de transcription
Combine les prédictions de basic_pitch, piano_transcription, transkun, hft par vote majoritaire pondéré.
"""
from __future__ import annotations

import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModelWeight:
    """Poids d'un modèle dans l'ensemble"""
    name: str
    weight: float = 1.0
    onset_weight: float = 1.0
    pitch_weight: float = 1.0
    duration_weight: float = 1.0


@dataclass
class EnsembleConfig:
    """Configuration de l'ensemble voting"""
    models: List[ModelWeight]
    onset_tolerance: float = 0.05      # Tolérance temporelle pour grouper les notes (secondes)
    pitch_tolerance: int = 1           # Tolérance en demi-tons pour considérer même note
    min_votes: int = 2                 # Votes minimum pour garder une note
    velocity_aggregation: str = "max"  # "max" | "mean" | "weighted_mean"
    duration_aggregation: str = "median"  # "median" | "mean" | "weighted_mean"


DEFAULT_ENSEMBLE_CONFIG = EnsembleConfig(
    models=[
        ModelWeight("piano_transcription", weight=1.5, onset_weight=1.2, pitch_weight=1.0, duration_weight=1.0),
        ModelWeight("basic_pitch", weight=1.0, onset_weight=1.0, pitch_weight=1.0, duration_weight=0.8),
        ModelWeight("transkun", weight=1.3, onset_weight=1.1, pitch_weight=1.1, duration_weight=1.1),
        ModelWeight("hft", weight=1.2, onset_weight=1.0, pitch_weight=1.0, duration_weight=1.0),
    ],
    onset_tolerance=0.05,
    pitch_tolerance=1,
    min_votes=2,
    velocity_aggregation="weighted_mean",
    duration_aggregation="median",
)


def load_ensemble_config(config: Optional[Any] = None) -> EnsembleConfig:
    """Charge la config d'ensemble depuis config.yaml ou utilise les défauts"""
    if config and hasattr(config, "transcriber") and hasattr(config.transcriber, "ensemble"):
        ens = config.transcriber.ensemble
        models = [
            ModelWeight(
                name=m.get("name", "piano_transcription"),
                weight=m.get("weight", 1.0),
                onset_weight=m.get("onset_weight", 1.0),
                pitch_weight=m.get("pitch_weight", 1.0),
                duration_weight=m.get("duration_weight", 1.0),
            )
            for m in ens.get("models", [])
        ]
        return EnsembleConfig(
            models=models,
            onset_tolerance=ens.get("onset_tolerance", 0.05),
            pitch_tolerance=ens.get("pitch_tolerance", 1),
            min_votes=ens.get("min_votes", 2),
            velocity_aggregation=ens.get("velocity_aggregation", "weighted_mean"),
            duration_aggregation=ens.get("duration_aggregation", "median"),
        )
    return DEFAULT_ENSEMBLE_CONFIG


def ensemble_vote(
    model_predictions: Dict[str, List[Tuple[float, int, float, float]]],
    config: Optional[EnsembleConfig] = None,
) -> List[Tuple[float, int, float, float]]:
    """
    Vote d'ensemble entre plusieurs modèles de transcription.
    
    Args:
        model_predictions: Dict {model_name: [(onset, pitch, duration, velocity), ...]}
        config: Configuration de l'ensemble
        
    Returns:
        Liste de notes fusionnées: [(onset, pitch, duration, velocity), ...]
    """
    if config is None:
        config = DEFAULT_ENSEMBLE_CONFIG
    
    if not model_predictions:
        return []
    
    # Filtrer les modèles qui ont des prédictions
    active_models = {k: v for k, v in model_predictions.items() if v}
    if not active_models:
        return []
    
    if len(active_models) == 1:
        # Un seul modèle -> retourner ses prédictions
        return list(active_models.values())[0]
    
    logger.info(f"[Ensemble] Vote entre {len(active_models)} modèles: {list(active_models.keys())}")
    
    # 1. Collecter toutes les notes de tous les modèles
    all_notes = []  # (model_name, onset, pitch, duration, velocity, model_weight)
    model_weights = {mw.name: mw for mw in config.models}
    
    for model_name, notes in active_models.items():
        weight = model_weights.get(model_name, ModelWeight(model_name, 1.0))
        for onset, pitch, duration, velocity in notes:
            all_notes.append({
                "model": model_name,
                "onset": onset,
                "pitch": pitch,
                "duration": duration,
                "velocity": velocity,
                "weight": weight.weight,
                "onset_weight": weight.onset_weight,
                "pitch_weight": weight.pitch_weight,
                "duration_weight": weight.duration_weight,
            })
    
    if not all_notes:
        return []
    
    # 2. Grouper les notes similaires (clustering par onset + pitch)
    clusters = _cluster_notes(all_notes, config)
    
    # 3. Voter dans chaque cluster
    voted_notes = []
    for cluster in clusters:
        voted = _vote_cluster(cluster, config)
        if voted is not None:
            voted_notes.append(voted)
    
    # 4. Trier par onset
    voted_notes.sort(key=lambda x: x[0])
    
    logger.info(f"[Ensemble] {len(all_notes)} notes brutes -> {len(voted_notes)} notes après vote")
    return voted_notes


def _cluster_notes(
    notes: List[Dict],
    config: EnsembleConfig,
) -> List[List[Dict]]:
    """Groupe les notes par proximité temporelle et hauteur"""
    if not notes:
        return []
    
    # Trier par onset
    notes_sorted = sorted(notes, key=lambda n: n["onset"])
    
    clusters = []
    current_cluster = [notes_sorted[0]]
    
    for note in notes_sorted[1:]:
        last = current_cluster[-1]
        
        # Vérifier si la note appartient au cluster courant
        onset_diff = abs(note["onset"] - last["onset"])
        pitch_diff = abs(note["pitch"] - last["pitch"])
        
        if onset_diff <= config.onset_tolerance and pitch_diff <= config.pitch_tolerance:
            current_cluster.append(note)
        else:
            # Nouveau cluster
            clusters.append(current_cluster)
            current_cluster = [note]
    
    if current_cluster:
        clusters.append(current_cluster)
    
    return clusters


def _vote_cluster(
    cluster: List[Dict],
    config: EnsembleConfig,
) -> Optional[Tuple[float, int, float, float]]:
    """Vote majoritaire pondéré dans un cluster de notes similaires"""
    if len(cluster) < config.min_votes:
        # Pas assez de votes, mais on peut garder si un modèle fort
        max_weight = max(n["weight"] for n in cluster)
        if max_weight >= 1.5:  # Modèle fort seul
            best = max(cluster, key=lambda n: n["weight"])
            return (best["onset"], best["pitch"], best["duration"], best["velocity"])
        return None
    
    # Compter les votes par pitch (arrondi)
    pitch_votes = defaultdict(float)
    for note in cluster:
        pitch_votes[note["pitch"]] += note["weight"] * note["pitch_weight"]
    
    # Pitch gagnant
    winning_pitch = max(pitch_votes, key=pitch_votes.get)
    winning_votes = pitch_votes[winning_pitch]
    total_votes = sum(pitch_votes.values())
    
    # Filtrer les notes du pitch gagnant
    winning_notes = [n for n in cluster if n["pitch"] == winning_pitch]
    
    # Agréger onset (moyenne pondérée par onset_weight)
    onset_num = sum(n["onset"] * n["weight"] * n["onset_weight"] for n in winning_notes)
    onset_den = sum(n["weight"] * n["onset_weight"] for n in winning_notes)
    voted_onset = onset_num / onset_den if onset_den > 0 else winning_notes[0]["onset"]
    
    # Agréger duration
    if config.duration_aggregation == "median":
        durations = [n["duration"] for n in winning_notes]
        voted_duration = float(np.median(durations))
    elif config.duration_aggregation == "weighted_mean":
        dur_num = sum(n["duration"] * n["weight"] * n["duration_weight"] for n in winning_notes)
        dur_den = sum(n["weight"] * n["duration_weight"] for n in winning_notes)
        voted_duration = dur_num / dur_den if dur_den > 0 else winning_notes[0]["duration"]
    else:  # mean
        voted_duration = float(np.mean([n["duration"] for n in winning_notes]))
    
    # Agréger velocity
    if config.velocity_aggregation == "max":
        voted_velocity = max(n["velocity"] for n in winning_notes)
    elif config.velocity_aggregation == "weighted_mean":
        vel_num = sum(n["velocity"] * n["weight"] for n in winning_notes)
        vel_den = sum(n["weight"] for n in winning_notes)
        voted_velocity = vel_num / vel_den if vel_den > 0 else winning_notes[0]["velocity"]
    else:  # mean
        voted_velocity = float(np.mean([n["velocity"] for n in winning_notes]))
    
    return (voted_onset, winning_pitch, voted_duration, voted_velocity)


def run_ensemble_transcription(
    audio_path: str,
    model_names: List[str],
    options: Dict[str, Any],
    config: Optional[Any] = None,
) -> Tuple[List[Tuple[float, int, float, float]], Dict[str, Any]]:
    """
    Lance la transcription avec plusieurs modèles et fait le vote d'ensemble.
    
    Returns:
        (note_events_fusionnés, metadata)
    """
    from backend.transcriber import transcribe_audio
    
    all_predictions = {}
    metadata = {"models_run": [], "models_failed": [], "raw_counts": {}}
    
    for model_name in model_names:
        try:
            model_options = options.copy()
            model_options["transcriber"] = model_name
            
            note_events, midi_data, pedal_intervals, tempo, warnings = transcribe_audio(audio_path, model_options)
            
            if note_events:
                # Convertir en format standard (onset, pitch, duration, velocity)
                # note_events format: (onset, pitch, duration, velocity) ou (onset, pitch, duration, velocity, ...)
                standardized = []
                for ev in note_events:
                    if len(ev) >= 4:
                        onset, pitch, duration, velocity = ev[:4]
                        # Normaliser velocity si > 1
                        if velocity > 1.0:
                            velocity = velocity / 127.0
                        standardized.append((onset, int(pitch), float(duration), float(velocity)))
                
                all_predictions[model_name] = standardized
                metadata["models_run"].append(model_name)
                metadata["raw_counts"][model_name] = len(standardized)
                logger.info(f"[Ensemble] {model_name}: {len(standardized)} notes")
            else:
                metadata["models_failed"].append(model_name)
                logger.warning(f"[Ensemble] {model_name}: aucune note détectée")
                
        except Exception as e:
            metadata["models_failed"].append(model_name)
            logger.error(f"[Ensemble] {model_name} a échoué: {e}")
    
    if not all_predictions:
        raise RuntimeError("Tous les modèles ont échoué")
    
    # Vote d'ensemble
    ensemble_config = load_ensemble_config(config)
    fused_notes = ensemble_vote(all_predictions, ensemble_config)
    
    metadata["fused_count"] = len(fused_notes)
    metadata["ensemble_config"] = {
        "models": [m.name for m in ensemble_config.models],
        "min_votes": ensemble_config.min_votes,
        "onset_tolerance": ensemble_config.onset_tolerance,
    }
    
    return fused_notes, metadata