# Data Formats V4 — audio-to-sheet

## Structures de données principales

### `NoteEvent` — Événement note brut (transcription)

```python
@dataclass
class NoteEvent:
    onset_sec: float           # Temps d'attaque (secondes)
    offset_sec: float          # Temps de relâchement (secondes)
    pitch_midi: float          # Pitch MIDI continu (ex: 60.3 = Do4 + 30 cents)
    velocity: int              # Vélocité MIDI 0-127
    confidence: float = 1.0    # Confiance modèle 0.0-1.0
    source: str = "basicpitch" # "basicpitch" | "hft" | "ensemble"
```

**Sérialisation JSON :**
```json
{
  "onset_sec": 1.234,
  "offset_sec": 2.456,
  "pitch_midi": 60.3,
  "velocity": 92,
  "confidence": 0.94,
  "source": "basicpitch"
}
```

---

### `MidiNoteEvent` — Événement note MIDI (parsing)

```python
@dataclass
class MidiNoteEvent:
    onset_sec: float
    offset_sec: float
    pitch_midi: int            # Entier (note MIDI standard)
    velocity: int              # 0-127
    track: int                 # Numéro de piste
    channel: int               # Canal MIDI 0-15
```

---

### `QuantizedNote` — Note quantifiée (grille rythmique)

```python
@dataclass
class QuantizedNote:
    pitch_midi: int                    # Pitch MIDI entier
    beat_position: float               # Position en beats (quantifiée)
    beat_duration: float               # Durée en beats (quantifiée)
    duration_str: str                  # 'w'|'h'|'q'|'e'|'s'|'t'|'x'
    dots: int = 0                      # Points d'augmentation (0-3)
    is_rest: bool = False              # True si silence
    velocity: int = 64                 # Vélocité
    amplitude: float = 0.5             # Amplitude normalisée 0-1
    hand: str = "treble"               # 'treble' | 'bass'
    voice_idx: int = 1                 # Index de la voix (1 ou 2) pour la polyphonie intra-portée
    tuplet: Optional[dict] = None      # {"ratio": 1.5, "notes": 3, "bracket": true}
    staccato: bool = False
    legato: bool = False
    dynamic: Optional[str] = None      # 'pp'|'p'|'mp'|'mf'|'f'|'ff'
    articulation: Optional[str] = None # 'staccato'|'legato'|'accent'|'tenuto'
```

**Durées supportées :**
| Symbole | Nom | Fraction de ronde |
|---------|-----|-------------------|
| `w` | Ronde | 1 |
| `h` | Blanche | 1/2 |
| `q` | Noire | 1/4 |
| `e` | Croche | 1/8 |
| `s` | Double croche | 1/16 |
| `t` | Triple croche | 1/32 |
| `x` | Quadruple croche | 1/64 |

**Tuplet format :**
```json
{
  "ratio": 1.5,
  "notes": 3,
  "bracket": true,
  "number": true
}
```
- `ratio` = durée réelle / durée notée (ex: triolet = 3/2 = 1.5)
- `notes` = nombre de notes dans le tuplet
- `bracket` = afficher l'accolade
- `number` = afficher le chiffre

---

### `VoiceSplit` — Séparation mains

```python
@dataclass
class StaffVoices:
    voices: Dict[int, List[QuantizedNote]] = field(default_factory=lambda: {1: []}) # ex: {1: [notes...], 2: [notes...]}

@dataclass
class VoiceSplit:
    treble: StaffVoices = field(default_factory=StaffVoices)  # Main droite (portée du haut)
    bass:   StaffVoices = field(default_factory=StaffVoices)  # Main gauche (portée du bas)
```

---

### `TempoMap` — Carte temporelle

```python
@dataclass
class TempoChange:
    beat: float                    # Position en beats
    bpm: float                     # Tempo en BPM
    time_signature: tuple[int, int] = (4, 4)  # (num, denom)

@dataclass
class Downbeat:
    beat: float                    # Position en beats
    measure_number: int            # Numéro mesure (1-indexed)
    confidence: float              # 0.0-1.0

@dataclass
class TempoMap:
    tempo_changes: List[TempoChange]
    downbeats: List[Downbeat]
    initial_bpm: float
    initial_time_signature: tuple[int, int] = (4, 4)
```

**Exemple JSON :**
```json
{
  "tempo_changes": [
    {"beat": 0.0, "bpm": 120.0, "time_signature": [4, 4]},
    {"beat": 32.0, "bpm": 100.0, "time_signature": [3, 4]}
  ],
  "downbeats": [
    {"beat": 0.0, "measure_number": 1, "confidence": 0.95},
    {"beat": 4.0, "measure_number": 2, "confidence": 0.92}
  ],
  "initial_bpm": 120.0,
  "initial_time_signature": [4, 4]
}
```

