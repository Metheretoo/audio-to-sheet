# Phase 8 — Frontend

## Objectif
Interface utilisateur web pour l'upload audio, la visualisation de partition et le téléchargement des fichiers générés (MIDI, MusicXML).

## Architecture
- **Framework**: HTML5 + CSS3 + JavaScript vanilla (pas de framework lourd)
- **Communication**: Fetch API vers Flask backend
- **Visualisation**: VexFlow pour le rendu de partition
- **Audio**: Web Audio API pour la lecture/preview

## Structure du dossier `frontend/`

```
frontend/
├── index.html          # Page principale
├── css/
│   └── style.css       # Styles
├── js/
│   ├── app.js          # Logique principale
│   ├── player.js       # Lecteur audio
│   └── score-viewer.js # Visualiseur de partition (VexFlow)
└── favicon.ico
```

## Fonctionnalités

### 1. Upload de fichier audio
- Glisser-déposer (drag & drop)
- Sélection via bouton
- Types acceptés: `.flac`, `.wav`, `.mp3`
- Taille max: 50 MB
- Barre de progression

### 2. Traitement et feedback
- Affichage du statut: "Upload en cours" → "Analyse en cours" → "Terminé"
- Messages d'erreur clairs
- Auto-refresh du statut toutes les 2 secondes

### 3. Visualisation de partition
- Rendu VexFlow responsive
- Navigation entre mesures (précédent/suivant)
- Zoom avant/arrière
- Affichage de l'armure (key signature)
- Affichage de la mesure (time signature)
- Affichage du BPM

### 4. Lecteur audio
- Lecture/Pause
- Synchronisation avec la partition (highlight de la mesure courante)
- Contrôle du volume

### 5. Téléchargement
- Bouton télécharger MIDI
- Bouton télécharger MusicXML
- Bouton télécharger JSON (debug)

## Routes API

| Méthode | Route | Description |
|---------|-------|-------------|
| POST | `/upload` | Upload audio + transcription |
| GET | `/status/<job_id>` | Statut du job |
| GET | `/midi/<job_id>` | Téléchargement MIDI |
| GET | `/score/<job_id>` | Téléchargement MusicXML |
| GET | `/score/json/<job_id>` | Téléchargement JSON debug |
| GET | `/health` | Health check |

## Design

### Palette de couleurs
- Primaire: `#2563eb` (bleu)
- Secondaire: `#10b981` (vert)
- Danger: `#ef4444` (rouge)
- Fond: `#f8fafc`
- Texte: `#1e293b`

### Responsive
- Mobile: < 768px (colonne unique)
- Tablette: 768px - 1024px
- Desktop: > 1024px (layout complet)

## Critères d'acceptation
- [x] Interface d'upload fonctionnelle (drag & drop + bouton)
- [x] Validation des types de fichier
- [x] Feedback visuel pendant le traitement
- [x] Visualisation de partition avec VexFlow
- [x] Lecteur audio synchronisé
- [x] Téléchargement MIDI/MusicXML
- [x] Design responsive
- [x] Gestion d'erreurs utilisateur

## Dépendances frontend
```html
<!-- VexFlow (CDN) -->
<script src="https://unpkg.com/vexflow@4.2.2/build/cjs/vexflow.js"></script>
<script src="https://unpkg.com/vexflow@4.2.2/build/cjs/vexflow-bravura.js"></script>
```

## Notes
- Le frontend est **statique** (pas de build nécessaire)
- Peut servir via Nginx, Apache, ou Flask en développement
- Pour la V4: migration vers React/Vue.js si nécessaire