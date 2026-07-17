# AudioScore V5 — Feuille de route (Audio → Partition Piano)

> Plan de correction et de stabilisation structuré par phases, issu de l'audit de la
> chaîne de transcription (`Metheretoo/audio-to-sheet`).
> **Contrainte permanente : 100 % local, hors-ligne, gratuit.** Aucun service payant,
> aucune dépendance réseau à l'exécution.

---

## 1. Vision V5

Passer d'une chaîne « boîte noire » qui échoue silencieusement à un pipeline
**fiable, traçable et fidèle**, dont chaque étape est observable, testée et
non destructive. L'objectif musical de référence reste la restitution correcte
d'une pièce classique à rubato (Mazurka Op. 68 No. 3 de Chopin), main gauche comprise.

### Objectifs mesurables de la V5
| # | Objectif | Indicateur de réussite |
|---|----------|------------------------|
| O1 | Fin des échecs silencieux | 0 étape critique qui « continue sans » sans warning remonté à l'UI |
| O2 | Main gauche restituée | ≥ 90 % des notes MG de la Mazurka de référence présentes (F1 onset/pitch) |
| O3 | Fidélité rythmique | Décalage cumulatif nul après 8 mesures (quantif. tempo-map-aware) |
| O4 | Reproductibilité | Toute transcription rejouable à l'identique + re-quantifiable sans re-transcrire |
| O5 | Base de code saine | 0 module mort exécutable, 1 seul point d'entrée backend, 1 seul quantizer |
| O6 | Non-régression | Harnais de test automatique exécuté à chaque phase |

### Principes directeurs (non négociables sur toutes les phases)
- **Local & gratuit** : tout modèle/outil tourne hors-ligne.
- **Fail loud, not silent** : une étape critique qui échoue lève une erreur ou remonte un warning explicite.
- **Non-destructif** : les timings bruts (`onset_raw`) ne sont jamais écrasés ; la quantification est une couche additive (`onset_quantized`).
- **Un seul chemin** : pas de code concurrent (un seul pipeline, un seul quantizer, une seule source de tempo).
- **Configurable, pas codé en dur** : les seuils musicaux vivent dans des presets versionnés.

---

## 2. Ordre des phases (priorisé)

> ⚠️ Réordonnancement volontaire par rapport à l'audit : votre **priorité n°1 est la
> stabilité/traçabilité + le nettoyage**. On la traite tôt (Phase 1) pour construire
> sur des fondations saines. La Phase 0 reste en tête car ce sont des correctifs
> quasi gratuits qui débloquent immédiatement les tests (le bug de sensibilité
> inversée est la cause racine des symptômes constatés).

| Phase | Titre | Priorité | Dépend de | Effort |
|-------|-------|----------|-----------|--------|
| **0** | Socle & quick wins (débloquant) | 🔴 Critique | — | S |
| **1** | Traçabilité, robustesse & migration FastAPI | 🔴 Critique (votre P1) | 0 | L |
| **2** | Nettoyage du code mort & unification | 🟠 Haute | 1 | M |
| **3** | Source de tempo unique & quantizer tempo-map-aware | 🟠 Haute | 1, 2 | L |
| **4** | Fidélité rythmique & ornements | 🟡 Moyenne | 3 | M |
| **5** | Pédale & dynamiques | 🟡 Moyenne | 3 | M |
| **6** | Ensemble tolérant au rubato | 🟢 Basse | 3, 5 | M |
| **7** | Harnais de validation régression | 🟠 Haute (transverse) | 0 | M |

*Effort : S = ~1-2 j, M = ~3-5 j, L = ~1-2 sem (indicatif, dev solo).*

> **Recommandation de séquencement pratique :** démarrer la Phase 7 (harnais) **en
> parallèle dès la fin de la Phase 0**, car il sert de filet de sécurité pour toutes
> les phases suivantes. C'est la garantie « fini les régressions silencieuses ».

---

## 3. Détail des phases

### Phase 0 — Socle & quick wins (débloquant) 🔴
**Objectif :** corriger les 3 bugs à impact maximal / coût minimal qui faussent
aujourd'hui toute évaluation de la qualité.

**Tâches**
- [ ] **Corriger le mapping « Sensibilité » inversé** (cause racine n°1). La sensibilité UI haute doit produire un seuil BAS :
  `onset_threshold = clamp(0.65 − 0.5 × sensibilité, 0.05, 0.5)`.
  - Fichiers : `frontend/js/app.js`, `backend/app.py`, `backend/transcriber.py`.
