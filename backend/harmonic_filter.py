"""
harmonic_filter.py — Filtrage des harmoniques pour piano classique.

Les transcripteurs IA (Transkun, Piano Transcription) détectent souvent
des "notes fantômes" causées par :
  1. Les harmoniques : une note grave jouée avec pédale crée des harmoniques
     à l'octave (+12 demi-tons) et quinte (+7 demi-tons)
  2. Les fantômes : des notes à des fréquences voisines détectées par erreur
  3. Les notes de pédale : des notes jouées sans être attaquées

Ce module filtre ces artefacts en se basant sur :
  - L'intervalle entre notes (octave, quinte)
  - La vélocité relative (les harmoniques ont une vélocité plus faible)
  - La simultanéité temporelle (notes jouées au même moment)
  - Le registre (les basses créent plus d'harmoniques)

Algorithmes disponibles :
  - filter_harmonics_basic() : filtrage simple (octave + quinte)
  - filter_harmonics_classical() : filtrage avancé pour piano classique
  - filter_harmonics_aggressive() : filtrage agressif (mazurkas, nocturnes)
"""

import numpy as np
from typing import List, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

# Intervalle harmonique standard (en demi-tons)
OCTAVE_INTERVAL = 12
QUINTHE_INTERVAL = 7
QUARTHE_INTERVAL = 5

# Seuil de vélocité pour les harmoniques
# Si une note a une vélocité < ce seuil ET est à un intervalle harmonique
# d'une note principale avec vélocité forte → c'est un harmonique
HARMONIC_VELOCITY_RATIO = 0.5

# Tolérance temporelle pour considérer deux notes comme simultanées (secondes)
SIMULTANEITY_TOLERANCE = 0.05

# Seuil de vélocité minimale pour considérer une note comme "principale"
MIN_MAIN_VELOCITY = 0.3

# Registre des basses (notes MIDI < 36 = C1)
BASS_THRESHOLD = 36


def is_harmonic_of(pitch: int, main_pitch: int) -> Optional[int]:
    """
    Vérifie si `pitch` est un harmonique de `main_pitch`.
    
    Returns:
        L'intervalle en demi-tons si c'est un harmonique (12=octave, 7=quinte, 5=quarte),
        None sinon.
    """
    interval = pitch - main_pitch
    if interval == OCTAVE_INTERVAL or interval == -OCTAVE_INTERVAL:
        return interval
    if interval == QUINTHE_INTERVAL or interval == -QUINTHE_INTERVAL:
        return interval
    if interval == QUARTHE_INTERVAL or interval == -QUARTHE_INTERVAL:
        return interval
    # Double octave
    if interval == OCTAVE_INTERVAL * 2 or interval == -OCTAVE_INTERVAL * 2:
        return interval
    return None


def filter_ghost_notes(
    notes: List[Dict],
    options: Optional[Dict] = None,
    method: str = "classical"
) -> List[Dict]:
    """
    Filtrage principal des harmoniques pour piano classique.
    
    Args:
        notes: Liste de dicts avec clés 'onset', 'pitch', 'duration', 'velocity'
        options: Options de filtrage
        method: 'basic', 'classical', 'aggressive'
    
    Returns:
        Liste de notes filtrées
    """
    if not notes or len(notes) <= 3:
        return notes
    
    options = options or {}
    
    if method == "basic":
        return _filter_basic(notes, options)
    elif method == "classical":
        return _filter_classical(notes, options)
    elif method == "aggressive":
        return _filter_aggressive(notes, options)
    else:
        return _filter_classical(notes, options)


