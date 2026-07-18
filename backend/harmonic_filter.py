"""
harmonic_filter.py — Filtrage des harmoniques pour piano classique.

Les transcripteurs IA (Transkun, Piano Transcription) détectent souvent
des "notes fantômes" causées par :
  1. Les harmoniques de pédale : une note grave jouée avec pédale forte crée
     des harmoniques à l'octave (+12), quinte (+7), quarte (+5), et doubles
  2. Les fantômes : des notes à des fréquences voisines détectées par erreur
  3. Les notes de pédale : des notes jouées sans être attaquées mais prolongées

Ce module filtre ces artefacts en se basant sur :
  - L'intervalle entre notes (octave, quinte, quarte, doubles)
  - La vélocité relative (les harmoniques ont une vélocité plus faible)
  - La simultanéité temporelle (notes jouées au même moment)
  - Le registre (les basses créent plus d'harmoniques)
  - La durée (les harmoniques de pédale ont souvent des durées anormalement longues)

Algorithmes disponibles :
  - 'basic' : filtrage simple (octave + quinte)
  - 'classical' : filtrage avancé pour piano classique
  - 'classical-strong' : filtrage renforcé pour Chopin/Debussy
  - 'aggressive' : filtrage agressif (mazurkas, nocturnes, musique romantique)
  - 'pedal-aware' : filtrage spécialisé pour harmoniques de pédale
"""

import numpy as np
from typing import List, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

# Intervalle harmonique standard (en demi-tons)
OCTAVE_INTERVAL = 12
QUINTE_INTERVAL = 7
QUARTE_INTERVAL = 5
QUINTE_AUGMENTED = 8  # Quinte augmentée (pour certains harmoniques)
OCTAVE_DOUBLE = 24
SEVENTEENTH = 19  # Double octave + quinte (pour harmoniques complexes)

# Tous les intervalles harmoniques à rechercher
HARMONIC_INTERVALS = [
    OCTAVE_INTERVAL, -OCTAVE_INTERVAL,
    QUINTE_INTERVAL, -QUINTE_INTERVAL,
    QUARTE_INTERVAL, -QUARTE_INTERVAL,
    OCTAVE_DOUBLE, -OCTAVE_DOUBLE,
    SEVENTEENTH, -SEVENTEENTH,
]

# Tolérance élargie pour les harmoniques (post-quantization)
HARMONIC_TOLERANCE = 1

# Seuil de vélocité pour les harmoniques
HARMONIC_VELOCITY_RATIO = 0.45

# Tolérance temporelle pour la simultanéité (secondes)
SIMULTANEITY_TOLERANCE = 0.05
PEDAL_SIMULTANEITY_TOLERANCE = 0.12

# Seuil de vélocité minimale pour une note "principale"
MIN_MAIN_VELOCITY = 0.3

# Registre des basses (notes MIDI < 36 = C1)
BASS_THRESHOLD = 36

# Seuil de vélocité pour les harmoniques de pédale
PEDAL_HARMONIC_VELOCITY_MAX = 0.65
ULTRA_HARMONIC_VELOCITY_MAX = 0.75

# Protection : notes avec vélocité > seuil sont toujours conservées
PROTECTED_VELOCITY_THRESHOLD = 0.80

# Protection : notes avec duration > seuil sont des tenues expressives
PROTECTED_DURATION_THRESHOLD = 1.5

# Durée minimale pour un harmonique de pédale
MIN_PEDAL_HARMONIC_DURATION = 0.5

# Tolérance pour les harmoniques doubles
ULTRA_DOUBLE_HARMONIC_SOURCES = 1


def is_harmonic_of(pitch: int, main_pitch: int) -> Optional[int]:
    """Vérifie si `pitch` est un harmonique de `main_pitch`."""
    interval = pitch - main_pitch
    if interval in HARMONIC_INTERVALS:
        return interval
    for harmonic_interval in HARMONIC_INTERVALS:
        if abs(interval - harmonic_interval) <= HARMONIC_TOLERANCE:
            return harmonic_interval
    return None


