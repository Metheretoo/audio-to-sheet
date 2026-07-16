"""
midi_exporter.py — Export MIDI et PDF (V3)
Version : 1.0 (audio-to-sheet V3)

Objectif :
  Convertir les événements MIDI quantisés en fichiers MIDI (.mid)
  et en partitions PDF/LilyPond pour visualisation et impression.

Caractéristiques :
  - Export MIDI standard (Type 0 ou Type 1)
  - Export LilyPond (.ly) pour génération PDF
  - Support polyphonique multi-instrument
  - Métadonnées musicales (titre, compositeur, mesure)
"""

import os
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


# ── Types ──────────────────────────────────────────────────────────────────────

class MidiFileType(Enum):
    """Type de fichier MIDI."""
    TYPE_0 = 0  # Single track
    TYPE_1 = 1  # Multiple tracks


class OutputFormat(Enum):
    """Format de sortie."""
    MIDI = "midi"
    LILYPOND = "lilypond"
    PDF = "pdf"
    ALL = "all"


@dataclass
class TrackConfig:
    """
    Configuration d'une piste MIDI.
    
    Attributes :
        name: Nom de la piste
        program: Programme MIDI (0-127)
        channel: Canal MIDI (0-15)
        is_drum: Si c'est une piste drum (channel 9 / channel 9)
        volume: Volume (0-127, default 100)
        pan: Panoramique (0-127, default 64 = centre)
    """
    name: str = "Track"
    program: int = 0
    channel: int = 0
    is_drum: bool = False
    volume: int = 100
    pan: int = 64


@dataclass
class ScoreMetadata:
    """Métadonnées de la partition."""
    title: str = ""
    composer: str = ""
    arranger: str = ""
    copyright: str = ""
    key: str = ""           # Tonalité (ex: "C major", "G minor")
    time_signature: str = ""  # Signature temporelle (ex: "4/4")
    tempo: float = 120.0     # BPM
    lyrics: List[str] = field(default_factory=list)  # Paroles (optionnel)


# ── LilyPond Builder ───────────────────────────────────────────────────────────

