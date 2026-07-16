# API Contracts V4 — audio-to-sheet

## Contrats internes (Python)

### `config.py` — Configuration validée (Pydantic)

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class AudioConfig(BaseModel):
    sample_rate: int = 22050
    onset_threshold: float = Field(ge=0.0, le=1.0, default=0.3)
    min_note_duration: float = Field(gt=0, default=0.05)

class TranscriptionConfig(BaseModel):
    # Les 3 modèles déjà installés depuis la V3 — aucun nouveau modèle requis en V4
    model: Literal["piano_transcription", "transkun", "hft", "ensemble"] = "piano_transcription"
    use_ensemble: bool = False
    ensemble_models: List[str] = ["piano_transcription", "transkun", "hft"]
    ensemble_strategy: Literal["union", "intersection", "majority"] = "majority"
    use_hmm_smoothing: bool = False
    hmm_transition_weight: float = Field(ge=0.0, le=1.0, default=0.7)
    # NOUVEAU V4 : lire le CC64 (pédale sustain) depuis le MIDI Piano Transcription
    read_pedal_from_midi: bool = True   # Piano Transcription sort déjà CC64
    chunk_duration_sec: float = 30.0    # Durée des chunks (longs morceaux)


class TempoConfig(BaseModel):
    method: Literal["auto", "madmom", "librosa", "fallback", "manual"] = "auto"
    manual_bpm: Optional[float] = None
    manual_meter: Optional[tuple[int, int]] = None
    downbeat_detection: bool = True

class QuantizationConfig(BaseModel):
    grid_resolution: int = Field(ge=4, le=128, default=32)
    merge_threshold_ticks: int = Field(ge=0, default=2)
    chord_onset_tolerance_sec: float = Field(ge=0.0, default=0.04)
    chord_duration_normalization: bool = True
    staccato_threshold_ratio: float = Field(ge=0.0, le=1.0, default=0.3)
    legato_threshold_ratio: float = Field(ge=0.0, le=1.0, default=0.85)
    tuplet_detection: bool = True
    max_tuplet_ratio: int = Field(ge=2, le=12, default=6)

class VoiceSplitConfig(BaseModel):
    split_point_midi: int = Field(ge=21, le=108, default=60)
    use_smoothing: bool = True
    use_ml_fallback: bool = False
    # Nouveaux paramètres V4 — Voice Split guidé par l'harmonie
    use_harmonic_context: bool = True
    harmony_penalty_weight: float = Field(ge=0.0, default=50.0)  # Pénalité si on casse un accord connu
    bass_bonus_weight: float = Field(ge=0.0, default=20.0)        # Bonus si la basse va en LH
    arpeggio_max_span_beats: float = 1.0                          # Fenêtre de fusion d'arpèges


class HarmonicConfig(BaseModel):
    enabled: bool = True
    key_window_beats: float = 16.0           # Fenêtre Krumhansl-Schmuckler
    key_window_overlap: float = 0.5          # Chevauchement 50%
    onset_tolerance_ms: float = 30.0         # Tolérance pour grouper les notes en accord
    min_arpeggio_notes: int = 3              # Nb de notes minimum pour détecter un arpège
    min_grace_note_ms: float = 150.0         # Notes < 150ms = candidates ornement
    chord_confidence_threshold: float = 0.5  # Ignorer les accords < ce seuil de confiance

class ScoreConfig(BaseModel):
    detect_dynamics: bool = True
    detect_pedal: bool = True
    suggest_fingerings: bool = False
    key_detection: Literal["krumhansl", "temperley", "manual"] = "krumhansl"
    manual_key: Optional[str] = None
    # NOUVEAU V4 : pour le preset Jazz
    write_chord_symbols: bool = False  # Ex: affiche "Cm7" au-dessus de la portée

class ExportConfig(BaseModel):
    midi_ticks_per_beat: int = 480
    musicxml_version: str = "4.0"
    lilypond_pdf: bool = False
    measures_per_line: int = 4

class PipelineConfig(BaseModel):
    checkpoint_dir: str = "./checkpoints"
    save_intermediate: bool = True
    resume_from_checkpoint: bool = False

