# Dépendances — Librairies open source recommandées pour la V2

> Ce document liste toutes les nouvelles dépendances à introduire en V2,
> avec justification, mode d'installation et notes de compatibilité.

---

## Dépendances V2 à ajouter

### 1. `madmom` — Beat tracking & downbeat detection

| Propriété | Valeur |
|---|---|
| **Usage** | Phase 1 — `tempo_map.py` |
| **Licence** | BSD 3-Clause (open source) |
| **Lien** | https://github.com/CPJKU/madmom |
| **Version recommandée** | `>= 0.16.1` |

**Pourquoi madmom plutôt que librosa ?**
- Utilise un réseau de neurones récurrents (RNN) entraîné sur de la musique réelle
- Robuste aux variations de tempo (rubato, ritardando)
- Fournit des `beat_times` précis à la frame près (100 fps)
- Gère la détection des downbeats (temps forts) séparément des beats

**Installation** :
```bash
pip install madmom
# madmom requiert Cython — s'assurer que Cython est installé d'abord :
pip install cython
pip install madmom
```

**Note de compatibilité** :
- ⚠️ madmom ne supporte pas Python 3.12+ officiellement (utiliser Python 3.10 ou 3.11)
- ⚠️ Sur Windows, peut nécessiter Microsoft Visual C++ Build Tools pour compiler Cython
- Vérifier la version Python du venv : `python --version`
- Si madmom ne s'installe pas : utiliser le fallback `librosa_advanced` (Phase 1, `_build_with_librosa`)

**Code minimal de validation** :
```python
from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
proc = DBNBeatTrackingProcessor(fps=100)
act  = RNNBeatProcessor()('test.mp3')
beats = proc(act)
print(f"Beats détectés : {len(beats)} | BPM estimé : {60/np.mean(np.diff(beats)):.1f}")
```

---

### 2. `numpy` — Calculs numériques (déjà présent)

| Propriété | Valeur |
|---|---|
| **Usage** | Toutes les phases |
| **Version actuelle** | `>= 1.24` (dans requirements.txt) |
| **Action** | ✅ Aucune — déjà installé |

Nouveaux usages en V2 :
- `np.interp()` pour l'interpolation dans `TempoMap.seconds_to_beat()`
- `np.diff()` pour calculer les IOI (Inter-Onset Intervals)
- `np.median()` pour le BPM global robuste

---

### 3. `librosa` — Audio analysis (déjà présent, usage étendu)

| Propriété | Valeur |
|---|---|
| **Usage** | Phase 1 — fallback beat tracking |
| **Version actuelle** | `>= 0.10` (dans requirements.txt) |
| **Action** | ✅ Aucune — déjà installé, usage étendu |

Nouveaux usages en V2 (plus avancés que la V1) :
```python
# V1 (basique) :
tempo, beats = librosa.beat.beat_track(y=y, sr=sr)

# V2 (avancé) :
onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, start_bpm=80)
beat_times = librosa.frames_to_time(beat_frames, sr=sr)
```
L'utilisation de `onset_envelope` avec `aggregate=np.median` est plus robuste que la version par défaut.

---

### 4. `dataclasses` — Types structurés (standard library)

| Propriété | Valeur |
|---|---|
| **Usage** | `TempoMap`, `QuantizedNote`, `VoiceSplit` |
| **Installation** | ✅ Aucune — module standard Python 3.7+ |

Utilisé pour définir les types de données proprement :
```python
from dataclasses import dataclass, field

@dataclass
class TempoMap:
    beat_times: np.ndarray
    global_bpm: float
    ...
```

---

## Dépendances V1 conservées

