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
    min_note_gap_beats: float = 0.0       # écart min entre notes snapées (0 = désactivé)


def _sensitivity_to_config(base: QuantizerConfig, sensitivity: float) -> QuantizerConfig:
    """
    Affine le preset de base selon la sensibilité continue [0.0-1.0].
    
    - 0.0  → quantification minimale (grille très fine 1/64, pas de snap, pas de fusion)
    - 0.5  → quantification intermédiaire (grille 1/16, snap doux, durée min courte)
    - 1.0  → preset de base inchangé (quantification forte selon le preset)
    
    Le mapping utilise une courbe linéaire simple pour un contrôle prévisible.
    """
    # Clamp dans [0, 1]
    s = max(0.0, min(1.0, sensitivity))
    
    # Configuration "minimale" (s=0) : quantification au plus proche sans snap
    MIN_GRID_DIV = 64        # grille très fine = pas d'aimantation
    MIN_SNAP = 0.0           # aucun snap à la grille
    MIN_DUR = 0.0625         # durée min = 1/64 (très court)
    MIN_MERGE = 0.0          # aucune fusion
    MIN_GAP = 0.0            # pas d'écart min
    
    # Configuration "maximale" (s=1) = preset de base
    MAX_GRID_DIV = base.grid_div     # ex: 8 pour classique
    MAX_SNAP = base.snap_threshold_ratio
    MAX_DUR = base.min_duration_beats
    MAX_MERGE = base.merge_threshold_beats
    MAX_GAP = base.min_note_gap_beats
    
    # Interpolation linéaire : s=0 → MIN, s=1 → MAX
    grid_div = int(round(MIN_GRID_DIV + (MAX_GRID_DIV - MIN_GRID_DIV) * s))
    snap_threshold = MIN_SNAP + (MAX_SNAP - MIN_SNAP) * s
    min_dur = MIN_DUR + (MAX_DUR - MIN_DUR) * s
    merge_thr = MIN_MERGE + (MAX_MERGE - MIN_MERGE) * s
    min_gap = MIN_GAP + (MAX_GAP - MIN_GAP) * s
    
    # grid_div doit être un diviseur valide de grille (puissance de 2 ou 12 pour ternaire)
    grid_div = max(4, min(64, grid_div))
    
    return QuantizerConfig(
        grid_div=grid_div,
        snap_threshold_ratio=snap_threshold,
        min_duration_beats=min_dur,
        merge_threshold_beats=merge_thr,
        allow_triplets=base.allow_triplets,
        min_note_gap_beats=min_gap,
    )


PRESETS = {
    'none':      QuantizerConfig(16, 0.00, 0.0,    0.00),
    'light':     QuantizerConfig(16, 0.25, 0.0625, 0.00, True),
    'standard':  QuantizerConfig(8,  0.40, 0.125,  0.05, True),
    'heavy':     QuantizerConfig(4,  0.50, 0.25,   0.10),
    'rubato':    QuantizerConfig(16, 0.20, 0.0625, 0.00, True),
    'triplets':  QuantizerConfig(12, 0.35, 0.125,  0.00, True),
    # classique : grille double-croche + ternaire, ornements préservés,
    # zéro fusion, aimantation douce. La précision vient de la tempo map.
    # snap_threshold_ratio réduit à 0.15 (était 0.30) pour éviter la fusion
    # de notes voisines qui sont à la limite de la grille.
    'classique': QuantizerConfig(8,  0.15, 0.125,  0.00, True),
    # NOUVEAU : preset "precision" pour transcription classique complexe.
    # Grille très fine (1/32 beat), snap très doux, durée min 1/64.
    # Idéal quand le transcriber (TruSinger/piano_transcription) fournit
    # des timings précis et qu'on veut minimiser la destruction rythmique.
    'precision': QuantizerConfig(32, 0.10, 0.0625, 0.00, True),
    # NOUVEAU (Plan C) : preset "ultra-classique" pour transcription classique
    # de style Chopin/Debussy avec ornements rapides et arpèges complexes.
    # Grille 1/16 beat (plus fine que classique=8), snap très doux (0.08),
    # durée min 1/64, zéro fusion, ternaire actif.
    # Cible : quand on veut une quantification "invisible" mais fonctionnelle.
    'ultra-classique': QuantizerConfig(16, 0.08, 0.0625, 0.00, True),
    # NOUVEAU (Plan D) : preset "classique-soft" — version adoucie de 'classique'.
    # Réduit le snap à 0.08 (était 0.15) pour éviter la fusion de notes voisines.
    # Idéal quand le transcriber est déjà précis et qu'on veut juste un léger alignement.
    'classique-soft': QuantizerConfig(8,  0.08, 0.125,  0.00, True),
    # NOUVEAU (Plan D) : preset "transkun" — optimisé pour le modèle Transkun.
    # Grille 1/16 beat, snap moyen (0.20), zéro fusion, ternaire actif.
    # Cible : quand le modèle fournit des timings précis mais qu'un léger
    # alignement rythmique est souhaité sans destruction du style.
    'transkun': QuantizerConfig(16, 0.20, 0.125,  0.00, True),
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


# ────────────────────────────────────────────────────────────── Protection basse
# Seuil en-dessous duquel une note est considérée comme "grave" (main gauche)
_BASS_PROTECT_PITCH = 55  # Si3 — notes < ce seuil sont protégées
# Seuil de vélocité minimal pour qu'une note grave soit considérée comme légitime
_BASS_PROTECT_MIN_VELOCITY = 0.01  # Presque n'importe quelle note grave est légitime


def _merge_same_pitch(notes: List[QuantizedNoteV4], thr: float) -> List[QuantizedNoteV4]:
    """Fusionne les notes de même pitch consécutives, MAIS protège les notes graves."""
    if thr <= 0 or not notes:
        return notes
    notes = sorted(notes, key=lambda n: (n.pitch_midi, n.beat_position))
    merged: List[QuantizedNoteV4] = []
    for n in notes:
        prev = merged[-1] if merged else None
        # PROTECTION BASSE : ne jamais fusionner une note grave protégée
        is_bass_protected = (
            n.pitch_midi < _BASS_PROTECT_PITCH and
            n.amplitude >= _BASS_PROTECT_MIN_VELOCITY
        )
        if (prev and prev.pitch_midi == n.pitch_midi and
            not is_bass_protected and
            (n.beat_position - prev.beat_end) < thr):
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
    quantization_sensitivity: float = None,  # NOUVEAU : contrôle continu [0.0-1.0]
) -> List[QuantizedNote]:
    """
    Signature étendue : quantization_sensitivity permet un réglage fin
    de la sensibilité de quantification sans changer de preset.
    
    - quantization_sensitivity=None (défaut) : utilise le preset tel quel
    - quantization_sensitivity=0.0 → quantification minimale
    - quantization_sensitivity=0.5 → quantification moyenne
    - quantization_sensitivity=1.0 → quantification forte
    
    Quand sensitivity est fourni, le preset sert de "base" mais les
    paramètres sont ajustés par _sensitivity_to_config().
    """
    base_cfg = PRESETS.get(quantization_level, PRESETS['standard'])
    
    # Si sensitivity est fourni, appliquer le mapping continu
    if quantization_sensitivity is not None:
        cfg = _sensitivity_to_config(base_cfg, quantization_sensitivity)
    else:
        cfg = base_cfg
    
    # Override pour rubato : réduire le snap pour préserver le micro-timing
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