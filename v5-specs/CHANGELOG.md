# V5 — Changelog

> **Règle :** toute modification de code est tracée ici AVANT ou IMMÉDIATEMENT APRÈS sa mise en place.
> Format : `DATE | PHASE | FICHIER | ACTION | MOTIF | IMPACT`.

---

## Légende Actions

| Action | Signification |
|--------|---------------|
| `CREATE` | Création d'un nouveau fichier |
| `MODIFY` | Modification d'un fichier existant |
| `DELETE` | Suppression d'un fichier |
| `ARCHIVE` | Déplacement vers `legacy/` |
| `RENAME` | Renommage |

---

## 2026-07-17

| Heure | Phase | Fichier | Action | Motif | Impact |
|-------|-------|---------|--------|-------|--------|
| 12:10 | — | `v5-specs/PHASE-TRACKER.md` | CREATE | Artefact de gouvernance — suivi phases | Suivi structuré |
| 12:10 | — | `v5-specs/CHANGELOG.md` | CREATE | Artefact de gouvernance — journal modifications | Traçabilité |
| 14:39 | P0.2 | `backend/app.py` | MODIFY | Découpler frame_threshold & offset_threshold de onset_threshold | frame=0.1, offset=0.3 fixes |
| 14:39 | P0.4 | `backend/app.py` | MODIFY | Demucs désactivé par défaut piano solo | use_demucs=false par défaut |
| 14:42 | P0.1 | `frontend/index.html` | MODIFY | Slider sensibilité 0→1, labels inversés, tooltip formule | Formule plus intuitive |
| 14:43 | P0.1 | `frontend/js/app.js` | MODIFY | Calcul onset_threshold = clamp(0.65 - 0.5 × sensibilité, 0.05, 0.5) | Mapping correct |
| 14:43 | P0.3 | `frontend/js/app.js` | MODIFY | Preset Classique : Demucs=false, split=true, sensibilité=1.0 | onset=0.15 |
| 14:44 | P0.5 | `frontend/js/app.js` | VERIFY | formData.append('preset', preset) présent | preset envoyé |
| 14:58 | P1.2 | `backend/transcriber.py` | MODIFY | WarningCollector + PipelineError + strict_mode support | Mode strict: erreurs critiques lèvent PipelineError |
| 14:58 | P1.2 | `backend/app.py` | MODIFY | Ajout option 'strict_mode' dans options dict | Option transmise au pipeline |
| 15:05 | P1.4 | `backend/transcriber.py` | MODIFY | detect_tonality_safe() avec fallback pitch_class | ImportError → warning structuré |
| 15:05 | P1.4 | `backend/app.py` | MODIFY | Vérification disponibilité tonality_detector au démarrage | Status loggé + _tonality_detector_status |
| 15:15 | P1.5 | `backend/verify_prerequisites.py` | MODIFY | Refactorisation : check_all(), verify_prerequisites(), format_results() | Structure programmatique + affichage console |
| 15:15 | P1.5 | `backend/app.py` | MODIFY | Appel verify_prerequisites() au démarrage du serveur | Prérequis vérifiés avant lancement |
| 15:20 | P1.6 | `backend/transcriber.py` | MODIFY | detect_tempo_librosa() → tuple (warnings, tempo) + WarningCollector | 1/5 fallbacks corrigés |
| 15:27 | P1.7a | `backend/fastapi_app.py` | CREATE | FastAPI + SSE progress (routes health/device/gpu-status) | Migration progressive, Flask conservé pour transcribe |
| 15:33 | P1.7b | `backend/fastapi_transcribe.py` | CREATE | Endpoint transcribe FastAPI async + SSE progress | /api/transcribe migré vers FastAPI |
| 15:33 | P1.7b | `backend/fastapi_app.py` | MODIFY | Ajout endpoint /api/transcribe + imports UploadFile/File/Form | Endpoint transcribe intégré dans FastAPI |
| 15:36 | P1.7 | `backend/requirements.txt` | MODIFY | Ajout FastAPI deps (fastapi, uvicorn, pydantic, starlette) | Dépendances installées |
| 15:41 | P1.7c | `frontend/js/app.js` | MODIFY | startTranscription() avec SSE EventSource + subscribeToProgress() | Progression temps réel + récupération résultat SSE |
| 15:45 | P1.8 | `backend/models.py` | CREATE | Validation Pydantic (TranscriptionOptions, validate_options, presets) | Validation typée avant pipeline |
| 15:45 | P1.8 | `backend/fastapi_transcribe.py` | MODIFY | Intégration validate_options() + apply_preset() | Options validées côté serveur |
| 15:55 | P2.1 | `backend/server.py` | ARCHIVE | Code mort (importait pipeline.py) → legacy/ | 0 impact runtime |
| 15:55 | P2.2 | `backend/pipeline.py` | ARCHIVE | Code V1/V2 obsolète → legacy/ | 0 impact runtime |
| 15:55 | P2.3 | `backend/patch_*.py` (×5) | ARCHIVE | Patches partiels obsolètes → legacy/ | 0 impact runtime |
| 16:07 | P3.5a | `backend/score_builder.py` | MODIFY | isDownbeat + measureNumber par mesure + tempoMapMethod/detectedMeter/tempoRange dans JSON | Les mesures portent des métadonnées de mesure |
| 16:08 | P3.5b | `backend/transcriber.py` | MODIFY | tempoMapMethod, detectedMeter, tempoRange, tempoConfidence → score_data | Pipeline transmet métadonnées TempoMap |
| 16:08 | P3.5c | `backend/transcriber.py` | MODIFY | Validation 3/4 vs 4/4 dans pipeline + alertes console | Mazurka 3/4 détectée correctement |
| 16:30 | P4.1 | `backend/models.py` | MODIFY | +OrnamentThresholds (6 seuils Pydantic) + detect_appoggiaturas/detect_trills + PRESET_VALUES enrichis | Seuils ornements configurables par preset |
| 16:30 | P4.2 | `backend/ornament_detector.py` | CREATE | Détection appoggiatures → grace notes MusicXML | OrnamentDetector + detect_ornaments() |
| 16:30 | P4.3 | `backend/ornament_detector.py` | MODIFY | Détection trilles → symbole tr MusicXML | Alternance notes + trill_min_notes |
| 16:30 | P4.4 | `backend/ornament_detector.py` | MODIFY | Support rythmes pointés | Ratios canoniques (1.5, 2.0, 2.5, 3.0) |
| 16:30 | P4 | `backend/score_builder.py` | MODIFY | +ornament_result param + _build_ornaments_json() | Section 'ornaments' dans JSON score |
| 16:30 | P4 | `v5-specs/PHASE-TRACKER.md` | MODIFY | Phase 4 terminée ✅ + résumé modifications | Traçabilité complète |
| 16:30 | P4 | `v5-specs/CHANGELOG.md` | MODIFY | Ajout entrées Phase 4 | Traçabilité complète |
| 16:35 | P5.1 | `backend/transcriber.py` | MODIFY | apply_pedal_aware_shortening déplacé AVANT quantification | P5.1 : durées cohérentes pédale |
| 16:35 | P5.1 | `backend/transcriber.py` | MODIFY | apply_pedal_aware_shortening import + appel dans pipeline | P5.1 : pedal-aware shortening actif |
| 16:35 | P5.2 | `backend/transcriber.py` | MODIFY | Vélocité standardisée 0-127 avec log max/médiane | P5.2 : nuances préservées |
| 16:35 | P5.4 | `backend/transcriber.py` | MODIFY | Agrégation multi-modèles pédale (clustering + vote) | P5.4 : pédales consensus |
| 16:36 | P5 | `v5-specs/PHASE-TRACKER.md` | MODIFY | Phase 5 terminée ✅ + résumé modifications | Traçabilité complète |
| 16:36 | P5 | `v5-specs/CHANGELOG.md` | MODIFY | Ajout entrées Phase 5 | Traçabilité complète |
| 16:50 | P6.1 | `backend/transcriber.py` | MODIFY | onset_tolerance adaptatif proportionnel à BPM local | `base × (120 / bpm)` tolérance rubato |
| 16:50 | P6.2 | `backend/score_builder.py` | MODIFY | +champ uncertainNoteIds [] | Liste IDs notes fallback single-model |
| 16:50 | P6.2 | `backend/transcriber.py` | MODIFY | Propager uncertain_indices → score_builder → JSON | uncertain_note_ids dans score_data |
| 16:50 | P6.4 | `frontend/css/style.css` | MODIFY | +CSS notes incertaines (.uncertain, .uncertain-highlight, @keyframes uncertain-pulse) | Bordure pointillée orange + pulsation |
| 16:50 | P6.4 | `frontend/js/renderer.js` | MODIFY | _renderJointVoices(+uncertainIds) + registerDOMInteractions highlight | Notes incertaines visibles frontend |
| 16:50 | P6 | `v5-specs/PHASE-TRACKER.md` | MODIFY | Phase 6 terminée ✅ | Traçabilité complète |
| 16:50 | P6 | `v5-specs/CHANGELOG.md` | MODIFY | Ajout entrées Phase 6 | Traçabilité complète |
| 17:00 | P7.1 | `references/mazurka_op68_no3_reference.txt` | CREATE | Documentation référence Mazurka Op.68 No.3 | Référence pour harnais régression |
| 17:00 | P7.2 | `regression_harness.py` | CREATE | Harnais comparaison référence vs pipeline | ReferenceStore + PipelineOutputParser |
| 17:00 | P7.3 | `regression_harness.py` | CREATE | Métriques F1/rythme/ornements | MetricCalculator avec matching greedy |
| 17:00 | P7.4 | `regression_harness.py` | CREATE | Seuils bloquants + CLI + run_regression() | DEFAULT_THRESHOLDS + argparse |
| 17:00 | P7.5 | `regression_harness.py` | CREATE | Historisation JSON + MongoDB | MetricsHistory + MetricsMongoStore |
| 17:00 | P7 | `v5-specs/PHASE-TRACKER.md` | MODIFY | Phase 7 terminée ✅ + résumé | Traçabilité complète |
| 17:00 | P7 | `v5-specs/CHANGELOG.md` | MODIFY | Ajout entrées Phase 7 + résumé | Traçabilité complète |

