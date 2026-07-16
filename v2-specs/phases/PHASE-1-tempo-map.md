# PHASE 1 — TempoMap Dynamique

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 2-4h
> **Prérequis** : aucun (première phase)
> **Fichier à créer** : `backend/tempo_map.py`
> **Fichiers à modifier** : `backend/requirements.txt`, `backend/app.py`

---

## Objectif

Remplacer la détection de tempo statique (un seul entier BPM) par une **TempoMap dynamique** qui suit l'évolution réelle du tempo au cours du morceau.

### Problème résolu

**V1 (problème)** :
```python
# transcriber.py ligne 94
tempo = detect_tempo_librosa(audio_path)  # ex: 120
# midi_parser.py ligne 269
beat_s = 60.0 / max(tempo, 20)           # = 0.5s par beat (FIXE)
start_b = quantize(start_s / beat_s, grid)  # DRIFT : 0.48s/0.5s = 0.96 beat → arrondi à 1.0
```
Si le musicien joue légèrement plus vite ou ralentit, chaque note suivante accumule une erreur.

**V2 (solution)** :
```python
# tempo_map.py
tempo_map = build_tempo_map(audio_path)
# Chaque timestamp est converti via interpolation sur les beats réels détectés
beat_position = tempo_map.seconds_to_beat(0.48)  # ex: 0.97 → sera arrondi localement
```

---

## Fichier à créer : `backend/tempo_map.py`

### Structure complète attendue

```python
"""
tempo_map.py — Détection dynamique du tempo et construction de la TempoMap

Stratégie de détection (par ordre de préférence) :
  1. madmom (RNN beat tracker) — le plus précis pour la musique expressive
  2. librosa beat_track avancé (avec onset_envelope) — fallback rapide
  3. estimate_tempo_from_events — dernier recours (IOI basique)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Tuple, Optional

@dataclass
class TempoMap:
    beat_times: np.ndarray          # timestamps absolus de chaque beat (secondes)
    downbeat_times: np.ndarray      # timestamps des temps forts (début de mesure)
    estimated_meter: Tuple[int, int]  # ex: (4, 4)
    global_bpm: float               # BPM médian
    method: str                     # 'madmom' | 'librosa_advanced' | 'fallback'

    def seconds_to_beat(self, t_seconds: float) -> float:
        """
        Convertit un timestamp absolu (secondes) en position de beat fractionnaire.

        Algorithme :
        - Si t_seconds < beat_times[0] : retourne une position négative interpolée
        - Si t_seconds > beat_times[-1] : extrapole linéairement
        - Sinon : interpolation linéaire entre les deux beats encadrants

        Exemple :
          beat_times = [0.0, 0.52, 1.01, 1.55]  # beats 0, 1, 2, 3
          seconds_to_beat(0.48) → 0.923  (proche du beat 1)
          seconds_to_beat(0.52) → 1.000  (exactement sur le beat 1)
        """
        ...

    def beat_to_seconds(self, beat: float) -> float:
        """Inverse de seconds_to_beat — interpolation depuis la position de beat."""
        ...

    def local_bpm_at(self, t_seconds: float) -> float:
        """Retourne le BPM local à un instant donné (pour diagnostic)."""
        ...


def build_tempo_map(audio_path: str, note_events=None) -> TempoMap:
    """
    Fonction principale. Tente madmom, repli sur librosa, puis fallback IOI.

    Paramètres :
      audio_path   : chemin vers le fichier audio (MP3, WAV, FLAC)
      note_events  : optionnel — utilisé pour le fallback IOI si l'audio échoue

    Retour : TempoMap
    """
    # Ordre de tentative :
    try:
        return _build_with_madmom(audio_path)
    except ImportError:
        print("[TempoMap] madmom non disponible, repli sur librosa")
    except Exception as e:
        print(f"[TempoMap] madmom a échoué ({e}), repli sur librosa")

    try:
        return _build_with_librosa(audio_path)
    except Exception as e:
        print(f"[TempoMap] librosa a échoué ({e}), repli sur IOI")

    return _build_fallback(note_events)


def _build_with_madmom(audio_path: str) -> TempoMap:
    """
    Beat tracking avec madmom RNNBeatProcessor.

    Madmom utilise un RNN entraîné qui est bien plus robuste que librosa
    sur les tempos expressifs (rubato, ritardando).

    Code de référence :
      from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
      proc = DBNBeatTrackingProcessor(fps=100)
      act  = RNNBeatProcessor()(audio_path)
      beat_times = proc(act)  # → array de timestamps

    Points d'attention :
    - madmom peut être long à initialiser (modèle RNN) → mettre en cache si possible
    - Si le fichier est MP3, madmom peut avoir besoin de ffmpeg installé
    - beat_times est un array 1D de floats (secondes)
    """
    ...

    # Après avoir obtenu beat_times et downbeat_times, détecter la mesure :
    meter = _detect_meter(beat_times, downbeat_times)

    return TempoMap(
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        estimated_meter=meter,
        global_bpm=float(np.median(60.0 / np.diff(beat_times))),
        method='madmom'
    )


def _build_with_librosa(audio_path: str) -> TempoMap:
    """
    Beat tracking avec librosa en mode avancé.

    Différence avec V1 : on utilise l'onset_envelope et beat_track avec
    start_bpm estimé pour réduire les erreurs d'octave (94 vs 138 BPM).

    Code de référence :
      import librosa
      y, sr = librosa.load(audio_path, sr=None)
      onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
      tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
      beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    Points d'attention :
    - Utiliser aggregate=np.median (plus robuste que la moyenne par défaut)
    - Si le BPM estimé est > 200 ou < 50, diviser/multiplier par 2 (correction d'octave)
    - Générer downbeat_times heuristiquement (tous les N beats selon la mesure estimée)
    """
    ...


def _build_fallback(note_events=None, default_bpm: float = 120.0) -> TempoMap:
    """
    Dernier recours : beat times synthétiques à partir d'un BPM estimé par IOI.

    Si note_events est fourni, on estime le BPM par médiane des IOI (comme V1).
    Sinon, on utilise default_bpm = 120.

    Les beat_times sont ensuite générés linéairement (0.0, beat_s, 2*beat_s, ...).
    Cette méthode ne résout PAS le drift, elle est identique à la V1.
    """
    ...


def _detect_meter(beat_times: np.ndarray, downbeat_times: np.ndarray) -> Tuple[int, int]:
    """
    Détecte la mesure (numérateur, dénominateur) à partir des beat/downbeat times.

    Algorithme :
    1. Calculer le nombre moyen de beats entre deux downbeats
    2. Arrondir à l'entier le plus proche : 2→2/4, 3→3/4, 4→4/4, 6→6/8
    3. Valeurs supportées : (2,4), (3,4), (4,4), (6,8), (5,4)

    Si downbeat_times est vide ou ambigu, retourner (4, 4) par défaut.
    """
    ...


# ── Auto-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, os
    test_file = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(__file__), '..', 'UNICORN ACADEMY THEME.mp3')

    print(f"[Test] Analyse de : {test_file}")
    tm = build_tempo_map(test_file)
    print(f"  Méthode       : {tm.method}")
    print(f"  BPM global    : {tm.global_bpm:.1f}")
    print(f"  Mesure        : {tm.estimated_meter}")
    print(f"  Nombre beats  : {len(tm.beat_times)}")
    print(f"  5 premiers beats (s) : {tm.beat_times[:5]}")

    # Test de conversion
    t = 5.0
    b = tm.seconds_to_beat(t)
    t2 = tm.beat_to_seconds(b)
    print(f"  Conversion : {t}s → beat {b:.3f} → {t2:.3f}s (erreur : {abs(t-t2)*1000:.1f}ms)")
```