class Config(BaseModel):
    audio: AudioConfig = AudioConfig()
    transcription: TranscriptionConfig = TranscriptionConfig()
    tempo: TempoConfig = TempoConfig()
    quantization: QuantizationConfig = QuantizationConfig()
    voice_split: VoiceSplitConfig = VoiceSplitConfig()
    harmonic: HarmonicConfig = HarmonicConfig()   # NOUVEAU
    score: ScoreConfig = ScoreConfig()
    export: ExportConfig = ExportConfig()
    device: DeviceConfig = DeviceConfig()
    pipeline: PipelineConfig = PipelineConfig()

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
```

---

### `transcriber.py` — Transcription audio → NoteEvent

```python
from dataclasses import dataclass
from typing import List, Optional
import numpy as np

@dataclass
class NoteEvent:
    onset_sec: float
    offset_sec: float
    pitch_midi: float          # Peut être fractionnaire (ex: 60.3 = Do4 + 30 cents)
    velocity: int              # 0-127
    confidence: float = 1.0    # 0.0-1.0
    source: str = "piano_transcription"  # piano_transcription | basicpitch | hft | ensemble

class Transcriber:
    def __init__(self, config: TranscriptionConfig, device: DeviceConfig):
        self.config = config
        self.device = device
    
    async def transcribe(self, audio_path: str) -> List[NoteEvent]:
        """Transcrit un fichier audio en liste de NoteEvent (chunks automatiques)."""
        ...
    
    async def get_pedal_events(self) -> List[dict]:
        """
        Retourne les événements de pédale (Piano Transcription les sort séparément).
        Format: [{'start_beat': float, 'end_beat': float, 'start_sec': float, 'end_sec': float}]
        Appeler après transcribe().
        """
        ...
    
    async def transcribe_array(self, audio: np.ndarray, sr: int) -> List[NoteEvent]:
        """Transcrit depuis un array numpy (pour tests/streaming)."""
        ...
```

---

### `piano_roll.py` — NoteEvent[] → Slice[] (NOUVEAU)

```python
@dataclass
class Slice:
    """Atome harmonique : accord vertical ou arpège brisé fusionné."""
    beat_position: float       # Position en beats globaux
    duration_beats: float      # Durée en beats
    midi_pitches: List[int]    # Notes MIDI (triées, ascendant)
    is_arpeggio: bool = False  # True si notes brisées fusionnées
    pedal_active: bool = False # True si la pédale est enfoncée


class PianoRoll:
    def group_into_slices(
        self,
        qnotes: List[QuantizedNote],
        config: HarmonicConfig
    ) -> List[Slice]:
        """Groupe les QuantizedNote en Slices harmoniques."""
        ...

    def fuse_arpeggios(self, slices: List[Slice], config: HarmonicConfig) -> List[Slice]:
        """Fusionne les séquences rapides de notes en blocs harmoniques."""
        ...
```

---

### `harmonic_analyzer.py` — Slice[] → HarmonicContext (NOUVEAU)

```python
@dataclass
class ChordAnalysis:
    root: str              # Ex: "C", "F#", "Bb"
    quality: str           # "major" | "minor" | "dominant-seventh" | ...
    inversion: int         # 0=fondamentale, 1=1er renversement, 2=2e, ...
    roman_numeral: str     # Ex: "I", "V7", "ii6", "?"
    is_known_chord: bool   # False si music21 échoue
    bass_note: int         # MIDI pitch de la note la plus grave
    confidence: float      # 0.0 à 1.0


@dataclass
class HarmonicContext:
    global_key: str                # Ex: "F major", "C minor"
    local_keys: List[tuple]        # [(beat_start: float, key_name: str), ...]
    chord_map: dict                # {beat_position: float -> ChordAnalysis}
    phrase_boundaries: List[float] # Positions en beats (cadences V->I)
    ornaments: List[dict]          # [{'beat_position': float, 'pitch': int, 'type': str}]


class HarmonicAnalyzer:
    def __init__(self, config: HarmonicConfig): ...

    def build_harmonic_context(self, slices: List[Slice]) -> HarmonicContext:
        """Point d'entrée principal : analyse complète depuis les Slices."""
        ...

    def detect_keys(
        self, slices: List[Slice], window_beats: float = 16.0
    ) -> List[tuple]:
        """Krumhansl-Schmuckler par fenêtre glissante. Retourne [(beat, key_name)]."""
        ...

    def analyze_chord(self, sl: Slice, current_key: str) -> ChordAnalysis:
        """Analyse un Slice via music21. Retourne un ChordAnalysis."""
        ...

    def detect_ornaments(
        self, slices: List[Slice], beat_duration_sec: float
    ) -> List[dict]:
        """Détecte grace notes et trilles (durée < min_grace_note_ms)."""
        ...
