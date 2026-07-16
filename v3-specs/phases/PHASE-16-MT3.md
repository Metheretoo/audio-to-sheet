# Phase 16 — Intégration de Google MT3

## Objectif
Ajouter le support du modèle **MT3 (Multi-Task Multitrack Music Transcription)** développé par Google Magenta, en tant que 4ème moteur de transcription sélectionnable par l'utilisateur.

## Choix de l'implémentation
Le dépôt officiel de Google `magenta/mt3` repose sur `JAX` et `T5X`, des frameworks complexes à installer sous Windows et pouvant entrer en conflit avec les versions CUDA de PyTorch.
Pour simplifier l'intégration et garantir la compatibilité, nous utilisons le paquet communautaire **`mt3-infer`**. Ce paquet offre :
- Une réécriture de l'inférence en PyTorch (partageant donc la VRAM et les bibliothèques avec `Transkun` et `Demucs`).
- Un téléchargement automatique des poids (checkpoints) depuis Hugging Face.
- Une sortie au format `pretty_midi` facile à parser.

## Modifications effectuées
1. **`backend/requirements.txt`** : Ajout de `mt3-infer[torch]>=0.1.0`. L'installation inclut ses propres sous-dépendances PyTorch.
2. **`backend/transcriber.py`** : 
   - Création de la fonction `run_mt3()`.
   - Extraction des événements MIDI `(onset, pitch, duration, velocity)` à partir de l'objet généré.
3. **`frontend/index.html`** : Ajout du bouton radio "Google MT3" dans le panneau des options avancées.

## Note sur le premier lancement
Lorsqu'un utilisateur sélectionne MT3 pour la première fois, la bibliothèque `mt3-infer` téléchargera les poids du modèle (environ 1.5 Go) en arrière-plan. La transcription semblera "bloquée" le temps du téléchargement, mais les exécutions ultérieures seront immédiates.