---

## Modifications `requirements.txt`

Ajouter les lignes suivantes :

```
# Beat tracking avancé (Phase 1)
madmom>=0.16
```

> **Note** : `madmom` nécessite Python < 3.12 et `cython`. Si l'installation échoue, utiliser
> la branche de fallback librosa. Vérifier la compatibilité avec le venv existant.

---

## Modification `app.py`

Remplacer dans la route `/api/transcribe` :

```python
# AVANT (V1) :
note_events, midi_data, tempo, warning_msgs = transcribe_audio(audio_path, options)

# APRÈS (V2) :
note_events, midi_data, _, warning_msgs = transcribe_audio(audio_path, options)

from tempo_map import build_tempo_map
tempo_map = build_tempo_map(audio_path, note_events=note_events)
tempo = int(tempo_map.global_bpm)  # pour compatibilité JSON

# Passer tempo_map aux étapes suivantes (Phase 2)
```

---

## Tests de validation

### Test 1 : Cohérence extrait vs morceau entier

```python
# Tester avec le fichier UNICORN ACADEMY THEME.mp3
# Le BPM global doit être dans la même "zone" (±15%) que sur un extrait de 30s
tm_full = build_tempo_map("UNICORN ACADEMY THEME.mp3")
# Extraire 30s (0-30s) avec librosa, sauvegarder en WAV temporaire
tm_extract = build_tempo_map("extrait_30s.wav")
assert abs(tm_full.global_bpm - tm_extract.global_bpm) / tm_full.global_bpm < 0.15
```

### Test 2 : Précision de la conversion `seconds_to_beat`

```python
# La conversion aller-retour doit être précise à <10ms
for t in [0.5, 1.2, 5.7, 15.3, 30.0]:
    b = tm.seconds_to_beat(t)
    t2 = tm.beat_to_seconds(b)
    assert abs(t - t2) < 0.010, f"Erreur trop grande à {t}s : {abs(t-t2)*1000:.1f}ms"
```

### Test 3 : Détection de mesure

```python
# Sur un fichier en 4/4, la mesure doit être détectée correctement
assert tm.estimated_meter == (4, 4)
```
