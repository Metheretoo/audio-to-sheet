"""
quantizer.py — Quantization MIDI (V3)
Version : 1.0 (audio-to-sheet V3)

Objectif :
  Convertir les note_events (timestamps audio bruts) en événements MIDI
  quantisés alignés sur une grille temporelle rationnelle.

Caractéristiques :
  - Grille de quantification configurable (1/32, 1/16, 1/8, 1/4)
  - Alignement sur les downbeats
  - Fusion des notes chevauchantes (polyphonie)
  - Sortie compatible with Mido / pretty_midi
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum


# ── Types ──────────────────────────────────────────────────────────────────────

class QuantizationGrid(Enum):
    """Grille de quantification (durée en temps de battement / beat)."""
    THIRTY_SECOND = 0.25   # 1/32 de mesure (4 beats → 8 cellules)
    SIXTEENTH = 0.5        # 1/16 de mesure (4 beats → 4 cellules)
    EIGHTH = 1.0           # 1/8 de mesure
    QUARTER = 2.0          # 1/4 de mesure


@dataclass
class QuantizedNote:
    """
    Note quantisée — format V3 (compatible voice_engine + score_builder).

    Paramètres :
        pitch_midi     : note MIDI (0-127, 60 = C4)
        amplitude      : vélocité normalisée (0.0-1.0)
        beat_position  : position de début sur la grille de beats (fractionnaire)
        beat_duration  : durée brute en beats (avant quantisation musicale)
        dur_str        : durée musicale quantisée ('w','h','q','8','16','32')
        dots           : nombre de points (0, 1, 2)
        hand           : main assignée ('treble' ou 'bass')
    """
    pitch_midi:     int
    amplitude:      float
    beat_position:  float
    beat_duration:  float
    dur_str:        str   = 'q'
    dots:           int   = 0
    hand:           str   = 'treble'

    @property
    def beat_end(self) -> float:
        """Position de fin en beats."""
        return self.beat_position + self.beat_duration

    # Alias de rétrocompatibilité
    @property
    def midi_note(self) -> int:
        return self.pitch_midi

    @property
    def start_beat(self) -> float:
        return self.beat_position

    @property
    def duration_beats(self) -> float:
        return self.beat_duration

    @property
    def velocity(self) -> int:
        return int(min(127, self.amplitude * 127))


@dataclass
class QuantizedEvent:
    """
    Événement MIDI quantisé (note_on + note_off groupés).
    Conservé pour compatibilité avec NoteQuantizer.
    """
    note: QuantizedNote
    time_beat: float       # temps de début en beat
    velocity: int          # vélocité MIDI
    duration_beats: float  # durée en beats


# ── Quantizer principal ───────────────────────────────────────────────────────

class NoteQuantizer:
    """
    Quantifie les note_events audio en événements MIDI alignés.
    
    Usage :
        quantizer = NoteQuantizer(grid=QuantizationGrid.SIXTEENTH, bpm=120)
        quantized = quantizer.quantify(note_events)
    """

    def __init__(
        self,
        grid: QuantizationGrid = QuantizationGrid.SIXTEENTH,
        bpm: float = 120.0,
        velocity_scale: float = 1.0,
        min_note_duration_beats: float = 0.25,
        merge_threshold_beats: float = 0.1
    ):
        """
        Args:
            grid: grille de quantification
            bpm: BPM global pour conversion beat ↔ seconds
            velocity_scale: facteur de mise à l'échelle de vélocité (0.0-2.0)
            min_note_duration_beats: durée minimale d'une note en beats
            merge_threshold_beats: seuil de fusion des notes chevauchantes en beats
        """
        self.grid = grid
        self.bpm = bpm
        self.velocity_scale = velocity_scale
        self.min_note_duration_beats = min_note_duration_beats
        self.merge_threshold_beats = merge_threshold_beats
        self._beat_duration = 60.0 / bpm

    def update_tempo(self, bpm: float):
        """Mettre à jour le BPM et recalculer la durée d'un beat."""
        self.bpm = bpm
        self._beat_duration = 60.0 / bpm

    def quantify(
        self,
        note_events: list,
        downbeat_times: Optional[np.ndarray] = None
    ) -> List[QuantizedEvent]:
        """
        Quantifie les note_events en événements MIDI.
        
        Args:
            note_events: liste de (onset_sec, pitch, duration, velocity)
            downbeat_times: timestamps des downbeats (optionnel)
            
        Returns:
            liste de QuantizedEvent
        """
        if not note_events:
            return []

        # Étape 1: Quantifier chaque note individuellement
        quantized_notes = []
        for onset_sec, pitch, duration, velocity in note_events:
            # Convertir onset en beat (relatif au premier downbeat ou au début)
            start_beat = onset_sec / self._beat_duration

            # Quantifier la position sur la grille
            grid_cell = self._quantize_position(start_beat, self.grid.value)
            start_beat_quantized = grid_cell * self.grid.value

            # Quantifier la durée
            duration_beats = duration / self._beat_duration
            duration_beats = self._quantize_duration(duration_beats)

            # Appliquer le scale de vélocité
            velocity_scaled = int(min(127, velocity * self.velocity_scale))

            quantized_notes.append(QuantizedEvent(
                note=QuantizedNote(
                    midi_note=int(round(pitch)),
                    start_beat=start_beat_quantized,
                    duration_beats=duration_beats,
                    velocity=velocity_scaled,
                    confidence=1.0
                ),
                time_beat=start_beat_quantized,
                velocity=velocity_scaled,
                duration_beats=duration_beats
            ))

        # Étape 2: Fusionner les notes chevauchantes (même pitch)
        quantized_notes = self._merge_overlapping(quantized_notes)

        # Étape 3: Trier par temps de début
        quantized_notes.sort(key=lambda e: e.time_beat)

        return quantized_notes

    def _quantize_position(self, position: float, grid_size: float) -> int:
        """
        Quantifie une position sur une grille de taille donnée.
        
        Exemple :
            position = 3.7 beats, grid_size = 0.5 (1/16)
            grid_cell = round(3.7 / 0.5) = round(7.4) = 7
            quantized = 7 * 0.5 = 3.5 beats
        """
        return int(round(position / grid_size))

    def _quantize_duration(self, duration_beats: float) -> float:
        """
        Quantifie la durée à la grille la plus proche.
        
        Les durats possibles : 1/32, 1/16, 1/8, 1/4, 3/16, 1/2, 3/4, 1, 2, 4
        """
    # Liste des durats canoniques en beats (pour un BPM donné)
        # Ces valeurs sont relatives au beat (1 beat = 1.0)
        # Inclut les triolets (ratio 2/3 = 1.5x plus court)
        canonical_durations = [
            0.125,  # 1/64 (pour rubato)
            0.167,  # 1/64 triplet (1/96)
            0.25,   # 1/32
            0.333,  # 1/32 triplet (1/48)
            0.5,    # 1/16
            0.667,  # 1/16 triplet (1/24)
            0.75,   # 3/32
            1.0,    # 1/8
            1.333,  # 1/8 triplet (1/6)
            1.5,    # 3/16
            2.0,    # 1/4
            2.667,  # 1/4 triplet (2/3)
            3.0,    # 3/8
            4.0,    # 1/2
            5.333,  # 1/2 triplet (4/3)
            6.0,    # 3/4
            8.0,    # 1 (pleine mesure 4/4)
            10.667, # 1 triplet (8/3)
            16.0,   # 2 mesures
        ]

        # Trouver la durée canonique la plus proche
        best = canonical_durations[0]
        best_err = abs(duration_beats - best)
        for d in canonical_durations[1:]:
            err = abs(duration_beats - d)
            if err < best_err:
                best = d
                best_err = err

        return max(best, self.min_note_duration_beats)

    def _merge_overlapping(
        self,
        events: List[QuantizedEvent]
    ) -> List[QuantizedEvent]:
        """
        Fusionne les notes de même pitch qui se chevauchent.
        
        Algorithme :
        1. Grouper par pitch (note de musique)
        2. Pour chaque groupe, fusionner les événements qui se chevauchent
        3. Retourner la liste fusionnée
        """
        # Grouper par pitch
        groups: dict[int, List[QuantizedEvent]] = {}
        for event in events:
            pitch = event.note.midi_note
            if pitch not in groups:
                groups[pitch] = []
            groups[pitch].append(event)

        # Fusionner chaque groupe
        result = []
        for pitch, group in groups.items():
            group.sort(key=lambda e: e.time_beat)
            merged = self._merge_group(group)
            result.extend(merged)

        return result

    def _merge_group(
        self,
        events: List[QuantizedEvent]
    ) -> List[QuantizedEvent]:
        """
        Fusionne les événements d'un même pitch qui se chevauchent.
        
        Règle :
        - Si deux événements se chevauchent (écart < merge_threshold),
          les fusionner en un seul avec :
            * onset = min(onset1, onset2)
            * duration = max(end1, end2) - min(onset1, onset2)
            * velocity = max(velocity1, velocity2)
        """
        if not events:
            return []

        merged = [events[0].copy()]

        for event in events[1:]:
            last = merged[-1]

            # Vérifier le chevauchement
            if event.time_beat < last.time_beat + last.duration_beats - self.merge_threshold_beats:
                # Chevauchement détecté → fusionner
                new_onset = min(last.time_beat, event.time_beat)
                new_end = max(
                    last.time_beat + last.duration_beats,
                    event.time_beat + event.duration_beats
                )
                new_duration = new_end - new_onset
                new_velocity = max(last.velocity, event.velocity)

                # Mettre à jour l'événement fusionné
                last.note.start_beat = new_onset
                last.note.duration_beats = new_duration
                last.note.velocity = new_velocity
                last.time_beat = new_onset
                last.duration_beats = new_duration
                last.velocity = new_velocity
            else:
                # Pas de chevauchement → nouveau événement
                merged.append(event)

        return merged


