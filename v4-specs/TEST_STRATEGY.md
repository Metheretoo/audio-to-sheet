# Test Strategy V4 — audio-to-sheet

## Objectifs

1. **Couverture** : ≥ 80% sur modules critiques (quantizer, voice_engine, tempo_map, score_builder)
2. **Déterminisme** : Tests reproductibles (seeds fixes, mocks déterministes)
3. **Vitesse** : Suite complète < 60s (unit) + < 5min (intégration)
4. **Régression** : Détection automatique via CI/CD

---

## Pyramide de tests

```
                    ┌─────────────────┐
                    │  E2E (3-5)      │  ← Pipeline complet audio→PDF
                    ├─────────────────┤
              ┌─────│ Integration (10)│  ← Modules enchaînés
              │     ├─────────────────┤
              │     │  Unit (50+)     │  ← Fonctions pures, modules isolés
              │     └─────────────────┘
              │
         ┌────┴────┐
         │ Property│  ← Hypothesis (propriétés mathématiques)
         │ Based   │
         └─────────┘
```

---

## Tests Unitaires (pytest)

### Structure

```
tests/
├── unit/
│   ├── test_config.py
│   ├── test_transcriber.py
│   ├── test_midi_parser.py
│   ├── test_tempo_map.py
│   ├── test_quantizer.py
│   ├── test_voice_engine.py
│   ├── test_score_builder.py
│   ├── test_ensemble_voter.py
│   ├── test_hmm_smoother.py
│   ├── test_quality_metrics.py
│   ├── test_ornament_detector.py
│   ├── test_hand_split_ml.py
│   └── test_exporters/
│       ├── test_midi_exporter.py
│       ├── test_musicxml_exporter.py
│       └── test_lilypond_exporter.py
├── integration/
│   ├── test_pipeline_audio.py
│   ├── test_pipeline_midi.py
│   ├── test_checkpoint_resume.py
│   └── test_ensemble_pipeline.py
├── e2e/
│   ├── test_full_pipeline.py
│   └── test_frontend_rendering.py
├── property/
│   ├── test_quantizer_properties.py
│   └── test_voice_engine_properties.py
├── fixtures/
│   ├── audio/
│   │   ├── simple_c_major.wav
│   │   ├── chord_progression.wav
│   │   ├── polyphonic_piano.wav
│   │   └── with_pedal.wav
│   ├── midi/
│   │   ├── simple.mid
│   │   ├── multi_track.mid
│   │   └── with_tempo_changes.mid
│   └── ground_truth/
│       ├── simple_c_major.json
│       ├── chord_progression.json
│       └── polyphonic_piano.json
└── conftest.py
```

### Fixtures partagées (`conftest.py`)

```python
import pytest
import numpy as np
from pathlib import Path

@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def simple_audio(fixtures_dir) -> str:
    return str(fixtures_dir / "audio" / "simple_c_major.wav")

@pytest.fixture
def simple_midi(fixtures_dir) -> str:
    return str(fixtures_dir / "midi" / "simple.mid")

@pytest.fixture
def ground_truth_simple(fixtures_dir) -> dict:
    import json
    with open(fixtures_dir / "ground_truth" / "simple_c_major.json") as f:
        return json.load(f)

@pytest.fixture
def sample_note_events() -> list:
    """NoteEvent déterministes pour tests unitaires."""
    from transcriber import NoteEvent
    return [
        NoteEvent(onset_sec=0.0, offset_sec=1.0, pitch_midi=60.0, velocity=100, confidence=1.0),
        NoteEvent(onset_sec=1.0, offset_sec=2.0, pitch_midi=64.0, velocity=90, confidence=0.95),
        NoteEvent(onset_sec=2.0, offset_sec=3.0, pitch_midi=67.0, velocity=80, confidence=0.9),
    ]

@pytest.fixture
def sample_tempo_map() -> TempoMap:
    from tempo_map import TempoMap, TempoChange, Downbeat
    return TempoMap(
        tempo_changes=[TempoChange(beat=0.0, bpm=120.0)],
        downbeats=[Downbeat(beat=0.0, measure_number=1, confidence=1.0)],
        initial_bpm=120.0
    )
```

---

## Tests par module

### `test_config.py`

