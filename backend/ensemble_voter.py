"""
ensemble_voter.py — Ensemble voting entre plusieurs modèles de transcription
Combine les prédictions de piano_transcription, transkun, hft par vote majoritaire pondéré.

Source unique de vérité pour la logique d'ensemble voting.
"""
from __future__ import annotations

import os
import time
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Classes de données
# ─────────────────────────────────────────────────────────────────────────

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
        ModelWeight("transkun", weight=1.3, onset_weight=1.1, pitch_weight=1.1, duration_weight=1.1),
    ],
    onset_tolerance=0.05,
    pitch_tolerance=1,
    min_votes=2,
    velocity_aggregation="weighted_mean",
    duration_aggregation="median",
)


# ─────────────────────────────────────────────────────────────────────────
# Chargement config depuis config.yaml
# ─────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────
# Vote d'ensemble (utilitaire - utilisé par ensemble_vote ci-dessous)
# ─────────────────────────────────────────────────────────────────────────

def ensemble_vote(
    model_predictions: Dict[str, List[Tuple[float, int, float, float]]],
    config: Optional[EnsembleConfig] = None,
) -> List[Tuple[float, int, float, float]]:
    """
    Vote d'ensemble entre plusieurs modèles de transcription.
    
    Version simplifiée pour usage unitaire. Pour le pipeline complet,
    utiliser run_ensemble_transcription().
    """
    if config is None:
        config = DEFAULT_ENSEMBLE_CONFIG
    
    if not model_predictions:
        return []
    
    active_models = {k: v for k, v in model_predictions.items() if v}
    if not active_models:
        return []
    
    if len(active_models) == 1:
        return list(active_models.values())[0]
    
    logger.info(f"[Ensemble] Vote entre {len(active_models)} modèles: {list(active_models.keys())}")
    
    all_notes = []
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
    
    clusters = _cluster_notes(all_notes, config)
    
    voted_notes = []
    for cluster in clusters:
        voted = _vote_cluster(cluster, config)
        if voted is not None:
            voted_notes.append(voted)
    
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
    
    notes_sorted = sorted(notes, key=lambda n: n["onset"])
    
    clusters = []
    current_cluster = [notes_sorted[0]]
    
    for note in notes_sorted[1:]:
        last = current_cluster[-1]
        
        onset_diff = abs(note["onset"] - last["onset"])
        pitch_diff = abs(note["pitch"] - last["pitch"])
        
        if onset_diff <= config.onset_tolerance and pitch_diff <= config.pitch_tolerance:
            current_cluster.append(note)
        else:
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
        max_weight = max(n["weight"] for n in cluster)
        if max_weight >= 1.5:
            best = max(cluster, key=lambda n: n["weight"])
            return (best["onset"], best["pitch"], best["duration"], best["velocity"])
        return None
    
    pitch_votes = defaultdict(float)
    for note in cluster:
        pitch_votes[note["pitch"]] += note["weight"] * note["pitch_weight"]
    
    winning_pitch = max(pitch_votes, key=pitch_votes.get)
    winning_notes = [n for n in cluster if n["pitch"] == winning_pitch]
    
    onset_num = sum(n["onset"] * n["weight"] * n["onset_weight"] for n in winning_notes)
    onset_den = sum(n["weight"] * n["onset_weight"] for n in winning_notes)
    voted_onset = onset_num / onset_den if onset_den > 0 else winning_notes[0]["onset"]
    
    if config.duration_aggregation == "median":
        durations = [n["duration"] for n in winning_notes]
        voted_duration = float(np.median(durations))
    elif config.duration_aggregation == "weighted_mean":
        dur_num = sum(n["duration"] * n["weight"] * n["duration_weight"] for n in winning_notes)
        dur_den = sum(n["weight"] * n["duration_weight"] for n in winning_notes)
        voted_duration = dur_num / dur_den if dur_den > 0 else winning_notes[0]["duration"]
    else:
        voted_duration = float(np.mean([n["duration"] for n in winning_notes]))
    
    velocities = [n["velocity"] for n in winning_notes]
    weights = [n["weight"] for n in winning_notes]
    
    if config.velocity_aggregation == "max":
        voted_velocity = max(velocities)
    elif config.velocity_aggregation == "weighted_mean":
        vel_num = sum(n["velocity"] * n["weight"] for n in winning_notes)
        vel_den = sum(n["weight"] for n in winning_notes)
        voted_velocity = vel_num / vel_den if vel_den > 0 else winning_notes[0]["velocity"]
    else:
        voted_velocity = float(np.mean(velocities))
    
    return (voted_onset, winning_pitch, voted_duration, voted_velocity)


