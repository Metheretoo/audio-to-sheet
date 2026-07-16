# Feuille de route et Idées d'améliorations (V4 → V5+)

Ce document recense les améliorations algorithmiques et architecturales possibles,
classées par ratio **Impact visuel (qualité de partition) / Effort d'implémentation**.

> **Note** : L'ordre strict d'implémentation des étapes V4.0 est défini dans
> `TRANSCRIPTION_QUALITY.md §7`. Ce document est complémentaire pour les idées
> plus exploratoires (V4.2+, V5).

---

## MVP Qualité V4.0 — Les incontournables (Rappel)

> Les étapes détaillées sont dans `TRANSCRIPTION_QUALITY.md`. Cette section rappelle
> brièvement les problèmes que ces étapes résolvent.

### 1. Extension de la durée liée à la Pédale (Pedal-Aware Duration)

- **Problème :** On joue staccato avec pédale → le modèle détecte une note longue → partition illisible.
- **Solution :** Si note > 1s dans une zone de pédale, raccourcir la durée notée à ~0.4s.
- **Impact :** `+25%` (partition beaucoup plus aérée et naturelle).

### 2. Beat Tracking madmom + Time Signature automatique

- **Problème :** Chopin Mazurka = 3/4. Le rendu actuel affiche 4/4 → toute la partition est fausse.
- **Solution :** `madmom.RNNDownBeatProcessor` avec vote majoritaire.
- **Impact :** `+45%` (la time signature correcte change tout le rendu).

### 3. Quantification sur Grille Locale (Local Beat Grid)

- **Problème :** Le drift cumulatif vient du calcul `onset_sec / (60/BPM_global)`.
- **Solution :** Utiliser `beat_times[]` de madmom. Pour chaque note, chercher le beat encadrant.
- **Impact :** `-70%` de notes parasites, zéro drift.

### 4. Filtrage des notes "Fantômes" (Harmoniques)

- **Problème :** Les modèles ML détectent souvent l'octave ou la quinte d'une note de basse forte.
- **Solution :** Supprimer si velocity faible + simultané + intervalle = 12 ou 19 demi-tons.
- **Impact :** `+20%` (partition beaucoup plus propre dans les basses).

### 5. Chunking Audio (Fenêtres glissantes)

- **Problème :** Fichier de 15 minutes → OOM (crash RAM/VRAM).
- **Solution :** `transcriber.py` découpe en segments de 30s (chevauchement 1s)
  et concatène les NoteEvent en déduisant les doublons dans la zone de chevauchement.
- **Impact :** `+100% stabilité` (zéro crash sur longs morceaux).
- **Effort :** `Moyen` (logique de tuilage + déduplication).
- **Cible :** **V4.0 — Étape 1 bis (intégrer dans transcriber.py)**

---

## Priorité Moyenne (V4.2 → V5.0)

Idées demandant plus de R&D ou risque de régression, à garder pour après
la stabilisation de l'architecture V4.

### 6. Aplatissement Temporel Dynamique (Tempo Flattening)

- **Problème :** Même avec beat_times[], le rubato extrême génère quelques
  triolets ou quintolets là où Chopin écrit de simples croches.
- **Solution :** DTW (`librosa.sequence.dtw`) pour déformer le temps continu
  vers une grille métronomique *avant* quantification.
- **Impact :** `+40%` sur la musique romantique, mais risque de régression pop/jazz.
- **Effort :** `Élevé` (DTW + mapping beats → grille, validation croisée).
- **Cible :** **V5.0** (optionnel via config)

### 7. Correction Ergonomique (Validation Physique)

- **Problème :** L'IA affecte à la main gauche un accord dont l'écartement
  dépasse la douzième (impossible pour une main humaine).
- **Solution :** Règles d'ergonomie dans `voice_engine.py` :
  pénalité si `max_pitch - min_pitch > 17 demi-tons` à un instant T.
- **Impact :** `+30%` crédibilité pour les pianistes.
- **Effort :** `Élevé` (complexifie l'algo Dijkstra).
- **Cible :** **V5.0**

---

## Ce qui est très complexe voire impossible (limites du domaine)

Il faut être honnête sur les limites pour ne pas surestimer la V4 :

| Fonctionnalité | Limite | Statut |
|----------------|--------|--------|
| Rubato parfaitement "aplati" | Impossible sans MIDI source (info perdue dans audio) | Approximatif seulement |
| Ornements complexes (gruppetti multi-notes) | Durée < 50ms, modèles IA peu fiables | Partiel |
| Doigtés optimaux | Dépend de la main du pianiste, NP-difficile | Heuristique seulement |
| Harmonie jazz complexe (altérations) | Requiert théorie harmonique avancée | V5+ |
| Séparation parfaite LH/RH style brisé | Ambiguïté fondamentale (cf. "Raindrop Prelude") | Approximatif |

---

## Références

- `TRANSCRIPTION_QUALITY.md` — Priorités d'implémentation V4.0
- `ARCHITECTURE.md` — Organisation des modules
- `API_CONTRACTS.md` — Contrats de données
