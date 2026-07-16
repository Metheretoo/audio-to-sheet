# audio-to-sheet — Spécifications V2

> **Dossier de référence pour les agents codeurs.**
> Chaque fichier `.md` de ce dossier est une directive autonome et suffisante pour implémenter une phase du projet.
> Un agent peut prendre en charge une phase sans lire tout le projet à condition de lire :
> 1. Ce `README.md`
> 2. Le fichier de phase qui lui est assigné
> 3. `ARCHITECTURE.md` pour comprendre les interfaces entre modules

---

## Contexte du projet

`audio-to-sheet` est une application web locale qui transcrit un fichier audio (piano) en partition lisible.

**Stack actuelle (V1)**
- Backend : Python / Flask (`backend/app.py`)
- Transcription : `piano_transcription_inference` (modèle CRNN) ou `basic_pitch`
- Séparation instrumentale optionnelle : `demucs`
- Parsing / export : `backend/midi_parser.py` → JSON VexFlow
- Frontend : HTML + JS vanilla (`frontend/index.html`, `frontend/js/`)
- Rendu de partition : VexFlow (librairie JS)

**Problèmes V1 identifiés (à résoudre en V2)**
| Problème | Cause racine | Impact |
|---|---|---|
| Décalage temporel progressif (drift) | Tempo statique unique appliqué linéairement | Partition illisible à partir de la mesure 2-3 |
| Détection BPM instable (94 vs 138 BPM) | `librosa.beat_track` global sur tout le signal | Mauvaise base pour la quantification |
| Écriture musicale trop complexe | Quantification naïve (arrondi simple) | Trop de micro-notes, trop de silences parasites |
| Main gauche moins fiable | Seuil fixe MIDI 57, pas d'analyse contour | Accords enrichis mal attribués |
| Pas de gestion du rubato/ritardando | Pas de tempo map dynamique | Partition désynchronisée sur morceaux expressifs |

---

## Structure de ce dossier

```
v2-specs/
├── README.md                    ← Ce fichier (point d'entrée)
├── ARCHITECTURE.md              ← Schéma du pipeline V2 et interfaces entre modules
├── PROGRESS.md                  ← Suivi d'avancement global (à maintenir à jour)
│
├── phases/
│   ├── PHASE-1-tempo-map.md     ← Remplacement du tempo statique par une TempoMap dynamique
│   ├── PHASE-2-quantizer.md     ← Nouveau module de quantification musicale (quantizer.py)
│   ├── PHASE-3-voice-engine.md  ← Moteur d'alignement des voix / séparation LH-RH
│   ├── PHASE-4-score-repr.md    ← Représentation de partition stable (music21 ou custom)
│   └── PHASE-5-frontend.md      ← Adaptations frontend (tempo variable, mesures complexes)
│
└── references/
    ├── FAISABILITE.md           ← Limites techniques, ce qui est possible / impossible
    └── DEPENDENCIES.md          ← Librairies open source recommandées et pourquoi
```

---

## Ordre d'exécution des phases

```
PHASE 1 → PHASE 2 → PHASE 3 → PHASE 4 → PHASE 5
```

**Chaque phase doit être intégralement validée et testée avant de passer à la suivante.**
Les phases 1 et 2 sont des prérequis critiques. Les phases 3, 4 et 5 peuvent être travaillées en parallèle après validation de la phase 2.

---

## Règles pour les agents codeurs

1. **Ne jamais modifier les fichiers V1** sans créer d'abord le module V2 correspondant et valider son comportement.
2. **Respecter les interfaces définies dans `ARCHITECTURE.md`** — les contrats de données entre modules sont intangibles.
3. **Chaque nouveau module doit contenir** un bloc `if __name__ == "__main__"` avec un test minimal auto-exécutable.
4. **Les tests unitaires** sont décrits dans chaque fichier de phase. Les écrire avant le code (TDD léger).
5. **Langue** : code et commentaires en français (cohérence avec le projet V1). Noms de variables en anglais.
