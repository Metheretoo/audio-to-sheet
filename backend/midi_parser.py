"""
midi_parser.py — Conversion note_events → JSON VexFlow + export MIDI
"""
import uuid
import math
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

# ── Constantes ────────────────────────────────────────────────────────────────

# Noms de notes en demi-tons (avec dièses - par défaut)
PITCH_NAMES_SHARP = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']
# Noms de notes avec bémols (pour armures en bémols)
PITCH_NAMES_FLAT  = ['c', 'db', 'd', 'eb', 'e', 'f', 'gb', 'g', 'ab', 'a', 'bb', 'b']

# Tonalités avec bémols (utiliser noms bémolisés)
FLAT_KEY_SIGS = {'F', 'Bb', 'Eb', 'Ab', 'Db', 'Gb', 'Cb'}

# Table durées : (beats, code_vexflow, points, tuplet)
# tuplet = 1 (normal), 3/2 (triolet), 2/3 (duplet), etc.
# Inclut les triolets (ratio 2/3 = 1.5x plus court) et quadruple-croches (rubato)
DURATION_TABLE = [
    (4.000, 'w',  0, 1.0),
    (3.000, 'h',  1, 1.0),   # blanche pointée
    (2.000, 'h',  0, 1.0),
    (1.500, 'q',  1, 1.0),   # noire pointée
    (1.333, 'q',  0, 1.5),   # triolet de noires (2/3 de noire = 0.666... beat, 3 dans 1 temps)
    (1.000, 'q',  0, 1.0),
    (0.750, '8',  1, 1.0),   # croche pointée
    (0.667, '8',  0, 1.5),   # triolet de croches (2/3 de croche = 0.333... beat, 3 dans 1 temps)
    (0.500, '8',  0, 1.0),
    (0.375, '16', 1, 1.0),   # double-croche pointée
    (0.333, '16', 0, 1.5),   # triolet de double-croches
    (0.250, '16', 0, 1.0),
    (0.167, '32', 0, 1.5),   # triolet de triple-croches (rubato)
    (0.125, '32', 0, 1.0),   # triple-croche (rubato)
]

QUANTIZE_GRID        = 0.5    # Grille de quantification : croche (1/8) pour simplifier l'écriture
TREBLE_THRESHOLD     = 57     # MIDI 57 = La3 : seuil main droite / gauche (évite de perdre Si3-Do4)
MIN_DURATION_BEATS   = 0.25   # Minimum note length
CONFIDENCE_THRESHOLD = 0.20   # Amplitude minimum - valeur basse pour capturer les basses
DEDUP_WINDOW         = 0.08   # Fenêtre de déduplification en beats
PARASITE_MAX_DUR     = 0.5    # Durée max pour considérer une note parasite
PARASITE_MAX_AMP     = 0.35   # Amplitude max combinée à la durée courte = parasite

# Durées valides pour remplir les silences (ordre décroissant)
REST_DURS = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.167, 0.125]


# ── Fonctions utilitaires ─────────────────────────────────────────────────────

def get_pitch_names(key_sig='C'):
    """Retourne la table des noms de notes adaptée à l'armure."""
    if key_sig in FLAT_KEY_SIGS:
        return PITCH_NAMES_FLAT
    return PITCH_NAMES_SHARP


