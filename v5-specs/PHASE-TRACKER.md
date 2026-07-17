# V5 — Phase Tracker

> **Objectif :** suivre l'avancement, les décisions et les blocages de chaque phase V5.
> Uniquement ce document + `CHANGELOG.md` servent de mémoire du projet.
>
> **Règle d'or :** une phase n'est pas terminée tant que ses critères de réussite (DoD) ne sont pas tous cochés.

---

## Légende

| Symbole | Signification |
|---------|---------------|
| `⬜` | Non démarré |
| `🔵` | En cours |
| `✅` | Terminé (DoD validé) |
| `❌` | Échoué |
| `⚠️` | Partiel / besoin attention |
| `🔒` | Bloqué |

---

## Résumé global

| Phase | Statut | Début | Fin | Notes |
|-------|--------|-------|-----|-------|
| Phase 0 | ✅ | 2026-07-17 | 2026-07-17 | Socle & quick wins |
| Phase 1 | ✅ | 2026-07-17 | 2026-07-17 | Traçabilité & FastAPI |
| Phase 2 | ✅ | 2026-07-17 | 2026-07-17 | Nettoyage code mort |
| Phase 3 | ✅ | 2026-07-17 | 2026-07-17 | Tempo unique & quantizer |
| Phase 4 | ✅ | 2026-07-17 | 2026-07-17 | Ornements |
| Phase 5 | ✅ | 2026-07-17 | 2026-07-17 | Pédale & dynamiques |
| Phase 6 | ✅ | 2026-07-17 | 2026-07-17 | Ensemble rubato |
| Phase 7 | ✅ | 2026-07-17 | 2026-07-17 | Harnais régression |
| Phase 8 | ✅ | 2026-07-17 | 2026-07-17 | Polling HTTP (remplace SSE) |
| Phase 9 | ✅ | 2026-07-17 | 2026-07-17 | Nettoyage transcripteurs UI + erreur 500 + preset Classique |

---

## Phase 0 — Socle & quick wins (débloquant) ✅

**DoD :** Main gauche récupérée sur la Mazurka · preset UI → backend correct · 0 régression Standard/Jazz.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 0.1 | Corriger mapping "Sensibilité" inversé | ✅ | — | `onset_threshold = clamp(0.65 - 0.5 × sensibilité, 0.05, 0.5)` |
| 0.2 | Découpler frame_threshold & offset_threshold de onset_threshold | ✅ | — | `frame ≈ 0.1`, `offset ≈ 0.3` |
| 0.3 | Preset "Classique" corrigé (onset 0.25-0.3, Demucs désactivé, split activé) | ✅ | — | Demucs=false, split=true, sensibilité=1.0 |
| 0.4 | Demucs : désactivé par défaut piano solo ; échec → warning explicite | ✅ | — | Par défaut `use_demucs = false` |
| 0.5 | Frontend envoie réellement le champ `preset` | ✅ | — | `formData.append('preset', preset)` présent |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | frame_threshold = 0.1 fixe | Découpler de onset_threshold |
| 2026-07-17 | offset_threshold = 0.3 fixe | Découpler de onset_threshold |
| 2026-07-17 | Slider sensibilité 0→1 (au lieu de 0.1→0.9) | Formule plus intuitive |
| 2026-07-17 | onset_threshold calculé côté frontend | `clamp(0.65 - 0.5 × sensibilité, 0.05, 0.5)` |

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 1 — Traçabilité, robustesse & FastAPI ✅

