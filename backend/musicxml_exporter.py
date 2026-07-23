import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def _key_to_fifths(key):
    """
    Conversion tonalité MusicXML.
    """
    table = {
        "C": 0,
        "G": 1,
        "D": 2,
        "A": 3,
        "E": 4,
        "B": 5,
        "F#": 6,
        "C#": 7,

        "F": -1,
        "Bb": -2,
        "Eb": -3,
        "Ab": -4,
        "Db": -5,
        "Gb": -6,
        "Cb": -7,
    }

    return table.get(key.replace("m", ""), 0)

def _escape_xml(text: str) -> str:
    """Échappe les caractères XML."""
    s = str(text)
    s = s.replace('&', chr(38) + 'amp;')
    s = s.replace('<', chr(38) + 'lt;')
    s = s.replace('>', chr(38) + 'gt;')
    s = s.replace('"', chr(34) + 'quot;')
    s = s.replace("'", chr(39) + 'apos;')
    return s


def _duration_to_musicxml(quarter_length: float) -> str:
    """Convertit quarterLength en duration MusicXML (entier).
    
    MusicXML utilise des notes entières :
    - whole = 4 beats, half = 2 beats, quarter = 1 beat, eighth = 0.5, etc.
    """
    # On multiplie par un facteur pour garder la précision
    # puis on arrondit pour éviter les floats
    factor = 16  # précision jusqu'à 16ème de note
    duration = int(round(quarter_length * factor))
    return str(max(1, duration))


def _pitch_to_xml(note_obj) -> str:
    """Convertit une note/chord music21 en éléments pitch XML."""
    # On utilise la représentation standard
    steps = {
        'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F', 'G': 'G', 'A': 'A', 'B': 'B',
    }
    alter = 0
    step = 'C'
    octave = 4
    
    if hasattr(note_obj, 'pitch'):
        # C'est une note simple
        p = note_obj.pitch
        step = p.step
        alter = p.alter
        octave = p.octave
    elif hasattr(note_obj, 'pitches'):
        # C'est un accord - on prend la première note
        p = note_obj.pitches[0]
        step = p.step
        alter = p.alter
        octave = p.octave
    
    parts = [f"<step>{steps.get(step, step)}</step>"]
    if alter:
        parts.append(f"<alter>{alter}</alter>")
    parts.append(f"<octave>{octave}</octave>")
    return "".join(parts)


