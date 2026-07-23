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

# [P4] Import du détecteur d'ornements
try:
    from ornament_detector import OrnamentDetector, OrnamentResult, ArpeggioInfo
    _has_ornament_detector = True
except ImportError:
    _has_ornament_detector = False

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
    use_downbeats: bool = True,  # [P3.5] Activer l'utilisation de downbeat_times
    ornament_result: 'OrnamentResult' = None,  # [P4] Résultat de détection d'ornements
    uncertain_note_ids: list = None,  # [P6] IDs des notes incertaines (fallback single-model)
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
    import sys as _sys; _sys.stdout.flush()
    print(f"[ScoreBuilder DEBUG] key_sig={key_sig!r} detect_key={detect_key!r} manual_key_sig={manual_key_sig!r}", flush=True)

    if not detect_key:
        # L'utilisateur a désactivé la détection auto → respecter son choix (même si key_sig est vide, utiliser 'C')
        key_sig = manual_key_sig
        print(f"[ScoreBuilder] ✅ Tonalité manuelle respectée: {key_sig} (detect_key={detect_key})")
    elif harmonic_ctx is not None and harmonic_ctx.stable_keys and detect_key:
        # Ne pas utiliser la tonalité harmonique si detect_key=False (l'utilisateur a choisi manuellement)
        # Prendre la tonalité de la 1ère entrée stable pour l'armure initiale
        first_key_name = harmonic_ctx.stable_keys[0][1]  # ex: "F major" / "a minor"
        key_sig = key_name_to_vexflow(first_key_name)
        print(f"[ScoreBuilder] ⚠️ Tonalité harmonique utilisée: {first_key_name} → {key_sig} (detect_key={detect_key})")
    elif detect_key:
        all_notes = voices.treble + voices.bass
        # Passer (onset, pitch, duration, amplitude) au détecteur
        key_sig = detect_key_signature([
            (n.beat_position, n.pitch_midi, n.beat_duration, n.amplitude) for n in all_notes
        ])
        print(f"[ScoreBuilder] ⚠️ Tonalité par détecteur interne: {key_sig} (detect_key={detect_key})")
    else:
        key_sig = manual_key_sig
        print(f"[ScoreBuilder] ✅ Tonalité par défaut (fallback): {key_sig}")
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

    # [P3.5] Extraire downbeat_times pour intégration dans le JSON
    downbeat_times_beats = None
    if use_downbeats and hasattr(tempo_map, 'downbeat_times') and len(tempo_map.downbeat_times) > 0:
        # Convertir downbeat timestamps (secondes) → positions de beat
        downbeat_times_beats = [tempo_map.seconds_to_beat(t) for t in tempo_map.downbeat_times]
        print(f"[ScoreBuilder] {len(downbeat_times_beats)} downbeats détectés (P3.5)")

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

        measure_data = {
            'treble': build_voice_vexflow(
                treble_in_measure, m_start, beats_per_measure, 'treble', key_sig
            ),
            'bass': build_voice_vexflow(
                bass_in_measure, m_start, beats_per_measure, 'bass', key_sig
            ),
            # m_start: position absolue du début de cette mesure en beats (pour le frontend)
            'm_start': m_start,
        }

        # ── Note la plus haute de la main droite (pour aider les débutants) ─
        # Pour CHAQUE NOTE de la main droite qui commence dans cette mesure,
        # on détecte si c'est la note la plus haute parmi toutes les notes
        # de la main droite de TOUTE la partition à ce moment-là.
        pitch_names = ['Do', 'Do♯', 'Ré', 'Ré♯', 'Mi', 'Fa', 'Fa♯', 'Sol', 'Sol♯', 'La', 'La♯', 'Si']
        
        # Notes de la main droite qui commencent DANS cette mesure
        treble_in_measure = [
            n for n in voices.treble
            if n.beat_position >= m_start and n.beat_position < m_end
        ]
        treble_sounding = [n for n in treble_in_measure if not getattr(n, 'is_rest', False)]
        
        highest_notes_per_beat = []
        if treble_sounding:
            for note in treble_sounding:
                note_name = pitch_names[note.pitch_midi % 12]
                highest_notes_per_beat.append({
                    'beatInMeasure': round(note.beat_position - m_start, 3),
                    'midiPitch': note.pitch_midi,
                    'noteName': note_name
                })
        
        measure_data['highestNotes'] = highest_notes_per_beat
        
        # Debug : vérifier que highestNotes est bien peuplé
        if highest_notes_per_beat:
            print(f"[ScoreBuilder DEBUG] Mesure {m_idx + 1}: {len(highest_notes_per_beat)} notes aigües, m_start={m_start:.3f}", flush=True)

        measures.append(measure_data)

    # [P3.5] Construire les mesures avec information downbeat
    # Convertir downbeat_times_beats en indices de mesure pour le JSON
    downbeat_measure_indices = set()
    if downbeat_times_beats is not None:
        for db_beat in downbeat_times_beats:
            m_idx = int(db_beat / beats_per_measure)
            if 0 <= m_idx < num_measures:
                downbeat_measure_indices.add(m_idx)

    # Marquer chaque mesure comme downbeat ou non
    measures_with_downbeat = []
    for m_idx in range(num_measures):
        measure_data = measures[m_idx]
        measure_data['isDownbeat'] = m_idx in downbeat_measure_indices
        measure_data['measureNumber'] = m_idx + 1  # 1-indexed pour le frontend
        measures_with_downbeat.append(measure_data)

    result = {
        'tempo':         global_bpm,
        'timeSignature': [ts_num, ts_den],
        'keySignature':  key_sig,
        'totalMeasures': num_measures,
        'measures':      measures_with_downbeat,
        # [P3.5] Métadonnées TempoMap pour le frontend
        'tempoMapMethod':  getattr(tempo_map, 'method', 'unknown'),
        'detectedMeter':   list(getattr(tempo_map, 'estimated_meter', (ts_num, ts_den))),
        'tempoRange':      list(tempo_map.tempo_range()) if hasattr(tempo_map, 'tempo_range') else [],
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
    
    # [P4] Intégration des ornements dans le JSON
    if ornament_result is not None:
        result['ornaments'] = _build_ornaments_json(ornament_result, beats_per_measure)
    
    # [P6] Intégration des notes incertaines (fallback single-model)
    if uncertain_note_ids is not None and len(uncertain_note_ids) > 0:
        result['uncertainNotes'] = uncertain_note_ids
        print(f"[ScoreBuilder] {len(uncertain_note_ids)} notes marquées comme 'incertaines' (P6)")
    
    return result


# ── Détection et fusion des arpèges ───────────────────────────────────────────

def _merge_arpeggios(notes: List[QuantizedNote], key_sig: str = 'C') -> List[QuantizedNote]:
    """
    Identifie les séquences de notes correspondant à des arpèges ascendants
    et les fusionne en un seul accord pour le rendu VexFlow.
    """
    if not _has_ornament_detector or not notes:
        return notes

    # On utilise un seuil basique pour la détection à la volée s'il n'y a pas d'OrnamentResult global
    detector = OrnamentDetector()
    beat_positions = [n.beat_position for n in notes]
    # On n'a pas accès à already_ornamental ici, mais c'est un cas fallback de toute façon
    arpeggios = detector._detect_arpeggios(notes, beat_positions, {})
    
    if not arpeggios:
        return notes
        
    merged_notes = list(notes)
    
    # Appliquer de la fin vers le début pour ne pas perturber les index
    for arp in reversed(arpeggios):
        # Créer une copie de la première note de l'arpège (qui sera la note de base de l'accord)
        base_note = merged_notes[arp.start_index]
        base_note._is_arpeggio = True
        base_note._arpeggio_direction = 'up'
        
        # Supprimer les autres notes de l'arpège pour ne garder que la base (VexFlow fera l'accord avec les pitches originaux ? Non, il faut garder les notes mais leur donner la MÊME position !)
        # Ah ! build_voice_vexflow regroupe les notes par beat_position !
        # Donc pour fusionner en accord, il suffit d'aligner la beat_position de toutes les notes sur celle de la première.
        for i in range(arp.start_index + 1, arp.end_index + 1):
            merged_notes[i].beat_position = base_note.beat_position
            merged_notes[i]._is_arpeggio = True
            
        # Aligner la durée de la base sur celle de la plus longue (la dernière)
        last_note = merged_notes[arp.end_index]
        base_note.beat_duration = max(base_note.beat_duration, (last_note.beat_position_original if hasattr(last_note, 'beat_position_original') else last_note.beat_position) + last_note.beat_duration - base_note.beat_position)

    return merged_notes

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
    2. Détecter et fusionner les accords arpégés ascendants (P-Arp)
    3. Grouper les notes simultanées en accords (beat_position identique)
    4. Pour chaque accord :
       - La durée est l'IOI (distance jusqu'à la prochaine note) sauf si
         le sustain mesuré est clairement staccato (< 40 % de l'IOI ET < 0.5 beat).
       - On évite ainsi les silences parasites entre deux notes liées/tenues.
    5. Combler les silences réels (gaps entre notes non liées) en fin de mesure.

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

    # [P-Arp] Détecter et fusionner les accords arpégés AVANT le groupement
    notes = _merge_arpeggios(notes, key_sig)

    # [FIX] Aligner les notes dont les positions sont très proches (< 0.05 beat)
    # sur la même position. Cela capture les accords brisés rapides non détectés
    # comme arpèges (ex: triple croches proches en musique classique).
    _ALIGN_THRESHOLD = 0.05  # beats
    aligned_notes = []
    if notes:
        current_pos = notes[0].beat_position
        aligned_notes.append(notes[0])
        for n in notes[1:]:
            if abs(n.beat_position - current_pos) <= _ALIGN_THRESHOLD:
                # Aligner sur la position courante
                n.beat_position = current_pos
            else:
                current_pos = n.beat_position
            aligned_notes.append(n)
        notes = aligned_notes

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
    """
    MIDI pitch → clé VexFlow (ex: 60 → 'c/4', 61 → 'c#/4').
    
    Cette fonction map le MIDI pitch au nom de note avec l'altération correcte
    EN FONCTION de l'armure. Les altérations sont calculées pour que la note
    soit correcte musicalement par rapport à l'armure donnée.
    
    Principe :
    - L'armure VexFlow (keySignature) altère certaines notes automatiquement
    - Cette fonction doit retourner la note de base + l'altération qui,
      combinée à l'armure, donne la note désirée
    - Ex: armure F (Si♭) + note Si naturel → retourne 'b/X:n' (bécarre)
    
    Exemples :
    - Armure C : MIDI 60 (C4) → 'c/4' (pas d'altération)
    - Armure F (1♭=Si♭) : MIDI 71 (Si naturel) → 'b/4:n' (bécarre annule le ♭)
    - Armure F (1♭=Si♭) : MIDI 70 (Si♭) → 'b/4:b' (bémol renforce le ♭)
    - Armure G (1#=Fa#) : MIDI 65 (Fa naturel) → 'f/4:n' (bécarre annule le #)
    - Armure G (1#=Fa#) : MIDI 66 (Fa#) → 'f/4:#' (dièse renforce le #)
    """
    pitch_class = pitch % 12
    
    # VexFlow octave : c/4 = MIDI 60 (C4 = Do central)
    vexflow_octave = (pitch // 12) - 1
    
    # Mapping pitch_class → nom de note VexFlow de base
    # C=0, D=2, E=4, F=5, G=7, A=9, B=11 (intervalles en demi-tons)
    NOTE_TO_DEGREE = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
    
    # Mapping pitch_class → nom de note avec DIÈSES (pour armures à dièses)
    # Les notes enharmones utilisent des dièses : Db→C#, Eb→D#, Gb→F#, Ab→G#, Bb→A#
    PITCH_TO_NAME_SHARP = {
        0: 'c', 1: 'c#', 2: 'd', 3: 'd#', 4: 'e', 5: 'f',
        6: 'f#', 7: 'g', 8: 'g#', 9: 'a', 10: 'a#', 11: 'b'
    }
    
    # Mapping pitch_class → nom de note avec BÉMOLS (pour armures à bémols)
    # Les notes enharmones utilisent des bémols : C#→Db, D#→Eb, F#→Gb, G#→Ab, A#→Bb
    PITCH_TO_NAME_FLAT = {
        0: 'c', 1: 'db', 2: 'd', 3: 'eb', 4: 'e', 5: 'f',
        6: 'gb', 7: 'g', 8: 'ab', 9: 'a', 10: 'bb', 11: 'b'
    }
    
    # Mapping complet des armures → notes altérées
    # Format: (mode, tonic_normalized) → (alt_type, set de pitch_class altérés)
    # alt_type: 'sharp' = dièse, 'flat' = bémol
    
    # Ordre des altérations par armure
    SHARP_KEY_SIG = {
        # Majeures avec dièses
        ('major', 'g'): 1,            # G: 1# (F#)
        ('major', 'd'): 2,            # D: 2# (F# C#)
        ('major', 'a'): 3,            # A: 3# (F# C# G#)
        ('major', 'e'): 4,            # E: 4# (F# C# G# D#)
        ('major', 'b'): 5,            # B: 5# (F# C# G# D# A#)
        ('major', 'f#'): 6,           # F#: 6# (F# C# G# D# A# E#)
        ('major', 'c#'): 7,           # C#: 7#
        # Mineures avec dièses (relative majeure)
        ('minor', 'e'): 1,            # Em: relative de G
        ('minor', 'b'): 2,            # Bm: relative de D
        ('minor', 'f#'): 3,           # F#m: relative de A
        ('minor', 'c#'): 4,           # C#m: relative de E
        ('minor', 'g#'): 5,           # G#m: relative de B
        ('minor', 'd#'): 6,           # D#m: relative de F#
        ('minor', 'a#'): 7,           # A#m: relative de C#
    }
    
    FLAT_KEY_SIG = {
        # Majeures avec bémols
        ('major', 'f'): 1,            # F: 1b (Bb)
        ('major', 'bb'): 2,           # Bb: 2b (Bb Eb)
        ('major', 'eb'): 3,           # Eb: 3b (Bb Eb Ab)
        ('major', 'ab'): 4,           # Ab: 4b (Bb Eb Ab Db)
        ('major', 'db'): 5,           # Db: 5b (Bb Eb Ab Db Gb)
        ('major', 'gb'): 6,           # Gb: 6b (Bb Eb Ab Db Gb Cb)
        ('major', 'cb'): 7,           # Cb: 7b
        # Mineures avec bémols (relative majeure)
        ('minor', 'd'): 1,            # Dm: relative de F
        ('minor', 'g'): 2,            # Gm: relative de Bb
        ('minor', 'c'): 3,            # Cm: relative de Eb
        ('minor', 'f'): 4,            # Fm: relative de Ab
        ('minor', 'bb'): 5,           # Bbm: relative de Db
        ('minor', 'eb'): 6,           # Ebm: relative de Gb
        ('minor', 'ab'): 7,           # Abm: relative de Cb
    }
    
    # Normaliser l'armure
    is_minor = key_sig.lower().endswith('m')
    mode = 'minor' if is_minor else 'major'
    
    key_sig_clean = key_sig.lower().rstrip('m')
    
    # Déterminer la tonique normalisée
    if len(key_sig_clean) >= 2 and key_sig_clean[1] in '#b':
        tonic = key_sig_clean[:2]
    else:
        tonic = key_sig_clean[0]
    
    # Normaliser la tonique (Bb → bb, Eb → eb, etc.)
    if len(tonic) == 2 and tonic[1] == '#':
        tonic = tonic.lower()  # 'f#' → 'f#'
    elif len(tonic) == 2 and tonic[1] == 'b':
        tonic = tonic.lower()  # 'bb' → 'bb'
    
    # Trouver le type d'armure et le nombre d'altérations
    num_alts = 0
    alt_type = 'natural'  # 'natural', 'sharp', 'flat'
    
    if mode in ('major', 'minor'):
        # Chercher dans les armures dièses
        if (mode, tonic) in SHARP_KEY_SIG:
            num_alts = SHARP_KEY_SIG[(mode, tonic)]
            alt_type = 'sharp'
        # Chercher dans les armures bémols
        elif (mode, tonic) in FLAT_KEY_SIG:
            num_alts = FLAT_KEY_SIG[(mode, tonic)]
            alt_type = 'flat'
    
    # Déterminer quelles notes sont altérées
    # Ordre des altérations dièses: F C G D A E B (pitch_class: 5 0 7 2 9 4 11)
    SHARP_ORDER = [5, 0, 7, 2, 9, 4, 11]
    # Ordre des altérations bémols: B E A D G C F (pitch_class: 11 4 9 2 7 0 5)
    FLAT_ORDER = [11, 4, 9, 2, 7, 0, 5]
    
    # Construire les sets de notes altérées
    sharp_classes = set(SHARP_ORDER[:num_alts]) if alt_type == 'sharp' else set()
    flat_classes = set(FLAT_ORDER[:num_alts]) if alt_type == 'flat' else set()
    
    # ── Calculer l'altération requise ────────────────────────────────────
    # Choisir le nom de note (dièse ou bémol) selon le type d'armure
    if alt_type == 'flat':
        base_name = PITCH_TO_NAME_FLAT[pitch_class]
    else:
        # sharp ou natural : utiliser le mapping dièse
        base_name = PITCH_TO_NAME_SHARP[pitch_class]
    
    # La note de base (base_name) a un degré
    base_degree = NOTE_TO_DEGREE.get(base_name[0], 0)
    
    # Différence entre le pitch désiré et la note de base naturelle
    diff = pitch_class - base_degree  # -1, 0, ou 1
    
    # L'armure altère-t-elle cette note ?
    note_altered_by_key = pitch_class in sharp_classes or pitch_class in flat_classes
    
    # Calculer l'altération VexFlow à appliquer
    if alt_type == 'sharp' and note_altered_by_key:
        # L'armure met un dièse sur cette note
        if diff == 0:
            # Note naturelle désirée → bécarre pour annuler le dièse
            alter_str = ':n'
        elif diff == -1:
            # Note bémol désirée → bémol double (bb + # = naturel, donc bb)
            alter_str = ':bb'
        else:  # diff == 1
            # Note dièse désirée → dièse double
            alter_str = ':x'
    elif alt_type == 'flat' and note_altered_by_key:
        # L'armure met un bémol sur cette note
        if diff == 0:
            # Note naturelle désirée → bécarre pour annuler le bémol
            alter_str = ':n'
        elif diff == 1:
            # Note dièse désirée → dièse (b + # = naturel, donc #)
            alter_str = ':#'
        else:  # diff == -1
            # Note bémol désirée → bémol double
            alter_str = ':bb'
    else:
        # L'armure ne met rien sur cette note
        if diff == 0:
            # Note naturelle → pas d'altération
            alter_str = ''
        elif diff == 1:
            # Note dièse désirée → dièse simple
            alter_str = ':#'
        else:  # diff == -1
            # Note bémol désirée → bémol simple
            alter_str = ':b'
    
    return f"{base_name}/{vexflow_octave}{alter_str}"


def vexflow_key_to_pitch(key: str) -> int:
    """'c#/4' → MIDI pitch (gère aussi les altérations: 'b/4:n', 'f#/4:#', etc.)"""
    NOTE_ST = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
    parts = key.split('/')
    if len(parts) != 2:
        return 60
    note_str = parts[0].lower()
    # Extraire uniquement le nombre de l'octave (ignorer les altérations comme :n, :#, :b, :x, :bb)
    octave_str = parts[1].split(':')[0]  # '4:n' → '4', '4:#' → '4'
    try:
        octave = int(octave_str)
    except ValueError:
        return 60
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
        # note_events est un tuple (onset, pitch, duration, velocity)
        # event[0] = onset, event[1] = pitch, event[2] = duration, event[3] = velocity
        pitch = int(event[1])  # event[1] = pitch (MIDI note number)
        duration = float(event[2]) if len(event) > 2 else 1.0  # event[2] = duration
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
        9: 'Cm', 4: 'Gm', 11: 'Dm', 6: 'Am', 1: 'Em', 8: 'Bm', 3: 'F#m',
        2: 'Fm', 7: 'Bbm', 0: 'Ebm', 5: 'Abm', 10: 'Dbm'
    }

    for shift in range(12):
        shifted_hist = np.roll(histogram, -shift)

        corr_maj = np.correlate(shifted_hist, major_profile)[0]
        corr_min = np.correlate(shifted_hist, minor_profile)[0]

        # CORRECTION : comparer le MEILLEUR des deux modes POUR CE SHIFT,
        # puis mettre à jour uniquement si ce meilleur score bat le global.
        # Bug précédent : corr_maj et corr_min étaient comparés séparément,
        # permettant un mismatch shift+mode (ex: shift=G mais mode mineur).
        if corr_maj >= corr_min:
            if corr_maj > best_correlation:
                best_correlation = corr_maj
                best_key = major_keys.get(shift, 'C')
        else:
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


# ── [P4] Helpers pour les ornements dans le JSON ───────────────────────────

def _build_ornaments_json(
    ornament_result: 'OrnamentResult', 
    beats_per_measure: float
) -> Dict[str, Any]:
    """
    Construit la section 'ornaments' du JSON de score (Phase 4).
    
    Retourne un dict avec :
      - appoggiaturas: liste de grace notes avec pitch, target, measure
      - trills: liste de symboles tr avec startBeat, endBeat, measure
      - dottedRhythms: liste de rythmes pointés détectés
      - summary: compteurs par type
    """
    appoggiaturas = []
    for app in ornament_result.appoggiaturas:
        measure_num = int(app.beat_position / beats_per_measure) + 1 if beats_per_measure > 0 else 1
        appoggiaturas.append({
            'type': 'graceNote',
            'pitch': app.grace_note_pitch,
            'targetPitch': app.target_pitch,
            'beatPosition': round(app.beat_position, 3),
            'duration': round(app.duration_beats, 3),
            'measure': measure_num,
            'musicxml': '<grace slash="true"><note><pitch><step>C</step><alter>0</alter></pitch><duration>0</duration></note></grace>',
        })
    
    trills = []
    for tr in ornament_result.trills:
        measure_num = int(tr.start_beat / beats_per_measure) + 1 if beats_per_measure > 0 else 1
        trills.append({
            'type': 'trill',
            'startBeat': round(tr.start_beat, 3),
            'endBeat': round(tr.end_beat, 3),
            'primaryPitch': tr.primary_pitch,
            'auxiliaryPitch': tr.auxiliary_pitch,
            'noteCount': tr.note_count,
            'measure': measure_num,
            'musicxml': f'<ornaments><trill-mark>{tr.start_beat:.2f}-{tr.end_beat:.2f}</trill-mark></ornaments>',
        })
    
    dotted_rhythms = []
    for dr in ornament_result.dotted_rhythms:
        measure_num = int(dr.beat_position / beats_per_measure) + 1 if beats_per_measure > 0 else 1
        dotted_rhythms.append({
            'type': 'dottedRhythm',
            'noteIndex': dr.note_index,
            'beatPosition': round(dr.beat_position, 3),
            'duration': round(dr.duration_beats, 3),
            'dottedRatio': dr.dotted_ratio,
            'measure': measure_num,
        })
        
    arpeggios = []
    for arp in getattr(ornament_result, 'arpeggios', []):
        measure_num = int(arp.beat_position / beats_per_measure) + 1 if beats_per_measure > 0 else 1
        arpeggios.append({
            'type': 'arpeggio',
            'startBeat': round(arp.beat_position, 3),
            'totalSpanBeats': round(arp.total_span_beats, 3),
            'noteCount': arp.note_count,
            'measure': measure_num,
        })
    
    return {
        'appoggiaturas': appoggiaturas,
        'trills': trills,
        'dottedRhythms': dotted_rhythms,
        'arpeggios': arpeggios,
        'summary': {
            'appoggiaturaCount': len(appoggiaturas),
            'trillCount': len(trills),
            'dottedRhythmCount': len(dotted_rhythms),
            'arpeggioCount': len(arpeggios),
            'totalOrnamentedNotes': len(ornament_result.note_ornaments),
        }
    }


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