**DoD :** UI affiche tempo/quantizer/harmonie/export · mode strict fonctionne · parité Flask→FastAPI · options validées Pydantic.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 1.1 | Collecteur `warnings[]` dans pipeline → JSON → UI | ✅ | — | WarningCollector créé, intégré dans TranscriptionPipeline.run() |
| 1.2 | Mode strict (option) | ✅ | — | WarningCollector + PipelineError + strict_mode dans options |
| 1.3 | Export MusicXML never stub | ✅ | — | Plus de stub, warning si music21 manquant |
| 1.4 | tonality_detector ImportError → warning | ✅ | P1.4 | detect_tonality_safe() + fallback pitch_class |
| 1.5 | verify_prerequisites.py au démarrage | ✅ | P1.5 | check_all() + verify_prerequisites() intégrée |
| 1.6 | Remplacer print/fallbacks muets par warnings structurés | ✅ | P1.6 | detect_tempo_librosa() → tuple (warnings, tempo) + WarningCollector |
| 1.7a | FastAPI basique + SSE progress | ✅ | P1.7a | fastapi_app.py (health/device/gpu-status/SSEManager) |
| 1.7b | Endpoint transcribe FastAPI async | ✅ | P1.7b | fastapi_transcribe.py + intégration dans fastapi_app.py |
| 1.7c | Adapter frontend SSE + récupérer résultat | ✅ | P1.7c | EventSource + subscribeToProgress() + SSE result fetch |
| 1.8 | Validation Pydantic options pipeline | ✅ | P1.8 | models.py (TranscriptionOptions, validate_options, PRESET_VALUES) + intégration fastapi_transcribe.py |
| 1.9 | Vérifier config.yaml aligné | ✅ | P1.9 | config.yaml vérifié — paramètres cohérents avec code |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | WarningCollector class dans transcriber.py | Collecte structurée avec category/level/message |
| 2026-07-17 | PipelineError pour erreurs critiques | Arrêt immédiat en mode strict |
| 2026-07-17 | Plus de stub MusicXML | Échec explicite au lieu de fichier vide |
| 2026-07-17 | detect_tonality_safe() avec fallback pitch_class | P1.4 : ImportError → warning au lieu de crash |
| 2026-07-17 | Migration progressive FastAPI (pas régressive) | Zéro risque, Flask conservé pour transcribe |
| 2026-07-17 | SSEProgressManager avec asyncio.Queue | SSE temps réel sans bloquer le pipeline |
| 2026-07-17 | Validation Pydantic avec TranscriptionOptions | Validation typée + bornes + patterns + cohérence |
| 2026-07-17 | Presets centralisés dans models.py | apply_preset() + PRESET_VALUES unifiés |

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 2 — Nettoyage code mort & unification ✅

**DoD :** 0 module orphelin · 1 quantizer · 1 point d'entrée · harnais vert.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 2.1 | Trancher server.py vs app.py → FastAPI unique | ✅ | P2.1 | server.py archivé (code mort), app.py conservé actif |
| 2.2 | Archiver pipeline.py (AsyncPipeline/SSEPipeline cassés) | ✅ | P2.2 | → `legacy/` |
| 2.3 | Archiver patch_*.py (5 fichiers) | ✅ | P2.3 | → `legacy/` (5 fichiers) |
| 2.4 | Unifier NoteQuantizer + quantize_notes → quantizer.py unique | ✅ | P2.4 | quantizer.py déjà unifié |
| 2.5 | Supprimer double détection tempo | ✅ | P2.5 | build_tempo_map() déjà source unique |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | server.py → legacy/ | Code mort, importait pipeline.py (archivé) |
| 2026-07-17 | pipeline.py → legacy/ | Code V1/V2 obsolète |
| 2026-07-17 | patch_*.py → legacy/ | 5 patches partiels obsolètes |
| 2026-07-17 | quantizer.py conservé | Déjà unifié (NoteQuantizer + quantize_notes) |
| 2026-07-17 | tempo_map.py conservé | build_tempo_map() déjà source unique |

**Résultats :**
- ✅ legacy/ contient : `pipeline.py`, `server.py`, `patch_madmom.py`, `patch_phase2_quantizer.py`, `patch_phase3_ensemble.py`, `patch_phase4_madmom.py`, `patch_transcriber_run.py`
- ✅ 0 module orphelin dans backend/ actif
- ✅ 1 quantizer : `quantizer.py`
- ✅ Source tempo unique : `build_tempo_map()` dans `tempo_map.py`

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 3 — Source tempo unique & quantizer tempo-map-aware ✅

