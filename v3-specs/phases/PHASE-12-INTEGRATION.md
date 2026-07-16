# Phase 12 — Intégration Finale

## Objectif
Vérifier que tous les modules fonctionnent ensemble correctement et préparer la version finale.

## Checklist d'intégration

### 1. Vérification des dépendances
```bash
# Installer toutes les dépendances
pip install -r backend/requirements.txt

# Vérifier l'installation
python -c "import mido; import librosa; import numpy; import flask; import flask_cors; print('Toutes les dépendances sont installées.')"
```

### 2. Vérification du pipeline
```bash
# Script de validation
python backend/_validate_pipeline.py
```

### 3. Vérification de l'API
```bash
# Démarrer le serveur
python backend/app.py

# Tester les endpoints
curl http://localhost:5000/health
curl -X POST -F "file=@test.mp3" http://localhost:5000/upload
curl http://localhost:5000/status/<job_id>
```

### 4. Vérification du frontend
```bash
# Ouvrir frontend/index.html dans un navigateur
# Ou servir via Flask:
python -c "from flask import send_from_directory; import flask; app = flask.Flask(__name__); @app.route('/')\ndef index():\n    return send_from_directory('frontend', 'index.html'); app.run()"
```

### 5. Vérification cross-platform
- [x] Fonctionne sur Windows
- [x] Fonctionne sur macOS
- [x] Fonctionne sur Linux

### 6. Vérification des performances
- [x] Transcription < 30s pour un fichier de 3 minutes
- [x] Mémoire < 500MB
- [x] Qualité de sortie acceptable

## Fichiers à livrer

```
audio-to-sheet/
├── README.md                    ← Documenté
├── backend/
│   ├── app.py
│   ├── midi_parser.py
│   ├── quantizer.py
│   ├── tempo_map.py
│   ├── transcriber.py
│   ├── voice_engine.py
│   ├── score_builder.py
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   ├── js/app.js
│   ├── js/player.js
│   └── js/score-viewer.js
├── v3-specs/
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── PROGRESS.md
│   └── phases/
├── run_prod.bat                ← Script Windows
├── docker-compose.yml
├── Dockerfile
└── .gitignore
```

## Commandes de déploiement rapide

### Windows
```bash
run_prod.bat
```

### macOS/Linux
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
python backend/app.py
```

### Docker
```bash
docker-compose up -d
```

## Critères d'acceptation
- [x] Pipeline complet fonctionnel
- [x] API répond correctement
- [x] Frontend affiche la partition
- [x] Téléchargement MIDI/MusicXML fonctionne
- [x] Documentation à jour
- [x] Installation sans erreur

## Retours après intégration
- Note les problèmes rencontrés
- Les corrections apportées
- Les améliorations suggérées