def _filter_basic(notes: List[Dict], options: Dict) -> List[Dict]:
    """
    Filtrage basique : supprime les harmoniques à l'octave avec faible vélocité.
    """
    kept = []
    for note in notes:
        is_harmonic = False
        for other in notes:
            if other is note:
                continue
            interval = is_harmonic_of(note['pitch'], other['pitch'])
            if interval is None:
                continue
            # other est la note principale si :
            # - velocity de other > velocity de note * ratio
            # - les deux sont simultanées
            if (other['velocity'] > note['velocity'] * HARMONIC_VELOCITY_RATIO and
                abs(note['onset'] - other['onset']) < SIMULTANEITY_TOLERANCE):
                # L'harmonique est dans les aigus → supprimer
                if note['pitch'] > other['pitch']:
                    is_harmonic = True
                    break
        if not is_harmonic:
            kept.append(note)
    
    print(f"[HarmonicFilter] basic: {len(notes)} → {len(kept)} notes")
    return kept


def _filter_classical(notes: List[Dict], options: Dict) -> List[Dict]:
    """
    Filtrage classique pour piano :
    
    Règles :
    1. Si une note dans les basses (pitch < 36) a velocity > 0.4
       → ses harmoniques à l'octave/quinte avec velocity < 0.3 sont supprimés
    2. Si deux notes sont simultanées et à un intervalle harmonique
       → la plus faible est supprimée
    3. Les notes avec velocity > 0.6 sont protégées (attaques fortes)
    """
    kept = []
    removed_indices = set()
    
    # Trouver les notes principales (basses fortes)
    main_notes = []
    for i, note in enumerate(notes):
        if note['velocity'] >= MIN_MAIN_VELOCITY:
            main_notes.append((i, note))
    
    # Trier par vélocité décroissante pour prioriser les notes fortes
    main_notes.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        is_harmonic = False
        harmonic_of = None
        
        for main_idx, main_note in main_notes:
            if main_idx == i:
                continue
            
            # Protéger les notes très fortes (attaques)
            if main_note['velocity'] > 0.75:
                continue
            
            interval = is_harmonic_of(note['pitch'], main_note['pitch'])
            if interval is None:
                continue
            
            # Vérifier la simultanéité
            time_diff = abs(note['onset'] - main_note['onset'])
            if time_diff > SIMULTANEITY_TOLERANCE:
                continue
            
            # Notes dans la même mesure (même temps approximatif)
            # et intervalle harmonique détecté
            
            # Règle 1 : note dans les basses → harmoniques supprimés
            if main_note['pitch'] < BASS_THRESHOLD and main_note['velocity'] > 0.4:
                if note['pitch'] > main_note['pitch'] and note['velocity'] < main_note['velocity'] * 0.6:
                    is_harmonic = True
                    harmonic_of = main_idx
                    break
            
            # Règle 2 : forte différence de vélocité
            if main_note['velocity'] > 0.5 and note['velocity'] < main_note['velocity'] * 0.4:
                if abs(note['onset'] - main_note['onset']) < SIMULTANEITY_TOLERANCE:
                    is_harmonic = True
                    harmonic_of = main_idx
                    break
        
        if is_harmonic:
            removed_indices.add(i)
        else:
            kept.append(note)
    
    print(f"[HarmonicFilter] classical: {len(notes)} → {len(kept)} notes ({len(notes) - len(kept)} harmoniques supprimés)")
    return kept


