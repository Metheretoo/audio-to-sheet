# PHASE 2 — Quantizer Intelligent (Rhythm Inference Layer)

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 3-5h
> **Prérequis** : Phase 1 complète (`tempo_map.py` disponible et testé)
> **Fichier à créer** : `backend/quantizer.py`

---

## Objectif

Créer le **moteur d'inférence rythmique** qui transforme les note_events bruts (timestamps en secondes) en notes musicales propres (positions en beats, durées standard).

### Problème résolu

**V1 (problème)** :
```python
# midi_parser.py ligne 295 — division linéaire avec tempo FIXE
beat_s  = 60.0 / max(tempo, 20)         # ex: 0.5s par beat
start_b = quantize(start_s / beat_s, grid)  # ex: 0.48 / 0.5 = 0.96 → arrondi à 1.0
# Résultat : si le musicien joue à 119 BPM au lieu de 120,
# à la mesure 10, l'erreur cumulée = 10 * (0.504 - 0.5) = 40ms → décalage visible
```

**V2 (solution)** :
```python
# quantizer.py — utilise la TempoMap
beat_position = tempo_map.seconds_to_beat(start_s)  # ex: 0.97 (suit le tempo réel)
snapped = snap_to_grid(beat_position, grid=0.25)     # ex: 1.0  (noire)
# Résultat : chaque note est ancrée sur SON beat réel, pas sur un beat théorique fixe
```

---

## Fichier à créer : `backend/quantizer.py`

