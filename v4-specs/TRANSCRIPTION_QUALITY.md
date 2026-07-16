# Stratégie Qualité de Transcription — V4

> **Ce document est le plus important du dossier.** L'échec des versions
> précédentes ne vient pas de l'architecture mais du fait que le problème
> "qualité partition" n'est jamais attaqué à sa source. Ce document le fait.

---

## 1. Diagnostic honnête : Pourquoi les versions précédentes échouent

### 1.1 La partition de référence vs le rendu actuel

En comparant `Réel - Mazurka in F Major, Op. 68, No. 3.jpg` et `Mazurka - v4 bis.jpg`,
les écarts se lisent immédiatement :

| Critère | Original Chopin | Rendu actuel | Impact |
|---------|----------------|--------------|--------|
| Métrique | **3/4** (Mazurka) | **4/4** mal détecté | Fatal — toute la partition est fausse |
| Tempo | *Allegro ma non troppo* (~♩=80-100 avec rubato) | 77 BPM global fixe | Fatal — drift cumulatif dès mesure 2 |
| Ligatures (beams) | Impeccables, par groupes | Anarchiques | Illisible |
| Nuances | `f`, `p`, `ff`, `sf` | Absentes | Perd l'information musicale |
| Ornements | Appogiatures, accents `>` | Absents | Informel |
| Silences | Ronde/demi-pause bien placés | Silences parasites partout | Rend la lecture impossible |
| Main gauche | Basses + accords propres | Doublons harmoniques, notes fantômes | Injoutable |

### 1.2 Les vrais goulots d'étranglement (par ordre d'impact)

```
Rang 1 — Détection métrique (time signature)
  BasicPitch retourne des note_events bruts, SANS information rythmique.
  Un 3/4 joué avec rubato ressemble à du 4/4 ou du 6/8 pour un algo naïf.
  Solution : madmom RNNBeatProcessor + RNNDownBeatProcessor (SOTA gratuit).

Rang 2 — Rubato / Dynamic Tempo Map
  Chopin = variations de tempo continues (ritardando, accelerando, rubato).
  Un BPM fixe génère du "drift" cumulatif dès la mesure 2.
  Solution : beat_times[] (un timestamp par beat, pas un BPM global).

Rang 3 — Quantification sur grille locale (pas globale)
  La quantification doit s'aligner sur beat_times[i] local, pas BPM moyen.
  Solution : grille locale par intervalle de beat + résolution max 1/32.

Rang 4 — Notes fantômes / Harmoniques
  BasicPitch détecte les harmoniques des basses (+12 et +7 demi-tons).
  Solution : filtre post-transcription (< 15 lignes, impact fort).

Rang 5 — Séparation mains (voice split)
  Split naïf Do4 (MIDI 60) insuffisant pour Chopin style brisé.
  Solution : Dijkstra sur contour mélodique + distance inter-voix.
```

---

## 2. Modèles de transcription : ce qui est déjà en place

### 2.1 Ce que tu as déjà (V2/V3)

> **Correction importante** : "Piano Transcription Kong" désigné dans ce document
> est le même package que celui installé depuis la V2 (`piano_transcription_inference`
> par Qiuqiang Kong, ByteDance). Il n'y a **rien à migrer** sur ce point.

| Modèle | Package | Auteur | Installé depuis | Spécificité |
|--------|---------|--------|-----------------|-------------|
| **Piano Transcription** | `piano_transcription_inference` | Qiuqiang Kong (ByteDance) | **V2** | MAESTRO, sort la pédale CC64 |
| **Transkun** | `transkun` | Kunxiong Fang et al. | **V3** | Token-based, bonne polyphonie |
| **HFT-Transformer** | `hft-transformer` | Zhiyao Duan et al. | **V3** | Haute résolution frame-level |

### 2.2 Ce que la V4 apporte réellement (c'est le PIPELINE, pas le modèle)

La V4 n'a **pas besoin de changer de modèle**. Elle doit corriger ce qui se passe
*après* la transcription :

