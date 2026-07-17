"# Phase 4 — madmom : validation d'installation & activation

## TL;DR

**Bonne nouvelle** : `madmom` est **déjà** dans `requirements.txt` (>=0.16) et
**déjà branché** dans `tempo_map.py::build_tempo_map()` avec un fallback
proprement géré vers librosa puis IOI. Il n'y a **rien à coder** — juste à
s'assurer que l'installation Windows fonctionne et à valider que madmom est bien
utilisé au runtime.

---

## 1. Vérifier que madmom est installé

Depuis la racine du projet :

```bash
venv\Scripts\python.exe -c \"import madmom; print('madmom', madmom.__version__)\"
```

**Résultat attendu** : `madmom 0.16.x`

**Si ImportError** : voir §2 pour installer.

---

## 2. Installation Windows (les pièges)

madmom pose deux problèmes récurrents sur Windows :

### Piège 1 : Cython requis avant madmom
```bash
venv\Scripts\pip install cython==0.29.36
venv\Scripts\pip install madmom
```

### Piège 2 : numpy >= 1.24 casse madmom
madmom 0.16 utilise `np.float`, `np.int`, etc. supprimés en numpy 1.24+.
Le code `tempo_map.py:184-193` **monkey-patch déjà** ces attributs avant l'import madmom → OK.

Mais si tu es sur numpy 2.x, ça peut planter plus profond. Solution :
```bash
venv\Scripts\pip install \"numpy>=1.23,<1.27\"
```

### Piège 3 : ffmpeg pour la lecture MP3
madmom lit les MP3 via ffmpeg. Sur Windows :
```bash
# Via conda (recommandé)
conda install -c conda-forge ffmpeg
# OU télécharger ffmpeg.exe et l'ajouter au PATH
```

Sans ffmpeg, madmom fonctionne quand même pour les WAV/FLAC.

---

## 3. Vérifier que madmom est bien utilisé au runtime

Après une transcription, dans `backend/server.log` :

```
[TempoMap] OK madmom -- BPM=138.2, mesure=(3, 4), beats=487
```

**Si tu vois à la place** :
```
[TempoMap] madmom non disponible, repli sur librosa avance
[TempoMap] OK librosa_advanced -- BPM=94.0, mesure=(4, 4), beats=234
```
→ madmom n'est pas installé correctement. Retour §2.

**Si tu vois** :
```
[TempoMap] madmom a echoue (AttributeError: module 'numpy' has no attribute 'float')
```
→ le monkey-patch n'a pas suffi. Downgrade numpy (§2 piège 2).

---

## 4. Downbeat tracking — vérifier `estimated_meter`

`tempo_map.py::_detect_downbeats_madmom` (ligne 347) utilise
`RNNDownBeatProcessor + DBNDownBeatTrackingProcessor` pour trouver les temps
forts et déduire la mesure (3/4 vs 4/4).

Sur la Mazurka Op. 68 n°3, tu dois voir dans les logs :
```
[TempoMap] downbeats détectés : 60 downbeats, meter=(3, 4)
[TempoMap] OK madmom -- BPM=138.2, mesure=(3, 4), beats=487
```

Si `mesure=(4, 4)` malgré une pièce en 3/4, deux causes possibles :
- Enregistrement démarre à contretemps → augmenter la fenêtre d'analyse
- Pédale masque les downbeats → réduire par un pré-Demucs

---

## 5. Modèles pré-téléchargés

madmom télécharge ses modèles RNN au premier appel. Sur une machine sans
Internet, il faut **pré-télécharger** :

```bash
# Récupère et cache les modèles (env. 50 MB)
venv\Scripts\python.exe -c \"
from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor
RNNBeatProcessor()
DBNBeatTrackingProcessor(fps=100)
RNNDownBeatProcessor()
DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
print('Modèles madmom téléchargés OK')
\"
```

