# Audit V5 — audio-to-sheet (état réel du code, branche master)

> Audit statique du code réellement exécuté, réalisé sur le dépôt cloné.
> Objectif : répondre à 2 questions —
> **(1)** reste-t-il des étapes qui écrasent le travail précédent ou des échecs silencieux qui ruinent le résultat ?
> **(2)** erreurs architecturales / anomalies / meilleure façon de faire ?

---

## TL;DR — Pourquoi vous ne voyez aucune amélioration

**La quasi-totalité des correctifs V5 est écrite dans des chemins de code jamais exécutés.**
Le lanceur `AudioScore.vbs` démarre `python backend\app.py` (**Flask**, port 5000).
Or les fixes V5 (validation Pydantic, `apply_preset()`, migration FastAPI, formule
de « sensibilité » corrigée) vivent dans `fastapi_app.py` / `fastapi_transcribe.py` /
`models.py` / l'app.js « corrigé » — **tous contournés**. C'est exactement la
« schizophrénie de pipeline » de l'audit initial… revenue sous une autre forme.

Résultat : le chemin réel est **inchangé** par rapport au bug d'origine, ce qui explique
précisément votre symptôme (« la main gauche s'efface quand j'augmente la sensibilité »).

---

## 1. Anomalie architecturale n°1 — deux stacks concurrents, le lanceur pointe sur le mauvais

| | Stack **exécuté** | Stack **mort** |
|---|---|---|
| Point d'entrée | `backend/app.py` (Flask, port 5000) | `backend/fastapi_app.py` + `fastapi_transcribe.py` |
| Lancé par | `AudioScore.vbs` → `python backend\app.py` | rien |
| Validation options | ❌ aucune (lecture brute du form) | ✅ `validate_options()` Pydantic — **jamais appelé** |
| Application preset serveur | ❌ | ✅ `apply_preset()` (models.py) — **jamais appelé** |

**Preuve :** `AudioScore.vbs:28` → `... python backend\app.py`.
`fastapi_transcribe.py:137` (`validate_options`) et `:45` (`apply_preset`) ne sont donc
jamais atteints.

➡️ **Tout P1.7 / P1.8 du CHANGELOG (FastAPI + Pydantic) est du code mort.**

---

## 2. Le bug « sensibilité » est TOUJOURS présent dans le chemin réel

- Le slider a l'id `onset-threshold` et le frontend envoie sa **valeur brute** :
  `frontend/js/app.js:465` → `formData.append('onset_threshold', document.getElementById('onset-threshold').value)`.
- **Aucune** transformation `clamp(0.65 − 0.5 × sensibilité, …)` n'existe dans l'`app.js`
  réel (elle est annoncée dans le CHANGELOG P0.1 mais **absente du code**).
- Côté serveur, `app.py:299` relit la valeur brute et la passe telle quelle :
  `onset_threshold_val = float(request.form.get('onset_threshold', 0.5))`.

**Conséquence directe :** monter le curseur = monter `onset_threshold` = **moins** de
notes détectées = main gauche (notes douces) effacée. C'est votre symptôme exact,
sémantiquement inversé par rapport à ce qu'un utilisateur attend.

**Aggravant :** le preset **Classique** met le curseur à `0.85` (`app.js:273`) — seuil
catastrophique. (Il est partiellement masqué parce que Classique utilise Transkun qui
ignore ce seuil, cf. §5 — mais tout preset basé sur `piano_transcription`/`basic_pitch`
en souffre pleinement.)

---

## 3. Échecs silencieux / valeurs ignorées encore actifs

### 3.1 🔴 Mismatch de nom → la quantification « légère » est ignorée
- Frontend envoie le champ **`quantization`** (`app.js:469`).
- Backend lit **`quantization_level`** (`app.py:316`) → introuvable → **toujours `standard`**.
- Le preset Classique choisit pourtant `light` : ce choix **n'atteint jamais** le quantizer.
- Pire : `tempo_quantizer.PRESETS` contient une entrée **`classique`** soignée
  (zéro fusion, triple-croche, aimantation douce) qui n'est **jamais sélectionnable**
  (l'UI n'offre que light/standard/heavy). → Le « bon » quantizer classique est du code mort.
- **Impact :** contredit directement le conseil « Transkun + quantification légère ».
  Vous obtenez la grille `standard` (fusion 0.05, snap 0.40) alors que vous croyez avoir léger.

