# Phase 6 — API REST

> **Statut** : À implémenter
> **Dépendances** : Phase 1 ✅, Phase 2 ✅, Phase 3 ✅, Phase 4 ✅
> **Gain attendu** : API Flask avec endpoints upload, transcribe, download, health

---

## Objectif

Exposer le pipeline audio→sheet music via une API RESTful avec Flask. L'API doit gérer le téléchargement audio, la transcription, l'export MIDI et le statut du serveur.

---

## Architecture

```
backend/app.py (extension de l'actuel)
├── Flask app
├── Upload endpoint
├── Transcribe endpoint (async)
├── Download endpoint
├── Health endpoint
└── CORS configuration
```

---

## Endpoints

### 1. `POST /upload` — Télécharger un fichier audio

**Request:**
```
POST /upload
Content-Type: multipart/form-data

file: <audio_file>
```

**Response 200:**
```json
{
  "status": "ok",
  "filename": "uploaded_audio.wav",
  "duration": 180.5,
  "sample_rate": 44100,
  "channels": 2,
  "file_size": 15876000
}
```

**Response 400:**
```json
{
  "error": "Type de fichier non supporté. Formats acceptés: wav, mp3, flac, m4a, webm"
}
```

**Validation:**
- Type MIME: audio/*
- Taille max: 100 MB
- Formats: wav, mp3, flac, m4a, webm

---

### 2. `POST /transcribe` — Lancer la transcription

**Request:**
```
POST /transcribe
Content-Type: application/json

{
  "filename": "uploaded_audio.wav"
}
```

**Response 202 (Accepted):**
```json
{
  "status": "processing",
  "message": "Transcription démarrée",
  "job_id": "abc123"
}
```

**Note:** La transcription est asynchrone. Le client doit poller `/status/<job_id>`.

---

### 3. `GET /transcribe/<filename>` — Transcription directe (synchrone alternatif)

**Request:**
```
GET /transcribe?filename=uploaded_audio.wav
```

**Response 200:**
- Content-Type: `audio/midi`
- Content-Disposition: `attachment; filename="output.mid"`
- Body: fichier MIDI binaire

**Response 202 (si encore en cours):**
```json
{
  "status": "processing",
  "progress": 0.5
}
```

---

### 4. `GET /status/<job_id>` — Vérifier le statut

**Request:**
```
GET /status/abc123
```

**Response 200 (en cours):**
```json
{
  "status": "processing",
  "progress": 0.75,
  "phase": "quantization",
  "estimated_time": 10
}
```

**Response 200 (terminé):**
```json
{
  "status": "completed",
  "midi_url": "/download/abc123.mid",
  "duration": 180.5,
  "bpm": 120,
  "key": "C"
}
```

**Response 404 (not found):**
```json
{
  "error": "Job non trouvé"
}
```

---

### 5. `GET /download/<filename>` — Télécharger le MIDI

**Request:**
```
GET /download/output.mid
```

**Response 200:**
- Content-Type: `audio/midi`
- Content-Disposition: `attachment; filename="output.mid"`
- Body: fichier MIDI binaire

**Response 404:**
```json
{
  "error": "Fichier non trouvé"
}
```

---

### 6. `GET /health` — Santé du serveur

**Request:**
```
GET /health
```

**Response 200:**
```json
{
  "status": "healthy",
  "version": "3.0.0",
  "uptime": 3600,
  "modules": {
    "voice_engine": "ok",
    "transcriber": "ok",
    "quantizer": "ok",
    "midi_exporter": "ok"
  },
  "resources": {
    "cpu_percent": 25.0,
    "memory_percent": 40.0
  }
}
```

---

### 7. `GET /info` — Informations système

**Request:**
```
GET /info
```

**Response 200:**
```json
{
  "python_version": "3.11.0",
  "platform": "Windows 11",
  "cuda_available": true,
  "cuda_version": "12.1",
  "available_ram_gb": 32,
  "available_disk_gb": 500
}
```

---

## Structure du Code

```python
# backend/app.py

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import time
import threading
from datetime import datetime

from voice_engine import VoiceEngine
from transcriber import MIDITranscriber
from quantizer import Quantizer
from midi_parser import MIDIExporter

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac', 'm4a', 'webm'}

# Jobs tracking
jobs = {}

# === Helpers ===

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_job_status(job_id):
    return jobs.get(job_id, {'status': 'not_found'})

def run_transcription(job_id, filename):
    """Exécute le pipeline complet en arrière-plan"""
    try:
        # Phase 1: Voice Engine
        progress = 0.1
        jobs[job_id]['progress'] = progress
        jobs[job_id]['phase'] = 'voice_detection'
        
        voice_engine = VoiceEngine()
        voice_result = voice_engine.detect_voices(os.path.join(UPLOAD_FOLDER, filename))
        jobs[job_id]['voices'] = voice_result
        
        # Phase 2: Transcription
        progress = 0.3
        jobs[job_id]['progress'] = progress
        jobs[job_id]['phase'] = 'transcription'
        
        transcriber = MIDITranscriber()
        midi_data = transcriber.transcribe(voice_result)
        jobs[job_id]['midi_data'] = midi_data
        
        # Phase 3: Quantizer
        progress = 0.6
        jobs[job_id]['progress'] = progress
        jobs[job_id]['phase'] = 'quantization'
        
        quantizer = Quantizer()
        quantized = quantizer.quantize(midi_data)
        jobs[job_id]['quantized'] = quantized
        
        # Phase 4: MIDI Export
        progress = 0.8
        jobs[job_id]['progress'] = progress
        jobs[job_id]['phase'] = 'export'
        
        exporter = MIDIExporter(quantized['tempo_map'], quantized['key'])
        output_path = exporter.export(quantized['notes'], os.path.join(OUTPUT_FOLDER, filename.replace(os.path.splitext(filename)[1], '.mid')))
        
        # Completion
        progress = 1.0
        jobs[job_id]['progress'] = progress
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['midi_url'] = f'/download/{os.path.basename(output_path)}'
        
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)


# === Routes ===

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier dans la requête'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({
            'error': 'Type de fichier non supporté. Formats acceptés: wav, mp3, flac, m4a, webm'
        }), 400
    
    # Save file
    filename = file.filename
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    # Get file info
    stat = os.stat(filepath)
    file_size = stat.st_size
    
    # Get audio info
    try:
        import librosa
        y, sr = librosa.load(filepath, sr=None)
        duration = len(y) / sr
        channels = 1 if len(y.shape) == 1 else y.shape[0]
    except:
        duration = file_size / (16 * 44100)  # estimation
        channels = 1
    
    return jsonify({
        'status': 'ok',
        'filename': filename,
        'duration': round(duration, 3),
        'sample_rate': 44100,
        'channels': channels,
        'file_size': file_size
    }), 200


@app.route('/transcribe', methods=['POST'])
def transcribe_file():
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({'error': 'Nom du fichier requis'}), 400
    
    filename = data['filename']
    
    # Check if file exists
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Fichier non trouvé'}), 404
    
    # Create job
    job_id = hashlib.md5(filename.encode()).hexdigest()
    jobs[job_id] = {
        'status': 'processing',
        'progress': 0,
        'phase': 'init',
        'filename': filename,
        'created_at': datetime.now().isoformat()
    }
    
    # Start transcription in background thread
    thread = threading.Thread(target=run_transcription, args=(job_id, filename))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'status': 'processing',
        'message': 'Transcription démarrée',
        'job_id': job_id
    }), 202


@app.route('/transcribe/<filename>', methods=['GET'])
def transcribe_direct(filename):
    """Transcription synchrone (pour petits fichiers)"""
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Fichier non trouvé'}), 404
    
    # Exécuter le pipeline complet
    try:
        # Phase 1
        voice_engine = VoiceEngine()
        voice_result = voice_engine.detect_voices(filepath)
        
        # Phase 2
        transcriber = MIDITranscriber()
        midi_data = transcriber.transcribe(voice_result)
        
        # Phase 3
        quantizer = Quantizer()
        quantized = quantizer.quantize(midi_data)
        
        # Phase 4
        exporter = MIDIExporter(quantized['tempo_map'], quantized['key'])
        output_path = exporter.export(
            quantized['notes'],
            os.path.join(OUTPUT_FOLDER, filename.replace(os.path.splitext(filename)[1], '.mid'))
        )
        
        return send_file(
            output_path,
            mimetype='audio/midi',
            as_attachment=True,
            download_name=os.path.basename(output_path)
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job non trouvé'}), 404
    
    if job['status'] == 'completed':
        return jsonify(job), 200
    elif job['status'] == 'error':
        return jsonify(job), 500
    else:
        return jsonify(job), 200


@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    filepath = os.path.join(OUTPUT_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Fichier non trouvé'}), 404
    
    return send_file(
        filepath,
        mimetype='audio/midi',
        as_attachment=True,
        download_name=filename
    )


@app.route('/health', methods=['GET'])
def health_check():
    import psutil
    import sys
    import torch
    
    # Check module health
    modules = {}
    for name, module in [
        ('voice_engine', VoiceEngine),
        ('transcriber', MIDITranscriber),
        ('quantizer', Quantizer),
        ('midi_exporter', MIDIExporter)
    ]:
        try:
            module()
            modules[name] = 'ok'
        except:
            modules[name] = 'error'
    
    # Resources
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    
    return jsonify({
        'status': 'healthy',
        'version': '3.0.0',
        'uptime': time.time() - startup_time,
        'modules': modules,
        'resources': {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent
        }
    }), 200


@app.route('/info', methods=['GET'])
def system_info():
    import psutil
    
    return jsonify({
        'python_version': sys.version,
        'platform': sys.platform,
        'cuda_available': torch.cuda.is_available(),
        'cuda_version': torch.version.cuda if torch.cuda.is_available() else None,
        'available_ram_gb': psutil.virtual_memory().available / (1024**3),
        'available_disk_gb': psutil.disk_usage('/').free / (1024**3)
    }), 200


# === Main ===

startup_time = time.time()

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )
```

---

## Dépendances API

```txt
# backend/requirements.txt (ajouter si absent)

flask>=3.0
flask-cors>=4.0
psutil>=5.9      # Health check (CPU/RAM)
```

---

## Frontend Integration

### JavaScript Client

```javascript
// frontend/js/api-client.js

class AudioToSheetAPI {
    constructor(baseUrl = 'http://localhost:5000') {
        this.baseUrl = baseUrl;
    }

    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${this.baseUrl}/upload`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`Upload failed: ${response.statusText}`);
        }
        
        return await response.json();
    }

    async transcribeFile(filename) {
        const response = await fetch(`${this.baseUrl}/transcribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        });
        
        if (response.status === 202) {
            return await response.json();  // { job_id, status: 'processing' }
        }
        
        return await response.json();  // Direct MIDI download info
    }

    async getJobStatus(jobId) {
        const response = await fetch(`${this.baseUrl}/status/${jobId}`);
        return await response.json();
    }

    async downloadMidi(filename) {
        const response = await fetch(`${this.baseUrl}/download/${filename}`);
        return await response.blob();
    }

    async healthCheck() {
        const response = await fetch(`${this.baseUrl}/health`);
        return await response.json();
    }

    // Polling utility
    async waitForCompletion(jobId, interval = 1000, timeout = 300000) {
        const start = Date.now();
        
        while (Date.now() - start < timeout) {
            const status = await this.getJobStatus(jobId);
            
            if (status.status === 'completed') {
                return status;
            } else if (status.status === 'error') {
                throw new Error(`Transcription error: ${status.error}`);
            }
            
            await new Promise(resolve => setTimeout(resolve, interval));
        }
        
        throw new Error('Timeout waiting for transcription');
    }
}

// Export singleton
const api = new AudioToSheetAPI();
export default api;
```

---

## Sécurité

### 1. File Upload Security

```python
# Restriction par type de fichier
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac', 'm4a', 'webm'}

# Limitation taille
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

# Validation filename
def secure_filename(filename):
    import re
    # Remove dangerous characters
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    return filename
```

### 2. Rate Limiting

```python
from flask_limiter import Limiter
limiter = Limiter(app, key_func=lambda: request.remote_addr)

@app.route('/transcribe', methods=['POST'])
@limiter.limit("5 per minute")
def transcribe_file():
    ...
```

### 3. CORS Configuration

```python
CORS(app, resources={
    r"/upload": {"origins": "*"},
    r"/transcribe": {"origins": "*"},
    r"/download/*": {"origins": "*"},
    r"/health": {"origins": "*"},
    r"/info": {"origins": "*"}
})
```

---

## Erreurs Standardisées

```json
{
  "error": "message d'erreur",
  "code": "ERROR_CODE",
  "details": {}
}
```

| Code | HTTP Status | Description |
|------|-------------|-------------|
| FILE_TOO_LARGE | 413 | Fichier trop volumineux |
| INVALID_FORMAT | 400 | Format non supporté |
| FILE_NOT_FOUND | 404 | Fichier introuvable |
| JOB_NOT_FOUND | 404 | Job introuvable |
| TRANScription_ERROR | 500 | Erreur de transcription |
| EXPORT_ERROR | 500 | Erreur d'export MIDI |

---

## Ordre d'Implémentation

1. Créer `backend/app.py` avec les endpoints de base
2. Ajouter CORS
3. Implémenter `/upload`
4. Implémenter `/transcribe` (async)
5. Implémenter `/status/<job_id>`
6. Implémenter `/download/<filename>`
7. Implémenter `/health` et `/info`
8. Ajouter sécurité (file validation, rate limiting)
9. Tester avec curl/Postman
10. Connecter avec le frontend

---

**Dernière mise à jour** : 4 juillet 2026