def is_pedal_harmonic(note: Dict, main_note: Dict) -> bool:
    """Vérifie si `note` est un harmonique de pédale de `main_note`."""
    interval = is_harmonic_of(note['pitch'], main_note['pitch'])
    if interval is None:
        return False
    if main_note['pitch'] >= BASS_THRESHOLD:
        return False
    if main_note['velocity'] < 0.35:
        return False
    if note['pitch'] <= main_note['pitch']:
        return False
    time_diff = abs(note['onset'] - main_note['onset'])
    if time_diff > PEDAL_SIMULTANEITY_TOLERANCE:
        return False
    if note['velocity'] >= main_note['velocity'] * 0.45:
        if note['velocity'] < PEDAL_HARMONIC_VELOCITY_MAX and main_note['velocity'] > 0.5:
            pass
        else:
            return False
    if note['duration'] > 2.0 and note['velocity'] < 0.4:
        return True
    return True


def filter_ghost_notes(
    notes: List[Dict],
    options: Optional[Dict] = None,
    method: str = "classical"
) -> List[Dict]:
    """Filtrage principal des harmoniques pour piano classique."""
    if not notes or len(notes) <= 3:
        return notes
    
    options = options or {}
    
    if method == "basic":
        return _filter_basic(notes, options)
    elif method == "classical":
        return _filter_classical(notes, options)
    elif method == "classical-strong":
        return _filter_classical_strong(notes, options)
    elif method == "aggressive":
        return _filter_aggressive(notes, options)
    elif method == "pedal-aware":
        return _filter_pedal_aware(notes, options)
    elif method == "ultra":
        return _filter_ultra(notes, options)
    elif method == "custom":
        return _filter_custom(notes, options)
    else:
        return _filter_classical(notes, options)


def _filter_basic(notes: List[Dict], options: Dict) -> List[Dict]:
    """Filtrage basique : supprime les harmoniques à l'octave avec faible vélocité."""
    kept = []
    for note in notes:
        is_harmonic = False
        for other in notes:
            if other is note:
                continue
            interval = is_harmonic_of(note['pitch'], other['pitch'])
            if interval is None:
                continue
            if (other['velocity'] > note['velocity'] * HARMONIC_VELOCITY_RATIO and
                abs(note['onset'] - other['onset']) < SIMULTANEITY_TOLERANCE):
                if note['pitch'] > other['pitch']:
                    is_harmonic = True
                    break
        if not is_harmonic:
            kept.append(note)
    
    print(f"[HarmonicFilter] basic: {len(notes)} → {len(kept)} notes")
    return kept


def _filter_classical(notes: List[Dict], options: Dict) -> List[Dict]:
    """Filtrage classique pour piano."""
    kept = []
    removed_indices = set()
    
    main_notes = []
    for i, note in enumerate(notes):
        if note['velocity'] >= MIN_MAIN_VELOCITY:
            main_notes.append((i, note))
    
    main_notes.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        is_harmonic = False
        
        for main_idx, main_note in main_notes:
            if main_idx == i:
                continue
            if main_note['velocity'] > 0.75:
                continue
            
            interval = is_harmonic_of(note['pitch'], main_note['pitch'])
            if interval is None:
                continue
            
            time_diff = abs(note['onset'] - main_note['onset'])
            if time_diff > SIMULTANEITY_TOLERANCE:
                continue
            
            if main_note['pitch'] < BASS_THRESHOLD and main_note['velocity'] > 0.4:
                if note['pitch'] > main_note['pitch'] and note['velocity'] < main_note['velocity'] * 0.6:
                    is_harmonic = True
                    break
            
            if main_note['velocity'] > 0.5 and note['velocity'] < main_note['velocity'] * 0.4:
                if abs(note['onset'] - main_note['onset']) < SIMULTANEITY_TOLERANCE:
                    is_harmonic = True
                    break
        
        if is_harmonic:
            removed_indices.add(i)
        else:
            kept.append(note)
    
    print(f"[HarmonicFilter] classical: {len(notes)} → {len(kept)} notes ({len(notes) - len(kept)} supprimés)")
    return kept