# ─────────────────────────────────────────────────────────────────────────
# Détection runtime des modèles disponibles
# ─────────────────────────────────────────────────────────────────────────

def detect_available_ensemble_models() -> dict:
    """
    Détecte à runtime quels modèles d'ensemble sont réellement utilisables.
    
    Returns:
        dict: {model_name: bool} indiquant la disponibilité
    """
    import importlib
    availability = {
        'piano_transcription': False,
        'basic_pitch': False,
        'transkun': False,
        'hft': False,
        'mt3': False,
    }
    try:
        importlib.import_module('piano_transcription_inference')
        availability['piano_transcription'] = True
    except ImportError:
        pass
    try:
        importlib.import_module('basic_pitch.inference')
        availability['basic_pitch'] = True
    except ImportError:
        pass
    try:
        importlib.import_module('transkun')
        availability['transkun'] = True
    except ImportError:
        pass
    try:
        importlib.import_module('run_hft')
        availability['hft'] = True
    except (ImportError, ModuleNotFoundError):
        pass
    mt3_path = os.environ.get('MT3_PATH', '/mt3')
    availability['mt3'] = os.path.isdir(mt3_path)
    return availability


# ─────────────────────────────────────────────────────────────────────────
# Résultat fusionné
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class FusedResult:
    """Résultat fusionné du mode ensemble."""
    notes: List[Tuple[float, int, float, int]]
    midi: Any
    pedals: List[Tuple[float, float]]
    uncertain_ids: set


# ─────────────────────────────────────────────────────────────────────────
# Transcription ensemble complète (pipeline principal)
# ─────────────────────────────────────────────────────────────────────────

