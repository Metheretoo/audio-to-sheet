# Analyse Harmonique et Piano Roll (La "Grosse V4")

Pour dépasser les limites du découpage naïf (LH/RH par hauteur de note) et
s'attaquer sérieusement au répertoire classique (Chopin, Debussy, Schubert),
la V4 intègre une couche de compréhension musicale entre la transcription
brute et le découpage en voix.

---

## 1. Vue d'ensemble du pipeline

```
NoteEvents (Piano Transcription + pedal_events)
  │
  ▼  note_filter.py
NoteEvents filtrés (sans fantômes, durées correctes)
  │
  ▼  tempo_map.py (madmom)
QuantizedNote[]  (notes alignées sur beat_times[])
  │
  ▼  piano_roll.py
Slice[]  (groupes de notes harmoniquement cohérents)
  │
  ▼  harmonic_analyzer.py (music21 + Krumhansl-Schmuckler)
HarmonicContext  (tonalité, accords, chiffrage romain)
  │
  ▼  voice_engine.py (Dijkstra pénalisé par harmonie)
VoiceSplit  (LH / RH avec cohérence d'accord garantie)
  │
  ▼  score_builder.py
ScoreData  (nuances, pédale, ornements)
```

---

## 2. Structures de données

### 2.1 `Slice` — l'atome harmonique

Un `Slice` représente un instant harmonique : un accord vertical, ou un
arpège brisé fusionné en un seul bloc pour l'analyse.

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Slice:
    beat_position: float          # Position en beats globaux (ex: 4.25)
    duration_beats: float         # Durée en beats
    midi_pitches: List[int]       # Liste des notes MIDI (ex: [48, 55, 60, 64])
    is_arpeggio: bool = False     # True si notes brisées fusionnées
    onset_tolerance_ms: float = 30.0
    pedal_active: bool = False    # La pédale est-elle enfoncée ?
```

### 2.2 `ChordAnalysis` — le résultat de music21

```python
@dataclass
class ChordAnalysis:
    root: str                      # Ex: "C", "F#", "Bb"
    quality: str                   # Ex: "major", "minor", "dominant-seventh"
    inversion: int                 # 0=fondamentale, 1=premier renversement, etc.
    roman_numeral: str             # Ex: "I", "V7", "ii6"
    is_known_chord: bool           # False si music21 ne reconnaît pas
    bass_note: int                 # MIDI pitch de la basse (note la plus grave)
    confidence: float              # 0.0 à 1.0
```

### 2.3 `HarmonicContext` — le résultat global de l'analyse

```python
@dataclass
class HarmonicContext:
    global_key: str                # Ex: "F major", "C minor"
    # Tonalité par segment (une entrée tous les 4 mesures environ)
    local_keys: List[tuple]        # [(beat_start, key_name), ...]
    # Un ChordAnalysis par Slice
    chord_map: dict                # {beat_position: ChordAnalysis}
    # Frontières de phrases (pour guider les liaisons)
    phrase_boundaries: List[float] # Positions en beats
```

---

## 3. Module `piano_roll.py` — Groupement en Slices

### 3.1 Algorithme de groupement vertical (accords)

```python
import numpy as np
from collections import defaultdict

def group_into_slices(
    qnotes: List[QuantizedNote],
    onset_tolerance_beats: float = 0.03,  # ~30ms à 60 BPM
    pedal_events: List[dict] = None
) -> List[Slice]:
    """
    Groupe les QuantizedNote en Slices harmoniques.
    Les notes avec des onsets très proches forment un accord vertical.
    """
    if not qnotes:
        return []

    # Trier par onset
    sorted_notes = sorted(qnotes, key=lambda n: n.beat_position)
    slices = []
    current_group = [sorted_notes[0]]

    for note in sorted_notes[1:]:
        # Si la note est proche de la précédente -> même Slice
        if note.beat_position - current_group[0].beat_position <= onset_tolerance_beats:
            current_group.append(note)
        else:
            slices.append(_make_slice(current_group, pedal_events))
            current_group = [note]

    if current_group:
        slices.append(_make_slice(current_group, pedal_events))

    return slices


def _make_slice(notes: List[QuantizedNote], pedal_events) -> Slice:
    beat_pos = notes[0].beat_position
    pitches  = sorted([n.pitch_midi for n in notes])
    in_pedal = any(
        p['start_beat'] <= beat_pos <= p['end_beat']
        for p in (pedal_events or [])
    )
    return Slice(
        beat_position=beat_pos,
        duration_beats=max(n.duration_beats for n in notes),
        midi_pitches=pitches,
        pedal_active=in_pedal
    )