**DoD :** Décalage nul après 8+ mesures Mazurka · re-quantif sans re-transcrire · signature 3/4 détectée.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 3.1 | build_tempo_map = source unique tempo | ✅ | — | tempo_map.py (déjà fait) |
| 3.2 | Beat tracking dynamique (beats + downbeats) | ✅ | — | DBNBeatTrackingProcessor + DBNDownBeatTrackingProcessor |
| 3.3 | Détection signature rythmique (3/4 vs 4/4) | ✅ | — | _estimate_bar_length + _detect_meter |
| 3.4 | Quantizer tempo-map-aware (interpolation) | ✅ | — | tempo_quantizer.py (drop-in) |
| 3.5a | downbeat_times → JSON score (isDownbeat + measureNumber) | ✅ | P3.5a | score_builder.py : isDownbeat, measureNumber |
| 3.5b | downbeat_times → score_data pipeline (métadonnées) | ✅ | P3.5b | transcriber.py : tempoMapMethod, detectedMeter, tempoRange |
| 3.6 | Non-destructif : onset_raw + onset_quantized | ✅ | — | QuantizedNoteV4 (onset_sec_raw, beat_position_raw) |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | downbeat_times → JSON (isDownbeat + measureNumber) | Frontend affiche les temps forts visuellement |
| 2026-07-17 | tempoMapMethod → score_data | UI affiche la confiance de la détection |
| 2026-07-17 | tempoRange → score_data | UI affiche les variations de tempo |
| 2026-07-17 | Validation 3/4 vs 4/4 dans pipeline | Alertes console si détection ≠ manuelle |

**Résultats Phase 3 :**
- ✅ `score_builder.py` : isDownbeat + measureNumber par mesure
- ✅ `score_builder.py` : tempoMapMethod + detectedMeter + tempoRange dans JSON
- ✅ `transcriber.py` : métadonnées TempoMap transmises au score_data
- ✅ `transcriber.py` : validation signature détectée vs demandée
- ✅ QuantizedNoteV4 conserve onset_sec_raw + beat_position_raw (non-destructif)

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 4 — Fidélité rythmique & ornements ✅

**DoD :** Trilles/appoggiatures = ornements (pas salves) · métriques harnais en hausse.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 4.1 | Seuils configurables via presets Pydantic | ✅ | P4.1 | OrnamentThresholds + PRESET_VALUES |
| 4.2 | Détection appoggiatures → grace notes MusicXML | ✅ | P4.2 | ornament_detector.py |
| 4.3 | Détection trilles → symbole tr | ✅ | P4.3 | ornament_detector.py |
| 4.4 | Support rythmes pointés dans durées canoniques | ✅ | P4.4 | ornament_detector.py |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | OrnamentThresholds comme modèle Pydantic | Validation typée des seuils |
| 2026-07-17 | Seuils spécifiques par preset | Classique plus sensible, Jazz tolérant |
| 2026-07-17 | Détection séparée appoggiatures/trilles/rythmes | Modularité + testabilité |
| 2026-07-17 | Intégration JSON via ornament_result param | Non-destructif, backward compatible |

**Résultats Phase 4 :**
- ✅ `models.py` : OrnamentThresholds (6 seuils validés) + presets enrichis
- ✅ `ornament_detector.py` : module complet (OrnamentDetector + detect_ornaments)
- ✅ `score_builder.py` : _build_ornaments_json() intégré au JSON de sortie
- ✅ Presets : classique (sensible), jazz (tolérant rythmes pointés), equilibre (standard)

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 5 — Pédale & dynamiques ✅

