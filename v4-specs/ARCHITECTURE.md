# Architecture V4 — audio-to-sheet

> **Lire en premier : `TRANSCRIPTION_QUALITY.md`**
> Ce document décrit COMMENT le pipeline est organisé.
> Mais la qualité de la partition dépend avant tout des choix décrits dans
> `TRANSCRIPTION_QUALITY.md` (modèle, beat tracking, quantification locale).
> Ne pas passer à l'implémentation de ce document sans avoir lu celui-là.

## Vue d'ensemble

Pipeline modulaire **audio → partition** avec séparation stricte des responsabilités,
contrats formels entre modules, et tests automatisés.

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Transcriber│──▶│  TempoMap   │──▶│  Quantizer  │──▶│ VoiceEngine │──▶│ScoreBuilder │──▶│  Exporters  │
│  (onsets,   │   │  (beats,    │   │  (grid,     │   │  (LH/RH     │   │  (measures, │   │  MIDI       │
│   pitches)  │   │   meter)    │   │   merge,    │   │   split)    │   │   dynamics)│   │  MusicXML   │
└─────────────┘   └─────────────┘   │  tuplets)   │   └─────────────┘   └─────────────┘   │  LilyPond   │
                                    └─────────────┘                                         └─────────────┘
```

---

## Modules Backend (`backend/`)

| Module | Responsabilité | Entrée | Sortie |
|--------|----------------|--------|--------|
| `config.py` | Chargement/validation `config.yaml` (Pydantic) | `config.yaml` | `Config` object |
| `transcriber.py` | Détection onsets + pitch (BasicPitch/ONNX) | `audio_path` | `List[NoteEvent]` |
| `midi_parser.py` | Parsing MIDI → NoteEvent | `midi_path` | `List[NoteEvent]` |
| `tempo_map.py` | Détection tempo/mètre (madmom/librosa/fallback) | `audio_path`, `NoteEvent[]` | `TempoMap` |
| `quantizer.py` | Alignement grille, fusion, staccato/legato, tuplets | `NoteEvent[]`, `TempoMap` | `QuantizedNote[]` |
| `voice_engine.py` | Séparation mains (registre, contour, harmonie, continuité) | `QuantizedNote[]` | `VoiceSplit` |
| `score_builder.py` | Construction mesures, détection dynamique, pédale, doigtés | `VoiceSplit`, `TempoMap` | `ScoreData` |
| `midi_exporter.py` | Export MIDI Type 1 + tempo changes + LilyPond PDF | `ScoreData`, `QuantizedNote[]` | `.mid`, `.pdf` |
| `musicxml_exporter.py` | Export MusicXML 4.0 (dynamiques, articulations, pédale) | `ScoreData` | `.musicxml` |
| `ensemble_voter.py` | Vote d'ensemble multi-modèles (BasicPitch, HFT, etc.) | `List[NoteEvent[]]` | `NoteEvent[]` |
| `hmm_smoother.py` | Post-traitement Viterbi (lissage pitch/onset) | `NoteEvent[]` | `NoteEvent[]` |
| `pipeline.py` | Orchestration async + checkpointing JSON par stage | `audio_path`, `Config` | `PipelineResult` |
| `model_cache.py` | Cache modèles ONNX (vérification hash, téléchargement) | — | `ModelCache` |
| `note_filter.py` | Filtres post-transcription (notes fantômes, durées irréalistes, pedal-aware) | `NoteEvent[]` | `NoteEvent[]` |
| `piano_roll.py` | **[NOUVEAU]** Regroupement des notes en accords/slices | `QuantizedNote[]` | `Slice[]` |
| `harmonic_analyzer.py` | **[NOUVEAU]** Analyse music21 (tonalité, chiffrage accords) | `Slice[]` | `HarmonicContext` |
| `quality_metrics.py` | Métriques qualité (F1 onset, pitch accuracy, etc.) | `NoteEvent[]`, `ground_truth` | `QualityReport` |
| `ornament_detector.py` | Détection ornementations (trilles, mordants, appogiatures) | `NoteEvent[]` | `Ornament[]` |
| `hand_split_ml.py` | Séparation mains par ML (optionnel, complément voice_engine) | `QuantizedNote[]` | `VoiceSplit` |

---

## Modules Frontend (`frontend/js/`)

| Module | Responsabilité |
|--------|----------------|
| `app.js` | Point d'entrée, routing, état global |
| `editor/` | Édition partition (sélection multi, copy/paste, annotations, undo/redo) |
| `renderer/` | Rendu VexFlow (beams intelligents, silences centrés, accords, altérations) |
| `player/` | Lecture audio sync (curseur, métronome, tempo progressif, boucle A-B) |
| `exporter/` | Téléchargement MIDI/MusicXML/PDF, impression |
| `i18n.js` | Internationalisation (fr/en/es/de) |
| `pwa.js` | Service worker, cache offline, install prompt |

---

## Flux de données principal

```python
# pipeline.py (V4 — ordre prioritaire selon TRANSCRIPTION_QUALITY.md)
async def run_pipeline(audio_path: str, config: Config) -> PipelineResult:
    # 1. Transcription (Piano Transcription Kong en V4, BasicPitch en fallback)
    events = await transcriber.transcribe(audio_path, config)
    
    # 2. Filtrage post-transcription (NOUVEAU — notes fantômes, durées, pédale)
    events = note_filter.filter_ghost_notes(events)
    events = note_filter.filter_unrealistic_durations(events)
    pedal_events = transcriber.get_pedal_events()  # depuis Piano Transcription
    events = note_filter.apply_pedal_aware_shortening(events, pedal_events)
    
    # 3. Tempo map (madmom beat tracking — OBLIGATOIRE pour time sig correcte)
    tempo_map = tempo_map_builder.build(audio_path, events, config)
    
    # 4. Ensemble voting (optionnel, si config.use_ensemble)
    if config.transcription.use_ensemble:
        events = ensemble_voter.vote([events, hft_events, ...])
    
    # 5. Quantification sur grille LOCALE (beat_times[], pas BPM global)
    qnotes = quantizer.quantize(events, tempo_map, config)
    
    # 6. Compréhension Harmonique (NOUVEAU - music21)
    slices = piano_roll.group_into_slices(qnotes)
    harmonic_context = harmonic_analyzer.analyze(slices)
    
    # 7. Séparation voix guidée par l'harmonie (Dijkstra amélioré)
    voices = voice_engine.split_with_harmony(qnotes, harmonic_context, config)
    
    # 8. Construction partition (nuances, pédale, doigtés)
    score = score_builder.build(voices, tempo_map, config)
    
    # 9. Exports
    midi_path      = midi_exporter.export(score, qnotes, config)
    musicxml_path  = musicxml_exporter.export(score, config)
    pdf_path       = midi_exporter.export_lilypond_pdf(score, config) if config.export_pdf else None
    
    return PipelineResult(score, midi_path, musicxml_path, pdf_path, checkpoints)