def _filter_classical_strong(notes: List[Dict], options: Dict) -> List[Dict]:
    """
    Filtrage renforcé pour partitions classiques complexes (Chopin, Debussy, nocturnes).
    
    Combinaison de pedal-aware avec des seuils plus agressifs :
    - Vélocité relative plus basse (0.35 au lieu de 0.45)
    - Intervalle 19 (seizième) ajouté pour harmoniques complexes
    - Protection renforcée des notes mélodiques aigües
    - Détection de patterns harmoniques sans basses
    """
    kept = []
    removed_indices = set()
    removed_reasons = {'strong_pedal': 0, 'strong_double': 0, 'strong_weak': 0, 'strong_pattern': 0}
    
    # Configuration spécifique classical-strong
    velocity_ratio = options.get('velocity_ratio', 0.35)
    time_window = options.get('time_window', 0.1)
    
    # Notes basses fortes (susceptibles d'activer la pédale)
    pedal_basses = []
    for i, note in enumerate(notes):
        if note['pitch'] < BASS_THRESHOLD and note['velocity'] > 0.3:
            pedal_basses.append((i, note))
    
    pedal_basses.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    # Zones de pédale élargies
    pedal_zones = []
    if pedal_basses:
        for idx, note in pedal_basses:
            if note['velocity'] > 0.35:
                pedal_zones.append({
                    'pitch': note['pitch'],
                    'velocity': note['velocity'],
                    'start': note['onset'] - 0.05,
                    'end': note['onset'] + max(note['duration'], 0.8) + 0.4,
                })
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        # PROTECTION : notes mélodiques légitimes (plus agressif)
        if note['velocity'] > PROTECTED_VELOCITY_THRESHOLD:
            kept.append(note)
            continue
        
        if note['pitch'] > 80 and note['velocity'] > 0.55:
            kept.append(note)
            continue
        
        # Protection relative aux basses
        max_rel_velocity = 0
        for _, bass in pedal_basses:
            if bass['velocity'] > 0:
                rel_vel = note['velocity'] / bass['velocity']
                max_rel_velocity = max(max_rel_velocity, rel_vel)
        
        if max_rel_velocity > 0.75 and note['velocity'] > 0.5:
            kept.append(note)
            continue
        
        # Détection par patterns harmoniques (sans basses)
        if not pedal_zones:
            harmonic_count = 0
            harmonic_sources = []
            for j, other in enumerate(notes):
                if j == i or j in removed_indices:
                    continue
                interval = is_harmonic_of(note['pitch'], other['pitch'])
                if interval is not None:
                    if (other['velocity'] > note['velocity'] * 0.55 and
                        abs(note['onset'] - other['onset']) < PEDAL_SIMULTANEITY_TOLERANCE):
                        harmonic_count += 1
                        harmonic_sources.append(j)
            
            if harmonic_count >= 2 and note['velocity'] < 0.38:
                removed_indices.add(i)
                removed_reasons['strong_pattern'] += 1
                continue
            
            if harmonic_count >= 1:
                for src_idx in harmonic_sources:
                    src = notes[src_idx]
                    if (src['velocity'] > 0.35 and
                        note['duration'] > MIN_PEDAL_HARMONIC_DURATION and
                        note['velocity'] < 0.38):
                        removed_indices.add(i)
                        removed_reasons['strong_pattern'] += 1
                        break
                if i in removed_indices:
                    continue
            
            if note['velocity'] < 0.28 and note['duration'] > 1.0:
                for j, other in enumerate(notes):
                    if j == i or j in removed_indices:
                        continue
                    interval = is_harmonic_of(note['pitch'], other['pitch'])
                    if interval is not None:
                        if abs(note['onset'] - other['onset']) < PEDAL_SIMULTANEITY_TOLERANCE:
                            removed_indices.add(i)
                            removed_reasons['strong_pattern'] += 1
                            break
                if i in removed_indices:
                    continue
        
        # DÉTECTION D'HARMONIQUES DE PÉDALE (avec zones)
        is_pedal_harmonic_note = False
        
        for zone in pedal_zones:
            if note['onset'] < zone['start'] or note['onset'] > zone['end']:
                continue
            
            interval = is_harmonic_of(note['pitch'], zone['pitch'])
            if interval is None:
                continue
            
            if note['pitch'] <= zone['pitch']:
                continue
            
            # Seuil de vélocité plus bas que pedal-aware
            if note['velocity'] >= zone['velocity'] * velocity_ratio:
                if note['velocity'] >= PEDAL_HARMONIC_VELOCITY_MAX:
                    continue
            
            # Durée + vélocité : harmonique de pédale détectée
            if note['duration'] > 0.7 and note['velocity'] < 0.38:
                is_pedal_harmonic_note = True
                removed_reasons['strong_pedal'] += 1
                break
            
            # Double harmonique
            harmonic_sources = 0
            for other_zone in pedal_zones:
                if other_zone['pitch'] == zone['pitch']:
                    continue
                other_interval = is_harmonic_of(note['pitch'], other_zone['pitch'])
                if other_interval is not None:
                    harmonic_sources += 1
            
            if harmonic_sources >= 1 and note['velocity'] < 0.33:
                is_pedal_harmonic_note = True
                removed_reasons['strong_double'] += 1
                break
            
            # Harmonique faible proche du temps d'attaque
            if (note['velocity'] < 0.33 and 
                abs(note['onset'] - zone['start']) < PEDAL_SIMULTANEITY_TOLERANCE):
                is_pedal_harmonic_note = True
                removed_reasons['strong_weak'] += 1
                break
        
        if is_pedal_harmonic_note:
            removed_indices.add(i)
        else:
            kept.append(note)
    
    total_removed = len(notes) - len(kept)
    print(f"[HarmonicFilter] classical-strong: {len(notes)} → {len(kept)} notes ({total_removed} supprimés)")
    if total_removed > 0:
        print(f"[HarmonicFilter]   → strong_pedal: {removed_reasons['strong_pedal']}, "
              f"strong_double: {removed_reasons['strong_double']}, "
              f"strong_weak: {removed_reasons['strong_weak']}, "
              f"strong_pattern: {removed_reasons['strong_pattern']}")
    
    return kept