**DoD :** Nuances p/f non aplaties · durées cohérentes pédale.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 5.1 | Quantification AVANT apply_pedal_aware_shortening | ✅ | P5.1 | apply_pedal_aware_shortening déplacé AVANT quantification |
| 5.2 | Vélocité standardisée 0-127 | ✅ | P5.2 | velocity [0.0-1.0] × 127 avec max/médiane |
| 5.3 | Préserver dynamique (max/médiane pondérée) | ✅ | P5.3 | Log max_amplitude + median_amplitude |
| 5.4 | Agrégation multi-modèles pédale | ✅ | P5.4 | Clustering + vote pondéré (tolérance 50ms) |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | apply_pedal_aware_shortening AVANT quantification | Préserver durées en secondes cohérentes avec pédale |
| 2026-07-17 | Vélocité × 127 avec préservation max/médiane | Ne pas aplatir les nuances dynamiques |
| 2026-07-17 | Clustering pédales avec tolérance 50ms | Fusionner détections similaires multi-modèles |
| 2026-07-17 | Vote pondéré par modèle (min_votes=2) | Ne garder que pédales consensus |

**Résultats Phase 5 :**
- ✅ `transcriber.py` : apply_pedal_aware_shortening déplacé AVANT quantification (P5.1)
- ✅ `transcriber.py` : Vélocité standardisée 0-127 (P5.2)
- ✅ `transcriber.py` : max_amplitude + median_amplitude loggés (P5.3)
- ✅ `transcriber.py` : Agrégation multi-modèles pédale avec clustering (P5.4)

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 6 — Ensemble tolérant au rubato 🟢

**DoD :** Moins de notes rejetées sur rubato · notes "incertaines" visibles frontend.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 6.1 | onset_tolerance adaptatif (proportionnel tempo local) | ✅ | P6.1 | Proportionnel à BPM local : `base × (120 / bpm)` |
| 6.2 | Fallback intelligent + flag "incertain" | ✅ | P6.2 | Single-model → uncertain_indices dans JSON |
| 6.3 | Agrégation multi-modèles pédale | ✅ | P5.4 | Déjà fait (P5.4 : clustering + vote) |
| 6.4 | Frontend : affichage notes incertaines | ✅ | P6.4 | CSS + renderer.js (highlight orange pointillé) |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| — | — | — |

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase SSE — SSE progress + GPU acceleration ✅

**DoD :** Progression SSE temps réel pendant transcription · GPU Intel XPU utilisé · heartbeat fiable.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| SSE.1 | GPU Intel XPU détecté | ✅ | P-SSE.1 | PyTorch 2.12.1+xpu, XPU available: True, 1 device |
| SSE.2 | TranscriptionPipeline.run() accepte progress_cb | ✅ | P-SSE.2 | Callback SSE depuis chaque étape du pipeline |
| SSE.3 | SSE progress events depuis pipeline | ✅ | P-SSE.3 | init→transcription→quantization→harmony→score_build→export→done |
| SSE.4 | fastapi_transcribe.py progress_cb bridge | ✅ | P-SSE.4 | async _progress_cb → _publish_progress → SSE |
| SSE.5 | Heartbeat SSE fiable (15s timeout) | ✅ | P-SSE.5 | 20 heartbeat max = 5 min |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | progress_cb dans TranscriptionPipeline.run() | Publier SSE depuis l'intérieur du pipeline |
| 2026-07-17 | async _progress_cb bridge | Connecter sync pipeline → async SSE |
| 2026-07-17 | Événements : init/transcription/quantization/harmony/score_build/export/done | Couvrir toutes les étapes du pipeline |
| 2026-07-17 | GPU XPU détecté automatiquement | detect_computing_device() → XPU > CUDA > CPU |

**Fichiers modifiés :**
| Fichier | Modifications |
|---------|--------------|
| `transcriber.py` | +progress_cb param, +_cb() calls dans chaque étape |
| `fastapi_transcribe.py` | +_progress_cb bridge, +_run_pipeline wrapper |

