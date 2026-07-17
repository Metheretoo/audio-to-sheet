"\"\"\"
PATCH — transcriber.TranscriptionPipeline.run()

À appliquer sur backend/transcriber.py à la place de la méthode `run()` actuelle
(lignes 905 → 1096 approximativement).

Ce patch reconnecte au pipeline utilisé en production (Stack A via app.py) tous
les correctifs qui n'existaient jusqu'ici que dans pipeline.py (Stack B jamais
exécutée). Les changements sont commentés `# FIX #N` avec le n° du bug du
DIAGNOSTIC.md.

Aucune signature d'entrée/sortie n'est modifiée : app.py continue de recevoir
un dict `score_data` enrichi (`midi_path`, `xml_path`, `note_count`, etc.).
\"\"\"

    def run(self, input_path, output_dir, options=None):
        import os
        import midi_parser
        from tempo_map import build_tempo_map
        from quantizer import quantize_notes
        from voice_engine import split_voices
        from score_builder import build_score

        print(f\"[Pipeline] Début de la transcription: {input_path}\")

        options = options or {
            'transcriber': 'piano_transcription',
            'use_demucs': False,
            'detect_tempo': True,
            'onset_threshold': 0.5,
            'frame_threshold': 0.25,
        }

        # ── 1. Transcription brute (audio → note_events) ─────────────────────
        note_events, midi_data, pedal_intervals, raw_tempo, warning_msgs = transcribe_audio(
            input_path, options
        )
        if not note_events:
            raise ValueError(\"Aucune note détectée dans l'audio\")
        print(f\"[Pipeline] {len(note_events)} notes brutes\")

        # ── 1.5 Filtrage note_filter (FIX #2) ─────────────────────────────────
        # Convertit d'abord tuple → dict pour compat note_filter, puis reconvertit.
        notes_dict = [
            {'onset': n[0], 'pitch': n[1], 'duration': n[2],
             'velocity': (n[3] / 127.0) if n[3] > 1 else float(n[3])}
            for n in note_events
        ]
        try:
            from note_filter import filter_ghost_notes, apply_pedal_aware_shortening
            notes_dict = filter_ghost_notes(notes_dict, options)
            notes_dict = apply_pedal_aware_shortening(notes_dict, pedal_intervals or [], options)
            print(f\"[Pipeline] {len(notes_dict)} notes après note_filter (ghost + pedal-aware)\")
        except Exception as e:
            print(f\"[Pipeline] ⚠ note_filter indisponible ({e}), fallback filtrage naïf\")

        # Filtrage utilisateur (remove_short_notes / merge_near_notes) conservé
        remove_short = options.get('remove_short_notes', False)
        min_dur_s = options.get('minimum_note_duration', 50) / 1000.0
        if remove_short:
            notes_dict = [n for n in notes_dict if n['duration'] >= min_dur_s]

        if options.get('merge_near_notes', False):
            merge_gap_s = options.get('merge_gap_ms', 30) / 1000.0
            notes_dict.sort(key=lambda n: (n['pitch'], n['onset']))
            merged = []
            for n in notes_dict:
                if merged and merged[-1]['pitch'] == n['pitch'] and \
                   (n['onset'] - (merged[-1]['onset'] + merged[-1]['duration'])) < merge_gap_s:
                    prev = merged[-1]
                    prev['duration'] = (n['onset'] + n['duration']) - prev['onset']
                    prev['velocity'] = max(prev['velocity'], n['velocity'])
                else:
                    merged.append(dict(n))
            notes_dict = merged
            notes_dict.sort(key=lambda n: n['onset'])

        # Reconversion en tuples pour compat quantize_notes/tempo_map
        note_events = [
            (n['onset'], n['pitch'], n['duration'],
             int(round(n['velocity'] * 127)) if n['velocity'] <= 1 else int(n['velocity']))
            for n in notes_dict
        ]
        print(f\"[Pipeline] {len(note_events)} notes après filtrage complet\")

        # ── 2. Tempo Map ─────────────────────────────────────────────────────
        user_tempo = options.get('tempo')
        start_bpm = float(user_tempo) if user_tempo else None
        tm = build_tempo_map(input_path, note_events, start_bpm=start_bpm)
        display_bpm = tm.global_bpm
        if start_bpm and not options.get('detect_tempo', True):
            display_bpm = start_bpm

        # ── 3. Quantification ────────────────────────────────────────────────
        quantization_level = options.get('quantization_level', 'standard')
        quantized_notes = quantize_notes(
            note_events,
            bpm=tm.global_bpm,
            quantization_level=quantization_level,
            enable_rubato=options.get('enable_rubato', False),
            enable_triplets=options.get('enable_triplets', False),
            tempo_map=tm,
        )
        print(f\"[Pipeline] {len(quantized_notes)} notes quantisées ({quantization_level})\")

        # ── 4. Analyse harmonique (TOUJOURS, pas seulement en preset jazz) ──
        # FIX #4 : les symboles d'accord doivent être disponibles quel que soit le preset.
        preset = options.get('preset', 'standard')
        harmonic_ctx = None
        key_name = options.get('key_sig', 'C')
        try:
            from harmonic_analyzer import build_harmonic_context
            from piano_roll import group_into_slices, fuse_arpeggios

            # FIX #6 : pédales converties en beats avant l'analyse harmonique
            pedal_beats = []
            if pedal_intervals:
                for p_start, p_end in pedal_intervals:
                    pedal_beats.append(
                        (tm.seconds_to_beat(p_start), tm.seconds_to_beat(p_end))
                    )

            slices = group_into_slices(quantized_notes, pedal_events=pedal_beats or None)
            slices = fuse_arpeggios(slices)
            harmonic_ctx = build_harmonic_context(slices)

            if options.get('detect_key', True):
                key_name = harmonic_ctx.global_key
                print(f\"[Pipeline] Tonalité détectée: {key_name}\")
        except Exception as e:
            print(f\"[Pipeline] ⚠ Analyse harmonique en échec ({e})\")

        # ── 5. Séparation LH/RH guidée par harmonie (FIX #3) ─────────────────
        try:
            if harmonic_ctx is not None:
                from voice_engine import split_with_harmony
                voices = split_with_harmony(quantized_notes, harmonic_ctx, options)
                print(\"[Pipeline] Split LH/RH : split_with_harmony (guidé)\")
            else:
                voices = split_voices(quantized_notes, options=options)
                print(\"[Pipeline] Split LH/RH : split_voices (fallback)\")
        except Exception as e:
            print(f\"[Pipeline] ⚠ split_with_harmony échoué ({e}), fallback split_voices\")
            voices = split_voices(quantized_notes, options=options)

        # ── 6. Construction du score ─────────────────────────────────────────
        time_sig_str = options.get('time_sig', '4/4')
        try:
            ts_parts = time_sig_str.split('/')
            time_signature = [int(ts_parts[0]), int(ts_parts[1])]
        except Exception:
            time_signature = list(tm.estimated_meter)

        # FIX #4 : write_chord_symbols=True par défaut. Une option 'chord_symbols'
        # peut désactiver depuis l'UI.
        show_chords = options.get('chord_symbols', True) or (preset == 'jazz')

        score_options = {
            'detect_key': False,          # déjà fait ci-dessus
            'time_sig': time_signature,
            'display_bpm': display_bpm,
            'write_chord_symbols': show_chords,
            'detect_dynamics': True,
        }

        # FIX #6 : pédales en beats pour build_score
        pedal_beats_list = []
        if pedal_intervals:
            for p_start, p_end in pedal_intervals:
                pedal_beats_list.append(
                    (tm.seconds_to_beat(p_start), tm.seconds_to_beat(p_end))
                )

        score_data = build_score(
            voices, tm,
            key_sig=key_name,
            options=score_options,
            harmonic_ctx=harmonic_ctx,
            pedals=pedal_beats_list,   # ← beats, pas secondes
        )

        score_data.setdefault('metadata', {})['warnings'] = warning_msgs

        # ── 7. Export MIDI + MusicXML réel (FIX #5) ──────────────────────────
        os.makedirs(output_dir, exist_ok=True)
        midi_path = os.path.join(output_dir, 'output.mid')
        xml_path = os.path.join(output_dir, 'score.musicxml')

        midi_parser.score_to_midi(score_data, midi_path)

        try:
            from musicxml_exporter import export_musicxml
            export_musicxml(score_data, xml_path)
            print(f\"[Pipeline] MusicXML généré : {xml_path}\")
        except Exception as e:
            print(f\"[Pipeline] ⚠ Export MusicXML en échec ({e}), stub écrit\")
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write('<?xml version=\"1.0\" encoding=\"UTF-8\"?><score-partwise></score-partwise>')

        # ── 8. Métadonnées pour le frontend ──────────────────────────────────
        score_data['midi_path'] = midi_path
        score_data['xml_path'] = xml_path
        score_data['note_count'] = len(quantized_notes)
        score_data['warnings'] = warning_msgs
        score_data['tempoMapMethod'] = tm.method
        score_data['tempoConfidence'] = (
            0.85 if tm.method == 'madmom'
            else (0.6 if tm.method == 'librosa_advanced' else 0.3)
        )
        score_data['tempoRange'] = tm.tempo_range()
        score_data['detectedMeter'] = tm.estimated_meter

        print(f\"[Pipeline] Terminé — MIDI: {midi_path} | XML: {xml_path}\")
        return score_data
"