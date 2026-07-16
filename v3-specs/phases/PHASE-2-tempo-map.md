# PHASE 2 — Tempo Map pur Python

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 6-8h
> **Prérequis** : Phase 1 V2 complète (voice_engine.py)
> **Fichiers à modifier** : `backend/tempo_map.py`
> **Fichiers à ne PAS modifier** : `backend/voice_engine.py`, `backend/quantizer.py`

---

## Objectif

Créer un Tempo Map pur Python (sans dépendances externes) pour atteindre **30-40% de gain** de précision et garantir la compatibilité 100% locale.

**Problèmes V2 résolus** :
- Dépendances externes (madmom/librosa)
- Fallback IOI identique V1 (drift non corrigé)
- Pas de validation
- Pas de correction de drift

**Nouvelles fonctionnalités** :
- Beat tracking pur Python avec numpy
- Correction de drift avec filtre Kalman
- Validation par analyse spectrale
- Fallback robuste

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

> Le Tempo Map est utilisé par `quantizer.py` pour quantifier les notes.

---

## Tâche 2.1 — Beat tracking pur Python

**Fichier** : `backend/tempo_map.py`

### Nouvelle fonction : `_build_with_numpy()`

```python
def _build_with_numpy(audio_path: str) -> TempoMap:
    """
    Beat tracking pur Python avec numpy.
    
    Algorithme :
    1. Charger l'audio avec numpy (pas de librosa)
    2. Calculer l'enveloppe d'attaque (onset strength)
    3. Détecter les beats avec l'algorithme de Davies & Plumbley
    4. Estimer le tempo avec la médiane des IOI
    5. Détecter les downbeats heuristiques
    
    Retourne : TempoMap
    """
```

### Algorithme

1. **Chargement audio** : utiliser `numpy` pour lire le fichier audio
2. **Onset strength** : calculer l'énergie de chaque frame
3. **Beat tracking** : utiliser l'algorithme de Davies & Plumbley (inspiré de librosa)
4. **Tempo estimation** : médiane des IOI (Inter-Onset Intervals)
5. **Downbeats** : tous les 4 beats (fallback)

### Tests

```python
# Test 1 : Morceau avec tempo stable (120 BPM)
# Attendu : global_bpm ≈ 120, beats détectés

# Test 2 : Morceau avec tempo variable (ritardando)
# Attendu : beats avec variations de tempo

# Test 3 : Fallback si pas de beats détectés
# Attendu : TempoMap avec BPM fixe
```

---

## Tâche 2.2 — Correction de drift avec Kalman

**Fichier** : `backend/tempo_map.py`

### Nouvelle fonction : `_correct_drift()`

```python
def _correct_drift(beat_times: np.ndarray, global_bpm: float) -> np.ndarray:
    """
    Corrige le drift du tempo avec un filtre Kalman.
    
    Paramètres :
      beat_times : array des timestamps des beats
      global_bpm : BPM médian initial
    
    Retourne : array des timestamps corrigés
    
    Algorithme :
    1. Initialiser le filtre Kalman (état = beat_position, mesure = timestamp)
    2. Estimer le drift (écart entre beats attendus et réels)
    3. Lisser les timestamps avec le filtre
    4. Retourner les timestamps corrigés
    """
```

### Algorithme

1. **Initialisation Kalman** : état = beat_position, mesure = timestamp
2. **Estimation du drift** : calculer l'écart entre beats attendus et réels
3. **Lissage** : appliquer le filtre Kalman pour lisser les variations
4. **Extrapolation** : extrapoler les beats avant/après la plage

### Tests

```python
# Test 1 : Drift linéaire (bpm décroissant)
# Attendu : drift corrigé, beats alignés

# Test 2 : Drift non linéaire (variations complexes)
# Attendu : drift corrigé, beats lissés

# Test 3 : Pas de drift
# Attendu : timestamps inchangés
```

---

## Tâche 2.3 — Validation par analyse spectrale

**Fichier** : `backend/tempo_map.py`

