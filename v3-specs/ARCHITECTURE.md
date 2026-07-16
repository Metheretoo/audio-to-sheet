# Architecture — Audio-to-Sheet Music V3

> **État** : À jour (mis à jour pour refléter les 4 phases)

---

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                    Audio-to-Sheet Music V3                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Phase 1    │    │   Phase 2    │    │   Phase 3    │  │
│  │  Voice Engine│───▶│  Tempo Map   │───▶│  Quantizer   │  │
│  │              │    │              │    │              │  │
│  │ • Upload     │    │ • Onset      │    │ • Normalize  │  │
│  │ • Analyze    │    │ • Cluster    │    │ • Detect     │  │
│  │ • Transcribe │    │ • Map BPM    │    │   notes      │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │          │
│         ▼                   ▼                   ▼          │
│      ┌─────────────────────────────────────────────┐       │
│     │              Phase 4                         │       │
│     │           MIDI Exporter                      │       │
│     │                                              │       │
│     │  • Convert notes → MIDI events               │       │
│     │  • Add tempo/key signatures                  │       │
│     │  • Export .mid file                          │       │
│     └──────────────────────────────────────────────┘       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                     Sorties                                   │
│                                                             │
│  • MIDI file (.mid)              ✓  Standard MIDI          │
│  • JSON score (debug)            ✓  Notes + timing         │
│  • HTML preview (frontend)       ✓  Web Audio API          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Structure du Projet

```
audio-to-sheet/
├── backend/
│   ├── app.py                        # FastAPI server (orchestrateur)
│   ├── voice_engine.py              # Phase 1 — Voice Engine V3
│   ├── tempo_map.py                 # Phase 2 — Tempo Map V3
│   ├── quantizer.py                 # Phase 3 — Quantizer V3
│   ├── midi_exporter.py             # Phase 4 — MIDI Exporter (à créer)
│   └── requirements.txt             # Dépendances Python
│
├── frontend/
│   ├── index.html                   # Interface utilisateur
│   ├── js/
│   │   ├── app.js                   # Logique principale
│   │   ├── player.js                # Lecteur audio
│   │   └── score-viewer.js          # Visualiseur de partition
│   └── css/
│       └── style.css                # Styles
│
├── v3-specs/
│   ├── README.md                     # Guide principal
│   ├── ARCHITECTURE.md               # Ce fichier
│   ├── PROGRESS.md                   # Suivi d'avancement
│   ├── phases/
│   │   ├── PHASE-1-VOICE-ENGINE.md
│   │   ├── PHASE-2-TEMPO-MAP.md
│   │   ├── PHASE-3-QUANTIZER.md
│   │   ├── PHASE-4-MIDI-EXPORT.md
│   │   ├── tonality_detector.py      # Implémentation
│   │   ├── quantizer.py              # Implémentation
│   │   └── midi_exporter.py          # Implémentation
│   └── references/
│       ├── FAISABILITE.md
│       ├── DEPENDENCIES.md
│       └── tonality-detection.md     # (à créer)
│
├── uploads/                          # Fichiers temporaires
├── outputs/                          # Fichiers générés
└── TODO.txt                          # TODO list
```

---

## Dépendances entre Phases

```
Phase 1 (Voice Engine)
    └── Phase 2 (Tempo Map)
            └── Phase 3 (Quantizer)
                    └── Phase 4 (MIDI Export)
```

**Chaque phase dépend du bon fonctionnement de la précédente.**

---

## Points d'Intégration API

### Endpoint Principal

```
POST /transcribe
Content-Type: multipart/form-data
  file: audio_file (FLAC, MP3, WAV, M4A)

Response:
  - MIDI file (application/midi)
  - OR JSON { error: "..." }
```

### Pipeline Interne

```
upload → VoiceEngine.analyze() → AudioSegment
       → TempoMapV3.compute()  → BPM clusters
       → QuantizerV3.quantize()→ List[Note]
       → MIDIExporter.export() → .mid file
```

---

## Changements V2 → V3

| Aspect | V2 | V3 |
|--------|----|----|
| Détection tempo | Heuristics simples | Clustering DBSCAN |
| Quantization | Threshold fixe | Algorithme adaptatif |
| Tonalité | Non implémenté | Krumhansl-Schum + Parncutt |
| MIDI | Basique | Type 0/1, signatures |
| Architecture | Monolithique | Modulaire (4 phases) |

---

## Dépendances Finales

```
# backend/requirements.txt
numpy>=1.24.0
librosa>=0.10.0
mir_eval>=0.7
flask-cors>=4.0
python-multipart>=0.0.6
scikit-learn>=1.2.0
midiutil>=1.2.1
soundfile>=0.12.0
```

---

**Dernière mise à jour** : 4 juillet 2026