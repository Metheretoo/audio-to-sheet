# PHASE 4 — Score Builder & Intégration Pipeline

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 4-6h
> **Prérequis** : Phases 1, 2 et 3 complètes et validées
> **Fichiers à créer** : `backend/score_builder.py`
> **Fichiers à modifier** : `backend/app.py`, `backend/midi_parser.py`

---

## Objectif

Construire le module `score_builder.py` qui transforme le `VoiceSplit` (issu de Phase 3) en JSON VexFlow propre et complet, puis **câbler le nouveau pipeline dans `app.py`** pour remplacer l'ancien flux.

Le format JSON de sortie doit rester **identique à la V1** pour ne pas casser le frontend.

---

## Rappel du format JSON VexFlow attendu (contrat immuable)

```json
{
  "tempo": 120,
  "timeSignature": [4, 4],
  "keySignature": "C",
  "totalMeasures": 8,
  "measures": [
    {
      "treble": [
        {
          "id": "uuid-...",
          "keys": ["c/4", "e/4", "g/4"],
          "durationStr": "q",
          "dots": 0,
          "isRest": false,
          "startBeat": 0.0,
          "duration": 1.0,
          "midiPitch": 60,
          "hand": "treble",
          "amplitude": 0.75
        }
      ],
      "bass": [...]
    }
  ]
}
```

> **RÈGLE** : ne jamais modifier cette structure. Le frontend `renderer.js` dépend de chaque champ.

---

## Fichier à créer : `backend/score_builder.py`

