# Audio2Score — Transcription Audio → Partition Piano

Application locale et open source pour convertir un fichier audio (MP3, WAV, FLAC) en partition de piano (clé de Sol + clé de Fa), avec édition interactive et lecture locale.

---

## ✅ Prérequis

- **Python 3.9 ou supérieur** — [télécharger](https://python.org)
- **Connexion Internet** uniquement pour la **première installation** (dépendances Python)
- **Espace disque** : ~5-10 Go (modèles IA + dépendances)

> ⚠️ Si Python n'est pas dans le PATH Windows, cochez « Add Python to PATH » lors de l'installation.

---

## 🚀 Démarrage

### Méthode 1 : Lanceur automatique

Double-cliquez sur **`Lanceur test.bat`** (à la racine du projet `audio-to-sheet/`).

Le script va automatiquement :
1. Vérifier Python
2. Activer l'environnement virtuel (`venv/`)
3. Vérifier et installer les dépendances
4. Démarrer le serveur local sur **http://localhost:5000**

> 💡 La première exécution peut prendre **5 à 15 minutes** le temps que les dépendances soient installées.

### Méthode 2 : Installation manuelle

```bash
# Se placer dans le dossier backend
cd backend

# Créer et activer l'environnement virtuel
python -m venv venv
venv\Scripts\activate

# Installer les dépendances
pip install -r requirements.txt

# Démarrer le serveur
python app.py
```

---

## 🎹 Utilisation

### 1. Uploader un fichier

- Glissez-déposez un fichier MP3, WAV ou FLAC, ou cliquez "Choisir un fichier"
- Taille maximale : **50 MB**

### 2. Modes de qualité (presets)

L'application propose 5 presets configurés automatiquement. Voici leur configuration **réelle** telle qu'implémentée dans `frontend/js/app.js` (fonction `applyPreset`) :

| Mode | Transcripteur | Demucs | Quantification | Force d'alignement | Seuil de détection | Rubato | Triolets | Filtrage harmonique | Usage recommandé |
|------|---------------|--------|----------------|-------------------|-------------|--------|----------|---------------------|------------------|
| **Rapide** | Basic Pitch | ❌ false | Light | 0.5 | 1.0 (max) | ❌ | ❌ | off | Aperçu immédiat sur fichier contenant uniquement du piano |
| **Équilibré** ✅ (recommandé, actif par défaut) | Transkun | ❌ false | Standard | 0.5 | 0.55 | ❌ | ❌ | off | Majority des morceaux (Pop, YouTube, etc.) |
| **Precision** | Piano Transcription | ❌ false | Heavy | 0.90 | 0.33 (sensible) | ✅ | ✅ | transkun-chord | Partitions classiques complexes (Chopin, Debussy...) avec minimum de notes en trop |
| **Classique** | Piano Transcription | ❌ false | Light | 1.0 | 0.20 (ultra sensible) + Seuil adaptatif ✅ | ✅ | ✅ | classical | Musique classique expressif, arpèges, notes douces — **optimisé pour capter les basses** |
| **Jazz** | Piano Transcription | ❌ false | Heavy | 0.5 | 0.67 | ❌ | ❌ | off | Morceaux swing ou à rubato, simplification pour la lecture |
| **Studio** | Piano Transcription | ✅ true | Standard | 0.5 | 0.50 | ❌ | ❌ | off | Enregistrement studio piano solo — **nouveau mode par défaut** |

> 💡 **Force d'alignement** : 0.0 = Rythme libre (brut) → 1.0 = Alignement maximal sur le preset de quantification. Pour une mazurka Chopin avec beaucoup de notes en trop, utilisez le preset **Precision** + filtrage **transkun-chord**.

### 3. Filtrage harmonique

Le filtrage harmonique supprime les **"notes fantômes"** causées par la pédale forte du piano :

- **Comment ça marche ?** Une note grave jouée avec pédale crée des harmoniques à l'octave (+12 demi-tons), quinte (+7), et quarte (+5). Ces harmoniques sont détectés comme des notes par l'IA et apparaissent en trop dans la partition.
- **Le filtrage les supprime** en se basant sur la vélocité, la simultanéité temporelle, la durée et le registre des notes.

| Niveau | Description |
|--------|-------------|
| **Désactivé** | Pas de filtrage (par défaut) |
| **Basique** | Filtre simple (octave + quinte) |
| **Classique** | Recommandé pour Chopin, Debussy, musique classique |
| **Agressif** | Pour partitions très complexes (mazurkas, nocturnes) |
| **Anti-pédale** | Spécialisé harmoniques de pédale — le plus efficace pour notes en trop |
| **transkun-chord** (NOUVEAU) | **Recommandé pour classique** : Transkun + filtre contextuel par accord — supprime les notes parasites dans les accords |

#### Nouveau : Filtre "transkun-chord"

Le filtre **transkun-chord** combine deux étapes :
1. **Filtrage Transkun** : supprime les harmoniques de pédale (seuils calibrés pour Transkun v2)
2. **Filtre contextuel par accord** : identifie les accords légitimes (majeurs, mineurs, septièmes, diminués) et supprime les notes qui n'appartiennent à AUCUN accord valide

**Exemple** : Accord C majeur (C4-E4-G4) détecté + C#4 à vélocité faible → C#4 supprimé car n'appartient pas à C majeur.

### 4. Options avancées

#### Transcripteur

- **Piano Transcription** (recommandé) : Entraîné spécifiquement sur le piano, meilleur pour accords complexes
- **Transkun** (expressivité maximale) : Modèle Transformer SOTA avec haute précision expressive, idéal pour partitions classiques complexes
- **Basic Pitch** (rapide) : Modèle de Spotify, rapide et léger, idéal pour un aperçu immédiat
- **hFT-Transformer** (Sony) : Modèle de transcription audio à base de Transformer, performant sur la détection de notes et de pédales

#### Isolation du piano (Demucs)

- Sépare les instruments et conserve principalement la piste piano
- Désactivez uniquement si votre fichier est un enregistrement studio **exclusivement** piano

#### Nettoyage MIDI

- **Supprimer les notes très courtes** : Filtre les notes parasites (ghost notes)
  - Durée minimale par défaut : 50ms
- **Fusionner les notes répétées proches** : Lisse le rendu pour notes tenues

#### Quantification

| Option | Granularité | Description |
|--------|-------------|-------------|
| Aucune | Brut | Pas d'arrondi (injouable, debug uniquement) |
| Légère | 1/32 | Garde le jeu "humain" (classique, jazz) |
| **Standard** | **1/16** | **Meilleur compromis lisibilité (Pop/Variété)** |
| Forte | 1/8 | Simplification maximale (débutants) |

#### Options expressives

- **Rubato** : Préserve l'expressivité (arpèges, notes inégales)
- **Triolets** : Active la détection et l'écriture des triolets
- **Smooth** (rythme simplifié) : Double le tempo et simplifie le rythme (noires/croches uniquement)

#### Noms des notes en français

- **Activer** : Affiche les noms des notes (Do, Ré, Mi, Fa, Sol, La, Si) au-dessus des portées
- Les noms incluent les altérations (dièses ♯ et bémols b)
- Par défaut : désactivé (cliquer sur l'option pour l'activer)

#### Séparation des mains

- Option activée par défaut
- Sépare automatiquement main gauche / main droite

#### Analyse musicale

- **Détection automatique du tempo** : BPM détecté par analyse audio
- **Détection automatique de la mesure** : 4/4, 3/4, 2/4, 3/8, 6/8, 9/8, 12/8
- **Détection automatique de la tonalité** : Clé musicale détectée (armure)

### 5. Affichage interactif (post-traitement)

> ℹ️ **Les accords et la pédale sont appliqués en post-traitement** sur la page de modification de la partition, directement dans votre navigateur. Vous pouvez donc afficher/masquer ces éléments **à tout moment** sans avoir besoin de re-transcrire.

#### Accords jazz

- ☑️ **Afficher les accords** : Affiche les symboles d'accords au-dessus de la portée de main droite (ex: C, G7, Am, Dm7b5)
- Désactivé par défaut

#### Pédale du sustain

- ☑️ **Afficher la pédale** : Affiche les indications de pédale (S, T, pedal, lift) entre les deux portées
- Activé par défaut

#### Noms des notes les plus aigües

- ☑️ **Noms des notes** : Affiche le nom de la note la plus haute de chaque accord (ex: "Si" au-dessus de l'accord)
- Désactivé par défaut

### 6. Paramètres manuels (optionnels)

| Paramètre | Description |
|-----------|-------------|
| Tempo (manuel) | Surcharger le tempo détecté (40-300 BPM) |
| Mesure | 4/4, 3/4, 2/4, 3/8, 6/8, 9/8, 12/8 |
| Tonalité/Armure | Surcharger la tonalité détectée (13 options) |
| Seuil de détection | Ajuste la sensibilité (0.20-0.85). Plus c'est bas, plus la détection est sensible (plus de notes, y compris les notes douces). Par défaut : 0.55 (Équilibré) |
| 🎹 Seuil adaptatif basses/aigus | **Activé par défaut**. Réduit le seuil de détection des notes graves (main gauche, pitch < 55) pour capter les attaques douces. Les aigus conservent le seuil utilisateur. |
| Seuil basses (main gauche) | Ajuste le seuil minimum pour les graves (0.05-0.85, défaut 0.15). Plus c'est bas, plus les basses douces sont détectées. |
| Protection basse (main gauche) | Pondération de la vélocité minimale pour les notes graves (0.00-1.00). Les notes graves < 0.35 sont forcées à 0.35 pour survivre au filtrage harmonique. |
| Force d'alignement | Ajuste l'intensité de l'alignement rythmique (0.00-1.00). 0.0 = Rythme libre (brut) → 1.0 = Alignement maximal sur le preset de quantification sélectionné |

### 7. Transcription

- Cliquez **Transcrire** → l'IA analyse le fichier localement (1-3 min)
- La progression est affichée en temps réel via SSE (Server-Sent Events)
- Pipeline : Initialisation → Isolation Demucs → Transcription IA → Quantification → Construction partition → Export fichiers

### 8. Éditer la partition

#### Sélection

| Action | Raccourci |
|--------|-----------|
| Note suivante | → |
| Note précédente | ← |
| Monter d'un demi-ton | ↑ ♯ / ↑ |
| Descendre d'un demi-ton | ↓ ♭ / ↓ |

#### Durée

| Note | Raccourci | Valeur |
|------|-----------|--------|
| Ronde | W | 1.0 |
| Blanche | H | 0.5 |
| Noire | Q | 0.25 |
| Croche | 8 | 0.125 |
| Double croche | 6 | 0.0625 |
| Pointée | . | +50% durée |

#### Édition

| Action | Bouton | Raccourci |
|--------|--------|-----------|
| Assigner main droite | ✋ Droite | — |
| Assigner main gauche | 🤚 Gauche | — |
| Supprimer | 🗑 | Suppr |
| Annuler | ↩ Annuler | Ctrl+Z |
| Rétablir | ↪ Rétablir | Ctrl+Y / Ctrl+Shift+Z |
| Désélectionner | — | Échap |
| Insérer note | ➕ Note | — |
| Insérer silence | ➕ Silence | — |

### 9. Lire la partition

- Cliquez **▶ Lire** ou appuyez sur **Espace** pour lancer la lecture audio
- Les notes jouées se surlignent en or en temps réel
- La barre de progression avance et affiche le temps écoulé
- Cliquez sur la barre pour vous déplacer dans le morceau
- Appuyez sur **Échap** pour arrêter la lecture
- Moteur audio : **Son MIDI** (synthétiseur) ou **Piano concert** (SoundFont)

### 10. Transposer

- **Monter/Descendre** d'un demi-ton (boutons ↑ / ↓)
- **Changer l'enharmonie** (♯/♭) : convertit les dièses en bémols et vice-versa

### 11. Exporter

| Format | Méthode | Description |
|--------|---------|-------------|
| **PDF** | 📄 PDF | Fenêtre d'impression du navigateur → "Enregistrer en PDF" |
| **MIDI** | 🎵 MIDI | Fichier `partition_piano.mid` téléchargé |
| **MusicXML** | 🎼 XML | Fichier `.xml` au format MusicXML (compatible MuseScore, Finale...) |

---

## 📁 Structure du projet

```
audio-to-sheet/
├── backend/
│   ├── app.py                    ← Serveur Flask (API REST + SSE)
│   ├── transcriber.py            ← Pipeline de transcription complet
│   ├── harmonic_filter.py        ← Filtrage harmonique (notes fantômes)
│   ├── harmonic_analyzer.py      ← Analyse des harmoniques
│   ├── midi_parser.py            ← Analyse et génération MIDI
│   ├── musicxml_exporter.py      ← Export MusicXML 3.0
│   ├── tonality_detector.py      ← Détection tonalité & tempo
│   ├── tonality_detector - Copie.py ← Variante de détection tonalité
│   ├── quantizer.py              ← Quantification adaptative
│   ├── tempo_quantizer.py        ← Quantification du tempo
│   ├── voice_engine.py           ← Détection main gauche/droite
│   ├── note_filter.py            ← Filtrage et nettoyage de notes
│   ├── ornament_detector.py      ← Détection des ornements musicaux
│   ├── rhythm_simplifier.py      ← Simplification rythmique
│   ├── tempo_map.py              ← Cartographie du tempo
│   ├── piano_roll.py             ← Génération du piano roll
│   ├── ensemble_voter.py         ← Agrégation multi-modèles
│   ├── score_builder.py          ← Construction de la partition
│   ├── score_data.py             ← Structures de données du score
│   ├── verovio_export.py         ← Export pour rendu Verovio
│   ├── _fix_harmonic.py          ← Correctif filtrage harmonique
│   ├── verify_prerequisites.py   ← Vérification des prérequis
│   ├── run_hft.py                ← Exécution hFT-Transformer
│   ├── requirements.txt          ← Dépendances Python
│   ├── setup.py                  ← Installation
│   ├── setup_gpu.bat             ← Setup GPU Windows
│   ├── hft_transformer/          ← Modèle hFT-Transformer (Sony)
│   │   ├── README.md
│   │   ├── requirements.txt
│   │   ├── model/
│   │   ├── training/
│   │   ├── evaluation/
│   │   └── corpus/
│   └── legacy/                   ← Code legacy (ancien code)
│       ├── pipeline.py
│       ├── server.py
│       ├── patch_*.py
│       └── old/
│           ├── config.py
│           ├── device_manager.py
│           ├── exporters.py
│           └── ...
├── frontend/
│   ├── index.html                ← Interface principale
│   ├── favicon.ico
│   ├── css/
│   │   └── style.css             ← Design dark mode premium
│   └── js/
│       ├── app.js                ← Logique principale + lecteur audio
│       ├── renderer.js           ← Moteur VexFlow (rendu SVG)
│       ├── editor.js             ← Éditeur interactif
│       ├── ScorePlayer.js        ← Lecteur audio Score
│       └── lib/
│           ├── vexflow.js        ← Bibliothèque VexFlow
│           ├── soundfont-player.min.js
│           └── acoustic_grand_piano-mp3.js
├── uploads/                      ← Fichiers temporaires uploadés (auto-nettoyés)
├── outputs/                      ← Fichiers MIDI/XML exportés
├── references/                   ← Références musicales
├── docs/
│   └── presets-musique-classique.md  ← Documentation presets classiques
├── config.yaml                   ← Configuration globale
├── proxy.py                      ← Proxy HTTP
├── Lanceur test.bat              ← Lanceur automatique Windows
├── arreter_serveur.bat           ← Arrêt du serveur
├── AudioScore.vbs                ├── Lanceur VBScript
├── AudioScore_private.vbs        ├── Lanceur VBScript privé
└── README.md                     ← Ce fichier
```

---

## 🔧 Dépendances (toutes open source / gratuites)

| Bibliothèque | Rôle | Licence | Statut |
|---|---|---|---|
| **Piano Transcription** | Transcription piano haute qualité | — | Installé via pip (git) |
| **Transkun** | Transcripteur Transformer SOTA | — | Installé via pip |
| **hFT-Transformer** (Sony) | Transcription audio Transformer | Apache 2.0 | ⚠️ Installation manuelle requise |
| **Demucs** | Séparation audio (isolation piano) | MIT | Installé via pip |
| **Flask** | Serveur web local | BSD | Installé via pip |
| **Flask-CORS** | Gestion des CORS | MIT | Installé via pip |
| **mido** | Lecture/écriture MIDI | MIT | Installé via pip |
| **pretty_midi** | Manipulation MIDI avancée | MIT | Installé via pip |
| **librosa** | Traitement audio | ISC | Installé via pip |
| **soundfile** | Lecture/écriture fichiers audio | — | Installé via pip |
| **numpy** | Calcul numérique | BSD | Installé via pip |
| **scipy** | Traitement du signal | BSD | Installé via pip |
| **madmom** | Beat tracking avancé | — | Installé via pip |
| **pydantic** | Validation de données | MIT | Installé via pip |
| **fastapi** | API framework (migration) | MIT | Installé via pip |
| **uvicorn** | ASGI server | BSD | Installé via pip |
| **onnxruntime** | Inférence modèle IA | MIT | Installé via pip |
| **VexFlow** | Rendu de partition en SVG | MIT | Inclus dans frontend/ |
| **Web Audio API** | Synthèse sonore locale | — | Intégrée au navigateur |
| **music21** | Export MusicXML | GPL | ⚠️ Optionnel (commenté dans requirements.txt) |

> **Aucun nouveau package n'est nécessaire** pour le filtrage harmonique. Le module `harmonic_filter.py` utilise uniquement `numpy` (déjà dans les dépendances).
>
> ⚠️ **hFT-Transformer** : Ce modèle doit être cloné manuellement dans le dossier `backend/hft_transformer/` depuis https://github.com/qiuqiangkong/hft-transformer. Il n'est pas installé via pip.

---

## 🏗️ Architecture

### Backend (Flask + Pydantic)

| Module | Responsabilité |
|--------|----------------|
| `app.py` | Serveur Flask, API REST, SSE streaming, validation Pydantic |
| `transcriber.py` | Pipeline de transcription orchestré |
| `harmonic_filter.py` | Filtrage harmonique (octave, quinte, harmoniques de pédale) |
| `harmonic_analyzer.py` | Analyse des harmoniques |
| `midi_parser.py` | Analyse et génération MIDI |
| `musicxml_exporter.py` | Export MusicXML |
| `tonality_detector.py` | Détection tonalité et tempo |
| `quantizer.py` | Quantification sur grille musicale |
| `tempo_quantizer.py` | Quantification du tempo |
| `voice_engine.py` | Séparation main gauche/droite |
| `note_filter.py` | Filtrage et nettoyage des notes |
| `ornament_detector.py` | Détection des ornements musicaux |
| `rhythm_simplifier.py` | Simplification rythmique |
| `tempo_map.py` | Cartographie du tempo |
| `piano_roll.py` | Génération du piano roll |
| `ensemble_voter.py` | Agrégation multi-modèles |
| `score_builder.py` | Construction de la partition |
| `score_data.py` | Structures de données du score |
| `verovio_export.py` | Export pour rendu Verovio |
| `verify_prerequisites.py` | Vérification des prérequis |
| `run_hft.py` | Exécution hFT-Transformer |

### Frontend

| Fichier | Responsabilité |
|---------|----------------|
| `index.html` | Interface principale |
| `css/style.css` | Design dark mode premium (glassmorphism, violet/gold) |
| `js/app.js` | Logique principale, communication API, gestion des presets |
| `js/renderer.js` | Moteur de rendu VexFlow (SVG) |
| `js/editor.js` | Éditeur interactif de partition |
| `js/ScorePlayer.js` | Lecteur audio avec synchronisation |

### Pipeline de transcription

```
Upload audio → Demucs (isolation) → Transcripteur IA → Quantification
    → Harmonic filter → Voice separation → MIDI/MusicXML export
```

---

## ❓ Problèmes fréquents

**Le fichier ne se transcrit pas**
→ Vérifiez le format (MP3, WAV, FLAC uniquement). Si le fichier est corrompu, essayez un autre.

**Le serveur ne démarre pas**
→ Vérifiez que le port 5000 n'est pas déjà utilisé : `netstat -ano | findstr :5000`

**"VexFlow introuvable"**
→ Vérifiez votre connexion et relancez Lanceur test.bat (il retéléchargera VexFlow).

**La transcription est trop dense / trop sparse**
→ Ajustez le curseur "Sensibilité de détection" (bas = moins de notes, haut = plus de notes).
→ Changez le mode de quantification (Légère = plus de détails, Forte = plus simple).
→ Pour classique : utilisez le preset **Classique** ou **Precision** avec filtrage **transkun-chord**.

**Pas de son lors de la lecture**
→ Cliquez d'abord une fois dans la page (les navigateurs bloquent l'audio tant qu'il n'y a pas d'interaction utilisateur).
→ Essayez l'autre moteur audio (Son MIDI ou Piano concert).

**Installation longue ou bloquée**
→ Les modèles IA (surtout Demucs et Piano Transcription) peuvent prendre du temps au premier téléchargement. Soyez patient.
→ Si vous avez des problèmes de dépendances, vérifiez que vous avez un compilateur C++ installé pour Windows.

**GPU non détecté**
→ Pour NVIDIA CUDA : installez PyTorch avec CUDA support
→ Pour Intel ARC A770 : `pip install torch --index-url https://download.pytorch.org/whl/xpu`

---

## 📄 Licence

Ce projet est distribué en open source. Chaque bibliothèque conserve sa licence respective (voir tableau ci-dessus).

---

## 🤝 Contribution

Pour signaler un bug ou proposer une amélioration, veuillez ouvrir une issue sur le dépôt.