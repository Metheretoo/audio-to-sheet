"\"\"\"
PATCH — quantizer.py

Objectif : ajouter le preset \"classique\" (grille 1/32 + triolets) et retirer
la divergence entre config.yaml (déclare \"classique\") et quantizer.py (grid_map
hardcodée qui ignore config.yaml).

CONSTAT :
- `config.yaml:82-116` définit 6 presets (none/light/standard/heavy/rubato/triplets).
- `quantizer.py:390-395` définit un `grid_map` HARDCODÉ qui ignore config.yaml.
- Le preset \"classique\" (proposé dans TODO.txt) n'existe nulle part.

À appliquer sur `backend/quantizer.py` : remplacer les blocs `grid_map` et
`snap_map` (lignes ~390 → 414) par ceux ci-dessous.
\"\"\"

# ============================================================================
# À REMPLACER lignes ~390-414 dans quantizer.py, dans la fonction quantize_notes
# ============================================================================

    # Choisir la résolution de la grille de position (subdivisions par beat).
    # Ajout du preset \"classique\" pour piano classique (Chopin, Debussy, etc.)
    # avec micro-timing très fin + triolets. Aligné avec config.yaml.
    grid_map = {
        'none':      16,   # 1/16 beat ≈ très fin (quasi brut)
        'light':     16,   # 1/16 beat = triple-croche
        'standard':   8,   # 1/8  beat = double-croche
        'heavy':      4,   # 1/4  beat = croche
        'rubato':    32,   # 1/32 beat : capte le micro-timing expressif
        'triplets':  12,   # 1/12 beat : base triolet + subdivisions binaires
        'classique': 32,   # NOUVEAU : 1/32 beat, comparable au rubato mais
                           # avec snap réel actif (voir snap_map ci-dessous)
    }
    grid_div = grid_map.get(quantization_level, 8)

    # Aimantation : snap_step = 1 / snap_div (en beats)
    snap_map = {
        'none':      0,    # pas d'aimantation
        'light':     4,    # → double-croche (snap_step=0.25)
        'standard':  2,    # → croche       (snap_step=0.5)
        'heavy':     1,    # → noire         (snap_step=1.0)
        'rubato':    4,    # → double-croche : garde le rubato mais lisible
        'triplets':  3,    # → tiers de beat : aimantation sur triolets
        'classique': 4,    # NOUVEAU : aimantation sur double-croche
                           # (grille 1/32 pour DÉTECTER l'expressif, snap 1/4
                           # pour rester lisible en notation)
    }
    snap_div = snap_map.get(quantization_level, 2)
    snap_threshold_ratio = 0.45


# ============================================================================
# ÉGALEMENT à modifier : la logique enable_rubato (~lignes 428-437)
# doit accepter les nouveaux presets sans les écraser.
# Remplacer le bloc `if enable_rubato:` par :
# ============================================================================

    # Le mode Rubato manuel (checkbox UI) affine sans dégrader les presets
    # déjà fins. Compatible avec le preset \"classique\" qui est déjà en 1/32.
    if enable_rubato:
        grid_div = max(grid_div, 32)  # au moins 1/32 beat
        if snap_div > 0:
            # Relâche l'aimantation d'un cran (croche → double-croche, etc.)
            # pour préserver l'expressivité tout en évitant la soupe.
            snap_div = min(snap_div * 2, 8)
            snap_threshold_ratio = 0.30  # aimantation moins agressive


# ============================================================================
# Modifications config.yaml (à appliquer à la racine du projet)
# ============================================================================
\"\"\"
Dans `config.yaml`, section `quantization.levels`, remplacer/ajouter :

  standard:
    grid_resolution: 0.125       # 1/8 beat = double-croche (AVANT 0.25 = trop grossier)
    ioi_tolerance: 0.15
    swing_ratio: 1.0
    detect_tuples: true

  classique:                     # NOUVEAU preset
    grid_resolution: 0.03125     # 1/32 beat
    ioi_tolerance: 0.08
    swing_ratio: 1.0
    detect_tuples: true
    adaptive_tempo: true
    tuple_types: [\"triplet\", \"quintuplet\", \"sextuplet\"]

NOTE : `config.yaml` sert essentiellement de documentation aujourd'hui — le code
lit rarement ces valeurs. Une évolution v5 devrait charger ces params dans la
`grid_map` dynamiquement.
\"\"\"

# ============================================================================
# Modifications frontend/index.html (menu Quantification)
# ============================================================================
\"\"\"
Ajouter l'option classique dans le <select id=\"quantization\"> :

  <option value=\"none\">Aucune (brut)</option>
  <option value=\"light\">Légère (1/16)</option>
  <option value=\"standard\" selected>Standard (1/8)</option>
  <option value=\"heavy\">Forte (1/4)</option>
  <option value=\"rubato\">Rubato (expressif)</option>
  <option value=\"triplets\">Triolets</option>
  <option value=\"classique\">Classique (Chopin/Debussy)</option>  ← NOUVEAU
\"\"\"
"