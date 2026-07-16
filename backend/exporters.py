import os
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

def export_all_formats(score_data: dict, voice_split, output_dir: str, base_name: str, formats: List[str]) -> Dict[str, str]:
    """
    Exporte la partition dans les formats demandés.
    """
    os.makedirs(output_dir, exist_ok=True)
    generated_files = {}
    base_path = os.path.join(output_dir, base_name)
    
    # 1. Export MusicXML
    if "musicxml" in formats or "xml" in formats:
        try:
            from backend.musicxml_exporter import export_musicxml
            xml_path = f"{base_path}.musicxml"
            export_musicxml(score_data, xml_path)
            generated_files["musicxml"] = xml_path
            logger.info(f"[Export] MusicXML généré : {xml_path}")
        except Exception as e:
            logger.error(f"[Export] Erreur MusicXML : {e}")

    # 2. Export MIDI & PDF via midi_exporter (LilyPond)
    needs_midi = "midi" in formats or "mid" in formats
    needs_pdf = "pdf" in formats
    
    if needs_midi or needs_pdf:
        try:
            from backend.midi_exporter import ScoreExporter, ScoreMetadata, TrackConfig, OutputFormat
            
            # Préparer les metadata
            metadata = ScoreMetadata(
                title=score_data.get("title", base_name),
                key=score_data.get("keySignature", "C"),
                tempo=score_data.get("tempo", 120),
            )
            # timeSignature is [num, den]
            ts = score_data.get("timeSignature", [4, 4])
            metadata.time_signature = f"{ts[0]}/{ts[1]}"
            
            exporter = ScoreExporter(metadata)
            
            # Reconstituer une liste d'événements depuis voice_split (treble + bass)
            # En V3, midi_exporter gérait une seule liste d'events.
            all_notes = []
            if hasattr(voice_split, "treble") and hasattr(voice_split, "bass"):
                all_notes = voice_split.treble + voice_split.bass
            elif isinstance(voice_split, list):
                all_notes = voice_split
                
            exporter.add_track(all_notes, TrackConfig(name="Piano", program=0))
            
            # Déterminer le format
            if needs_midi and needs_pdf:
                fmt = OutputFormat.ALL
            elif needs_midi:
                fmt = OutputFormat.MIDI
            else:
                fmt = OutputFormat.PDF
                
            files = exporter.export(base_path, fmt)
            
            for f in files:
                if f.endswith('.mid') or f.endswith('.midi'):
                    generated_files["midi"] = f
                elif f.endswith('.pdf'):
                    generated_files["pdf"] = f
                elif f.endswith('.ly'):
                    generated_files["lilypond"] = f
                    
            logger.info(f"[Export] MIDI/PDF générés pour {base_name}")
        except Exception as e:
            logger.error(f"[Export] Erreur MIDI/PDF : {e}")

    return generated_files