---

## Phase 5 — Résumé des modifications

### Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `transcriber.py` | apply_pedal_aware_shortening déplacé AVANT quantification (P5.1) |
| `transcriber.py` | apply_pedal_aware_shortening import + appel dans pipeline (P5.1) |
| `transcriber.py` | Vélocité standardisée 0-127 avec log max/médiane (P5.2/P5.3) |
| `transcriber.py` | Agrégation multi-modèles pédale (clustering + vote pondéré) (P5.4) |

### Impact mesurable

| Élément | Avant | Après |
|---------|-------|-------|
| apply_pedal_aware_shortening ordre | ❌ APRÈS quantification | ✅ AVANT quantification |
| Vélocité dans MIDI | ⚠️ Variable | ✅ 0-127 standardisé |
| Dynamique préservée | ❌ Non | ✅ max/médiane loggés |
| Agrégation pédales multi-modèles | ❌ Inexistante | ✅ Clustering + vote (tolérance 50ms) |

---

## Phase 4 — Résumé des modifications

### Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `models.py` | +OrnamentThresholds (Pydantic), +detect_appoggiaturas/detect_trills (bool), PRESET_VALUES enrichis avec ornament_thresholds par preset |
| `score_builder.py` | +ornament_result param dans build_score(), +_build_ornaments_json() helper |

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `ornament_detector.py` | Module complet de détection d'ornements (OrnamentDetector, OrnamentResult, AppoggiaturaInfo, TrillInfo, DottedRhythmInfo) |

