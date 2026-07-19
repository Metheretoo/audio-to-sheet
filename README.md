# AudioScore — Transcription Audio → Partition Piano

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
cd audio-to-sheet/backend

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

| Mode | Transcripteur | Quantification | Filtrage harmonique | Sensibilité | Usage recommandé |
|------|---------------|----------------|---------------------|-------------|------------------|
| **Rapide** | Piano Transcription | Légère (1/32) | Désactivé | Bas (0.20) | Aperçu immédiat sur fichier piano propre |
| **Équilibré** (recommandé) | Piano Transcription | Standard (1/16) | Désactivé | Moyen (0.50) | Majority des morceaux (Pop, YouTube, etc.) |
| **Classique** | Transkun | Légère (1/32) | **transkun-chord** | Moyenne (0.50) | Musique classique (Chopin, Debussy...) |
| **Studio** | Piano Transcription HD | Standard (1/16) | Classique | Moyenne (0.50) | Jeu expressif, arpèges rapides |
| **Jazz** | Piano Transcription | Forte (1/8) | Désactivé | Haut (0.70) | Morceaux swing ou rubato |
| **Precision** | Transkun | Forte (1/8) | **transkun-chord** | Élevée (0.85) | Partitions classiques complexes — supprime les notes parasites dans les accords |

> 💡 Pour une mazurka Chopin avec beaucoup de notes en trop, utilisez le preset **Precision** + filtrage **transkun-chord**.

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

#### Séparation des mains
- Option activée par défaut
- Sépare automatiquement main gauche / main droite

#### Analyse musicale
- **Détection automatique du tempo** : BPM détecté par analyse audio
- **Détection automatique de la tonalité** : Clé musicale détectée (armure)

### 5. Paramètres manuels (optionnels)

| Paramètre | Description |
|-----------|-------------|
| Tempo (manuel) | Surcharger le tempo détecté (40-300 BPM) |
| Mesure | 4/4, 3/4, 2/4 ou 6/8 |
| Tonalité/Armure | Surcharger la tonalité détectée (13 options) |
| Sensibilité de détection | Ajuste la sensibilité (0.10-0.90). Plus c'est haut, plus la détection est stricte (moins de notes) |
| Sensibilité de quantification | Ajuste la précision de la quantification (0.00-1.00). Plus c'est haut, plus les notes sont alignées sur la grille |

### 6. Transcription
- Cliquez **Transcrire** → l'IA analyse le fichier localement (1-3 min)
- La progression est affichée en temps réel

### 7. Éditer la partition

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

### 8. Lire la partition
- Cliquez **▶ Lire** ou appuyez sur **Espace** pour lancer la lecture audio
- Les notes jouées se surlignent en or en temps réel
- La barre de progression avance et affiche le temps écoulé
- Cliquez sur la barre pour vous déplacer dans le morceau
- Appuyez sur **Échap** pour arrêter la lecture
- Moteur audio : **Son MIDI** (synthétiseur) ou **Piano concert** (SoundFont)

### 9. Exporter
| Format | Méthode | Description |
|--------|---------|-------------|
| **PDF** | 📄 PDF | Fenêtre d'impression du navigateur → "Enregistrer en PDF" |
| **MIDI** | 🎵 MIDI | Fichier `partition_piano.mid` téléchargé |
| **MusicXML** | Disponible | Fichier `.xml` au format MusicXML 3.0 |

---

## 📁 Structure du projet

