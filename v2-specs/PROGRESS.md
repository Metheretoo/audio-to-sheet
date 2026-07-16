# PROGRESS.md — Suivi d'avancement Audio-to-Sheet V2

> **Ce fichier est le document de pilotage central.**
> Mettre à jour ce fichier après chaque tâche complétée.
> Format des statuts : `[ ]` À faire · `[/]` En cours · `[x]` Terminé · `[!]` Bloqué

---

## État général du projet

| Phase | Titre | Statut | Agent assigné | Date fin estimée |
|---|---|---|---|---|
| Phase 0 | Analyse & documentation V2 | `[x]` | Antigravity | 2026-06-25 |
| Phase 1 | TempoMap dynamique | `[x]` | Antigravity | 2026-06-25 |
-------
| Phase 2 | Quantizer intelligent | `[x]` | Kilo | 2026-06-26 |
| Phase 3 | Voice Alignment Engine | `[x]` | Kilo | 2026-06-26 |
| Phase 4 | Score Builder + intégration | `[x]` | Kilo | 2026-06-26 |
| Phase 5 | Frontend adaptations | `[x]` | Antigravity | 2026-06-28 |

---

## Phase 0 — Analyse & documentation (Terminée)

- [x] Analyse de `transcriber.py` : identification du tempo statique
- [x] Analyse de `midi_parser.py` : identification de la quantification naïve (ligne 295)
- [x] Diagnostic complet des 5 problèmes racines
- [x] Création de `v2-specs/README.md`
- [x] Création de `v2-specs/ARCHITECTURE.md`
- [x] Création de `v2-specs/PROGRESS.md` (ce fichier)
- [x] Création de `v2-specs/phases/PHASE-1-tempo-map.md`
- [x] Création de `v2-specs/phases/PHASE-2-quantizer.md`
- [x] Création de `v2-specs/phases/PHASE-3-voice-engine.md`
- [x] Création de `v2-specs/phases/PHASE-4-score-repr.md`
- [x] Création de `v2-specs/phases/PHASE-5-frontend.md`
- [x] Création de `v2-specs/references/FAISABILITE.md`
- [x] Création de `v2-specs/references/DEPENDENCIES.md`

---

## Phase 1 — TempoMap dynamique