```python
def test_config_defaults():
    from config import Config
    cfg = Config()
    assert cfg.audio.sample_rate == 22050
    assert cfg.transcription.model == "basicpitch"

def test_config_from_yaml(tmp_path):
    from config import Config
    yaml_content = """
audio:
  sample_rate: 44100
transcription:
  model: "hft"
"""
    path = tmp_path / "test.yaml"
    path.write_text(yaml_content)
    cfg = Config.from_yaml(str(path))
    assert cfg.audio.sample_rate == 44100
    assert cfg.transcription.model == "hft"

def test_config_validation_errors():
    from config import Config
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Config(audio={"sample_rate": -1})
```

### `test_quantizer.py` (CRITIQUE)

```python
import pytest
from quantizer import Quantizer, QuantizedNote
from tempo_map import TempoMap, TempoChange, Downbeat

class TestQuantizer:
    @pytest.fixture
    def quantizer(self, sample_tempo_map):
        from config import QuantizationConfig
        return Quantizer(QuantizationConfig(), sample_tempo_map)
    
    def test_quantize_simple_onsets(self, quantizer, sample_note_events):
        qnotes = quantizer.quantize(sample_note_events)
        assert len(qnotes) == 3
        # Vérifier alignement grille
        for n in qnotes:
            assert n.beat_position % (1/32) < 1e-6  # Grille 1/32
    
    def test_merge_close_notes_same_pitch(self, quantizer):
        from transcriber import NoteEvent
        events = [
            NoteEvent(0.0, 0.5, 60.0, 100),
            NoteEvent(0.51, 1.0, 60.0, 90),  # Gap < threshold
        ]
        qnotes = quantizer.quantize(events)
        assert len(qnotes) == 1  # Fusionnées
        assert qnotes[0].beat_duration == pytest.approx(1.0, rel=0.1)
    
    def test_staccato_detection(self, quantizer):
        from transcriber import NoteEvent
        # Note courte = staccato
        events = [NoteEvent(0.0, 0.1, 60.0, 100)]  # 0.1s à 120 BPM = 0.2 beats
        qnotes = quantizer.quantize(events)
        assert qnotes[0].staccato == True
    
    def test_legato_detection(self, quantizer):
        from transcriber import NoteEvent
        # Note longue = legato
        events = [NoteEvent(0.0, 1.8, 60.0, 100)]  # 1.8s à 120 BPM = 3.6 beats
        qnotes = quantizer.quantize(events)
        assert qnotes[0].legato == True
    
    def test_tuplet_detection_triplet(self, quantizer):
        from transcriber import NoteEvent
        # Triolet de croches (3 notes dans 1 temps)
        events = [
            NoteEvent(0.0, 0.166, 60.0, 100),
            NoteEvent(0.166, 0.333, 62.0, 100),
            NoteEvent(0.333, 0.5, 64.0, 100),
        ]
        qnotes = quantizer.quantize(events)
        assert all(n.tuplet is not None for n in qnotes)
        assert qnotes[0].tuplet["ratio"] == pytest.approx(1.5)
        assert qnotes[0].tuplet["notes"] == 3

# Property-based tests (Hypothesis)
from hypothesis import given, strategies as st

@given(st.lists(st.floats(0, 10), min_size=2, max_size=20))
def test_quantize_preserves_order(onsets):
    """L'ordre des notes doit être préservé après quantification."""
    from transcriber import NoteEvent
    from quantizer import Quantizer
    from tempo_map import TempoMap, TempoChange
    
    events = [NoteEvent(o, o+0.5, 60.0, 100) for o in sorted(onsets)]
    tm = TempoMap([TempoChange(0.0, 120.0)], [], 120.0)
    q = Quantizer(QuantizationConfig(), tm)
    qnotes = q.quantize(events)
    
    positions = [n.beat_position for n in qnotes]
    assert positions == sorted(positions)
```

### `test_voice_engine.py` (CRITIQUE)