Les modèles sont stockés dans `venv\Lib\site-packages\madmom\models\` — ils peuvent
être copiés sur une machine hors ligne.

---

## 6. Ordre des priorités madmom vs librosa

Actuellement dans `tempo_map.py:181-219` :

1. **madmom** (RNN + DBN) → BPM ± 1, downbeat ± 20ms
2. **librosa** (`onset_strength` + `beat_track`) → BPM ± 3, pas de downbeat
3. **IOI fallback** (median inter-onset) → BPM très approximatif

**Recommandation** : laisser l'ordre en l'état. Le fallback librosa est là pour
les cas où madmom refuse un fichier (rare) ou pour les tests unitaires sur
machines minimales.

---

## 7. Métrique de succès

Sur la Mazurka Op. 68 n°3 (audio de référence dans le repo) :

| Métrique | Sans madmom (librosa) | Avec madmom |
|---|---|---|
| BPM détecté | 94 ou 138 (aléatoire) | ~130-138 stable |
| Mesure détectée | 4/4 (faux) | 3/4 |
| Décalage LH/RH mesure 20 | ~1 temps | < 1 croche |
| Downbeat aligné à la mes. 1 | ❌ | ✅ |

Le gain sur le **downbeat tracking** est probablement le plus grand levier de
qualité de ce projet — sans downbeats fiables, le `score_builder` ne peut pas
mettre les barres de mesure au bon endroit, d'où toutes les cascades de bugs
que tu observais.

---

## 8. Aucun code à modifier — checklist finale

- [ ] `venv\Scripts\python.exe -c \"import madmom\"` fonctionne
- [ ] `venv\Scripts\python.exe -c \"import numpy; assert numpy.__version__ < '1.27'\"` OK
- [ ] `ffmpeg -version` renvoie une version (si tu utilises des MP3)
- [ ] Test à blanc du download des modèles (§5)
- [ ] Transcription d'un WAV court → log `[TempoMap] OK madmom`
- [ ] Transcription de la Mazurka → log `mesure=(3, 4)`

Si tout est vert, la Phase 4 est terminée sans écrire une ligne de code.

---

## 9. Ce que madmom ne fera PAS pour toi

- **Rubato extrême** (< 60 BPM avec accélération x2) : madmom se fait piéger
  → activer le check \"Rubato\" + preset \"classique\" du côté quantizer
- **Ornements** (grace notes) : madmom voit un beat parasite → ne rien faire,
  c'est `detect_ornaments()` qui doit s'en charger (Phase 6 du plan initial)
- **Changements de mesure au sein d'un morceau** (3/4 → 4/4) : madmom fixe la
  mesure globale ; c'est très rare mais à savoir

---

## 10. Fichier de test rapide (optionnel)

Créer `backend/_test_madmom.py` :

```python
\"\"\"Smoke test madmom — lance depuis la racine du projet.\"\"\"
import sys
sys.path.insert(0, 'backend')

import numpy as np
if not hasattr(np, 'float'):
    np.float = float
    np.int = int
    np.bool = np.bool_
    np.complex = complex
    np.object = object

from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

audio = 'uploads/example.wav'  # ← adapte le chemin

print(\"→ Beat tracking...\")
proc = DBNBeatTrackingProcessor(fps=100)
act = RNNBeatProcessor()(audio)
beats = proc(act)
print(f\"  {len(beats)} beats, BPM ≈ {60.0 / np.median(np.diff(beats)):.1f}\")

print(\"→ Downbeat tracking...\")
dproc = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
dact = RNNDownBeatProcessor()(audio)
downbeats = dproc(dact)
print(f\"  {len(downbeats)} downbeats, premières valeurs :
  {downbeats[:5]}\")

# La 2ème colonne indique la position dans la mesure (1 = downbeat).
# On peut en déduire beats_per_bar en comptant les valeurs entre deux `1`.
```

Exécution : `venv\Scripts\python.exe backend\_test_madmom.py`
"