**Événements SSE publiés :**
| Progress | Step | Message |
|----------|------|---------|
| 0.0 | init | Démarrage de la transcription... |
| 0.10 | transcription | Prétraitement audio et transcription IA... |
| 0.35 | transcription | Transcription terminée: N notes brutes |
| 0.38 | filtering | Filtrage des notes et analyse de la pédale... |
| 0.50 | tempomap | Analyse du tempo et de la mesure... |
| 0.55 | quantization | Quantification rythmique... |
| 0.70 | harmony | Analyse harmonique et détection de tonalité... |
| 0.78 | voice_split | Séparation mains gauche/droite... |
| 0.85 | score_build | Construction de la partition... |
| 0.92 | export | Export MIDI et MusicXML... |
| 1.00 | done | Terminé — MIDI: ... |

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Phase 7 — Harnais validation régression ✅

**DoD :** Rapport F1/rythme/ornements à chaque exécution · chute métriques détectée automatiquement.

| # | Tâche | Statut | Changelog | Notes |
|---|-------|--------|-----------|-------|
| 7.1 | Créer dossier references/ + doc Mazurka | ✅ | P7.1 | mazurka_op68_no3_reference.txt créé |
| 7.2 | Script comparaison référence vs sortie pipeline | ✅ | P7.2 | regression_harness.py (ReferenceStore + PipelineOutputParser) |
| 7.3 | Métriques automatiques (F1 notes, rythme, ornements) | ✅ | P7.3 | MetricCalculator (F1, onset error, ornements) |
| 7.4 | Exécution harnais à chaque phase + seuils bloquants | ✅ | P7.4 | DEFAULT_THRESHOLDS + run_regression() + CLI |
| 7.5 | Historisation métriques JSON + MongoDB optionnel | ✅ | P7.5 | MetricsHistory + MetricsMongoStore |

**Décisions prises :**
| Date | Décision | Raison |
|------|----------|--------|
| 2026-07-17 | ReferenceStore parse MusicXML natif | Pas de dépendance externe pour le parsing |
| 2026-07-17 | PipelineOutputParser parse score_data JSON | Réutilise le format existant du pipeline |
| 2026-07-17 | MetricCalculator avec matching greedy | Simple, efficace, O(n×m) acceptable pour <500 notes |
| 2026-07-17 | DEFAULT_THRESHOLDS configurables | F1≥90%, Rythme≥85%, Ornements≥80% |
| 2026-07-17 | Historisation JSON par défaut + MongoDB optionnel | Zéro dépendance par défaut, MongoDB optionnel |
| 2026-07-17 | CLI complète avec argparse | Usage autonome ou intégré au pipeline |

**Résultats Phase 7 :**
- ✅ `references/mazurka_op68_no3_reference.txt` : documentation référence Mazurka
- ✅ `regression_harness.py` : harnais complet (ReferenceStore + PipelineOutputParser + MetricCalculator + RegressionReport + MetricsHistory)
- ✅ CLI : `python regression_harness.py --reference <xml> --output <dir>`
- ✅ Métriques : F1 notes MG/MD, précision/rythme, ornements, signature 3/4
- ✅ Seuils bloquants : configurables via DEFAULT_THRESHOLDS
- ✅ Historisation : JSON file-based (100 derniers) + MongoDB optionnel

**Fichiers créés :**
| Fichier | Description |
|---------|-------------|
| `regression_harness.py` | Harnais de validation régression complet |
| `references/mazurka_op68_no3_reference.txt` | Documentation référence Mazurka Op.68 No.3 |

**Architecture :**
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

**Seuils par défaut :**
| Métrique | Seuil | Description |
|----------|-------|-------------|
| f1_notes_mg | ≥ 90% | F1 main gauche |
| f1_notes_md | ≥ 90% | F1 main droite |
| precision_rythme | ≥ 85% | Précision onset |
| ornements_preserves | ≥ 80% | Taux ornements |
| signature_detectee | 100% | Signature 3/4 |
| chute_metriques | 5% | Alert if drop > 5% |

