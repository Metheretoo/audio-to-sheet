"""
harmonic_analyzer.py — Analyse harmonique via music21 (Krumhansl-Schmuckler)
Version: 4.0

Responsabilités :
- Détecter la tonalité globale et les changements locaux (avec filtre de stabilité)
- Analyser chaque Slice comme accord (chiffrage romain, qualité, basse)
- Détecter les cadences (frontières de phrase)
- Construire le HarmonicContext complet
"""

from dataclasses import dataclass, field
from typing import List, Optional

# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ChordAnalysis:
    root: str                      # Ex: "C", "F#", "Bb"
    quality: str                   # Ex: "major", "minor", "dominant-seventh"
    inversion: int                 # 0=fondamentale, 1=premier renversement
    roman_numeral: str             # Ex: "I", "V7", "ii6"
    is_known_chord: bool           # False si music21 ne reconnaît pas
    bass_note: int                 # MIDI pitch de la basse
    confidence: float              # 0.0 à 1.0
    chord_symbol: str = ""         # Ex: "Cm7" — pour le preset Jazz


@dataclass
class HarmonicContext:
    global_key: str                # Ex: "F major"
    local_keys: List[tuple]        # [(beat_start, key_name), ...]
    chord_map: dict                # {beat_position: ChordAnalysis}
    phrase_boundaries: List[float] # positions en beats (cadences V->I)
    stable_keys: List[tuple] = field(default_factory=list)  # après filtrage


# ── Analyse harmonique ─────────────────────────────────────────────────────────

def build_harmonic_context(slices: list, window_beats: float = 16.0) -> HarmonicContext:
    """
    Construit le HarmonicContext complet depuis une liste de Slices.
    
    Étapes :
      1. Détection tonalité par fenêtre glissante (Krumhansl-Schmuckler)
      2. Filtrage de stabilité (évite les armures parasites)
      3. Analyse accord par accord (music21 roman numeral)
      4. Détection frontières de phrase (cadences V→I)
    """
    from piano_roll import Slice as SliceType  # import local pour éviter circulaire

    if not slices:
        return HarmonicContext(
            global_key="C major",
            local_keys=[(0.0, "C major")],
            chord_map={},
            phrase_boundaries=[],
            stable_keys=[(0.0, "C major")]
        )

    local_keys  = detect_keys(slices, window_beats=window_beats)
    stable_keys = filter_stable_key_changes(local_keys, min_confirmations=2)
    chord_map   = {}

    for sl in slices:
        # Trouver la tonalité locale applicable à ce Slice
        current_key = stable_keys[0][1] if stable_keys else "C major"
        for beat_start, key_name in stable_keys:
            if sl.beat_position >= beat_start:
                current_key = key_name

        chord_map[sl.beat_position] = analyze_chord(sl, current_key)

    return HarmonicContext(
        global_key=stable_keys[0][1] if stable_keys else "C major",
        local_keys=local_keys,
        chord_map=chord_map,
        phrase_boundaries=_detect_phrase_boundaries(slices, chord_map),
        stable_keys=stable_keys
    )


def detect_keys(slices: list, window_beats: float = 16.0) -> List[tuple]:
    """
    Détecte la tonalité par fenêtre glissante (Krumhansl-Schmuckler via music21).
    Retourne [(beat_start, key_name), ...]
    """
    try:
        from music21 import stream, note, chord as m21chord
    except ImportError:
        return [(0.0, "C major")]

    if not slices:
        return [(0.0, "C major")]

    max_beat = slices[-1].beat_position
    results  = []
    pos      = 0.0

    while pos <= max_beat:
        window_slices = [s for s in slices
                         if pos <= s.beat_position < pos + window_beats]
        if len(window_slices) < 4:
            pos += window_beats / 2
            continue

        # Construire un stream music21 temporaire pour cette fenêtre
        s = stream.Stream()
        for sl in window_slices:
            if len(sl.midi_pitches) == 1:
                s.append(note.Note(sl.midi_pitches[0]))
            elif len(sl.midi_pitches) > 1:
                s.append(m21chord.Chord(sl.midi_pitches))

        try:
            detected_key = s.analyze('key')  # Krumhansl-Schmuckler
            results.append((pos, str(detected_key)))
        except Exception:
            pass

        pos += window_beats / 2  # Chevauchement de 50%

    if not results:
        results = [(0.0, "C major")]

    return results