```python
class TestVoiceEngine:
    @pytest.fixture
    def engine(self):
        from voice_engine import VoiceEngine
        from config import VoiceSplitConfig
        return VoiceEngine(VoiceSplitConfig())
    
    def test_split_simple_chord(self, engine):
        from quantizer import QuantizedNote
        notes = [
            QuantizedNote(48, 0.0, 1.0, 'q'),  # Do3 → bass
            QuantizedNote(52, 0.0, 1.0, 'q'),  # Mi3 → bass
            QuantizedNote(55, 0.0, 1.0, 'q'),  # Sol3 → bass
            QuantizedNote(60, 0.0, 1.0, 'q'),  # Do4 → treble
        ]
        result = engine.split(notes)
        assert len(result.bass) == 3
        assert len(result.treble) == 1
        assert result.bass[0].pitch_midi == 48
        assert result.treble[0].pitch_midi == 60
    
    def test_grey_zone_decision(self, engine):
        from quantizer import QuantizedNote
        # Zone grise 55-65 : Sol3 (55) à Fa4 (65)
        notes = [
            QuantizedNote(55, 0.0, 1.0, 'q', amplitude=0.8),  # Sol3 fort → bass
            QuantizedNote(65, 1.0, 1.0, 'q', amplitude=0.5),  # Fa4 faible → treble
        ]
        result = engine.split(notes)
        assert notes[0].hand == 'bass'
        assert notes[1].hand == 'treble'
    
    def test_continuity_smoothing(self, engine):
        from quantizer import QuantizedNote
        # Alternance rapide Do4/Sol3
        notes = [
            QuantizedNote(60, 0.0, 1.0, 'q'),
            QuantizedNote(55, 1.0, 1.0, 'q'),
            QuantizedNote(60, 2.0, 1.0, 'q'),
            QuantizedNote(55, 3.0, 1.0, 'q'),
        ]
        result = engine.split(notes)
        # Après lissage : Do4→treble, Sol3→bass (pas d'oscillation)
        treble_pitches = {n.pitch_midi for n in result.treble}
        bass_pitches = {n.pitch_midi for n in result.bass}
        assert 60 in treble_pitches
        assert 55 in bass_pitches
    
    def test_chord_root_to_bass(self, engine):
        from quantizer import QuantizedNote
        # Accord Do majeur : Do3, Mi3, Sol3, Do4
        notes = [
            QuantizedNote(48, 0.0, 1.0, 'q'),  # Do3
            QuantizedNote(52, 0.0, 1.0, 'q'),  # Mi3
            QuantizedNote(55, 0.0, 1.0, 'q'),  # Sol3
            QuantizedNote(60, 0.0, 1.0, 'q'),  # Do4
        ]
        result = engine.split(notes)
        # Fondamentale (Do3) + notes graves → bass
        bass_pitches = {n.pitch_midi for n in result.bass}
        assert 48 in bass_pitches
        assert 52 in bass_pitches
        assert 55 in bass_pitches
        assert 60 not in bass_pitches  # Do4 → treble
```

### `test_tempo_map.py`

```python
class TestTempoMap:
    def test_sec_beat_conversion(self, sample_tempo_map):
        # 120 BPM = 2 beats/sec
        assert sample_tempo_map.sec_to_beat(1.0) == 2.0
        assert sample_tempo_map.beat_to_sec(2.0) == 1.0
    
    def test_tempo_change(self):
        from tempo_map import TempoMap, TempoChange, Downbeat
        tm = TempoMap(
            tempo_changes=[
                TempoChange(0.0, 120.0),
                TempoChange(8.0, 60.0),  # Changement à la mesure 3
            ],
            downbeats=[
                Downbeat(0.0, 1, 1.0),
                Downbeat(4.0, 2, 1.0),
                Downbeat(8.0, 3, 1.0),
            ],
            initial_bpm=120.0
        )
        # 2 premières mesures à 120 BPM = 4 sec
        # Mesure 3 à 60 BPM = 4 sec
        assert tm.beat_to_sec(8.0) == pytest.approx(8.0)
        assert tm.sec_to_beat(6.0) == pytest.approx(6.0)
    
    def test_measure_numbering(self, sample_tempo_map):
        assert sample_tempo_map.get_measure_at_beat(0.0) == 1
        assert sample_tempo_map.get_measure_at_beat(3.9) == 1
        assert sample_tempo_map.get_measure_at_beat(4.0) == 2
```

### `test_ensemble_voter.py`

