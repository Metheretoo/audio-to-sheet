# PHASE 1 — Voice Engine amélioré

> **Agent assigné** : Cline
> **Statut** : `[✓]` En cours
> **Durée estimée** : 8-12h
> **Prérequis** : Phase 2 V2 complète (tempo_map.py)
> **Fichiers à modifier** : `backend/voice_engine.py`
> **Fichiers à ne PAS modifier** : `backend/tempo_map.py`, `backend/quantizer.py`

---

## Objectif

Améliorer le Voice Engine pour atteindre **40-50% de gain** de précision dans la séparation main gauche/main droite.

**Problèmes V2 résolus** :
- Règles simples (seuils MIDI fixes)
- Pas d'analyse harmonique des accords
- Contour basique (±1 demi-ton)
- Pas de dynamique
- Continuité rigide

**Nouvelles fonctionnalités** :
- Analyse harmonique des accords (fondamentales, inversions)
- Contour musical avancé (fenêtrage, patterns)
- Lissage adaptatif (Markov, pénalités)
- Intégration de la dynamique (amplitude)

---

## Contexte : ce que le backend V2 envoie maintenant

Le JSON retourné par `/api/transcribe` contient les notes quantisées :

```json
{
  "tempo": 118,
  "timeSignature": [4, 4],
  "keySignature": "G",
  "totalMeasures": 12,
  "measures": [...],
  "notes": [
    {
      "pitch_midi": 60,
      "beat_position": 0.0,
      "beat_duration": 1.0,
      "amplitude": 0.8,
      "hand": "treble"
    }
  ]
}
```

> Ces notes sont déjà quantisées par `quantizer.py`. Le Voice Engine doit les séparer en LH/RH.

---

## Tâche 1.1 — Analyse harmonique des accords

**Fichier** : `backend/voice_engine.py`

### Nouvelle fonction : `analyze_harmony()`

```python
def analyze_harmony(group: List[QuantizedNote]) -> dict:
    """
    Analyse l'accord pour extraire :
    - Fondamentale (note la plus basse)
    - Inversions (position de la fondamentale)
    - Type d'accord (majeur, mineur, 7ème, etc.)
    - Notes de basse (notes graves qui doivent aller à la main gauche)
    
    Retourne un dict avec :
    {
        "root": int,           # MIDI de la fondamentale
        "inversion": int,      # 0 = position basse, 1 = première inversion, etc.
        "bass_notes": List[int], # MIDI des notes de basse
        "chord_type": str      # "M", "m", "7", "maj7", etc.
    }
    """
```

### Algorithme

1. **Fondamentale** : note la plus basse du groupe
2. **Inversion** : nombre de notes plus basses que la fondamentale
3. **Type d'accord** : calculer les intervalles relatifs à la fondamentale
4. **Notes de basse** : notes sous le seuil BASS_ANCHOR (48) + notes graves dans la zone grise

### Tests

```python
# Test 1 : Accord C majeur (Do3-Mi3-Sol3)
# Attendu : root=48, inversion=0, bass_notes=[48, 52, 55]

# Test 2 : Accord C7 (Do3-Mi3-Sol3-Si3)
# Attendu : root=48, inversion=0, bass_notes=[48, 52, 55, 59]

# Test 3 : Accord C6 (Do3-Mi3-Sol3-La3)
# Attendu : root=48, inversion=0, bass_notes=[48, 52, 55, 57]
```

---

## Tâche 1.2 — Contour musical avancé

**Fichier** : `backend/voice_engine.py`

### Nouvelle fonction : `analyze_contour_advanced()`

```python
def analyze_contour_advanced(notes: List[QuantizedNote], window: float = 0.5) -> dict:
    """
    Analyse le contour musical avec fenêtrage.
    
    Retourne un dict avec :
    {
        "direction": str,      # "ascending", "descending", "mixed"
        "jumps": List[int],    # Liste des sauts (en demi-tons)
        "patterns": List[str], # Patterns détectés (ex: "asc-desc-asc")
        "smoothness": float    # Score de lissage (0-1, 1 = très lisse)
    }
    """
```

### Algorithme

1. **Fenêtrage** : grouper les notes par fenêtre de 0.5 beats
2. **Direction** : calculer la tendance globale (moyenne des mouvements)
3. **Sauts** : détecter les sauts > 7 demi-tons (potentiel changement de voix)
4. **Patterns** : identifier des patterns répétitifs (ex: asc-desc-asc)
5. **Smoothness** : calculer le coefficient de variation des intervalles

### Tests

```python
# Test 1 : Contour ascendant (Do4-Sol4-Re5)
# Attendu : direction="ascending", smoothness=0.9

# Test 2 : Contour descendant (Mi5-La4-Sol4)
# Attendu : direction="descending", smoothness=0.85

# Test 3 : Contour mixte (Do4-Sol4-Mi4-La4)
# Attendu : direction="mixed", smoothness=0.7
```

---

