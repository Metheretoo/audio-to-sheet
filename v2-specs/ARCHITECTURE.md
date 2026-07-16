# Architecture V2 — Pipeline de transcription

## Vue d'ensemble du pipeline

```
                  ┌─────────────────────────────────────────────────────────┐
                  │                    PIPELINE V2                          │
                  └─────────────────────────────────────────────────────────┘

  [Fichier Audio]
       │
       ▼
  ┌─────────────────┐
  │  transcriber.py  │  ← INCHANGÉ (Phase 0 : garder tel quel)
  │  Piano Transcr.  │    Produit : note_events + midi_data
  │  / Basic Pitch   │
  └────────┬────────┘
           │ note_events: List[Tuple[float, float, int, float, list]]
           │   (start_s, end_s, pitch_midi, amplitude, pitch_bends)
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                       tempo_map.py [NOUVEAU]                        │
  │                                                                     │
  │  Entrée  : audio_path (str)                                         │
  │  Sortie  : TempoMap object                                          │
  │    - beat_times: np.ndarray  (timestamps absolus de chaque beat)    │
  │    - downbeat_times: np.ndarray (timestamps des temps forts)        │
  │    - estimated_meter: Tuple[int, int]  ex: (4, 4)                   │
  │    - global_bpm: float  (BPM médian, pour info)                     │
  │    - method: str  ('madmom' | 'librosa_advanced' | 'fallback')      │
  └────────┬────────────────────────────────────────────────────────────┘
           │ TempoMap
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                       quantizer.py [NOUVEAU]                        │
  │                                                                     │
  │  Entrée  : note_events + TempoMap + options                         │
  │  Sortie  : List[QuantizedNote]                                      │
  │    - beat_position: float  (position en beats depuis le début)      │
  │    - beat_duration: float  (durée en beats)                         │
  │    - pitch_midi: int                                                │
  │    - amplitude: float                                               │
  │    - hand: str  ('treble' | 'bass')                                 │
  │    - dur_str: str  ('q', '8', 'h', 'w', '16', ...)                 │
  │    - dots: int  (0 ou 1)                                            │
  └────────┬────────────────────────────────────────────────────────────┘
           │ List[QuantizedNote]
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                   voice_engine.py [NOUVEAU]                         │
  │                                                                     │
  │  Entrée  : List[QuantizedNote]                                      │
  │  Sortie  : VoiceSplit object                                        │
  │    - treble: List[QuantizedNote]  (main droite)                     │
  │    - bass:   List[QuantizedNote]  (main gauche)                     │
  └────────┬────────────────────────────────────────────────────────────┘
           │ VoiceSplit
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                  score_builder.py [NOUVEAU]                         │
  │                                                                     │
  │  Entrée  : VoiceSplit + TempoMap + key_sig                          │
  │  Sortie  : ScoreData (dict compatible JSON/VexFlow)                 │
  │    - tempo, timeSignature, keySignature                             │
  │    - measures: List[Measure]  (treble + bass par mesure)            │
  └────────┬────────────────────────────────────────────────────────────┘
           │ ScoreData (JSON)
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │            midi_parser.py (MODIFIÉ — rôle réduit)                   │
  │                                                                     │
  │  Garde uniquement :                                                  │
  │    - score_to_midi()      (export MIDI depuis JSON édité)           │
  │    - detect_key_signature()                                         │
  │    - midi_to_vexflow_key()                                          │
  │    - utilitaires VexFlow (beats_to_duration, etc.)                  │
  └────────┬────────────────────────────────────────────────────────────┘
           │ JSON VexFlow
           ▼
      [Frontend VexFlow — renderer.js]
```

---

## Contrats de données (Interfaces entre modules)

### 1. `note_events` — format V1 conservé

Produit par `transcriber.py`, consommé par `quantizer.py`.

```python
note_events: List[Tuple]
# Chaque tuple : (start_s, end_s, pitch_midi, amplitude, pitch_bends)
# Exemples :
# (0.42, 0.91, 60, 0.75, [])     ← Do4, 490ms, forte
# (1.23, 1.48, 52, 0.30, [])     ← Mi3, 250ms, piano
```

### 2. `TempoMap` — nouveau type de données

Défini dans `tempo_map.py`. Objet Python avec les attributs suivants :

```python
@dataclass
class TempoMap:
    beat_times: np.ndarray       # shape (N,) — timestamps des N beats en secondes
    downbeat_times: np.ndarray   # shape (M,) — timestamps des M temps forts
    estimated_meter: Tuple[int, int]  # ex: (4, 4), (3, 4), (6, 8)
    global_bpm: float            # BPM médian sur tout le morceau
    method: str                  # traceur utilisé

    def seconds_to_beat(self, t_seconds: float) -> float:
        """Convertit un timestamp absolu en position de beat (fractionnaire)."""
        ...

    def beat_to_seconds(self, beat: float) -> float:
        """Inverse : position de beat → timestamp."""
        ...
```

### 3. `QuantizedNote` — nouveau type de données

Défini dans `quantizer.py` :

```python
@dataclass
class QuantizedNote:
    pitch_midi: int
    amplitude: float
    beat_position: float   # position depuis le beat 0
    beat_duration: float   # durée en beats (ex: 1.0 = noire, 0.5 = croche)
    dur_str: str           # code VexFlow : 'q', '8', 'h', 'w', '16'
    dots: int              # 0 ou 1 (note pointée)
    hand: str              # 'treble' ou 'bass'
```

### 4. `ScoreData` — format JSON VexFlow (compatible V1)

Produit par `score_builder.py`. **Format identique à la V1** pour ne pas casser le frontend :

```json
{
  "tempo": 120,
  "timeSignature": [4, 4],
  "keySignature": "C",
  "totalMeasures": 8,
  "measures": [
    {
      "treble": [ ...notes VexFlow... ],
      "bass":   [ ...notes VexFlow... ]
    }
  ]
}
```

---

## Règles d'intégration dans `app.py`

Le fichier `app.py` est le point d'entrée. Il doit être modifié **en dernier** (Phase 4) pour orchestrer le nouveau pipeline.

**Flux V2 dans `app.py` :**

```python
# 1. Transcription brute (inchangé)
note_events, midi_data, _, warnings = transcribe_audio(audio_path, options)

# 2. TempoMap dynamique (NOUVEAU)
from tempo_map import build_tempo_map
tempo_map = build_tempo_map(audio_path)

# 3. Quantification (NOUVEAU)
from quantizer import quantize_notes
quantized = quantize_notes(note_events, tempo_map, options)

# 4. Séparation voix (NOUVEAU)
from voice_engine import split_voices
voices = split_voices(quantized, options)

# 5. Construction partition (NOUVEAU)
from score_builder import build_score
score_data = build_score(voices, tempo_map, key_sig, options)
```

---

## Fichiers à créer / modifier

| Fichier | Statut | Phase |
|---|---|---|
| `backend/tempo_map.py` | **NOUVEAU** | Phase 1 |
| `backend/quantizer.py` | **NOUVEAU** | Phase 2 |
| `backend/voice_engine.py` | **NOUVEAU** | Phase 3 |
| `backend/score_builder.py` | **NOUVEAU** | Phase 4 |
| `backend/app.py` | **MODIFIER** (orchestration) | Phase 4 |
| `backend/midi_parser.py` | **MODIFIER** (allégé) | Phase 4 |
| `frontend/js/renderer.js` | **MODIFIER** (tempo variable) | Phase 5 |
| `backend/requirements.txt` | **MODIFIER** (nouvelles dépendances) | Phase 1 |