```python
class TestEnsembleVoter:
    def test_majority_vote(self):
        from ensemble_voter import EnsembleVoter, EnsembleConfig
        from transcriber import NoteEvent
        
        config = EnsembleConfig(min_votes=2)
        voter = EnsembleVoter(config)
        
        model1 = [NoteEvent(0.0, 1.0, 60.0, 100, 0.9)]
        model2 = [NoteEvent(0.05, 1.0, 60.0, 95, 0.8)]  # Même note, onset décalé
        model3 = [NoteEvent(1.0, 2.0, 62.0, 90, 0.7)]   # Note différente
        
        result = voter.vote([model1, model2, model3])
        assert len(result) == 1
        assert result[0].pitch_midi == 60
        # Onset moyenné pondéré
        assert result[0].onset_sec == pytest.approx(0.02, abs=0.03)
    
    def test_insufficient_votes_discarded(self):
        from ensemble_voter import EnsembleVoter, EnsembleConfig
        from transcriber import NoteEvent
        
        config = EnsembleConfig(min_votes=3)
        voter = EnsembleVoter(config)
        
        model1 = [NoteEvent(0.0, 1.0, 60.0, 100, 0.9)]
        model2 = [NoteEvent(0.0, 1.0, 62.0, 95, 0.8)]  # Pitch différent
        
        result = voter.vote([model1, model2])
        assert len(result) == 0  # Pas assez de votes
```

### `test_hmm_smoother.py`

```python
class TestHMMSmoother:
    def test_smooth_pitch_jumps(self):
        from hmm_smoother import HMMSmoother, HMMConfig
        from transcriber import NoteEvent
        
        config = HMMConfig(transition_weight=0.8, max_jump_semitones=5)
        smoother = HMMSmoother(config)
        
        # Saut brutal Do4 → La4 (9 demi-tons) → devrait être lissé
        events = [
            NoteEvent(0.0, 0.5, 60.0, 100),
            NoteEvent(0.5, 1.0, 69.0, 90),  # Saut 9 demi-tons
            NoteEvent(1.0, 1.5, 60.0, 80),
        ]
        result = smoother.smooth(events)
        # Le saut devrait être réduit
        assert abs(result[1].pitch_midi - 60.0) < 5.0
    
    def test_preserve_legitimate_jumps(self):
        from hmm_smoother import HMMSmoother, HMMConfig
        from transcriber import NoteEvent
        
        config = HMMConfig(transition_weight=0.5, max_jump_semitones=12)
        smoother = HMMSmoother(config)
        
        # Octave jump légitime (Do4 → Do5)
        events = [
            NoteEvent(0.0, 0.5, 60.0, 100),
            NoteEvent(0.5, 1.0, 72.0, 90),
        ]
        result = smoother.smooth(events)
        assert result[1].pitch_midi == pytest.approx(72.0, abs=1.0)
```

### `test_quality_metrics.py`

```python
class TestQualityMetrics:
    def test_perfect_match(self):
        from quality_metrics import QualityMetrics
        from transcriber import NoteEvent
        
        events = [
            NoteEvent(0.0, 1.0, 60.0, 100),
            NoteEvent(1.0, 2.0, 62.0, 90),
        ]
        metrics = QualityMetrics()
        report = metrics.evaluate(events, events)
        
        assert report.onset_f1 == 1.0
        assert report.pitch_accuracy == 1.0
        assert report.overall_score == 1.0
    
    def test_onset_tolerance(self):
        from quality_metrics import QualityMetrics
        from transcriber import NoteEvent
        
        pred = [NoteEvent(0.05, 1.0, 60.0, 100)]  # 50ms décalage
        truth = [NoteEvent(0.0, 1.0, 60.0, 100)]
        
        metrics = QualityMetrics(onset_tolerance_sec=0.05)
        report = metrics.evaluate(pred, truth)
        assert report.onset_f1 == 1.0  # Dans la tolérance
        
        metrics = QualityMetrics(onset_tolerance_sec=0.01)
        report = metrics.evaluate(pred, truth)
        assert report.onset_f1 == 0.0  # Hors tolérance
```

### `test_ornament_detector.py`

```python
class TestOrnamentDetector:
    def test_detect_trill(self):
        from ornament_detector import OrnamentDetector
        from transcriber import NoteEvent
        
        detector = OrnamentDetector()
        # Trille Do4-Ré4 rapide
        events = [
            NoteEvent(0.0, 0.1, 60.0, 100),
            NoteEvent(0.1, 0.2, 62.0, 90),
            NoteEvent(0.2, 0.3, 60.0, 80),
            NoteEvent(0.3, 0.4, 62.0, 85),
            NoteEvent(0.4, 0.5, 60.0, 95),
        ]
        ornaments = detector.detect(events)
        assert len(ornaments) == 1
        assert ornaments[0].type == "trill"
        assert ornaments[0].main_note_idx == 0
    
    def test_detect_mordent(self):
        from ornament_detector import OrnamentDetector
        from transcriber import NoteEvent
        
        detector = OrnamentDetector()
        # Mordant : Do4 → Si3 → Do4
        events = [
            NoteEvent(0.0, 0.15, 60.0, 100),
            NoteEvent(0.15, 0.25, 59.0, 80),
            NoteEvent(0.25, 0.4, 60.0, 90),
        ]
        ornaments = detector.detect(events)
        assert len(ornaments) == 1
        assert ornaments[0].type == "mordent"
```

