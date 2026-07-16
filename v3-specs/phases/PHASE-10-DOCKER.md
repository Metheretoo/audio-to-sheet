# Phase 10 — Docker et Déploiement

## Objectif
Containeriser l'application pour un déploiement facile et reproductible.

## Fichiers Docker

### `Dockerfile`

```dockerfile
# Image multi-stage pour audio-to-sheet v3
FROM python:3.11-slim AS builder

WORKDIR /build

# Installation des dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copie des dépendances Python
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Image finale
FROM python:3.11-slim

WORKDIR /app

# Copie des dépendances installées
COPY --from=builder /install /usr/local

# Copie du code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Création des dossiers temporaires
RUN mkdir -p /tmp/uploads /tmp/outputs

# Exposition du port
EXPOSE 5000

# Lancement
CMD ["python", "backend/app.py", "--host", "0.0.0.0"]
```

### `docker-compose.yml`

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./uploads:/app/uploads
      - ./outputs:/app/outputs
    environment:
      - FLASK_ENV=production
      - MAX_CONTENT_LENGTH=52428800  # 50MB
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### `.dockerignore`

```
__pycache__
*.pyc
.venv
venv
*.egg-info
uploads/
outputs/
.env
*.md
v3-specs/
v2-specs/
tests/
.DS_Store
Thumbs.db
```

## Build et Run

```bash
# Build
docker build -t audio-to-sheet:v3 .

# Run
docker run -p 5000:5000 -v $(pwd)/uploads:/app/uploads -v $(pwd)/outputs:/app/outputs audio-to-sheet:v3

# Avec docker-compose
docker-compose up -d

# Logs
docker-compose logs -f app

# Stop
docker-compose down
```

## Déploiement Production

### Option 1: Docker seul
```bash
docker-compose up -d
```

### Option 2: Nginx reverse proxy
```nginx
server {
    listen 80;
    server_name audio-to-sheet.local;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 50M;
    }
}
```

### Option 3: systemd service
```ini
[Unit]
Description=Audio-to-Sheet Music V3
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/audio-to-sheet
ExecStart=/usr/bin/docker-compose up -d
Restart=always

[Install]
WantedBy=multi-user.target
```

## Critères d'acceptation
- [x] Dockerfile fonctionnel
- [x] docker-compose.yml configuré
- [x] Image build sans erreur
- [x] Application accessible sur port 5000
- [x] Volumes pour uploads/outputs
- [x] Health check configuré
- [x] .dockerignore pour réduire l'image

## Notes
- Image finale: ~500MB (Python slim)
- Pour production: ajouter nginx + SSL
- Pour Kubernetes: adapter le deployment YAML