---

### `ScoreData` — Structure partition complète

```python
@dataclass
class Measure:
    number: int
    treble: List[dict] = field(default_factory=list)  # Notes format VexFlow
    bass:   List[dict] = field(default_factory=list)
    time_signature: tuple[int, int] = (4, 4)
    key_signature: str = "C"
    dynamics: List[dict] = field(default_factory=list)  # {"beat": 1.0, "dynamic": "f", "type": "instant"}
    pedal: List[dict] = field(default_factory=list)     # {"start_beat": 1.0, "end_beat": 4.0, "type": "sustain"}
    fingerings: List[dict] = field(default_factory=list) # {"note_id": "n123", "finger": 2}

@dataclass
class ScoreData:
    measures: List[Measure]
    tempo_map: TempoMap
    metadata: Dict[str, any] = field(default_factory=dict)
```

**Métadonnées standard :**
```json
{
  "title": "Transcription AudioScore",
  "composer": "Unknown",
  "tempo": 120,
  "key_signature": "C",
  "time_signature": [4, 4],
  "duration_sec": 45.2,
  "measures_count": 16,
  "total_notes": 234,
  "transcription_date": "2025-01-15T10:30:00Z",
  "software": "AudioScore v4.0",
  "models_used": ["basicpitch"],
  "config_hash": "sha256:abc123..."
}
```

**Format note VexFlow (dans Measure.treble/bass) :**
```json
{
  "id": "n123",
  "keys": ["c/4", "e/4", "g/4"],
  "duration": "q",
  "dots": 0,
  "isRest": false,
  "beat": 1.0,
  "hand": "treble",
  "voice": 1,
  "tuplet": {"ratio": 1.5, "notes": 3},
  "staccato": false,
  "legato": true,
  "dynamic": "mf",
  "articulation": "legato",
  "fingering": 2
}
```

- `keys` : format VexFlow `"note/octave"` (ex: `"c/4"`, `"f#/5"`, `"bb/3"`)
- `duration` : `'w'|'h'|'q'|'e'|'s'|'t'|'x'`
- `beat` : position dans la mesure (0.0 à numérateur)

**Dynamiques :**
```json
{"beat": 1.0, "dynamic": "f", "type": "instant"}      // Subito
{"beat": 2.0, "dynamic": "cresc", "type": "hairpin", "end_beat": 4.0, "end_dynamic": "ff"}
```

**Pédale :**
```json
{"start_beat": 1.0, "end_beat": 4.0, "type": "sustain"}
{"start_beat": 5.0, "end_beat": 8.0, "type": "sostenuto"}
{"start_beat": 9.0, "end_beat": 12.0, "type": "una_corda"}
```

---

### `Checkpoint` — Point de reprise pipeline

```python
@dataclass
class Checkpoint:
    stage: str                   # "transcription" | "ensemble_vote" | "hmm_smooth" | "tempo_map" | "quantization" | "voice_split" | "score_build"
    data: Any                    # Données sérialisées (JSON)
    timestamp: float             # Unix timestamp
```

**Fichier checkpoint JSON :**
```json
{
  "stage": "quantization",
  "data": { /* QuantizedNote[] sérialisé */ },
  "timestamp": 1705312200.123
}
```

---

### `QualityReport` — Rapport qualité

```python
@dataclass
class QualityReport:
    onset_f1: float
    onset_precision: float
    onset_recall: float
    pitch_accuracy: float           # 0.0-1.0
    pitch_rmse_cents: float         # RMSE en cents
    velocity_correlation: float     # -1.0 à 1.0
    voice_split_accuracy: float     # 0.0-1.0
    measure_alignment_score: float  # 0.0-1.0
    overall_score: float            # 0.0-1.0 (pondéré)
```

---

### `Ornament` — Ornementation détectée

```python
@dataclass
class Ornament:
    type: str                       # "trill" | "mordent" | "turn" | "appoggiatura" | "acciaccatura"
    main_note_idx: int              # Index note principale
    start_idx: int                  # Index début ornement
    end_idx: int                    # Index fin ornement
    confidence: float               # 0.0-1.0
```

---

## Formats d'export

### MIDI (Standard MIDI File Type 1)

- **Ticks par noire** : 480 (configurable)
- **Pistes** : 
  - Track 0 : Meta (tempo, time signature, key signature)
  - Track 1 : Main droite (treble)
  - Track 2 : Main gauche (bass)
  - Track 3+ : Autres voix si applicable