def _filter_aggressive(notes: List[Dict], options: Dict) -> List[Dict]:
    """Filtrage agressif pour partitions complexes (Chopin, mazurkas, nocturnes)."""
    kept = []
    removed_indices = set()
    
    bass_notes = []
    for i, note in enumerate(notes):
        if note['pitch'] < BASS_THRESHOLD and note['velocity'] > 0.3:
            bass_notes.append((i, note))
    
    bass_notes.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        if note['velocity'] > PROTECTED_VELOCITY_THRESHOLD or note['duration'] > PROTECTED_DURATION_THRESHOLD:
            kept.append(note)
            continue
        
        is_harmonic = False
        
        for main_idx, main_note in bass_notes:
            if main_idx == i:
                continue
            
            interval = is_harmonic_of(note['pitch'], main_note['pitch'])
            if interval is None:
                continue
            
            time_diff = abs(note['onset'] - main_note['onset'])
            if time_diff > 0.08:
                continue
            
            if (main_note['velocity'] > 0.35 and 
                note['pitch'] > main_note['pitch'] and
                note['velocity'] < main_note['velocity'] * 0.5):
                is_harmonic = True
                break
            
            is_double_harmonic = False
            for other_idx, other_note in bass_notes:
                if other_idx == main_idx or other_idx == i:
                    continue
                interval2 = is_harmonic_of(note['pitch'], other_note['pitch'])
                if interval2 is not None and interval != interval2:
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
    
    print(f"[HarmonicFilter] aggressive: {len(notes)} → {len(kept)} notes ({len(notes) - len(kept)} supprimés)")
    return kept