| Problème | Cause réelle | Solution V4 |
|----------|-------------|-------------|
| Drift cumulatif | `onset / BPM_global` au lieu de `beat_times[]` | madmom + grille locale |
| Time signature 4/4 au lieu de 3/4 | Pas de détection de mètre | madmom RNNDownBeatProcessor |
| Pédale absente de la partition | Piano Transcription sort CC64 mais `score_builder` ne le lit pas | Lire les CC64 + pedal-aware |
| Accords LH incomplets | Voice split naïf par seuil MIDI 60 | music21 + Dijkstra harmonique |
| Notes fantômes | Harmoniques détectés comme notes | `note_filter.py` |

### 2.3 Stratégie d'ensemble (vote multi-modèles)

Avec 3 modèles déjà installés, on peut faire un **vote d'ensemble** pour améliorer
l'onset F1. Stratégie recommandée :

```
Piano Transcription  ]                          [ NoteEvent[] fusionnés
Transkun             ] --> ensemble_voter.py --> [ (union + filtre confidence)
HFT-Transformer      ]                          [ (ou intersection pour les notes incertaines)
```

- **Union** : garder toutes les notes détectées par au moins 1 modèle → meilleur rappel (recall)
- **Intersection** : garder seulement les notes détectées par 2+ modèles → meilleure précision
- **Vote majoritaire** (2/3) : compromis recommandé pour la musique classique

La pédale vient **toujours de Piano Transcription** (seul modèle qui la sort).

---

## 3. Détection de tempo et métrique : la clé du succès

### 3.1 Le pipeline de détection temporelle (obligatoire V4.0)

```
Audio --> madmom.RNNBeatProcessor   --> beat_times[]
      --> madmom.RNNDownBeatProcessor --> downbeat_times[]
      --> Déduire time_signature depuis ratio downbeat/beat
      --> Construire TempoMap avec BPM local par segment (fenêtre 4 mesures)
```

**Implémentation `tempo_map.py` :**

```python
import madmom
import numpy as np

def build_tempo_map_madmom(audio_path: str) -> TempoMap:
    proc_beat  = madmom.features.beats.RNNBeatProcessor()
    proc_dbeat = madmom.features.beats.RNNDownBeatProcessor()

    act_beat  = proc_beat(audio_path)
    act_dbeat = proc_dbeat(audio_path)

    beat_times = madmom.features.beats.BeatTrackingProcessor(fps=100)(act_beat)
    downbeat_info = madmom.features.downbeats.DBNDownBeatTrackingProcessor(
        beats_per_bar=[2, 3, 4], fps=100
    )(act_dbeat)

    # Déduire la mesure : max beat_in_bar dans downbeat_info
    beats_per_bar_candidates = [int(row[1]) for row in downbeat_info if row[1] > 0]
    time_sig_num = max(
        set(beats_per_bar_candidates),
        key=beats_per_bar_candidates.count
    )

    # BPM local : diff entre beats consécutifs
    beat_intervals = np.diff(beat_times)
    local_bpms = 60.0 / beat_intervals

    tempo_changes = _segment_tempo_changes(beat_times, local_bpms, time_sig_num)
    downbeats = _extract_downbeats(downbeat_info)

    return TempoMap(
        tempo_changes=tempo_changes,
        downbeats=downbeats,
        initial_bpm=float(np.median(local_bpms)),
        initial_time_signature=(time_sig_num, 4)
    )
```

### 3.2 Cas particulier du rubato (Chopin)

Le rubato est **intentionnel** : ce n'est PAS une erreur à corriger,
c'est l'expression musicale. La partition doit refléter ce qui est ÉCRIT
(noires régulières), pas ce qui est JOUÉ (avec accélérations/ralentissements).

**Stratégie V4 :**

```
Option A — Tempo Map fidèle (par défaut V4.0) :
  Conserver le rubato dans la TempoMap.
  La quantification s'aligne sur beat_times[] détectés localement.
  Résultat : partition légèrement plus dense (quelques triolets apparaissent)
             mais fidèle à l'interprétation. Lisible.

Option B — Tempo Flattening (V4.2, optionnel) :
  DTW pour déformer le temps continu vers une grille métronomique.
  Résultat : partition plus propre (noires/croches simples) mais moins fidèle.
  Activer via : config.yaml -> quantization.tempo_flattening: true
```

---

## 4. Quantification : aligner sur la grille locale

### 4.1 Principe fondamental (la correction la plus importante)

