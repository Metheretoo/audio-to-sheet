# FAISABILITÉ — V3

> **Document de référence pour les agents codeurs.**
> Ce fichier décrit les limites techniques, ce qui est possible / impossible en V3.

---

## Objectif V3

Créer une version améliorée de `audio-to-sheet` avec **40-60% de gain** de qualité, **100% gratuite et locale**.

---

## Ce qui est POSSIBLE en V3

### ✅ 1. Voice Engine amélioré (40-50% gain)

**Technologies** :
- Python standard + numpy
- Analyse harmonique simplifiée (fondamentale + inversions)
- Contour musical (fenêtrage, patterns)
- Lissage adaptatif (Markov, pénalités)
- Intégration de la dynamique (amplitude)

**Ce qui est possible** :
- Analyse des accords (fondamentale, inversions, type d'accord)
- Détecter les patterns musicaux (ascendant, descendant, mixte)
- Lisser les changements de main (max 3 changements)
- Prioriser les notes fortes pour la main gauche
- Garantir la rétrocompatibilité avec V2

**Ce qui n'est PAS possible** :
- Analyse harmonique complète (accords complexes, extensions)
- Reconnaissance de style musical (classique, jazz, pop)
- Gestion des micro-détails (trill, mordent, glissando)
- Séparation instrumentale (piano seul)

**Estimation** : 40-50% de gain

---

### ✅ 2. Tempo Map pur Python (30-40% gain)

**Technologies** :
- Python standard + numpy
- Beat tracking avec algorithme de Davies & Plumbley
- Correction de drift avec filtre Kalman
- Validation par analyse spectrale
- Fallback robuste

**Ce qui est possible** :
- Beat tracking sans dépendances externes (madmom/librosa)
- Correction de drift (linéaire et non linéaire)
- Validation par FFT
- Fallback avec correction de drift
- Garantir la rétrocompatibilité avec V2

**Ce qui n'est PAS possible** :
- Beat tracking aussi précis que madmom/librosa
- Analyse fine du rubato/ritardando
- Détection de variations de tempo complexes
- Gestion des changements de signature temporelle

**Estimation** : 30-40% de gain

---

### ✅ 3. Quantization contextuelle (35-45% gain)

**Technologies** :
- Python standard + numpy
- Contexte musical (tonalité, mesure, voix)
- Durées naturelles (demi-temps, triplets, points)
- Gestion des micro-détails (accents, nuances)
- Lissage des transitions
- Validation par analyse spectrale

**Ce qui est possible** :
- Durées naturelles (0.5, 0.66, 1.5 beats)
- Détecter les accents et nuances
- Lisser les transitions brusques
- Supprimer les silences parasites
- Garantir la rétrocompatibilité avec V2

**Ce qui n'est PAS possible** :
- Quantization parfaite (100% de précision)
- Gestion des micro-détails complexes (trill, mordent, glissando)
- Reconnaissance de style musical
- Gestion des nuances complexes (crescendo, decrescendo)

**Estimation** : 35-45% de gain

---

## Ce qui est IMPOSSIBLE en V3

### ❌ 1. Transcription parfaite

- **Problème** : Les modèles de transcription (CRNN, basic_pitch) ont des erreurs intrinsèques
- **Solution** : Accepter les erreurs et les corriger avec le contexte musical
- **Impact** : 20-30% de notes incorrectes restent

### ❌ 2. Séparation instrumentale

- **Problème** : Le piano est un instrument polyphonique (plusieurs notes simultanées)
- **Solution** : Accepter la séparation LH/RH et gérer les ambiguïtés
- **Impact** : 10-20% de notes mal attribuées

### ❌ 3. Reconnaissance de style musical

- **Problème** : Différents styles ont des conventions différentes
- **Solution** : Utiliser des règles générales et accepter les erreurs
- **Impact** : 5-10% de notes incorrectes

### ❌ 4. Gestion des micro-détails

- **Problème** : Les micro-détails (trill, mordent, glissando) sont difficiles à détecter
- **Solution** : Ignorer les micro-détails ou les simplifier
- **Impact** : 5-10% de micro-détails perdus

---

## Contraintes de performance

### ✅ 1. Performance acceptable

- **Temps de transcription** : < 10 secondes pour 5 minutes d'audio
- **Temps de quantization** : < 1 seconde pour 1000 notes
- **Temps de voice engine** : < 0.5 seconde pour 1000 notes
- **Temps de tempo map** : < 2 secondes pour 5 minutes d'audio

### ✅ 2. Performance acceptable

- **Utilisation mémoire** : < 500 Mo pour 5 minutes d'audio
- **Utilisation CPU** : < 50% pour 5 minutes d'audio
- **Utilisation GPU** : Non nécessaire (pas de deep learning)

---

## Contraintes de dépendances

### ✅ 1. Dépendances minimales

- **numpy** : Oui (pour les calculs mathématiques)
- **scipy** : Non (optionnel, pour FFT)
- **librosa** : Non (pas de dépendances externes)
- **madmom** : Non (pas de dépendances externes)
- **basic_pitch** : Non (pas de dépendances externes)
- **piano_transcription_inference** : Non (pas de dépendances externes)

### ✅ 2. Installation simple

- **pip install numpy** : Oui
- **pip install scipy** : Optionnel
- **pip install -r requirements.txt** : Oui (numpy uniquement)

---

## Contraintes de rétrocompatibilité

### ✅ 1. JSON VexFlow identique

- **Format JSON** : Identique à V2
- **Champs** : Identiques à V2
- **Structure** : Identique à V2
- **Impact** : 100% de rétrocompatibilité

### ✅ 2. Frontend identique

- **HTML** : Identique à V2
- **CSS** : Identique à V2
- **JS** : Identique à V2
- **Impact** : 100% de rétrocompatibilité

---

## Risques et solutions

| Risque | Probabilité | Impact | Solution |
|---|---|---|---|
| Beat tracking numpy moins précis | Moyen | Moyen | Utiliser des paramètres optimisés |
| Performance lissage Kalman | Faible | Faible | Utiliser un filtre simplifié |
| Incompatibilité V2 | Faible | Élevé | Garantir la rétrocompatibilité (JSON VexFlow identique) |
| Tests insuffisants | Moyen | Élevé | Tester sur 50+ morceaux variés |
| Erreurs de transcription | Élevé | Élevé | Accepter les erreurs et les corriger avec le contexte |

---

## Métriques de succès

### ✅ 1. Gain global

- **Voice Engine** : 40-50% de notes correctes en LH/RH
- **Tempo Map** : 30-40% de BPM corrects, pas de drift
- **Quantization** : 35-45% de durées naturelles
- **Global** : 40-60% de gain sur la qualité de la partition

### ✅ 2. Performance

- **Temps de transcription** : < 10 secondes pour 5 minutes d'audio
- **Temps de quantization** : < 1 seconde pour 1000 notes
- **Temps de voice engine** : < 0.5 seconde pour 1000 notes
- **Temps de tempo map** : < 2 secondes pour 5 minutes d'audio

### ✅ 3. Rétrocompatibilité

- **JSON VexFlow** : 100% identique à V2
- **Frontend** : 100% identique à V2
- **API** : 100% identique à V2

### ✅ 4. Dépendances

- **numpy** : Oui (obligatoire)
- **scipy** : Non (optionnel)
- **librosa** : Non (pas de dépendances externes)
- **madmom** : Non (pas de dépendances externes)

---

## Conclusion

**V3 est faisable** avec un gain global de **40-60%** de qualité de la partition, tout en garantissant la rétrocompatibilité avec V2 et en utilisant uniquement des dépendances gratuites et locales.

**Objectif atteignable** : 40-60% de gain, 100% gratuit et local, 100% de rétrocompatibilité.

**Estimation globale** : 22-28h de travail (8-12h + 6-8h + 8-10h)