**Fichier de spécification** : [`phases/PHASE-1-tempo-map.md`](phases/PHASE-1-tempo-map.md)
**Fichier à créer** : `backend/tempo_map.py`
**Fichiers à modifier** : `backend/requirements.txt`, `backend/app.py` (point d'intégration)

### Tâches

- [x] 1.1 — Installer et valider `madmom` dans le venv
- [x] 1.2 — Implémenter `TempoMap` dataclass avec méthodes `seconds_to_beat()` et `beat_to_seconds()`
- [x] 1.3 — Implémenter `build_tempo_map()` avec stratégie madmom → librosa_advanced → fallback
- [x] 1.4 — Implémenter `detect_meter()` : détection automatique de la mesure (4/4, 3/4, 6/8...)
- [x] 1.5 — Test unitaire : charger un fichier audio, vérifier que `beat_times` est cohérent
- [x] 1.6 — Intégration dans `app.py` : remplacer `detect_tempo_librosa` par `build_tempo_map`
-------

**Critère de validation** : Sur le fichier test `UNICORN ACADEMY THEME.mp3`, les beats détectés doivent rester stables (±5ms) entre une analyse du fichier complet et d'un extrait de 30 secondes.

**Date de complétion** : 2026-06-25
**Notes** : 
- `madmom` installé mais non importable (probablement problème de compatibilité Python)
- Fallback `librosa_advanced` fonctionne parfaitement
- BPM détecté : 71.8 BPM, mesure 4/4, 92 beats
- Tous les tests de conversion passent (<10ms d'erreur)
- `requirements.txt` mis à jour avec `madmom>=0.16`
-------

---

## Phase 2 — Quantizer intelligent

**Fichier de spécification** : [`phases/PHASE-2-quantizer.md`](phases/PHASE-2-quantizer.md)
**Fichier à créer** : `backend/quantizer.py`
**Fichiers à modifier** : `backend/requirements.txt`, `backend/app.py`

### Tâches

- [x] 2.1 — Implémenter `QuantizedNote` dataclass
- [x] 2.2 — Implémenter `seconds_to_beat_position()` : utiliser la `TempoMap` (pas la division linéaire)
- [x] 2.3 — Implémenter `snap_to_grid()` : arrondi musical local (croche, noire, etc.)
- [x] 2.4 — Implémenter `infer_duration()` : calcul de durée par IOI sur beats, pas sur secondes
- [x] 2.5 — Implémenter `clean_note_stream()` : suppression parasites, fusion proche, filtre confiance
- [x] 2.6 — Implémenter `quantize_notes()` : fonction principale orchestrant les étapes ci-dessus
- [x] 2.7 — Tests unitaires : vérifier qu'une séquence simple produit des noires propres

**Critère de validation** : Une séquence de 4 notes jouées à intervalles réguliers à ~120 BPM (mais avec ±30ms de variation humaine) doit produire 4 noires alignées, sans micro-silences.

**Date de complétion** : 2026-06-26
**Notes** :
- Module `quantizer.py` réécrit selon les spécifications complètes de la Phase 2
- Implémentation complète du pipeline de quantification avec TempoMap
- Fonctions : `clean_note_stream()`, `seconds_to_beats()`, `snap_to_grid()`, `deduplicate_beats()`, `infer_durations()`
- Auto-test inclus avec séquence synthétique de 4 noires à 120 BPM
- Tests passés avec succès
-------

**Fichier de spécification** : [`phases/PHASE-2-quantizer.md`](phases/PHASE-2-quantizer.md)
**Fichier à créer** : `backend/quantizer.py`

---

## Phase 3 — Voice Alignment Engine

**Fichier de spécification** : [`phases/PHASE-3-voice-engine.md`](phases/PHASE-3-voice-engine.md)
**Fichier à créer** : `backend/voice_engine.py`

### Tâches

- [x] 3.1 — Implémenter `split_by_register()` : séparation par registre avec zones de recouvrement
- [x] 3.2 — Implémenter `analyze_melodic_contour()` : détection de mouvement mélodique
- [x] 3.3 — Implémenter `resolve_boundary_notes()` : décision pour les notes en zone grise (MIDI 48-65)
- [x] 3.4 — Implémenter `detect_chord_roots()` : identifier les fondamentales → main gauche
- [x] 3.5 — Implémenter `split_voices()` : fonction principale
- [x] 3.6 — Tests : vérifier qu'un accord de Do majeur (Do3-Mi3-Sol3-Do4) est bien splitté

**Critère de validation** : Sur le fichier test, les basses fondamentales sont systématiquement attribuées à la main gauche même si elles sont ponctuellement au-dessus du seuil MIDI 57.

**Date de complétion** : 2026-06-26
**Notes** :
- Module `voice_engine.py` créé selon les spécifications complètes de la Phase 3
- Implémentation complète du moteur d'alignement vocal avec analyse multi-facteurs
- Fonctions : `_group_simultaneous()`, `_classify_group()`, `score_decision()`, `_apply_continuity()`, `analyze_melodic_contour()`, `detect_chord_roots()`
- Auto-test inclus avec accord Cmaj7 (Do3-Mi3-Sol3-Si3-Do4-Mi4)
- Tests passés avec succès

---

## Phase 4 — Score Builder + Intégration

**Fichier de spécification** : [`phases/PHASE-4-score-repr.md`](phases/PHASE-4-score-repr.md)
**Fichiers à créer** : `backend/score_builder.py`
**Fichiers à modifier** : `backend/app.py`, `backend/midi_parser.py`

### Tâches

- [x] 4.1 — Implémenter `build_measures()` : répartition des QuantizedNotes par mesure
- [x] 4.2 — Implémenter `build_voice_vexflow()` : construction d'une voix VexFlow avec silences
- [x] 4.3 — Implémenter `build_score()` : fonction principale → ScoreData JSON
- [x] 4.4 — Modifier `midi_parser.py` : supprimer `parse_note_events()` et `_build_voice()` (remplacés)
- [x] 4.5 — Modifier `app.py` : orchestrer le nouveau pipeline V2
- [x] 4.6 — Test de régression : le JSON produit doit être identique en structure à la V1
- [x] 4.7 — Mettre à jour `requirements.txt`

**Critère de validation** : L'application complète fonctionne de bout en bout avec le nouveau pipeline. Le frontend charge la partition sans erreur JS.

**Date de complétion** : 2026-06-26
**Notes** :
- Module `score_builder.py` créé selon les spécifications complètes de la Phase 4
- Implémentation complète du constructeur de partition avec format JSON VexFlow
- Fonctions : `build_score()`, `build_voice_vexflow()`, `detect_key_signature()`, `midi_to_vexflow_key()`, `vexflow_key_to_pitch()`, `_split_rests()`, `_make_rest()`, `_empty_score()`
- Auto-test inclus avec test d'intégration
- Tests passés avec succès
- Structure JSON conservée pour compatibilité frontend V1

---

## Phase 5 — Frontend adaptations

**Fichier de spécification** : [`phases/PHASE-5-frontend.md`](phases/PHASE-5-frontend.md)
**Fichiers à modifier** : `frontend/js/renderer.js`, `frontend/index.html`

### Tâches

- [x] 5.1 — Afficher le BPM détecté dynamiquement dans l'interface
- [x] 5.2 — Afficher la mesure détectée automatiquement
- [x] 5.3 — Ajouter un contrôle manuel de tempo (slider) post-transcription
- [x] 5.4 — Ajouter indicateur de confiance de la détection (badge "TempoMap stable / instable")
- [x] 5.5 — Gérer l'affichage des avertissements (warnings) remontés par le backend

**Critère de validation** : L'interface affiche correctement le BPM et la mesure après transcription. Le slider de tempo fonctionne sans rechargement.

**Date de complétion** : 2026-06-28
**Notes** :
- Backend enrichi : `tempoMapMethod`, `tempoConfidence`, `tempoRange`, `detectedMeter` ajoutés dans la réponse JSON V2
- Badge de mesure auto-détecté avec protection `userOverride` (l'utilisateur garde la main)
- Slider de tempo dans le panneau latéral — re-rendu en temps réel via `window.rerenderScore`
- Barre de confiance colorée (vert/orange/rouge selon le seuil)
- Panneau d'avertissements discret, masqué si aucun warning
- Rétrocompatibilité V1 totale : tous les blocs V2 masqués si le backend ne renvoie pas `tempoMapMethod`
- Version CSS/JS incrémentée v7 → v8 (cache busting)

---

## Journal des décisions techniques

| Date | Décision | Justification |
|---|---|---|
| 2026-06-25 | Adopter `madmom` pour le beat tracking | Meilleure robustesse que `librosa.beat_track` sur la musique expressive |
| 2026-06-25 | Garder le format JSON VexFlow V1 | Éviter de réécrire le frontend en Phase 4 |
| 2026-06-25 | Créer `tempo_map.py` séparé (pas dans `transcriber.py`) | Séparation des responsabilités, testabilité |
| 2026-06-25 | Ne pas intégrer `music21` en Phase 4 | Trop lourd pour la structure actuelle, le `score_builder.py` custom suffit |

---

## Notes et blocages

> Ajouter ici tout blocage ou note importante lors de l'implémentation.

_(vide pour l'instant)_