```

---

### `voice_engine.py` — VoiceSplit guidé par HarmonicContext (MODIFIÉ)

Signature mise à jour pour accepter le `HarmonicContext` :

```python
class VoiceEngine:
    def split_with_harmony(
        self,
        qnotes: List[QuantizedNote],
        harmonic_ctx: HarmonicContext,
        config: VoiceSplitConfig
    ) -> VoiceSplit:
        """
        Sépare en LH / RH avec :
        1. Dijkstra (coût mélodique)
        2. Pénalité harmonique (ne pas casser un accord music21 connu)
        3. Bonus basse (note la plus grave de l'accord -> LH)
        """
        ...
```

---

### `midi_parser.py` — Parsing MIDI → NoteEvent

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class MidiNoteEvent:
    onset_sec: float
    offset_sec: float
    pitch_midi: int
    velocity: int
    track: int
    channel: int

class MidiParser:
    def parse(self, midi_path: str) -> List[MidiNoteEvent]:
        """Parse un fichier MIDI Type 0/1/2."""
        ...
    
    def parse_bytes(self, data: bytes) -> List[MidiNoteEvent]:
        """Parse depuis des bytes (upload web)."""
        ...
```

---

### `tempo_map.py` — Carte temporelle

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class TimeSignature(Enum):
    SIMPLE = "simple"
    COMPOUND = "compound"
    IRREGULAR = "irregular"

@dataclass
class TempoChange:
    beat: float          # Position en beats depuis le début
    bpm: float
    time_signature: tuple[int, int] = (4, 4)  # (numérateur, dénominateur)

@dataclass
class Downbeat:
    beat: float
    measure_number: int
    confidence: float

@dataclass
class TempoMap:
    tempo_changes: List[TempoChange]
    downbeats: List[Downbeat]
    initial_bpm: float
    initial_time_signature: tuple[int, int] = (4, 4)
    
    def sec_to_beat(self, sec: float) -> float:
        """Convertit secondes → beats."""
        ...
    
    def beat_to_sec(self, beat: float) -> float:
        """Convertit beats → secondes."""
        ...
    
    def get_measure_at_beat(self, beat: float) -> int:
        """Retourne le numéro de mesure (1-indexed)."""
        ...
    
    def get_beat_in_measure(self, beat: float) -> float:
        """Position dans la mesure (0.0 à time_sig_num)."""
        ...

class TempoMapBuilder:
    def __init__(self, config: TempoConfig):
        self.config = config
    
    def build(self, audio_path: str, events: List[NoteEvent]) -> TempoMap:
        """Construit la TempoMap depuis audio + événements."""
        ...
    
    def build_from_midi(self, midi_path: str) -> TempoMap:
        """Construit depuis un MIDI (tempo map + time sig)."""
        ...
```

---

### `quantizer.py` — Quantification

```python
from dataclasses import dataclass, field
from typing import List, Optional, Literal
from enum import Enum

class NoteDuration(Enum):
    WHOLE = "w"
    HALF = "h"
    QUARTER = "q"
    EIGHTH = "e"
    SIXTEENTH = "s"
    THIRTY_SECOND = "t"
    SIXTY_FOURTH = "x"

@dataclass
class QuantizedNote:
    pitch_midi: int
    beat_position: float      # Position en beats (quantifiée)
    beat_duration: float      # Durée en beats (quantifiée)
    duration_str: str         # 'w', 'h', 'q', 'e', 's', 't', 'x'
    dots: int = 0
    is_rest: bool = False
    velocity: int = 64
    amplitude: float = 0.5
    hand: str = "treble"      # 'treble' | 'bass'
    tuplet: Optional[dict] = None  # {"ratio": 3/2, "notes": 3} pour triolet
    staccato: bool = False
    legato: bool = False
    dynamic: Optional[str] = None  # 'pp', 'p', 'mp', 'mf', 'f', 'ff'
    articulation: Optional[str] = None  # 'staccato', 'legato', 'accent', 'tenuto'

