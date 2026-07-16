# PHASE 3 — Quantization contextuelle

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 8-10h
> **Prérequis** : Phase 2 V2 complète (tempo_map.py)
> **Fichiers à modifier** : `backend/quantizer.py`
> **Fichiers à ne PAS modifier** : `backend/tempo_map.py`, `backend/voice_engine.py`

---

## Objectif

Améliorer la quantization pour atteindre **35-45% de gain** de précision en utilisant le contexte musical.

**Problèmes V2 résolus** :
- Quantization brute (arrondi simple)
- Pas de contexte musical
- Durées artificielles
- Pas de gestion des micro-détails
- Pas de validation

**Nouvelles fonctionnalités** :
- Contexte musical (tonalité, mesure, voix)
- Durées naturelles (demi-temps, triplets)
- Gestion des micro-détails (accents, nuances)
- Lissage des transitions
- Validation par analyse spectrale

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

> La quantization est utilisée par `score_builder.py` pour générer la partition.

---

## Tâche 3.1 — Analyse du contexte musical

**Fichier** : `backend/quantizer.py`

### Nouvelle fonction : `analyze_context()`

```python
def analyze_context(
    notes: List[QuantizedNote],
    tempo_map: TempoMap,
    key_signature: str,
    time_signature: Tuple[int, int]
) -> dict:
    """
    Analyse le contexte musical pour la quantization.
    
    Paramètres :
      notes : Liste des notes
      tempo_map : TempoMap
      key_signature : Tonalité (ex: "G", "Cm")
      time_signature : Signature temporelle (ex: [4, 4])
    
    Retourne un dict avec :
    {
        "key_signature": str,
        "time_signature": Tuple[int, int],
        "tempo": float,
        "context_type": str,  # "tonic", "dominant", "subdominant", "other"
        "expected_duration": float,  # Durée attendue (en beats)
        "voice_context": str,  # "melody", "accompaniment"
    }
    """
```

### Algorithme

1. **Tonality** : analyser la tonalité pour identifier les degrés
2. **Signature temporelle** : extraire la signature
3. **Tempo** : récupérer le tempo global
4. **Contexte** : déterminer le contexte musical (tonique, dominante, etc.)
5. **Voix** : identifier si c'est une mélodie ou un accompagnement

### Tests

```python
# Test 1 : Tonique (Do majeur)
# Attendu : context_type="tonic", expected_duration=1.0

# Test 2 : Dominante (Sol majeur)
# Attendu : context_type="dominant", expected_duration=1.0

# Test 3 : Signature 3/4
# Attendu : time_signature=[3, 4]
```

---

## Tâche 3.2 — Durées naturelles

**Fichier** : `backend/quantizer.py`

### Nouvelle fonction : `quantize_with_natural_durations()`

```python
def quantize_with_natural_durations(
    notes: List[QuantizedNote],
    tempo_map: TempoMap,
    context: dict
) -> List[QuantizedNote]:
    """
    Quantize avec des durées naturelles (demi-temps, triplets, etc.).
    
    Paramètres :
      notes : Liste des notes
      tempo_map : TempoMap
      context : Contexte musical
    
    Retourne : Liste des notes quantizées avec durées naturelles
    
    Algorithme :
    1. Déterminer la durée naturelle pour chaque note
    2. Gérer les demi-temps (0.5 beats)
    3. Gérer les triplets (0.66 beats)
    4. Gérer les points (1.5 beats)
    5. Gérer les silences parasites
    """
```

### Algorithme

1. **Demi-temps** : notes avec beat_position = 0.5 → durée = 0.5
2. **Triplets** : notes avec beat_position = 0.33 ou 0.66 → durée = 0.66
3. **Points** : notes avec beat_position = 0.0 → durée = 1.5
4. **Silences** : détecter et supprimer les silences parasites (< 0.1 beats)
5. **Lissage** : ajuster les transitions pour éviter les micro-détails

### Tests

```python
# Test 1 : Note à demi-temps
# Attendu : beat_duration = 0.5

# Test 2 : Note à triplet
# Attendu : beat_duration = 0.66

# Test 3 : Note pointée
# Attendu : beat_duration = 1.5

# Test 4 : Silence parasite
# Attendu : supprimé
```

---

## Tâche 3.3 — Gestion des micro-détails

**Fichier** : `backend/quantizer.py`

### Nouvelle fonction : `handle_micro_details()`