```

### 3.2 Fusion d'arpèges (Chopin LH style brisé)

Les arpèges brisés de Chopin (Do2 → Sol2 → Mi3 → Do4 sur 1 beat) doivent
être reconnus comme un seul accord pour l'analyse harmonique, sinon
`music21` voit 4 "accords" de 1 note = incompréhensible.

```python
def fuse_arpeggios(
    slices: List[Slice],
    max_span_beats: float = 1.0,   # Un arpège tient dans 1 beat
    min_notes_in_arpeggio: int = 3
) -> List[Slice]:
    """
    Fusionne les séquences rapides de notes isolées en un seul Slice
    si elles forment vraisemblablement un arpège.
    """
    fused = []
    i = 0
    while i < len(slices):
        # Collecter les slices mono-note consécutifs dans la fenêtre
        window = [slices[i]]
        j = i + 1
        while (j < len(slices)
               and len(slices[j].midi_pitches) == 1
               and slices[j].beat_position - slices[i].beat_position <= max_span_beats):
            window.append(slices[j])
            j += 1

        if len(window) >= min_notes_in_arpeggio:
            # Fusionner en un seul Slice
            all_pitches = []
            for s in window:
                all_pitches.extend(s.midi_pitches)
            merged = Slice(
                beat_position=window[0].beat_position,
                duration_beats=window[-1].beat_position - window[0].beat_position,
                midi_pitches=sorted(set(all_pitches)),
                is_arpeggio=True,
                pedal_active=any(s.pedal_active for s in window)
            )
            fused.append(merged)
            i = j
        else:
            fused.append(slices[i])
            i += 1

    return fused
```

---

## 4. Module `harmonic_analyzer.py` — music21

### 4.1 Détection de la tonalité (globale + locale)

```python
import music21
from music21 import stream, note, chord, roman, key as m21key

def detect_keys(slices: List[Slice], window_beats: float = 16.0) -> List[tuple]:
    """
    Détecte la tonalité par fenêtre glissante (Krumhansl-Schmuckler via music21).
    Retourne [(beat_start, key_name), ...]
    """
    if not slices:
        return [('0.0', 'C major')]

    max_beat = slices[-1].beat_position
    results = []
    pos = 0.0

    while pos < max_beat:
        window_slices = [s for s in slices
                         if pos <= s.beat_position < pos + window_beats]
        if len(window_slices) < 4:
            pos += window_beats / 2
            continue

        # Construire un stream music21 temporaire
        s = stream.Stream()
        for sl in window_slices:
            if len(sl.midi_pitches) == 1:
                s.append(note.Note(sl.midi_pitches[0]))
            elif len(sl.midi_pitches) > 1:
                s.append(chord.Chord(sl.midi_pitches))

        detected_key = s.analyze('key')  # Krumhansl-Schmuckler
        results.append((pos, str(detected_key)))
        pos += window_beats / 2  # Chevauchement de 50%

    return results


def filter_stable_key_changes(
    local_keys: List[tuple],
    min_confirmations: int = 2
) -> List[tuple]:
    """
    Filtre les changements de tonalité instables (chromatismes passagers).
    Ne valide un changement d'armure que s'il est confirmé sur N fenêtres.

    Problème sans ce filtre :
      Une appogiature en Do# dans un morceau en Fa Majeur peut déclencher
      une fausse détection "Ré Majeur" sur une fenêtre → armure parasite.

    Avec ce filtre (min_confirmations=2, fenêtres de 50% overlap) :
      Le Do# doit persister sur 2 fenêtres consécutives (~8 mesures)
      avant de déclencher un changement d'armure. Bien calibré pour Chopin.
    """
    if not local_keys:
        return []

    stable = [local_keys[0]]
    run_key = local_keys[0][1]
    count   = 1

    for beat_pos, key_name in local_keys[1:]:
        if key_name == run_key:
            count += 1
        else:
            count   = 1
            run_key = key_name

        if count >= min_confirmations and key_name != stable[-1][1]:
            stable.append((beat_pos, key_name))

    return stable