```
audio-to-sheet/
├── backend/
│   ├── app.py                 ← Serveur Flask (API REST)
│   ├── transcriber.py         ← Pipeline de transcription complet
│   ├── harmonic_filter.py     ← Filtrage harmonique (suppression notes fantômes)
│   ├── midi_parser.py         ← Analyse MIDI (notes, header, tempo)
│   ├── quantizer.py           ← Quantization adaptative
│   ├── tonality_detector.py   ← Détection tonalité & tempo
│   ├── midi_exporter.py       ← Export MIDI Type 0
│   ├── score_builder.py       ← Génération MusicXML 3.0
│   ├── voice_engine.py        ← Détection main gauche/droite
│   └── requirements.txt       ← Dépendances Python
├── frontend/
│   ├── index.html             ← Interface principale
│   ├── favicon.ico
│   ├── css/
│   │   └── style.css          ← Design dark mode
│   └── js/
│       ├── app.js             ← Logique principale + lecteur audio
│       ├── renderer.js        ← Moteur VexFlow (rendu SVG)
│       ├── editor.js          ← Éditeur interactif
│       └── lib/               ← Bibliothèques tierces (VexFlow, etc.)
├── v3-specs/                  ← Spécifications V3
│   ├── README.md              ← Guide principal V3
│   ├── ARCHITECTURE.md        ← Architecture du système
│   ├── PROGRESS.md            ← Suivi d'avancement
│   ├── phases/                ← Phases d'implémentation
│   └── references/            ← Documentation de référence
├── uploads/                   ← Fichiers temporaires (auto-nettoyés)
├── outputs/                   ← Fichiers MIDI/XML exportés
├── run_prod.bat               ← Lanceur Windows
├── TODO.txt                   ← Liste des tâches
└── README.md                  ← Ce fichier
```

---

## 🔧 Dépendances (toutes open source / gratuites)

| Bibliothèque | Rôle | Licence |
|---|---|---|
| **Piano Transcription** | Transcription piano haute qualité | — |
| **Demucs** | Séparation audio (isolation piano) | MIT |
| **Flask** | Serveur web local | BSD |
| **mido** | Lecture/écriture MIDI | MIT |
| **pretty_midi** | Manipulation MIDI avancée | MIT |
| **librosa** | Traitement audio | ISC |
| **soundfile** | Lecture/écriture fichiers audio | — |
| **numpy** | Calcul numérique | BSD |
| **scipy** | Traitement du signal | BSD |
| **onnxruntime** | Inférence modèle IA | MIT |
| **VexFlow** | Rendu de partition en SVG | MIT |
| **Web Audio API** | Synthèse sonore locale (intégrée au navigateur) | — |

> **Aucun nouveau package n'est nécessaire** pour le filtrage harmonique. Le module `harmonic_filter.py` utilise uniquement `numpy` (déjà dans les dépendances).

---

## 🏗️ Architecture V3

Le projet V3 est organisé en phases modulaires :

| Phase | Module | Description | Statut |
|-------|--------|-------------|--------|
| 1 | `midi_parser.py` | Analyse MIDI brute | ✅ Complet |
| 2 | `quantizer.py` | Quantization sur grille musicale | ✅ Complet |
| 3 | `tonality_detector.py` | Détection tonalité & tempo | ✅ Complet |
| 4 | `midi_exporter.py` | Export MIDI Type 0 | ✅ Complet |
| 5 | `score_builder.py` | Génération MusicXML 3.0 | ✅ Complet |
| 6 | `transcriber.py` | Orchestration pipeline complet | ✅ Complet |
| 7 | `app.py` | API REST Flask + SSE | ✅ Complet |
| 8 | `frontend/` | Interface utilisateur | 🔄 En cours |

> Voir `v3-specs/PROGRESS.md` pour le suivi détaillé de chaque phase.

---

## ❓ Problèmes fréquents

**Le fichier ne se transcrit pas**
→ Vérifiez le format (MP3, WAV, FLAC uniquement). Si le fichier est corrompu, essayez un autre.

**Le serveur ne démarre pas**
→ Vérifiez que le port 5000 n'est pas déjà utilisé : `netstat -ano | findstr :5000`

**"VexFlow introuvable"**
→ Vérifiez votre connexion et relancez run_prod.bat (il retéléchargera VexFlow).

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

---

## 📄 Licence

Ce projet est distribué en open source. Chaque bibliothèque conserve sa licence respective (voir tableau ci-dessus).

---

## 🤝 Contribution

Les phases V3 sont documentées dans le dossier `v3-specs/phases/`. Chaque phase est autonome et peut être implémentée indépendamment.

Pour signaler un bug ou proposer une amélioration, veuillez ouvrir une issue sur le dépôt.