```python
"""
score_builder.py — Construction de la partition (ScoreData JSON pour VexFlow)

Prend un VoiceSplit (QuantizedNote treble + bass) et produit le JSON
de partition compatible avec renderer.js (format V1 conservé).

Pipeline interne :
  1. detect_key_signature()   : analyse harmonique (Krumhansl-Schmuckler)
  2. build_measures()         : répartition des notes par mesure
  3. build_voice_vexflow()    : construction d'une voix avec silences automatiques
  4. build_score()            : assemblage final du JSON
"""

import uuid
import math
import numpy as np
from typing import List, Tuple, Dict, Any
from quantizer import QuantizedNote, beats_to_duration, duration_beats
from voice_engine import VoiceSplit
from tempo_map import TempoMap


# ── Constantes ────────────────────────────────────────────────────────────────

PITCH_NAMES_SHARP = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']
PITCH_NAMES_FLAT  = ['c', 'db', 'd', 'eb', 'e', 'f', 'gb', 'g', 'ab', 'a', 'bb', 'b']
FLAT_KEY_SIGS     = {'F', 'Bb', 'Eb', 'Ab', 'Db', 'Gb', 'Cb'}
REST_DURS         = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25]

# Positions correctes des silences par portée (règle VexFlow)
REST_POSITIONS = {
    'treble': {'w': 'd/5', 'default': 'b/4'},
    'bass':   {'w': 'f/3', 'default': 'd/3'},
}


# ── Fonction principale ───────────────────────────────────────────────────────

def build_score(
    voices: VoiceSplit,
    tempo_map: TempoMap,
    key_sig: str = 'C',
    options: dict = None,
) -> Dict[str, Any]:
    """
    Construit le ScoreData JSON complet depuis un VoiceSplit.

    Paramètres :
      voices    : VoiceSplit (treble + bass de QuantizedNote)
      tempo_map : TempoMap pour extraire le BPM et la mesure
      key_sig   : armure détectée (ou 'C' par défaut)
      options   : dict optionnel avec :
        - detect_key : bool (défaut True) — relancer la détection d'armure
        - time_sig   : Tuple[int,int] — override de mesure si détecté manuellement

    Retourne un dict compatible JSON / VexFlow.
    """
    if options is None:
        options = {}

    # 1. Tonalité
    if options.get('detect_key', True):
        all_notes = voices.treble + voices.bass
        key_sig = detect_key_signature([
            (0, 1, n.pitch_midi, n.amplitude) for n in all_notes
        ])

    # 2. Mesure et tempo
    time_sig = options.get('time_sig', list(tempo_map.estimated_meter))
    ts_num, ts_den = time_sig[0], time_sig[1]
    beats_per_measure = ts_num * (4.0 / ts_den)
    global_bpm = int(round(tempo_map.global_bpm))

    # 3. Nombre de mesures nécessaires
    all_notes = voices.treble + voices.bass
    if not all_notes:
        return _empty_score(global_bpm, ts_num, ts_den, key_sig)

    total_beats = max(n.beat_position + n.beat_duration for n in all_notes)
    num_measures = max(1, math.ceil(total_beats / beats_per_measure))

    # 4. Construire les mesures
    measures = []
    for m_idx in range(num_measures):
        m_start = m_idx * beats_per_measure
        m_end   = (m_idx + 1) * beats_per_measure

        treble_in_measure = [
            n for n in voices.treble
            if n.beat_position >= m_start and n.beat_position < m_end
        ]
        bass_in_measure = [
            n for n in voices.bass
            if n.beat_position >= m_start and n.beat_position < m_end
        ]

        measures.append({
            'treble': build_voice_vexflow(
                treble_in_measure, m_start, beats_per_measure, 'treble', key_sig
            ),
            'bass': build_voice_vexflow(
                bass_in_measure, m_start, beats_per_measure, 'bass', key_sig
            ),
        })

    return {
        'tempo':         global_bpm,
        'timeSignature': [ts_num, ts_den],
        'keySignature':  key_sig,
        'totalMeasures': num_measures,
        'measures':      measures,
    }


# ── Construction d'une voix ───────────────────────────────────────────────────

def build_voice_vexflow(
    notes: List[QuantizedNote],
    m_start: float,
    beats_per_measure: float,
    hand: str,
    key_sig: str = 'C',
) -> List[Dict[str, Any]]:
    """
    Construit la liste de notes/silences VexFlow pour une voix dans une mesure.

    Algorithme :
    1. Si pas de notes → retourner [silence pleine mesure]
    2. Grouper les notes sur la même grille en accords (beat_position identique)
    3. Parcourir les positions de grille dans la mesure :
       - Si une note/accord est présent → l'émettre avec durée calculée par IOI
       - Sinon → émettre un silence de durée appropriée
    4. Combler les silences en fin de mesure

    IMPORTANT :
    - Travailler en beats RELATIFS à la mesure (m_start = 0 pour cette mesure)
    - Ne jamais créer de chevauchement (note_end > prochaine note_start)
    - La somme des durées de la voix doit être EXACTEMENT beats_per_measure

    Retourne une liste de dicts VexFlow (notes + silences).
    """
    REST_KEY = REST_POSITIONS[hand]['default']

    if not notes:
        dur_str, dots = beats_to_duration(beats_per_measure)
        rest_key = REST_POSITIONS[hand].get(dur_str, REST_KEY)
        return [_make_rest(rest_key, dur_str, dots, m_start, beats_per_measure, hand)]

    # Grouper par position (accords)
    chords: Dict[float, List[QuantizedNote]] = {}
    for n in notes:
        pos = round(n.beat_position - m_start, 6)
        chords.setdefault(pos, []).append(n)

    sorted_positions = sorted(chords.keys())
    voice = []
    cursor = 0.0  # position courante relative à la mesure

    for i, pos in enumerate(sorted_positions):
        # Silence avant cet accord
        gap = pos - cursor
        if gap > 0.01:
            voice.extend(_split_rests(gap, m_start + cursor, hand))

        chord_notes = chords[pos]
        primary = max(chord_notes, key=lambda n: n.amplitude)

        # Durée par IOI
        if i < len(sorted_positions) - 1:
            ioi = sorted_positions[i + 1] - pos
        else:
            ioi = beats_per_measure - pos

        raw_dur = primary.beat_duration
        target  = ioi if (raw_dur >= 0.3 * ioi and ioi >= 0.125) else raw_dur
        target  = min(target, beats_per_measure - pos)  # ne pas déborder

        dur_str, dots = beats_to_duration(target)
        final_dur     = duration_beats(dur_str, dots)

        # Empêcher le chevauchement
        if i < len(sorted_positions) - 1:
            max_dur = sorted_positions[i + 1] - pos
            if final_dur > max_dur:
                final_dur = max_dur
                dur_str, dots = beats_to_duration(final_dur)
                final_dur = duration_beats(dur_str, dots)

        all_keys = sorted(
            {midi_to_vexflow_key(n.pitch_midi, key_sig) for n in chord_notes},
            key=vexflow_key_to_pitch,
        )

        voice.append({
            'id':          str(uuid.uuid4()),
            'keys':        all_keys,
            'durationStr': dur_str,
            'dots':        dots,
            'isRest':      False,
            'startBeat':   primary.beat_position,
            'duration':    final_dur,
            'midiPitch':   primary.pitch_midi,
            'hand':        hand,
            'amplitude':   round(primary.amplitude, 3),
        })

        cursor = pos + final_dur

    # Silence final
    remaining = beats_per_measure - cursor
    if remaining > 0.01:
        voice.extend(_split_rests(remaining, m_start + cursor, hand))

    return voice


# ── Utilitaires de construction ───────────────────────────────────────────────

def _split_rests(total_beats: float, start_beat: float, hand: str) -> List[Dict]:
    """Découpe un silence en durées standard (plus grande valeur possible en premier)."""
    rests = []
    remaining = total_beats
    pos = start_beat

    while remaining > 0.01:
        chosen = next((d for d in REST_DURS if d <= remaining + 1e-4), None)
        if chosen is None:
            break
        dur_str, dots = beats_to_duration(chosen)
        rest_key = REST_POSITIONS[hand].get(dur_str, REST_POSITIONS[hand]['default'])
        rests.append(_make_rest(rest_key, dur_str, dots, pos, chosen, hand))
        remaining -= chosen
        pos += chosen

    return rests


def _make_rest(key: str, dur_str: str, dots: int, start_beat: float,
               duration: float, hand: str) -> Dict[str, Any]:
    return {
        'id':          str(uuid.uuid4()),
        'keys':        [key],
        'durationStr': dur_str,
        'dots':        dots,
        'isRest':      True,
        'startBeat':   start_beat,
        'duration':    duration,
        'midiPitch':   None,
        'hand':        hand,
        'amplitude':   0,
    }


def _empty_score(tempo, ts_num, ts_den, key_sig='C') -> Dict[str, Any]:
    return {
        'tempo': tempo,
        'timeSignature': [ts_num, ts_den],
        'keySignature': key_sig,
        'totalMeasures': 0,
        'measures': [],
    }


# ── Conversions MIDI ↔ VexFlow ────────────────────────────────────────────────

def midi_to_vexflow_key(pitch: int, key_sig: str = 'C') -> str:
    """MIDI pitch → clé VexFlow  (ex: 60 → 'c/4')"""
    names = PITCH_NAMES_FLAT if key_sig in FLAT_KEY_SIGS else PITCH_NAMES_SHARP
    return f"{names[pitch % 12]}/{(pitch // 12) - 1}"


def vexflow_key_to_pitch(key: str) -> int:
    """'c#/4' → MIDI pitch"""
    NOTE_ST = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
    parts = key.split('/')
    if len(parts) != 2:
        return 60
    note_str = parts[0].lower()
    octave = int(parts[1])
    base = NOTE_ST.get(note_str[0], 0)
    mod = note_str[1:].count('#') - note_str[1:].count('b')
    return (octave + 1) * 12 + base + mod


# ── Détection tonalité (Krumhansl-Schmuckler) ─────────────────────────────────

def detect_key_signature(note_events) -> str:
    """
    Détecte la tonalité à partir des note_events.
    Copié depuis midi_parser.py V1 — ne pas modifier l'algorithme.

    note_events : List[(start, end, pitch_midi, amplitude)]
    Retourne : str (ex: 'C', 'G', 'Bb', 'F#')
    """
    # [Copier l'implémentation de midi_parser.detect_key_signature() ici]
    # Voir backend/midi_parser.py lignes 140-202
    ...


# ── Modifications `app.py` ────────────────────────────────────────────────────
# (Section documentaire — ne pas coder ici)
#
# Dans /api/transcribe, remplacer la section "Parser les notes" par :
#
#   from tempo_map    import build_tempo_map
#   from quantizer    import quantize_notes
#   from voice_engine import split_voices
#   from score_builder import build_score
#
#   tempo_map  = build_tempo_map(audio_path, note_events=note_events)
#   quantized  = quantize_notes(note_events, tempo_map, options)
#   voices     = split_voices(quantized, options)
#   key_sig    = options.get('key_sig', 'C')
#   score_data = build_score(voices, tempo_map, key_sig, options)
#
# Supprimer l'appel à parse_note_events() de midi_parser.


# ── Auto-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    Test d'intégration : créer un VoiceSplit synthétique et vérifier
    que le JSON produit est valide et complet (sum durées = beats_per_measure).
    """
    from quantizer import QuantizedNote
    from voice_engine import VoiceSplit
    from tempo_map import TempoMap
    import json

    bpm = 120.0
    beat_times = np.array([i * (60.0 / bpm) for i in range(32)])
    tm = TempoMap(
        beat_times=beat_times,
        downbeat_times=beat_times[::4],
        estimated_meter=(4, 4),
        global_bpm=bpm,
        method='test_synthetic'
    )

    def make_qn(pitch, pos, dur=1.0, hand='treble'):
        return QuantizedNote(
            pitch_midi=pitch, amplitude=0.7,
            beat_position=pos, beat_duration=dur,
            dur_str='q', dots=0, hand=hand
        )

    # 4 noires treble + 4 noires bass
    treble = [make_qn(60, 0), make_qn(62, 1), make_qn(64, 2), make_qn(65, 3)]
    bass   = [make_qn(48, 0, hand='bass'), make_qn(52, 2, hand='bass')]
    voices = VoiceSplit(treble=treble, bass=bass)

    score = build_score(voices, tm, key_sig='C')

    # Vérification
    assert score['totalMeasures'] == 1
    assert len(score['measures']) == 1
    m = score['measures'][0]

    treble_dur = sum(n['duration'] for n in m['treble'])
    bass_dur   = sum(n['duration'] for n in m['bass'])
    assert abs(treble_dur - 4.0) < 0.01, f"Treble sum = {treble_dur}, attendu 4.0"
    assert abs(bass_dur   - 4.0) < 0.01, f"Bass sum = {bass_dur}, attendu 4.0"

    print("[Test] ✓ Score construit, durées correctes")
    print(json.dumps(score, indent=2)[:500])  # Aperçu du JSON
```