class Quantizer:
    def __init__(self, config: QuantizationConfig, tempo_map: TempoMap):
        self.config = config
        self.tempo_map = tempo_map
    
    def quantize(self, events: List[NoteEvent]) -> List[QuantizedNote]:
        """Quantifie les événements sur la grille."""
        ...
    
    def _detect_tuplets(self, notes: List[QuantizedNote]) -> List[QuantizedNote]:
        """Détecte et marque les tuplets (triolets, quintolets, etc.)."""
        ...
    
    def _merge_close_notes(self, notes: List[QuantizedNote]) -> List[QuantizedNote]:
        """Fusionne les notes très proches en accords (cluster temporel) et normalise leurs durées."""
        ...
    
    def _detect_articulation(self, notes: List[QuantizedNote]) -> List[QuantizedNote]:
        """Détecte staccato/legato selon ratio durée/grille."""
        ...
```

---

### `voice_engine.py` — Séparation mains

```python
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from quantizer import QuantizedNote

@dataclass
class StaffVoices:
    voices: Dict[int, List[QuantizedNote]] = field(default_factory=lambda: {1: []}) # ex: {1: [notes...], 2: [notes...]}

@dataclass
class VoiceSplit:
    treble: StaffVoices = field(default_factory=StaffVoices)  # Main droite (portée du haut)
    bass:   StaffVoices = field(default_factory=StaffVoices)  # Main gauche (portée du bas)

class VoiceEngine:
    def __init__(self, config: VoiceSplitConfig):
        self.config = config
    
    def split(self, notes: List[QuantizedNote]) -> VoiceSplit:
        """Sépare les notes en deux mains (treble/bass), puis en voix internes (polyphonie)."""
        ...
    
    def split_with_ml_fallback(self, notes: List[QuantizedNote], ml_model) -> VoiceSplit:
        """Utilise le modèle ML en fallback si configuré."""
        ...

# Fonctions utilitaires exposées
def analyze_harmony(group: List[QuantizedNote]) -> dict:
    """Analyse harmonique d'un groupe de notes simultanées."""
    ...

def analyze_contour_advanced(notes: List[QuantizedNote], window: float = 0.5) -> dict:
    """Analyse de contour mélodique avancée."""
    ...

def smooth_voice_split(treble: List[QuantizedNote], bass: List[QuantizedNote], options: dict = None) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """Lissage des changements de main (Dijkstra)."""
    ...

def apply_dynamics(notes: List[QuantizedNote], options: dict = None) -> List[QuantizedNote]:
    """Applique les scores de dynamique."""
    ...
```

---

### `score_builder.py` — Construction partition

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from voice_engine import VoiceSplit
from tempo_map import TempoMap

@dataclass
class Measure:
    number: int
    treble: List[dict] = field(default_factory=list)  # Notes format VexFlow
    bass:   List[dict] = field(default_factory=list)
    time_signature: tuple[int, int] = (4, 4)
    key_signature: str = "C"
    dynamics: List[dict] = field(default_factory=list)  # {beat, dynamic, type}
    pedal: List[dict] = field(default_factory=list)     # {start_beat, end_beat, type}
    fingerings: List[dict] = field(default_factory=list) # {note_id, finger}

@dataclass
class ScoreData:
    measures: List[Measure]
    tempo_map: TempoMap
    metadata: Dict[str, any] = field(default_factory=dict)
    # metadata: title, composer, tempo, key, time_sig, etc.

class ScoreBuilder:
    def __init__(self, config: ScoreConfig):
        self.config = config
    
    def build(self, voices: VoiceSplit, tempo_map: TempoMap) -> ScoreData:
        """Construit la structure de partition complète."""
        ...
    
    def _build_measures(self, voices: VoiceSplit, tempo_map: TempoMap) -> List[Measure]:
        """Découpe en mesures selon la carte temporelle."""
        ...
    
    def _detect_dynamics(self, notes: List[QuantizedNote]) -> List[dict]:
        """Détecte les marques de dynamique (pp, p, mp, mf, f, ff)."""
        ...
    
    def _detect_pedal(self, notes: List[QuantizedNote]) -> List[dict]:
        """Détecte les événements de pédale (sustain)."""
        ...
    
    def _suggest_fingerings(self, notes: List[QuantizedNote]) -> List[dict]:
        """Suggère des doigtés basiques selon la tonalité."""
        ...
    
    def _detect_key_signature(self, notes: List[QuantizedNote]) -> str:
        """Détecte l'armure (Krumhansl-Schmuckler ou Temperley)."""
        ...
```

---

### `ensemble_voter.py` — Vote d'ensemble