- **Événements** : Note On/Off, Control Change (sustain pedal CC64), Program Change

### MusicXML 4.0 (Partwise)

Structure principale :
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <work>
    <work-title>Transcription AudioScore</work-title>
  </work>
  <identification>
    <encoding>
      <software>AudioScore</software>
      <encoding-date>2025-01-15</encoding-date>
    </encoding>
  </identification>
  <part-list>
    <score-part id="P1">
      <part-name>Piano</part-name>
      <part-abbreviation>Pno.</part-abbreviation>
      <score-instrument id="P1-I1">
        <instrument-name>Piano</instrument-name>
      </score-instrument>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration>
        <type>quarter</type>
        <voice>1</voice>
        <staff>1</staff>
      </note>
      <!-- ... -->
    </measure>
  </part>
</score-partwise>
```

**Éléments inclus :**
- `<attributes>` : divisions, key, time, clef (par mesure si changement)
- `<note>` : pitch/rest, duration, type, dots, voice, staff, stem, beam, notations
- `<notations>` : dynamics, articulations, ornaments, technical (fingerings), slurs, tied
- `<direction>` : dynamics (wedge, words), pedal, metronome, wedge
- `<barline>` : style, repeat, ending

### LilyPond → PDF (optionnel)

Template minimal :
```lilypond
\version "2.24.0"
\header {
  title = "Transcription AudioScore"
  composer = "Unknown"
  tagline = ##f
}
global = {
  \key c \major
  \time 4/4
  \tempo 4=120
}
right = \relative c'' {
  \global
  c4 e g c
}
left = \relative c {
  \global
  \clef bass
  c2 g
}
\score {
  \new PianoStaff <<
    \new Staff = "right" \right
    \new Staff = "left" \left
  >>
  \layout { }
  \midi { }
}
```

---

## Configuration YAML (config.yaml)

```yaml
audio:
  sample_rate: 22050
  onset_threshold: 0.3
  min_note_duration: 0.05

transcription:
  model: "basicpitch"           # basicpitch | hft | ensemble
  use_ensemble: false
  ensemble_models: ["basicpitch", "hft"]
  use_hmm_smoothing: true
  hmm_transition_weight: 0.7

tempo:
  method: "auto"                # auto | madmom | librosa | fallback | manual
  manual_bpm: null
  downbeat_detection: true

quantization:
  grid_resolution: 32           # 4-128
  merge_threshold_ticks: 2
  staccato_threshold_ratio: 0.3
  legato_threshold_ratio: 0.85
  tuplet_detection: true
  max_tuplet_ratio: 6

voice_split:
  split_point_midi: 60          # 21-108 (Do4 par défaut)
  use_smoothing: true
  use_ml_fallback: false

score:
  detect_dynamics: true
  detect_pedal: true
  suggest_fingerings: false
  key_detection: "krumhansl"    # krumhansl | temperley | manual
  manual_key: null

export:
  midi_ticks_per_beat: 480
  musicxml_version: "4.0"
  lilypond_pdf: false
  measures_per_line: 4

pipeline:
  checkpoint_dir: "./checkpoints"
  save_intermediate: true
  resume_from_checkpoint: false
```

---

## Messages WebSocket

### Progression
```json
{
  "type": "progress",
  "stage": "quantization",
  "progress": 0.65,
  "message": "Quantifying 1247 notes...",
  "details": {
    "notes_processed": 812,
    "total_notes": 1247
  }
}
```

### Checkpoint
```json
{
  "type": "checkpoint",
  "stage": "quantization",
  "path": "./checkpoints/quantization.json",
  "size_bytes": 245760
}
```

### Completion
```json
{
  "type": "complete",
  "result": {
    "job_id": "uuid",
    "score_data": { /* ScoreData */ },
    "midi_url": "/api/download/uuid/output.mid",
    "musicxml_url": "/api/download/uuid/output.musicxml",
    "pdf_url": "/api/download/uuid/output.pdf",
    "checkpoints": [ /* Checkpoint[] */ ],
    "metrics": { /* QualityReport */ }
  }
}
```

### Erreur
```json
{
  "type": "error",
  "stage": "transcription",
  "message": "Model load failed: CUDA out of memory",
  "recoverable": true,
  "suggestion": "Reduce batch size or use CPU fallback"
}
```

---

## Références

- `ARCHITECTURE.md` — Architecture globale
- `API_CONTRACTS.md` — Contrats d'API
- `TEST_STRATEGY.md` — Tests et CI/CD
- `MIGRATION_V3_V4.md` — Migration