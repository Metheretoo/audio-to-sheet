# Phase 7 — Flask API Backend

## Objectif
Expose les fonctionnalités de transcription via une API RESTful avec Flask.

## Architecture
- **Framework**: Flask 3.x + Flask-CORS
- **Upload**: Audio file (multipart/form-data)
- **Processing**: Pipeline synchronisé (upload → process → return JSON)
- **Output**: JSON response with score data, downloadable MIDI

## Dépendances supplémentaires
```
flask>=3.0,<4.0
flask-cors>=4.0,<5.0
```

## Configuration

```python
app.config.update({
    'MAX_CONTENT_LENGTH': 50 * 1024 * 1024,  # 50 MB max
    'UPLOAD_FOLDER': tempfile.gettempdir(),
    'OUTPUT_FOLDER': tempfile.gettempdir(),
})
```

## Routes

### `POST /upload`
Upload audio et lance la transcription.

**Request:**
- `file` (multipart): fichier audio (.flac, .wav, .mp3)

**Response 200:**
```json
{
  "job_id": "abc123",
  "status": "completed",
  "result": {
    "key": "C",
    "meter": "4/4",
    "bpm": 120,
    "time_signature": [4, 4],
    "tracks": [...],
    "measures": [...]
  }
}
```

**Response 400:**
```json
{
  "error": "Invalid file. Allowed types: flac, wav, mp3"
}
```

**Response 413:**
```json
{
  "error": "File too large. Maximum size: 50MB"
}
```

### `GET /status/<job_id>`
Vérifie le statut d'un job.

**Response 200:**
```json
{
  "job_id": "abc123",
  "status": "completed",  // queued | processing | completed | failed
  "error": null
}
```

### `GET /midi/<job_id>`
Télécharge le fichier MIDI généré.

**Response 200:** Fichier binary `.mid`

**Response 404:**
```json
{
  "error": "MIDI file not found"
}
```

### `GET /score/<job_id>`
Télécharge le fichier MusicXML généré.

**Response 200:** Fichier binary `.xml`

**Response 404:**
```json
{
  "error": "Score file not found"
}
```

### `GET /health`
Health check.

**Response 200:**
```json
{
  "status": "ok",
  "version": "3.0.0"
}
```

## Structure du fichier `app.py`

```python
"""audio-to-sheet music v3 — API Flask"""
import os
import tempfile
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from transcriber import TranscriptionPipeline

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {'flac', 'wav', 'mp3'}
pipeline = TranscriptionPipeline()

# Routes
# /upload, /status/<job_id>, /midi/<job_id>, /score/<job_id>, /health

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

## Critères d'acceptation
- [x] Route `/upload` accepte .flac, .wav, .mp3
- [x] Route `/upload` retourne JSON avec résultat de transcription
- [x] Route `/status/<job_id>` retourne statut du job
- [x] Route `/midi/<job_id>` sert le fichier MIDI
- [x] Route `/score/<job_id>` sert le fichier MusicXML
- [x] Route `/health` retourne `{"status": "ok"}`
- [x] Limitation taille fichier: 50 MB
- [x] CORS activé
- [x] Gestion d'erreurs (type non supporté, fichier introuvable)

## Notes
- Le processing est **synchrone** pour la V3 (pas de file d'attente)
- Les fichiers temporaires sont dans `%TEMP%`
- Pour la V4: ajout d'un worker async (Celery/RQ)