## Tâche 1.3 — Lissage adaptatif

**Fichier** : `backend/voice_engine.py`

### Nouvelle fonction : `smooth_voice_split()`

```python
def smooth_voice_split(
    treble: List[QuantizedNote],
    bass: List[QuantizedNote],
    options: dict = None
) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """
    Lisse les changements de main trop fréquents.
    
    Paramètres :
      treble : Liste des notes en main droite
      bass   : Liste des notes en main gauche
      options : dict optionnel avec :
        - max_hand_changes : int (nombre max de changements, défaut: 3)
        - penalty_factor : float (pénalité par changement, défaut: 0.5)
    
    Retourne (treble_lissified, bass_lissified).
    
    Algorithme :
    1. Convertir en graphe de transitions (notes voisines)
    2. Calculer le coût de chaque transition (changements de main)
    3. Trouver le chemin de coût minimum (Dijkstra)
    4. Retourner les notes lissifiées
    """
```

### Algorithme

1. **Graphe de transitions** : chaque note connectée aux notes voisines (beat_position ± 0.1)
2. **Coût de transition** : 0 si même main, 1 si changement de main
3. **Pénalité** : multiplier le coût par `penalty_factor`
4. **Dijkstra** : trouver le chemin de coût minimum
5. **Séparation** : séparer les notes par main

### Tests

```python
# Test 1 : Alternance fréquente (Do4, Sol3, Do4, Sol3)
# Attendu : 2 changements max, notes lissifiées

# Test 2 : Changement unique (Do4, Sol3, Mi3)
# Attendu : 1 changement, pas de lissage nécessaire

# Test 3 : Pas de changement (Do4, Sol4, Mi4)
# Attendu : 0 changement, pas de lissage
```

---

## Tâche 1.4 — Intégration de la dynamique

**Fichier** : `backend/voice_engine.py`

### Nouvelle fonction : `apply_dynamics()`

```python
def apply_dynamics(notes: List[QuantizedNote], options: dict = None) -> List[QuantizedNote]:
    """
    Applique les poids de dynamique aux notes.
    
    Paramètres :
      notes : Liste des notes
      options : dict optionnel avec :
        - amplitude_weight : float (poids pour l'amplitude, défaut: 0.3)
    
    Retourne : Liste des notes avec un champ `dynamic_score` (float)
    """
```

### Algorithme

1. **Normalisation** : normaliser l'amplitude entre 0 et 1
2. **Pondération** : `dynamic_score = amplitude * amplitude_weight`
3. **Priorisation** : les notes avec `dynamic_score > 0.5` sont prioritisées pour la main gauche si bass

### Tests

```python
# Test 1 : Note forte et basse (amplitude=0.9, pitch=52)
# Attendu : dynamic_score=0.27, priorité élevée pour bass

# Test 2 : Note faible et aiguë (amplitude=0.3, pitch=72)
# Attendu : dynamic_score=0.09, priorité faible pour bass
```

---

## Tâche 1.5 — Fonction principale améliorée

**Fichier** : `backend/voice_engine.py`

### Modification de `split_voices()`

```python
def split_voices(
    notes: List[QuantizedNote],
    options: dict = None
) -> VoiceSplit:
    """
    Sépare les notes en deux voix (treble/bass) selon le contexte musical.
    
    Nouveaux paramètres optionnels :
      - use_harmony : bool (activer analyse harmonique, défaut: True)
      - use_contour : bool (activer analyse de contour, défaut: True)
      - use_smoothing : bool (activer lissage, défaut: True)
      - use_dynamics : bool (activer analyse de dynamique, défaut: True)
    
    Algorithme amélioré :
    1. Grouper les notes simultanées en accords
    2. Pour chaque accord, analyser l'harmonie (si use_harmony)
    3. Pour chaque accord, analyser le contour (si use_contour)
    4. Attribuer les notes avec score_decision amélioré
    5. Appliquer la correction de continuité (si use_smoothing)
    6. Appliquer les poids de dynamique (si use_dynamics)
    """
```

---

## Tâche 1.6 — Tests de validation

**Fichier** : `backend/voice_engine.py`

### Auto-test principal

