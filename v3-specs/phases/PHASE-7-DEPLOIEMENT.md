# Phase 7 — Déploiement & Documentation

> **Statut** : À implémenter
> **Dépendances** : Phase 6 ✅ (API REST)
> **Gain attendu** : Docker, CI/CD, documentation, scripts de déploiement

---

## Objectif

Préparer l'application pour la production avec Docker, CI/CD, documentation complète et scripts de déploiement.

---

## Livrables

### 1. Docker & Docker Compose

### 2. CI/CD (GitHub Actions)

### 3. Documentation

### 4. Scripts de déploiement

---

## Docker

### Dockerfile

```dockerfile
# backend/Dockerfile

FROM python:3.11-slim

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p uploads outputs

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

# Run application
CMD ["python", "app.py"]
```

### Docker Compose

```yaml
# docker-compose.yml

version: '3.8'

services:
  app:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: audio-to-sheet
    ports:
      - "5000:5000"
    volumes:
      - ./uploads:/app/uploads
      - ./outputs:/app/outputs
    environment:
      - FLASK_ENV=production
      - CUDA_VISIBLE_DEVICES=0
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:5000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]

  frontend:
    image: nginx:alpine
    container_name: audio-to-sheet-frontend
    ports:
      - "80:80"
    volumes:
      - ./frontend:/usr/share/nginx/html
    depends_on:
      - app
    restart: unless-stopped

volumes:
  uploads:
  outputs:
```

### .dockerignore

```gitignore
# .dockerignore

__pycache__
*.pyc
*.pyo
.eggs
*.egg-info
.env
.venv
venv
dist
build
.mypy_cache
.pytest_cache
*.md
.git
.gitignore
Dockerfile
docker-compose.yml
.vscode
.idea
*.swp
*.swo
```

---

## CI/CD — GitHub Actions

### .github/workflows/ci.yml

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install flake8 black isort
      
      - name: Run flake8
        run: |
          flake8 backend/ --max-line-length=120 --count
      
      - name: Run black
        run: |
          black --check backend/
      
      - name: Run isort
        run: |
          isort --check --profile=black backend/

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r backend/requirements.txt
          pip install pytest pytest-cov
      
      - name: Run tests
        run: |
          pytest backend/tests/ --cov=backend --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

  build:
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: |
          docker build -t audio-to-sheet:latest ./backend
      
      - name: Run Docker health check
        run: |
          docker run -d --name test-container -p 5000:5000 audio-to-sheet:latest
          sleep 10
          curl -f http://localhost:5000/health || exit 1
          docker stop test-container

  deploy:
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - name: Deploy to server
        run: |
          echo "Deployment en cours..."
          # Ajouter les commandes de déploiement selon l'infrastructure
```

---

## Documentation

### README.md (racine du projet)

```markdown
# Audio-to-Sheet v3

Transcription automatique de musique audio en partitions musicales (format MIDI).

## 🚀 Quick Start

### Installation locale

```bash
# 1. Clone le projet
git clone https://github.com/votreusername/audio-to-sheet.git
cd audio-to-sheet

# 2. Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Installer les dépendances
pip install -r backend/requirements.txt

# 4. Lancer le serveur
cd backend
python app.py
```

### Avec Docker

```bash
# Build et run
docker-compose up -d

# Accès
# Backend:  http://localhost:5000
# Frontend: http://localhost
```

## 📡 API

### Upload un fichier
```bash
curl -X POST -F "file=@audio.mp3" http://localhost:5000/upload
```

### Transcrire
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"filename": "audio.mp3"}' \
  http://localhost:5000/transcribe
```

### Vérifier le statut
```bash
curl http://localhost:5000/status/{job_id}
```

### Télécharger le MIDI
```bash
curl -O http://localhost:5000/download/output.mid
```

## 🏗️ Architecture

```
audio-to-sheet/
├── backend/              # Backend Flask
│   ├── app.py            # API REST
│   ├── voice_engine.py   # Phase 1: Détection vocale
│   ├── transcriber.py    # Phase 2: Transcription
│   ├── quantizer.py      # Phase 3: Quantisation
│   ├── midi_parser.py    # Phase 4: Export MIDI
│   └── requirements.txt
├── frontend/             # Frontend React
│   ├── index.html
│   ├── js/
│   └── css/
├── uploads/              # Fichiers uploadés
├── outputs/              # Fichiers MIDI générés
├── v3-specs/            # Spécifications v3
├── docker-compose.yml
└── README.md
```

## 🧪 Tests

```bash
# Run all tests
pytest backend/tests/ -v

# With coverage
pytest backend/tests/ --cov=backend --cov-report=html
```

## 📋 Formats supportés

**Input:** WAV, MP3, FLAC, M4A, WebM
**Output:** MIDI (Type 1)

## 🔧 Configuration

```python
# backend/config.py

class Config:
    UPLOAD_FOLDER = 'uploads'
    OUTPUT_FOLDER = 'outputs'
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
    ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac', 'm4a', 'webm'}
    HOST = '0.0.0.0'
    PORT = 5000
    DEBUG = False
```

## 🚨 Dépannage

### CUDA/GPU non détecté
```bash
python -c "import torch; print(torch.cuda.is_available())"
```

### Erreur de compilation
```bash
# Installer les build tools
sudo apt-get install build-essential
```

## 📄 Licence

MIT License

## 👥 Contribuer

1. Fork le projet
2. Créer une branche (`git checkout -b feature/ma-feature`)
3. Commit les changements (`git commit -m 'Ajout feature'`)
4. Push vers la branche (`git push origin feature/ma-feature`)
5. Ouvrir une Pull Request
```