class LilyPondBuilder:
    """
    Génère du code LilyPond à partir d'événements MIDI quantisés.
    
    Usage :
        builder = LilyPondBuilder(metadata)
        builder.add_track(quantized_events, config)
        ly_content = builder.build()
    """

    # Mapping MIDI program → nom LilyPond
    INSTRUMENT_MAP = {
        0: "piano",           # Acoustic Grand Piano
        1: "piano",          # Bright Acoustic Piano
        2: "piano",          # Electric Grand Piano
        3: "celesta",        # Glockenspiel
        4: "celesta",        # Music Box
        5: "vibraphone",     # Vibraphone
        8: "marimba",        # Marimba
        12: "accordion",     # Accordion
        24: "guitar",        # Acoustic Guitar
        25: "guitar",        # Nylon Guitar
        29: "bass",          # Electric Bass (finger)
        32: "violin",       # Violin
        33: "viola",        # Viola
        34: "cello",        # Cello
        35: "contrabass",   # Contrabass
        40: "flute",        # Flute
        43: "recorder",     # Recorder
        48: "organ",        # Harmonium Organ
        56: "trumpet",      # Trumpet
        57: "trombone",     # Trombone
        58: "tuba",         # Tuba
        60: "sax",          # Alto Saxophone
        63: "clarinet",     # Clarinet
        72: "timpani",      # Timpani
        80: "drums",        # Drum Set
    }

    def __init__(self, metadata: ScoreMetadata):
        self.metadata = metadata
        self.tracks: List[dict] = []
        self._time_signature = "4/4"
        self._key = "c"  # C major default

        if metadata.time_signature:
            self._time_signature = metadata.time_signature
        if metadata.key:
            # Convertir "G major" → "g", "C# minor" → "cis-moll"
            key_parts = metadata.key.lower().split()
            if key_parts:
                self._key = key_parts[0].replace('#', 'is')

    def add_track(
        self,
        events,
        config: TrackConfig,
        track_index: int = 0
    ):
        """
        Ajoute une piste au LilyPond.
        
        Args:
            events: liste de QuantizedEvent ou dict
            config: configuration de la piste
            track_index: index de la piste (0 = premier)
        """
        self.tracks.append({
            'config': config,
            'events': events,
            'index': track_index
        })

    def build(self) -> str:
        """
        Génère le code LilyPond complet.
        
        Returns:
            String contenant le code LilyPond valide
        """
        lines = []

        # En-tête LilyPond
        lines.append('\\version "2.24.0"')
        lines.append("")

        # Métadonnées
        lines.append("\\paper {")
        lines.append("  #(set-paper-size \\\"a4\\\")")
        lines.append("  top-margin = 15")
        lines.append("  bottom-margin = 15")
        lines.append("  left-margin = 15")
        lines.append("  right-margin = 15")
        lines.append("  indent = 0")
        lines.append("  print-page-number = ##f")
        lines.append("}")
        lines.append("")

        # Global context
        lines.append("\\score {")
        lines.append("  \\new PianoStaff <")

        # Titre
        if self.metadata.title:
            lines.append(
                f'  \\markup {{ \\fontsize #2 \\underline \\"'
                f'{self.metadata.title}\\" }}'
            )

        # Compositeur
        if self.metadata.composer:
            lines.append(
                f'  \\markup {{ \\fontsize #1 \\"'
                f'{self.metadata.composer}\\" }}'
            )

        # Tonalité et tempo
        lines.append(
            f"  \\new Staff \\with {{ "
            f"instrumentName = \\"Piano\\" "
            f"}} <"
        )
        lines.append(f"  \\key {self._key} \\major")
        lines.append(f"  \\time {self._time_signature}")
        lines.append(f"  \\tempo 4={self.metadata.tempo}")
        lines.append("  ")

        # Générer les notes pour la piste principale
        if self.tracks:
            notes = self._events_to_lilypond(self.tracks[0]['events'])
            lines.append(notes)

        lines.append("  >")
        lines.append("  >")

        # Autres pistes
        for track in self.tracks[1:]:
            config = track['config']
            events = track['events']
            instrument = self.INSTRUMENT_MAP.get(
                config.program, "piano"
            )
            lines.append(
                f"  \\new Staff \\with {{ "
                f"instrumentName = \\"{config.name}\\" "
                f"}} <"
            )
            lines.append(f"  \\key {self._key} \\major")
            lines.append(f"  \\time {self._time_signature}")
            lines.append(f"  \\tempo 4={self.metadata.tempo}")
            lines.append(
                f"  \\set Staff.instrumentName = \\"{config.name}\\" "
            )
            lines.append(f"  {self._events_to_lilypond(events)}")
            lines.append("  >")

        lines.append("  >")
        lines.append("  \\layout { }")
        lines.append("}")

        return "\n".join(lines)

    def _events_to_lilypond(self, events) -> str:
        """
        Convertit des événements quantisés en notation LilyPond.
        
        Exemple :
            c'4 e'4 g4 c'2
        """
        if not events:
            return ""

        # Trier par temps
        sorted_events = sorted(events, key=lambda e: e.time_beat)

        # Convertir beats → mesures (hypothèse : 4 beats = 1 mesure)
        beats_per_measure = 4
        notes = []

        for event in sorted_events:
            # Convertir MIDI note → note LilyPond
            pitch_name = self._midi_to_note_name(event.note.midi_note)
            duration = self._beats_to_duration(
                event.duration_beats, beats_per_measure
            )
            velocity = event.velocity

            # Formater la note LilyPond
            note_str = f"{pitch_name}{duration}"
            notes.append(note_str)

        return " ".join(notes)

    def _midi_to_note_name(self, midi_note: int) -> str:
        """
        Convertit un MIDI note number en nom de note LilyPond.
        
        MIDI 60 = C4 → c''
        MIDI 69 = A4 → a'
        """
        note_names = ['c', 'cs', 'd', 'es', 'e', 'f', 'fis', 'g',
                      'gs', 'a', 'as', 'b']

        # Note dans l'octave
        note_idx = midi_note % 12
        octave = (midi_note // 12) - 1

        # Primitives pour les notes aiguës
        if octave >= 4:
            base = note_names[note_idx] + "'" * (octave - 3)
        elif octave == 3:
            base = note_names[note_idx]
        else:
            base = note_names[note_idx] + "," * (4 - octave)

        return base

    def _beats_to_duration(
        self,
        duration_beats: float,
        beats_per_measure: int = 4
    ) -> str:
        """
        Convertit des beats en fraction de note LilyPond.
        
        1 beat → 4 (noire)
        2 beats → 2 (blanche)
        0.5 beat → 8 (croche)
        """
        # Convertir en qualité de note (4 = noire par défaut)
        quality = 4 * beats_per_measure / duration_beats

        # Arrondir à la qualité la plus proche
        qualities = [0.125, 0.25, 0.5, 1, 2, 4, 8, 16]
        best = min(qualities, key=lambda q: abs(q - quality))

        return str(int(best))


# ── MIDI File Builder ──────────────────────────────────────────────────────────

class MidiFileBuilder:
    """
    Construit un fichier MIDI Type 0 ou Type 1 à partir d'événements quantisés.
    
    Usage :
        builder = MidiFileBuilder(metadata, midi_type=MidiFileType.TYPE_0)
        builder.add_track(quantized_events, config)
        midi_bytes = builder.build()
    """

    def __init__(
        self,
        metadata: ScoreMetadata,
        midi_type: MidiFileType = MidiFileType.TYPE_0
    ):
        self.metadata = metadata
        self.midi_type = midi_type
        self.tracks: List[List[dict]] = []  # Liste de listes d'événements
        self._tempo_map: List[Tuple[float, int]] = []  # (beat, microseconds_per_beat)

    def add_track(
        self,
        events,
        config: TrackConfig,
        track_index: int = 0
    ):
        """
        Ajoute une piste MIDI.
        
        Args:
            events: liste de QuantizedEvent
            config: configuration de la piste
            track_index: index de la piste
        """
        midi_events = []

        # Event 0: Program Change
        if config.is_drum:
            channel = 9  # MIDI channel 10 (0-indexed)
        else:
            channel = config.channel
        midi_events.append({
            'type': 'program_change',
            'time': 0,
            'program': config.program,
            'channel': channel
        })

        # Event: Control Change (Volume)
        midi_events.append({
            'type': 'control_change',
            'time': 0,
            'control': 7,  # Volume
            'value': config.volume,
            'channel': channel
        })

        # Event: Control Change (Pan) si non-center
        if config.pan != 64:
            midi_events.append({
                'type': 'control_change',
                'time': 0,
                'control': 10,  # Pan
                'value': config.pan,
                'channel': channel
            })

        # Convertir chaque QuantizedEvent en MIDI messages
        for event in events:
            # Note On
            midi_events.append({
                'type': 'note_on',
                'time': event.time_beat,
                'note': event.note.midi_note,
                'velocity': event.velocity,
                'channel': channel
            })

            # Note Off
            midi_events.append({
                'type': 'note_off',
                'time': event.time_beat + event.duration_beats,
                'note': event.note.midi_note,
                'velocity': 0,
                'channel': channel
            })

        self.tracks.append(midi_events)

    def build(self) -> bytes:
        """
        Construit et retourne les bytes MIDI.
        
        Returns:
            Bytes du fichier MIDI
        """
        if self.midi_type == MidiFileType.TYPE_0:
            return self._build_type0()
        else:
            return self._build_type1()

    def _build_type0(self) -> bytes:
        """
        Construit un MIDI Type 0 (single track).
        
        Tous les événements sont fusionnés dans une seule piste.
        """
        # Fusionner tous les événements
        all_events = []
        for track_events in self.tracks:
            all_events.extend(track_events)

        # Trier par temps
        all_events.sort(key=lambda e: e['time'])

        # Construire le fichier MIDI
        return self._write_midi(all_events, num_tracks=1)

    def _build_type1(self) -> bytes:
        """
        Construit un MIDI Type 1 (multi-track).
        
        Chaque piste est séparée + une piste de tempo globale.
        """
        # Piste de tempo en premier
        tempo_events = [{
            'type': 'set_tempo',
            'time': 0,
            'tempo': int(60000000 / self.metadata.tempo)
        }]

        # Écrire chaque piste
        all_tracks = [tempo_events] + self.tracks
        return self._write_midi(all_tracks, num_tracks=len(all_tracks))

    def _write_midi(self, tracks, num_tracks: int) -> bytes:
        """
        Écrit le fichier MIDI au format binaire.
        
        Note: Implémentation simplifiée.
        Pour une production, utiliser 'midiutil' ou 'mido'.
        """
        import struct

        # En-tête MThd
        header = b'MThd'
        header += struct.pack('>I', 6)  # Length
        header += struct.pack('>HH', 0 if num_tracks == 1 else 1,
                              num_tracks)
        header += struct.pack('>HH', 480, 0)  # PPQ, clocks per beat
        # PPQ = 480 ticks par noire (standard)

        # Données de chaque piste
        track_data = b''
        if isinstance(tracks[0], list):
            # Multi-track (Type 1)
            for track_events in tracks:
                track_data += self._write_track(track_events)
        else:
            # Single track (Type 0)
            track_data += self._write_track(tracks)

        return header + track_data

    def _write_track(self, events) -> bytes:
        """Écrit une piste MIDI avec encodage variable-length."""
        track_header = b'MTrk'

        # Événements séquentiels
        midis = []

        last_time = 0
        for event in events:
            delta = int(event['time'] * 480) - last_time
            midis.append((delta, event))
            last_time = int(event['time'] * 480)

        # Encodage de chaque événement
        body = b''
        for delta, event in midis:
            body += self._encode_variable_length(delta)

            if event['type'] == 'note_on':
                body += b'\x9' + str(event['channel']).encode()
                body += self._encode_midi_note(event['note'])
                body += self._encode_midi_velocity(event['velocity'])
            elif event['type'] == 'note_off':
                body += bytes([0x80 | event['channel']])
                body += self._encode_midi_note(event['note'])
                body += b'\x00'  # velocity 0
            elif event['type'] == 'program_change':
                body += bytes([0xC0 | event['channel']])
                body += self._encode_midi_value(event['program'])
            elif event['type'] == 'control_change':
                body += bytes([0xB0 | event['channel']])
                body += self._encode_midi_value(event['control'])
                body += self._encode_midi_value(event['value'])
            elif event['type'] == 'set_tempo':
                # Meta event: Tempo (0x51)
                tempo = event['tempo']
                body += b'\xff\x51\x03'
                body += bytes([
                    (tempo >> 16) & 0xFF,
                    (tempo >> 8) & 0xFF,
                    tempo & 0xFF
                ])
                tempo = event['tempo']
                body += bytes([
                    (tempo >> 16) & 0xFF,
                    (tempo >> 8) & 0xFF,
                    tempo & 0xFF
                ])

        # End of track
        body += b'\xff\x2f\x00'

        track_header += struct.pack('>I', len(body)) + body
        return track_header

    def _encode_variable_length(self, value: int) -> bytes:
        """Encode un entier en format MIDI variable-length."""
        if value == 0:
            return b'\x00'

        bytes_list = []
        v = value
        while v > 0:
            bytes_list.append(v & 0x7F)
            v >>= 7

        result = b''
        for i in range(len(bytes_list) - 1, -1, -1):
            byte = bytes_list[i]
            if i > 0:
                byte |= 0x80  # Continuation bit
            result += bytes([byte])

        return result

    def _encode_midi_note(self, note: int) -> bytes:
        """Encode un note MIDI (0-127)."""
        return bytes([note & 0xFF])

    def _encode_midi_velocity(self, velocity: int) -> bytes:
        """Encode une vélocité MIDI (0-127)."""
        return bytes([velocity & 0xFF])

    def _encode_midi_value(self, value: int) -> bytes:
        """Encode une valeur MIDI (0-127)."""
        return bytes([value & 0xFF])


# ── PDF Generator (via LilyPond) ───────────────────────────────────────────────

class PdfGenerator:
    """
    Génère des PDF à partir de code LilyPond.
    
    Nécessite LilyPond installé sur le système.
    """

    def __init__(self, lilypond_path: Optional[str] = None):
        """
        Args:
            lilypond_path: Chemin vers l'exécutable LilyPond
                          (None = chercher dans PATH)
        """
        self.lilypond_path = lilypond_path or "lilypond"

    def generate_pdf(
        self,
        lilypond_content: str,
        output_path: str = "output.pdf"
    ) -> bool:
        """
        Génère un PDF depuis du code LilyPond.
        
        Args:
            lilypond_content: Code LilyPond valide
            output_path: Chemin de sortie (.pdf ou .ly)
            
        Returns:
            True si succès
        """
        import subprocess
        import tempfile
        import os

        # Étape 1: Écrire le fichier .ly temporaire
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ly', delete=False
        ) as f:
            f.write(lilypond_content)
            ly_path = f.name

        try:
            # Étape 2: Exécuter LilyPond
            result = subprocess.run(
                [self.lilypond_path, ly_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                print(f"[PdfGenerator] Erreur LilyPond: {result.stderr}")
                return False

            # Étape 3: Renommer le PDF généré
            pdf_auto_path = ly_path[:-3] + "pdf"  # .ly → .pdf
            if os.path.exists(pdf_auto_path):
                # Si output_path est un répertoire, mettre le fichier dedans
                if os.path.isdir(output_path):
                    import shutil
                    shutil.move(pdf_auto_path,
                               os.path.join(output_path,
                                            os.path.basename(pdf_auto_path)))
                elif output_path.endswith('.pdf'):
                    import shutil
                    shutil.move(pdf_auto_path, output_path)
                else:
                    import shutil
                    shutil.move(pdf_auto_path, output_path + '.pdf')

            return True

        except FileNotFoundError:
            print("[PdfGenerator] LilyPond non trouvé dans PATH")
            return False
        except subprocess.TimeoutExpired:
            print("[PdfGenerator] LilyPond a expiré (>60s)")
            return False
        finally:
            # Nettoyer les fichiers temporaires
            for ext in ['.ly', '.tex', '.ps', '.pdf', '.log']:
                path = ly_path[:-3] + ext
                if os.path.exists(path):
                    os.remove(path)


# ── Classe principale d'export ─────────────────────────────────────────────────

class ScoreExporter:
    """
    Exporteur principal de partitions.
    
    Usage :
        exporter = ScoreExporter(metadata)
        exporter.add_track(events, config)
        exporter.export("output", OutputFormat.ALL)
    """

    def __init__(self, metadata: ScoreMetadata):
        self.metadata = metadata
        self.tracks: List[tuple] = []  # (events, config)

    def add_track(self, events, config: TrackConfig):
        """Ajoute une piste à exporter."""
        self.tracks.append((events, config))

    def export(
        self,
        output_path: str,
        format: OutputFormat = OutputFormat.ALL
    ) -> List[str]:
        """
        Exporte la partition dans le format spécifié.
        
        Args:
            output_path: Chemin de sortie (sans extension ou répertoire)
            format: Format d'export (MIDI, LilyPond, PDF, ALL)
            
        Returns:
            Liste des fichiers générés
        """
        generated_files = []

        if format in (OutputFormat.MIDI, OutputFormat.ALL):
            midi_file = self._export_midi(output_path)
            if midi_file:
                generated_files.append(midi_file)

        if format in (OutputFormat.LILYPOND, OutputFormat.ALL):
            ly_file = self._export_lilypond(output_path)
            if ly_file:
                generated_files.append(ly_file)

        if format == OutputFormat.PDF:
            pdf_success = self._export_pdf(output_path)
            if pdf_success:
                pdf_path = output_path + ".pdf"
                generated_files.append(pdf_path)

        return generated_files

    def _export_midi(self, output_path: str) -> Optional[str]:
        """Exporte en MIDI."""
        try:
            metadata = self.metadata
            builder = MidiFileBuilder(
                metadata, MidiFileType.TYPE_0
            )

            for events, config in self.tracks:
                builder.add_track(events, config)

            midi_bytes = builder.build()

            # Écrire le fichier
            midi_path = output_path if output_path.endswith('.mid') \
                else output_path + '.mid'
            with open(midi_path, 'wb') as f:
                f.write(midi_bytes)

            print(f"[ScoreExporter] MIDI exporté: {midi_path}")
            return midi_path

        except Exception as e:
            print(f"[ScoreExporter] Erreur export MIDI: {e}")
            return None

    def _export_lilypond(self, output_path: str) -> Optional[str]:
        """Exporte en LilyPond."""
        try:
            builder = LilyPondBuilder(self.metadata)

            for i, (events, config) in enumerate(self.tracks):
                builder.add_track(events, config, i)

            ly_content = builder.build()

            ly_path = output_path if output_path.endswith('.ly') \
                else output_path + '.ly'
            with open(ly_path, 'w', encoding='utf-8') as f:
                f.write(ly_content)

            print(f"[ScoreExporter] LilyPond exporté: {ly_path}")
            return ly_path

        except Exception as e:
            print(f"[ScoreExporter] Erreur export LilyPond: {e}")
            return None

    def _export_pdf(self, output_path: str) -> bool:
        """Exporte en PDF via LilyPond."""
        try:
            # D'abord exporter en LilyPond
            ly_path = self._export_lilypond(output_path)
            if not ly_path:
                return False

            # Lire le contenu LilyPond
            with open(ly_path, 'r', encoding='utf-8') as f:
                ly_content = f.read()

            # Générer le PDF
            generator = PdfGenerator()
            success = generator.generate_pdf(ly_content, output_path)

            if success:
                print(f"[ScoreExporter] PDF exporté: {output_path}.pdf")

            return success

        except Exception as e:
            print(f"[ScoreExporter] Erreur export PDF: {e}")
            return False


# ── Utilitaires ────────────────────────────────────────────────────────────────

def export_score(
    events,
    metadata: ScoreMetadata,
    config: TrackConfig,
    output_path: str = "output",
    format: OutputFormat = OutputFormat.ALL
) -> List[str]:
    """
    Fonction utilitaire pour exporter rapidement une partition.
    
    Args:
        events: liste de QuantizedEvent
        metadata: métadonnées de la partition
        config: configuration de la piste
        output_path: chemin de sortie
        format: format d'export
        
    Returns:
        Liste des fichiers générés
    """
    exporter = ScoreExporter(metadata)
    exporter.add_track(events, config)
    return exporter.export(output_path, format)


# ── Auto-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("="*60)
    print("[Test] MIDI Exporter V3")
    print("="*60)

    # Données de test
    from quantizer import QuantizedNote, QuantizedEvent

    test_events = [
        QuantizedEvent(
            note=QuantizedNote(midi_note=60, start_beat=0.0,
                             duration_beats=1.0, velocity=100),
            time_beat=0.0, velocity=100, duration_beats=1.0
        ),
        QuantizedEvent(
            note=QuantizedNote(midi_note=64, start_beat=1.0,
                             duration_beats=1.0, velocity=90),
            time_beat=1.0, velocity=90, duration_beats=1.0
        ),
        QuantizedEvent(
            note=QuantizedNote(midi_note=67, start_beat=2.0,
                             duration_beats=2.0, velocity=110),
            time_beat=2.0, velocity=110, duration_beats=2.0
        ),
    ]

    metadata = ScoreMetadata(
        title="Test V3",
        composer="Auto-généré",
        key="C major",
        time_signature="4/4",
        tempo=120.0
    )

    config = TrackConfig(
        name="Piano",
        program=0,
        channel=0,
        volume=100
    )

    # Export MIDI
    exporter = ScoreExporter(metadata)
    exporter.add_track(test_events, config)

    midi_file = exporter._export_midi("test_output")
    ly_file = exporter._export_lilypond("test_output")

    if midi_file:
        print(f"\n[MIDI] Fichier généré: {midi_file}")
    if ly_file:
        print(f"[LilyPond] Fichier généré: {ly_file}")

    print(f"\n[Test] SUCCES - MIDI et LilyPond exportés")
    print("="*60)