### Nouvelle fonction : `_validate_tempo()`

```python
def _validate_tempo(beat_times: np.ndarray, audio_path: str) -> bool:
    """
    Valide le tempo en analysant l'audio.
    
    Paramètres :
      beat_times : array des timestamps des beats
      audio_path : chemin vers le fichier audio
    
    Retourne : bool (True si tempo valide, False sinon)
    
    Algorithme :
    1. Charger l'audio
    2. Calculer la FFT
    3. Vérifier la cohérence avec les beats
    4. Détecter les anomalies (beats trop rapprochés ou trop éloignés)
    """
```

### Algorithme

1. **FFT** : calculer la transformée de Fourier
2. **Analyse spectrale** : vérifier la présence de patterns périodiques
3. **Validation** : vérifier que les beats sont cohérents avec l'audio
4. **Anomalies** : détecter les beats aberrants (IOI < 0.1s ou > 3.0s)

### Tests

```python
# Test 1 : Tempo valide (120 BPM)
# Attendu : validation = True

# Test 2 : Tempo invalide (beats trop rapprochés)
# Attendu : validation = False

# Test 3 : Tempo invalide (beats trop éloignés)
# Attendu : validation = False
```

---

## Tâche 2.4 — Fallback robuste

**Fichier** : `backend/tempo_map.py`

### Nouvelle fonction : `_build_fallback_numpy()`

```python
def _build_fallback_numpy(
    note_events: Optional[list] = None,
    default_bpm: float = 120.0
) -> TempoMap:
    """
    Dernier recours : TempoMap synthétique avec correction de drift.
    
    Paramètres :
      note_events : optionnel — utilisé pour le fallback IOI
      default_bpm : BPM par défaut
    
    Retourne : TempoMap
    
    Algorithme :
    1. Estimer BPM depuis les IOI des note_events
    2. Générer des beats synthétiques linéaires
    3. Corriger le drift avec Kalman
    4. Retourner la TempoMap
    """
```

### Algorithme

1. **Estimation BPM** : calculer la médiane des IOI
2. **Beats synthétiques** : générer des beats linéaires
3. **Correction de drift** : appliquer le filtre Kalman
4. **Downbeats** : tous les 4 beats

### Tests

```python
# Test 1 : Fallback avec note_events
# Attendu : TempoMap avec BPM estimé

# Test 2 : Fallback sans note_events
# Attendu : TempoMap avec BPM par défaut

# Test 3 : Fallback avec drift
# Attendu : drift corrigé
```

---

## Tâche 2.5 — Fonction principale améliorée

**Fichier** : `backend/tempo_map.py`

### Modification de `build_tempo_map()`

```python
def build_tempo_map(
    audio_path: str,
    note_events: Optional[list] = None
) -> TempoMap:
    """
    Construit une TempoMap dynamique depuis un fichier audio.
    
    Ordre de tentative (V3) :
      1. numpy (pur Python, pas de dépendances)
      2. Fallback numpy avec correction de drift
      3. Fallback IOI (identique à V2, mais avec drift corrigé)
    
    Paramètres :
      audio_path   : chemin absolu vers le fichier audio
      note_events  : optionnel — utilisé pour le fallback IOI
    
    Retourne : TempoMap
    """
```

---

## Tâche 2.6 — Tests de validation

**Fichier** : `backend/tempo_map.py`

### Auto-test principal

