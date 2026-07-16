# Phase 14 — Intégration Transkun (SOTA Piano Transcription)

## Objectif
Ajouter **Transkun** (Yujia Yan) comme 3ème moteur de transcription IA pour proposer un rendu hautement expressif (Transformers + Neural Semi-CRF), tout en conservant la modularité du pipeline V3 existant.

## Contexte
Le projet possède actuellement :
1. **Piano Transcription Inference (ByteDance)** (Par défaut, puissant, très bon sur la pédale)
2. **Basic Pitch (Spotify)** (Léger, rapide)
Transkun viendra se positionner comme l'alternative la plus avancée technologiquement pour capturer les moindres nuances de jeu (vélocité).

## Plan de mise en œuvre

### 1. Frontend
- Mettre à jour `frontend/index.html` pour ajouter l'option "Transkun" dans le `<select>` des modèles.

### 2. Backend - Dépendances
- Ajouter `transkun>=2.0.0` dans `backend/requirements.txt`.
- S'assurer que Transkun n'entre pas en conflit avec `torch>=2.5.0` (requis pour Intel XPU).

### 3. Backend - Pipeline (`transcriber.py`)
- Créer un pont `run_transkun(audio_path, options)`.
- **Mécanisme d'intégration** : 
  - Transkun génère un `.mid` de très haute qualité.
  - Le pont utilisera `python -m transkun.transcribe` pour écrire ce fichier dans un dossier temporaire.
  - Le pipeline utilisera ensuite `backend/midi_parser.py` (notre outil interne de la Phase 1) pour relire ce MIDI et en extraire les `note_events` bruts.
  - Ces `note_events` seront renvoyés au pipeline standard (Tempo map → Quantization → Score builder).

### 4. Gestion GPU (Intel ARC)
- Transkun s'attend généralement à `"cuda"` ou `"cpu"`.
- Il faudra wrapper l'appel pour détecter si le système utilise `"xpu"` (Intel ARC) et configurer Transkun en conséquence (ou forcer le CPU si Transkun ne gère que CUDA strict, bien que PyTorch XPU soit souvent transparent).

## Critères d'acceptation
- [ ] L'utilisateur peut sélectionner "Transkun" dans l'UI.
- [ ] L'inférence s'exécute sans crasher le serveur.
- [ ] La partition générée inclut toutes les phases V3 habituelles (tonalité, tempo map).
- [ ] Aucun conflit avec les autres moteurs (ByteDance / Basic Pitch restent fonctionnels).
