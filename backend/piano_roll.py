"""
piano_roll.py — Regroupement des notes en Slices pour l'analyse harmonique
Version: 4.0

Responsabilités :
- Regrouper les QuantizedNote en accords verticaux (Slices)
- Fusionner les arpèges brisés rapides en un seul Slice
"""

import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

# On suppose que QuantizedNote a au moins : beat_position, duration_beats, pitch_midi (ou midi_note), start_beat
@dataclass
class Slice:
    beat_position: float
    duration_beats: float
    midi_pitches: List[int]
    is_arpeggio: bool = False
    onset_tolerance_ms: float = 30.0
    pedal_active: bool = False

# [FIX] Augmentation onset_tolerance_beats : 0.03 → 0.15 beat
# Pour musique classique avec rubato, les notes d'un accord peuvent être
# légèrement décalées. On élargit la fenêtre de groupement.
def group_into_slices(
    qnotes: list,
    onset_tolerance_beats: float = 0.15,  # Augmenté pour regrouper notes proches
    pedal_events: List[tuple[float, float]] = None
) -> List[Slice]:
    """
    Groupe les QuantizedNote en Slices harmoniques.
    Les notes avec des onsets très proches forment un accord vertical.
    
    pedal_events: liste de (start_beat, end_beat)
    """
    if not qnotes:
        return []

    # Essayer d'extraire beat_position de manière robuste (support V1, V2, V3)
    def get_beat(n):
        return getattr(n, 'beat_position', getattr(n, 'start_beat', 0.0))

    # Trier par onset
    sorted_notes = sorted(qnotes, key=get_beat)
    slices = []
    current_group = [sorted_notes[0]]

    for note in sorted_notes[1:]:
        # Si la note est proche de la précédente -> même Slice
        if get_beat(note) - get_beat(current_group[0]) <= onset_tolerance_beats:
            current_group.append(note)
        else:
            slices.append(_make_slice(current_group, pedal_events))
            current_group = [note]

    if current_group:
        slices.append(_make_slice(current_group, pedal_events))

    return slices

def _make_slice(notes: list, pedal_events: List[tuple[float, float]]) -> Slice:
    def get_beat(n): return getattr(n, 'beat_position', getattr(n, 'start_beat', 0.0))
    def get_pitch(n): return getattr(n, 'pitch_midi', getattr(n, 'midi_note', 60))
    def get_dur(n): return getattr(n, 'beat_duration', getattr(n, 'duration_beats', 1.0))
    
    beat_pos = get_beat(notes[0])
    pitches  = sorted([get_pitch(n) for n in notes])
    
    in_pedal = False
    if pedal_events:
        for p_start, p_end in pedal_events:
            if p_start <= beat_pos <= p_end:
                in_pedal = True
                break
                
    return Slice(
        beat_position=beat_pos,
        duration_beats=max(get_dur(n) for n in notes),
        midi_pitches=pitches,
        pedal_active=in_pedal
    )

# [FIX] Augmentation max_span_beats : 1.0 → 2.0 beats
# Pour musique classique (Mazurka Chopin) : les accords brisés rapides
# peuvent s'étendre sur ~1.5 beat avec le rubato
def fuse_arpeggios(
    slices: List[Slice],
    max_span_beats: float = 2.0,   # Augmenté pour regrouper notes proches en accords
    min_notes_in_arpeggio: int = 2  # Réduit à 2 pour capturer plus de cas
) -> List[Slice]:
    """
    Fusionne les séquences rapides de notes isolées en un seul Slice
    si elles forment vraisemblablement un arpège.
    """
    if not slices:
        return []
        
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

        # L'arpège a du sens s'il y a assez de notes (ou si la pédale les lie)
        # S'il y a pédale, on est plus clément sur la fusion des notes brisées
        is_arpeggiated = len(window) >= min_notes_in_arpeggio
        if not is_arpeggiated and len(window) >= 2 and any(s.pedal_active for s in window):
            is_arpeggiated = True

        if is_arpeggiated:
            # Fusionner en un seul Slice
            all_pitches = []
            for s in window:
                all_pitches.extend(s.midi_pitches)
            merged = Slice(
                beat_position=window[0].beat_position,
                duration_beats=window[-1].beat_position - window[0].beat_position + window[-1].duration_beats,
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