def _filter_pedal_aware(notes: List[Dict], options: Dict) -> List[Dict]:
    """
    Filtrage spécialisé pour les harmoniques de pédale du piano.
    
    Le plus important pour la musique classique complexe (Chopin, Debussy, etc.).
    Fonctionne même sans basses fortes via détection par patterns harmoniques.
    """
    kept = []
    removed_indices = set()
    removed_reasons = {'pedal_harmonic': 0, 'double_harmonic': 0, 'weak_harmonic': 0, 'pattern_harmonic': 0}
    
    # Notes basses fortes (susceptibles d'activer la pédale)
    pedal_basses = []
    for i, note in enumerate(notes):
        if note['pitch'] < BASS_THRESHOLD and note['velocity'] > 0.35:
            pedal_basses.append((i, note))
    
    pedal_basses.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    # Zones de pédale
    pedal_zones = []
    if pedal_basses:
        for idx, note in pedal_basses:
            if note['velocity'] > 0.4:
                pedal_zones.append({
                    'pitch': note['pitch'],
                    'velocity': note['velocity'],
                    'start': note['onset'] - 0.05,
                    'end': note['onset'] + max(note['duration'], 1.0) + 0.3,
                })
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        # PROTECTION : notes mélodiques légitimes
        if note['velocity'] > PROTECTED_VELOCITY_THRESHOLD:
            kept.append(note)
            continue
        
        if note['pitch'] > 84:
            kept.append(note)
            continue
        
        max_rel_velocity = 0
        for _, bass in pedal_basses:
            if bass['velocity'] > 0:
                rel_vel = note['velocity'] / bass['velocity']
                max_rel_velocity = max(max_rel_velocity, rel_vel)
        
        if max_rel_velocity > 0.7 and note['velocity'] > 0.5:
            kept.append(note)
            continue
        
        # Détection par patterns harmoniques (sans basses)
        if not pedal_zones:
            harmonic_count = 0
            harmonic_sources = []
            for j, other in enumerate(notes):
                if j == i or j in removed_indices:
                    continue
                interval = is_harmonic_of(note['pitch'], other['pitch'])
                if interval is not None:
                    if (other['velocity'] > note['velocity'] * 0.6 and
                        abs(note['onset'] - other['onset']) < PEDAL_SIMULTANEITY_TOLERANCE):
                        harmonic_count += 1
                        harmonic_sources.append(j)
            
            if harmonic_count >= 2 and note['velocity'] < 0.4:
                removed_indices.add(i)
                removed_reasons['pattern_harmonic'] += 1
                continue
            
            if harmonic_count >= 1:
                for src_idx in harmonic_sources:
                    src = notes[src_idx]
                    if (src['velocity'] > 0.4 and
                        note['duration'] > 0.8 and
                        note['velocity'] < 0.35):
                        removed_indices.add(i)
                        removed_reasons['pattern_harmonic'] += 1
                        break
                if i in removed_indices:
                    continue
            
            if note['velocity'] < 0.3 and note['duration'] > 1.2:
                for j, other in enumerate(notes):
                    if j == i or j in removed_indices:
                        continue
                    interval = is_harmonic_of(note['pitch'], other['pitch'])
                    if interval is not None:
                        if abs(note['onset'] - other['onset']) < PEDAL_SIMULTANEITY_TOLERANCE:
                            removed_indices.add(i)
                            removed_reasons['pattern_harmonic'] += 1
                            break
                if i in removed_indices:
                    continue
        
        # DÉTECTION D'HARMONIQUES DE PÉDALE (avec zones)
        is_pedal_harmonic_note = False
        
        for zone in pedal_zones:
            if note['onset'] < zone['start'] or note['onset'] > zone['end']:
                continue
            
            interval = is_harmonic_of(note['pitch'], zone['pitch'])
            if interval is None:
                continue
            
            if note['pitch'] <= zone['pitch']:
                continue
            
            if note['velocity'] >= zone['velocity'] * 0.45:
                if note['velocity'] >= PEDAL_HARMONIC_VELOCITY_MAX:
                    continue
            
            if note['duration'] > 0.8 and note['velocity'] < 0.4:
                is_pedal_harmonic_note = True
                removed_reasons['pedal_harmonic'] += 1
                break
            
            harmonic_sources = 0
            for other_zone in pedal_zones:
                if other_zone['pitch'] == zone['pitch']:
                    continue
                other_interval = is_harmonic_of(note['pitch'], other_zone['pitch'])
                if other_interval is not None:
                    harmonic_sources += 1
            
            if harmonic_sources >= 1 and note['velocity'] < 0.35:
                is_pedal_harmonic_note = True
                removed_reasons['double_harmonic'] += 1
                break
            
            if (note['velocity'] < 0.35 and 
                abs(note['onset'] - zone['start']) < PEDAL_SIMULTANEITY_TOLERANCE):
                is_pedal_harmonic_note = True
                removed_reasons['weak_harmonic'] += 1
                break
        
        if is_pedal_harmonic_note:
            removed_indices.add(i)
        else:
            kept.append(note)
    
    total_removed = len(notes) - len(kept)
    print(f"[HarmonicFilter] pedal-aware: {len(notes)} → {len(kept)} notes ({total_removed} supprimés)")
    if total_removed > 0:
        print(f"[HarmonicFilter]   → pedal_harmonic: {removed_reasons['pedal_harmonic']}, "
              f"double_harmonic: {removed_reasons['double_harmonic']}, "
              f"weak_harmonic: {removed_reasons['weak_harmonic']}, "
              f"pattern_harmonic: {removed_reasons['pattern_harmonic']}")
    
    return kept