| Librairie | Usage | Phase V2 |
|---|---|---|
| `flask >= 3.0` | Serveur web | Phase 4 (app.py) |
| `flask-cors` | CORS | Phase 4 (app.py) |
| `piano-transcription-inference` | Transcription notes | Phase 0 (inchangé) |
| `basic-pitch` | Transcription notes (fallback) | Phase 0 (inchangé) |
| `pretty_midi` | Manipulation MIDI | Phase 0 (inchangé) |
| `mido` | Export MIDI | Phase 4 (midi_parser) |
| `librosa` | Audio analysis | Phase 1 (étendu) |
| `soundfile` | Lecture audio | Phase 0 (inchangé) |
| `demucs` | Séparation instrumentale | Phase 0 (inchangé) |
| `requests` | Téléchargement modèles | Phase 0 (inchangé) |
| `torch` | Inférence IA | Phase 0 (inchangé) |

---

## `requirements.txt` — Version V2 complète

```txt
# ── Web backend ───────────────────────────────────────────────────────────────
flask>=3.0
flask-cors>=4.0
waitress>=3.0

# ── HTTP / utils ──────────────────────────────────────────────────────────────
requests>=2.31

# ── Audio / ML core ───────────────────────────────────────────────────────────
numpy>=1.24
scipy>=1.10
librosa>=0.10
soundfile>=0.12
mido>=1.3
pretty_midi>=0.2.10

# ── Beat tracking avancé (Phase 1 V2) ─────────────────────────────────────────
# Prérequis : pip install cython d'abord si madmom ne s'installe pas
madmom>=0.16

# ── Deep learning Intel / PyTorch stack ──────────────────────────────────────
torch==2.7.1+xpu
torchaudio==2.7.1+xpu
intel-extension-for-pytorch==2.7.1+xpu

# ── Piano transcription (CRITICAL) ───────────────────────────────────────────
piano-transcription-inference @ git+https://github.com/qiuqiangkong/piano_transcription_inference

# ── Audio separation (si activé dans options) ────────────────────────────────
demucs>=4.0

# ── Optional ONNX/OpenVINO (basic-pitch ou fallback) ─────────────────────────
onnxruntime-openvino>=1.17
```

---

## Procédure d'installation V2

```bash
# 1. Activer le venv existant
cd D:\IA\Antigravity\audio-to-sheet
.\venv\Scripts\activate

# 2. Installer Cython (prérequis madmom)
pip install cython

# 3. Installer madmom
pip install madmom

# 4. Valider l'installation
python -c "import madmom; print('madmom OK, version:', madmom.__version__)"

# 5. Valider le beat tracking
python backend/tempo_map.py "UNICORN ACADEMY THEME.mp3"
```

---

## Alternatives si madmom ne s'installe pas

| Alternative | Précision | Installation | Notes |
|---|---|---|---|
| `librosa` (avancé) | ⭐⭐⭐ | ✅ déjà installé | Fallback Phase 1 |
| `essentia` | ⭐⭐⭐⭐ | Complexe (C++) | Non recommandé sur Windows |
| `aubio` | ⭐⭐⭐ | `pip install aubio` | Bonne alternative à madmom |

Si `madmom` est impossible à installer, utiliser `aubio` comme alternative :
```bash
pip install aubio
```
Puis dans `tempo_map.py`, adapter `_build_with_madmom` pour utiliser `aubio.tempo`.

---

## Ce qu'on n'installe PAS (et pourquoi)

| Librairie | Raison de l'exclusion |
|---|---|
| `music21` | Trop lourd (>500MB), API complexe pour notre cas d'usage. Le `score_builder.py` custom suffit. Reconsidérer en V3 pour export MusicXML. |
| `pretty_midi` (pour score) | Utilisé uniquement pour lecture/écriture MIDI brut. La construction de partition passe par notre JSON custom. |
| `omnizart` | Excellent modèle de transcription mais dépendances conflictuelles avec `piano_transcription_inference`. À évaluer en V3. |
| `torch` (upgrade) | La version actuelle (2.7.1+xpu) est optimisée pour Intel. Ne pas changer sauf nécessité absolue. |