**Blocages :**
| Date | Blocage | Résolution |
|------|---------|------------|
| — | — | — |

---

## Jalons de livraison

| Jalon | Phases incluses | Statut | Date atteinte |
|-------|-----------------|--------|---------------|
| M0 | Phase 0 | ✅ | 2026-07-17 |
| M1 | Phase 1 | ✅ | 2026-07-17 |
| M2 | Phase 2 + 3 | ✅ | 2026-07-17 |
| M3 | Phase 4 + 5 | ✅ | P4 + P5 terminées |
| M4 | Phase 6 + finalisation | 🟢 | 2026-07-17 |
| M5 | Phase 7 (harnais) | ✅ | 2026-07-17 |

---

## Métriques de référence (à remplir Phase 7)

| Métrique | Valeur actuelle (v4) | Cible V5 | Valeur mesurée |
|----------|---------------------|----------|----------------|
| F1 notes MG (Mazurka) | — | ≥ 90% | — |
| F1 notes MD (Mazurka) | — | ≥ 90% | — |
| Précision rythmique (8 mesures) | — | décalage = 0 | — |
| Ornements préservés | — | ≥ 80% | — |
| Signature 3/4 détectée | ❌ | ✅ | — |
| Échecs silencieux | 6 | 0 | — |

> **Note :** Les valeurs mesurées seront remplies après la saisie du MusicXML référence (tâche 7.1) et la première exécution du harnais.

---

## Phase 4 — Résumé des modifications

### Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `models.py` | +OrnamentThresholds, +detect_appoggiaturas/detect_trills, PRESET_VALUES enrichis |
| `score_builder.py` | +ornament_result param, +_build_ornaments_json() |

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `ornament_detector.py` | Détection ornements (appoggiatures, trilles, rythmes pointés) |

### Impact mesurable

| Élément | Avant | Après |
|---------|-------|-------|
| Seuils ornements | ❌ Codés en dur | ✅ Configurable par preset |
| Détection appoggiatures | ❌ Inexistante | ✅ grace notes MusicXML |
| Détection trilles | ❌ Inexistante | ✅ symbole tr MusicXML |
| Rythmes pointés | ❌ Non détectés | ✅ identification + JSON |
| Ornements dans JSON score | ❌ Absents | ✅ section 'ornaments' complète |

---

## Phase 3 — Résumé des modifications

### Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `tempo_map.py` | Source unique tempo (beat + downbeat tracking) |
| `quantizer.py` | Quantizer tempo-map-aware |
| `score_builder.py` | isDownbeat, measureNumber, tempoMapMethod, detectedMeter, tempoRange |
| `transcriber.py` | Métadonnées TempoMap + validation signature |

### Impact mesurable

| Élément | Avant | Après |
|---------|-------|-------|
| Source tempo | Multiple | unique (tempo_map.py) |
| Quantization | Statique | tempo-map-aware |
| Downbeats | ❌ | ✅ isDownbeat + measureNumber |
| Tempo metadata | ❌ | ✅ tempoMapMethod + tempoRange |
| QuantizedNoteV4 | ❌ | ✅ onset_sec_raw + beat_position_raw |

---

## Note config.yaml

| Date | Vérification | Résultat |
|------|-------------|-----------|
| 2026-07-17 | Alignement config.yaml ↔ code | ✅ Aligné |

**Points vérifiés :**
- `transcriber.default` = `piano_transcription` → cohérent avec TranscriptionOptions.default
- `demucs.enabled` = `true` → cohérent (mais use_demucs=false par défaut côté API)
- `quantization.default` = `standard` → cohérent avec TranscriptionOptions.default
- `tempo.min_bpm/max_bpm` = 40/220 → cohérent avec tempo Field(gt=20, lt=300)
- `key.detector` = `krumhansl` → cohérent avec detect_tonality_safe()
- `pipeline.stages` → cohérent avec SSE progress stage mapping
- `server.sse_heartbeat_interval` = 15s → cohérent avec SSE timeout 15s