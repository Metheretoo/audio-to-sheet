"""
Quantizer V4 — tempo-map-aware et non destructif.
Drop-in replacement de quantizer.quantize_notes :
même signature, même type de retour (List[QuantizedNote]).

Différences vs V3 :
  - Conversion secondes → beats via tm.seconds_to_beat() (suit le rubato)
    au lieu d'un BPM global fixe.
  - Timings originaux conservés (champs *_raw) : rien n'est écrasé.
  - Seuils par preset, plus de valeurs codées en dur :
    * 'classique' : AUCUNE fusion de notes, durée min = triple-croche,
      aimantation douce (0.30), triolets actifs.
  - Aimantation intelligente : grille binaire ET ternaire en concurrence,
    la plus proche gagne ; hors seuil → grille fine 1/48 (pas de saut forcé).
"""

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

from quantizer import QuantizedNote  # dataclass V3 (compat voice_engine + score_builder)


# ────────────────────────────────────────────────────────────── structures

@dataclass
class QuantizedNoteV4(QuantizedNote):
    """QuantizedNote enrichie : conserve les timings originaux."""
    onset_sec_raw:     float = 0.0
    duration_sec_raw:  float = 0.0
    beat_position_raw: float = 0.0
    beat_duration_raw: float = 0.0


@dataclass
class QuantizerConfig:
    grid_div: int = 8                     # subdivisions binaires par beat
    snap_threshold_ratio: float = 0.45    # aimantation (0 = désactivée)
    min_duration_beats: float = 0.25      # durée minimale notée
    merge_threshold_beats: float = 0.1    # fusion notes répétées (0 = jamais)
    allow_triplets: bool = False


PRESETS = {
    'none':      QuantizerConfig(16, 0.00, 0.0,    0.00),
    'light':     QuantizerConfig(16, 0.25, 0.0625, 0.00, True),
    'standard':  QuantizerConfig(8,  0.40, 0.125,  0.05, True),
    'heavy':     QuantizerConfig(4,  0.50, 0.25,   0.10),
    'rubato':    QuantizerConfig(16, 0.20, 0.0625, 0.00, True),
    'triplets':  QuantizerConfig(12, 0.35, 0.125,  0.00, True),
    # classique : grille double-croche + ternaire, ornements préservés,
    # zéro fusion, aimantation douce. La précision vient de la tempo map.
    'classique': QuantizerConfig(8,  0.30, 0.125,  0.00, True),
}

# durée en beats → (dur_str, dots)  [beat = noire]
_DUR_TABLE = [
    (6.0,   'w', 1), (4.0,  'w', 0),
    (3.0,   'h', 1), (2.0,  'h', 0),
    (1.5,   'q', 1), (1.0,  'q', 0),
    (0.75,  '8', 1), (0.5,  '8', 0),
    (0.375, '16', 1), (0.25, '16', 0),
    (0.125, '32', 0),
]


# ────────────────────────────────────────────────────────────── helpers

def _to_amplitude(v) -> float:
    """Normalisation vélocité unique : accepte 0-1 ou 0-127, sort 0.0-1.0."""
    v = float(v)
    if v > 1.0:
        v = v / 127.0
    return max(0.0, min(1.0, v))


def _snap_position(value: float, cfg: QuantizerConfig) -> float:
    """Aimante sur la grille binaire OU ternaire la plus proche.
    Hors seuil : grille fine 1/48 (on n'écrase pas l'intention rythmique)."""
    fine = max(0.0, round(value * 48) / 48)
    if cfg.snap_threshold_ratio <= 0 or cfg.grid_div <= 0:
        return fine
    step = 1.0 / cfg.grid_div
    candidates = [round(value / step) * step]
    if cfg.allow_triplets:
        for t_step in (1.0 / 3.0, 1.0 / 6.0):
            candidates.append(round(value / t_step) * t_step)
    best = min(candidates, key=lambda c: abs(value - c))
    if abs(value - best) <= cfg.snap_threshold_ratio * step:
        return max(0.0, best)
    return fine


def _nearest_notation(beats: float) -> Tuple[str, int]:
    beats = max(beats, 1e-3)
    d = min(_DUR_TABLE, key=lambda row: abs(row[0] - beats))
    return d[1], d[2]


