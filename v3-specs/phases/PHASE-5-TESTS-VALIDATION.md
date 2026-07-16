# Phase 5 — Tests & Validation

> **Statut** : À implémenter
> **Dépendances** : Phase 1 ✅, Phase 2 ✅, Phase 3 ✅, Phase 4 (à créer)
> **Gain attendu** : Suite de tests complète couvrant tout le pipeline

---

## Objectif

Créer une suite de tests complète pour valider le bon fonctionnement de chaque module individuellement et du pipeline intégré dans son ensemble.

---

## Contexte

Le pipeline audio→sheet music est complexe (4 phases). Chaque phase doit être testée individuellement (tests unitaires) et l'ensemble du pipeline doit être testé de bout en bout (tests intégrés).

---

## Structure des Tests

```
backend/tests/
├── __init__.py
├── conftest.py              # Fixtures partagées
├── test_voice_engine.py     # Phase 1
├── test_transcriber.py      # Phase 2
├── test_quantizer.py        # Phase 3
├── test_midi_exporter.py    # Phase 4
├── test_integration.py      # Pipeline complet
├── test_data/
│   ├── sample.wav           # Test audio basique
│   ├── simple_tune.mid      # Test MIDI simple
│   └── readme.txt           # Description des fichiers de test
└── README.md                # Comment exécuter les tests
```

---

## Tests Unitaires par Phase

### Phase 1 — Voice Engine

```python
# test_voice_engine.py

def test_detect_voices_mono():
    """Détection de voix sur audio mono (melody seule)"""
    engine = VoiceEngine()
    result = engine.detect_voices("test_mono.wav")
    assert len(result['voices']) == 1
    assert result['dominant_voice'] == 'melody'

def test_detect_voices_stereo():
    """Détection de voix sur audio stéréo"""
    engine = VoiceEngine()
    result = engine.detect_voices("test_stereo.wav")
    assert len(result['voices']) >= 1

def test_extract_melody():
    """Extraction de mélodie"""
    engine = VoiceEngine()
    result = engine.extract_melody(...)
    assert len(result['notes']) > 0
    for note in result['notes']:
        assert 0 <= note['frequency'] <= 5000
```

### Phase 2 — MIDI Transcriber

```python
# test_transcriber.py

def test_f0_to_midi_notes():
    """Conversion F0 en notes MIDI"""
    transcriber = MIDITranscriber()
    f0_data = {'frequencies': [...], 'times': [...]}
    notes = transcriber.f0_to_notes(f0_data)
    assert len(notes) > 0
    for note in notes:
        assert 21 <= note['midi_number'] <= 108

def test_midi_to_chords():
    """Conversion en accords"""
    transcriber = MIDITranscriber()
    chords = transcriber.detect_chords(notes)
    assert len(chords) > 0

def test_bpm_clustering():
    """Regroupement BPM"""
    transcriber = MIDITranscriber()
    bpm_points = [(0, 120), (30, 125), (60, 118)]
    clusters = transcriber.cluster_bpm(bpm_points, threshold=10)
    assert len(clusters) >= 1
```

### Phase 3 — Quantizer

```python
# test_quantizer.py

def test_quantize_beats():
    """Quantification des beats"""
    quantizer = Quantizer()
    quantizer.set_tempo_map([(0, 120)])
    notes = [{'start_time': 0.0, 'end_time': 0.5, 'midi_number': 60}]
    result = quantizer.quantize_notes(notes)
    assert len(result) == 1
    assert result[0]['start_tick'] % 480 == 0  # Sur le temps

def test_quantize_tempo_change():
    """Quantification avec changement de tempo"""
    quantizer = Quantizer()
    quantizer.set_tempo_map([(0, 100), (30, 140)])
    notes = [...]  # notes couvrant les deux tempos
    result = quantizer.quantize_notes(notes)
    # Vérifier que les ticks reflètent les deux tempos
```

### Phase 4 — MIDI Exporter

```python
# test_midi_exporter.py

def test_export_basic():
    """Export MIDI basique"""
    exporter = MIDIExporter([(0, 120)], 'C')
    notes = [{'note_number': 60, 'start_time': 0, 'end_time': 1, 'velocity': 64}]
    output = exporter.export(notes, 'test_output.mid')
    assert os.path.exists(output)
    assert os.path.getsize(output) > 0

def test_validate_midi():
    """Validation du fichier MIDI avec mido"""
    exporter = MIDIExporter([(0, 120)], 'C')
    notes = [...]
    output = exporter.export(notes, 'test_validate.mid')
    
    import mido
    mid = mido.MidiFile(output)
    assert mid.type in (0, 1)
```

---

## Tests d'Intégration

```python
# test_integration.py

def test_full_pipeline_mono():
    """Pipeline complet sur audio mono"""
    result = run_full_pipeline("test_data/sample_mono.wav")
    assert result['midi_path'] is not None
    assert os.path.exists(result['midi_path'])
    assert result['analysis'] is not None

def test_full_pipeline_stereo():
    """Pipeline complet sur audio stéréo"""
    result = run_full_pipeline("test_data/sample_stereo.wav")
    assert result['midi_path'] is not None

def test_api_endpoints():
    """Test des endpoints API"""
    client = TestClient(app)
    
    # Test upload + transcription
    with open('test_data/sample.wav', 'rb') as f:
        response = client.post(
            '/transcribe',
            files={'file': ('test.wav', f, 'audio/wav')}
        )
    assert response.status_code == 200
    assert response.headers['content-type'] == 'audio/midi'
```

---

## Configuration pytest

```ini
# backend/pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    unit: Tests unitaires
    integration: Tests d'intégration
    slow: Tests longs
```

```json
// backend/pyproject.toml (ou setup.cfg)
{
  "dev-dependencies": [
    "pytest>=7.0",
    "pytest-cov>=3.0",
    "pytest-asyncio>=0.18",
    "mido>=1.2.0",      # Pour validation MIDI
    "test-align>=0.3.0"  # Pour validation timing
  ]
}
```

---

## Commandes de Test

```bash
# Tous les tests
cd backend
pytest

# Tests unitaires seulement
pytest -m unit

# Tests d'intégration
pytest -m integration

# Avec couverture
pytest --cov=voice_engine --cov=midi_transcriber --cov=quantizer --cov=midi_exporter --cov-report=html

# Rapport de couverture
start htmlcov/index.html
```

---

## Règles

1. **Code en français** : commentaires et docstrings en français
2. **Fichiers de test** : tous les fichiers audio/MIDI de test doivent être légers (< 1 Mo si possible)
3. **Fixtures** : utiliser des fixtures pytest pour les objets partagés
4. **Async** : utiliser `pytest-asyncio` pour les tests async
5. **CI-ready** : les tests doivent pouvoir tourner sur GitHub Actions

---

## Ordre d'Implémentation

1. Créer `backend/tests/` structure
2. Créer fichiers de test (`test_data/`)
3. Implémenter `test_voice_engine.py`
4. Implémenter `test_transcriber.py`
5. Implémenter `test_quantizer.py`
6. Implémenter `test_midi_exporter.py`
7. Implémenter `test_integration.py`
8. Créer `pytest.ini`
9. Exécuter `pytest --cov` et vérifier ≥ 80% couverture

---

**Dernière mise à jour** : 4 juillet 2026