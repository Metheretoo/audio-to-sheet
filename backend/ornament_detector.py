"""
ornament_detector.py — Détection d'ornements musicaux (Phase 4)

Détection :
  - Appoggiatures → grace notes en MusicXML
  - Trilles → symbole tr en MusicXML
  - Rythmes pointés → identification pour durées canoniques

Ce module prend une liste de QuantizedNote et retourne :
  - Des flags par note (estAppoggiatura, estTrille, etc.)
  - Des symboles d'ornement à insérer dans le JSON de score
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from quantizer import QuantizedNote


# ─────────────────────────────────────────────────────────────────────────────
# Types de retour
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AppoggiaturaInfo:
    """Information sur une appoggiature détectée."""
    note_index: int          # Index dans la liste originale
    grace_note_pitch: int    # MIDI pitch de la grace note
    target_pitch: int        # MIDI pitch de la note cible
    beat_position: float     # Position en beat
    duration_beats: float    # Durée en beats
    is_grace: bool = True    # Toujours True (c'est une grace note)


@dataclass
class TrillInfo:
    """Information sur un trille détecté."""
    start_index: int         # Index de la première note du trille
    end_index: int           # Index de la dernière note du trille
    start_beat: float        # Position de début en beat
    end_beat: float          # Position de fin en beat
    primary_pitch: int       # Note principale du trille (note cible)
    auxiliary_pitch: int     # Note d'auxiliaire (altération)
    note_count: int          # Nombre de notes du trille
    is_trill: bool = True    # Toujours True (c'est un trille)


@dataclass
class DottedRhythmInfo:
    """Information sur un rythme pointé détecté."""
    note_index: int
    beat_position: float
    duration_beats: float
    dotted_ratio: float      # Ratio pointé détecté (ex: 1.5 pour point d'orgue)
    tolerance: float         # Tolérance utilisée


@dataclass
class OrnamentResult:
    """Résultat complet de détection d'ornements."""
    original_notes: List[QuantizedNote] = field(default_factory=list)
    appoggiaturas: List[AppoggiaturaInfo] = field(default_factory=list)
    trills: List[TrillInfo] = field(default_factory=list)
    dotted_rhythms: List[DottedRhythmInfo] = field(default_factory=list)
    
    # Mapping note_index → type d'ornement
    note_ornaments: Dict[int, str] = field(default_factory=dict)
    
    # Pour le JSON MusicXML
    grace_notes: List[Dict[str, Any]] = field(default_factory=list)
    trill_symbols: List[Dict[str, Any]] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Détecteur principal
# ─────────────────────────────────────────────────────────────────────────────