def filter_stable_key_changes(local_keys: List[tuple], min_confirmations: int = 2) -> List[tuple]:
    """
    Filtre les changements de tonalité instables.
    Un changement n'est validé que s'il est confirmé sur N fenêtres consécutives.
    
    Évite les fausses armures dues à des chromatismes passagers.
    """
    if not local_keys:
        return []

    stable   = [local_keys[0]]
    run_key  = local_keys[0][1]
    count    = 1

    for beat_pos, key_name in local_keys[1:]:
        if key_name == run_key:
            count += 1
        else:
            count   = 1
            run_key = key_name

        if count >= min_confirmations and key_name != stable[-1][1]:
            stable.append((beat_pos, key_name))

    return stable


def analyze_chord(sl, current_key: str) -> ChordAnalysis:
    """
    Analyse un seul Slice avec music21 pour identifier l'accord et son rôle.
    Retourne un ChordAnalysis complet avec chiffrage romain et symbole Jazz.
    """
    try:
        from music21 import chord as m21chord, roman, key as m21key
    except ImportError:
        return ChordAnalysis(root='?', quality='unknown', inversion=0,
                             roman_numeral='?', is_known_chord=False,
                             bass_note=min(sl.midi_pitches) if sl.midi_pitches else 0,
                             confidence=0.0, chord_symbol='?')

    if not sl.midi_pitches:
        return ChordAnalysis(root='?', quality='rest', inversion=0,
                             roman_numeral='?', is_known_chord=False,
                             bass_note=0, confidence=0.0, chord_symbol='')

    # Garde-fou anti-bruit (v4.2) : une tranche à moins de 3 hauteurs de classe
    # distinctes (une seule note, ou un simple intervalle) n'est PAS un vrai
    # accord — ne pas produire de faux symbole (juste le nom de la basse), ce
    # qui serait trompeur maintenant que l'affichage des accords est activé
    # par défaut sur tous les presets.
    distinct_pitch_classes = {p % 12 for p in sl.midi_pitches}
    if len(distinct_pitch_classes) < 3:
        return ChordAnalysis(root='?', quality='incomplete', inversion=0,
                             roman_numeral='?', is_known_chord=False,
                             bass_note=min(sl.midi_pitches), confidence=0.2,
                             chord_symbol='')

    # 1. Construire l'accord music21. Si ça échoue, il n'y a vraiment rien à
    #    afficher (notes invalides / silence).
    try:
        c = m21chord.Chord(sl.midi_pitches)
    except Exception:
        return ChordAnalysis(root='?', quality='unknown', inversion=0,
                             roman_numeral='?', is_known_chord=False,
                             bass_note=min(sl.midi_pitches) if sl.midi_pitches else 0,
                             confidence=0.0, chord_symbol='?')

    # 2. Symbole Jazz (ex: "Cm7", "F", "G7") — c'est CE symbole qui est affiché
    #    au-dessus de la portée. Il ne dépend pas de la tonalité et doit donc
    #    rester disponible même si l'analyse tonale (étape 3) échoue.
    jazz_symbol = _build_jazz_symbol(c)
    is_triad_or_seventh = False
    try:
        is_triad_or_seventh = bool(c.isTriad() or c.isSeventh())
    except Exception:
        pass

    # 3. Chiffrage romain (fonction tonale). Sur de l'audio réel, beaucoup
    #    d'accords contiennent des notes de passage / appogiatures qui ne sont
    #    pas de vrais accords diatoniques : romanNumeralFromChord() échoue alors
    #    souvent. C'est normal et ne doit PAS supprimer le symbole Jazz déjà
    #    calculé (bug corrigé v4.1 : auparavant, cet échec mettait
    #    is_known_chord=False, ce qui faisait disparaître le symbole d'accord
    #    du rendu final, même en preset Jazz).
    roman_numeral = '?'
    try:
        key_parts = current_key.split()
        key_name  = key_parts[0] if key_parts else "C"
        mode_name = key_parts[1] if len(key_parts) > 1 else "major"
        k = m21key.Key(key_name, mode_name)
        rn = roman.romanNumeralFromChord(c, k)
        roman_numeral = rn.figure
    except Exception:
        roman_numeral = '?'

    if jazz_symbol:
        confidence = 0.9 if is_triad_or_seventh else 0.6
    else:
        confidence = 0.3

    return ChordAnalysis(
        root=c.root().name if c.pitches else '?',
        quality=c.quality,
        inversion=c.inversion() if is_triad_or_seventh else 0,
        roman_numeral=roman_numeral,
        is_known_chord=bool(jazz_symbol),
        bass_note=min(sl.midi_pitches),
        confidence=confidence,
        chord_symbol=jazz_symbol
    )


