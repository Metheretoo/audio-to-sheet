import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def export_musicxml(score_data: Dict[str, Any], output_path: str):
    """
    Exporte le ScoreData en MusicXML en utilisant music21.
    Gère les portées multiples, armures, pédales, symboles d'accords.
    """
    import music21
    from music21 import stream, note, chord, meter, tempo, key, harmony, spanner, clef

    # Création du score et des 2 parties (main droite, main gauche)
    s = stream.Score()
    
    part_treble = stream.Part()
    part_treble.partName = "Piano (Treble)"
    part_treble.insert(0, clef.TrebleClef())
    
    part_bass = stream.Part()
    part_bass.partName = "Piano (Bass)"
    part_bass.insert(0, clef.BassClef())

    # Métadonnées
    s.insert(0, music21.metadata.Metadata())
    s.metadata.title = score_data.get("title", "Transcription V4")
    
    global_tempo = score_data.get("tempo", 120)
    ts_num, ts_den = score_data.get("timeSignature", [4, 4])
    global_ts = meter.TimeSignature(f"{ts_num}/{ts_den}")
    global_key = key.Key(score_data.get("keySignature", "C"))
    
    part_treble.insert(0, global_ts)
    part_bass.insert(0, global_ts)
    part_treble.insert(0, global_key)
    part_bass.insert(0, global_key)
    part_treble.insert(0, tempo.MetronomeMark(number=global_tempo))

    # Dictionnaires pour gérer les changements d'armure par mesure (0-indexé)
    key_changes = {}
    for kc in score_data.get("keyChanges", []):
        measure_idx = kc.get("measure", 0)
        mode = kc.get("mode", "major")
        root = kc.get("key", "C")
        key_changes[measure_idx] = key.Key(root, mode)

    # Dictionnaires pour les symboles d'accords Jazz (associés à la main droite)
    chord_symbols_map = {}
    for cs in score_data.get("chordSymbols", []):
        m_idx = cs.get("measure", 0)
        chord_symbols_map.setdefault(m_idx, []).append(cs)

    # Fonction utilitaire pour parser une durée VexFlow (approximatif pour musicxml)
    # Dans score_data, la vraie durée en beats est dans 'duration' (float)
    def make_music21_duration(beats: float) -> music21.duration.Duration:
        # 1 beat = noire (quarter length = 1.0) dans music21 par défaut.
        return music21.duration.Duration(quarterLength=beats)

    def vexflow_key_to_pitch(vf_key: str):
        # 'c#/4' -> 'C#4'
        parts = vf_key.split('/')
        if len(parts) == 2:
            return f"{parts[0].upper()}{parts[1]}"
        return "C4"

    # Suivi des pédales : mapping de temps global -> événements de pédale
    # On gérera ça comme un Spanner après avoir construit toutes les mesures.
    # Pour ça, on va aplatir (flat) la partition à la fin et insérer les spanners,
    # ou on peut trouver les objets Note au bon offset.

    # ── Construction des mesures ────────────────────────────
    for m_idx, m_data in enumerate(score_data.get("measures", [])):
        m_num = m_idx + 1
        
        m_treble = stream.Measure(number=m_num)
        m_bass = stream.Measure(number=m_num)
        
        # Changement d'armure éventuel
        if m_idx in key_changes:
            m_treble.insert(0, key_changes[m_idx])
            m_bass.insert(0, key_changes[m_idx])
            
        # Symboles d'accords (ajoutés à la main droite)
        if m_idx in chord_symbols_map:
            for cs in chord_symbols_map[m_idx]:
                sym = cs.get("symbol")
                beat_in_meas = cs.get("beatInMeasure", 0.0)
                try:
                    hc = harmony.ChordSymbol(sym)
                    m_treble.insert(beat_in_meas, hc)
                except:
                    pass # Ignore si format non reconnu par music21
                    
        # Remplissage des notes - Treble
        for item in m_data.get("treble", []):
            dur = make_music21_duration(item.get("duration", 1.0))
            if item.get("isRest", False):
                r = note.Rest(duration=dur)
                m_treble.insert(item.get("startBeat", 0.0), r)
            else:
                pitches = [vexflow_key_to_pitch(k) for k in item.get("keys", [])]
                if len(pitches) == 1:
                    n = note.Note(pitches[0], duration=dur)
                else:
                    n = chord.Chord(pitches, duration=dur)
                m_treble.insert(item.get("startBeat", 0.0), n)
                
        # Remplissage des notes - Bass
        for item in m_data.get("bass", []):
            dur = make_music21_duration(item.get("duration", 1.0))
            if item.get("isRest", False):
                r = note.Rest(duration=dur)
                m_bass.insert(item.get("startBeat", 0.0), r)
            else:
                pitches = [vexflow_key_to_pitch(k) for k in item.get("keys", [])]
                if len(pitches) == 1:
                    n = note.Note(pitches[0], duration=dur)
                else:
                    n = chord.Chord(pitches, duration=dur)
                m_bass.insert(item.get("startBeat", 0.0), n)
                
        part_treble.append(m_treble)
        part_bass.append(m_bass)

    # ── Gestion des Pédales via SustainPedal (Spanner) ──────
    # Les pédales sont en beats absolus.
    # On va utiliser le flat_treble pour trouver les éléments aux offsets de début/fin.
    flat_treble = part_treble.flatten()
    for pedal in score_data.get("pedalMarkings", []):
        start_beat = pedal.get("startBeat", 0.0)
        end_beat = pedal.get("endBeat", 0.0)
        
        if end_beat <= start_beat:
            continue
            
        # Insérer manuellement la balise SustainPedal
        sp = spanner.SustainPedal()
        
        # Trouver la note/silence au (ou proche du) start_beat
        start_elems = flat_treble.getElementsByOffset(start_beat, start_beat + 0.5)
        end_elems = flat_treble.getElementsByOffset(end_beat - 0.5, end_beat + 0.5)
        
        if len(start_elems) > 0 and len(end_elems) > 0:
            sp.addSpannedElements(start_elems[0], end_elems[-1])
            part_treble.insert(0, sp)

    s.insert(0, part_treble)
    s.insert(0, part_bass)
    
    # ── Écriture du fichier ─────────────────────────────────
    # Pour s'assurer que music21 lie bien les 2 portées d'un piano
    staff_group = music21.layout.StaffGroup([part_treble, part_bass], name='Piano', abbreviation='Pno.', symbol='brace')
    s.insert(0, staff_group)

    s.write('musicxml', fp=output_path)