```
MAUVAIS (V1-V3) :
   beat_position = onset_sec / (60 / BPM_global)
   --> Tout le drift vient de là.

CORRECT (V4) :
   Pour chaque note, chercher le beat le plus proche dans beat_times[].
   Calculer la fraction de beat et arrondir sur la grille (1/32, 1/16...).
```

```python
def quantize_onset(onset_sec: float, beat_times: np.ndarray, grid: int = 32) -> float:
    """
    Aligne onset_sec sur la grille rythmique locale.
    grid = résolution max (32 = double croche, 16 = croche, 8 = noire)
    Retourne la position quantifiée en beats globaux.
    """
    beat_idx = np.searchsorted(beat_times, onset_sec, side='right') - 1
    beat_idx = max(0, min(beat_idx, len(beat_times) - 2))

    beat_start = beat_times[beat_idx]
    beat_end   = beat_times[beat_idx + 1]
    beat_dur   = beat_end - beat_start

    frac = (onset_sec - beat_start) / beat_dur
    quantized_frac = round(frac * grid) / grid

    return beat_idx + quantized_frac
```

### 4.2 Détection des tuplets (triolets, quintolets)

```python
def detect_triplet_group(notes_in_beat: list, beat_dur: float) -> bool:
    """True si 3 notes forment un triolet (3 dans l'espace de 2 temps)."""
    if len(notes_in_beat) != 3:
        return False
    intervals = [
        notes_in_beat[i+1].onset_sec - notes_in_beat[i].onset_sec
        for i in range(2)
    ]
    expected  = beat_dur / 3.0
    tolerance = expected * 0.25
    return all(abs(iv - expected) < tolerance for iv in intervals)
```

---

## 5. Filtrage post-transcription (rapide, impact fort)

Ces filtres s'appliquent **après** transcription, **avant** quantification.
Coût : quelques ms. Gain : partition beaucoup plus propre.

### 5.1 Filtre notes fantômes (harmoniques)

```python
def filter_ghost_notes(
    events: list,
    velocity_threshold: int = 30,
    harmonic_intervals: tuple = (12, 19, 24)
) -> list:
    """Supprime les harmoniques détectées comme vraies notes."""
    filtered = []
    for note in events:
        is_ghost = False
        for other in events:
            if other is note:
                continue
            interval = abs(round(note.pitch_midi) - round(other.pitch_midi))
            onset_overlap = abs(note.onset_sec - other.onset_sec) < 0.05
            stronger = other.velocity > note.velocity * 2
            if interval in harmonic_intervals and onset_overlap and stronger:
                is_ghost = True
                break
        if not is_ghost or note.velocity >= velocity_threshold:
            filtered.append(note)
    return filtered
```

### 5.2 Filtre durées irréalistes

```python
def filter_unrealistic_durations(
    events: list,
    min_duration: float = 0.04,
    max_duration: float = 8.0
) -> list:
    """Supprime notes trop courtes (bruit) ou trop longues (pédale confondue)."""
    return [e for e in events
            if min_duration <= (e.offset_sec - e.onset_sec) <= max_duration]
```

### 5.3 Correction de la durée par pédale (pedal-aware shortening)

```python
def apply_pedal_aware_shortening(events: list, pedal_events: list) -> list:
    """
    Si une note longue tombe dans une zone de pédale, raccourcir sa durée notée.
    Partition résultante : noire + symbole Ped. au lieu d'une ronde ignoble.
    """
    result = []
    for note in events:
        in_pedal = any(
            p['start'] <= note.onset_sec <= p['end']
            for p in pedal_events
        )
        if in_pedal and (note.offset_sec - note.onset_sec) > 1.0:
            from dataclasses import replace
            note = replace(note, offset_sec=note.onset_sec + 0.4)
        result.append(note)
    return result
```

---

## 6. Métriques de qualité cible pour V4

La cible n'est pas la perfection, mais la **jouabilité sans correction majeure**.

| Métrique | V3 estimé | Cible V4.0 | Cible V4.2 |
|----------|-----------|------------|------------|
| Détection time signature correcte | ~40% | **85%** | 95% |
| Onset F1 (+/-50ms) | ~0.70 | **0.85** | 0.90 |
| Pitch accuracy (+/-0.5 semitone) | ~0.75 | **0.88** | 0.92 |
| Notes fantômes éliminées | ~0% | **80%** | 95% |
| Mesures correctement fermées | ~50% | **90%** | 95% |
| Effort de retouche manuelle | ~3h / 2 pages | **< 30min** | < 10min |