```python
def handle_micro_details(
    notes: List[QuantizedNote],
    context: dict
) -> List[QuantizedNote]:
    """
    Gère les micro-détails (accents, nuances, etc.).
    
    Paramètres :
      notes : Liste des notes
      context : Contexte musical
    
    Retourne : Liste des notes avec micro-détails gérés
    
    Algorithme :
    1. Détecter les accents (notes fortes)
    2. Détecter les nuances (notes douces)
    3. Gérer les micro-détails (trill, mordent, etc.)
    4. Supprimer les micro-détails parasites
    """
```

### Algorithme

1. **Accents** : notes avec amplitude > 0.8 → marquer comme accent
2. **Nuances** : notes avec amplitude < 0.3 → marquer comme douces
3. **Micro-détails** : détecter les micro-détails (trill, mordent, etc.)
4. **Parasites** : supprimer les micro-détails parasites (< 0.05 beats)

### Tests

```python
# Test 1 : Note forte (amplitude=0.9)
# Attendu : accent détecté

# Test 2 : Note douce (amplitude=0.2)
# Attendu : nuance douce détectée

# Test 3 : Micro-détail parasite
# Attendu : supprimé
```

---

## Tâche 3.4 — Lissage des transitions

**Fichier** : `backend/quantizer.py`

### Nouvelle fonction : `smooth_transitions()`

```python
def smooth_transitions(
    notes: List[QuantizedNote],
    context: dict
) -> List[QuantizedNote]:
    """
    Lisser les transitions entre notes.
    
    Paramètres :
      notes : Liste des notes
      context : Contexte musical
    
    Retourne : Liste des notes avec transitions lissées
    
    Algorithme :
    1. Détecter les transitions brusques (sauts > 7 demi-tons)
    2. Lisser les transitions (ajuster les durées)
    3. Gérer les patterns répétitifs
    4. Éviter les micro-détails parasites
    """
```

### Algorithme

1. **Sauts brusques** : détecter les sauts > 7 demi-tons
2. **Lissage** : ajuster les durées pour éviter les micro-détails
3. **Patterns** : identifier et conserver les patterns répétitifs
4. **Parasites** : supprimer les micro-détails parasites (< 0.1 beats)

### Tests

```python
# Test 1 : Saut brusque (Do4-Sol4)
# Attendu : lissage appliqué

# Test 2 : Pattern répétitif (Do4-Sol4-Do4-Sol4)
# Attendu : pattern conservé

# Test 3 : Micro-détail parasite
# Attendu : supprimé
```

---

## Tâche 3.5 — Validation par analyse spectrale

**Fichier** : `backend/quantizer.py`

### Nouvelle fonction : `validate_quantization()`

```python
def validate_quantization(
    notes: List[QuantizedNote],
    audio_path: str,
    tempo_map: TempoMap
) -> dict:
    """
    Valide la quantization en analysant l'audio.
    
    Paramètres :
      notes : Liste des notes quantizées
      audio_path : chemin vers le fichier audio
      tempo_map : TempoMap
    
    Retourne : dict avec :
    {
        "is_valid": bool,
        "error_count": int,
        "notes_correct": int,
        "notes_incorrect": int,
        "notes_correct_rate": float,
    }
    """
```

### Algorithme

1. **FFT** : calculer la transformée de Fourier de l'audio
2. **Analyse** : comparer les notes quantizées avec l'audio
3. **Validation** : vérifier la cohérence des notes
4. **Erreur** : compter les notes incorrectes
5. **Taux** : calculer le taux de notes correctes

### Tests

```python
# Test 1 : Quantization valide
# Attendu : is_valid=True, notes_correct_rate > 0.8

# Test 2 : Quantization invalide
# Attendu : is_valid=False, notes_correct_rate < 0.8
```

---

## Tâche 3.6 — Fonction principale améliorée

**Fichier** : `backend/quantizer.py`

### Modification de `quantize_notes()`

```python
def quantize_notes(
    notes: List[NoteEvent],
    tempo_map: TempoMap,
    key_signature: str,
    time_signature: Tuple[int, int]
) -> List[QuantizedNote]:
    """
    Quantize les notes avec contexte musical.
    
    Ordre de traitement (V3) :
      1. Analyse du contexte musical
      2. Quantization avec durées naturelles
      3. Gestion des micro-détails
      4. Lissage des transitions
      5. Validation
    
    Paramètres :
      notes : Liste des notes non quantizées
      tempo_map : TempoMap
      key_signature : Tonalité
      time_signature : Signature temporelle
    
    Retourne : Liste des notes quantizées
    """
```

---

## Tâche 3.7 — Tests de validation

**Fichier** : `backend/quantizer.py`

### Auto-test principal