```python
from dataclasses import dataclass
from typing import List
from transcriber import NoteEvent

@dataclass
class EnsembleConfig:
    models: List[str] = ["basicpitch", "hft"]
    onset_tolerance_sec: float = 0.05
    pitch_tolerance_semitones: float = 0.5
    min_votes: int = 2
    weight_by_confidence: bool = True

class EnsembleVoter:
    def __init__(self, config: EnsembleConfig):
        self.config = config
    
    def vote(self, model_outputs: List[List[NoteEvent]]) -> List[NoteEvent]:
        """
        Vote majoritaire pondéré par confiance.
        
        Algorithme:
        1. Aligner les onsets (tolérance onset_tolerance_sec)
        2. Grouper les notes de même pitch (± pitch_tolerance_semitones)
        3. Pour chaque groupe: garder si votes >= min_votes
        4. Moyenne pondérée des attributs (onset, pitch, velocity)
        """
        ...
```

---

### `hmm_smoother.py` — Lissage Viterbi

```python
from dataclasses import dataclass
from typing import List
from transcriber import NoteEvent
import numpy as np

@dataclass
class HMMConfig:
    transition_weight: float = 0.7      # Poids transition vs observation
    pitch_states: int = 88              # Nombre d'états pitch (A0-C8)
    max_jump_semitones: int = 12        # Saut max entre notes consécutives
    onset_sigma: float = 0.05           # Écart-type onset (secondes)

class HMMSmoother:
    def __init__(self, config: HMMConfig):
        self.config = config
    
    def smooth(self, events: List[NoteEvent]) -> List[NoteEvent]:
        """
        Lissage Viterbi sur la séquence d'événements.
        
        États: pitch MIDI discrétisé (0-87 pour A0-C8)
        Observations: pitch_midi continu + onset_sec
        Transitions: pénalité pour sauts > max_jump_semitones
        """
        ...
```

---

### `pipeline.py` — Orchestration

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
import json
import asyncio

@dataclass
class Checkpoint:
    stage: str
    data: Any
    timestamp: float

@dataclass
class PipelineResult:
    score: ScoreData
    midi_path: Optional[str]
    musicxml_path: Optional[str]
    pdf_path: Optional[str]
    checkpoints: List[Checkpoint] = field(default_factory=list)
    metrics: Optional[Dict] = None

class Pipeline:
    def __init__(self, config: Config, hooks: Optional[PipelineHooks] = None):
        self.config = config
        self.hooks = hooks or PipelineHooks()
        self.checkpoints: List[Checkpoint] = []
    
    async def run(self, audio_path: str) -> PipelineResult:
        """Exécute le pipeline complet."""
        # 1. Transcription
        events = await self._run_transcription(audio_path)
        self._save_checkpoint("transcription", events)
        
        # 2. Ensemble voting (optionnel)
        if self.config.transcription.use_ensemble:
            events = self._run_ensemble_voting(events)
            self._save_checkpoint("ensemble_vote", events)
        
        # 3. HMM smoothing (optionnel)
        if self.config.transcription.use_hmm_smoothing:
            events = self._run_hmm_smoothing(events)
            self._save_checkpoint("hmm_smooth", events)
        
        # 4. Tempo map
        tempo_map = self._run_tempo_map(audio_path, events)
        self._save_checkpoint("tempo_map", tempo_map)
        
        # 5. Quantization
        qnotes = self._run_quantization(events, tempo_map)
        self._save_checkpoint("quantization", qnotes)
        
        # 6. Voice split
        voices = self._run_voice_split(qnotes)
        self._save_checkpoint("voice_split", voices)
        
        # 7. Score building
        score = self._run_score_builder(voices, tempo_map)
        self._save_checkpoint("score_build", score)
        
        # 8. Exports
        midi_path = self._run_midi_export(score, qnotes)
        musicxml_path = self._run_musicxml_export(score)
        pdf_path = self._run_pdf_export(score) if self.config.export.lilypond_pdf else None
        
        return PipelineResult(score, midi_path, musicxml_path, pdf_path, self.checkpoints)
    
    def _save_checkpoint(self, stage: str, data: Any):
        if not self.config.pipeline.save_intermediate:
            return
        path = Path(self.config.pipeline.checkpoint_dir) / f"{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Sérialisation JSON (dataclasses → dict)
        with open(path, 'w') as f:
            json.dump(self._serialize(data), f, indent=2)
        self.checkpoints.append(Checkpoint(stage, str(path), time.time()))
    
    def resume_from_checkpoint(self, checkpoint_dir: str) -> PipelineResult:
        """Reprend le pipeline depuis un checkpoint."""
        ...