def _merge_same_pitch(notes: List[QuantizedNoteV4], thr: float) -> List[QuantizedNoteV4]:
    if thr <= 0 or not notes:
        return notes
    notes = sorted(notes, key=lambda n: (n.pitch_midi, n.beat_position))
    merged: List[QuantizedNoteV4] = []
    for n in notes:
        prev = merged[-1] if merged else None
        if prev and prev.pitch_midi == n.pitch_midi and \
           (n.beat_position - prev.beat_end) < thr:
            prev.beat_duration = (n.beat_position + n.beat_duration) - prev.beat_position
            prev.amplitude = max(prev.amplitude, n.amplitude)
            prev.dur_str, prev.dots = _nearest_notation(prev.beat_duration)
        else:
            merged.append(n)
    merged.sort(key=lambda n: (n.beat_position, n.pitch_midi))
    return merged


# ────────────────────────────────────────────────────────────── API publique

def quantize_notes(
    note_events: list,
    tempo_map=None,
    key_sig: str = 'C',
    time_sig: tuple = (4, 4),
    bpm: float = 120.0,
    tempo: float = None,
    quantization_level: str = 'standard',
    enable_rubato: bool = False,
    enable_triplets: bool = False,
) -> List[QuantizedNote]:
    """Signature identique à quantizer.quantize_notes (drop-in)."""
    cfg = PRESETS.get(quantization_level, PRESETS['standard'])
    if enable_rubato:
        cfg = replace(cfg, snap_threshold_ratio=min(cfg.snap_threshold_ratio, 0.20))
    if enable_triplets:
        cfg = replace(cfg, allow_triplets=True)

    eff_bpm = float(tempo or bpm or 120.0)

    def to_beats(t_sec: float) -> float:
        """Cœur du fix : interpolation sur la tempo map réelle → le rubato
        devient linéaire en espace 'beats'. Fallback BPM fixe si absente."""
        if tempo_map is not None and hasattr(tempo_map, 'seconds_to_beat'):
            try:
                return float(tempo_map.seconds_to_beat(t_sec))
            except Exception:
                pass
        return t_sec * eff_bpm / 60.0

    out: List[QuantizedNoteV4] = []
    for ev in note_events:
        onset_s, pitch, dur_s, vel = float(ev[0]), int(ev[1]), float(ev[2]), ev[3]

        b_on_raw = to_beats(onset_s)
        b_off_raw = to_beats(onset_s + dur_s)
        b_dur_raw = max(b_off_raw - b_on_raw, 1e-4)

        b_on = _snap_position(b_on_raw, cfg)
        b_dur = max(b_dur_raw, cfg.min_duration_beats) if cfg.min_duration_beats > 0 else b_dur_raw
        dur_str, dots = _nearest_notation(b_dur)

        out.append(QuantizedNoteV4(
            pitch_midi=pitch,
            amplitude=_to_amplitude(vel),
            beat_position=b_on,
            beat_duration=b_dur,
            dur_str=dur_str,
            dots=dots,
            onset_sec_raw=onset_s,
            duration_sec_raw=dur_s,
            beat_position_raw=b_on_raw,
            beat_duration_raw=b_dur_raw,
        ))

    out = _merge_same_pitch(out, cfg.merge_threshold_beats)
    out.sort(key=lambda n: (n.beat_position, n.pitch_midi))
    return out


if __name__ == "__main__":
    # Auto-test : appoggiature (50 ms) + note principale, rubato simulé
    events = [(0.98, 77, 0.05, 90), (1.03, 76, 0.60, 100), (1.66, 72, 0.30, 80)]
    notes = quantize_notes(events, bpm=120.0, quantization_level='classique')
    for n in notes:
        print(f"pitch={n.pitch_midi} pos={n.beat_position:.3f} "
              f"(raw={n.beat_position_raw:.3f}) dur={n.dur_str}{'.' * n.dots}")
    assert len(notes) == 3, "l'appoggiature ne doit PAS être fusionnée"
    print("OK — ornements préservés, timings raw conservés")