def run_ensemble_transcription(
    audio_path: str,
    options: Dict[str, Any],
) -> FusedResult:
    """
    Exécute la transcription en mode ensemble (vote multi-modèles).
    Auto-détection des modèles disponibles + filtrage transparent.
    
    Args:
        audio_path: Chemin vers le fichier audio
        options: Dictionnaire d'options (contient 'ensemble' pour config)
        
    Returns:
        FusedResult avec .notes, .midi, .pedals, .uncertain_ids
    """
    import pretty_midi
    from collections import defaultdict
    
    t0 = time.perf_counter()
    
    ensemble_config = options.get('ensemble', {})
    
    # Configuration par défaut des modèles (poids)
    default_models = [
        {'name': 'piano_transcription', 'weight': 1.5, 'onset_weight': 1.2, 'pitch_weight': 1.0, 'duration_weight': 1.0},
        {'name': 'transkun',           'weight': 1.3, 'onset_weight': 1.1, 'pitch_weight': 1.1, 'duration_weight': 1.1},
    ]
    models_config = ensemble_config.get('models', default_models)

    # PHASE 3 : filtrer selon la dispo réelle des modèles
    availability = detect_available_ensemble_models()
    logger.info(f"[Ensemble] Modèles disponibles: {list(k for k, v in availability.items() if v)}")

    filtered_models = [m for m in models_config if availability.get(m['name'], False)]
    if len(filtered_models) < len(models_config):
        skipped = [m['name'] for m in models_config if not availability.get(m['name'], False)]
        logger.warning(f"[Ensemble] Modèles indisponibles, ignorés: {skipped}")

    if not filtered_models:
        raise RuntimeError(
            "Ensemble impossible : aucun modèle installé. "
            "Vérifie : pip install piano_transcription_inference transkun"
        )

    if len(filtered_models) < 2:
        logger.info(f"[Ensemble] Un seul modèle dispo ({filtered_models[0]['name']}), bascule sur mode single-model.")
        # Résolution paresseuse pour éviter imports circulaires
        if filtered_models[0]['name'] == 'piano_transcription':
            from transcriber import run_piano_transcription
            note_events, midi_data, pedal_intervals = run_piano_transcription(audio_path, options)
            return FusedResult(notes=note_events, midi=midi_data, pedals=pedal_intervals, uncertain_ids=set())
        elif filtered_models[0]['name'] == 'transkun':
            from transcriber import run_transkun
            note_events, midi_data, pedal_intervals = run_transkun(audio_path, options)
            return FusedResult(notes=note_events, midi=midi_data, pedals=pedal_intervals, uncertain_ids=set())
        elif filtered_models[0]['name'] == 'basic_pitch':
            from transcriber import run_basic_pitch
            note_events, midi_data, pedal_intervals = run_basic_pitch(audio_path, options)
            return FusedResult(notes=note_events, midi=midi_data, pedals=pedal_intervals, uncertain_ids=set())
        elif filtered_models[0]['name'] == 'mt3':
            from transcriber import run_mt3
            note_events, midi_data, pedal_intervals = run_mt3(audio_path, options)
            return FusedResult(notes=note_events, midi=midi_data, pedals=pedal_intervals, uncertain_ids=set())
        raise RuntimeError(f"Modèle {filtered_models[0]['name']} non implémenté pour fallback")

    models_config = filtered_models

    # ── Onset tolerance adaptatif proportionnel au tempo local ──
    base_onset_tolerance = ensemble_config.get('onset_tolerance', 0.04)
    base_pitch_tolerance = ensemble_config.get('pitch_tolerance', 1)
    min_votes = ensemble_config.get('min_votes', 2)
    velocity_aggregation = ensemble_config.get('velocity_aggregation', 'weighted_mean')
    duration_aggregation = ensemble_config.get('duration_aggregation', 'median')
    
    def _adaptive_onset_tolerance(bpm: float) -> float:
        """Retourne le onset_tolerance adapté au BPM local."""
        if bpm <= 0:
            return base_onset_tolerance
        beat_duration = 60.0 / bpm
        tolerance = max(0.02, min(0.10, beat_duration * 0.04))
        return tolerance
    
    # Exécuter chaque modèle
    all_model_results = {}
    
    for model_cfg in models_config:
        model_name = model_cfg['name']
        
        # Résolution paresseuse des fonctions
        if model_name == 'piano_transcription':
            from transcriber import run_piano_transcription as _fn
            model_functions = {'piano_transcription': _fn}
        elif model_name == 'transkun':
            from transcriber import run_transkun as _fn
            model_functions = {'transkun': _fn}
        elif model_name == 'basic_pitch':
            from transcriber import run_basic_pitch as _fn
            model_functions = {'basic_pitch': _fn}
        elif model_name == 'mt3':
            from transcriber import run_mt3 as _fn
            model_functions = {'mt3': _fn}
        elif model_name == 'hft':
            from run_hft import run_hft as _fn
            model_functions = {'hft': _fn}
        else:
            logger.warning(f"[Ensemble] Modèle '{model_name}' non implémenté")
            continue
        
        if model_name not in model_functions:
            logger.warning(f"[Ensemble] Modèle '{model_name}' non disponible")
            continue
        
        logger.info(f"[Ensemble] Exécution du modèle: {model_name} (poids: {model_cfg['weight']})")
        try:
            model_options = options.copy()
            note_events, midi_data, pedal_intervals = model_functions[model_name](audio_path, model_options)
            all_model_results[model_name] = {
                'notes': note_events,
                'midi': midi_data,
                'pedal': pedal_intervals,
                'weight': model_cfg['weight'],
                'onset_weight': model_cfg.get('onset_weight', 1.0),
                'pitch_weight': model_cfg.get('pitch_weight', 1.0),
                'duration_weight': model_cfg.get('duration_weight', 1.0),
            }
            logger.info(f"[Ensemble]   → {len(note_events)} notes détectées")
        except Exception as e:
            logger.error(f"[Ensemble] Erreur modèle {model_name}: {e}")
            continue
    
    if not all_model_results:
        raise RuntimeError("Aucun modèle n'a réussi à transcrire l'audio")
    
    # ── FUSION PAR VOTE PONDÉRÉ ──────────────────────────────────────────────
    logger.info(f"[Ensemble] Fusion de {len(all_model_results)} modèles...")
    
    # Collecter toutes les notes de tous les modèles
    all_notes = []
    for model_name, result in all_model_results.items():
        w = result['weight']
        ow = result['onset_weight']
        pw = result['pitch_weight']
        dw = result['duration_weight']
        for note in result['notes']:
            onset, pitch, duration, velocity = note[:4]
            all_notes.append((onset, pitch, duration, velocity, model_name, w, ow, pw, dw))
    
    if not all_notes:
        raise RuntimeError("Aucune note détectée par aucun modèle")
    
    # BPM moyen pour adapter le tolérance
    onsets = [n[0] for n in all_notes]
    display_bpm = options.get('display_bpm', 120)
    avg_bpm = max(40, min(250, display_bpm))
    adaptive_tolerance = _adaptive_onset_tolerance(avg_bpm)
    adaptive_pitch_tolerance = base_pitch_tolerance
    
    logger.info(f"[Ensemble] onset_tolerance adaptatif = {adaptive_tolerance:.4f}s (BPM≈{avg_bpm})")
    
    # Grouper les notes similaires (clustering par onset + pitch)
    all_notes.sort(key=lambda x: (x[0], x[1]))
    
    clusters = []
    for note in all_notes:
        onset, pitch, duration, velocity, mname, mw, mow, mpw, mdw = note
        
        assigned = False
        for cluster in clusters:
            rep_onset = cluster['rep_onset']
            rep_pitch = cluster['rep_pitch']
            
            if abs(onset - rep_onset) <= adaptive_tolerance and abs(pitch - rep_pitch) <= adaptive_pitch_tolerance:
                cluster['notes'].append(note)
                assigned = True
                break
        
        if not assigned:
            clusters.append({
                'rep_onset': onset,
                'rep_pitch': pitch,
                'notes': [note]
            })
    
    # Filtrer les clusters par nombre minimum de votes
    valid_clusters = [c for c in clusters if len(c['notes']) >= min_votes]
    logger.info(f"[Ensemble] {len(clusters)} clusters formés, {len(valid_clusters)} retenus (min_votes={min_votes})")
    
    # Marquer les clusters "incertains" (< min_votes * 2 modèles)
    uncertain_clusters = [c for c in valid_clusters if len(c['notes']) < min_votes * 2]
    if uncertain_clusters:
        logger.info(f"[Ensemble] {len(uncertain_clusters)} cluster(s) incertain(s) détecté(s)")
    
    # Agréger chaque cluster valide
    fused_notes = []
    uncertain_notes = set()
    for idx, cluster in enumerate(valid_clusters):
        notes = cluster['notes']
        is_uncertain = len(notes) < min_votes
        
        if is_uncertain:
            logger.info(f"[Ensemble] cluster {idx} incertain — 1 seul modèle, fallback activé")
        
        # Onset: moyenne pondérée
        weighted_onset = sum(n[0] * n[6] * n[5] for n in notes) / sum(n[6] * n[5] for n in notes)
        
        # Pitch: vote majoritaire pondéré
        pitch_votes = defaultdict(float)
        for n in notes:
            pitch_votes[n[1]] += n[7] * n[5]
        fused_pitch = max(pitch_votes.items(), key=lambda x: x[1])[0]
        
        # Durée: selon méthode configurée
        if duration_aggregation == 'median':
            durations = [n[2] for n in notes]
            fused_duration = float(np.median(durations))
        elif duration_aggregation == 'mean':
            fused_duration = float(np.mean([n[2] for n in notes]))
        elif duration_aggregation == 'weighted_mean':
            fused_duration = sum(n[2] * n[8] * n[5] for n in notes) / sum(n[8] * n[5] for n in notes)
        else:
            fused_duration = float(np.median([n[2] for n in notes]))
        
        # Vélocité: selon méthode configurée
        velocities = [n[3] for n in notes]
        weights = [n[5] for n in notes]
        
        if velocity_aggregation == 'max':
            fused_velocity = max(velocities)
        elif velocity_aggregation == 'mean':
            fused_velocity = float(np.mean(velocities))
        elif velocity_aggregation == 'weighted_mean':
            fused_velocity = sum(v * w for v, w in zip(velocities, weights)) / sum(weights)
        else:
            fused_velocity = float(np.mean(velocities))
        
        fused_notes.append((
            weighted_onset,
            fused_pitch,
            fused_duration,
            int(round(fused_velocity)),
            is_uncertain
        ))
        if is_uncertain:
            uncertain_notes.add(len(fused_notes) - 1)
    
    # Trier par onset
    fused_notes.sort(key=lambda x: x[0])
    
    # Créer un objet MIDI fusionné
    primary_model = max(all_model_results.items(), key=lambda x: x[1]['weight'])[0]
    fused_midi = all_model_results[primary_model]['midi']
    
    if fused_midi:
        for inst in fused_midi.instruments:
            inst.notes.clear()
        
        for onset, pitch, duration, velocity, _ in fused_notes:
            note = pretty_midi.Note(
                velocity=min(127, max(0, velocity)),
                pitch=pitch,
                start=onset,
                end=onset + duration
            )
            if fused_midi.instruments:
                fused_midi.instruments[0].notes.append(note)
            else:
                piano = pretty_midi.Instrument(program=0, is_drum=False, name='Piano')
                piano.notes.append(note)
                fused_midi.instruments.append(piano)
    
    # ── Fusion des pédales multi-modèles ─────────────────────────────────────
    all_pedal_intervals = []
    for model_name, result in all_model_results.items():
        model_pedals = result.get('pedal', [])
        model_weight = result['weight']
        for p_start, p_end in model_pedals:
            all_pedal_intervals.append((p_start, p_end, model_weight, model_name))
    
    pedal_tolerance = 0.05
    fused_pedals = []
    for p_start, p_end, weight, mname in all_pedal_intervals:
        assigned = False
        for i, (fp_start, fp_end, fp_weight, fp_models) in enumerate(fused_pedals):
            if abs(p_start - fp_start) <= pedal_tolerance and abs(p_end - fp_end) <= pedal_tolerance:
                fused_pedals[i] = (
                    (fp_start + p_start) / 2,
                    (fp_end + p_end) / 2,
                    fp_weight + weight,
                    fp_models + [mname],
                )
                assigned = True
                break
        if not assigned:
            fused_pedals.append((p_start, p_end, weight, [mname]))
    
    min_pedal_votes = min(2, len(all_model_results)) if len(all_model_results) > 1 else 1
    fused_pedals = [
        (ps, pe, w, models) for ps, pe, w, models in fused_pedals
        if len(models) >= min_pedal_votes
    ]
    fused_pedals = [(ps, pe) for ps, pe, _, _ in fused_pedals]
    
    logger.info(f"[Ensemble] {len(fused_pedals)} pédales fusionnées (multi-modèles)")
    
    dt = time.perf_counter() - t0
    logger.info(f"[Ensemble] Terminé en {dt:.2f}s — {len(fused_notes)} notes fusionnées")
    
    return FusedResult(notes=fused_notes, midi=fused_midi, pedals=fused_pedals, uncertain_ids=uncertain_notes)