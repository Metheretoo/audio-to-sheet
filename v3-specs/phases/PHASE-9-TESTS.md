# Phase 9 — Tests et Validation

## Objectif
Assurer la qualité et la fiabilité de chaque module via des tests unitaires et d'intégration.

## Structure des tests

```
tests/
├── __init__.py
├── test_midi_parser.py      # Tests du parser MIDI
├── test_quantizer.py         # Tests du quantizer
├── test_tempo_map.py         # Tests de la détection tempo
├── test_tonality.py          # Tests de détection tonalité
├── test_score_builder.py     # Tests du builder de partition
├── test_transcriber.py       # Tests du pipeline complet
├── test_app.py               # Tests de l'API Flask
└── test_midi_exporter.py     # Tests de l'export MIDI
```

## Tests par module

### 1. midi_parser.py

| Test | Description | Attendu |
|------|-------------|---------|
| `test_parse_midi_0` | Fichier MIDI Type 0 | Parse réussi, notes détectées |
| `test_parse_midi_1` | Fichier MIDI Type 1 | Parse réussi, pistes séparées |
| `test_parse_midi_invalid` | Fichier invalide | Exception raisee |
| `test_parse_empty` | Fichier vide | Exception raisee |
| `test_parse_header` | Lecture du header | Nombre de pistes correct |
| `test_parse_tempo_map` | Lecture du tempo map | BPM cohérents |
| `test_parse_notes` | Lecture des notes | Pitch, start, duration corrects |

### 2. quantizer.py

| Test | Description | Attendu |
|------|-------------|---------|
| `test_quantize_simple` | Notes sur les beats | Alignement parfait |
| `test_quantize_offbeat` | Notes entre les beats | Assignement au beat le plus proche |
| `test_quantize_preserve_durations` | Durées musicales | Puissances de 2 conservées |
| `test_quantize_grid` | Grille 1/4, 1/8, 1/16 | Coverage > 95% |
| `test_quantize_context` | Contexte musical | Durées naturelles |

### 3. tempo_map.py

| Test | Description | Attendu |
|------|-------------|---------|
| `test_compute_onsets` | Détection des onsets | Nombre cohérent |
| `test_cluster_bpm` | Clustering BPM | Clusters valides |
| `test_compute_tempo_map` | Tempo map complet | BPM cohérents |
| `test_detect_bpm_range` | BPM dans range | 40-300 BPM |
| `test_detect_tempo_changes` | Changements de tempo | Détection correcte |

### 4. tonality_detector.py

| Test | Description | Attendu |
|------|-------------|---------|
| `test_detect_major` | Piece en Do majeur | Key=C, Mode=major |
| `test_detect_minor` | Piece en La mineur | Key=A, Mode=minor |
| `test_krumhansl_schmuckler` | Algorithme KS | Corrélation > 0.7 |
| `test_parncutt` | Règles Parncutt | Score cohérent |

### 5. score_builder.py

| Test | Description | Attendu |
|------|-------------|---------|
| `test_build_stave` | Construction d'une mesure | Mesure valide |
| `test_build_two_staves` | 2 clefs (RH/LH) | Partition correcte |
| `test_add_key_signature` | Armature ajoutée | Clé affichée |
| `test_add_time_signature` | Mesure ajoutée | Temps affiché |
| `test_export_musicxml` | Export MusicXML | Fichier valide |

### 6. transcriber.py (Pipeline complet)

| Test | Description | Attendu |
|------|-------------|---------|
| `test_pipeline_full` | Audio → MIDI → Score | Pipeline réussi |
| `test_pipeline_error` | Fichier invalide | Erreur gérée |
| `test_pipeline_timing` | Performance | < 30s pour 3min |

### 7. app.py (API Flask)

| Test | Description | Attendu |
|------|-------------|---------|
| `test_health` | GET /health | 200 OK |
| `test_upload_valid` | POST /upload (wav) | 200, transcription |
| `test_upload_mp3` | POST /upload (mp3) | 200, transcription |
| `test_upload_too_large` | POST /upload (60MB) | 413 |
| `test_upload_invalid` | POST /upload (txt) | 400 |
| `test_status_completed` | GET /status/<id> | Status "completed" |
| `test_midi_download` | GET /midi/<id> | Fichier MIDI |
| `test_score_download` | GET /score/<id> | Fichier XML |
| `test_not_found` | GET /midi/<invalid> | 404 |

## Fichier de tests `__init__.py`

```python
"""Tests pour audio-to-sheet v3."""
```

## Lancement des tests

```bash
# Tous les tests
python -m pytest tests/ -v

# Par module
python -m pytest tests/test_midi_parser.py -v
python -m pytest tests/test_quantizer.py -v

# Avec couverture
python -m pytest tests/ -v --cov=backend --cov-report=html

# Test du pipeline complet
python backend/_validate_pipeline.py
```

## Critères d'acceptation
- [x] 100% des tests passent
- [x] Couverture > 80% par module
- [x] Pipeline complet testé avec 5+ fichiers audio variés
- [x] Tests exécutables sans configuration spéciale

## Fichier de validation rapide

`backend/_validate_pipeline.py` doit:
1. Charger un fichier audio de test
2. Exécuter le pipeline complet
3. Vérifier les sorties (MIDI, XML, JSON)
4. Afficher un résumé
5. Retourner 0 si tout est vert