# ── Utilitaires ────────────────────────────────────────────────────────────────

def quantize_note_events(
    note_events: list,
    bpm: float = 120.0,
    grid: QuantizationGrid = QuantizationGrid.SIXTEENTH
) -> List[QuantizedEvent]:
    """
    Fonction utilitaire pour quantifier rapidement des note_events.
    
    Args:
        note_events: liste de (onset_sec, pitch, duration, velocity)
        bpm: BPM global
        grid: grille de quantification
        
    Returns:
        liste de QuantizedEvent
    """
    quantizer = NoteQuantizer(grid=grid, bpm=bpm)
    return quantizer.quantify(note_events)


# ── Export pour compatibilité ──────────────────────────────────────────────────

# Compatibilité avec le code existant
Note = QuantizedNote
MidiEvent = QuantizedEvent

# Réexport depuis midi_parser pour les fichiers qui importent ces fonctions depuis quantizer
# (score_builder.py, _validate_pipeline.py)
from midi_parser import beats_to_duration, duration_beats  # noqa: F401, E402


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
    """
    Convertit des note_events bruts en QuantizedNote V3.

    Args:
        note_events : liste de (onset_sec, pitch_midi, duration_sec, velocity_0_127)
                      OU objets avec attributs .onset, .duration, .pitch_midi, .amplitude
        tempo_map   : TempoMap (optionnel) — si fourni, utilisé pour la conversion beats
        bpm         : BPM global (utilisé si tempo_map est None)
        tempo       : alias de bpm (rétrocompatibilité)
        key_sig     : armure (non utilisé ici, pour compatibilité _validate_pipeline)
        time_sig    : mesure (non utilisé ici, pour compatibilité)
        quantization_level : niveau de quantisation
            - 'none'     : pas de quantisation (position brute, arrondie à 1/64)
            - 'light'    : grille 1/16 beat (triple croche)
            - 'standard' : grille 1/8  beat (double croche)  [défaut]
            - 'heavy'    : grille 1/4  beat (croche)
        enable_rubato : si True, utilise une grille très fine (1/32 beat) pour le rubato expressif
        enable_triplets : si True, autorise les durées de triolet dans la quantification

    Returns:
        liste de QuantizedNote (V3)
    """
    # Résoudre le BPM effectif
    effective_bpm = bpm
    if tempo is not None:
        effective_bpm = tempo
    if tempo_map is not None:
        effective_bpm = tempo_map.global_bpm

    beat_s = 60.0 / max(effective_bpm, 20.0)

    # Choisir la résolution de la grille de position
    # (diviseur : nombre de subdivisions par beat)
    grid_map = {
        'none':      16,   # 1/16 beat ≈ très fin (quasi brut)
        'light':     16,   # 1/16 beat = triple-croche
        'standard':   8,   # 1/8  beat = double-croche
        'heavy':      4,   # 1/4  beat = croche
        'rubato':    32,   # 1/32 beat : capte le micro-timing expressif
        'triplets':  12,   # 1/12 beat : base triolet + subdivisions binaires
        'classique': 32,   # NOUVEAU : 1/32 beat, comparable au rubato mais
                           # avec snap réel actif (voir snap_map ci-dessous)
    }
    grid_div = grid_map.get(quantization_level, 8)

    # Grille d'aimantation : résolution vers laquelle on attire les notes proches
    # pour éliminer les micro-silences parasites.
    #
    # IMPORTANT : snap_div est en DIVISIONS PAR BEAT, donc :
    #   snap_div = 2  → snap_step = 0.5 beat = CROCHE
    #   snap_div = 1  → snap_step = 1.0 beat = NOIRE
    #
    # Le threshold à 30% évite d'avaler les vraies doubles-croches intentionnelles :
    #   note à 0.125 beat d'une croche → snap (car 0.125 < 0.5*0.30=0.15) ✓
    #   note à 0.25 beat d'une croche  → pas snap (car 0.25 > 0.15) ✓ (double-croche voulue)
    snap_map = {
        'none':      0,    # pas d'aimantation
        'light':     4,    # → double-croche (snap_step=0.25)
        'standard':  2,    # → croche       (snap_step=0.5)
        'heavy':     1,    # → noire         (snap_step=1.0)
        'rubato':    4,    # → double-croche : garde le rubato mais lisible
        'triplets':  3,    # → tiers de beat : aimantation sur triolets
        'classique': 4,    # NOUVEAU : aimantation sur double-croche
    }
    snap_div = snap_map.get(quantization_level, 2)
    snap_threshold_ratio = 0.45   # 45% de la cellule = aimantation forte pour éviter la "soupe"

    # BUG CORRIGÉ (v4.1) : le mode Rubato forçait auparavant grid_div=32 ET
    # désactivait complètement l'aimantation (snap_div=0), ÉCRASANT le niveau
    # de quantification choisi par l'utilisateur. Résultat : impossible d'obtenir
    # une partition lisible en Rubato, quel que soit le réglage "Forte/Standard/
    # Légère" choisi ("soupe de notes" signalée en retour).
    #
    # Le Rubato doit uniquement permettre de CAPTER le micro-timing expressif
    # (grille fine), pas supprimer toute aimantation rythmique. On affine donc
    # la grille sans jamais la dégrader (max avec la grille déjà choisie), et on
    # relâche l'aimantation au lieu de la couper : le rythme reste lisible tout
    # en conservant davantage de nuance qu'en mode non-rubato.
    if enable_rubato:
        grid_div = max(grid_div, 32)  # au moins 1/32 beat
        if snap_div > 0:
            snap_div = min(snap_div * 2, 8)
            snap_threshold_ratio = 0.30

    result: List[QuantizedNote] = []

    for event in note_events:
        # Support tuple (onset, pitch, duration, velocity) ET objets SimpleNamespace
        if isinstance(event, (list, tuple)):
            onset_sec   = float(event[0])
            pitch_midi  = int(event[1])
            duration_sec = float(event[2])
            velocity    = int(event[3]) if len(event) > 3 else 80
        else:
            onset_sec    = float(event.onset)
            pitch_midi   = int(event.pitch_midi)
            duration_sec = float(event.duration)
            velocity     = int(getattr(event, 'amplitude', 0.8) * 127)

        amplitude = min(1.0, velocity / 127.0)

        # Convertir onset et duration en beat
        if tempo_map is not None:
            beat_position = tempo_map.seconds_to_beat(onset_sec)
            beat_end = tempo_map.seconds_to_beat(onset_sec + duration_sec)
            beat_duration = beat_end - beat_position
        else:
            beat_position = onset_sec / beat_s
            beat_duration = duration_sec / beat_s

        beat_position = max(0.0, beat_position)
        beat_duration = max(0.125, beat_duration)  # min = double croche

        # Arrondir la position sur la grille choisie
        if quantization_level == 'none':
            # Pas d'arrondi : conserver la position brute (arrondie à la milliseconde)
            beat_position = round(beat_position * 1000) / 1000
        else:
            # 1. Quantification sur la grille fine
            beat_position = round(beat_position * grid_div) / grid_div

            # 2. ── Aimantation vers grille grossière ──
            # snap_step = taille d'une cellule de la grille grossière (en beats)
            # Exemple standard : snap_step=0.5 (croche)
            # Une note à 0.125 beat d'une croche → snap_step=0.5, remainder=0.125
            # 0.125 < 0.5*0.30=0.15 → aimantée ✓
            if snap_div > 0:
                snap_step = 1.0 / snap_div
                threshold = snap_step * snap_threshold_ratio
                remainder = beat_position % snap_step
                if remainder < threshold:            # proche du début de cellule
                    beat_position = beat_position - remainder
                elif remainder > snap_step - threshold:  # proche de la fin (début de la suivante)
                    beat_position = beat_position - remainder + snap_step
                beat_position = round(beat_position, 9)

        # Quantiser la durée musicalement
        dur_str, dots = beats_to_duration(beat_duration)

        result.append(QuantizedNote(
            pitch_midi=pitch_midi,
            amplitude=amplitude,
            beat_position=beat_position,
            beat_duration=beat_duration,
            dur_str=dur_str,
            dots=dots,
            hand='treble'  # sera reclassifié par split_voices
        ))

    # Trier par position
    result.sort(key=lambda n: n.beat_position)
    return result



