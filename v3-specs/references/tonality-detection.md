# Référence : Détection de Tonalité

> Spécification détaillée pour le module `tonality_detector.py`.

---

## Objectif

Identifier la tonalité (key) d'un segment audio en utilisant des algorithmes de Krumhansl-Schum et Parncutt.

---

## Entrées

| Paramètre | Type | Description |
|-----------|------|-------------|
| `audio_segment` | `np.ndarray` | Segment audio (float64, mono) |
| `sample_rate` | `int` | Échantillonnage (ex: 22050 Hz) |

## Sortie

| Valeur | Type | Description |
|--------|------|-------------|
| `key` | `str` | Tonalité détectée (ex: 'C', 'Am', 'Bb') |
| `confidence` | `float` | Confiance de la détection [0.0, 1.0] |
| `key_profile` | `np.ndarray` | Vecteur de profil K-S (12 valeurs) |

---

## Algorithme 1 : Krumhansl-Schum (K-S)

### Étape 1 : Chroma Extraction

1. Calculer le **chromagramme** de l'audio segment
2. Utiliser STFT (Short-Time Fourier Transform) via `librosa` ou `numpy`
3. Regrouper les bins FFT en 12 classes chromatiques (C, C#, D, ..., B)
4. Normaliser le chromagramme en [0, 1]

### Étape 2 : Corrélation avec Profils K-S

1. Charger le **profil Krumhansl-Schum** majeur (12 valeurs)
2. Charger le **profil Krumhansl-Schum** mineur (12 valeurs)
3. Calculer la corrélation entre le chromagramme et chaque profil
4. Sélectionner la tonalité avec la corrélation la plus élevée

### Profils K-S (majeur)

```
Index:  0   1   2   3   4   5   6   7   8   9  10  11
Note:   C  C#   D  D#   E   F  F#   G  G#   A  A#   B
Profil: 4.38 2.55 3.48 1.67 3.69 3.47 1.66 4.28 2.37 3.48 2.35 2.86
```

### Profils K-S (mineur)

```
Index:  0   1   2   3   4   5   6   7   8   9  10  11
Note:   C  C#   D  D#   E   F  F#   G  G#   A  A#   B
Profil: 3.96 2.82 2.66 3.48 1.66 2.74 3.66 2.36 3.55 2.86 3.73 2.45
```

### Formule de corrélation (Pearson)

```
r(X, Y) = Σ((x_i - mean(X)) * (y_i - mean(Y))) / sqrt(Σ(x_i - mean(X))² * Σ(y_i - mean(Y))²)
```

### Décision

- Si `correlation_majeur > correlation_mineur` → tonalité majeure
- Sinon → tonalité mineure
- Le nom de la tonalité est la note d'index avec la corrélation la plus élevée dans le profil gagnant

---

## Algorithme 2 : Parncutt

### Principe

Similaire à K-S mais utilise un **profil de tonalité alternatif** plus sensible aux nuances.

### Profils Parncutt (majeur)

```
Index:  0   1   2   3   4   5   6   7   8   9  10  11
Note:   C  C#   D  D#   E   F  F#   G  G#   A  A#   B
Profil: 0.85 0.28 0.62 0.15 0.78 0.58 0.12 0.82 0.25 0.65 0.18 0.45
```

### Décision

Même approche que K-S : corréler + sélectionner le meilleur match.

---

## Fusion des Deux Algorithmes

### Pondération

```
score_final = 0.6 * score_KS + 0.4 * score_Parncutt
```

### Implémentation

1. Calculer les scores K-S pour chaque tonalité (24 candidates : 12 majeures + 12 mineures)
2. Calculer les scores Parncutt pour chaque tonalité
3. Fusionner les scores avec la pondération
4. Retourner la tonalité avec le score final le plus élevé

---

## Fichier de Sortie

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class KeyDetection:
    key: str                    # Ex: 'C', 'Am', 'Bb'
    confidence: float           # [0.0, 1.0]
    key_profile: np.ndarray     # 12 valeurs (chroma vector)
    algorithm: str              # 'ks', 'parncutt', ou 'fused'
    
    def __repr__(self):
        return f"KeyDetection(key={self.key}, confidence={self.confidence:.3f})"
```

---

## Exemple d'Utilisation

```python
from tonality_detector import detect_key

detection = detect_key(audio_segment, sample_rate=22050)
print(detection)
# Output: KeyDetection(key='C', confidence=0.842)
```

---

## Notes d'Implémentation

1. **Sans dépendances externes** : Utiliser uniquement `numpy` pour les calculs FFT
2. **Performance** : Le chroma doit être calculé efficacement (pas de boucles Python)
3. **Robustesse** : Gérer les segments très courts (> 0.5s recommandé)
4. **Testabilité** : Fournir des cas de test avec des tons purs connus