```

---

### `quality_metrics.py` — Métriques qualité

```python
from dataclasses import dataclass
from typing import List, Optional
from transcriber import NoteEvent

@dataclass
class QualityReport:
    onset_f1: float
    onset_precision: float
    onset_recall: float
    pitch_accuracy: float          # % notes pitch correct (±0.5 semitone)
    pitch_rmse_cents: float        # RMSE en cents
    velocity_correlation: float    # Corrélation vélocité vs ground truth
    voice_split_accuracy: float    # % notes correctes LH/RH
    measure_alignment_score: float # Alignement mesures (0-1)
    overall_score: float           # Score global pondéré

class QualityMetrics:
    def __init__(self, onset_tolerance_sec: float = 0.05, pitch_tolerance_cents: float = 50):
        self.onset_tolerance = onset_tolerance_sec
        self.pitch_tolerance = pitch_tolerance_cents
    
    def evaluate(self, predicted: List[NoteEvent], ground_truth: List[NoteEvent]) -> QualityReport:
        """Évalue la qualité vs ground truth."""
        ...
    
    def evaluate_voice_split(self, predicted: VoiceSplit, ground_truth: VoiceSplit) -> float:
        """Évalue la séparation mains."""
        ...
```

---

### `ornament_detector.py` — Détection ornementations

```python
from dataclasses import dataclass
from typing import List, Optional
from transcriber import NoteEvent

@dataclass
class Ornament:
    type: str              # "trill", "mordent", "turn", "appoggiatura", "acciaccatura"
    main_note_idx: int     # Index de la note principale dans la séquence
    start_idx: int         # Index de début de l'ornementation
    end_idx: int           # Index de fin
    confidence: float

class OrnamentDetector:
    def __init__(self, min_ornament_duration: float = 0.05, max_ornament_duration: float = 0.3):
        self.min_dur = min_ornament_duration
        self.max_dur = max_ornament_duration
    
    def detect(self, events: List[NoteEvent]) -> List[Ornament]:
        """
        Détecte les ornementations par analyse de patterns:
        - Trille: alternance rapide note principale/note supérieure
        - Mordant: note principale → note inférieure → note principale
        - Tour: note principale → sup → principale → inf → principale
        - Appogiature: note d'ornement + note principale (durée volée)
        """
        ...
```

---

## Contrats HTTP (Frontend ↔ Backend)

### `POST /api/transcribe`

```json
// Request
{
  "audio_file": "base64_or_multipart",
  "config": { /* Config.yaml subset */ },
  "options": {
    "return_checkpoints": false,
    "return_metrics": false
  }
}

// Response (200)
{
  "job_id": "uuid",
  "status": "completed",
  "result": {
    "score_data": { /* ScoreData JSON */ },
    "midi_url": "/api/download/job_id/output.mid",
    "musicxml_url": "/api/download/job_id/output.musicxml",
    "pdf_url": "/api/download/job_id/output.pdf",
    "checkpoints": [ /* Checkpoint[] */ ],
    "metrics": { /* QualityReport */ }
  }
}

// Response (202 - async)
{
  "job_id": "uuid",
  "status": "processing",
  "progress": 0.3,
  "current_stage": "quantization"
}
```

### `GET /api/jobs/{job_id}/status`

```json
{
  "job_id": "uuid",
  "status": "processing|completed|failed",
  "progress": 0.65,
  "current_stage": "voice_split",
  "stages_completed": ["transcription", "tempo_map", "quantization"],
  "eta_seconds": 12
}
```

### `GET /api/download/{job_id}/{filename}`

Retourne le fichier binaire avec headers appropriés.

### `POST /api/validate-config`

```json
// Request
{ "config": { /* Config.yaml */ } }

// Response
{ "valid": true, "warnings": [], "errors": [] }
```

---

## WebSocket (Progression temps réel)

```
WS /api/ws/{job_id}

Server → Client:
{ "type": "progress", "stage": "quantization", "progress": 0.6, "message": "Quantifying 1247 notes..." }
{ "type": "checkpoint", "stage": "quantization", "path": "./checkpoints/quantization.json" }
{ "type": "complete", "result": { ... } }
{ "type": "error", "stage": "transcription", "message": "Model load failed" }
```

---

## Références

- `ARCHITECTURE.md` — Architecture globale
- `DATA_FORMATS.md` — Structures de données détaillées
- `TEST_STRATEGY.md` — Tests et CI/CD
- `MIGRATION_V3_V4.md` — Migration