- [ ] **Découpler `frame_threshold` et `offset_threshold`** de `onset_threshold` (ne plus dériver `onset/3`) ; revenir aux défauts sains (`frame ≈ 0.1`, `offset ≈ 0.3`).
- [ ] **Preset « Classique » corrigé** : `onset ≈ 0.25–0.3`, `frame = 0.1`, `offset = 0.3`, **Demucs désactivé**, split mains activé.
- [ ] **Demucs** : désactivé par défaut sur piano solo ; si activé et qu'il échoue → warning explicite (pas de continuation silencieuse).
- [ ] **Frontend envoie réellement le champ `preset`** (aujourd'hui seules les valeurs dépliées partent, le backend reçoit toujours `standard`).

**Critères de succès (Definition of Done)**
- La Mazurka transcrite avec le preset Classique fait **réapparaître la main gauche**.
- Le preset choisi dans l'UI est bien celui reçu par le backend (vérifié dans les logs).
- Aucune régression sur les presets Standard/Jazz existants.

**Risques :** valeurs de seuils à affiner empiriquement → couvert par le grid search de la Phase 7.

---

### Phase 1 — Traçabilité, robustesse & migration FastAPI 🔴 (votre priorité n°1)
**Objectif :** rendre chaque étape observable et faire échouer bruyamment ce qui doit
échouer. Migration vers FastAPI pour bénéficier de l'async, de la progression SSE et
de la validation Pydantic — le tout 100 % local.

**Tâches — Traçabilité (fin des échecs silencieux)**
- [ ] **Collecteur `warnings[]`** dans le pipeline, remonté dans la réponse JSON et affiché dans l'UI :
  - méthode tempo réellement utilisée (`madmom` / `librosa` / `fallback`),
  - quantizer réellement exécuté (V4 tempo-map-aware / V3 fallback),
  - harmonie OK / échec (impacte le split MG/MD),
  - export MusicXML OK / échec.
- [ ] **Mode strict (option)** : toute étape critique en échec lève une erreur au lieu de continuer.
- [ ] **Export MusicXML** : ne plus jamais écrire de stub vide → erreur explicite.
- [ ] **`tonality_detector`** : un `ImportError` ne doit plus retourner « C majeur, confiance 0.0 » silencieusement.
- [ ] **`verify_prerequisites.py`** : vérification de `madmom` (et autres deps critiques) au démarrage, message clair si absent.
- [ ] Remplacer les `print`/logs muets des 5 fallbacks (`note_filter`, quantizer V4→V3, harmonie, export, tonalité) par des warnings structurés.

**Tâches — Migration FastAPI**
- [ ] Recréer l'API sous FastAPI : endpoint de transcription async + **endpoint de progression SSE** (les transcriptions sont longues).
- [ ] **Validation Pydantic** de toutes les options du pipeline (presets, seuils) → fin des paramètres bruts non validés.
- [ ] Conserver le frontend existant (VexFlow + Web Audio API) ; adapter uniquement les appels réseau.

**Critères de succès**
- L'UI affiche pour chaque transcription : tempo (méthode), quantizer, harmonie, export.
- Une étape critique cassée en mode strict → message d'erreur clair, pas de partition silencieusement fausse.
- L'ancien comportement fonctionnel est préservé (parité fonctionnelle Flask → FastAPI).

**Risques :** parité de comportement pendant la migration → mitigé par le harnais Phase 7 exécuté avant/après.

---

### Phase 2 — Nettoyage du code mort & unification 🟠
**Objectif :** éliminer les séquelles des refontes pour que les futures modifs
n'atterrissent plus dans du code non exécuté.

**Tâches**
- [ ] Trancher **`server.py` vs `app.py`** → un seul point d'entrée backend (celui de FastAPI, Phase 1).
- [ ] Archiver/supprimer **`pipeline.py`** (`AsyncPipeline`/`SSEPipeline` non utilisés, importent un `demucs_separator` inexistant → cassé).
- [ ] Archiver/supprimer les **`patch_*.py`** (`patch_madmom`, `patch_phase2_quantizer`, `patch_phase3_ensemble`, `patch_phase4_madmom`, `patch_transcriber_run`).
- [ ] **Unifier les deux quantizers concurrents** (`NoteQuantizer` classe vs `quantize_notes` fonction) en un seul module `quantizer.py`.
- [ ] Supprimer la **double détection de tempo** (`detect_tempo_librosa` dans `transcribe_audio` + `build_tempo_map`) → préparer la source unique (Phase 3).

**Critères de succès**
- `grep` de code mort = 0 module exécutable orphelin.
- Un seul quantizer, un seul point d'entrée, importés partout.
- Le harnais (Phase 7) passe toujours au vert après nettoyage.

**Risques :** supprimer un module « faussement mort » → mitigé : archiver dans `legacy/` avant suppression + tests.

---

### Phase 3 — Source de tempo unique & quantizer tempo-map-aware 🟠
**Objectif :** corriger le décalage cumulatif catastrophique du rubato en faisant du
tempo variable la base de la quantification.

**Tâches**
- [ ] **`build_tempo_map` = source unique de tempo** ; `detect_tempo_librosa` retiré de `transcribe_audio`.
- [ ] **Beat tracking dynamique** (beats + downbeats) au lieu d'un BPM global → la tempo map suit le rubato mesure par mesure.
- [ ] **Détection de la signature rythmique** (3/4 vs 4/4) — critique pour la Mazurka.
- [ ] **Quantizer tempo-map-aware** : conversion secondes → beats par **interpolation via la map**, jamais via `60/bpm` fixe.
- [ ] **Implémenter réellement `downbeat_times`** dans le quantizer (aujourd'hui code mort).
- [ ] **Non-destructif** : chaque note conserve `onset_raw` **et** `onset_quantized` → re-quantification sans re-transcription + alimente l'éditeur frontend.

**Critères de succès**
- Décalage cumulatif nul après 8+ mesures sur la Mazurka de référence.
- Changer le tempo/quantif ne nécessite plus de re-transcrire (re-quantif à la volée).
- Signature rythmique 3/4 correctement détectée sur la Mazurka.

**Risques :** qualité de `madmom`/downbeats sur rubato extrême → warning si confiance faible (Phase 1) + fallback tracé.

---

### Phase 4 — Fidélité rythmique & ornements 🟡
**Objectif :** cesser de « massacrer » les ornements par des seuils codés en dur.

**Tâches**
- [ ] **Rendre tous les seuils configurables** (fin des valeurs codées en dur) via presets Pydantic :
  - `min_note_duration_beats` (0.25 aujourd'hui → abaissé à la triple-croche pour le Classique),
  - `merge_threshold_beats` (0.1 → désactivé/quasi-nul pour le Classique),
  - `snap_threshold_ratio` (0.45 → réduit, aimantation moins agressive).
- [ ] **Détection d'appoggiatures** : note très courte juste avant un temps → `grace note` en MusicXML.
- [ ] **Détection de trilles** : alternance rapide de 2 hauteurs → symbole `tr` au lieu de 12 notes illisibles.
- [ ] **Support des rythmes pointés** dans les durées canoniques.

**Critères de succès**
- Trilles/appoggiatures de la Mazurka rendus comme ornements, pas comme salves de notes.
- Taux d'ornements préservés mesuré par le harnais (Phase 7) en hausse nette.

**Risques :** faux positifs de détection d'ornements → réglage par preset + validation régression.

---

### Phase 5 — Pédale & dynamiques 🟡
**Objectif :** arrêter d'écraser le travail de la pédale et aplatir la dynamique.

**Tâches**
- [ ] **Inverser l'ordre** : quantification d'abord, `apply_pedal_aware_shortening` ensuite (son travail n'est plus écrasé).
- [ ] **Standardiser la vélocité** : représentation interne unique **0-127** dès la sortie de chaque modèle ; supprimer l'heuristique `if velocity > 1`.
- [ ] **Préserver la dynamique** : remplacer `weighted_mean` de l'ensemble par **max ou médiane pondérée**.
- [ ] (Préparé pour Phase 6) agrégation multi-modèles de la pédale plutôt que garder seulement le modèle primaire.

**Critères de succès**
- Les nuances (p/f) de la Mazurka ne sont plus aplaties.
- Durées de notes cohérentes avec la pédale, sans double écrasement.

---

### Phase 6 — Ensemble tolérant au rubato 🟢
**Objectif :** que les modèles « votent » correctement malgré le tempo variable.

**Tâches**
- [ ] **`onset_tolerance` adaptatif** : 50 ms fixe → tolérance proportionnelle au tempo local (via la tempo map).
- [ ] **Fallback intelligent** : une note rejetée par `min_votes = 2` mais avec forte confiance du modèle primaire est conservée avec un **flag « incertain »** (exploitable dans l'éditeur).
- [ ] **Agrégation multi-modèles de la pédale** (vote par recouvrement d'intervalles).
- [ ] Frontend : affichage visuel des notes « incertaines ».

**Critères de succès**
- Moins de notes valides rejetées sur passages à rubato marqué.
- Les notes « incertaines » sont visibles et éditables côté frontend.

---

### Phase 7 — Harnais de validation régression 🟠 (transverse, à démarrer tôt)
**Objectif :** filet de sécurité automatique — « fini les régressions silencieuses ».

**Tâches**
- [ ] **Saisir le MusicXML de référence** de la Mazurka Op. 68 No. 3 depuis l'image de la partition (quelques mesures suffisent au départ — vous avez confirmé qu'il n'existe pas encore).
- [ ] Script de comparaison **référence vs sortie du pipeline**.
- [ ] **Métriques automatiques** : F1 notes (onset/pitch), précision rythmique, taux d'ornements préservés.
- [ ] Exécution du harnais **à chaque phase** (avant/après) ; seuils de régression bloquants en CI locale.
- [ ] (Optionnel) **MongoDB** pour historiser les jobs de transcription et l'évolution des métriques de régression.

**Critères de succès**
- Un rapport chiffré (F1, rythme, ornements) produit à chaque exécution.
- Toute chute de métrique entre deux phases est détectée automatiquement.

---

## 4. Cas de test de référence
- **Pièce :** Chopin, Mazurka Op. 68 No. 3 (piano solo, rubato, main gauche discrète, ornements, mesure 3/4).
- **Ground truth :** MusicXML **à ressaisir depuis l'image** (Phase 7) — commencer par 8–16 mesures représentatives.
- **Entrée :** votre fichier FLAC haute qualité.
- **Pourquoi :** concentre tous les défauts constatés (perte MG, rubato, ornements, signature rythmique).

---

## 5. Stack technique cible V5
| Couche | Choix V5 | Note |
|--------|----------|------|
| Backend | **FastAPI** (migration Phase 1) | async + SSE + validation Pydantic, 100 % local |
| Frontend | VexFlow + Web Audio API (conservé) | enrichi pour notes « incertaines » |
| Modèles IA | Piano Transcription / Transkun (ensemble) | inchangés, hors-ligne |
| Tempo/beat | `madmom` (primaire) → `librosa` (fallback tracé) | source unique |
| Persistance | MongoDB (optionnel, Phase 7) | historisation jobs + métriques |

---

## 6. Jalons de livraison
| Jalon | Contenu | Résultat attendu |
|-------|---------|------------------|
| **M0** | Phase 0 | Main gauche récupérée, tests débloqués |
| **M1** | Phases 1 + 7 (démarrage) | Pipeline observable, filet de régression en place, FastAPI |
| **M2** | Phases 2 + 3 | Base saine + rubato correct (pas de décalage cumulatif) |
| **M3** | Phases 4 + 5 | Ornements et dynamiques fidèles |
| **M4** | Phase 6 + finalisation | Ensemble robuste au rubato → **V5 stable** |

---

## 7. Risques transverses & parades
| Risque | Impact | Parade |
|--------|--------|--------|
| Réglage empirique des seuils | Qualité variable | Grid search + harnais Phase 7 |
| Régression pendant migration FastAPI | Perte de fonctionnalité | Parité testée avant/après via harnais |
| `madmom` absent/instable en local | Tempo faux | Vérif au démarrage + warning + fallback tracé |
| Suppression de code « faussement mort » | Bug caché | Archiver dans `legacy/` avant suppression |
| Ground truth incomplet | Métriques peu fiables | Étendre progressivement le MusicXML de référence |

---

## 8. Prochaines actions immédiates
1. Valider cette feuille de route (ordre des phases, jalons).
2. Démarrer **Phase 0** (quick wins débloquants).
3. Lancer en parallèle **Phase 7** : ressaisir les premières mesures de la Mazurka en MusicXML.
4. Enchaîner sur **Phase 1** (votre priorité n°1 : traçabilité + FastAPI).

---
*Document de planification — version 1. À amender au fil des retours et des mesures du harnais de régression.*