```python
if __name__ == "__main__":
    """
    Test : morceau varié avec différents styles
    Attendu : 40-50% de notes correctes en LH/RH
    """
    from quantizer import QuantizedNote
    
    def make_note(pitch, pos=0.0, dur=1.0, amp=0.7):
        return QuantizedNote(
            pitch_midi=pitch, amplitude=amp,
            beat_position=pos, beat_duration=dur,
            dur_str='q', dots=0, hand='treble'
        )
    
    # Test 1 : Accord C majeur 7ème (Do3-Mi3-Sol3-Si3)
    chord = [
        make_note(48),  # Do3 → bass attendu
        make_note(52),  # Mi3 → bass attendu
        make_note(55),  # Sol3 → bass attendu
        make_note(59),  # Si3 → treble attendu
    ]
    
    result = split_voices(chord)
    
    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")
    
    # Vérifications
    bass_pitches   = {n.pitch_midi for n in result.bass}
    treble_pitches = {n.pitch_midi for n in result.treble}
    
    assert 48 in bass_pitches,   "Do3 doit être en main gauche"
    assert 59 in treble_pitches, "Si3 doit être en main droite"
    print("[Test] ✓ Accord Cmaj7 validé")
    
    # Test 2 : Contour ascendant (Do4-Sol4-Re5)
    contour = [
        make_note(60, 0.0, 1.0, 0.8),
        make_note(67, 1.0, 1.0, 0.7),
        make_note(72, 2.0, 1.0, 0.6),
    ]
    
    result = split_voices(contour)
    
    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")
    
    # Vérifications
    assert 60 in result.treble, "Do4 doit être en main droite"
    assert 72 in result.treble, "Re5 doit être en main droite"
    print("[Test] ✓ Contour ascendant validé")
    
    # Test 3 : Alternance fréquente (Do4, Sol3, Do4, Sol3)
    alternation = [
        make_note(60, 0.0, 1.0, 0.8),
        make_note(55, 1.0, 1.0, 0.7),
        make_note(60, 2.0, 1.0, 0.6),
        make_note(55, 3.0, 1.0, 0.5),
    ]
    
    result = split_voices(alternation)
    
    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")
    
    # Vérifications
    assert len(result.treble) >= 2, "Do4 doit être en main droite (au moins 2 fois)"
    assert len(result.bass) >= 2, "Sol3 doit être en main gauche (au moins 2 fois)"
    print("[Test] ✓ Alternance lissifiée validé")
    
    print("\n[SUCCESS] Tous les tests passés !")
```

---

## Styles CSS à ajouter

**Fichier** : `frontend/css/` (si nécessaire)

```css
/* Indicateurs de voix V3 */
.voice-split-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: rgba(255,255,255,0.08);
    border-radius: 6px;
    font-size: 0.85rem;
}

.voice-badge {
    padding: 2px 8px;
    border-radius: 12px;
    color: white;
    font-size: 0.75rem;
    font-weight: 600;
}

.voice-badge.treble { background: #3498db; }
.voice-badge.bass { background: #e74c3c; }
```

---

## Tests de validation

| Test | Description | Attendu |
|---|---|---|
| 1.1 | Accord C majeur 7ème | Do3, Mi3, Sol3 → bass ; Si3 → treble |
| 1.1 | Accord C6 | Do3, Mi3, Sol3, La3 → bass |
| 1.2 | Contour ascendant | Do4, Sol4, Re5 → treble |
| 1.2 | Contour descendant | Mi5, La4, Sol4 → bass |
| 1.3 | Alternance fréquente | 2 changements max, notes lissifiées |
| 1.4 | Note forte et basse | Priorité élevée pour bass |
| 1.5 | Test complet | 40-50% de notes correctes |

---

## Risques et solutions

| Risque | Solution |
|---|---|
| Analyse harmonique complexe | Implémenter une version simplifiée (fondamentale + inversions) |
| Performance lissage Dijkstra | Utiliser un algorithme plus simple (Markov) |
| Incompatibilité V2 | Garantir la rétrocompatibilité (JSON VexFlow identique) |
| Tests insuffisants | Tester sur 50+ morceaux variés |

---

## Implémentation - Tâche 1.3 : Lissage adaptatif (À implémenter)

### smooth_voice_split()

```python
def smooth_voice_split(
    treble: List[QuantizedNote],
    bass: List[QuantizedNote],
    options: dict = None
) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """
    Lisse les changements de main trop fréquents.
    
    Paramètres :
      treble : Liste des notes en main droite
      bass   : Liste des notes en main gauche
      options : dict optionnel avec :
        - max_hand_changes : int (nombre max de changements, défaut: 3)
        - penalty_factor : float (pénalité par changement, défaut: 0.5)
    
    Retourne (treble_lissified, bass_lissified).
    
    Algorithme :
    1. Combiner les notes et les trier par beat_position
    2. Pour chaque note, calculer un score de préférence (grave=left, aigu=right)
    3. Appliquer une pénalité pour les changements de main consécutifs
    4. Utiliser un algorithme de type Viterbi/Markov pour trouver la séquence optimale
    """
```

**Implémentation** :
- Combiner toutes les notes et les trier par beat_position
- Pour chaque note, calculer un score de préférence basé sur le pitch
- Appliquer une pénalité de `penalty_factor` pour chaque changement de main
- Utiliser un algorithme de dynamique programming pour trouver la séquence optimale
- Séparer les notes selon la séquence optimale

## Métriques de succès

- **Gain attendu** : 40-50% de notes correctes en LH/RH
- **Tests** : 50+ morceaux variés
- **Performance** : < 1 seconde pour 1000 notes
- **Rétrocompatibilité** : 100% avec V2