```python
"""
quantizer.py — Moteur d'inférence rythmique (Rhythm Inference Layer)

Transforme les note_events bruts (timestamps secondes) en QuantizedNotes
(positions et durées musicales) en utilisant la TempoMap dynamique.

Pipeline interne :
  1. clean_note_stream()     : suppression parasites, fusions, filtre confiance
  2. seconds_to_beats()      : conversion via TempoMap (pas de division linéaire)
  3. snap_to_grid()          : arrondi musical local adaptatif
  4. infer_duration()        : calcul de durée par IOI sur beats, pas secondes
  5. assign_hand()           : pré-attribution main gauche/droite (raffinée en Phase 3)
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
from tempo_map import TempoMap

# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class QuantizedNote:
    pitch_midi: int
    amplitude: float
    beat_position: float    # position depuis le beat 0
    beat_duration: float    # durée en beats (1.0 = noire, 0.5 = croche, etc.)
    dur_str: str            # code VexFlow : 'q', '8', 'h', 'w', '16'
    dots: int               # 0 ou 1
    hand: str               # 'treble' ou 'bass' (raffiné en Phase 3)
    start_s: float = 0.0    # timestamp original (gardé pour debug)
    end_s: float   = 0.0    # timestamp original (gardé pour debug)


# ── Constantes ────────────────────────────────────────────────────────────────

# Table de durées musicales standard (en beats)
DURATION_TABLE = [
    (4.000, 'w',  0),   # ronde
    (3.000, 'h',  1),   # blanche pointée
    (2.000, 'h',  0),   # blanche
    (1.500, 'q',  1),   # noire pointée
    (1.000, 'q',  0),   # noire
    (0.750, '8',  1),   # croche pointée
    (0.500, '8',  0),   # croche
    (0.375, '16', 1),   # double-croche pointée
    (0.250, '16', 0),   # double-croche
]

TREBLE_THRESHOLD    = 57     # MIDI 57 = La3 (seuil par défaut, raffiné en Phase 3)
CONFIDENCE_MIN      = 0.15   # amplitude minimum pour retenir une note
MIN_DURATION_BEATS  = 0.20   # durée minimale en beats (en dessous → parasite)
DEDUP_WINDOW_BEATS  = 0.08   # fenêtre de déduplification en beats


# ── Fonction principale ───────────────────────────────────────────────────────

def quantize_notes(
    note_events: list,
    tempo_map: TempoMap,
    options: dict = None
) -> List[QuantizedNote]:
    """
    Pipeline complet de quantification.

    Paramètres :
      note_events : List[(start_s, end_s, pitch_midi, amplitude, pitch_bends)]
      tempo_map   : TempoMap issu de tempo_map.build_tempo_map()
      options     : dict avec les clés optionnelles :
        - quantization_level : 'light' | 'standard' | 'heavy' (défaut: 'standard')
        - remove_short_notes : bool (défaut: True)
        - minimum_note_duration : int en ms (défaut: 50)
        - merge_near_notes : bool (défaut: True)
        - merge_gap_ms : int (défaut: 30)
        - split_hands : bool (défaut: True)

    Retour : List[QuantizedNote] triée par beat_position
    """
    if options is None:
        options = {}

    # Étape 1 : Nettoyage brut (en secondes)
    events = clean_note_stream(note_events, options)

    # Étape 2 : Conversion secondes → beats via TempoMap
    beat_events = seconds_to_beats(events, tempo_map)

    # Étape 3 : Arrondi sur grille musicale
    grid = _get_grid(options.get('quantization_level', 'standard'))
    snapped = [snap_to_grid(be, grid) for be in beat_events]

    # Étape 4 : Déduplication après snap (notes qui tombent sur le même beat)
    snapped = deduplicate_beats(snapped)

    # Étape 5 : Inférence des durées par IOI
    with_durations = infer_durations(snapped)

    # Étape 6 : Attribution main (pré-classification simple, raffinée Phase 3)
    if options.get('split_hands', True):
        for note in with_durations:
            note.hand = 'treble' if note.pitch_midi >= TREBLE_THRESHOLD else 'bass'

    return sorted(with_durations, key=lambda n: (n.beat_position, -n.pitch_midi))


# ── Étapes du pipeline ────────────────────────────────────────────────────────

def clean_note_stream(note_events: list, options: dict) -> list:
    """
    Nettoyage des note_events bruts (en secondes) :
    1. Supprimer notes trop courtes (< minimum_note_duration ms)
    2. Supprimer notes trop silencieuses (amplitude < CONFIDENCE_MIN)
    3. Fusionner notes du même pitch très proches dans le temps
    4. Supprimer doublons (même pitch, même onset)

    Retourne une liste nettoyée de tuples (start_s, end_s, pitch, amp, bends).
    """
    ...


def seconds_to_beats(note_events: list, tempo_map: TempoMap) -> list:
    """
    Convertit les timestamps en positions de beats via la TempoMap.

    Pour chaque event (start_s, end_s, pitch, amp, bends) :
      - beat_start = tempo_map.seconds_to_beat(start_s)
      - beat_end   = tempo_map.seconds_to_beat(end_s)

    Retourne une liste de tuples (beat_start, beat_end, pitch, amp, start_s, end_s).

    IMPORTANT : Ne pas utiliser de division linéaire ici.
    La TempoMap gère toute la conversion avec interpolation.
    """
    result = []
    for event in note_events:
        start_s, end_s, pitch, amp = float(event[0]), float(event[1]), int(event[2]), float(event[3])
        beat_start = tempo_map.seconds_to_beat(start_s)
        beat_end   = tempo_map.seconds_to_beat(end_s)
        result.append((beat_start, beat_end, pitch, amp, start_s, end_s))
    return result


def snap_to_grid(beat_event: tuple, grid: float = 0.25) -> tuple:
    """
    Arrondit les positions de beats sur la grille musicale.

    Paramètre grid : résolution de la grille en beats
      - 0.125 (1/32) : 'light'
      - 0.25  (1/16) : 'standard'
      - 0.5   (1/8)  : 'heavy'

    Arrondit beat_start et beat_end sur le multiple de grid le plus proche.
    S'assure que la durée minimale est respectée (>= grid).

    Algorithme :
      snapped_start = round(beat_start / grid) * grid
      snapped_end   = round(beat_end   / grid) * grid
      if snapped_end - snapped_start < grid:
          snapped_end = snapped_start + grid
    """
    ...


def deduplicate_beats(beat_events: list) -> list:
    """
    Supprime les notes qui ont le même pitch et la même position après snap.
    Conserve celle avec la plus haute amplitude.

    Fenêtre de déduplication : DEDUP_WINDOW_BEATS (0.08 beats par défaut).
    """
    ...


def infer_durations(beat_events: list) -> List[QuantizedNote]:
    """
    Calcule la durée musicale de chaque note par IOI (Inter-Onset Interval).

    Algorithme par groupe de pitch :
    1. Trier les notes par beat_position
    2. Pour chaque note, calculer l'IOI = beat_start[n+1] - beat_start[n]
    3. La durée de la note n est min(beat_duration_brute, IOI * 0.9)
       (le facteur 0.9 évite le chevauchement)
    4. Snap de la durée sur DURATION_TABLE (valeur musicale la plus proche)

    Note cruciale : travailler uniquement en beats, JAMAIS en secondes.
    Les durées calculées doivent être cohérentes avec la TempoMap.

    Retourne une liste de QuantizedNote (sans hand, qui est défini après).
    """
    ...


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _get_grid(level: str) -> float:
    """Retourne la résolution de grille selon le niveau de quantification."""
    return {'light': 0.125, 'standard': 0.25, 'heavy': 0.5}.get(level, 0.25)


def beats_to_duration(beats: float) -> Tuple[str, int]:
    """Valeur en beats → (code VexFlow, points)"""
    best = min(DURATION_TABLE, key=lambda d: abs(d[0] - beats))
    return best[1], best[2]


def duration_beats(dur_str: str, dots: int) -> float:
    """Code VexFlow + points → valeur en beats"""
    MAP = {'w': 4.0, 'h': 2.0, 'q': 1.0, '8': 0.5, '16': 0.25}
    base = MAP.get(dur_str, 1.0)
    return base * 1.5 if dots else base


# ── Auto-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    Test avec une séquence synthétique de 4 noires à ~120 BPM avec variation humaine.
    Résultat attendu : 4 QuantizedNote avec dur_str='q' et beat_position=[0, 1, 2, 3].
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from tempo_map import build_tempo_map

    # Séquence synthétique : 4 noires à ~120 BPM avec ±30ms variation humaine
    bpm = 120.0
    beat_s = 60.0 / bpm
    import random
    random.seed(42)
    fake_events = []
    for i in range(4):
        jitter = random.uniform(-0.030, 0.030)  # ±30ms variation humaine
        start = i * beat_s + jitter
        end   = start + beat_s * 0.85
        fake_events.append((start, end, 60 + i, 0.7, []))

    # Créer un TempoMap synthétique pour le test
    beat_times = np.array([i * beat_s for i in range(16)])
    from tempo_map import TempoMap
    tm = TempoMap(
        beat_times=beat_times,
        downbeat_times=beat_times[::4],
        estimated_meter=(4, 4),
        global_bpm=bpm,
        method='test_synthetic'
    )

    notes = quantize_notes(fake_events, tm)

    print(f"[Test] {len(notes)} notes quantifiées :")
    for n in notes:
        print(f"  pitch={n.pitch_midi} pos={n.beat_position:.2f} dur={n.dur_str} dots={n.dots}")

    # Vérifications
    assert len(notes) == 4, f"Attendu 4 notes, obtenu {len(notes)}"
    for i, n in enumerate(notes):
        assert abs(n.beat_position - i) < 0.1, f"Position {i} incorrecte : {n.beat_position}"
        assert n.dur_str == 'q', f"Durée incorrecte : {n.dur_str}"
    print("[Test] ✓ Toutes les vérifications passées")
```