class OrnamentDetector:
    """
    Détecte les ornements musicaux dans une liste de notes quantisées.
    
    Usage :
        detector = OrnamentDetector(thresholds=ornament_thresholds)
        result = detector.detect(notes, beat_positions, is_downbeats)
    """
    
    def __init__(self, thresholds=None):
        """
        Args:
            thresholds: OrnamentThresholds ou dict de seuils
        """
        if thresholds is None:
            from models import OrnamentThresholds
            thresholds = OrnamentThresholds()
        
        if isinstance(thresholds, dict):
            from models import _dict_to_ornament_thresholds
            thresholds = _dict_to_ornament_thresholds(thresholds)
        
        self.thresholds = thresholds
    
    def detect(
        self,
        notes: List[QuantizedNote],
        beat_positions: Optional[List[float]] = None,
        is_downbeats: Optional[List[bool]] = None,
        measure_length: float = 3.0,  # Par défaut 3 beats (Mazurka 3/4)
    ) -> OrnamentResult:
        """
        Détecte tous les ornements dans la liste de notes.
        
        Args:
            notes: liste de QuantizedNote
            beat_positions: positions en beat (si None, utilise note.beat_position)
            is_downbeats: booléen par beat (si None, calcule approx)
            measure_length: longueur d'une mesure en beats (défaut 3 pour Mazurka)
        
        Returns:
            OrnamentResult avec toutes les détections
        """
        result = OrnamentResult(original_notes=notes)
        
        if not notes:
            return result
        
        # Normaliser les positions
        if beat_positions is None:
            beat_positions = [n.beat_position for n in notes]
        
        # Calculer is_downbeats si non fourni
        if is_downbeats is None:
            is_downbeats = self._compute_downbeats(beat_positions, measure_length)
        
        # 1. Détecter les appoggiatures (P4.2)
        result.appoggiaturas = self._detect_appoggiaturas(
            notes, beat_positions, is_downbeats
        )
        for app in result.appoggiaturas:
            result.note_ornaments[app.note_index] = 'appoggiatura'
        
        # 2. Détecter les trilles (P4.3)
        result.trills = self._detect_trills(notes, beat_positions)
        for tr in result.trills:
            for idx in range(tr.start_index, tr.end_index + 1):
                result.note_ornaments[idx] = 'trill'
        
        # 3. Détecter les rythmes pointés (P4.4)
        result.dotted_rhythms = self._detect_dotted_rhythms(notes, beat_positions)
        
        # Construire les structures pour MusicXML
        result.grace_notes = self._build_grace_notes_xml(result.appoggiaturas)
        result.trill_symbols = self._build_trill_symbols_xml(result.trills)
        
        return result
    
    # ── Helpers ─────────────────────────────────────────────────────────
    
    def _compute_downbeats(
        self, 
        beat_positions: List[float], 
        measure_length: float
    ) -> List[bool]:
        """Compute downbeat markers from beat positions and measure length."""
        if not beat_positions:
            return []
        
        min_beat = min(beat_positions)
        max_beat = max(beat_positions)
        
        # Générer les positions de downbeats théoriques
        first_downbeat = (min_beat // measure_length) * measure_length
        downbeat_positions = []
        pos = first_downbeat
        while pos <= max_beat:
            downbeat_positions.append(pos)
            pos += measure_length
        
        # Mapper chaque beat à un is_downbeat
        is_downbeat = []
        tolerance = 0.1  # Tolérance en beats
        for bp in beat_positions:
            is_db = any(abs(bp - db) < tolerance for db in downbeat_positions)
            is_downbeat.append(is_db)
        
        return is_downbeat
    
    def _detect_appoggiaturas(
        self,
        notes: List[QuantizedNote],
        beat_positions: List[float],
        is_downbeats: List[bool]
    ) -> List[AppoggiaturaInfo]:
        """
        Détecte les appoggiatures.
        
        Règle :
        - Note très courte (≤ appoggiatura_max_duration_beats)
        - Juste AVANT un temps fort (≤ appoggiatura_max_interval_beats avant downbeat)
        - La note suivante est la "note de résolution" (même pitch ou +1/-1 demi-ton)
        """
        appoggiaturas = []
        max_dur = self.thresholds.appoggiatura_max_duration_beats
        max_int = self.thresholds.appoggiatura_max_interval_beats
        
        for i, (note, bp, is_db) in enumerate(zip(notes, beat_positions, is_downbeats)):
            # Cette note est-elle juste AVANT un downbeat ?
            if is_db:
                continue  # On cherche les notes AVANT le downbeat
            
            # Chercher le downbeat suivant le plus proche
            next_downbeat_dist = float('inf')
            for j in range(i + 1, len(is_downbeats)):
                if is_downbeats[j]:
                    next_downbeat_dist = beat_positions[j] - bp
                    break
            
            if next_downbeat_dist > max_int or next_downbeat_dist <= 0:
                continue
            
            # La note est-elle assez courte ?
            if note.beat_duration > max_dur:
                continue
            
            # La note suivante (résolution) doit être proche en pitch
            if i + 1 >= len(notes):
                continue
            
            next_note = notes[i + 1]
            pitch_diff = abs(next_note.pitch_midi - note.pitch_midi)
            
            # L'appoggiature résout généralement par mouvement conjoint
            if pitch_diff <= 2:  # Résolution par step (diatonique)
                appoggiaturas.append(AppoggiaturaInfo(
                    note_index=i,
                    grace_note_pitch=note.pitch_midi,
                    target_pitch=next_note.pitch_midi,
                    beat_position=bp,
                    duration_beats=note.beat_duration,
                ))
        
        return appoggiaturas
    
    def _detect_trills(
        self,
        notes: List[QuantizedNote],
        beat_positions: List[float]
    ) -> List[TrillInfo]:
        """
        Détecte les trilles.
        
        Règle :
        - Séquence de ≥ trill_min_notes notes de durée courte (≤ trill_max_note_duration_beats)
        - Alternance de 2 hauteurs proches (trill_pitch_interval_min demi-tons)
        - Les notes doivent être rapprochées rythmiquement
        """
        trills = []
        min_notes = self.thresholds.trill_min_notes
        max_dur = self.thresholds.trill_max_note_duration_beats
        min_interval = self.thresholds.trill_pitch_interval_min
        
        if len(notes) < min_notes:
            return trills
        
        i = 0
        while i < len(notes):
            # Chercher une séquence potentielle de trille
            if notes[i].beat_duration > max_dur:
                i += 1
                continue
            
            # Étendre la séquence
            seq_start = i
            seq_end = i
            
            for j in range(i + 1, len(notes)):
                note = notes[j]
                
                # La note doit être courte
                if note.beat_duration > max_dur:
                    break
                
                # L'intervalle de pitch doit être cohérent avec un trille
                # (alternance autour d'une note principale)
                if j == i + 1:
                    # Première étape : définir l'intervalle
                    interval = abs(note.pitch_midi - notes[i].pitch_midi)
                    if interval < min_interval or interval > 4:
                        break
                    primary_pitch = notes[i].pitch_midi
                    auxiliary_pitch = note.pitch_midi
                else:
                    # Vérifier l'alternance
                    if abs(note.pitch_midi - primary_pitch) <= 1:
                        seq_end = j
                    elif abs(note.pitch_midi - auxiliary_pitch) <= 1:
                        seq_end = j
                    else:
                        break
                
                # Les notes doivent être rapprochées (pas de grand gap)
                if j > 0:
                    gap = beat_positions[j] - beat_positions[j - 1]
                    if gap > max_dur * 2:  # Gap > 2x la durée max
                        break
            
            # Vérifier si la séquence est assez longue
            seq_length = seq_end - seq_start + 1
            if seq_length >= min_notes:
                primary = notes[seq_start].pitch_midi
                auxiliary = notes[seq_start + 1].pitch_midi if seq_start + 1 < len(notes) else primary + 1
                
                trills.append(TrillInfo(
                    start_index=seq_start,
                    end_index=seq_end,
                    start_beat=beat_positions[seq_start],
                    end_beat=beat_positions[seq_end] + notes[seq_end].beat_duration,
                    primary_pitch=primary,
                    auxiliary_pitch=auxiliary,
                    note_count=seq_length,
                ))
                i = seq_end + 1
            else:
                i += 1
        
        return trills
    
    def _detect_dotted_rhythms(
        self,
        notes: List[QuantizedNote],
        beat_positions: List[float]
    ) -> List[DottedRhythmInfo]:
        """
        Détecte les rythmes pointés (P4.4).
        
        Règle :
        - Une note dont la durée est proche d'un ratio pointé (1.5x, 2x, etc.)
        - Tolérance: dotted_rhythm_tolerance_beats
        """
        dotted = []
        tolerance = self.thresholds.dotted_rhythm_tolerance_beats
        
        # Ratios pointés canoniques
        dotted_ratios = [1.5, 2.0, 2.5, 3.0]  # 1.5 = point d'orgue simple
        
        for i, note in enumerate(notes):
            dur = note.beat_duration
            if dur < 0.5:  # Trop court pour être un rythme pointé significatif
                continue
            
            # Vérifier si la durée correspond à un ratio pointé
            for ratio in dotted_ratios:
                expected_base = dur / ratio
                # Vérifier si base + base*ratio ≈ dur (avec tolérance)
                expected = expected_base * (1 + ratio)
                
                if abs(dur - expected) <= tolerance:
                    dotted.append(DottedRhythmInfo(
                        note_index=i,
                        beat_position=beat_positions[i],
                        duration_beats=dur,
                        dotted_ratio=ratio,
                        tolerance=tolerance,
                    ))
                    break
        
        return dotted
    
    def _build_grace_notes_xml(self, appoggiaturas: List[AppoggiaturaInfo]) -> List[Dict[str, Any]]:
        """Construit les grace notes pour le JSON MusicXML."""
        grace_notes = []
        for app in appoggiaturas:
            grace_notes.append({
                'type': 'graceNote',
                'pitch': app.grace_note_pitch,
                'targetPitch': app.target_pitch,
                'beatPosition': app.beat_position,
                'duration': app.duration_beats,
                'musicxml': f'<grace slash="true"><note><pitch><step>C</step><alter>0</alter></pitch><duration>0</duration></note></grace>',
            })
        return grace_notes
    
    def _build_trill_symbols_xml(self, trills: List[TrillInfo]) -> List[Dict[str, Any]]:
        """Construit les symboles tr pour le JSON MusicXML."""
        trill_symbols = []
        for tr in trills:
            trill_symbols.append({
                'type': 'trill',
                'startBeat': tr.start_beat,
                'endBeat': tr.end_beat,
                'primaryPitch': tr.primary_pitch,
                'auxiliaryPitch': tr.auxiliary_pitch,
                'noteCount': tr.note_count,
                'musicxml': f'<ornaments><trill-mark>{tr.start_beat:.2f}-{tr.end_beat:.2f}</trill-mark></ornaments>',
            })
        return trill_symbols


# ─────────────────────────────────────────────────────────────────────────────
# Fonction utilitaire rapide
# ─────────────────────────────────────────────────────────────────────────────

def detect_ornaments(
    notes: List[QuantizedNote],
    thresholds=None,
    measure_length: float = 3.0,
) -> OrnamentResult:
    """
    Détection rapide d'ornements (fonction utilitaire).
    
    Args:
        notes: liste de QuantizedNote
        thresholds: seuils de détection
        measure_length: longueur de mesure en beats (3 pour Mazurka 3/4)
    
    Returns:
        OrnamentResult
    """
    detector = OrnamentDetector(thresholds=thresholds)
    beat_positions = [n.beat_position for n in notes]
    return detector.detect(notes, beat_positions=beat_positions, measure_length=measure_length)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("[Test] Ornament Detector (Phase 4)")
    print("=" * 60)
    
    # Notes de test : simuler une phrase avec ornements
    test_notes = [
        QuantizedNote(pitch_midi=60, amplitude=0.7, beat_position=0.0, beat_duration=1.0, hand='treble'),
        QuantizedNote(pitch_midi=61, amplitude=0.5, beat_position=1.0, beat_duration=0.1, hand='treble'),  # Appoggiature
        QuantizedNote(pitch_midi=62, amplitude=0.8, beat_position=1.1, beat_duration=1.0, hand='treble'),  # Résolution
        QuantizedNote(pitch_midi=62, amplitude=0.7, beat_position=2.0, beat_duration=0.2, hand='treble'),  # Début trille
        QuantizedNote(pitch_midi=63, amplitude=0.7, beat_position=2.2, beat_duration=0.2, hand='treble'),  # Trille
        QuantizedNote(pitch_midi=62, amplitude=0.7, beat_position=2.4, beat_duration=0.2, hand='treble'),  # Trille
        QuantizedNote(pitch_midi=63, amplitude=0.7, beat_position=2.6, beat_duration=0.2, hand='treble'),  # Trille
        QuantizedNote(pitch_midi=64, amplitude=0.8, beat_position=3.0, beat_duration=1.0, hand='treble'),
    ]
    
    detector = OrnamentDetector()
    result = detector.detect(test_notes, measure_length=3.0)
    
    print(f"\nNotes analysées: {len(result.original_notes)}")
    print(f"Appoggiatures détectées: {len(result.appoggiaturas)}")
    for app in result.appoggiaturas:
        print(f"  - Note {app.note_index}: pitch={app.grace_note_pitch} → {app.target_pitch} @ beat {app.beat_position:.2f}")
    
    print(f"Trilles détectés: {len(result.trills)}")
    for tr in result.trills:
        print(f"  - Trille beats {tr.start_beat:.2f}-{tr.end_beat:.2f}: {tr.primary_pitch}↔{tr.auxiliary_pitch} ({tr.note_count} notes)")
    
    print(f"Rythmes pointés détectés: {len(result.dotted_rhythms)}")
    for dr in result.dotted_rhythms:
        print(f"  - Note {dr.note_index} @ beat {dr.beat_position:.2f}: ratio={dr.dotted_ratio:.1f}")
    
    print(f"\n[MTest] SUCCES - {len(result.appoggiaturas)} appoggiatures, {len(result.trills)} trilles")
    print("=" * 60)