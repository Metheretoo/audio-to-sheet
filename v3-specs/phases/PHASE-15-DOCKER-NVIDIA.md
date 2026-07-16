# Phase 15 — Architecture Docker (Migration NVIDIA RTX)

## Objectif
Permettre un déploiement de l'application sur une machine cible vierge équipée d'une carte graphique NVIDIA (ex: RTX 3090) sans avoir à y installer Python, PyTorch, ou CUDA nativement. Cette isolation est garantie via Docker.

## Prérequis sur la machine cible (Le PC RTX)
1. **Windows 10/11 à jour**.
2. **Pilotes NVIDIA classiques** installés (ceux pour les jeux/affichages suffisent, ils incluent les cœurs CUDA).
3. **Docker Desktop pour Windows** installé.
   - *Note:* Lors de l'installation, assurez-vous que l'option "Use WSL 2 based engine" est cochée (c'est le cas par défaut).

## Instructions de migration

1. Copiez l'intégralité de ce dossier de projet (`Audio-to-Sheet`) sur une clé USB ou par le réseau local, et collez-le sur le PC avec la RTX 3090.
2. Démarrez l'application **Docker Desktop** sur ce PC et attendez que l'icône dans la barre des tâches indique que le moteur tourne.
3. Entrez dans le dossier du projet que vous venez de copier, et double-cliquez sur le fichier `LANCER_AUDIO_TO_SHEET.bat`.

## Que va-t-il se passer lors du premier lancement ?
Le script va ordonner à Docker de lire le fichier `Dockerfile`. 
Docker va alors télécharger une image Linux contenant `Python 3.10`, `PyTorch` et `CUDA 12.1`. Cela pèse plusieurs gigaoctets (généralement 5-6 Go), le téléchargement peut prendre une dizaine de minutes selon votre connexion.
Une fois téléchargé, il va automatiquement installer `transkun` et les autres dépendances.

Aux lancements suivants, l'application démarrera instantanément.

## Accès à l'application
Le serveur Flask démarrera dans le conteneur sur le port 5000 et le transmettra à la machine hôte.
- Sur le PC RTX, ouvrez le navigateur à l'adresse : `http://localhost:5000`
- Depuis n'importe quel autre ordinateur de votre réseau local (ex: votre PC Intel), tapez l'adresse IP locale de la RTX : `http://192.168.1.19:5000`

## Pourquoi cette approche ?
Le fichier `docker-compose.yml` utilise la directive suivante :
```yaml
reservations:
  devices:
    - driver: nvidia
      count: 1
      capabilities: [gpu]
```
Grâce au pont magique fourni par Docker Desktop sous Windows (via WSL2), la carte RTX 3090 est physiquement exposée au conteneur Linux isolé. Lorsque Transkun demandera `--device cuda`, PyTorch verra bien les 24 Go de VRAM et pourra effectuer des calculs de transcription à une vitesse fulgurante.