# ─── Contrat avec score_builder.py ─────────────────────────────────────────
#
# MAILLON MANQUANT CRITIQUE : une fois les changements de tonalité détectés
# et stabilisés, score_builder.py DOIT les convertir en événements de partition.
#
# Pseudocode attendu dans score_builder.py :
#
#   stable_keys = filter_stable_key_changes(harmonic_ctx.local_keys)
#
#   for (beat_pos, key_name) in stable_keys:
#       measure_num = tempo_map.beat_to_measure(beat_pos)
#       score.insert_key_signature(measure_num, key_name)
#       # → MusicXML : <key><fifths>N</fifths><mode>major|minor</mode></key>
#       # → LilyPond : \key f \major  ou  \key f \minor
#
# Exemple pour la Mazurka Op. 68 No. 3 :
#   stable_keys = [(0.0, "F major"), (48.0, "F minor"), (96.0, "F major")]
#   → Armure mesure 1  : 1 bémol (Si♭)
#   → Armure mesure 17 : 4 bémols (Si♭, Mi♭, La♭, Ré♭)  ← changement visible
#   → Armure mesure 33 : 1 bémol (retour)
#
# ATTENTION : un changement d'armure en MusicXML annule l'armure précédente.
# Ne pas oublier d'émettre le "courtesy key signature" (bécarres si besoin)
# à la fin de la portée précédant le changement.
# ────────────────────────────────────────────────────────────────────────────

def analyze_chord(sl: Slice, current_key: str) -> ChordAnalysis:
    """
    Analyse un seul Slice avec music21 pour identifier l'accord et son rôle.
    """
    if not sl.midi_pitches:
        return ChordAnalysis(root='?', quality='rest', inversion=0,
                             roman_numeral='?', is_known_chord=False,
                             bass_note=0, confidence=0.0)

    c = chord.Chord(sl.midi_pitches)
    k = m21key.Key(current_key.split()[0])  # Ex: "F major" -> "F"

    try:
        rn = roman.romanNumeralFromChord(c, k)
        return ChordAnalysis(
            root=str(c.root()),
            quality=c.quality,
            inversion=c.inversion(),
            roman_numeral=rn.figure,
            is_known_chord=True,
            bass_note=min(sl.midi_pitches),
            confidence=0.9 if c.isTriad() or c.isSeventh() else 0.6
        )
    except Exception:
        return ChordAnalysis(
            root=str(c.root()) if c.pitches else '?',
            quality=c.quality,
            inversion=0,
            roman_numeral='?',
            is_known_chord=False,
            bass_note=min(sl.midi_pitches),
            confidence=0.3
        )
```

### 4.2 Construction du HarmonicContext complet

```python
def build_harmonic_context(slices: List[Slice]) -> HarmonicContext:
    local_keys  = detect_keys(slices, window_beats=16.0)
    chord_map   = {}

    for sl in slices:
        # Trouver la tonalité locale applicable
        current_key = local_keys[0][1]  # Défaut: première détectée
        for beat_start, key_name in local_keys:
            if sl.beat_position >= beat_start:
                current_key = key_name

        chord_map[sl.beat_position] = analyze_chord(sl, current_key)

    return HarmonicContext(
        global_key=local_keys[0][1] if local_keys else 'C major',
        local_keys=local_keys,
        chord_map=chord_map,
        phrase_boundaries=_detect_phrase_boundaries(slices, chord_map)
    )


def _detect_phrase_boundaries(
    slices: List[Slice],
    chord_map: dict
) -> List[float]:
    """
    Les cadences (V -> I, V7 -> I) marquent des frontières de phrase.
    Utile pour le score_builder (liaisons, respirations).
    """
    boundaries = []
    prev_rn = None
    for sl in slices:
        ca = chord_map.get(sl.beat_position)
        if ca and prev_rn in ('V', 'V7') and ca.roman_numeral == 'I':
            boundaries.append(sl.beat_position)
        if ca:
            prev_rn = ca.roman_numeral
    return boundaries