### Impact mesurable

| Élément | Avant | Après |
|---------|-------|-------|
| Seuils ornements | ❌ Codés en dur | ✅ Configurable par preset (OrnamentThresholds) |
| Détection appoggiatures | ❌ Inexistante | ✅ grace notes MusicXML (ornament_detector.py) |
| Détection trilles | ❌ Inexistante | ✅ symbole tr MusicXML |
| Rythmes pointés | ❌ Non détectés | ✅ identification + JSON |
| Ornements dans JSON score | ❌ Absents | ✅ section 'ornaments' complète |
| Presets ornements | ❌ Aucun | ✅ classique (sensible), jazz (tolérant), equilibre (standard) |

---

## Phase 3 — Résumé des modifications

### Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `score_builder.py` | - Paramètre `use_downbeats` dans `build_score()`<br>- `downbeat_times_beats` : conversion timestamps → beats<br>- `downbeat_measure_indices` : indices de downbeats par mesure<br>- `isDownbeat` + `measureNumber` dans chaque mesure<br>- `tempoMapMethod`, `detectedMeter`, `tempoRange` dans result JSON |
| `transcriber.py` | - Métadonnées TempoMap transmises à score_data (ligne ~2.5)<br>- `tempoMapMethod`, `detectedMeter`, `tempoRange`, `tempoConfidence`<br>- Validation signature 3/4 vs 4/4 dans pipeline |