```python
if __name__ == "__main__":
    """
    Test : morceau varié avec différents styles
    Attendu : 30-40% de BPM corrects, pas de drift
    """
    import sys
    import os
    
    test_file = None
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    else:
        # Chercher le fichier MP3 de test dans le répertoire parent
        parent = os.path.join(os.path.dirname(__file__), '..')
        for f in os.listdir(parent):
            if f.endswith('.mp3') or f.endswith('.wav'):
                test_file = os.path.join(parent, f)
                break
    
    if not test_file or not os.path.exists(test_file):
        print("[Test] Aucun fichier audio trouvé. Passer le chemin en argument.")
        print("Usage: python tempo_map.py <chemin_audio>")
        sys.exit(1)
    
    print("\n" + "="*60)
    print(f"[Test] Analyse de : {os.path.basename(test_file)}")
    print("="*60 + "\n")
    
    tm = build_tempo_map(test_file)
    
    print("\n-- Resultats --")
    print(f"  Methode         : {tm.method}")
    print(f"  BPM global      : {tm.global_bpm:.2f}")
    print(f"  Mesure          : {tm.estimated_meter[0]}/{tm.estimated_meter[1]}")
    print(f"  Nombre de beats : {len(tm.beat_times)}")
    t_range = tm.tempo_range()
    print(f"  Plage BPM       : [{t_range[0]:.1f} - {t_range[1]:.1f}]")
    print(f"  5 premiers beats (s) : {[round(b, 3) for b in tm.beat_times[:5]]}")
    
    print("\n-- Tests de conversion --")
    all_ok = True
    for t in [1.0, 5.0, 10.0, 20.0, 30.0]:
        if t > tm.beat_times[-1] + 5:
            continue
        b  = tm.seconds_to_beat(t)
        t2 = tm.beat_to_seconds(b)
        err_ms = abs(t - t2) * 1000
        status = "OK" if err_ms < 10.0 else "FAIL"
        if err_ms >= 10.0:
            all_ok = False
        print(f"  [{status}]  {t:.1f}s -> beat {b:.3f} -> {t2:.3f}s  (erreur: {err_ms:.2f}ms)")
    
    print("\n-- Tempo local --")
    for t in [0.0, 5.0, 15.0, 30.0]:
        if t > tm.beat_times[-1] + 5:
            continue
        bpm_loc = tm.local_bpm_at(t)
        print(f"  BPM a {t:.0f}s : {bpm_loc:.1f}")
    
    if all_ok:
        print("\n[Test] SUCCES - Tous les tests de conversion sont passes (<10ms d'erreur)")
    else:
        print("\n[Test] ATTENTION - Certaines conversions depassent 10ms")
```

---

## Styles CSS à ajouter

**Fichier** : `frontend/css/` (si nécessaire)

```css
/* Indicateurs de tempo V3 */
.tempo-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: rgba(255,255,255,0.08);
    border-radius: 6px;
    font-size: 0.85rem;
}

.tempo-badge {
    padding: 2px 8px;
    border-radius: 12px;
    color: white;
    font-size: 0.75rem;
    font-weight: 600;
}

.tempo-badge.madmom { background: #2ecc71; }
.tempo-badge.librosa { background: #f39c12; }
.tempo-badge.numpy { background: #3498db; }
```

---

## Tests de validation

| Test | Description | Attendu |
|---|---|---|
| 2.1 | Beat tracking numpy | Beats détectés, pas de dépendances |
| 2.1 | Tempo stable | global_bpm ≈ 120 BPM |
| 2.2 | Drift linéaire | Drift corrigé |
| 2.2 | Drift non linéaire | Drift corrigé |
| 2.3 | Validation spectrale | Validation = True |
| 2.4 | Fallback numpy | TempoMap avec drift corrigé |
| 2.5 | Test complet | 30-40% de BPM corrects |

---

## Risques et solutions

| Risque | Solution |
|---|---|
| Beat tracking numpy moins précis | Utiliser des paramètres optimisés |
| Performance lissage Kalman | Utiliser un filtre simplifié |
| Incompatibilité V2 | Garantir la rétrocompatibilité (JSON VexFlow identique) |
| Tests insuffisants | Tester sur 50+ morceaux variés |

---

## Métriques de succès

- **Gain attendu** : 30-40% de BPM corrects, pas de drift
- **Tests** : 50+ morceaux variés
- **Performance** : < 2 secondes pour 5 minutes d'audio
- **Rétrocompatibilité** : 100% avec V2
- **Dépendances** : numpy uniquement (pas madmom/librosa)