---

## Scripts de Déploiement

### deploy.sh (Linux/Mac)

```bash
#!/bin/bash

# Audio-to-Sheet Deployment Script

set -e

echo "🚀 Déploiement de Audio-to-Sheet v3"

# Vérifier Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose n'est pas installé"
    exit 1
fi

# Arrêter les conteneurs existants
echo "📦 Arrêt des conteneurs existants..."
docker-compose down || true

# Build
echo "🔨 Build des images..."
docker-compose build

# Run
echo "▶️  Démarrage des conteneurs..."
docker-compose up -d

# Health check
echo "🏥 Vérification de la santé du service..."
for i in {1..30}; do
    if curl -f http://localhost:5000/health &> /dev/null; then
        echo "✅ Service healthy!"
        exit 0
    fi
    echo "   Attente... ($i/30)"
    sleep 1
done

echo "❌ Le service n'a pas démarré correctement"
exit 1
```

### deploy.ps1 (Windows)

```powershell
# Audio-to-Sheet Deployment Script for Windows

Write-Host "🚀 Déploiement de Audio-to-Sheet v3" -ForegroundColor Green

# Vérifier Docker
if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker n'est pas installé" -ForegroundColor Red
    exit 1
}

# Arrêter les conteneurs existants
Write-Host "📦 Arrêt des conteneurs existants..."
docker-compose down 2>$null

# Build
Write-Host "🔨 Build des images..."
docker-compose build

# Run
Write-Host "▶️  Démarrage des conteneurs..."
docker-compose up -d

# Health check
Write-Host "🏥 Vérification de la santé du service..."
for ($i = 1; $i -le 30; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:5000/health" -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Host "✅ Service healthy!" -ForegroundColor Green
            exit 0
        }
    } catch {}
    Write-Host "   Attente... ($i/30)"
    Start-Sleep -Seconds 1
}

Write-Host "❌ Le service n'a pas démarré correctement" -ForegroundColor Red
exit 1
```

---

## Nginx Configuration (Production)

### nginx.conf

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Frontend
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://app:5000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Max upload size
        client_max_body_size 100M;
        
        # Timeouts
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    # Static files
    location /static/ {
        alias /usr/share/nginx/html/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Gzip
    gzip on;
    gzip_types text/plain application/json application/javascript text/css;
    gzip_min_length 1000;
}
```

---

## Monitoring

### Health Check Custom

```python
# backend/health.py

import psutil
import torch
import time
from datetime import datetime

def get_system_health():
    """Informations système complètes"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # GPU (si CUDA disponible)
    gpu_info = None
    if torch.cuda.is_available():
        gpu_info = {
            'available': True,
            'device_count': torch.cuda.device_count(),
            'memory_total_mb': torch.cuda.get_device_properties(0).total_mem / (1024**2),
            'memory_free_mb': torch.cuda.mem_get_info()[0] / (1024**2),
        }
    
    return {
        'cpu_percent': cpu_percent,
        'memory': {
            'percent': memory.percent,
            'available_gb': memory.available / (1024**3),
            'total_gb': memory.total / (1024**3)
        },
        'disk': {
            'free_gb': disk.free / (1024**3),
            'total_gb': disk.total / (1024**3)
        },
        'gpu': gpu_info,
        'timestamp': datetime.now().isoformat()
    }
```

---

## Checklist de Déploiement

### Pré-déploiement

- [ ] Tous les tests passent (`pytest`)
- [ ] Code linté (flake8, black, isort)
- [ ] Documentation à jour
- [ ] Variables d'environnement configurées
- [ ] Base de données migrée (si applicable)
- [ ] SSL certifié obtenu
- [ ] Domain name configuré

### Déploiement

- [ ] Docker images buildées
- [ ] Conteneurs démarrés
- [ ] Health checks passent
- [ ] Frontend accessible
- [ ] API fonctionnelle
- [ ] Fichiers uploadés et transcrits avec succès

### Post-déploiement

- [ ] Monitoring configuré
- [ ] Logs configurés
- [ ] Backups configurés
- [ ] Alertes configurées
- [ ] Performance testée
- [ ] Sécurité audité

---

## Variables d'Environnement

```bash
# backend/.env.example

# Flask
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=your-secret-key-here

# Server
HOST=0.0.0.0
PORT=5000

# Upload
MAX_CONTENT_LENGTH=104857600  # 100 MB
ALLOWED_EXTENSIONS=wav,mp3,flac,m4a,webm

# CUDA
CUDA_VISIBLE_DEVICES=0

# CORS
CORS_ORIGINS=*

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/audio-to-sheet/app.log
```

---

## Rollback Plan

```bash
# rollback.sh

#!/bin/bash

echo "🔄 Rollback en cours..."

# Arrêter le conteneur actuel
docker-compose down

# Démarrer la version précédente
docker-compose -f docker-compose.yml exec app docker tag audio-to-sheet:latest audio-to-sheet:current
docker-compose -f docker-compose.yml exec app docker tag audio-to-sheet:previous audio-to-sheet:latest

# Redémarrer
docker-compose up -d

# Vérifier
sleep 10
curl http://localhost:5000/health
```

---

**Dernière mise à jour** : 4 juillet 2026