### 3.2 🟠 Faute de frappe sur l'offset → seuil ignoré silencieusement
`transcriber.py:895` : `transcriber.offset_threshod = onset_threshold`
(`threshod` au lieu de `threshold`). L'attribut réel n'est jamais réglé →
la librairie garde son défaut, et **l'`offset_threshold` envoyé par l'UI est ignoré**.
De plus la ligne recouple (par intention) l'offset à l'onset, ce que l'audit demandait
justement de **découpler** — la faute de frappe neutralise l'intention par accident.

### 3.3 🟠 Dynamique (P5) calculée mais jamais appliquée
`transcriber.py:1453-1457` calcule `max_amplitude` / `median_amplitude`… puis se contente
de les **`print`**. La conversion de vélocité reste un simple `round(v×127)` (ligne 1464).
La « préservation de la dynamique par max/médiane pondérée » du CHANGELOG P5 est **cosmétique**.
En prime, la vélocité subit 3 conversions successives (÷127 ligne 1403 → ×127 ligne 1464 →
÷127 `_to_amplitude` dans le quantizer) : churn inutile, source d'imprécision.

### 3.4 🟡 Warnings non remontés hors mode strict
Le `WarningCollector` est bien branché, mais en mode normal (`strict_mode=false` par défaut)
les échecs (import `note_filter`, harmonie, tonalité) sont seulement **loggés** et empilés
dans `score_data['warnings']` — l'UI ne force pas leur affichage. L'utilisateur ne voit pas
qu'une étape a été sautée. La traçabilité existe côté données mais reste passive.

### 3.5 🟡 Ordre pédale ↔ quantification : intention contredite par le commentaire
Le commentaire (`transcriber.py:1391`) dit « appliqué APRÈS la quantification » alors que le
code applique `apply_pedal_aware_shortening` **AVANT** (ligne 1420, quantif ligne 1491).
Le comportement (raccourcir puis quantifier) est en soi défendable et n'écrase pas les
durées (le quantizer conserve les `*_raw`), mais l'intention documentée et le code divergent
→ dette de confusion. **Le vrai problème pédale est ailleurs** (cf. §5).

---

## 4. Ce qui, en revanche, est correct en V5 (à conserver)

- ✅ `tempo_quantizer.py` (V4) est **bien conçu** : conversion secondes→beats via la tempo
  map (`seconds_to_beat`), timings `*_raw` conservés, presets, aimantation binaire/ternaire.
  Non destructif comme demandé.
- ✅ Le pipeline vivant appelle bien désormais `note_filter.filter_ghost_notes`,
  `split_with_harmony` (si harmonie OK), l'analyse harmonique **toujours**, l'export
  MusicXML réel (plus de stub vide) et `chord_symbols` par défaut. Ces correctifs-là
  sont, eux, **réellement dans le chemin exécuté**.
- ✅ `legacy/` : le code mort historique (`server.py`, `pipeline.py`, `patch_*.py`) a bien
  été archivé.

---

## 5. Chemin « Classique = Transkun » : limites réelles

- ✅ Bon choix : le preset Classique bascule sur `transkun` (`app.js:263`), conforme au conseil.
- 🔴 `run_transkun` **ne renvoie aucune pédale** : `return note_events, midi_data, []`
  (`transcriber.py:629`). Transkun exporte pourtant les CC64 dans son MIDI, mais le code ne
  lit que `instrument.notes`. → Sur le chemin classique, `apply_pedal_aware_shortening` et la
  fusion de tranches par pédale n'ont **aucune donnée** : pédale perdue.
- 🟠 `run_transkun` ignore `onset_threshold`/`frame` (normal, c'est un subprocess) — donc le
  curseur à 0.85 n'affecte pas Classique ; mais couplé au §3.1 (quantif `standard` au lieu de
  légère), la sortie classique n'est pas celle que vous croyez configurer.
- ⚠️ Dépend d'un `python -m transkun.transcribe` installé et fonctionnel en local ; en cas
  d'échec, `RuntimeError` remonte (pas silencieux, bien) mais l'UX est brutale.

---

## 6. Trois sources de vérité pour les presets (anomalie de conception)