```

---

## Configuration centralisée (`config.yaml`)

```yaml
audio:
  sample_rate: 22050
  onset_threshold: 0.3
  min_note_duration: 0.05

transcription:
  model: "basicpitch"          # basicpitch | hft | ensemble
  use_ensemble: false
  ensemble_models: ["basicpitch", "hft"]
  use_hmm_smoothing: true
  hmm_transition_weight: 0.7

tempo:
  method: "auto"               # madmom | librosa | fallback | manual
  manual_bpm: null
  downbeat_detection: true

quantization:
  grid_resolution: 32          # 1/32 note
  merge_threshold_ticks: 2
  staccato_threshold_ratio: 0.3
  legato_threshold_ratio: 0.85
  tuplet_detection: true
  max_tuplet_ratio: 6

voice_split:
  split_point_midi: 60         # Middle C
  use_smoothing: true
  use_ml_fallback: false

score:
  detect_dynamics: true
  detect_pedal: true
  suggest_fingerings: false
  key_detection: "krumhansl"   # krumhansl | temperley | manual
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

## Points d'extension (Plugin hooks)

```python
# pipeline.py — hooks pour extensions
class PipelineHooks:
    def on_transcription_complete(self, events: List[NoteEvent]) -> List[NoteEvent]: ...
    def on_tempo_map_built(self, tm: TempoMap) -> TempoMap: ...
    def on_quantization_complete(self, qnotes: List[QuantizedNote]) -> List[QuantizedNote]: ...
    def on_voice_split_complete(self, vs: VoiceSplit) -> VoiceSplit: ...
    def on_score_built(self, score: ScoreData) -> ScoreData: ...
    def on_export_complete(self, paths: Dict[str, str]) -> Dict[str, str]: ...
```

---

## Intégration TODO2 / TODO3

| Sujet TODO | Module concerné | Statut dans specs |
|------------|-----------------|-------------------|
| Ensemble voting | `ensemble_voter.py` | ✅ Défini |
| Viterbi smoothing | `hmm_smoother.py` | ✅ Défini |
| Pedal detection | `score_builder.py` | ✅ Config + implémentation |
| Checkpointing | `pipeline.py` | ✅ Config + implémentation |
| Quality metrics | `quality_metrics.py` | ✅ Défini |
| Ornament detection | `ornament_detector.py` | ✅ Défini |
| ML hand split | `hand_split_ml.py` | ✅ Défini (optionnel) |
| Practice mode | `frontend/js/player/` | ✅ Architecture |
| PWA + i18n | `frontend/js/pwa.js`, `i18n.js` | ✅ Architecture |
| ONNX INT8 quantization | `tools/quantize_onnx.py` | ⚠️ À ajouter dans CI/CD |
| Dockerfile multi-stage | `Dockerfile` | ⚠️ À ajouter dans CI/CD |
| VexFlow beams/rests/chords | `frontend/js/renderer/` | ✅ Architecture |
| Dynamics/pedal/fingerings | `score_builder.py` | ✅ Config + implémentation |
| MusicXML 4.0 complet | `musicxml_exporter.py` | ✅ Défini |
| PDF haute qualité | `midi_exporter.export_lilypond_pdf` | ✅ Défini |
| Editor multi-select/copy/paste/annotations | `frontend/js/editor/` | ✅ Architecture |
| GPU/WebGL detection | `frontend/js/renderer/`, `pwa.js` | ✅ Architecture |

---

## Références

- `TRANSCRIPTION_QUALITY.md` — **À lire en premier** : choix modèles, beat tracking, priorités
- `HARMONIC_ANALYSIS.md` — Intégration de `music21` et du Piano Roll pour le Voice Split
- `API_CONTRACTS.md` — Signatures, types, contrats HTTP
- `DATA_FORMATS.md` — Structures de données détaillées
- `TEST_STRATEGY.md` — Stratégie de tests, CI/CD
- `MIGRATION_V3_V4.md` — Guide migration
- `ROADMAP_IDEAS.md` — Idées V4.2+ et V5