---

## Tests d'intégration

### `test_pipeline_audio.py`

```python
@pytest.mark.integration
class TestPipelineAudio:
    async def test_full_pipeline_wav(self, simple_audio):
        from pipeline import Pipeline
        from config import Config
        
        config = Config()
        config.pipeline.save_intermediate = True
        config.pipeline.checkpoint_dir = "./test_checkpoints"
        
        pipeline = Pipeline(config)
        result = await pipeline.run(simple_audio)
        
        assert result.score is not None
        assert result.midi_path is not None
        assert result.musicxml_path is not None
        assert len(result.checkpoints) == 7  # 7 stages
        
        # Vérifier structure score
        assert len(result.score.measures) > 0
        assert result.score.metadata["total_notes"] > 0
    
    async def test_pipeline_resume_from_checkpoint(self, simple_audio, tmp_path):
        from pipeline import Pipeline
        from config import Config
        
        config = Config()
        config.pipeline.save_intermediate = True
        config.pipeline.checkpoint_dir = str(tmp_path / "checkpoints")
        
        # Run 1 : complet
        pipeline1 = Pipeline(config)
        result1 = await pipeline1.run(simple_audio)
        
        # Run 2 : reprise depuis quantization
        config.pipeline.resume_from_checkpoint = True
        pipeline2 = Pipeline(config)
        result2 = await pipeline2.run(simple_audio)
        
        assert result2.score.measures == result1.score.measures
```

### `test_checkpoint_resume.py`

```python
@pytest.mark.integration
def test_checkpoint_serialization(tmp_path):
    from pipeline import Pipeline, Checkpoint
    from config import Config
    import json
    
    config = Config()
    config.pipeline.checkpoint_dir = str(tmp_path)
    config.pipeline.save_intermediate = True
    
    pipeline = Pipeline(config)
    # Mock: injecter des données de test
    test_data = [{"pitch_midi": 60, "beat_position": 1.0}]
    pipeline._save_checkpoint("test_stage", test_data)
    
    # Vérifier fichier créé
    checkpoint_files = list(tmp_path.glob("*.json"))
    assert len(checkpoint_files) == 1
    
    with open(checkpoint_files[0]) as f:
        data = json.load(f)
    assert data["stage"] == "test_stage"
    assert data["data"] == test_data
```

---

## Tests E2E

### `test_full_pipeline.py`

```python
@pytest.mark.e2e
async def test_audio_to_pdf(tmp_path, simple_audio):
    """Test complet : audio → partition PDF."""
    from pipeline import Pipeline
    from config import Config
    
    config = Config()
    config.export.lilypond_pdf = True
    config.pipeline.checkpoint_dir = str(tmp_path / "checkpoints")
    
    pipeline = Pipeline(config)
    result = await pipeline.run(simple_audio)
    
    assert result.pdf_path is not None
    assert Path(result.pdf_path).exists()
    assert Path(result.pdf_path).stat().st_size > 1000  # PDF non vide
```

---

## Tests Frontend (Playwright)

```javascript
// tests/e2e/frontend_rendering.spec.js
const { test, expect } = require('@playwright/test');

test('render score from JSON', async ({ page }) => {
  await page.goto('http://localhost:8080');
  
  // Charger un fichier de test
  await page.setInputFiles('#audio-input', 'tests/fixtures/audio/simple_c_major.wav');
  
  // Attendre transcription
  await page.waitForSelector('#score-container svg', { timeout: 30000 });
  
  // Vérifier rendu
  const svg = await page.locator('#score-container svg');
  await expect(svg).toBeVisible();
  
  // Vérifier éléments musicaux
  const notes = await page.locator('.vf-stavenote').count();
  expect(notes).toBeGreaterThan(0);
});

test('practice mode loop A-B', async ({ page }) => {
  await page.goto('http://localhost:8080');
  await page.setInputFiles('#audio-input', 'tests/fixtures/audio/simple_c_major.wav');
  await page.waitForSelector('#score-container svg');
  
  // Activer mode pratique
  await page.click('#practice-mode-btn');
  
  // Définir boucle A-B
  await page.click('#set-loop-start');
  await page.click('#set-loop-end');
  await page.click('#start-loop');
  
  // Vérifier lecture en boucle
  await expect(page.locator('#loop-indicator')).toBeVisible();
});
```