# ── Auto-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("="*60)
    print("[Test] Quantizer V3")
    print("="*60)

    # Données de test : (onset_sec, pitch, duration, velocity)
    test_notes = [
        (0.0,   60, 0.5, 100),  # C4
        (0.5,   64, 0.5, 90),   # E4
        (1.0,   67, 1.0, 110),  # G4
        (1.5,   60, 0.5, 100),  # C4
        (2.0,   62, 0.5, 95),   # D4
        (2.5,   64, 1.0, 100),  # E4
        (3.5,   67, 0.5, 110),  # G4
        (4.0,   72, 2.0, 120),  # C5 (note tenue longue)
    ]

    quantizer = NoteQuantizer(grid=QuantizationGrid.SIXTEENTH, bpm=120)
    quantized = quantizer.quantify(test_notes)

    print(f"\nBPM: {quantizer.bpm}")
    print(f"Grille: {quantizer.grid.name} ({quantizer.grid.value} beats)")
    print(f"\n{'Input':<30} {'Quantized':<30}")
    print("-" * 60)

    for i, (inp, out) in enumerate(zip(test_notes, quantized)):
        onset, pitch, dur, vel = inp
        print(
            f"  onset={onset:.1f}s pitch={pitch} dur={dur:.1f}s vel={vel}    ->    "
            f"beat={out.time_beat:.3f} pitch={out.note.midi_note} "
            f"dur={out.duration_beats:.2f} beats vel={out.velocity}"
        )

    print(f"\n[Test] SUCCES - {len(quantized)} notes quantizees")
    print("="*60)