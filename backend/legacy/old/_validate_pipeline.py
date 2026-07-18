"""
_validate_pipeline.py
Validation du pipeline quantizer + score_builder apres refactoring.
Lance avec : python backend/_validate_pipeline.py
"""
import sys, os, numpy as np
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(__file__))

from quantizer import beats_to_duration, duration_beats, quantize_notes
from score_builder import build_voice_vexflow, _split_rests, build_score
from voice_engine import split_voices, VoiceSplit
from tempo_map import TempoMap
from quantizer import QuantizedNote

PASS = "[OK]"
FAIL = "[FAIL]"
errors = []

def check(label, got, expected):
    ok = got == expected
    status = PASS if ok else FAIL
    print(f"  {status} {label}: attendu={expected!r}, obtenu={got!r}")
    if not ok:
        errors.append(label)

# ────────────────────────────────────────────────────────────────────
print("\n== 1. beats_to_duration (arrondi musical) ==")
cases = [
    (0.85, False, 'q',   0),   # noire   : 85% >= 65% de 1.0
    (0.90, False, 'q',   0),   # noire   : 90% >= 65% de 1.0
    (0.65, False, '8',   1),   # croche pointee : 0.65 < 0.75 -> best_up=0.75 ; 65% >= 65%*0.75
    (0.64, False, '8',   1),   # croche pointee : idem
    (0.75, False, '8',   1),   # croche pointee exacte
    (0.70, False, '8',   1),   # croche pointee : 70% < 65% de 1.0, mais 70% >= 65% de 0.75
    (1.70, False, 'h',   0),   # blanche  : 85% >= 65% de 2.0
    (1.30, False, 'q',   1),   # noire pointee : 1.3 < 1.5 -> best_up=1.5 ; 87% >= 65%*1.5
    (1.29, False, 'q',   1),   # noire pointee
    (0.50, False, '8',   0),   # croche exacte
    (1.00, False, 'q',   0),   # noire exacte
    (2.00, False, 'h',   0),   # blanche exacte
    # floor=True
    (1.70, True,  'q',   1),   # floor -> noire pointee (1.5 <= 1.7)
    (2.50, True,  'h',   0),   # floor -> blanche (2.0 <= 2.5)
    (0.80, True,  '8',   1),   # floor -> croche pointee (0.75 <= 0.8)
    (0.60, True,  '8',   0),   # floor -> croche (0.5 <= 0.6)
]
for beats, floor, exp_str, exp_dots in cases:
    got_str, got_dots = beats_to_duration(beats, floor=floor)
    check(f"beats_to_duration({beats}, floor={floor})",
          (got_str, got_dots), (exp_str, exp_dots))

# ────────────────────────────────────────────────────────────────────
print("\n== 2. _split_rests (pas de residus < double-croche) ==")
# 1 noire de silence
rests = _split_rests(1.0, 0.0, 'bass')
check("1 noire silence -> 1 element", len(rests), 1)
check("1 noire silence -> dur='q'", rests[0]['durationStr'], 'q')

# 2 beats de silence -> blanche
rests = _split_rests(2.0, 0.0, 'treble')
check("2 beats silence -> 1 element (blanche)", len(rests), 1)

# 1.5 beats -> noire pointee
rests = _split_rests(1.5, 0.0, 'bass')
check("1.5 beats -> 1 element", len(rests), 1)
check("1.5 beats -> dur='q' dots=1", (rests[0]['durationStr'], rests[0]['dots']), ('q', 1))

# 0.20 beats (residus flottant) -> ignores
rests = _split_rests(0.20, 0.0, 'bass')
check("0.20 beats ignores (< double-croche)", rests, [])

# ────────────────────────────────────────────────────────────────────
print("\n== 3. build_voice_vexflow (laisser sonner) ==")

def make_qn(pitch, pos, raw_dur, hand='bass'):
    dur_str, dots = beats_to_duration(raw_dur)
    return QuantizedNote(
        pitch_midi=pitch, amplitude=0.7,
        beat_position=pos, beat_duration=raw_dur,
        dur_str=dur_str, dots=dots, hand=hand
    )

# Main gauche : 2 notes separees de 2 beats, sustain brut = 0.75
# Attendu : chacune etendue a 2 beats (blanche) par la logique "laisser sonner"
bass_notes = [make_qn(48, 0.0, 0.75), make_qn(48, 2.0, 0.75)]
voice = build_voice_vexflow(bass_notes, m_start=0.0, beats_per_measure=4.0, hand='bass')
real_notes = [v for v in voice if not v['isRest']]
check("2 notes bass sur 4 beats : count notes", len(real_notes), 2)
check("note 1 dure une blanche (IOI=2.0)", real_notes[0]['durationStr'], 'h')
check("note 2 dure une blanche (IOI=2.0)", real_notes[1]['durationStr'], 'h')
rests_in_voice = [v for v in voice if v['isRest']]
check("aucun silence parasite entre les 2 notes", len(rests_in_voice), 0)

# Note staccato : sustain brut = 0.15, IOI = 1.0
# is_staccato = (0.15 < 0.4*1.0) AND (0.15 < 0.5) -> True
# target = raw_dur = 0.15 -> double-croche
staccato = [make_qn(60, 0.0, 0.15, hand='treble'), make_qn(62, 1.0, 0.15, hand='treble')]
voice_s = build_voice_vexflow(staccato, m_start=0.0, beats_per_measure=4.0, hand='treble')
note_s = [v for v in voice_s if not v['isRest']]
check("staccato 0.15 vs IOI 1.0 : dur='16' (double-croche)",
      note_s[0]['durationStr'], '16')

# ────────────────────────────────────────────────────────────────────
print("\n== 4. quantize_notes (objets SimpleNamespace) ==")
bpm = 120.0
beat_s = 60.0 / bpm
beat_times = np.array([i * beat_s for i in range(32)])
tm = TempoMap(
    beat_times=beat_times,
    downbeat_times=beat_times[::4],
    estimated_meter=(4, 4),
    global_bpm=bpm,
    method='test'
)
# 4 noires bass (C3) separees de 1 beat avec sustain 0.85 beats
# quantize_notes attend des objets avec .onset, .duration, .pitch_midi, .amplitude
bass_events = [
    SimpleNamespace(onset=i * beat_s, duration=beat_s * 0.85, pitch_midi=48, amplitude=0.8)
    for i in range(4)
]
notes = quantize_notes(bass_events, tm, 'C', (4, 4))
check("4 noires C3 quantifiees", len(notes), 4)
for i, n in enumerate(notes):
    check(f"  noire {i} : beat_duration brute proche de 0.85",
          abs(n.beat_duration - 0.85) < 0.05, True)

# ────────────────────────────────────────────────────────────────────
print("\n== 5. split_voices + build_score (notes quantisees) ==")
voices = split_voices(notes)
score = build_score(voices, tm, key_sig='C')
m0_bass = score['measures'][0]['bass']
notes_bass = [x for x in m0_bass if not x['isRest']]
rests_bass = [x for x in m0_bass if x['isRest']]
check("mesure 1 bass : 4 notes", len(notes_bass), 4)
check("mesure 1 bass : 0 silence (notes tenues)", len(rests_bass), 0)
for i, nb in enumerate(notes_bass):
    check(f"  note bass {i} etendue a noire (IOI)", nb['durationStr'], 'q')

# ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 50)
if errors:
    print(f"ECHECS ({len(errors)}) : {', '.join(errors)}")
    sys.exit(1)
else:
    print("Tous les tests passes.")
