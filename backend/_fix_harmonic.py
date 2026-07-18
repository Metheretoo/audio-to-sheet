"""Script de correction de harmonic_filter.py"""

content = r'''"""
harmonic_filter.py - Filtrage des harmoniques pour piano classique.

Les transcripteurs IA (Transkun, Piano Transcription) detectent souvent
des "notes fantomes" causees par :
  1. Les harmoniques de pedale : une note grave jouee avec pedale forte cree
     des harmoniques a l'octave (+12), quinte (+7), quarte (+5), et doubles
  2. Les fantomes : des notes a des frequencies voisees detectees par erreur
  3. Les notes de pedale : des notes jouees sans etre attaquees mais prolongees

Ce module filtre ces artefacts en se basant sur :
  - L'intervalle entre notes (octave, quinte, quarte, doubles)
  - La velocite relative (les harmoniques ont une velocite plus faible)
  - La simultaneite temporelle (notes jouees au meme moment)
  - Le registre (les basses creat plus d'harmoniques)
  - La duree (les harmoniques de pedale ont souvent des durees anormalement longues)

Algorithmes disponibles :
  - 'basic' : filtrage simple (octave + quinte)
  - 'classical' : filtrage avance pour piano classique
  - 'aggressive' : filtrage agressif (mazurkas, nocturnes, musique romantique)
  - 'pedal-aware' : filtrage specialise pour harmoniques de pedale
"""

import numpy as np
from typing import List, Dict, Optional


# ---------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------

OCTAVE_INTERVAL = 12
QUINTE_INTERVAL = 7
QUARTE_INTERVAL = 5
OCTAVE_DOUBLE = 24
QUINTE_AUGMENTED = 8

# Tous les intervalles harmoniques a rechercher
HARMONIC_INTERVALS = [
    OCTAVE_INTERVAL, -OCTAVE_INTERVAL,
    QUINTHE_INTERVAL, -QUINTE_INTERVAL,
    QUARTE_INTERVAL, -QUARTE_INTERVAL,
    OCTAVE_DOUBLE, -OCTAVE_DOUBLE,
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


def is_harmonic_of(pitch: int, main_pitch: int):
    """Vérifie si pitch est un harmonique de main_pitch."""
    interval = pitch - main_pitch
    if interval in HARMONIC_INTERVALS:
        return interval
    for hi in HARMONIC_INTERVALS:
        if abs(interval - hi) <= HARMONIC_TOLERANCE:
            return interval
    return None


def is_pedal_harmonic(note, main_note):
    """Vérifie si note est un harmonique de pédale de main_note."""
    interval = is_harmonic_of(note["pitch"], main_note["pitch"])
    if interval is None:
        return False
    if main_note["pitch"] >= BASS_THRESHOLD:
        return False
    if main_note["velocity"] < 0.35:
        return False
    if note["pitch"] <= main_note["pitch"]:
        return False
    if abs(note["onset"] - main_note["onset"]) > PEDAL_SIMULTANEITY_TOLERANCE:
        return False
    if note["velocity"] >= main_note["velocity"] * 0.45:
        if note["velocity"] < PEDAL_HARMONIC_VELOCITY_MAX and main_note["velocity"] > 0.5:
            pass
        else:
            return False
    if note["duration"] > 2.0 and note["velocity"] < 0.4:
        return True
    return True


def filter_ghost_notes(notes, options=None, method="classical"):
    """Filtrage principal des harmoniques pour piano classique."""
    if not notes or len(notes) <= 3:
        return notes
    options = options or {}
    methods_map = {
        "basic": _filter_basic,
        "classical": _filter_classical,
        "aggressive": _filter_aggressive,
        "pedal-aware": _filter_pedal_aware,
        "ultra": _filter_ultra,
    }
    fn = methods_map.get(method, _filter_classical)
    return fn(notes, options)


def _filter_basic(notes, options):
    """Filtrage basique : supprime les harmoniques a l'octave avec faible velocite."""
    kept = []
    for note in notes:
        is_harmonic = False
        for other in notes:
            if other is note:
                continue
            interval = is_harmonic_of(note["pitch"], other["pitch"])
            if interval is None:
                continue
            if (other["velocity"] > note["velocity"] * HARMONIC_VELOCITY_RATIO
                    and abs(note["onset"] - other["onset"]) < SIMULTANEITY_TOLERANCE):
                if note["pitch"] > other["pitch"]:
                    is_harmonic = True
                    break
        if not is_harmonic:
            kept.append(note)
    print(f"[HarmonicFilter] basic: {len(notes)} -> {len(kept)} notes")
    return kept


def _filter_classical(notes, options):
    """Filtrage classique pour piano."""
    kept = []
    removed = set()
    main_notes = []
    for i, n in enumerate(notes):
        if n["velocity"] >= MIN_MAIN_VELOCITY:
            main_notes.append((i, n))
    main_notes.sort(key=lambda x: x[1]["velocity"], reverse=True)

    for i, note in enumerate(notes):
        if i in removed:
            continue
        is_harmonic = False
        for midx, mnote in main_notes:
            if midx == i:
                continue
            if mnote["velocity"] > 0.75:
                continue
            interval = is_harmonic_of(note["pitch"], mnote["pitch"])
            if interval is None:
                continue
            if abs(note["onset"] - mnote["onset"]) > SIMULTANEITY_TOLERANCE:
                continue
            if mnote["pitch"] < BASS_THRESHOLD and mnote["velocity"] > 0.4:
                if note["pitch"] > mnote["pitch"] and note["velocity"] < mnote["velocity"] * 0.6:
                    is_harmonic = True
                    break
            if mnote["velocity"] > 0.5 and note["velocity"] < mnote["velocity"] * 0.4:
                if abs(note["onset"] - mnote["onset"]) < SIMULTANEITY_TOLERANCE:
                    is_harmonic = True
                    break
        if is_harmonic:
            removed.add(i)
        else:
            kept.append(note)
    print(f"[HarmonicFilter] classical: {len(notes)} -> {len(kept)} notes ({len(notes)-len(kept)} suppr.)")
    return kept


def _filter_aggressive(notes, options):
    """Filtrage agressif pour partitions complexes (Chopin, mazurkas, nocturnes)."""
    kept = []
    removed = set()
    bass_notes = []
    for i, n in enumerate(notes):
        if n["pitch"] < BASS_THRESHOLD and n["velocity"] > 0.3:
            bass_notes.append((i, n))
    bass_notes.sort(key=lambda x: x[1]["velocity"], reverse=True)

    for i, note in enumerate(notes):
        if i in removed:
            continue
        if note["velocity"] > PROTECTED_VELOCITY_THRESHOLD or note["duration"] > PROTECTED_DURATION_THRESHOLD:
            kept.append(note)
            continue
        is_harmonic = False
        for midx, mnote in bass_notes:
            if midx == i:
                continue
            interval = is_harmonic_of(note["pitch"], mnote["pitch"])
            if interval is None:
                continue
            if abs(note["onset"] - mnote["onset"]) > 0.08:
                continue
            if mnote["velocity"] > 0.35 and note["pitch"] > mnote["pitch"] and note["velocity"] < mnote["velocity"] * 0.5:
                is_harmonic = True
                break
            is_double = False
            for oidx, onote in bass_notes:
                if oidx == midx or oidx == i:
                    continue
                i2 = is_harmonic_of(note["pitch"], onote["pitch"])
                if i2 is not None and i2 != interval:
                    if note["velocity"] < 0.3:
                        is_double = True
                        break
            if is_double:
                is_harmonic = True
                break
        if is_harmonic:
            removed.add(i)
        else:
            kept.append(note)
    print(f"[HarmonicFilter] aggressive: {len(notes)} -> {len(kept)} notes ({len(notes)-len(kept)} suppr.)")
    return kept


def _filter_pedal_aware(notes, options):
    """
    Filtrage specialise pour les harmoniques de pedale du piano.
    
    Le plus important pour la musique classique complexe (Chopin, Debussy, etc.).
    Fonctionne meme sans basses fortes via detection par patterns harmoniques.
    """
    kept = []
    removed = set()
    reasons = {"pedal": 0, "double": 0, "weak": 0, "pattern": 0}

    pedal_basses = []
    for i, n in enumerate(notes):
        if n["pitch"] < BASS_THRESHOLD and n["velocity"] > 0.35:
            pedal_basses.append((i, n))
    pedal_basses.sort(key=lambda x: x[1]["velocity"], reverse=True)

    pedal_zones = []
    for idx, n in pedal_basses:
        if n["velocity"] > 0.4:
            pedal_zones.append({
                "pitch": n["pitch"],
                "velocity": n["velocity"],
                "start": n["onset"] - 0.05,
                "end": n["onset"] + max(n["duration"], 1.0) + 0.3,
            })

    for i, note in enumerate(notes):
        if i in removed:
            continue
        if note["velocity"] > PROTECTED_VELOCITY_THRESHOLD:
            kept.append(note)
            continue
        if note["pitch"] > 84:
            kept.append(note)
            continue

        max_rel = 0
        for _, b in pedal_basses:
            if b["velocity"] > 0:
                max_rel = max(max_rel, note["velocity"] / b["velocity"])
        if max_rel > 0.7 and note["velocity"] > 0.5:
            kept.append(note)
            continue

        if not pedal_zones:
            h_count = 0
            h_sources = []
            for j, other in enumerate(notes):
                if j == i or j in removed:
                    continue
                iv = is_harmonic_of(note["pitch"], other["pitch"])
                if iv is not None:
                    if other["velocity"] > note["velocity"] * 0.6 and abs(note["onset"] - other["onset"]) < PEDAL_SIMULTANEITY_TOLERANCE:
                        h_count += 1
                        h_sources.append(j)
            if h_count >= 2 and note["velocity"] < 0.4:
                removed.add(i)
                reasons["pattern"] += 1
                continue
            if h_count >= 1:
                for si in h_sources:
                    src = notes[si]
                    if src["velocity"] > 0.4 and note["duration"] > 0.8 and note["velocity"] < 0.35:
                        removed.add(i)
                        reasons["pattern"] += 1
                        break
                if i in removed:
                    continue
            if note["velocity"] < 0.3 and note["duration"] > 1.2:
                for j, other in enumerate(notes):
                    if j == i or j in removed:
                        continue
                    if is_harmonic_of(note["pitch"], other["pitch"]) is not None:
                        if abs(note["onset"] - other["onset"]) < PEDAL_SIMULTANEITY_TOLERANCE:
                            removed.add(i)
                            reasons["pattern"] += 1
                            break
                if i in removed:
                    continue

        is_pedal = False
        for zone in pedal_zones:
            if note["onset"] < zone["start"] or note["onset"] > zone["end"]:
                continue
            iv = is_harmonic_of(note["pitch"], zone["pitch"])
            if iv is None:
                continue
            if note["pitch"] <= zone["pitch"]:
                continue
            if note["velocity"] >= zone["velocity"] * 0.45:
                if note["velocity"] >= PEDAL_HARMONIC_VELOCITY_MAX:
                    continue
            if note["duration"] > 0.8 and note["velocity"] < 0.4:
                is_pedal = True
                reasons["pedal"] += 1
                break
            h_src = 0
            for oz in pedal_zones:
                if oz["pitch"] == zone["pitch"]:
                    continue
                if is_harmonic_of(note["pitch"], oz["pitch"]) is not None:
                    h_src += 1
            if h_src >= 1 and note["velocity"] < 0.35:
                is_pedal = True
                reasons["double"] += 1
                break
            if note["velocity"] < 0.35 and abs(note["onset"] - zone["start"]) < PEDAL_SIMULTANEITY_TOLERANCE:
                is_pedal = True
                reasons["weak"] += 1
                break
        if is_pedal:
            removed.add(i)
        else:
            kept.append(note)

    total = len(notes) - len(kept)
    print(f"[HarmonicFilter] pedal-aware: {len(notes)} -> {len(kept)} notes ({total} suppr.)")
    if total > 0:
        print(f"[HarmonicFilter]   -> pedal:{reasons['pedal']} double:{reasons['double']} weak:{reasons['weak']} pattern:{reasons['pattern']}")
    return kept


def _filter_ultra(notes, options):
    """Filtrage ultra-aggressif pour partitions complexes de style classique."""
    kept = []
    removed = set()
    reasons = {"pedal": 0, "double": 0, "weak": 0, "pattern": 0}

    pedal_basses = []
    for i, n in enumerate(notes):
        if n["pitch"] < BASS_THRESHOLD and n["velocity"] > 0.25:
            pedal_basses.append((i, n))
    pedal_basses.sort(key=lambda x: x[1]["velocity"], reverse=True)

    pedal_zones = []
    for idx, n in pedal_basses:
        if n["velocity"] > 0.3:
            pedal_zones.append({
                "pitch": n["pitch"],
                "velocity": n["velocity"],
                "start": n["onset"] - 0.05,
                "end": n["onset"] + max(n["duration"], 0.8) + 0.5,
            })

    for i, note in enumerate(notes):
        if i in removed:
            continue
        if note["velocity"] > PROTECTED_VELOCITY_THRESHOLD:
            kept.append(note)
            continue
        if note["pitch"] > 84 and note["velocity"] > 0.6:
            kept.append(note)
            continue

        max_rel = 0
        for _, b in pedal_basses:
            if b["velocity"] > 0:
                max_rel = max(max_rel, note["velocity"] / b["velocity"])
        if max_rel > 0.8 and note["velocity"] > 0.55:
            kept.append(note)
            continue

        if not pedal_zones:
            h_count = 0
            h_sources = []
            for j, other in enumerate(notes):
                if j == i or j in removed:
                    continue
                iv = is_harmonic_of(note["pitch"], other["pitch"])
                if iv is not None:
                    if other["velocity"] > note["velocity"] * 0.5 and abs(note["onset"] - other["onset"]) < PEDAL_SIMULTANEITY_TOLERANCE:
                        h_count += 1
                        h_sources.append(j)
            if h_count >= 2 and note["velocity"] < 0.35:
                removed.add(i)
                reasons["pattern"] += 1
                continue
            if h_count >= 1:
                for si in h_sources:
                    src = notes[si]
                    if src["velocity"] > 0.3 and note["duration"] > MIN_PEDAL_HARMONIC_DURATION and note["velocity"] < ULTRA_HARMONIC_VELOCITY_MAX:
                        removed.add(i)
                        reasons["pattern"] += 1
                        break
                if i in removed:
                    continue
            if note["velocity"] < 0.4 and note["duration"] > 0.8:
                for j, other in enumerate(notes):
                    if j == i or j in removed:
                        continue
                    if is_harmonic_of(note["pitch"], other["pitch"]) is not None:
                        if abs(note["onset"] - other["onset"]) < PEDAL_SIMULTANEITY_TOLERANCE:
                            removed.add(i)
                            reasons["pattern"] += 1
                            break
                if i in removed:
                    continue

        is_pedal = False
        for zone in pedal_zones:
            if note["onset"] < zone["start"] or note["onset"] > zone["end"]:
                continue
            iv = is_harmonic_of(note["pitch"], zone["pitch"])
            if iv is None:
                continue
            if note["pitch"] <= zone["pitch"]:
                continue
            if note["velocity"] >= zone["velocity"] * 0.5:
                if note["velocity"] >= ULTRA_HARMONIC_VELOCITY_MAX:
                    continue
            if note["duration"] > MIN_PEDAL_HARMONIC_DURATION and note["velocity"] < ULTRA_HARMONIC_VELOCITY_MAX:
                is_pedal = True
                reasons["pedal"] += 1
                break
            h_src = 0
            for oz in pedal_zones:
                if oz["pitch"] == zone["pitch"]:
                    continue
                if is_harmonic_of(note["pitch"], oz["pitch"]) is not None:
                    h_src += 1
            if h_src >= ULTRA_DOUBLE_HARMONIC_SOURCES and note["velocity"] < ULTRA_HARMONIC_VELOCITY_MAX:
                is_pedal = True
                reasons["double"] += 1
                break
            if note["velocity"] < ULTRA_HARMONIC_VELOCITY_MAX and abs(note["onset"] - zone["start"]) < PEDAL_SIMULTANEITY_TOLERANCE:
                is_pedal = True
                reasons["weak"] += 1
                break
        if is_pedal:
            removed.add(i)
        else:
            kept.append(note)

    total = len(notes) - len(kept)
    print(f"[HarmonicFilter] ultra: {len(notes)} -> {len(kept)} notes ({total} suppr.)")
    if total > 0:
        print(f"[HarmonicFilter]   -> pedal:{reasons['pedal']} double:{reasons['double']} weak:{reasons['weak']} pattern:{reasons['pattern']}")
    return kept


def get_harmonic_analysis(notes):
    """Analyse les harmoniques presents dans les notes sans les supprimer."""
    if not notes:
        return {"total_notes": 0, "potential_harmonics": 0, "bass_notes": 0, "simultaneous_chords": 0}
    bass_count = sum(1 for n in notes if n["pitch"] < BASS_THRESHOLD)
    simultaneous = 0
    for i, n1 in enumerate(notes):
        for j, n2 in enumerate(notes):
            if j <= i:
                continue
            if abs(n1["onset"] - n2["onset"]) < SIMULTANEITY_TOLERANCE:
                simultaneous += 1
                break
    harmonics = 0
    for i, note in enumerate(notes):
        for j, other in enumerate(notes):
            if j == i:
                continue
            if is_harmonic_of(note["pitch"], other["pitch"]) is not None:
                if note["velocity"] < other["velocity"] * HARMONIC_VELOCITY_RATIO:
                    harmonics += 1
                    break
    return {"total_notes": len(notes), "potential_harmonics": harmonics, "bass_notes": bass_count, "simultaneous_chords": simultaneous}


def filter_with_analysis(notes, options=None, method="classical"):
    """Filtrage harmonique avec retour d'analyse."""
    before = get_harmonic_analysis(notes)
    filtered = filter_ghost_notes(notes, options, method)
    after = get_harmonic_analysis(filtered)
    return filtered, before, after
'''

with open("harmonic_filter.py", "w", encoding="utf-8") as f:
    f.write(content)
print("OK: harmonic_filter.py ecrit avec succes")