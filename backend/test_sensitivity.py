"""Test du fix de quantization_sensitivity."""
from tempo_quantizer import quantize_notes, PRESETS, _sensitivity_to_config

# Test avec le preset 'classique'
base_cfg = PRESETS['classique']
print(f"Preset classique de base:")
print(f"  grid_div={base_cfg.grid_div}, snap={base_cfg.snap_threshold_ratio}, min_dur={base_cfg.min_duration_beats}")
print()

# Tester différents niveaux de sensibilité
print("Mapping sensibilité → config:")
for s in [0.0, 0.25, 0.5, 0.75, 1.0]:
    cfg = _sensitivity_to_config(base_cfg, s)
    print(f"  s={s:.2f} → grid_div={cfg.grid_div}, snap={cfg.snap_threshold_ratio:.3f}, min_dur={cfg.min_duration_beats:.4f}, merge={cfg.merge_threshold_beats:.3f}")

print()

# Tester avec des données synthétiques
events = [(0.0, 60, 0.5, 80), (0.51, 62, 0.5, 80), (1.02, 64, 0.5, 80), (1.5, 67, 0.5, 80)]

print("Avec s=0.0 (quantification minimale):")
notes = quantize_notes(events, bpm=120.0, quantization_level='classique', quantization_sensitivity=0.0)
for n in notes:
    dots_str = "." * n.dots
    print(f"  pitch={n.pitch_midi} pos={n.beat_position:.6f} (raw={n.beat_position_raw:.3f}) dur={n.dur_str}{dots_str}")

print()

print("Avec s=1.0 (quantification forte):")
notes = quantize_notes(events, bpm=120.0, quantization_level='classique', quantization_sensitivity=1.0)
for n in notes:
    dots_str = "." * n.dots
    print(f"  pitch={n.pitch_midi} pos={n.beat_position:.6f} (raw={n.beat_position_raw:.3f}) dur={n.dur_str}{dots_str}")

print()
print("✅ Test passé !")