```python
if __name__ == "__main__":
    """
    Test : morceau varié avec différents styles
    Attendu : 35-45% de durées naturelles
    """
    from tempo_map import TempoMap
    from voice_engine import VoiceSplit
    
    def make_note(pitch, pos=0.0, dur=1.0, amp=0.7):
        return NoteEvent(
            pitch_midi=pitch, onset=pos, duration=dur,
            amplitude=amp, velocity=80
        )
    
    # Test 1 : Morceau avec demi-temps
    notes = [
        make_note(60, 0.0, 1.0, 0.8),   # Do4
        make_note(67, 0.5, 1.0, 0.7),   # Sol4 (demi-temps)
        make_note(72, 1.0, 1.0, 0.6),   # Re5
    ]
    
    # Simuler une TempoMap
    tm = TempoMap()
    tm.global_bpm = 120.0
    tm.beat_times = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    
    quantized = quantize_notes(notes, tm, "C", (4, 4))
    
    print("\n[Test] Notes quantizées avec contexte")
    for note in quantized:
        print(f"  {note.pitch_midi} @ {note.beat_position:.2f} dur={note.beat_duration:.2f}")
    
    # Vérifications
    durations = [n.beat_duration for n in quantized]
    has_half = any(abs(d - 0.5) < 0.1 for d in durations)
    has_triplet = any(abs(d - 0.66) < 0.1 for d in durations)
    
    print(f"\n[Test] Durées naturelles : half={has_half}, triplet={has_triplet}")
    
    # Test 2 : Morceau avec silences parasites
    notes2 = [
        make_note(60, 0.0, 1.0, 0.8),
        make_note(60, 0.1, 0.1, 0.0),  # Silence parasite
        make_note(67, 0.5, 1.0, 0.7),
    ]
    
    quantized2 = quantize_notes(notes2, tm, "C", (4, 4))
    
    print(f"\n[Test] Notes quantizées (sans silences parasites)")
    for note in quantized2:
        print(f"  {note.pitch_midi} @ {note.beat_position:.2f} dur={note.beat_duration:.2f}")
    
    # Vérifications
    silence_count = sum(1 for n in quantized2 if n.beat_duration < 0.1)
    print(f"\n[Test] Silences parasites : {silence_count}")
    
    if has_half and has_triplet and silence_count == 0:
        print("\n[Test] SUCCES - Tous les tests de quantization sont passes")
    else:
        print("\n[Test] ATTENTION - Certains tests de quantization ont échoué")
```

---

## Styles CSS à ajouter

**Fichier** : `frontend/css/` (si nécessaire)

```css
/* Indicateurs de quantization V3 */
.quantization-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: rgba(255,255,255,0.08);
    border-radius: 6px;
    font-size: 0.85rem;
}

.quantization-badge {
    padding: 2px 8px;
    border-radius: 12px;
    color: white;
    font-size: 0.75rem;
    font-weight: 600;
}

.quantization-badge.natural { background: #9b59b6; }
.quantization-badge.micro { background: #e67e22; }
.quantization-badge.smooth { background: #1abc9c; }
```

---

## Tests de validation

| Test | Description | Attendu |
|---|---|---|
| 3.1 | Analyse contexte musical | Contexte détecté |
| 3.2 | Durées naturelles | Durées = 0.5, 0.66, 1.5 |
| 3.2 | Demi-temps | beat_duration = 0.5 |
| 3.2 | Triplets | beat_duration = 0.66 |
| 3.2 | Points | beat_duration = 1.5 |
| 3.2 | Silences parasites | Supprimés |
| 3.3 | Accents | Détectés |
| 3.3 | Nuances | Détectées |
| 3.3 | Micro-détails parasites | Supprimés |
| 3.4 | Sauts brusques | Lisssés |
| 3.4 | Patterns répétitifs | Conservés |
| 3.5 | Validation spectrale | Validation = True |
| 3.5 | Taux correct | > 80% |

---

## Risques et solutions

| Risque | Solution |
|---|---|
| Durées naturelles complexes | Implémenter une version simplifiée |
| Performance validation spectrale | Utiliser FFT simplifiée |
| Incompatibilité V2 | Garantir la rétrocompatibilité (JSON VexFlow identique) |
| Tests insuffisants | Tester sur 50+ morceaux variés |

---

## Métriques de succès

- **Gain attendu** : 35-45% de durées naturelles
- **Tests** : 50+ morceaux variés
- **Performance** : < 1 seconde pour 1000 notes
- **Rétrocompatibilité** : 100% avec V2
- **Dépendances** : numpy uniquement (pas madmom/librosa)