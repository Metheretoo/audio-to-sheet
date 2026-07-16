# PHASE 3 — Voice Alignment Engine (Séparation Main Gauche / Main Droite)

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 3-5h
> **Prérequis** : Phase 2 complète (`quantizer.py` disponible et testé)
> **Fichier à créer** : `backend/voice_engine.py`

---

## Objectif

Remplacer le seuil fixe `TREBLE_THRESHOLD = 57` par un **moteur d'alignement vocal dynamique** qui analyse le contexte musical pour attribuer chaque note à la main droite ou gauche de façon pertinente.

### Problème résolu

**V1 (problème)** :
```python
# midi_parser.py ligne 303
hand = 'treble' if pitch >= TREBLE_THRESHOLD else 'bass'
# Problème : un accord de Do3-Mi3-Sol3 (Do3=48, Mi3=52, Sol3=55)
# → tout va en BASS car < 57
# Mais musicalement, c'est un accord de main gauche "sol" qui devrait inclure
# la mélodie si elle est au-dessus et les accords en-dessous
```

**V2 (solution)** : Analyse contextuelle multi-facteurs.

---

## Concepts musicaux implémentés

### Zone de recouvrement
Le piano a une **zone de recouvrement** entre les deux mains autour du Do central (MIDI 60) :
- Main gauche typique : MIDI 24 (La0) → MIDI 65 (Fa4)
- Main droite typique : MIDI 55 (Sol3) → MIDI 108 (Do8)
- Zone grise : MIDI 55–65 → décision contextuelle

