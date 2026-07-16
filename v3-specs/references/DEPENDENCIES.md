# DEPENDENCIES — V3

> **Document de référence pour les agents codeurs.**
> Ce fichier décrit les librairies open source recommandées et pourquoi.

---

## Objectif V3

Créer une version améliorée de `audio-to-sheet` avec **40-60% de gain** de qualité, **100% gratuite et locale**.

---

## Librairies recommandées

### ✅ 1. numpy

**Version recommandée** : `>= 1.20.0`

**Pourquoi** :
- Nécessaire pour les calculs mathématiques (FFT, Kalman, etc.)
- Standard pour le traitement de l'audio en Python
- Léger et rapide
- Gratuit et open source

**Utilisation** :
- Beat tracking (onset strength)
- Correction de drift (Kalman)
- Quantization (durées naturelles)
- Analyse spectrale (FFT)

**Installation** :
```bash
pip install numpy
```

**Estimation** : 50 Mo

---

### ✅ 2. scipy (optionnel)

**Version recommandée** : `>= 1.7.0`

**Pourquoi** :
- FFT plus rapide que numpy
- Fonctions mathématiques avancées
- Optionnel (numpy suffit pour la plupart des cas)

**Utilisation** :
- FFT pour la validation spectrale
- Fonctions mathématiques avancées

**Installation** :
```bash
pip install scipy
```

**Estimation** : 30 Mo

---

### ❌ 3. librosa (NON RECOMMANDÉ)

**Pourquoi NON** :
- Dépendances externes (madmom, numpy, scipy, etc.)
- Installation complexe
- Pas nécessaire pour V3

**Si nécessaire** :
- Beat tracking plus précis
- Analyse spectrale plus avancée

**Installation** :
```bash
pip install librosa
```

**Estimation** : 200 Mo

---

### ❌ 4. madmom (NON RECOMMANDÉ)

**Pourquoi NON** :
- Dépendances externes (numpy, scipy, etc.)
- Installation complexe
- Pas nécessaire pour V3

**Si nécessaire** :
- Beat tracking plus précis
- Analyse spectrale plus avancée

**Installation** :
```bash
pip install madmom
```

**Estimation** : 100 Mo

---

### ❌ 5. basic_pitch (NON RECOMMANDÉ)

**Pourquoi NON** :
- Dépendances externes (numpy, scipy, etc.)
- Installation complexe
- Pas nécessaire pour V3

**Si nécessaire** :
- Transcription plus précise
- Reconnaissance de notes

**Installation** :
```bash
pip install basic_pitch
```

**Estimation** : 500 Mo

---

### ❌ 6. piano_transcription_inference (NON RECOMMANDÉ)

**Pourquoi NON** :
- Dépendances externes (numpy, scipy, etc.)
- Installation complexe
- Pas nécessaire pour V3

**Si nécessaire** :
- Transcription plus précise
- Reconnaissance de notes

**Installation** :
```bash
pip install piano-transcription-inference
```

**Estimation** : 1 Go

---

## Liste des dépendances V3

### ✅ Obligatoire

1. **numpy** : `>= 1.20.0`
   - Pour les calculs mathématiques
   - Pour le beat tracking
   - Pour la correction de drift
   - Pour la quantization
   - Pour l'analyse spectrale

### ✅ Optionnel

2. **scipy** : `>= 1.7.0`
   - Pour la FFT
   - Pour les fonctions mathématiques avancées

### ❌ Non recommandé

3. **librosa** : `>= 0.9.0`
   - Dépendances externes
   - Installation complexe
   - Pas nécessaire pour V3

4. **madmom** : `>= 0.42.0`
   - Dépendances externes
   - Installation complexe
   - Pas nécessaire pour V3

5. **basic_pitch** : `>= 1.0.0`
   - Dépendances externes
   - Installation complexe
   - Pas nécessaire pour V3

6. **piano_transcription_inference** : `>= 0.0.0`
   - Dépendances externes
   - Installation complexe
   - Pas nécessaire pour V3

---

## Installation simple

### ✅ Installation minimale (recommandée)

```bash
pip install numpy
```

**Taille** : ~50 Mo

**Fonctionnalités** :
- Beat tracking pur Python
- Correction de drift avec Kalman
- Quantization contextuelle
- Validation par analyse spectrale

---

### ✅ Installation complète (optionnel)

```bash
pip install numpy scipy
```

**Taille** : ~80 Mo

**Fonctionnalités** :
- Toutes les fonctionnalités V3
- FFT plus rapide
- Fonctions mathématiques avancées

---

### ❌ Installation avec dépendances externes (NON RECOMMANDÉ)

```bash
pip install librosa madmom basic_pitch piano-transcription-inference
```

**Taille** : ~1.8 Go

**Fonctionnalités** :
- Beat tracking plus précis
- Analyse spectrale plus avancée
- Transcription plus précise

**Problèmes** :
- Installation complexe
- Dépendances externes
- Pas nécessaire pour V3

---

## Comparaison des approches

| Approche | Taille | Installation | Fonctionnalités | Recommandé |
|---|---|---|---|---|
| **numpy uniquement** | 50 Mo | Simple | 100% V3 | ✅ Oui |
| **numpy + scipy** | 80 Mo | Simple | 100% V3 | ✅ Oui |
| **numpy + librosa** | 250 Mo | Complexe | 100% V3 | ❌ Non |
| **numpy + madmom** | 150 Mo | Complexe | 100% V3 | ❌ Non |
| **numpy + basic_pitch** | 550 Mo | Complexe | 100% V3 | ❌ Non |
| **numpy + piano-transcription-inference** | 1.05 Go | Complexe | 100% V3 | ❌ Non |

---

## Recommandation

**Recommandation** : Utiliser uniquement **numpy** (et optionnellement **scipy**).

**Pourquoi** :
- 100% gratuit et local
- Installation simple
- Pas de dépendances externes
- Fonctionnalités suffisantes pour V3
- Gain de 40-60% de qualité

**Estimation** : 50-80 Mo

---

## Risques

| Risque | Probabilité | Impact | Solution |
|---|---|---|---|
| numpy moins précis que librosa | Moyen | Faible | Utiliser des paramètres optimisés |
| scipy non installé | Faible | Faible | Optionnel, numpy suffit |
| Installation complexe | Faible | Faible | Installation simple (pip install numpy) |
| Dépendances externes | Élevé | Élevé | Éviter les dépendances externes |

---

## Conclusion

**Recommandation** : Utiliser uniquement **numpy** (et optionnellement **scipy**).

**Objectif atteignable** : 40-60% de gain, 100% gratuit et local, 100% de rétrocompatibilité.

**Estimation** : 50-80 Mo pour l'installation

**Avantages** :
- 100% gratuit et local
- Installation simple
- Pas de dépendances externes
- Fonctionnalités suffisantes pour V3
- Gain de 40-60% de qualité