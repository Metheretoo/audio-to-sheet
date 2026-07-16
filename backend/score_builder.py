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
import re
import numpy as np
from typing import List, Tuple, Dict, Any
from quantizer import QuantizedNote, beats_to_duration, duration_beats
from voice_engine import VoiceSplit
from tempo_map import TempoMap

# Format d'armure valide pour VexFlow : lettre A-G, altération simple/double
# optionnelle (# ou b), suffixe 'm' optionnel pour le mode mineur.
_VALID_VEXFLOW_KEY_RE = re.compile(r'^[A-G](#{1,2}|b{1,2})?m?$')


# ── Constantes ────────────────────────────────────────────────────────────────

PITCH_NAMES_SHARP = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']
PITCH_NAMES_FLAT  = ['c', 'db', 'd', 'eb', 'e', 'f', 'gb', 'g', 'ab', 'a', 'bb', 'b']
FLAT_KEY_SIGS     = {'F', 'Bb', 'Eb', 'Ab', 'Db', 'Gb', 'Cb'}
REST_DURS         = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.167, 0.125]

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
    harmonic_ctx=None,        # [V4] HarmonicContext depuis harmonic_analyzer
    pedals: list = None,      # [V4] liste de (onset_sec, offset_sec)
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
        - detect_dynamics : bool (défaut True) — détecter les nuances

    Retourne un dict compatible JSON / VexFlow.
    """
    if options is None:
        options = {}

    # 1. Tonalité
    #
    # BUGS CORRIGÉS (v4.1) :
    #  - Quand harmonic_ctx était disponible, l'armure auto-détectée écrasait
    #    TOUJOURS l'armure manuelle choisie par l'utilisateur (le paramètre
    #    key_sig et options['detect_key'] étaient purement et simplement ignorés).
    #  - Les tonalités mineures renvoyées par music21 (ex: "a minor") gardaient
    #    leur tonique en minuscule ('a'), ce qui faisait planter VexFlow
    #    ("Bad key signature spec: 'a'"). Voir key_name_to_vexflow().
    #
    # Priorité désormais : override manuel explicite > harmonic_ctx > détecteur
    # interne (Krumhansl-Schmuckler) > 'C' par défaut.
    detect_key = options.get('detect_key', True)
    manual_key_sig = normalize_key_signature(key_sig) if key_sig else 'C'

    if not detect_key and key_sig:
        key_sig = manual_key_sig
    elif harmonic_ctx is not None and harmonic_ctx.stable_keys:
        # Prendre la tonalité de la 1ère entrée stable pour l'armure initiale
        first_key_name = harmonic_ctx.stable_keys[0][1]  # ex: "F major" / "a minor"
        key_sig = key_name_to_vexflow(first_key_name)
    elif detect_key:
        all_notes = voices.treble + voices.bass
        key_sig = detect_key_signature([
            (0, 1, n.pitch_midi, n.amplitude) for n in all_notes
        ])
    else:
        key_sig = manual_key_sig
    key_sig = normalize_key_signature(key_sig)

    # Filet de sécurité final (v4.2) : quelle que soit la branche empruntée
    # ci-dessus, garantir que key_sig est bien un format VexFlow valide
    # (lettre A-G, altération optionnelle, 'm' optionnel pour le mineur)
    # avant de le renvoyer au frontend. Si une chaîne music21 brute a fuité
    # d'une manière ou d'une autre (ex: "G major"), on tente une dernière
    # conversion ; en dernier recours, on retombe sur 'C' plutôt que de
    # renvoyer une valeur qui ferait planter VexFlow côté client.
    if not _VALID_VEXFLOW_KEY_RE.match(key_sig):
        key_sig = key_name_to_vexflow(key_sig) if key_sig else 'C'
        if not _VALID_VEXFLOW_KEY_RE.match(key_sig):
            key_sig = 'C'

    # 2. Mesure et tempo
    #
    # BUG CORRIGÉ (v4.1) : la mesure manuelle choisie par l'utilisateur (ex: 3/4
    # pour une Mazurka) était systématiquement ignorée : la condition comparait
    # une liste JSON ([4, 4]) à un tuple Python ((4, 4)), ce qui est toujours
    # False en Python, et la valeur d'appel réelle (pipeline._build_score) ne
    # transmettait de toute façon jamais l'option 'time_sig' à build_score.
    # Résultat : seule la mesure auto-détectée par TempoMap était utilisée,
    # quel que soit le choix affiché dans l'UI.
    manual_time_sig = options.get('time_sig')
    if manual_time_sig:
        time_sig = list(manual_time_sig)
    elif options.get('detect_meter', options.get('detect_tempo', True)):
        time_sig = list(tempo_map.estimated_meter)
    else:
        time_sig = [4, 4]
    ts_num, ts_den = time_sig[0], time_sig[1]
    beats_per_measure = ts_num * (4.0 / ts_den)
    global_bpm = int(round(options.get('display_bpm', tempo_map.global_bpm)))

    # 3. Nombre de mesures nécessaires
    all_notes = voices.treble + voices.bass
    if not all_notes:
        return _empty_score(global_bpm, ts_num, ts_den, key_sig)

    total_beats = max(n.beat_position + n.beat_duration for n in all_notes)
    num_measures = max(1, math.ceil(total_beats / beats_per_measure))

    # 4. Détection des nuances (dynamique) si activée
    dynamics = None
    if options.get('detect_dynamics', True):
        dynamics = detect_dynamics(voices)

    # 5. Construire les mesures
    measures = []
    for m_idx in range(num_measures):
        m_start = m_idx * beats_per_measure
        m_end   = (m_idx + 1) * beats_per_measure

        # ── Sélection + isolation stricte des notes de cette mesure ────────
        # Une note appartient à la mesure si son DÉBUT est dans [m_start, m_end).
        # Si sa durée déborde sur la mesure suivante, on la TRONQUE (copie locale)
        # afin que chaque mesure soit ÉTANCHE : aucune modification d'une mesure
        # ne peut impacter une autre mesure.
        def _clip_to_measure(note, m_s, m_e):
            """Retourne une copie de la note avec beat_duration tronquée à la mesure."""
            from copy import copy as _copy
            clipped = _copy(note)
            max_dur = m_e - note.beat_position
            if clipped.beat_duration > max_dur + 1e-6:
                clipped.beat_duration = max(0.125, max_dur)  # min = triple croche
            return clipped

        treble_in_measure = [
            _clip_to_measure(n, m_start, m_end)
            for n in voices.treble
            if n.beat_position >= m_start and n.beat_position < m_end
        ]
        bass_in_measure = [
            _clip_to_measure(n, m_start, m_end)
            for n in voices.bass
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

    result = {
        'tempo':         global_bpm,
        'timeSignature': [ts_num, ts_den],
        'keySignature':  key_sig,
        'totalMeasures': num_measures,
        'measures':      measures,
    }
    
    # Ajouter les dynamiques si détectées
    if dynamics:
        result['dynamics'] = dynamics

    # [V4] Changements d'armure dynamiques (issues de harmonic_ctx)
    if harmonic_ctx is not None:
        result['keyChanges'] = _build_key_changes(
            harmonic_ctx.stable_keys, beats_per_measure
        )
        # Symboles d'accords (tous presets, affichage piloté côté UI)
        if options.get('write_chord_symbols', False):
            symbols = _build_chord_symbols(harmonic_ctx.chord_map, beats_per_measure)
            if symbols:
                result['chordSymbols'] = symbols

    elif options.get('write_chord_symbols', False):
        # BUG CORRIGÉ (v4.2) : si harmonic_ctx est None (analyse harmonique
        # échouée silencieusement en production), toute la section chordSymbols
        # était sautée — les accords n'apparaissaient jamais, même quand la
        # case était cochée. Fallback : analyser directement les tranches de
        # notes issues de la partition déjà construite.
        try:
            from backend.piano_roll import group_into_slices, fuse_arpeggios
            from backend.harmonic_analyzer import build_harmonic_context
            slices = fuse_arpeggios(group_into_slices(all_notes))
            if slices:
                fallback_ctx = build_harmonic_context(slices)
                symbols = _build_chord_symbols(fallback_ctx.chord_map, beats_per_measure)
                if symbols:
                    result['chordSymbols'] = symbols
        except Exception as _e:
            pass  # si l'analyse échoue ici aussi, on n'affiche rien (pas de crash)

    # [V4] Pédale forte
    if pedals:
        result['pedalMarkings'] = _build_pedal_markers(pedals, tempo_map, all_notes)
    
    return result


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

    Algorithme « lecture naturelle » :
    1. Si pas de notes → retourner [silence pleine mesure]
    2. Grouper les notes simultanées en accords (beat_position identique)
    3. Pour chaque accord :
       - La durée est l'IOI (distance jusqu'à la prochaine note) sauf si
         le sustain mesuré est clairement staccato (< 40 % de l'IOI ET < 0.5 beat).
       - On évite ainsi les silences parasites entre deux notes liées/tenues.
    4. Combler les silences réels (gaps entre notes non liées) en fin de mesure.

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
    visual_cursor = 0.0  # Temps réellement accumulé dans VexFlow

    for i, pos in enumerate(sorted_positions):
        # ── Silence avant cet accord ──────────────────────────────────────────
        gap = pos - visual_cursor
        if gap > 0.01:
            rests = _split_rests(gap, m_start + visual_cursor, hand)
            voice.extend(rests)
            for r in rests:
                visual_cursor = round(visual_cursor + r['duration'], 9)

        chord_notes = chords[pos]
        primary = max(chord_notes, key=lambda n: n.amplitude)

        # ── IOI = espace disponible jusqu'à la prochaine note ─────────────────
        if i < len(sorted_positions) - 1:
            ioi = sorted_positions[i + 1] - pos
        else:
            ioi = beats_per_measure - pos
        ioi = max(ioi, 0.125)   # au moins une double-croche

        raw_dur = primary.beat_duration
        is_staccato = (raw_dur < 0.4 * ioi) and (raw_dur < 0.5)
        
        is_legato = False
        if i < len(sorted_positions) - 1:
            next_pos = sorted_positions[i + 1]
            if pos + raw_dur > next_pos:
                is_legato = True
        
        if is_staccato:
            target = raw_dur
        elif is_legato:
            target = raw_dur
        else:
            target = ioi

        # Ne pas déborder la mesure (en se basant sur le curseur visuel réel !)
        space_in_measure = beats_per_measure - visual_cursor
        target = min(target, space_in_measure)
        target = max(target, 0.125)  # au minimum une triple croche

        dur_str, dots = beats_to_duration(target)
        final_dur     = duration_beats(dur_str, dots)

        # ── Sécurité anti-chevauchement (arrondi vers le bas) ─────────────────
        if i < len(sorted_positions) - 1:
            max_dur = sorted_positions[i + 1] - visual_cursor
            if final_dur > max_dur + 1e-4:
                dur_str, dots = beats_to_duration(max_dur, floor=True)
                final_dur = duration_beats(dur_str, dots)

        if final_dur > space_in_measure + 1e-6:
            dur_str, dots = beats_to_duration(space_in_measure, floor=True)
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

        visual_cursor = round(visual_cursor + final_dur, 9)

    # ── Silence final ─────────────────────────────────────────────────────────
    remaining = round(beats_per_measure - visual_cursor, 6)
    if remaining > 0.01:
        rests = _split_rests(remaining, m_start + visual_cursor, hand)
        voice.extend(rests)
        for r in rests:
            visual_cursor = round(visual_cursor + r['duration'], 9)

    return voice


# ── Utilitaires de construction ───────────────────────────────────────────────

def _split_rests(total_beats: float, start_beat: float, hand: str) -> List[Dict]:
    """
    Découpe un silence en durées standard (greedy : plus grande valeur possible en premier).

    Amélioration lisibilité :
    - On ignore les restes < 1/32 de beat (artefacts de calcul flottant)
    - On préfère consolider : ex. deux croches → une noire quand possible
    """
    rests = []
    remaining = round(total_beats, 6)
    pos = start_beat

    while remaining > 0.24:   # autoriser les silences jusqu'à la double-croche (0.25)
        chosen = next((d for d in REST_DURS if d <= remaining + 1e-4), None)
        if chosen is None:
            break
        dur_str, dots = beats_to_duration(chosen)
        rest_key = REST_POSITIONS[hand].get(dur_str, REST_POSITIONS[hand]['default'])
        rests.append(_make_rest(rest_key, dur_str, dots, pos, chosen, hand))
        remaining = round(remaining - chosen, 6)
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


# ── Conversions MIDI ↔ VexFlow ───────────────────────────────────────────────

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


KEY_MAP_NORMALIZED = {
    'A#': 'Bb',
    'D#': 'Eb',
    'G#': 'Ab',
    'C#': 'Db',
    'A#m': 'Bbm',
    'D#m': 'Ebm',
    'G#m': 'Abm',
}

def normalize_key_signature(key: str) -> str:
    return KEY_MAP_NORMALIZED.get(key, key)


def key_name_to_vexflow(key_name: str) -> str:
    """
    Convertit un nom de tonalite facon music21 (ex: 'F major', 'a minor', 'c# minor',
    'e- minor', 'B- major') en armure VexFlow valide (ex: 'F', 'Am', 'C#m', 'Ebm', 'Bb').

    BUGS CORRIGES (v4.1/v4.2) :
    - music21 utilise la CASSE de la tonique pour coder le mode (minuscule = mineur,
      ex. "a minor"), mais VexFlow exige que la lettre soit TOUJOURS en majuscule,
      avec un suffixe 'm' pour les tonalites mineures. Sans cette conversion, une
      armure mineure comme "a" provoquait un crash VexFlow :
      "BadKeySignature: Bad key signature spec: 'a'".
    - music21 note les bemols avec un tiret '-' (ex: "e- minor", "B- major"), jamais
      avec 'b'. Cette conversion manquait initialement, ce qui laissait passer des
      armures invalides comme "E-m" (au lieu de "Ebm") et faisait toujours planter
      VexFlow sur les tonalites mineures avec bemol.
    """
    if not key_name:
        return 'C'
    parts = key_name.split()
    tonic = parts[0] if parts else 'C'
    mode = parts[1].lower() if len(parts) > 1 else ('minor' if tonic[:1].islower() else 'major')
    # music21 : '-' = bémol → notation VexFlow attendue : 'b'
    tonic = tonic.replace('-', 'b')
    # La fondamentale doit toujours etre en majuscule pour VexFlow (ex: 'eb' -> 'Eb')
    tonic_cap = tonic[0].upper() + tonic[1:]
    key_sig = normalize_key_signature(tonic_cap)
    if mode.startswith('minor') and not key_sig.endswith('m'):
        key_sig = key_sig + 'm'
    return key_sig


def detect_dynamics(voices: VoiceSplit) -> Dict[str, Any]:
    """
    Détecte les nuances (dynamique) à partir des amplitudes des notes.
    
    Retourne un dict avec :
      - global_dynamic : nuance globale (pp, p, mp, mf, f, ff)
      - per_measure : liste de nuances par mesure
      - crescendo_diminuendo : liste de transitions (cresc. / dim.)
    """
    all_notes = voices.treble + voices.bass
    if not all_notes:
        return {'global_dynamic': 'mf', 'per_measure': [], 'crescendo_diminuendo': []}
    
    # Calculer l'amplitude moyenne globale
    amplitudes = [n.amplitude for n in all_notes if n.amplitude > 0]
    if not amplitudes:
        return {'global_dynamic': 'mf', 'per_measure': [], 'crescendo_diminuendo': []}
    
    avg_amp = sum(amplitudes) / len(amplitudes)
    max_amp = max(amplitudes)
    min_amp = min(amplitudes)
    
    # Déterminer la nuance globale
    if avg_amp > 0.85:
        global_dynamic = 'ff'
    elif avg_amp > 0.7:
        global_dynamic = 'f'
    elif avg_amp > 0.55:
        global_dynamic = 'mf'
    elif avg_amp > 0.4:
        global_dynamic = 'mp'
    elif avg_amp > 0.25:
        global_dynamic = 'p'
    else:
        global_dynamic = 'pp'
    
    # Détecter les changements de dynamique par mesure
    # (basé sur les variations d'amplitude entre mesures consécutives)
    per_measure = []
    crescendo_diminuendo = []
    
    # Regrouper les notes par mesure (approximation basée sur beat_position)
    measures_amp = {}
    for note in all_notes:
        measure_idx = int(note.beat_position // 4)  # Approximation pour 4/4
        if measure_idx not in measures_amp:
            measures_amp[measure_idx] = []
        measures_amp[measure_idx].append(note.amplitude)
    
    sorted_measures = sorted(measures_amp.keys())
    prev_avg = None
    
    for i, m_idx in enumerate(sorted_measures):
        amps = measures_amp[m_idx]
        m_avg = sum(amps) / len(amps) if amps else 0.5
        
        # Déterminer la nuance de la mesure
        if m_avg > 0.85:
            m_dyn = 'ff'
        elif m_avg > 0.7:
            m_dyn = 'f'
        elif m_avg > 0.55:
            m_dyn = 'mf'
        elif m_avg > 0.4:
            m_dyn = 'mp'
        elif m_avg > 0.25:
            m_dyn = 'p'
        else:
            m_dyn = 'pp'
        
        per_measure.append({
            'measure': m_idx,
            'dynamic': m_dyn,
            'avg_amplitude': round(m_avg, 3)
        })
        
        # Détecter crescendo/diminuendo
        if prev_avg is not None:
            diff = m_avg - prev_avg
            if diff > 0.15:
                crescendo_diminuendo.append({
                    'type': 'crescendo',
                    'from_measure': sorted_measures[i-1],
                    'to_measure': m_idx,
                    'amplitude_change': round(diff, 3)
                })
            elif diff < -0.15:
                crescendo_diminuendo.append({
                    'type': 'diminuendo',
                    'from_measure': sorted_measures[i-1],
                    'to_measure': m_idx,
                    'amplitude_change': round(abs(diff), 3)
                })
        
        prev_avg = m_avg
    
    return {
        'global_dynamic': global_dynamic,
        'per_measure': per_measure,
        'crescendo_diminuendo': crescendo_diminuendo,
        'stats': {
            'avg_amplitude': round(avg_amp, 3),
            'max_amplitude': round(max_amp, 3),
            'min_amplitude': round(min_amp, 3)
        }
    }


def detect_key_signature(note_events) -> str:
    """
    Détecte la tonalité (armure) à partir des note_events en utilisant les profils de Krumhansl-Schmuckler.
    Retourne la clé sous la forme VexFlow standard.
    """
    if not note_events:
        return 'C'

    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    major_profile = major_profile - np.mean(major_profile)
    minor_profile = minor_profile - np.mean(minor_profile)

    histogram = np.zeros(12)
    for event in note_events:
        pitch = int(event[2])
        duration = float(event[1]) - float(event[0]) if len(event) > 1 else 1.0
        amp = float(event[3]) if len(event) > 3 else 0.7
        histogram[pitch % 12] += max(0.01, duration) * amp

    if np.sum(histogram) == 0:
        return 'C'

    histogram = histogram - np.mean(histogram)

    best_correlation = -2.0
    best_key = 'C'

    major_keys = {
        0: 'C', 7: 'G', 2: 'D', 9: 'A', 4: 'E', 11: 'B', 6: 'F#',
        5: 'F', 10: 'Bb', 3: 'Eb', 8: 'Ab', 1: 'Db'
    }

    minor_keys = {
        9: 'C', 4: 'G', 11: 'D', 6: 'A', 1: 'E', 8: 'B', 3: 'F#',
        2: 'F', 7: 'Bb', 0: 'Eb', 5: 'Ab', 10: 'Db'
    }

    for shift in range(12):
        shifted_hist = np.roll(histogram, -shift)

        corr_maj = np.correlate(shifted_hist, major_profile)[0]
        if corr_maj > best_correlation:
            best_correlation = corr_maj
            best_key = major_keys.get(shift, 'C')

        corr_min = np.correlate(shifted_hist, minor_profile)[0]
        if corr_min > best_correlation:
            best_correlation = corr_min
            best_key = minor_keys.get(shift, 'C')

    return normalize_key_signature(best_key)



# ── Helpers V4 (harmonic_ctx, pedal, Jazz) ───────────────────────────────────

def _build_key_changes(stable_keys: list, beats_per_measure: float) -> list:
    """
    Construit la liste des changements d'armure à émettre dans le JSON.
    Chaque entrée indique la mesure 0-indexée où l'armure change.
    
    Ex: [(0.0, 'F major'), (48.0, 'F minor'), (96.0, 'F major')]
        beats_per_measure=3  →  mesures 0, 16, 32
    """
    changes = []
    prev_key = None
    for beat_pos, key_name in stable_keys:
        measure_num = int(beat_pos / beats_per_measure) if beats_per_measure > 0 else 0
        # Extraire tonique + mode
        parts    = key_name.split()
        raw_tonic = parts[0] if parts else 'C'
        # Mêmes corrections que key_name_to_vexflow() : music21 note les bémols
        # avec '-' (pas 'b') et code le mode mineur par une minuscule.
        tonic_fixed = raw_tonic.replace('-', 'b')
        tonic_fixed = tonic_fixed[0].upper() + tonic_fixed[1:]
        key_root = normalize_key_signature(tonic_fixed)
        mode     = parts[1] if len(parts) > 1 else 'major'
        entry    = {'measure': measure_num, 'key': key_root, 'mode': mode}
        if entry != prev_key:
            changes.append(entry)
            prev_key = entry
    return changes


def _build_chord_symbols(chord_map: dict, beats_per_measure: float) -> list:
    """
    Construit la liste des symboles d'accords pour le preset Jazz.
    Filtre les symboles vides ou non reconnus (confidence < 0.5).
    
    Retourne une liste de {measure, beat_in_measure, symbol} trié par position.
    """
    symbols = []
    for beat_pos, ca in sorted(chord_map.items()):
        if not ca or not ca.chord_symbol or not ca.is_known_chord:
            continue
        if ca.confidence < 0.5:
            continue
        measure_num   = int(beat_pos / beats_per_measure) if beats_per_measure > 0 else 0
        beat_in_meas  = beat_pos % beats_per_measure if beats_per_measure > 0 else beat_pos
        symbols.append({
            'measure':       measure_num,
            'beatInMeasure': round(beat_in_meas, 3),
            'symbol':        ca.chord_symbol,
            'romanNumeral':  ca.roman_numeral,
        })
    return symbols


def _build_pedal_markers(pedals: list, tempo_map, all_notes: list = None) -> list:
    """
    Convertit les intervalles de pédale (en secondes) en positions de mesure.
    Chaque entrée : {startBeat, endBeat, type: 'ped'|'*'}.

    pedals: liste de (onset_sec, offset_sec)

    BUGS CORRIGÉS (v4.1) :
    - Une tenue de pédale s'affichait même quand aucune note (ni main gauche,
      ni main droite) ne sonnait pendant tout l'intervalle (ex: deux silences
      simultanés) — absurde musicalement. On filtre désormais les tenues qui
      ne recouvrent aucune note jouée.
    - Deux tenues quasi consécutives (relâché puis re-pédalé presque aussitôt)
      créaient un chevauchement visuel gênant (symboles "Ped."/"*" collés) :
      on les fusionne désormais en une seule tenue quand l'écart est minime.
    """
    if not pedals:
        return []

    # ── 1. Conversion secondes → beats ───────────────────────────────────────
    raw_spans = []
    for p_start, p_end in pedals:
        start_beat = tempo_map.seconds_to_beat(p_start)
        end_beat   = tempo_map.seconds_to_beat(p_end)
        if end_beat > start_beat:
            raw_spans.append((start_beat, end_beat))
    raw_spans.sort(key=lambda s: s[0])

    # ── 2. Fusionner les tenues quasi-adjacentes (évite le chevauchement) ────
    MERGE_GAP_BEATS = 0.2  # en dessous de ~ une double-croche, on considère que c'est continu
    merged = []
    for start_beat, end_beat in raw_spans:
        if merged and start_beat - merged[-1][1] <= MERGE_GAP_BEATS:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_beat))
        else:
            merged.append((start_beat, end_beat))

    # ── 3. Filtrer les tenues sans aucune note jouée en dessous ──────────────
    def _has_sounding_note(start_beat: float, end_beat: float) -> bool:
        if not all_notes:
            return True  # pas d'info dispo → on ne filtre pas par prudence
        for n in all_notes:
            note_start = n.beat_position
            note_end   = n.beat_position + n.beat_duration
            if note_end > start_beat and note_start < end_beat:
                return True
        return False

    markers = []
    for start_beat, end_beat in merged:
        if not _has_sounding_note(start_beat, end_beat):
            continue
        markers.append({
            'startBeat': round(start_beat, 3),
            'endBeat':   round(end_beat, 3),
            'type':      'ped',
        })
    return markers


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