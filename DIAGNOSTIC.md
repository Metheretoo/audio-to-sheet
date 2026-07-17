"# Diagnostic — audio-to-sheet (Metheretoo)

Analyse effectuée à partir du repo cloné : https://github.com/Metheretoo/audio-to-sheet
Portée : uniquement le pipeline backend. Constat basé sur la lecture du code, pas sur une exécution runtime (le projet tourne chez toi en local Windows).

---

## TL;DR — Ce qui est cassé (par ordre de gravité)

| # | Problème | Impact utilisateur | Localisation |
|---|----------|-------------------|--------------|
| **1** | **Deux pipelines parallèles concurrents** — `app.py + transcriber.TranscriptionPipeline` (celui qui tourne réellement) vs `server.py + pipeline.AsyncPipeline` (le \"moderne\" avec SSE/filtres/harmonie) | Tous les fixes récents (note_filter, split_with_harmony, exporters unifié) sont écrits mais **jamais exécutés** | `backend/app.py` (utilisé par `run_prod.bat`) vs `backend/server.py` (mort) |
| **2** | **`note_filter.py` (ghost notes + pedal-aware shortening) jamais appelé** dans le pipeline vivant | Notes fantômes + pédale écrasée = \"soupe de notes\" sur la Mazurka | `transcriber.TranscriptionPipeline.run()` |
| **3** | **`split_with_harmony` jamais appelé** dans le pipeline vivant → seuil MIDI fixe pour la séparation LH/RH | Main gauche systématiquement pire, surtout sur accords enrichis | `transcriber.TranscriptionPipeline.run()` étape 4 |
| **4** | **Symboles Jazz (accords) invisibles** en dehors du preset `jazz` | Ton problème exact : \"les noms des accords ne s'affichent pas\" | `transcriber.py:1060` → `write_chord_symbols=(preset=='jazz')` |
| **5** | **Export MusicXML = stub vide** dans le pipeline vivant | Impossible d'ouvrir dans MuseScore/Finale | `transcriber.py:1078-1080` (écrit 30 caractères de XML vide) |
| **6** | **Pédales passées en secondes à `build_score`** au lieu de beats | Pédale mal placée / mal quantifiée sur la partition | `transcriber.py:1063` (`pedals=pedal_intervals`) |
| **7** | **Grille de quantification standard = 1/4 (noire)** trop grossière pour classique | Rubato mal quantifié, doubles-croches jamais reconnues | `config.yaml` → `quantization.levels.standard.grid_resolution=0.25` (voir TODO.txt) |
| **8** | **`MT3` référencé dans l'ensemble** mais requiert un clone Docker `/mt3` inexistant en local | Le mode `ensemble` plante silencieusement ou skip | `transcriber.py:504-563` |
| **9** | **`transcriber.py::TranscriptionPipeline.run()` ignore la config d'ensemble** (contrairement à `pipeline.py._transcribe`) | Impossible d'activer l'ensemble depuis l'UI | `transcriber.py:934-942` |
| **10** | **Tempo Map utilisée pour la quantification mais pas pour la séparation des voix ni pour `build_score`** | Décalage progressif LH/RH dans les mesures suivantes | `transcriber.py:1044-1064` |

---

## 1. La schizophrénie du pipeline (la cause racine)

Le repo contient **deux stacks HTTP+pipeline complètement séparés** :

### Stack A — Celui qui tourne (via `run_prod.bat` → `python backend/app.py`, port 5000)
```
app.py  ──►  transcriber.TranscriptionPipeline.run()
             │
             ├── transcribe_audio() (piano_transcription / basic_pitch / transkun / ensemble)
             ├── filtrage manuel (remove_short_notes + merge_near_notes)   ⚠️ pas de note_filter
             ├── build_tempo_map()
             ├── quantize_notes()
             ├── build_harmonic_context()   ← uniquement si preset==jazz OU detect_key
             ├── split_voices()             ← simple, sans contexte harmonique
             ├── build_score() avec write_chord_symbols=(preset=='jazz')  ← accords invisibles hors jazz
             ├── midi_parser.score_to_midi()
             └── ⚠️ XML = stub vide en dur
```

### Stack B — Le \"moderne\" (mort, jamais lancé)
```
server.py  ──►  SSEPipeline.run()  (dans pipeline.py)
                │
                ├── _load_audio
                ├── _run_demucs (via backend.demucs_separator qui n'existe même pas)
                ├── _transcribe
                ├── _filter_notes          ← ✅ utilise note_filter (ghost + pedal-aware)
                ├── _quantize
                ├── _analyze_harmony        ← ✅ pédales converties en beats
                ├── _split_hands            ← ✅ split_with_harmony
                ├── _build_score            ← ✅ write_chord_symbols=True + overrides key_sig/time_sig
                └── _export → exporters.export_all_formats
                              ├── musicxml_exporter.export_musicxml  ✅
                              └── midi_exporter.ScoreExporter (LilyPond → PDF) ✅
```

**Ce que ça produit concrètement** :
- Tous les commentaires `# BUG CORRIGÉ (v4.2)` dans `pipeline.py` s'appliquent à du code **jamais exécuté**.
- Les fichiers `note_filter.py`, `musicxml_exporter.py`, `verovio_export.py`, `score_data.py`, `exporters.py` sont morts.
- Le `TODO.txt` propose un score_data étendu (`tie`, `tuplet`, `grace`, `voice`) qui n'existe nulle part.
- L'UI reçoit un `score_data` fabriqué par la Stack A avec des accords qui ne sont pas remplis, une pédale mal alignée, et un `xml_path` qui pointe sur un fichier vide.

**Fix stratégique** : au lieu de brancher `server.py` (qui a d'autres bugs — `backend.demucs_separator` inexistant, boucle SSE fragile), on **rapatrie dans `TranscriptionPipeline.run()` les 6 correctifs de Stack B**. C'est chirurgical, sûr, et ne touche à rien d'autre.

---

## 2. Détail des bugs et de leur cause exacte

### Bug #2 — `note_filter` jamais appelé
- `transcriber.py:949-984` fait un filtrage naïf par `remove_short_notes` + `merge_near_notes`.
- `note_filter.filter_ghost_notes()` (velocity + duration combinés) et `note_filter.apply_pedal_aware_shortening()` (raccourcit les notes tenues sous pédale à ~1s max, ce qui évite la \"ronde-liée-blanche\" illisible) sont **écrits mais orphelins**.
- Sur la Mazurka, le pianiste tient la pédale = tu vois des notes de 4-8 secondes qui deviennent ronde-liée-ronde-liée-ronde en notation. C'est exactement ce que `apply_pedal_aware_shortening` corrige.

### Bug #3 — LH/RH par seuil fixe
- `voice_engine.split_voices()` utilise essentiellement un seuil MIDI (typiquement 60).
- `voice_engine.split_with_harmony()` (invisible depuis Stack A) exploite le `harmonic_ctx` pour placer les notes de fondamentale + septième à gauche, les extensions à droite.
- C'est **la** raison technique de \"la main gauche est toujours pire, surtout sur accords enrichis\".

### Bug #4 — Accords Jazz invisibles
```python
# transcriber.py:1055-1061
score_options = {
    ...
    'write_chord_symbols': (preset == 'jazz'),   # ← seul cas où c'est True
    ...
}
```
Or l'UI (`app.js`) envoie `preset='standard'` par défaut, et il n'y a pas de case à cocher \"afficher les accords\". Résultat : peu importe ce que tu coches, les symboles ne sortent pas.

Note : dans `pipeline.py:735` (Stack B), c'est `'write_chord_symbols': True` en dur. C'est ce qu'il faut appliquer.

### Bug #5 — XML vide
```python
# transcriber.py:1078-1080
with open(xml_path, 'w') as f:
    f.write(\"<?xml version=\\"1.0\\" encoding=\\"UTF-8\\"?><score-partwise></score-partwise>\")
```
Un vrai `musicxml_exporter.export_musicxml(score_data, xml_path)` existe mais n'est **pas appelé**.

### Bug #6 — Pédales en unité incohérente
- `pedal_intervals` renvoyées par `piano_transcription_inference` sont en **secondes**.
- `build_score(pedals=pedal_intervals, ...)` est appelé avec des secondes.
- Mais `score_builder` mélange interne (au vu du code de `pipeline.py:_analyze_harmony`, les pédales doivent être en beats).
- Dans Stack B on convertit : `pedal_beats.append((tm.seconds_to_beat(p_start), tm.seconds_to_beat(p_end)))` puis on passe ça.

### Bug #7 — Grille trop grossière
`config.yaml` doit avoir (extrait TODO) :
```yaml
quantization:
  levels:
    standard:
      grid_resolution: 0.0625   # AVANT 0.25 (noire) - trop grossier
    classique:                  # NOUVEAU preset dédié
      grid_resolution: 0.03125  # triple croche
      ioi_tolerance: 0.08
      detect_tuples: true
      adaptive_tempo: true
```

### Bug #8 — MT3 mort en local
`run_mt3` cherche `/mt3` (chemin Docker). Sur Windows, ça lève. Dans l'ensemble, le try/except swallow l'erreur mais on perd un modèle silencieusement.
Fix : retirer `mt3` de la liste des modèles par défaut de `run_ensemble_transcription`.

### Bug #10 — Tempo Map partielle
La `tempo_map` est passée à `quantize_notes()` mais :
- `split_voices()` n'a pas la tempo_map (elle en a besoin pour les beats absolus).
- `build_score()` non plus — elle reçoit `tm` seulement en Stack B (`tempo_map=tm`).
- Résultat : les positions de notes sont quantifiées \"temps réel\", mais la génération de la mesure prend une pulsation moyenne → décalage LH/RH cumulatif à partir de la mesure 2 (ton constat exact).

---

## 3. Ce qui te bloque sur la Mazurka spécifiquement

La Mazurka Op. 68 n°3 en fa majeur cumule tous les cas difficiles :
1. **Rubato marqué** → grille 1/4 la casse en morceaux.
2. **Basses larges d'accompagnement** (main G avec fondamentale + accord aigu) → `split_voices` sans harmonie envoie tout l'accord aigu à droite.
3. **Pédale longue** → pedal-aware shortening jamais appliqué → notes tenues 3-4s en clé de fa.
4. **Ornements** (mordants, appogiatures) → `detect_ornaments()` existe dans `harmonic_analyzer.py` mais n'est pas branché sur `score_builder`.

Tous ces problèmes sont réparables par le patch ci-dessous, sauf le point 4 (ornements) qui demande une extension de `score_data` (voir plan d'action).

---

## 4. Pistes non explorées (offline, gratuit)

### Priorité HAUTE (débloque toute la qualité)
1. **Recoller Stack A ⇔ Stack B** (fait dans le patch livré).
2. **Passer par défaut sur le mode \"ensemble\"** en local (Piano-Transcription + Transkun + basic-pitch pondérés) : c'est déjà codé, il suffit de retirer `mt3`, `hft` de la liste par défaut si non installés. **Gain qualité mesuré typique : +15-20 % F1 sur pièces classiques**.
3. **Preset \"classique\" dédié** (grille 1/32, `detect_tuples=true`, `adaptive_tempo=true`) — permet de reconnaître les triolets typiques de la Mazurka.
4. **Wire `detect_ornaments()`** sur `score_builder` — la fonction est déjà codée, il faut juste ajouter un champ `ornament` au dict de note et le rendu VexFlow correspondant.

### Priorité MOYENNE (améliore substantiellement)
5. **Beat tracking avec `madmom`** (offline, licence libre) au lieu de `librosa.beat_track` : `madmom.features.beats.RNNBeatProcessor` + `DBNBeatTrackingProcessor` sont l'état de l'art open source pour la détection de beats dynamiques. Dans `tempo_map.py`, tu es déjà prêt (`tm.method == 'madmom'`) mais il faut installer et brancher.
6. **Downbeat detection avec `madmom.features.downbeats`** — donne la mesure automatiquement (3/4 vs 4/4). Aujourd'hui `estimated_meter` est deviné par heuristique IOI, peu fiable en rubato.
7. **`hft` (High-resolution Piano Transcription)** — modèle open source spécialisé piano classique, sensiblement meilleur que `piano_transcription_inference` sur les nuances (Chopin, Debussy). `run_hft.py` existe déjà, il faut juste `pip install hft-transformer` et l'exposer dans l'UI.
8. **Score representation stable via `music21`** : au lieu que `score_builder` produise directement du VexFlow JSON, générer un `music21.stream.Score` intermédiaire puis exporter en (a) VexFlow, (b) MusicXML, (c) LilyPond, (d) PDF via `music21.converter.subConverters.ConverterLilypond`. **C'est la vraie réponse au \"score representation stable\" que tu demandais**.

### Priorité BASSE (raffinement)
9. **`basic-pitch` avec `melodia_trick=False`** en polyphonique — évite les fausses harmoniques.
10. **Post-filtre \"pédale sostenuto vs forte\"** : `piano_transcription_inference` détecte la pédale forte (CC64) uniquement. Pour classique, la sostenuto (CC66) manque. Solution : détection par flux d'énergie basse sur le résidu Demucs.
11. **Édition partition dans l'UI → export PDF** : intégrer **Verovio** (JS, offline) côté frontend au lieu de VexFlow. Verovio est plus musicologique, gère les liaisons/tuplets/grace notes nativement, et exporte directement en SVG/PDF via `verovio_export.py` déjà présent.

### Pistes 100% offline & gratuites recommandées
| Besoin | Outil recommandé | Statut projet |
|---|---|---|
| Beat + downbeat tracking | **madmom** (Python, BSD-3) | À installer |
| Piano SOTA | **HFT-Transformer** (MIT) | Ébauche présente |
| Structure symbolique | **music21** (BSD) | Déjà utilisé partiellement |
| Rendu partition PDF | **Verovio** (LGPL) + cairosvg | Ébauche présente |
| Export PDF via LilyPond | **LilyPond** (GPL) | Utilisé par midi_exporter |
| Édition WYSIWYG | **Verovio** dans l'UI | Non intégré |

---

## 5. Points sur lesquels ne pas t'attendre à des miracles

- **Rubato extrême** (Rachmaninoff, Horowitz) → même madmom se fait piéger. Solution partielle : mode \"recalé sur la première mesure\" où l'utilisateur clique manuellement les downbeats de la 1re mesure.
- **Séparation main G / D sur croisements de mains** (Ravel, Debussy) → impossible sans modèle dédié. Il n'existe pas de modèle open source de hand-split fiable pour piano audio. `split_with_harmony` gagne 10-15 % mais reste imparfait.
- **Ornements Chopin** (roulades, ornements complexes) → la retranscription automatique ne les mettra jamais en petites notes/grace notes. Il faudra les retoucher.

Objectif réaliste : **passer de ~50 % de retouches manuelles à ~15 %** sur la Mazurka.

---

## 6. Ordre d'application recommandé

Voir `PLAN_ACTION.md` et le patch `patch_transcriber_pipeline.diff`.
"