Les mêmes paramètres sont définis à **3 endroits divergents** :
1. `frontend/js/app.js` → `applyPreset()` (valeurs UI réelles).
2. `backend/models.py` → `PRESET_VALUES` (Pydantic, **jamais exécuté**).
3. `backend/tempo_quantizer.py` → `PRESETS` + `backend/config.yaml` → `quantization.levels`.

Aucune n'est autoritaire sur le chemin réel (Flask lit le form). Toute correction future
risque d'atterrir dans la mauvaise source → régressions garanties.

---

## 7. Réponses directes à vos 2 questions

**Q1 — Des étapes écrasent-elles encore le travail précédent / échecs silencieux ?**
Oui, mais surtout par **contournement**, pas par écrasement :
- Le choix de quantification (light) est **silencieusement ignoré** (§3.1).
- L'`offset_threshold` est **silencieusement ignoré** (typo, §3.2).
- La dynamique P5 est **calculée puis jetée** (§3.3).
- La pédale est **perdue** sur le chemin Transkun/classique (§5).
- Les warnings existent mais **ne remontent pas activement** à l'UI (§3.4).
Le quantizer lui-même n'écrase plus les timings bruts (bon point, §4).

**Q2 — Erreurs architecturales / meilleure façon de faire ?**
La faille structurelle est **un lanceur qui pointe sur l'ancienne stack Flask** pendant que
tous les fixes V5 sont écrits dans la stack FastAPI/Pydantic morte, plus **3 sources de
vérité pour les presets**. Tant que ce n'est pas unifié, chaque « correctif » a une chance
sur deux d'atterrir dans du code non exécuté — d'où votre « limite » impossible à percer.

---

## 8. Correctifs recommandés (par impact, sans refonte lourde)

| # | Priorité | Action | Fichiers |
|---|----------|--------|----------|
| 1 | 🔴 | **Choisir UN point d'entrée.** Recommandé : basculer le lanceur sur FastAPI (`uvicorn fastapi_app:app`) pour activer `validate_options()` + `apply_preset()` déjà écrits. Sinon, rapatrier `apply_preset` dans `app.py`. | `AudioScore.vbs`, `app.py`/`fastapi_app.py` |
| 2 | 🔴 | **Corriger la sémantique « sensibilité » à UN seul endroit** : `onset = clamp(0.65 − 0.5×sensibilité, 0.05, 0.5)`, et relabelliser le slider (ou l'assumer comme « seuil de détection : bas = plus de notes »). | `app.js` **ou** entrée serveur |
| 3 | 🔴 | **Aligner le nom du champ** `quantization` ↔ `quantization_level` et **exposer le niveau `classique`** dans l'UI ; défaut classique = `light`/`classique` + rubato. | `app.js:469`, `app.py:316` |
| 4 | 🟠 | **Preset Classique** : slider onset ≈ 0.20–0.25 (pour les modèles à seuil), pas 0.85. | `app.js:273` |
| 5 | 🟠 | **Lire la pédale de Transkun** (CC64 via `midi_data.instruments[*].control_changes`) au lieu de renvoyer `[]`. | `transcriber.py:629` |
| 6 | 🟠 | **Corriger la faute** `offset_threshod` → `offset_threshold` et décider du découplage (offset fixe 0.3 recommandé). | `transcriber.py:895` |
| 7 | 🟡 | **Appliquer réellement** la dynamique max/médiane (P5) au lieu de la logger ; unifier la vélocité en 0-127 une seule fois. | `transcriber.py:1453-1467` |
| 8 | 🟡 | **Remonter les warnings à l'UI en mode normal** (bandeau : méthode tempo, quantizer, harmonie OK/échec, pédale OK/échec). | `app.py`, `app.js` |
| 9 | 🟡 | **Une seule source de vérité pour les presets** (un module partagé), consommée par l'UI et le backend. | `models.py` ↔ `tempo_quantizer.py` ↔ `app.js` |
| 10 | 🟢 | Aligner le commentaire pédale/quantif avec le code réel. | `transcriber.py:1391` |

**Validation :** rejouer la Mazurka après #1→#4 et vérifier dans `server.log` que
`onset` réellement appliqué est bas, que le quantizer reçoit `light`/`classique`, et que la
pédale est non vide. Idéalement, brancher le `regression_harness.py` (déjà présent) comme
filet.

---
*Audit statique — basé sur la lecture du code de la branche master, sans exécution runtime.*