def midi_to_vexflow_key(pitch: int, key_sig='C') -> str:
    """MIDI pitch → clé VexFlow  (ex : 60 → 'c/4', 61 → 'c#/4' ou 'db/4')"""
    names  = get_pitch_names(key_sig)
    name   = names[pitch % 12]
    octave = (pitch // 12) - 1
    return f'{name}/{octave}'


def get_rest_key(dur_str: str, hand: str, dots: int = 0) -> str:
    """
    Retourne la clé VexFlow correcte pour un silence selon la durée, la portée et le point.
    """
    if hand == 'treble':
        return 'd/5' if dur_str == 'w' else 'b/4'
    else:  # bass
        return 'f/3' if dur_str == 'w' else 'd/3'


def beats_to_duration(beats: float, floor: bool = False):
    """Durée en beats → (code_vexflow, points)"""
    def cost(d_tuple):
        val, code, dots, tuplet = d_tuple
        dist = abs(val - beats)
        # Pénaliser les notes pointées et triolets pour préférer les durées simples
        penalty = 1.0
        if dots > 0: penalty *= 2.0
        if tuplet != 1.0: penalty *= 1.5
        return dist * penalty

    if floor:
        # Garder uniquement les durées inférieures ou égales (avec une petite tolérance)
        valid = [d for d in DURATION_TABLE if d[0] <= beats + 1e-4]
        if valid:
            best = min(valid, key=cost)
        else:
            best = min(DURATION_TABLE, key=cost)
    else:
        best = min(DURATION_TABLE, key=cost)
    return best[1], best[2]


def duration_beats(dur_str: str, dots: int) -> float:
    """Code VexFlow + points → durée en beats"""
    # IMPORTANT : '32' (triple croche = 0.125 beat) doit être présent
    # Son absence causait un fallback à 1.0 (noire) → erreurs de durée en cascade
    MAP = {'w': 4.0, 'h': 2.0, 'q': 1.0, '8': 0.5, '16': 0.25, '32': 0.125}
    base = MAP.get(dur_str, 0.125)  # fallback = triple croche (valeur minimale)
    if dots:
        base *= 1.5
    return base


def quantize(value: float, grid: float = QUANTIZE_GRID) -> float:
    return round(value / grid) * grid


def new_id() -> str:
    return str(uuid.uuid4())


def vexflow_key_to_pitch(key: str) -> int:
    """'c#/4' → MIDI pitch (pour tri et export)"""
    NOTE_ST = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
    parts = key.split('/')
    if len(parts) != 2:
        return 60
    note_str = parts[0].lower()
    try:
        octave = int(parts[1])
    except ValueError:
        octave = 4
    base = NOTE_ST.get(note_str[0], 0)
    mod  = note_str[1:].count('#') - note_str[1:].count('b')
    return (octave + 1) * 12 + base + mod


def _deduplicate(notes):
    """
    Supprime les notes en double : même pitch et début très proche.
    Garde celle qui a l'amplitude la plus haute.
    """
    if not notes:
        return notes

    notes = sorted(notes, key=lambda n: (n['startBeat'], n['midiPitch']))
    kept = []
    for n in notes:
        duplicate = False
        for k in kept:
            if (k['midiPitch'] == n['midiPitch'] and
                    abs(k['startBeat'] - n['startBeat']) < DEDUP_WINDOW):
                # Garder la plus forte
                if n['amplitude'] > k['amplitude']:
                    kept.remove(k)
                    kept.append(n)
                duplicate = True
                break
        if not duplicate:
            kept.append(n)
    return kept


# ── Parsing principal ─────────────────────────────────────────────────────────

# ── Tonalité automatique Krumhansl-Schmuckler ────────────────────────────────

def detect_key_signature(note_events):
    """
    Détecte la tonalité (armure) à partir d'un ensemble d'événements de notes
    en utilisant les profils de Krumhansl-Schmuckler.
    Retourne la clé sous la forme VexFlow standard.
    """
    if not note_events:
        return 'C'

    import numpy as np

    # Profils de Krumhansl-Schmuckler pour le mode Majeur et Mineur
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    # Normalisation des profils (centrés sur la moyenne)
    major_profile = major_profile - np.mean(major_profile)
    minor_profile = minor_profile - np.mean(minor_profile)

    # Histogramme des hauteurs de note (12 demi-tons) pondéré par l'amplitude et la durée
    histogram = np.zeros(12)
    for event in note_events:
        pitch = int(event[2])
        duration = float(event[1]) - float(event[0])
        amp = float(event[3]) if len(event) > 3 else 0.7
        histogram[pitch % 12] += max(0.01, duration) * amp

    if np.sum(histogram) == 0:
        return 'C'

    histogram = histogram - np.mean(histogram)

    best_correlation = -2.0
    best_key = 'C'

    # Mapping des toniques transposées sur les armures majeures VexFlow
    major_keys = {
        0: 'C', 7: 'G', 2: 'D', 9: 'A', 4: 'E', 11: 'B', 6: 'F#',
        5: 'F', 10: 'Bb', 3: 'Eb', 8: 'Ab', 1: 'Db', 6: 'Gb'
    }

    # Mapping mineur (armure majeure relative)
    minor_keys = {
        9: 'C', 4: 'G', 11: 'D', 6: 'A', 1: 'E', 8: 'B', 3: 'F#',
        2: 'F', 7: 'Bb', 0: 'Eb', 5: 'Ab', 10: 'Db', 3: 'Gb'
    }

    for shift in range(12):
        shifted_hist = np.roll(histogram, -shift)

        # Corrélation Majeur
        corr_maj = np.correlate(shifted_hist, major_profile)[0]
        if corr_maj > best_correlation:
            best_correlation = corr_maj
            best_key = major_keys.get(shift, 'C')

        # Corrélation Mineur
        corr_min = np.correlate(shifted_hist, minor_profile)[0]
        if corr_min > best_correlation:
            best_correlation = corr_min
            best_key = minor_keys.get(shift, 'C')

    return best_key


# ── Parsing principal ─────────────────────────────────────────────────────────

def parse_note_events(note_events, tempo=120, time_sig_num=4, time_sig_den=4, key_sig='C', options=None):
    """
    Convertit les note_events en JSON prêt pour VexFlow avec gestion des options.

    note_events : list[(start_s, end_s, pitch_midi, amplitude, pitch_bends)]
    """
    if options is None:
        options = {
            'transcriber': 'piano_transcription',
            'use_demucs': False,
            'quantization_level': 'standard',
            'remove_short_notes': True,
            'minimum_note_duration': 50,
            'merge_near_notes': True,
            'merge_gap_ms': 30,
            'split_hands': True,
            'detect_tempo': True,
            'detect_key': True
        }

    # ── A. Détection Tonalité ──────────────────────────────────────────────
    if options.get('detect_key', True):
        key_sig = detect_key_signature(note_events)
        print(f"[MIDI Parser] Tonalité détectée automatiquement : {key_sig}")

    if not note_events:
        return _empty_score(tempo, time_sig_num, time_sig_den, key_sig)

    # ── B. Nettoyage MIDI ──────────────────────────────────────────────────
    # 1. Supprimer les notes très courtes (en secondes)
    if options.get('remove_short_notes', True):
        min_dur_s = options.get('minimum_note_duration', 50) / 1000.0
        note_events = [e for e in note_events if (float(e[1]) - float(e[0])) >= min_dur_s]

    # 2. Fusionner les notes répétées très proches
    if options.get('merge_near_notes', True) and note_events:
        merge_gap_s = options.get('merge_gap_ms', 30) / 1000.0
        by_pitch = {}
        for event in note_events:
            pitch = int(event[2])
            by_pitch.setdefault(pitch, []).append(list(event))
            
        merged_events = []
        for pitch, events in by_pitch.items():
            events.sort(key=lambda x: float(x[0]))
            temp = []
            for ev in events:
                if not temp:
                    temp.append(ev)
                else:
                    last = temp[-1]
                    if (float(ev[0]) - float(last[1])) <= merge_gap_s:
                        last[1] = max(float(last[1]), float(ev[1]))
                        last[3] = max(float(last[3]), float(ev[3]))
                    else:
                        temp.append(ev)
            merged_events.extend(temp)
        note_events = merged_events

    if not note_events:
        return _empty_score(tempo, time_sig_num, time_sig_den, key_sig)

    beat_s            = 60.0 / max(tempo, 20)
    beats_per_measure = time_sig_num * (4.0 / time_sig_den)

    # ── C. Quantification ──────────────────────────────────────────────────
    quant_level = options.get('quantization_level', 'standard')
    if quant_level == 'none':
        grid = 0.0625 # 1/64
    elif quant_level == 'light':
        grid = 0.125  # 1/32
    elif quant_level == 'heavy':
        grid = 0.5    # 1/8
    else:  # standard
        grid = 0.25   # 1/16

    # ── D. Conversion des notes ────────────────────────────────────────────
    notes = []
    for event in note_events:
        start_s = float(event[0])
        end_s   = float(event[1])
        pitch   = int(event[2])
        amp     = float(event[3]) if len(event) > 3 else 0.7

        # Filtrage par confiance
        if amp < CONFIDENCE_THRESHOLD:
            continue

        start_b = quantize(start_s / beat_s, grid)
        end_b   = quantize(end_s   / beat_s, grid)
        dur_b   = max(grid, end_b - start_b)

        dur_str, dots = beats_to_duration(dur_b)

        # Main gauche / droite
        if options.get('split_hands', True):
            hand = 'treble' if pitch >= TREBLE_THRESHOLD else 'bass'
        else:
            hand = 'treble'

        notes.append({
            'id':          new_id(),
            'startBeat':   start_b,
            'duration':    duration_beats(dur_str, dots),
            'durationStr': dur_str,
            'dots':        dots,
            'keys':        [midi_to_vexflow_key(pitch, key_sig)],
            'midiPitch':   pitch,
            'hand':        hand,
            'amplitude':   round(amp, 3),
            'isRest':      False,
        })

    if not notes:
        return _empty_score(tempo, time_sig_num, time_sig_den, key_sig)

    # Déduplification
    notes = _deduplicate(notes)

    # Tri chronologique
    notes.sort(key=lambda n: (n['startBeat'], -n['midiPitch']))

    # Décalage pour commencer au début de la mesure 1
    min_start_beat = min(n['startBeat'] for n in notes) if notes else 0
    if min_start_beat > 0:
        for n in notes:
            n['startBeat'] -= min_start_beat
        print(f'[MIDI Parser] Décalage de la partition de {min_start_beat} beat(s) pour commencer à la 1ère note')

    # Regroupement par mesure
    total_beats  = max(n['startBeat'] + n['duration'] for n in notes) if notes else 0
    num_measures = max(1, math.ceil(total_beats / beats_per_measure))

    measures = []
    for m in range(num_measures):
        m_start = m * beats_per_measure
        m_end   = (m + 1) * beats_per_measure

        treble = [n for n in notes if n['hand'] == 'treble'
                  and n['startBeat'] >= m_start and n['startBeat'] < m_end]
        bass   = [n for n in notes if n['hand'] == 'bass'
                  and n['startBeat'] >= m_start and n['startBeat'] < m_end]

        # Utilisation de la grille dynamique pour la construction des voix
        measures.append({
            'treble': _build_voice(treble, m_start, beats_per_measure, 'treble', key_sig, grid),
            'bass':   _build_voice(bass,   m_start, beats_per_measure, 'bass',   key_sig, grid),
        })

    return {
        'tempo':         int(tempo),
        'timeSignature': [time_sig_num, time_sig_den],
        'keySignature':  key_sig,
        'totalMeasures': num_measures,
        'measures':      measures,
    }


def _build_voice(notes, m_start, beats_per_measure, hand, key_sig='C', grid=0.5):
    """
    Construit une voix complète pour une portée :
    - Fusionne les notes simultanées en accords
    - Détermine les durées par IOI (intervalle inter-attaque)
    - Remplit les silences
    """
    REST_KEY = get_rest_key('q', hand)  # clé par défaut pour les silences

    if not notes:
        dur_str, dots = beats_to_duration(beats_per_measure)
        rest_key = get_rest_key(dur_str, hand, dots)
        return [_make_rest(rest_key, dur_str, dots, m_start, beats_per_measure, hand)]

    # Position de grille relative à la mesure
    GRID = grid
    rel_notes = [
        {**n, '_g': int(round((n['startBeat'] - m_start) / GRID))}
        for n in notes
    ]

    # Regroupement en accords (même position de grille)
    chords = {}
    for n in rel_notes:
        chords.setdefault(n['_g'], []).append(n)

    chord_keys  = sorted(chords.keys())
    total_grid  = int(round(beats_per_measure / GRID))
    voice       = []
    cursor      = 0   # en unités de grille

    for i_chord, g in enumerate(chord_keys):
        # ── Étanchéité : si la grille dépasse la fin de mesure, ignorer ──────
        if g >= total_grid:
            break

        # Silence avant l'accord
        if g > cursor:
            gap = (g - cursor) * GRID
            voice.extend(_split_rests(gap, m_start + cursor * GRID, hand))
            cursor = g

        chord_notes = chords[g]
        primary     = chord_notes[0]
        raw_dur     = primary['duration']

        # ── Calcul de la durée musicale via IOI ───────────────────────────
        # Espace disponible dans la mesure (étanchéité)
        space_in_measure_grid = total_grid - g
        if i_chord < len(chord_keys) - 1:
            next_g = chord_keys[i_chord + 1]
            ioi_beats = (min(next_g, total_grid) - g) * GRID
        else:
            ioi_beats = space_in_measure_grid * GRID

        ioi_beats = max(GRID, min(ioi_beats, 4.0))  # entre 1 cellule et 4 beats
        if raw_dur >= 0.30 * ioi_beats and ioi_beats >= QUANTIZE_GRID:
            target_beats = ioi_beats
        else:
            target_beats = raw_dur

        # Plafonner AVANT l'arrondi musical (étanchéité absolue)
        target_beats = min(target_beats, space_in_measure_grid * GRID)

        dur_str, dots   = beats_to_duration(target_beats)
        final_duration  = duration_beats(dur_str, dots)
        dur_grid        = max(1, int(round(final_duration / GRID)))

        # Empêcher tout dépassement : ne jamais dépasser l'espace restant
        max_allowed_grid = space_in_measure_grid
        if i_chord < len(chord_keys) - 1:
            max_allowed_grid = min(max_allowed_grid, min(chord_keys[i_chord + 1], total_grid) - g)
        if dur_grid > max_allowed_grid:
            dur_grid = max(1, max_allowed_grid)
            final_duration = dur_grid * GRID
            dur_str, dots = beats_to_duration(final_duration)

        # Clés triées du grave à l'aigu, avec la bonne armure
        all_keys = sorted(
            {midi_to_vexflow_key(n['midiPitch'], key_sig) for n in chord_notes},
            key=vexflow_key_to_pitch,
        )

        voice.append({
            'id':          primary['id'],
            'keys':        all_keys,
            'durationStr': dur_str,
            'dots':        dots,
            'isRest':      False,
            'startBeat':   primary['startBeat'],
            'duration':    final_duration,
            'midiPitch':   primary['midiPitch'],
            'hand':        hand,
            'amplitude':   primary['amplitude'],
        })

        cursor = g + dur_grid

    # Silence en fin de mesure
    if cursor < total_grid:
        gap = (total_grid - cursor) * GRID
        voice.extend(_split_rests(gap, m_start + cursor * GRID, hand))

    return voice


def _split_rests(total_beats, start_beat, hand):
    """Découpe un silence en durées standard avec la bonne clé de portée."""
    rests     = []
    remaining = total_beats
    pos       = start_beat

    while remaining > 0.01:
        chosen = next((d for d in REST_DURS if d <= remaining + 1e-4), None)
        if chosen is None:
            break
        dur_str, dots = beats_to_duration(chosen)
        rest_key = get_rest_key(dur_str, hand, dots)
        rests.append(_make_rest(rest_key, dur_str, dots, pos, chosen, hand))
        remaining -= chosen
        pos       += chosen

    return rests


def _make_rest(key, dur_str, dots, start_beat, duration, hand):
    return {
        'id':          new_id(),
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


def _empty_score(tempo, ts_num, ts_den, key_sig='C'):
    return {
        'tempo': tempo,
        'timeSignature': [ts_num, ts_den],
        'keySignature': key_sig,
        'totalMeasures': 0,
        'measures': [],
    }


# ── Export MIDI ───────────────────────────────────────────────────────────────

def score_to_midi(score_data: dict, output_path: str):
    """
    Génère un fichier MIDI depuis le JSON de partition (potentiellement édité).
    """
    tempo    = score_data.get('tempo', 120)
    ts       = score_data.get('timeSignature', [4, 4])
    ts_num   = ts[0]
    ts_den   = ts[1]

    TPB = 480  # Ticks per beat

    mid = MidiFile(type=1, ticks_per_beat=TPB)

    # ── Piste de tempo ────────────────────────────────────────────────────
    tempo_track = MidiTrack()
    mid.tracks.append(tempo_track)
    tempo_us = mido.bpm2tempo(tempo)
    tempo_track.append(MetaMessage('set_tempo', tempo=tempo_us, time=0))
    tempo_track.append(MetaMessage(
        'time_signature',
        numerator=ts_num, denominator=ts_den,
        clocks_per_click=24, notated_32nd_notes_per_beat=8,
        time=0,
    ))
    tempo_track.append(MetaMessage('end_of_track', time=0))

    # ── Collecte des événements (ticks absolus) ───────────────────────────
    beats_per_measure = ts_num * (4.0 / ts_den)

    treble_evts = []
    bass_evts   = []

    for m_idx, measure in enumerate(score_data.get('measures', [])):
        m_start = m_idx * beats_per_measure

        for hand_key, evts_list in [('treble', treble_evts), ('bass', bass_evts)]:
            cursor = m_start
            for nd in measure.get(hand_key, []):
                dur = nd.get('duration', 1.0)

                if not nd.get('isRest') and nd.get('midiPitch') is not None:
                    start_tick = int(cursor * TPB)
                    end_tick   = int((cursor + dur) * TPB)
                    vel        = max(1, min(127, int(nd.get('amplitude', 0.7) * 100)))

                    for key in nd.get('keys', []):
                        pitch = vexflow_key_to_pitch(key)
                        evts_list.append(('on',  start_tick, pitch, vel))
                        evts_list.append(('off', end_tick,   pitch, 0))

                cursor += dur

    # ── Écriture des pistes ───────────────────────────────────────────────
    for name, evts, ch in [('Treble (main droite)', treble_evts, 0),
                            ('Bass (main gauche)',   bass_evts,   1)]:
        track = MidiTrack()
        mid.tracks.append(track)
        track.append(MetaMessage('track_name', name=name, time=0))

        # Trier : note_off avant note_on au même tick
        evts.sort(key=lambda e: (e[1], 0 if e[0] == 'off' else 1))

        prev = 0
        for etype, tick, pitch, vel in evts:
            delta = tick - prev
            if etype == 'on':
                track.append(Message('note_on',  channel=ch, note=pitch, velocity=vel, time=delta))
            else:
                track.append(Message('note_off', channel=ch, note=pitch, velocity=0,   time=delta))
            prev = tick

        track.append(MetaMessage('end_of_track', time=0))

    mid.save(output_path)
    print(f'[MIDI] Fichier sauvegardé : {output_path}')