def _filter_ultra(notes: List[Dict], options: Dict) -> List[Dict]:
    """Filtrage ultra-aggressif pour partitions complexes de style classique."""
    kept = []
    removed_indices = set()
    removed_reasons = {'ultra_pedal': 0, 'ultra_double': 0, 'ultra_weak': 0, 'ultra_pattern': 0}
    
    pedal_basses = []
    for i, note in enumerate(notes):
        if note['pitch'] < BASS_THRESHOLD and note['velocity'] > 0.25:
            pedal_basses.append((i, note))
    
    pedal_basses.sort(key=lambda x: x[1]['velocity'], reverse=True)
    
    pedal_zones = []
    if pedal_basses:
        for idx, note in pedal_basses:
            if note['velocity'] > 0.3:
                pedal_zones.append({
                    'pitch': note['pitch'],
                    'velocity': note['velocity'],
                    'start': note['onset'] - 0.05,
                    'end': note['onset'] + max(note['duration'], 0.8) + 0.5,
                })
    
    for i, note in enumerate(notes):
        if i in removed_indices:
            continue
        
        if note['velocity'] > PROTECTED_VELOCITY_THRESHOLD:
            kept.append(note)
            continue
        
        if note['pitch'] > 84 and note['velocity'] > 0.6:
            kept.append(note)
            continue
        
        max_rel_velocity = 0
        for _, bass in pedal_basses:
            if bass['velocity'] > 0:
                rel_vel = note['velocity'] / bass['velocity']
                max_rel_velocity = max(max_rel_velocity, rel_vel)
        
        if max_rel_velocity > 0.8 and note['velocity'] > 0.55:
            kept.append(note)
            continue
        
        if not pedal_zones:
            harmonic_count = 0
            harmonic_sources = []
            for j, other in enumerate(notes):
                if j == i or j in removed_indices:
                    continue
                interval = is_harmonic_of(note['pitch'], other['pitch'])
                if interval is not None:
                    if (other['velocity'] > note['velocity'] * 0.5 and
                        abs(note['onset'] - other['onset']) < PEDAL_SIMULTANEITY_TOLERANCE):
                        harmonic_count += 1
                        harmonic_sources.append(j)
            
            if harmonic_count >= 2 and note['velocity'] < 0.35:
                removed_indices.add(i)
                removed_reasons['ultra_pattern'] += 1
                continue
            
            if harmonic_count >= 1:
                for src_idx in harmonic_sources:
                    src = notes[src_idx]
                    if (src['velocity'] > 0.3 and
                        note['duration'] > MIN_PEDAL_HARMONIC_DURATION and
                        note['velocity'] < ULTRA_HARMONIC_VELOCITY_MAX):
                        removed_indices.add(i)
                        removed_reasons['ultra_pattern'] += 1
                        break
                if i in removed_indices:
                    continue
            
            if note['velocity'] < 0.4 and note['duration'] > 0.8:
                for j, other in enumerate(notes):
                    if j == i or j in removed_indices:
                        continue
                    interval = is_harmonic_of(note['pitch'], other['pitch'])
                    if interval is not None:
                        if abs(note['onset'] - other['onset']) < PEDAL_SIMULTANEITY_TOLERANCE:
                            removed_indices.add(i)
                            removed_reasons['ultra_pattern'] += 1
                            break
                if i in removed_indices:
                    continue
        
        is_pedal_harmonic_note = False
        
        for zone in pedal_zones:
            if note['onset'] < zone['start'] or note['onset'] > zone['end']:
                continue
            
            interval = is_harmonic_of(note['pitch'], zone['pitch'])
            if interval is None:
                continue
            
            if note['pitch'] <= zone['pitch']:
                continue
            
            if note['velocity'] >= zone['velocity'] * 0.5:
                if note['velocity'] >= ULTRA_HARMONIC_VELOCITY_MAX:
                    continue
            
            if note['duration'] > MIN_PEDAL_HARMONIC_DURATION and note['velocity'] < ULTRA_HARMONIC_VELOCITY_MAX:
                is_pedal_harmonic_note = True
                removed_reasons['ultra_pedal'] += 1
                break
            
            harmonic_sources = 0
            for other_zone in pedal_zones:
                if other_zone['pitch'] == zone['pitch']:
                    continue
                other_interval = is_harmonic_of(note['pitch'], other_zone['pitch'])
                if other_interval is not None:
                    harmonic_sources += 1
            
            if harmonic_sources >= ULTRA_DOUBLE_HARMONIC_SOURCES and note['velocity'] < ULTRA_HARMONIC_VELOCITY_MAX:
                is_pedal_harmonic_note = True
                removed_reasons['ultra_double'] += 1
                break
            
            if (note['velocity'] < ULTRA_HARMONIC_VELOCITY_MAX and 
                abs(note['onset'] - zone['start']) < PEDAL_SIMULTANEITY_TOLERANCE):
                is_pedal_harmonic_note = True
                removed_reasons['ultra_weak'] += 1
                break
        
        if is_pedal_harmonic_note:
            removed_indices.add(i)
        else:
            kept.append(note)
    
    total_removed = len(notes) - len(kept)
    print(f"[HarmonicFilter] ultra: {len(notes)} → {len(kept)} notes ({total_removed} supprimés)")
    if total_removed > 0:
        print(f"[HarmonicFilter]   → ultra_pedal: {removed_reasons['ultra_pedal']}, "
              f"ultra_double: {removed_reasons['ultra_double']}, "
              f"ultra_weak: {removed_reasons['ultra_weak']}, "
              f"ultra_pattern: {removed_reasons['ultra_pattern']}")
    
    return kept