---

## Modifications `midi_parser.py` (allégement)

Les fonctions suivantes sont **désormais dans `score_builder.py`** et doivent être **supprimées ou marquées deprecated** dans `midi_parser.py` :

| Fonction supprimée | Remplacée par |
|---|---|
| `parse_note_events()` | `score_builder.build_score()` |
| `_build_voice()` | `score_builder.build_voice_vexflow()` |
| `detect_key_signature()` | `score_builder.detect_key_signature()` |
| `midi_to_vexflow_key()` | `score_builder.midi_to_vexflow_key()` |
| `vexflow_key_to_pitch()` | `score_builder.vexflow_key_to_pitch()` |

**Fonctions conservées dans `midi_parser.py`** :
- `score_to_midi()` — export MIDI depuis JSON édité (inchangé)
- `beats_to_duration()`, `duration_beats()` — utilitaires (déjà dans `quantizer.py`)

> **Stratégie** : Ne pas supprimer immédiatement. Ajouter un `DeprecationWarning` et rediriger vers les nouvelles fonctions pour assurer la rétrocompatibilité pendant la transition.

---

## Tests de validation

### Test 1 : Intégrité des durées
Pour chaque mesure et chaque voix, la somme des durées doit être exactement `beats_per_measure`.
```python
for m in score['measures']:
    for hand in ['treble', 'bass']:
        total = sum(n['duration'] for n in m[hand])
        assert abs(total - beats_per_measure) < 0.001
```

### Test 2 : Test de régression JSON
Le JSON produit par V2 doit avoir la même structure que le JSON V1 pour un même fichier audio.
Clés obligatoires : `tempo`, `timeSignature`, `keySignature`, `totalMeasures`, `measures`.
Dans chaque note : `id`, `keys`, `durationStr`, `dots`, `isRest`, `startBeat`, `duration`, `midiPitch`, `hand`, `amplitude`.

### Test 3 : Test bout-en-bout
Lancer l'application avec `UNICORN ACADEMY THEME.mp3`, vérifier que la partition se charge sans erreur JavaScript, et que les premières mesures semblent cohérentes visuellement.