### Contour mélodique
Si une série de notes monte progressivement puis descend brusquement, la descente brusque indique souvent un saut à la main gauche (basse d'accompagnement).

### Fondamentales d'accord
Dans un accord (notes simultanées), la note la plus basse est souvent la **fondamentale** et appartient à la main gauche si elle est dans la zone grave.

---

## Fichier à créer : `backend/voice_engine.py`

```python
"""
voice_engine.py — Moteur d'alignement des voix pour piano (séparation LH/RH)

Prend une liste de QuantizedNote et produit un VoiceSplit (treble/bass)
en utilisant une approche multi-facteurs :
  1. Registre (zone de pitch)
  2. Contour mélodique (mouvement des notes dans le temps)
  3. Analyse des accords (fondamentales vs extensions)
  4. Continuité de voix (éviter les changements de main trop fréquents)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple
from quantizer import QuantizedNote


# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class VoiceSplit:
    treble: List[QuantizedNote] = field(default_factory=list)  # main droite
    bass:   List[QuantizedNote] = field(default_factory=list)  # main gauche


# ── Constantes ────────────────────────────────────────────────────────────────

BASS_MAX_MIDI   = 65     # Fa4 — au-dessus, toujours main droite (sauf exception)
TREBLE_MIN_MIDI = 55     # Sol3 — en-dessous, toujours main gauche (sauf exception)
GREY_ZONE       = (55, 65)  # Zone de décision contextuelle
BASS_ANCHOR     = 48     # Do3 — notes sous ce seuil → TOUJOURS main gauche

# Poids pour le score de décision
WEIGHT_PITCH      = 0.5   # Importance du registre absolu
WEIGHT_CONTOUR    = 0.3   # Importance du mouvement mélodique
WEIGHT_CHORD_POS  = 0.2   # Importance de la position dans l'accord


# ── Fonction principale ───────────────────────────────────────────────────────

def split_voices(
    notes: List[QuantizedNote],
    options: dict = None
) -> VoiceSplit:
    """
    Sépare les notes en deux voix (treble/bass) selon le contexte musical.

    Paramètres :
      notes   : List[QuantizedNote] triée par beat_position
      options : dict optionnel avec :
        - split_threshold : int MIDI (seuil de fallback, défaut: 60)
        - use_contour : bool (activer l'analyse de contour, défaut: True)
        - use_chord_analysis : bool (activer l'analyse d'accords, défaut: True)

    Retourne un VoiceSplit avec les notes réparties.

    Algorithme global :
    1. Grouper les notes simultanées en accords (même beat_position ± 0.05)
    2. Pour chaque accord, attribuer les notes avec score_decision()
    3. Appliquer la correction de continuité (éviter trop de changements rapides)
    """
    if options is None:
        options = {}

    # Grouper en instants simultanés
    groups = _group_simultaneous(notes)

    treble_notes = []
    bass_notes   = []

    for group in groups:
        t_notes, b_notes = _classify_group(group, options)
        treble_notes.extend(t_notes)
        bass_notes.extend(b_notes)

    # Correction de continuité (post-processing)
    if options.get('use_contour', True):
        treble_notes, bass_notes = _apply_continuity(treble_notes, bass_notes)

    # Mettre à jour le champ 'hand' sur chaque note
    for n in treble_notes:
        n.hand = 'treble'
    for n in bass_notes:
        n.hand = 'bass'

    return VoiceSplit(
        treble=sorted(treble_notes, key=lambda n: n.beat_position),
        bass=sorted(bass_notes,   key=lambda n: n.beat_position)
    )


# ── Groupement ────────────────────────────────────────────────────────────────

def _group_simultaneous(notes: List[QuantizedNote], window: float = 0.05) -> List[List[QuantizedNote]]:
    """
    Regroupe les notes dont la beat_position est à moins de `window` beats.
    Retourne une liste de groupes (chaque groupe = liste de notes simultanées).

    Algorithme :
    - Trier par beat_position
    - Créer un nouveau groupe si l'écart avec la note précédente > window
    """
    ...


# ── Classification d'un groupe ────────────────────────────────────────────────

def _classify_group(
    group: List[QuantizedNote],
    options: dict
) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """
    Attribue les notes d'un groupe (accord ou note seule) à treble ou bass.

    Règles par ordre de priorité :

    1. RÈGLE ABSOLUE BASSE : pitch < BASS_ANCHOR (48) → bass, toujours.
    2. RÈGLE ABSOLUE AIGUË : pitch > BASS_MAX_MIDI (65) → treble, toujours.
    3. ZONE GRISE [55-65] : utiliser score_decision() pour décider.
    4. ACCORD : si plusieurs notes simultanées, la note la plus basse dans la zone
       va à la bass, les autres au treble (règle de fondamentale).

    Retourne (treble_notes, bass_notes).
    """
    ...


def score_decision(note: QuantizedNote, group: List[QuantizedNote]) -> str:
    """
    Calcule un score pour décider si une note en zone grise va à treble ou bass.

    Facteurs :
    - Registre : plus la note est basse dans [55-65], plus elle tend vers bass
      score_pitch = (65 - pitch) / (65 - 55)  → 0.0 (treble) à 1.0 (bass)

    - Position dans l'accord :
      Si c'est la note la plus basse d'un accord de ≥3 notes → bass (+0.3)
      Si c'est la note la plus haute d'un accord → treble (-0.3)

    - Amplitude :
      Une note forte et basse est souvent une basse → bass si amp > 0.6 et pitch < 60

    Retourne 'treble' ou 'bass'.
    """
    score_bass = 0.0

    # Facteur 1 : registre
    if GREY_ZONE[0] <= note.pitch_midi <= GREY_ZONE[1]:
        score_bass += WEIGHT_PITCH * (GREY_ZONE[1] - note.pitch_midi) / (GREY_ZONE[1] - GREY_ZONE[0])

    # Facteur 2 : position dans l'accord
    if len(group) >= 2:
        pitches = [n.pitch_midi for n in group]
        if note.pitch_midi == min(pitches):
            score_bass += WEIGHT_CHORD_POS * 1.5  # fondamentale → bass
        elif note.pitch_midi == max(pitches):
            score_bass -= WEIGHT_CHORD_POS * 1.0  # voix aiguë → treble

    # Facteur 3 : amplitude
    if note.amplitude > 0.65 and note.pitch_midi < 60:
        score_bass += 0.15

    return 'bass' if score_bass > 0.5 else 'treble'


# ── Continuité ────────────────────────────────────────────────────────────────

def _apply_continuity(
    treble: List[QuantizedNote],
    bass: List[QuantizedNote]
) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """
    Lisse les changements de main trop fréquents.

    Problème typique sans continuité :
    - treble : Do4, Sol3, Do4, Sol3, ...  (oscillations rapides)
    - bas    : Mi3, Do4, Mi3, Do4, ...

    Solution : si une note en zone grise change de main sur moins de 2 beats
    et que sa "sœur" voisine est dans la même zone, réévaluer.

    IMPORTANT : ne modifier que les notes en zone grise (GREY_ZONE).
    Ne jamais déplacer une note hors de sa main si pitch < BASS_ANCHOR ou > BASS_MAX_MIDI.

    Algorithme :
    - Détecter les notes en zone grise qui oscillent entre treble et bass
    - Si 3 notes consécutives du même pitch alternent de main → forcer toutes dans la même
    """
    ...


# ── Analyse de contour ────────────────────────────────────────────────────────

def analyze_melodic_contour(notes: List[QuantizedNote]) -> List[float]:
    """
    Calcule le vecteur de mouvement mélodique de la voix principale.

    Retourne une liste de valeurs [-1, 0, +1] :
      +1 : note plus haute que la précédente (mouvement ascendant)
       0 : même note
      -1 : note plus basse que la précédente (mouvement descendant)

    Un saut descendant brusque (> 7 demi-tons) peut indiquer un changement de voix.
    Utilisé comme indicateur supplémentaire dans _apply_continuity().
    """
    if len(notes) < 2:
        return [0] * len(notes)

    pitches = [n.pitch_midi for n in notes]
    contour = [0]
    for i in range(1, len(pitches)):
        diff = pitches[i] - pitches[i-1]
        contour.append(1 if diff > 0 else (-1 if diff < 0 else 0))
    return contour


def detect_chord_roots(group: List[QuantizedNote]) -> Optional[QuantizedNote]:
    """
    Identifie la fondamentale d'un accord (note la plus basse du groupe).
    Retourne None si le groupe est vide.

    Dans un accord enrichi (7ème, 9ème), la fondamentale est la note la plus basse.
    Cette note doit aller à la main gauche si elle est dans la zone de basse.
    """
    if not group:
        return None
    return min(group, key=lambda n: n.pitch_midi)


# ── Auto-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    Test : accord de Do majeur 7ème (Do3-Mi3-Sol3-Si3-Do4-Mi4)
    Attendu :
      bass   : Do3 (48), Mi3 (52), Sol3 (55) — fondamentales
      treble : Si3 (59), Do4 (60), Mi4 (64)  — extensions et mélodie
    """
    from quantizer import QuantizedNote

    def make_note(pitch, pos=0.0, dur=1.0, amp=0.7):
        return QuantizedNote(
            pitch_midi=pitch, amplitude=amp,
            beat_position=pos, beat_duration=dur,
            dur_str='q', dots=0, hand='treble'
        )

    # Accord Cmaj7 : Do3-Mi3-Sol3-Si3 + Do4-Mi4 (joués simultanément)
    chord = [
        make_note(48),  # Do3 → bass attendu
        make_note(52),  # Mi3 → bass attendu
        make_note(55),  # Sol3 → bass attendu (zone grise, fondamentale)
        make_note(59),  # Si3 → treble attendu (zone grise, extension)
        make_note(60),  # Do4 → treble attendu
        make_note(64),  # Mi4 → treble attendu
    ]

    result = split_voices(chord)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications critiques
    bass_pitches   = {n.pitch_midi for n in result.bass}
    treble_pitches = {n.pitch_midi for n in result.treble}

    assert 48 in bass_pitches,   "Do3 doit être en main gauche"
    assert 64 in treble_pitches, "Mi4 doit être en main droite"
    assert 60 in treble_pitches, "Do4 doit être en main droite"
    print("[Test] ✓ Vérifications passées")
```

---

## Notes pour l'agent

### Piège 1 : Accords enrichis à la main gauche
Sur du jazz ou de la pop, la main gauche joue souvent des accords de 4 notes (ex: Do-Mi-Sol-Si). L'algorithme ne doit pas tout mettre à la main gauche sous prétexte que les notes sont en zone grise. Seule la fondamentale + basse va à la main gauche ; les tensions/extensions restent à droite.

### Piège 2 : Notes seules en zone grise
Une note seule à MIDI 60 (Do4) n'a pas de contexte d'accord. Décision par défaut : treble si > 59, bass sinon.

### Piège 3 : Ne pas surcharger la main gauche
Si la main gauche a plus de 4 notes à une même position, il y a probablement une erreur de classification. Limiter la main gauche à max 4-5 notes simultanées.

### Piège 4 : Compatibilité avec Phase 4
Le `VoiceSplit` produit est directement consommé par `score_builder.py`. L'ordre et la structure des `QuantizedNote` ne doivent pas être modifiés.