---

## CI/CD (GitHub Actions)

### `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install ruff mypy
      - run: ruff check backend/
      - run: mypy backend/

  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r backend/requirements.txt pytest pytest-asyncio hypothesis
      - run: pytest tests/unit -v --cov=backend --cov-report=xml
      - uses: codecov/codecov-action@v3

  integration-tests:
    runs-on: ubuntu-latest
    needs: unit-tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r backend/requirements.txt
      - run: pytest tests/integration -v --timeout=120

  e2e-tests:
    runs-on: ubuntu-latest
    needs: integration-tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build
      - uses: microsoft/playwright-github-action@v1
      - run: pytest tests/e2e -v --timeout=180

  property-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install hypothesis
      - run: pytest tests/property -v

  build-docker:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: audioscore:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## Couverture cible par module

| Module | Couverture cible | Priorité |
|--------|------------------|----------|
| `quantizer.py` | 90% | 🔴 Critique |
| `voice_engine.py` | 90% | 🔴 Critique |
| `tempo_map.py` | 85% | 🔴 Critique |
| `score_builder.py` | 85% | 🔴 Critique |
| `ensemble_voter.py` | 80% | 🟡 Important |
| `hmm_smoother.py` | 80% | 🟡 Important |
| `transcriber.py` | 70% | 🟡 Important |
| `midi_parser.py` | 70% | 🟡 Important |
| `quality_metrics.py` | 80% | 🟡 Important |
| `ornament_detector.py` | 75% | 🟢 Standard |
| `hand_split_ml.py` | 70% | 🟢 Standard |
| `exporters` | 75% | 🟢 Standard |
| `pipeline.py` | 70% | 🟢 Standard |

---

## Données de test (Fixtures)

### Génération ground truth

```python
# scripts/generate_ground_truth.py
"""Génère des fichiers ground truth depuis MIDI de référence."""
import json
from midi_parser import MidiParser
from tempo_map import TempoMapBuilder
from config import Config

def generate_ground_truth(midi_path: str, output_path: str):
    parser = MidiParser()
    events = parser.parse(midi_path)
    
    config = Config()
    tempo_builder = TempoMapBuilder(config.tempo)
    tempo_map = tempo_builder.build_from_midi(midi_path)
    
    # Quantifier avec config de référence
    from quantizer import Quantizer, QuantizationConfig
    quantizer = Quantizer(QuantizationConfig(), tempo_map)
    qnotes = quantizer.quantize(events)
    
    # Séparer voix
    from voice_engine import VoiceEngine, VoiceSplitConfig
    voice_engine = VoiceEngine(VoiceSplitConfig())
    voices = voice_engine.split(qnotes)
    
    # Sérialiser
    ground_truth = {
        "events": [e.__dict__ for e in events],
        "tempo_map": tempo_map.__dict__,
        "quantized_notes": [n.__dict__ for n in qnotes],
        "voice_split": {
            "treble": [n.__dict__ for n in voices.treble],
            "bass": [n.__dict__ for n in voices.bass]
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump(ground_truth, f, indent=2)
```

---

## Commandes utiles

```bash
# Tests unitaires seulement
pytest tests/unit -v

# Tests avec couverture
pytest tests/unit --cov=backend --cov-report=html

# Tests d'intégration
pytest tests/integration -v --timeout=120

# Tests E2E (nécessite serveur frontend)
pytest tests/e2e -v --timeout=180

# Property-based tests
pytest tests/property -v

# Tous les tests
pytest --cov=backend --cov-report=term-missing

# Linting
ruff check backend/
mypy backend/

# Générer fixtures ground truth
python scripts/generate_ground_truth.py fixtures/midi/simple.mid fixtures/ground_truth/simple.json
```

---

## Références

- `ARCHITECTURE.md` — Architecture globale
- `API_CONTRACTS.md` — Contrats d'API
- `DATA_FORMATS.md` — Formats de données
- `MIGRATION_V3_V4.md` — Migration