```

---

## 5. Intégration dans `voice_engine.py`

### La modification clé : pénalité harmonique dans Dijkstra

L'ancien Dijkstra minimisait seulement le **saut mélodique** (intervalle en
demi-tons entre notes consécutives). La modification : ajouter une pénalité
forte si une affectation de voix **casse un accord reconnu**.

```python
def _compute_edge_cost(
    note_a: QuantizedNote,
    note_b: QuantizedNote,
    voice: str,            # 'lh' ou 'rh'
    harmonic_ctx: HarmonicContext,
    config: VoiceConfig
) -> float:
    """
    Coût d'affecter note_b à la même voix que note_a.
    Coût faible = bonne décision.
    """
    # 1. Coût mélodique de base (intervalle en demi-tons)
    melodic_cost = abs(note_b.pitch_midi - note_a.pitch_midi)

    # 2. Pénalité si on est dans un accord reconnu et qu'on sépare ses notes
    harmony_penalty = 0.0
    chord_at_b = harmonic_ctx.chord_map.get(note_b.beat_position)
    if chord_at_b and chord_at_b.is_known_chord:
        # Si la basse de l'accord est assignée à LH,
        # les autres notes de l'accord DOIVENT rester en LH
        bass_in_lh = chord_at_b.bass_note < config.split_threshold
        note_in_chord = note_b.pitch_midi in _get_chord_pitches(chord_at_b)
        if bass_in_lh and voice == 'rh' and note_in_chord:
            harmony_penalty = config.harmony_penalty_weight  # Ex: 50.0

    # 3. Bonus si la note de basse de l'accord va en LH (comportement attendu)
    bass_bonus = 0.0
    if chord_at_b and note_b.pitch_midi == chord_at_b.bass_note and voice == 'lh':
        bass_bonus = -config.bass_bonus_weight  # Ex: -20.0 (coût négatif = bonus)

    return melodic_cost + harmony_penalty + bass_bonus
```

---

## 6. Détection des ornements via music21

Les appogiatures et petites notes rapides (< 150ms) polluent la partition.
`music21` peut aider à les identifier :

```python
def detect_ornaments(slices: List[Slice], beat_duration_sec: float) -> List[dict]:
    """
    Détecte les ornements (notes trop courtes pour être des vraies notes).
    Retourne une liste {beat_position, type: 'grace'|'trill'|'mordent'}.
    """
    ornaments = []
    min_grace_beats = 0.15 / beat_duration_sec  # < 150ms

    for i, sl in enumerate(slices):
        if sl.duration_beats < min_grace_beats and len(sl.midi_pitches) == 1:
            # Candidate appogiature : note isolée ultra-courte avant un accord
            if i + 1 < len(slices) and len(slices[i+1].midi_pitches) > 1:
                ornaments.append({
                    'beat_position': sl.beat_position,
                    'pitch': sl.midi_pitches[0],
                    'type': 'grace_note'
                })

        # Trille : alternance rapide de 2 notes
        if (i + 1 < len(slices)
                and len(sl.midi_pitches) == 1
                and len(slices[i+1].midi_pitches) == 1):
            interval = abs(sl.midi_pitches[0] - slices[i+1].midi_pitches[0])
            both_short = (sl.duration_beats < min_grace_beats * 2
                          and slices[i+1].duration_beats < min_grace_beats * 2)
            if interval in (1, 2) and both_short:
                ornaments.append({
                    'beat_position': sl.beat_position,
                    'pitch': sl.midi_pitches[0],
                    'type': 'trill'
                })

    return ornaments
concerne les étapes 5 à 7 (rebaptisées et enrichies).

| Priorité | Tâche | Module | Impact | Effort |
|----------|-------|--------|--------|--------|
| **1** | Piano Transcription (Kong) | `transcriber.py` | +30% onset F1 | 2h |
| **2** | Beat tracking madmom | `tempo_map.py` | +45% time sig | 4h |
| **3** | Quantification grille locale | `quantizer.py` | -70% drift | 6h |
| **4** | Filtres notes fantômes | `note_filter.py` | +20% propreté | 1h |
| **5** | Piano Roll + Fusion arpèges | `piano_roll.py` | base pour harmonie | 3h |
| **6** | Analyse harmonique music21 | `harmonic_analyzer.py` | clé du LH correct | 5h |
| **7** | Voice Split pénalisé harmonie | `voice_engine.py` | +35% LH correct | 4h |
| **8** | Détection ornements | `harmonic_analyzer.py` | partition plus propre | 2h |
| **9** | Pedal-aware shortening | `score_builder.py` | +25% aération | 2h |
| **10** | Nuances par vélocité | `score_builder.py` | musicalement correct | 2h |
| **11** | Export MusicXML 4.0 | `musicxml_exporter.py` | compatibilité | 3h |
| **12** | Export LilyPond PDF | `midi_exporter.py` | rendu typo pro | 2h |

---

## 9. Dépendances Python à ajouter

```
# requirements.txt (additions V4 Grosse)
piano_transcription_inference  # Modèle Kong (PyTorch, CUDA)
madmom                         # Beat tracking (CPU only)
music21                        # Analyse harmonique (MIT)
pretty_midi                    # Manipulation piano roll
mir_eval                       # Métriques qualité
numpy>=1.24
scipy                          # Utilisé par music21 / DTW
```