def _build_jazz_symbol(chord) -> str:
    """
    Construit un symbole d'accord au format Jazz depuis un objet music21.Chord.
    Exemples : "Cm7", "F", "G7", "Bbmaj7", "Dm7b5"
    """
    try:
        # BUG CORRIGÉ (v4.1) : str(chord.root()) inclut l'octave music21
        # (ex: "C4"), produisant des symboles invalides comme "C4m7" au lieu
        # de "Cm7". Il faut utiliser .name (classe de hauteur, sans octave).
        root = chord.root().name
        root = root.replace('-', 'b')  # music21 utilise '-' pour bémol
        triad_quality = chord.quality  # 'major' | 'minor' | 'diminished' | 'augmented' | 'other'

        # BUG CORRIGÉ (v4.1) : chord.quality (music21) ne renvoie QUE la
        # qualité de la triade sous-jacente — jamais 'dominant-seventh',
        # 'minor-seventh', etc. (ces valeurs du suffix_map d'origine ne
        # matchaient donc JAMAIS). Résultat : un G7 s'affichait "G", un Cm7
        # s'affichait "Cm" — la 7ème disparaissait systématiquement. On
        # détecte maintenant la présence d'une 7ème explicitement via
        # chord.seventh et son intervalle (en demi-tons) par rapport à la
        # fondamentale.
        seventh_semitones = None
        try:
            seventh_pitch = chord.seventh
            if seventh_pitch is not None:
                seventh_semitones = (seventh_pitch.midi - chord.root().midi) % 12
        except Exception:
            seventh_semitones = None

        if triad_quality == 'diminished':
            if seventh_semitones == 9:
                suffix = 'dim7'          # accord de septième diminuée
            elif seventh_semitones == 10:
                suffix = 'm7b5'          # demi-diminué
            else:
                suffix = 'dim'
        elif triad_quality == 'augmented':
            suffix = 'aug7' if seventh_semitones == 10 else 'aug'
        elif triad_quality == 'minor':
            if seventh_semitones == 11:
                suffix = 'mMaj7'
            elif seventh_semitones == 10:
                suffix = 'm7'
            else:
                suffix = 'm'
        elif triad_quality == 'major':
            if seventh_semitones == 11:
                suffix = 'maj7'
            elif seventh_semitones == 10:
                suffix = '7'
            else:
                suffix = ''
        else:
            suffix = ''

        # Inversion en basse : "Cm7/Eb"
        bass_pitch = chord.bass()
        root_pitch = chord.root()
        inversion_str = ''
        if bass_pitch and root_pitch and bass_pitch.name != root_pitch.name:
            bass_name = str(bass_pitch.name).replace('-', 'b')
            inversion_str = f"/{bass_name}"

        return f"{root}{suffix}{inversion_str}"
    except Exception:
        return ''


def _detect_phrase_boundaries(slices: list, chord_map: dict) -> List[float]:
    """
    Détecte les frontières de phrase via les cadences (V→I, V7→I).
    Ces positions peuvent être utilisées par score_builder pour placer
    des respirations, liaisons ou changements dynamiques.
    """
    boundaries = []
    prev_rn    = None

    for sl in slices:
        ca = chord_map.get(sl.beat_position)
        if ca and prev_rn in ('V', 'V7') and ca.roman_numeral in ('I', 'i'):
            boundaries.append(sl.beat_position)
        if ca:
            prev_rn = ca.roman_numeral

    return boundaries


def detect_ornaments(slices: list, beat_duration_sec: float) -> List[dict]:
    """
    Détecte les ornements potentiels (grace notes, trilles) dans les Slices.
    
    Args:
        slices: liste de Slice
        beat_duration_sec: durée d'un beat en secondes (60/BPM)
    
    Returns:
        Liste de {beat_position, pitch, type: 'grace_note'|'trill'}
    """
    ornaments = []
    min_grace_beats = 0.15 / max(beat_duration_sec, 0.01)  # < 150ms

    for i, sl in enumerate(slices):
        # Grace note candidate : note isolée ultra-courte avant un accord
        if sl.duration_beats < min_grace_beats and len(sl.midi_pitches) == 1:
            if i + 1 < len(slices) and len(slices[i + 1].midi_pitches) > 1:
                ornaments.append({
                    'beat_position': sl.beat_position,
                    'pitch': sl.midi_pitches[0],
                    'type': 'grace_note'
                })

        # Trille : alternance rapide de 2 notes proches
        if (i + 1 < len(slices)
                and len(sl.midi_pitches) == 1
                and len(slices[i + 1].midi_pitches) == 1):
            interval = abs(sl.midi_pitches[0] - slices[i + 1].midi_pitches[0])
            both_short = (sl.duration_beats < min_grace_beats * 2
                          and slices[i + 1].duration_beats < min_grace_beats * 2)
            if interval in (1, 2) and both_short:
                ornaments.append({
                    'beat_position': sl.beat_position,
                    'pitch': sl.midi_pitches[0],
                    'type': 'trill'
                })

    return ornaments