def export_musicxml(score_data: Dict[str, Any], output_path: str):
    """
    Exporte le ScoreData en MusicXML en construisant le XML manuellement.
    Cette approche évite les problèmes de music21 avec les références d'objets.
    """
    title = _escape_xml(score_data.get("title", "Transcription V4"))
    tempo = score_data.get("tempo", 120)
    ts_num, ts_den = score_data.get("timeSignature", [4, 4])
    key_sig = score_data.get("keySignature", "C")
    measures = score_data.get("measures", [])
    
    # Mapping des touches pour la tonalité
    key_to_mode = {
        'C': 'major', 'G': 'major', 'D': 'major', 'A': 'major',
        'E': 'major', 'B': 'major', 'F#': 'major', 'Db': 'major',
        'Gb': 'major', 'Ab': 'major', 'Eb': 'major', 'Bb': 'major',
        'F': 'major', 'Am': 'minor', 'Em': 'minor', 'Bm': 'minor',
        'F#m': 'minor', 'C#m': 'minor', 'G#m': 'minor', 'D#m': 'minor',
        'Bbm': 'minor', 'Ebm': 'minor', 'Abm': 'minor', 'Dbm': 'minor',
        'Gm': 'minor', 'Dm': 'minor', 'Am': 'minor',
    }
    key_mode = key_to_mode.get(key_sig, 'major')
    
    # Changements d'armure par mesure
    key_changes = {}
    for kc in score_data.get("keyChanges", []):
        measure_idx = kc.get("measure", 0)
        mode = kc.get("mode", "major")
        root = kc.get("key", "C")
        key_changes[measure_idx] = (root, mode)
    
    # Symboles d'accords par mesure
    chord_symbols_map = {}
    for cs in score_data.get("chordSymbols", []):
        m_idx = cs.get("measure", 0)
        chord_symbols_map.setdefault(m_idx, []).append(cs)
    
    # Pédales par mesure
    pedal_by_measure = {}
    for pedal in score_data.get("pedalMarkings", []):
        start_beat = pedal.get("startBeat", 0.0)
        pedal_type = pedal.get("type", "start")
        # Assigner à la mesure approximative
        for m_idx in range(len(measures)):
            # Estimer l'offset de la mesure
            m_start = sum(
                max(
                    sum(i.get("duration", 1.0) for i in measures[j].get("treble", [])),
                    sum(i.get("duration", 1.0) for i in measures[j].get("bass", []))
                )
                for j in range(m_idx)
            )
            m_end = m_start + max(
                sum(i.get("duration", 1.0) for i in measures[m_idx].get("treble", [])),
                sum(i.get("duration", 1.0) for i in measures[m_idx].get("bass", []))
            )
            if m_start <= start_beat < m_end:
                pedal_by_measure.setdefault(m_idx, []).append(pedal_type)
                break
    
    # Construction du XML MusicXML
    xml_parts = []
    xml_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_parts.append('<score-partwise>')
    xml_parts.append('  <movement-title>' + title + '</movement-title>')
    xml_parts.append('  <part-list>')
    xml_parts.append('    <score-part id="P1-piano">')
    xml_parts.append('      <part-name>Piano</part-name>')
    xml_parts.append('      <score-instrument id="P1-i1">')
    xml_parts.append('        <instrument-name>Piano</instrument-name>')
    xml_parts.append('      </score-instrument>')
    xml_parts.append('    </score-part>')
    xml_parts.append('  </part-list>')
    xml_parts.append('  <part id="P1-piano">')
    
    for m_idx, m_data in enumerate(measures):
        m_num = m_idx + 1
        
        xml_parts.append(f'    <measure number="{m_num}">')
        
        # Première mesure : clefs, armure, signature de temps
        if m_idx == 0:
            # Clef de sol
            xml_parts.append('      <attributes>')
            xml_parts.append('        <divisions>' + _duration_to_musicxml(1.0) + '</divisions>')
            fifths = _key_to_fifths(key_sig)

            xml_parts.append('        <key>')
            xml_parts.append(f'          <fifths>{fifths}</fifths>')
            xml_parts.append(f'          <mode>{key_mode}</mode>')
            xml_parts.append('        </key>')
            xml_parts.append('        <time><beats>' + str(ts_num) + '</beats><beat-type>' + str(ts_den) + '</beat-type></time>')
            xml_parts.append('        <clef>')
            xml_parts.append('          <sign>G</sign>')
            xml_parts.append('          <line>2</line>')
            xml_parts.append('        </clef>')
            xml_parts.append('      </attributes>')
            # Clef de fa pour la main gauche (partie basse)
            xml_parts.append('      <attributes>')
            xml_parts.append('        <clef>')
            xml_parts.append('          <sign>F</sign>')
            xml_parts.append('          <line>4</line>')
            xml_parts.append('        </clef>')
            xml_parts.append('      </attributes>')
        
        # Changement d'armure (uniquement si la tonalité DIFFÈRE de la mesure précédente)
        if m_idx in key_changes:
            root, mode = key_changes[m_idx]
            # Ne pas ajouter si c'est le même key/fifths que l'armure initiale (m_idx == 0)
            # ou identique à la mesure précédente
            prev_key = key_changes.get(m_idx - 1, (None, None))[0] if m_idx > 0 else key_sig
            if root == prev_key:
                pass  # même tonalité que mesure précédente → ne pas dupliquer
            else:
                fifths = _key_to_fifths(root)
                xml_parts.append('      <attributes>')
                xml_parts.append('        <key>')
                xml_parts.append(f'          <fifths>{fifths}</fifths>')
                xml_parts.append(f'          <mode>{mode}</mode>')
                xml_parts.append('        </key>')
                xml_parts.append('      </attributes>')
        
        # Pédales
        if m_idx in pedal_by_measure:
            for pt in pedal_by_measure[m_idx]:
                if pt == "start":
                    xml_parts.append('      <direction><direction-type><ped type="start"/></direction-type></direction>')
                else:
                    xml_parts.append('      <direction><direction-type><ped type="stop"/></direction-type></direction>')
        
        # Symboles d'accords
        if m_idx in chord_symbols_map:
            for cs in chord_symbols_map[m_idx]:
                sym = cs.get("symbol", "")
                beat = cs.get("beatInMeasure", 0.0)
                # Parser le symbole d'accord
                root_map = {'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F', 'G': 'G', 'A': 'A', 'B': 'B',
                           'Db': 'Db', 'Eb': 'Eb', 'Gb': 'Gb', 'Ab': 'Ab', 'Bb': 'Bb',
                           'F#': 'F#', 'G#': 'G#', 'A#': 'A#', 'Cb': 'Cb', 'B#': 'B#'}
                chord_type = 'maj7'
                root_note = 'C'
                for rk, rv in root_map.items():
                    if sym.startswith(rk):
                        root_note = rv
                        chord_type = sym[len(rk):] or 'maj7'
                        break
                xml_parts.append(f'      <harmony default-y="40">')
                xml_parts.append(f'        <root><root-step>{root_note}</root-step></root>')
                xml_parts.append(f'        <kind text="">{chord_type}</kind>')
                xml_parts.append(f'      </harmony>')
        
        # Notes treble (main droite)
        treble_offset = 0
        for item in m_data.get("treble", []):
            duration = item.get("duration", 1.0)
            start_beat = item.get("startBeat", 0.0)
            is_rest = item.get("isRest", False)
            
            # Division en sous-mesures si nécessaire
            offset = treble_offset
            notes_to_add = [item]
            if is_rest:
                xml_parts.append(f'      <note default-y="-100">')
                xml_parts.append(f'        <rest/>')
                xml_parts.append(f'        <duration>' + _duration_to_musicxml(duration) + '</duration>')
                xml_parts.append(f'        <voice>1</voice>')
                xml_parts.append(f'        <type>' + _duration_name(duration) + '</type>')
                xml_parts.append(f'      </note>')
            else:
                pitches = item.get("keys", [])
                for pitch_str in pitches:
                    parts = pitch_str.split('/')
                    step_char = parts[0][0].upper() if parts[0] else 'C'
                    octave = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 4
                    alter = 0
                    if len(parts[0]) > 1:
                        if parts[0][-1] == '#':
                            alter = 1
                        elif parts[0][-1] == 'b':
                            alter = -1
                    
                    xml_parts.append(f'      <note>')
                    xml_parts.append(f'        <pitch>')
                    xml_parts.append(f'          <step>{step_char}</step>')
                    if alter:
                        xml_parts.append(f'          <alter>{alter}</alter>')
                    xml_parts.append(f'          <octave>{octave}</octave>')
                    xml_parts.append(f'        </pitch>')
                    xml_parts.append(f'        <duration>' + _duration_to_musicxml(duration) + '</duration>')
                    xml_parts.append(f'        <offset>' + _duration_to_musicxml(start_beat) + '</offset>')
                    xml_parts.append(f'        <voice>1</voice>')
                    xml_parts.append(f'        <type>' + _duration_name(duration) + '</type>')
                    xml_parts.append(f'      </note>')
            
            treble_offset += duration
        
        # Notes bass (main gauche)
        bass_offset = 0
        for item in m_data.get("bass", []):
            duration = item.get("duration", 1.0)
            start_beat = item.get("startBeat", 0.0)
            is_rest = item.get("isRest", False)
            
            if is_rest:
                xml_parts.append(f'      <note default-y="-150">')
                xml_parts.append(f'        <rest/>')
                xml_parts.append(f'        <duration>' + _duration_to_musicxml(duration) + '</duration>')
                xml_parts.append(f'        <voice>2</voice>')
                xml_parts.append(f'        <type>' + _duration_name(duration) + '</type>')
                xml_parts.append(f'      </note>')
            else:
                pitches = item.get("keys", [])
                for pitch_str in pitches:
                    parts = pitch_str.split('/')
                    step_char = parts[0][0].upper() if parts[0] else 'C'
                    # Conversion octave VexFlow → octave MusicXML (scientifique)
                    # VexFlow : c/3 = MIDI 60 (C4 = Do central)
                    # MusicXML : octave 4 = C4 (Do central)
                    # Donc : musicxml_octave = vexflow_octave + 1
                    vexflow_oct = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
                    octave = vexflow_oct + 1
                    alter = 0
                    if len(parts[0]) > 1:
                        if parts[0][-1] == '#':
                            alter = 1
                        elif parts[0][-1] == 'b':
                            alter = -1
                    
                    xml_parts.append(f'      <note>')
                    xml_parts.append(f'        <pitch>')
                    xml_parts.append(f'          <step>{step_char}</step>')
                    if alter:
                        xml_parts.append(f'          <alter>{alter}</alter>')
                    xml_parts.append(f'          <octave>{octave}</octave>')
                    xml_parts.append(f'        </pitch>')
                    xml_parts.append(f'        <duration>' + _duration_to_musicxml(duration) + '</duration>')
                    xml_parts.append(f'        <offset>' + _duration_to_musicxml(start_beat) + '</offset>')
                    xml_parts.append(f'        <voice>2</voice>')
                    xml_parts.append(f'        <type>' + _duration_name(duration) + '</type>')
                    xml_parts.append(f'      </note>')
            
            bass_offset += duration
        
        xml_parts.append('    </measure>')
    
    xml_parts.append('  </part>')
    xml_parts.append('</score-partwise>')
    
    # Écriture du fichier
    xml_content = '\n'.join(xml_parts)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(xml_content)
    
    logger.info(f"[MusicXML] {len(measures)} mesures exportées vers {output_path}")


def _duration_name(quarter_length: float) -> str:
    """Convertit quarterLength en nom de note MusicXML."""
    if quarter_length <= 0:
        return '128th'
    if quarter_length >= 4:
        return 'whole'
    if quarter_length >= 2:
        return 'half'
    if quarter_length >= 1:
        return 'quarter'
    if quarter_length >= 0.5:
        return 'eighth'
    if quarter_length >= 0.25:
        return '16th'
    if quarter_length >= 0.125:
        return '32nd'
    return '64th'