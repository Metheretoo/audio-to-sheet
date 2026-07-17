"# Plan d'action — audio-to-sheet

Ce document opérationnalise le `DIAGNOSTIC.md`. Les tâches sont ordonnées pour maximiser le gain qualité au plus petit risque de régression.

---

## Phase 0 — Sécurité (avant toute chose)

- [ ] `git checkout -b fix/pipeline-unification`
- [ ] Sauvegarde du dernier PDF Mazurka de référence pour comparer avant/après.
- [ ] Vérifier que tu peux lancer `run_prod.bat` et transcrire un WAV court (30 s) sans crash.

---

## Phase 1 — Recoller le pipeline (patch livré)

**Objectif** : rebrancher `note_filter`, `split_with_harmony`, `musicxml_exporter` sur le pipeline vivant, corriger les unités de pédale, activer les symboles d'accord par défaut.

- [ ] Ouvrir `backend/transcriber.py`.
- [ ] Repérer la classe `TranscriptionPipeline` (~ligne 894).
- [ ] Remplacer **toute la méthode `run()`** (de `def run(self, input_path, output_dir, options=None):` jusqu'à la fin de la méthode, avant `def _detect_time_signature`) par le contenu de **`patch_transcriber_run.py`** livré ici. La méthode `_detect_time_signature` est conservée telle quelle mais devient inutilisée — tu peux la garder.
- [ ] Test manuel :
  ```bash
  venv\Scripts\python.exe backend\app.py
  ```
  Puis uploader un WAV court. Vérifier dans `backend\server.log` :
  - `Pipeline] X notes après note_filter`
  - `Pipeline] Split LH/RH : split_with_harmony (guidé)`
  - `Pipeline] MusicXML généré :`
- [ ] Ouvrir le `.musicxml` dans MuseScore/Finale pour valider qu'il est structurellement correct.
- [ ] Vérifier que les symboles d'accord (ex. `Cm7`, `F`, `G7`) s'affichent au-dessus de la portée dans l'UI.

**Bugs résolus par cette phase : #1, #2, #3, #4, #5, #6.**

---

## Phase 2 — Preset \"classique\" + config.yaml (fix #7)

**Objectif** : quantification adaptée au classique/rubato (Mazurka).

- [ ] Éditer `config.yaml` — ajouter/modifier :
  ```yaml
  quantization:
    levels:
      standard:
        grid_resolution: 0.0625    # AVANT 0.25 (bug historique)
        ioi_tolerance: 0.1
        detect_tuples: true
      rubato:
        grid_resolution: 0.0625
        ioi_tolerance: 0.05
        detect_tuples: true         # AVANT false → bloquait les triolets
        adaptive_tempo: true
      classique:                    # NOUVEAU
        grid_resolution: 0.03125
        ioi_tolerance: 0.08
        detect_tuples: true
        adaptive_tempo: true
  ```
- [ ] Ajouter `<option value=\"classique\">Classique</option>` dans `frontend/index.html` (menu Quantification).
- [ ] Vérifier que `quantizer.py::_load_preset()` accepte bien la clé `classique`.

---

## Phase 3 — Nettoyer le mode ensemble (fix #8)

- [ ] Dans `transcriber.py::run_ensemble_transcription`, retirer `mt3` et `hft` de la liste `models_config` par défaut si les modules ne sont pas installés (try `import`).
- [ ] Vérifier que le fallback `piano_transcription + basic_pitch + transkun` fonctionne.
- [ ] Exposer un check-list \"modèles disponibles\" dans `/api/config` pour que l'UI grise ceux qui manquent.

---

## Phase 4 — Beat & downbeat tracking pro (madmom)

**Objectif** : détection de mesure fiable (3/4 vs 4/4 sur Mazurka).

- [ ] `pip install madmom` (offline OK — pas d'appel réseau à l'exécution).
- [ ] Compléter `tempo_map.py::build_tempo_map` pour tenter `madmom.features.beats.RNNBeatProcessor + DBNBeatTrackingProcessor` en premier, fallback librosa.
- [ ] Ajouter le downbeat tracking (`RNNDownBeatProcessor + DBNDownBeatTrackingProcessor`) → alimente `tm.estimated_meter` de façon fiable.
- [ ] Bonus : afficher dans l'UI \"Tempo détecté (madmom) : 3/4, 138 BPM ± 3\".

---

## Phase 5 — HFT-Transformer pour piano classique

**Objectif** : gagner +5-10 % de précision sur pièces classiques.

- [ ] `pip install hft-transformer` (à vérifier — sinon utiliser le repo GitHub officiel offline).
- [ ] Compléter `run_hft.py` (déjà existant en ébauche).
- [ ] Ajouter `hft` au sélecteur \"Transcripteur\" du frontend.

---

## Phase 6 — score_data étendu (tie, tuplet, grace, voice)

**Objectif** : rendre les ornements + triolets visibles + liaisons de prolongation.

- [ ] Ajouter la fonction `normalize_note` dans `score_builder.py` (voir TODO.txt).
- [ ] Ajouter `normalizeNote` en tête de `renderer.js` et `editor.js`.
- [ ] Wire `detect_ornaments()` (déjà codé dans `harmonic_analyzer.py`) sur le pipeline juste après `build_score()` — enrichir les notes concernées avec `grace={slash: true}`.
- [ ] Adapter `renderer.js` pour dessiner les grace notes VexFlow (`new StaveNote({}).slash(true)`).

---

## Phase 7 — Rendu Verovio pour PDF pro

**Objectif** : PDF de partition de qualité éditoriale (Chopin-worthy).

- [ ] `pip install verovio cairosvg pypdf` (offline).
- [ ] `verovio_export.py` est déjà écrit. Ajouter une route `/api/export-pdf` qui prend le `xml_path` du dernier job et appelle `musicxml_to_pdf`.
- [ ] Frontend : bouton \"PDF pro (Verovio)\" en plus du PDF navigateur.

---

## Phase 8 — (Optionnel) Édition WYSIWYG avec Verovio dans l'UI

**Objectif** : remplacer VexFlow (rendu-only) par Verovio (rendu + édition + PDF export).

- [ ] Charger `verovio.js` en frontend (offline, dist statique).
- [ ] Réécrire `renderer.js` pour rendre depuis MusicXML au lieu du dict `score_data`.
- [ ] `editor.js` continue de manipuler `score_data` puis regénère un `<score-partwise>` MusicXML à la volée avant chaque rendu.

Note : c'est un gros chantier. À réserver pour une v5.

---

## Métriques de succès

À mesurer sur la Mazurka Op. 68 n°3 (fichier de référence dans le repo) :

| Métrique | Avant | Objectif (après P1-3) | Objectif (après P4-7) |
|---|---|---|---|
| Notes fantômes détectées manuellement | ~15-25/page | < 5/page | < 2/page |
| Décalage LH/RH à mesure 20 | ~1 temps | < 1 croche | < 1 double-croche |
| Symboles d'accord affichés | 0 % | ~85 % (accords tonaux) | ~95 % |
| Mesure détectée automatiquement | 4/4 (faux) | 3/4 (correct) | 3/4 |
| Retouches manuelles estimées | > 50 % | ~25-30 % | ~15 % |
| Export MusicXML utilisable | ❌ | ✅ | ✅ |

---

## Ce qu'il ne faut PAS toucher pour l'instant

- `pipeline.py` / `server.py` (Stack B) — laisser tel quel, ils seront retirés en v5 après stabilisation de Stack A.
- `midi_parser.py::score_to_midi` — fonctionne, ne pas régresser.
- `voice_engine.split_with_harmony` — utilisation ok telle qu'elle est.
- Le lanceur `run_prod.bat` — pas d'impact.
"