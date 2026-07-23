"""Test de l'effet visible de quantization_sensitivity avec des données désalignées."""
from tempo_quantizer import quantize_notes, PRESETS

# Données intentionally désalignées (artéfacts de transcription courants)
# Les positions ne tombent PAS sur la grille (grille classique = 1/8 beat = 0.0625 beats)
events = [
    (0.01, 60, 0.48, 80),   # décalé de 0.01 beat
    (0.63, 62, 0.52, 80),   # décalé de 0.07 beat
    (1.21, 64, 0.47, 80),   # décalé de 0.05 beat
    (1.85, 67, 0.53, 80),   # décalé de 0.02 beat
]

print("Données d'entrée (positions brutes en beats):")
for i, e in enumerate(events):
    print(f"  event {i}: onset={e[0]:.2f}s → {e[0] * 120 / 60:.4f} beats")
print()

print("=" * 70)
print("Avec s=0.0 (quantification minimale - pas d'aimantation):")
print("=" * 70)
notes = quantize_notes(events, bpm=120.0, quantization_level='classique', quantization_sensitivity=0.0)
for n in notes:
    offset = n.beat_position - n.beat_position_raw
    print(f"  pitch={n.pitch_midi} pos_quant={n.beat_position:.6f} pos_raw={n.beat_position_raw:.6f} Δ={offset:+.6f} dur={n.dur_str}")

print()
print("=" * 70)
print("Avec s=0.5 (quantification moyenne):")
print("=" * 70)
notes = quantize_notes(events, bpm=120.0, quantization_level='classique', quantization_sensitivity=0.5)
for n in notes:
    offset = n.beat_position - n.beat_position_raw
    print(f"  pitch={n.pitch_midi} pos_quant={n.beat_position:.6f} pos_raw={n.beat_position_raw:.6f} Δ={offset:+.6f} dur={n.dur_str}")

print()
print("=" * 70)
print("Avec s=1.0 (quantification forte - aimantation maximale):")
print("=" * 70)
notes = quantize_notes(events, bpm=120.0, quantization_level='classique', quantization_sensitivity=1.0)
for n in notes:
    offset = n.beat_position - n.beat_position_raw
    print(f"  pitch={n.pitch_midi} pos_quant={n.beat_position:.6f} pos_raw={n.beat_position_raw:.6f} Δ={offset:+.6f} dur={n.dur_str}")

print()
print("✅ Les différences de position montrent l'effet de l'aimantation !")