> Métriques mesurées avec `quality_metrics.py` sur `22 Piste 22.flac`
> en comparant à `Réel - Mazurka in F Major, Op. 68, No. 3.jpg`.

---

## 7. Plan de priorités V4 (ordre strict d'implémentation)

Ne pas passer à l'étape N+1 sans valider l'étape N sur `22 Piste 22.flac`.

> **Important** : les 3 modèles (Piano Transcription, Transkun, HFT-Transformer)
> sont déjà installés depuis la V3. Aucune migration de modèle n'est nécessaire.
> Les étapes 5 à 7 (Piano Roll + Analyse Harmonique music21) sont détaillées
> dans **`HARMONIC_ANALYSIS.md`**.

| Priorité | Tâche | Module cible | Impact | Effort |
|----------|-------|-------------|--------|--------|
| **1** | **Lire CC64 de la pédale** depuis MIDI Piano Transcription | `transcriber.py` | corrige l'anotation pédale | 1h |
| **2** | Beat tracking madmom (time sig + beat_times[]) | `tempo_map.py` | +45% time sig OK | 4h |
| **3** | Quantification sur grille locale (beat_times) | `quantizer.py` | -70% notes parasites | 6h |
| **4** | Filtre notes fantômes + durées irréalistes | `note_filter.py` (NOUVEAU) | +20% propreté | 1h |
| **5** | Piano Roll + Fusion arpèges | `piano_roll.py` (NOUVEAU) | base analyse harmonique | 3h |
| **6** | Analyse harmonique music21 (tonalité, accords) | `harmonic_analyzer.py` (NOUVEAU) | +35% LH correct | 5h |
| **7** | Voice Split guidé par harmonie (Dijkstra+) | `voice_engine.py` | clé pour accords LH | 4h |
| **8** | Pedal-aware : afficher la pédale sur la partition | `score_builder.py` | annotation pédale + durées | 2h |
| **9** | Détection ornements (grace notes, trilles) | `harmonic_analyzer.py` | partition propre | 2h |
| **10** | Nuances par vélocité | `score_builder.py` | musicalement correct | 2h |
| **11** | Ensemble voting 3 modèles (Piano Tr. + Transkun + HFT) | `ensemble_voter.py` | +5-10% onset F1 | 3h |
| **12** | Export MusicXML 4.0 complet | `musicxml_exporter.py` | compatibilité | 3h |
| **13** | Export LilyPond PDF | `midi_exporter.py` | rendu typographique | 2h |

> **Règle d'or V4** :
> - Étapes 1–4 = corriger le pipeline de base (tempo, drift, bruit)
> - Étapes 5–7 = comprendre la musique (harmonie, LH correct)
> - Étapes 8–10 = enrichir la partition (pédale, nuances, ornements)
> - Étape 11 = bonus qualité avec les modèles déjà en place

---

## 8. Références techniques

- **Piano Transcription (Kong)** : https://github.com/bytedance/piano_transcription
- **madmom** : https://github.com/CPJKU/madmom
- **music21** : https://web.mit.edu/music21/ (analyse harmonique)
- **pretty_midi** : https://github.com/craffel/pretty-midi (piano roll)
- **mir_eval** : métriques onset F1, pitch accuracy (pip install mir_eval)
- **MAESTRO Dataset** : https://magenta.tensorflow.org/datasets/maestro
- **librosa.sequence.dtw** : tempo flattening (V4.2)
- **`HARMONIC_ANALYSIS.md`** : détails implémentation music21 + piano roll

---

## 9. Fixture de test de référence

`22 Piste 22.flac` est **LA fixture principale** pour valider V4.

```yaml
# Valeurs attendues pour 22 Piste 22.flac
reference_mazurka:
  time_signature: [3, 4]
  key_signature: "F"              # 1 bémol
  tempo_bpm_range: [60, 100]      # Allegro ma non troppo + rubato
  measures_count_approx: 37
  sections:
    - {name: "A",    measures: [1, 8]}
    - {name: "B",    measures: [9, 16]}
    - {name: "A'",   measures: [17, 24]}
    - {name: "Coda", measures: [25, 37], marking: "Poco più vivo"}
```