---

## Interface consommée (Phase 1)

Ce module **importe** depuis `tempo_map.py` :
```python
from tempo_map import TempoMap, build_tempo_map
```
La `TempoMap` doit exposer `seconds_to_beat(t)` et `beat_to_seconds(b)`.

## Interface produite (pour Phase 3 et 4)

```python
# Phase 3 (voice_engine.py) consomme :
List[QuantizedNote]  # avec hand='treble'/'bass' (préliminaire)

# Phase 4 (score_builder.py) consomme :
# VoiceSplit.treble et VoiceSplit.bass → List[QuantizedNote]
```

---

## Notes d'implémentation pour l'agent

### Piège 1 : Ne pas re-diviser par le tempo
Le module doit appeler `tempo_map.seconds_to_beat()` et jamais `start_s / (60/bpm)`.

### Piège 2 : Gestion des notes simultanées
Plusieurs notes peuvent tomber sur le même beat (accord). Le snap ne doit pas les supprimer — c'est le rôle de `_build_voice` dans `score_builder.py`.

### Piège 3 : Durée minimale après snap
Après `snap_to_grid`, si `beat_end - beat_start < grid`, forcer `beat_end = beat_start + grid`. Sinon des durées nulles vont planter le score_builder.

### Piège 4 : Notes au-delà du dernier beat
Si `start_s > max(beat_times)`, extrapoler linéairement (la TempoMap gère ça).