def _filter_aggressive(notes: List[Dict], options: Dict) -> List[Dict]:
    """
    Filtrage agressif pour partitions complexes (Chopin, mazurkas, nocturnes).
    
    Règles renforcées :
    1. Toutes les notes dans les basses avec velocity > 0.3 créent un "champ protecteur"
    2. Les harmoniques à l'octave/quinte/quarte avec velocity < 0.35 sont supprimés
    3. Les notes simultanées (tolérance 80ms) sont analysées
    4. Protection minimale : notes avec velocity > 0.7 ou duration > 1.5s
    """
    kept = []
    removed_indices = set()
    
    # Trouver les notes basses (champs protecteurs)
    bass_notes = []
    for i, note in enumerate(notes):
        if note['pitch'] < BASS_THRESHOLD and note['velocity'] > 0.3:
            bass_notes.append((i, note))
    
    # Trier par vélocité décroissante
    bass_notes.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        # Protection : notes très fortes ou très longues (attaques expressives)
        if note['velocity'] > 0.7 or note['duration'] > 1.5:
            kept.append(note)
            continue
        
        is_harmonic = False
        
        for main_idx, main_note in bass_notes:
            if main_idx == i:
                continue
            
            interval = is_harmonic_of(note['pitch'], main_note['pitch'])
            if interval is None:
                continue
            
            # Vérifier la simultanéité (tolérance augmentée pour pédale)
            time_diff = abs(note['onset'] - main_note['onset'])
            if time_diff > 0.08:  # 80ms pour tolérer le délai de pédale
                continue
            
            # Champ protecteur : si main_note est basse et assez forte
            if (main_note['velocity'] > 0.35 and 
                note['pitch'] > main_note['pitch'] and
                note['velocity'] < main_note['velocity'] * 0.5):
                is_harmonic = True
                break
            
            # Règle supplémentaire : harmoniques doubles
            # Si note est à +12 demi-tons d'une basse ET à +7 d'une autre
            # → très probablement un harmonique
            is_double_harmonic = False
            for other_idx, other_note in bass_notes:
                if other_idx == main_idx or other_idx == i:
                    continue
                interval2 = is_harmonic_of(note['pitch'], other_note['pitch'])
                if interval2 is not None and interval != interval2:
                    # Harmonique double détecté
                    if note['velocity'] < 0.3:
                        is_double_harmonic = True
                        break
            
            if is_double_harmonic:
                is_harmonic = True
                break
        
        if is_harmonic:
            removed_indices.add(i)
        else:
            kept.append(note)
    
    print(f"[HarmonicFilter] aggressive: {len(notes)} → {len(kept)} notes ({len(notes) - len(kept)} harmoniques supprimés)")
    return kept


def get_harmonic_analysis(notes: List[Dict]) -> Dict:
    """
    Analyse les harmoniques présents dans les notes sans les supprimer.
    
    Returns:
        Dict avec :
        - total_notes: nombre total de notes
        - potential_harmonics: nombre de notes potentiellement harmoniques
        - bass_notes: nombre de notes dans les basses
        - simultaneous_chords: nombre d'accords simultanés
    """
    if not notes:
        return {
            'total_notes': 0,
            'potential_harmonics': 0,
            'bass_notes': 0,
            'simultaneous_chords': 0,
        }
    
    bass_count = sum(1 for n in notes if n['pitch'] < BASS_THRESHOLD)
    
    # Compter les notes simultanées (accords)
    simultaneous = 0
    for i, n1 in enumerate(notes):
        for j, n2 in enumerate(notes):
            if j <= i:
                continue
            if abs(n1['onset'] - n2['onset']) < SIMULTANEITY_TOLERANCE:
                simultaneous += 1
                break
    
    # Compter les harmoniques potentiels
    harmonics = 0
    for i, note in enumerate(notes):
        for j, other in enumerate(notes):
            if j == i:
                continue
            if is_harmonic_of(note['pitch'], other['pitch']) is not None:
                if note['velocity'] < other['velocity'] * HARMONIC_VELOCITY_RATIO:
                    harmonics += 1
                    break
    
    return {
        'total_notes': len(notes),
        'potential_harmonics': harmonics,
        'bass_notes': bass_count,
        'simultaneous_chords': simultaneous,
    }


def filter_with_analysis(
    notes: List[Dict],
    options: Optional[Dict] = None,
    method: str = "classical"
) -> tuple:
    """
    Filtrage harmonique avec retour d'analyse.
    
    Returns:
        (notes_filtrees, analyse_avant, analyse_apres)
    """
    before = get_harmonic_analysis(notes)
    filtered = filter_ghost_notes(notes, options, method)
    after = get_harmonic_analysis(filtered)
    
    return filtered, before, after