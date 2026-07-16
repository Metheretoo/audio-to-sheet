# Utilisation de l'image officielle PyTorch (CUDA 12.1, cuDNN 8, Python 3.10)
# Cette image est optimisée pour les GPU NVIDIA (comme la RTX 3090)
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime

# Éviter les prompts interactifs lors de l'installation apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Définir le dossier de travail dans le conteneur
WORKDIR /app

# Installer les dépendances système requises pour le traitement audio
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copier uniquement le fichier de configuration des dépendances d'abord (optimisation du cache Docker)
COPY backend/requirements.txt ./backend/

# Installer les dépendances Python du projet
# On ignore les messages d'avertissement liés à l'environnement root
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

# Copier tout le reste du projet
COPY . .

# Exposer le port par défaut de l'application Flask
EXPOSE 5000

# Démarrer le serveur backend
CMD ["python", "backend/app.py"]