def _filter_custom(notes: List[Dict], options: Dict) -> List[Dict]:
    """Filtrage harmonique avec paramètres manuels fins.
    
    Les paramètres sont lus depuis options['_custom_harmonic'] :
    - velocity_ratio: ratio de vélocité pour détecter les harmoniques (0.0-1.0)
    - protection_threshold: seuil de protection des notes fortes (0.0-1.0)
    - time_tolerance: fenêtre de simultanéité temporelle (en secondes)
    - bass_threshold: seuil de basse en MIDI pitch (12-72)
    
    Exemple d'utilisation :
        options['_custom_harmonic'] = {
            'velocity_ratio': 0.4,
            'protection_threshold': 0.85,
            'time_tolerance': 0.06,
            'bass_threshold': 38,
        }
    """
    custom = options.get('_custom_harmonic', {})
    if not custom:
        # Si aucun paramètre custom, fallback sur classical-strong
        return _filter_classical_strong(notes, options)
    
    # Sauvegarder les valeurs originales
    orig_vel_ratio = HARMONIC_VELOCITY_RATIO
    orig_prot_thresh = PROTECTED_VELOCITY_THRESHOLD
    orig_time_tol = SIMULTANEITY_TOLERANCE
    orig_bass_thresh = BASS_THRESHOLD
    
    # Appliquer les paramètres personnalisés
    velocity_ratio = custom.get('velocity_ratio', HARMONIC_VELOCITY_RATIO)
    protection_threshold = custom.get('protection_threshold', PROTECTED_VELOCITY_THRESHOLD)
    time_tolerance = custom.get('time_tolerance', SIMULTANEITY_TOLERANCE)
    bass_threshold = custom.get('bass_threshold', BASS_THRESHOLD)
    
    # Injecter temporairement dans les constantes du module
    globals()['HARMONIC_VELOCITY_RATIO'] = velocity_ratio
    globals()['PROTECTED_VELOCITY_THRESHOLD'] = protection_threshold
    globals()['SIMULTANEITY_TOLERANCE'] = time_tolerance
    globals()['BASS_THRESHOLD'] = bass_threshold
    
    try:
        # Utiliser pedal-aware avec les paramètres injectés
        return _filter_pedal_aware(notes, options)
    finally:
        # Restaurer les valeurs originales
        globals()['HARMONIC_VELOCITY_RATIO'] = orig_vel_ratio
        globals()['PROTECTED_VELOCITY_THRESHOLD'] = orig_prot_thresh
        globals()['SIMULTANEITY_TOLERANCE'] = orig_time_tol
        globals()['BASS_THRESHOLD'] = orig_bass_thresh


def get_harmonic_analysis(notes: List[Dict]) -> Dict:
    """Analyse les harmoniques présents dans les notes sans les supprimer."""
    if not notes:
        return {
            'total_notes': 0,
            'potential_harmonics': 0,
            'bass_notes': 0,
            'simultaneous_chords': 0,
        }
    
    bass_count = sum(1 for n in notes if n['pitch'] < BASS_THRESHOLD)
    
    simultaneous = 0
    for i, n1 in enumerate(notes):
        for j, n2 in enumerate(notes):
            if j <= i:
                continue
            if abs(n1['onset'] - n2['onset']) < SIMULTANEITY_TOLERANCE:
                simultaneous += 1
                break
    
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
    """Filtrage harmonique avec retour d'analyse."""
    before = get_harmonic_analysis(notes)
    filtered = filter_ghost_notes(notes, options, method)
    after = get_harmonic_analysis(filtered)
    
    return filtered, before, after