### Impact mesurable

| Élément | Avant | Après |
|---------|-------|-------|
| downbeat_times dans JSON | ❌ Jamais utilisé | ✅ isDownbeat + measureNumber par mesure |
| tempoMapMethod dans JSON | ❌ Inexistant | ✅ 'madmom' / 'librosa_advanced' / 'fallback' |
| detectedMeter dans JSON | ❌ Inexistant | ✅ [numérateur, dénominateur] |
| tempoRange dans JSON | ❌ Inexistant | ✅ [BPM_min, BPM_max] |
| tempoConfidence dans JSON | ❌ Inexistant | ✅ 0.85 (madmom) / 0.6 (librosa) / 0.3 (fallback) |
| Validation 3/4 Mazurka | ❌ Aucune | ✅ Console + score_data |

---

## Template d'entrée

```
| HH:MM | Phase N | chemin/fichier.py | ACTION | description brève | impact mesurable |
```

### Exemples

```
| 14:30 | P0.1 | backend/transcriber.py | MODIFY | Inverser mapping sensibilité → seuil | MG réapparaît Mazurka |
| 15:00 | P2.3 | backend/patch_madmom.py | ARCHIVE | Code mort non importé → legacy/ | 0 impact runtime |
| 16:00 | P1.7 | backend/app.py | MODIFY | Migration route Flask → FastAPI | SSE progression temps réel |
```

---

## Phase 7 — Résumé des modifications

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `regression_harness.py` | Harnais de validation régression complet |
| `references/mazurka_op68_no3_reference.txt` | Documentation référence Mazurka Op.68 No.3 |

### Architecture

```
regression_harness.py
├── ReferenceStore          # Parse MusicXML référence
├── PipelineOutputParser    # Parse score_data JSON
├── MetricCalculator        # F1, rythme, ornements
├── RegressionReport        # Formatage + sauvegarde
├── MetricsHistory          # Historisation JSON + MongoDB
├── MetricsMongoStore       # Stockage MongoDB optionnel
└── run_regression() / main()  # Point d'entrée
```

### Seuils par défaut

| Métrique | Seuil | Description |
|----------|-------|-------------|
| f1_notes_mg | ≥ 90% | F1 main gauche |
| f1_notes_md | ≥ 90% | F1 main droite |
| precision_rythme | ≥ 85% | Précision onset |
| ornements_preserves | ≥ 80% | Taux ornements |
| signature_detectee | 100% | Signature 3/4 |
| chute_metriques | 5% | Alert if drop > 5% |

### Usage CLI

```bash
# Exécution basique
python regression_harness.py --reference mazurka.musicxml --output outputs/

# Seuils personnalisés
python regression_harness.py --reference mazurka.musicxml --output outputs/ \
  --f1-notes-mg 85 --f1-notes-md 85 --precision-rythme 80

# Historisation MongoDB
python regression_harness.py --reference mazurka.musicxml --output outputs/ \
  --mongo-uri mongodb://localhost:27017 --db audio-to-sheet --collection metrics
```

---

## Règles d'utilisation

1. **Une ligne par modification significative.** Pas de bruit.
2. **Toujours préciser la phase** (ex: `P0.1`, `P1.7`, `P3.5`).
3. **Si une modification casse quelque chose**, le noter dans la même entrée + entrée corrective.
4. **Ce fichier est vivant** — il se remplit au fil de l'eau, pas en rafale à la fin.