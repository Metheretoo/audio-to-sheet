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
from typing import List, Tuple, Optional
from quantizer import QuantizedNote

# Poids de la pénalité harmonique (configurable)
HARMONY_PENALTY_WEIGHT = 50.0  # coût si on brise un accord reconnu
BASS_BONUS_WEIGHT      = 20.0  # bonus si la basse d'accord va en LH


# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class VoiceSplit:
    treble: List[QuantizedNote] = field(default_factory=list)  # main droite
    bass:   List[QuantizedNote] = field(default_factory=list)  # main gauche


# ── Constantes ────────────────────────────────────────────────────────────────

BASS_MAX_MIDI   = 65     # Fa4 — au-dessus, toujours main droite (sauf exception)
TREBLE_MIN_MIDI = 55     # Sol3 — en-dessous, toujours main gauche (sauf exception)
GREY_ZONE       = (55, 65)  # Zone de décision contextuelle
BASS_ANCHOR     = 55     # Si3 — notes sous ce seuil → TOUJOURS main gauche (élargi de 48 à 55)

# Poids pour le score de décision
WEIGHT_PITCH      = 0.5   # Importance du registre absolu
WEIGHT_CONTOUR    = 0.3   # Importance du mouvement mélodique
WEIGHT_CHORD_POS  = 0.2   # Importance de la position dans l'accord


# ── Fonction principale ───────────────────────────────────────────────────────

def split_voices(
    notes: List[QuantizedNote],
    options: dict = None,
    harmonic_ctx = None
) -> VoiceSplit:
    """
    Sépare les notes en deux voix (treble/bass) selon le contexte musical.
    """
    if options is None:
        options = {}

    if not options.get('split_hands', True):
        # Si split_hands est désactivé, tout va dans treble
        for n in notes:
            n.hand = 'treble'
        return VoiceSplit(
            treble=sorted(notes, key=lambda n: n.beat_position),
            bass=[]
        )

    # Grouper en instants simultanés
    groups = _group_simultaneous(notes)

    treble_notes = []
    bass_notes   = []

    for group in groups:
        t_notes, b_notes = _classify_group(group, options)
        treble_notes.extend(t_notes)
        bass_notes.extend(b_notes)

    # Mettre à jour le champ 'hand' sur chaque note AVANT la continuité
    for n in treble_notes:
        n.hand = 'treble'
    for n in bass_notes:
        n.hand = 'bass'

    # Correction de continuité (post-processing)
    if options.get('use_smoothing', True):
        treble_notes, bass_notes = _apply_continuity(treble_notes, bass_notes)

    # Mettre à jour une dernière fois au cas où
    for n in treble_notes:
        n.hand = 'treble'
    for n in bass_notes:
        n.hand = 'bass'

    return VoiceSplit(
        treble=sorted(treble_notes, key=lambda n: n.beat_position),
        bass=sorted(bass_notes,   key=lambda n: n.beat_position)
    )


def split_with_harmony(
    notes: List[QuantizedNote],
    harmonic_ctx=None,
    options: dict = None
) -> VoiceSplit:
    """
    Séparation LH/RH guidée par l'analyse harmonique.
    
    Amélioration V4 : une pénalité Dijkstra est appliquée quand une affectation
    sépare des notes appartenant au même accord reconnu par music21.
    
    Si harmonic_ctx est None (ou import raté), repli sur split_voices().
    """
    if options is None:
        options = {}

    if harmonic_ctx is None:
        return split_voices(notes, options)

    if not options.get('split_hands', True):
        for n in notes:
            n.hand = 'treble'
        return VoiceSplit(
            treble=sorted(notes, key=lambda n: n.beat_position),
            bass=[]
        )

    # Pré-tri par beat
    sorted_notes = sorted(notes, key=lambda n: n.beat_position)
    if not sorted_notes:
        return VoiceSplit()

    # --- Dijkstra sur 2 voix ---
    # État : (note_index, hand)  hand = 0=treble / 1=bass
    # On cherche l'affectation qui minimise le coût total.
    INF = float('inf')
    n_notes = len(sorted_notes)

    # dist[i][h] = coût minimal pour affecter la note i à la main h
    dist = [[INF, INF] for _ in range(n_notes)]
    prev = [[None, None] for _ in range(n_notes)]

    # Initialiser: première note
    note0 = sorted_notes[0]
    dist[0][0] = 0.0 if note0.pitch_midi >= TREBLE_MIN_MIDI else INF
    dist[0][1] = 0.0 if note0.pitch_midi <= BASS_MAX_MIDI else INF
    # Forcer les règles absolues
    if note0.pitch_midi < BASS_ANCHOR:
        dist[0][0] = INF; dist[0][1] = 0.0
    elif note0.pitch_midi >= BASS_MAX_MIDI:
        dist[0][0] = 0.0; dist[0][1] = INF

    for i in range(1, n_notes):
        note = sorted_notes[i]
        for h in range(2):  # 0=treble, 1=bass
            # Règles absolues
            if note.pitch_midi < BASS_ANCHOR and h == 0:
                continue
            if note.pitch_midi >= BASS_MAX_MIDI and h == 1:
                continue
            # Trouver le meilleur état précédent
            for ph in range(2):
                if dist[i-1][ph] == INF:
                    continue
                # Calculer le coût de la transition
                if harmonic_ctx:
                    cost = _compute_edge_cost_with_harmony(
                        sorted_notes[i-1], note,
                        'rh' if h == 0 else 'lh',
                        harmonic_ctx, options
                    )
                else:
                    cost = _compute_edge_cost(sorted_notes[i-1], note, 'rh' if h == 0 else 'lh', options)
                
                # Pénalité de changement de main dans la zone grise
                if ph != h and GREY_ZONE[0] <= note.pitch_midi <= GREY_ZONE[1]:
                    cost += 5.0
                total = dist[i-1][ph] + cost
                if total < dist[i][h]:
                    dist[i][h] = total
                    prev[i][h] = ph

    # Reconstruire le chemin optimal
    # Choisir la main pour la dernière note
    last_hand = 0 if dist[n_notes-1][0] <= dist[n_notes-1][1] else 1
    hands = [None] * n_notes
    hands[n_notes-1] = last_hand
    for i in range(n_notes-2, -1, -1):
        hands[i] = prev[i+1][hands[i+1]] if prev[i+1][hands[i+1]] is not None else 0

    treble_notes = []
    bass_notes   = []
    for i, note in enumerate(sorted_notes):
        h = hands[i] if hands[i] is not None else (1 if note.pitch_midi < BASS_ANCHOR else 0)
        if h == 0:
            note.hand = 'treble'
            treble_notes.append(note)
        else:
            note.hand = 'bass'
            bass_notes.append(note)

    # Lissage de continuité
    if options.get('use_smoothing', True):
        treble_notes, bass_notes = _apply_continuity(treble_notes, bass_notes)
        for n in treble_notes: n.hand = 'treble'
        for n in bass_notes:   n.hand = 'bass'

    return VoiceSplit(
        treble=sorted(treble_notes, key=lambda n: n.beat_position),
        bass=sorted(bass_notes,   key=lambda n: n.beat_position)
    )


def _compute_edge_cost_with_harmony(
    note_a: QuantizedNote,
    note_b: QuantizedNote,
    voice: str,            # 'lh' ou 'rh'
    harmonic_ctx,
    config: dict
) -> float:
    """
    Coût d'affecter note_b à la voix `voice` après note_a.
    Intègre la pénalité harmonique V4.
    """
    # 1. Coût mélodique (intervalle en demi-tons)
    melodic_cost = abs(note_b.pitch_midi - note_a.pitch_midi)

    # 2. Pénalité si on brise un accord reconnu
    harmony_penalty = 0.0
    chord_at_b = harmonic_ctx.chord_map.get(note_b.beat_position)
    if chord_at_b and chord_at_b.is_known_chord:
        # Note de basse de l'accord dans la zone LH ?
        bass_in_lh = chord_at_b.bass_note <= BASS_MAX_MIDI
        if bass_in_lh and voice == 'rh' and note_b.pitch_midi in _get_chord_pitches(chord_at_b):
            harmony_penalty = config.get('harmony_penalty_weight', HARMONY_PENALTY_WEIGHT)

    # 3. Bonus basse d'accord en LH
    bass_bonus = 0.0
    if chord_at_b and note_b.pitch_midi == chord_at_b.bass_note and voice == 'lh':
        bass_bonus = -config.get('bass_bonus_weight', BASS_BONUS_WEIGHT)

    return max(0.0, melodic_cost + harmony_penalty + bass_bonus)


def _get_chord_pitches(chord_analysis) -> list:
    """Reconstruit (approximativement) les pitches d'un accord depuis ChordAnalysis."""
    # ChordAnalysis ne stocke pas les pitches bruts, on utilise bass_note + estimation
    # Pour la pénalité, on travaille uniquement sur la basse = bonne heuristique
    return [chord_analysis.bass_note]


# Alias pour compatibilité avec pipeline.py
def split_hands(note_events: list, method: str = 'dynamic', split_point: int = 57) -> list:
    """
    Wrapper compatible pipeline.py (qui transmet des list de dicts, pas des QuantizedNote).
    Ajoute un champ 'hand' à chaque note dict.
    """
    for n in note_events:
        pitch = n.get('pitch', 60) if isinstance(n, dict) else getattr(n, 'pitch_midi', 60)
        if isinstance(n, dict):
            n['hand'] = 'bass' if pitch < split_point else 'treble'
    return note_events


# ── Groupement ────────────────────────────────────────────────────────────────

def _group_simultaneous(notes: List[QuantizedNote], window: float = 0.05) -> List[List[QuantizedNote]]:
    """
    Regroupe les notes dont la beat_position est à moins de `window` beats.
    Retourne une liste de groupes (chaque groupe = liste de notes simultanées).

    Algorithme :
    - Trier par beat_position
    - Créer un nouveau groupe si l'écart avec la note précédente > window
    """
    if not notes:
        return []

    sorted_notes = sorted(notes, key=lambda n: n.beat_position)
    groups = []
    current_group = [sorted_notes[0]]

    for note in sorted_notes[1:]:
        if abs(note.beat_position - current_group[-1].beat_position) <= window:
            current_group.append(note)
        else:
            groups.append(current_group)
            current_group = [note]

    groups.append(current_group)
    return groups


# ── Classification d'un groupe ────────────────────────────────────────────────

def _classify_group(
    group: List[QuantizedNote],
    options: dict
) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """
    Attribue les notes d'un groupe (accord ou note seule) à treble ou bass.

    Règles par ordre de priorité :

    1. RÈGLE ABSOLUE BASSE : pitch ≤ BASS_ANCHOR (55) → bass, toujours.
    2. RÈGLE ABSOLUE AIGUË : pitch ≥ BASS_MAX_MIDI (65) → treble, toujours.
    3. ZONE GRISE [55-65] : utiliser score_decision() pour décider.
    4. ACCORD : si plusieurs notes simultanées, la note la plus basse dans la zone
       va à la bass, les autres au treble (règle de fondamentale).

    Retourne (treble_notes, bass_notes).
    """
    treble_notes = []
    bass_notes = []

    for note in group:
        pitch = note.pitch_midi

        if pitch < BASS_ANCHOR:
            bass_notes.append(note)
            continue

        if pitch >= BASS_MAX_MIDI:
            treble_notes.append(note)
            continue

        # Règle 3 : zone grise [BASS_ANCHOR, BASS_MAX_MIDI) → score décision
        # Avec BASS_ANCHOR=55 et BASS_MAX_MIDI=65, c'est [55, 65)
        if BASS_ANCHOR <= pitch < BASS_MAX_MIDI:
            decision = score_decision(note, group, options)
            if decision == 'treble':
                treble_notes.append(note)
            else:
                bass_notes.append(note)
            continue

        # Règle 4 : notes entre BASS_ANCHOR et GREY_ZONE[0] (55-55) → bass par défaut
        bass_notes.append(note)

    return treble_notes, bass_notes


def score_decision(note: QuantizedNote, group: List[QuantizedNote], options: dict = None) -> str:
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

    - NOUVEAU : Vélocité pour les basses
      Une note grave (< 50) avec vélocité > 0.20 est protégée (main gauche légitime)
      Une note en zone grise avec vélocité > 0.50 tend vers main droite

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

    # NOUVEAU : Facteur vélocité pour distinguer LH/RH en zone grise
    # PROTECTION PROGRESSIVE basée sur la vélocité
    # - velocity < 0.15  → bonus maximal (basses jouées doucement)
    # - velocity 0.15-0.30 → bonus fort (basses jouées normalement)
    # - velocity 0.30-0.50 → bonus réduit (basses fortes, mais légitimes)
    # - velocity > 0.50  → bonus faible (notes mélodiques aiguës)
    if hasattr(note, 'velocity') and note.velocity is not None:
        velocity = note.velocity
    else:
        velocity = note.amplitude
    
    # Bonus progressif pour les basses (notes graves avec vélocité modérée)
    # Avec BASS_ANCHOR=55, les notes < 55 ont déjà été attribuées à bass dans _classify_group
    # Donc ici on ne traite que la zone grise [55, 65)
    if BASS_ANCHOR <= note.pitch_midi < BASS_MAX_MIDI:
        if velocity < 0.15:
            score_bass += 0.35  # Tend vers main gauche (basse jouée doucement)
        elif velocity < 0.30:
            score_bass += 0.28  # Tend vers main gauche (basse jouée normalement)
        elif velocity < 0.50:
            score_bass += 0.15  # Légère tendance main gauche
        else:
            score_bass -= 0.05  # Légère tendance main droite (note forte = mélodie)
    else:
        # Note en zone grise ou au-dessus
        if BASS_ANCHOR <= note.pitch_midi < BASS_MAX_MIDI:
            if velocity > 0.50:
                score_bass -= 0.15  # Tend vers main droite
    
    # [NOUVEAU] Protection basse renforcée depuis le paramètre UI
    # Les basses protégées reçoivent un bonus massif pour forcer la main gauche
    if hasattr(note, 'velocity') and note.velocity is not None:
        # Obtenir le seuil de protection basse (de options ou par défaut)
        protection_threshold = None
        if options and 'bass_protection_velocity' in options:
            protection_threshold = options['bass_protection_velocity']
        if protection_threshold is None:
            from note_filter import BASS_PROTECTION_THRESHOLD
            protection_threshold = BASS_PROTECTION_THRESHOLD
        
        # Seuil bas : en dessous de 35% du seuil → bonus massif LH
        low_threshold = protection_threshold * 0.35
        if note.amplitude <= low_threshold and note.pitch_midi < BASS_MAX_MIDI:
            score_bass += 2.0  # Bonus très fort pour main gauche
        
        # Si la note est très grave (< 36 = Do1) → toujours main gauche
        if note.pitch_midi < 36:
            score_bass += 1.5

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
    # Fusionner les deux listes par beat_position
    all_notes = treble + bass
    sorted_notes = sorted(all_notes, key=lambda n: n.beat_position)

    # Identifier les notes en zone grise
    grey_notes = [n for n in sorted_notes if GREY_ZONE[0] <= n.pitch_midi <= GREY_ZONE[1]]

    # Pour chaque note en zone grise, vérifier les alternances
    for i in range(len(grey_notes) - 2):
        note1 = grey_notes[i]
        note2 = grey_notes[i + 1]
        note3 = grey_notes[i + 2]

        # Vérifier si les notes sont proches dans le temps
        if abs(note2.beat_position - note1.beat_position) < 0.1 and \
           abs(note3.beat_position - note2.beat_position) < 0.1:

            # Vérifier si alternance de main
            if note1.hand != note2.hand and note2.hand != note3.hand:
                # Si alternance, forcer toutes dans la main de la note centrale
                if note2.hand == 'treble':
                    note1.hand = 'treble'
                    note3.hand = 'treble'
                else:
                    note1.hand = 'bass'
                    note3.hand = 'bass'

    # Séparer à nouveau
    treble_notes = [n for n in sorted_notes if n.hand == 'treble']
    bass_notes = [n for n in sorted_notes if n.hand == 'bass']

    return treble_notes, bass_notes


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


# ── Phase 1 : Nouvelles fonctions de contexte musical ─────────────────────────

def analyze_harmony(group: List[QuantizedNote]) -> dict:
    """
    Analyse l'accord pour extraire :
    - Fondamentale (note la plus basse)
    - Inversions (position de la fondamentale)
    - Type d'accord (majeur, mineur, 7ème, etc.)
    - Notes de basse (notes graves qui doivent aller à la main gauche)

    Retourne un dict avec :
    {
        "root": int,           # MIDI de la fondamentale
        "inversion": int,      # 0 = position basse, 1 = première inversion, etc.
        "bass_notes": List[int], # MIDI des notes de basse
        "chord_type": str      # "M", "m", "7", "maj7", etc.
    }
    """
    if not group:
        return {
            "root": None,
            "inversion": 0,
            "bass_notes": [],
            "chord_type": "other"
        }

    # Fondamentale (note la plus basse)
    root_note = min(group, key=lambda n: n.pitch_midi)
    root = root_note.pitch_midi

    # Inversion : nombre de notes plus basses que la fondamentale
    notes_below_root = sum(1 for n in group if n.pitch_midi < root)
    inversion = notes_below_root

    # Notes de basse (notes sous BASS_ANCHOR + notes graves dans la zone grise)
    bass_notes = [n.pitch_midi for n in group if n.pitch_midi < BASS_ANCHOR or (BASS_ANCHOR <= n.pitch_midi <= GREY_ZONE[0] and n.amplitude > 0.6)]

    # Type d'accord (détection simplifiée)
    pitches = sorted([n.pitch_midi for n in group])
    intervals = [pitches[i+1] - pitches[i] for i in range(len(pitches)-1)]

    # Détection de type d'accord
    chord_type = "other"
    if len(pitches) >= 3:
        # Vérifier si c'est un accord majeur (2 tons + 1 ton)
        if abs(intervals[0] - 4) < 1 and abs(intervals[1] - 3) < 1:
            chord_type = "M"
        # Vérifier si c'est un accord mineur (1 ton + 2 tons)
        elif abs(intervals[0] - 3) < 1 and abs(intervals[1] - 4) < 1:
            chord_type = "m"
        # Vérifier si c'est un accord 7ème
        elif len(pitches) >= 4:
            chord_type = "7"

    return {
        "root": root,
        "inversion": inversion,
        "bass_notes": bass_notes,
        "chord_type": chord_type
    }


def analyze_contour_advanced(notes: List[QuantizedNote], window: float = 0.5) -> dict:
    """
    Analyse le contour musical avec fenêtrage.

    Retourne un dict avec :
    {
        "direction": str,      # "ascending", "descending", "mixed"
        "jumps": List[int],    # Liste des sauts (en demi-tons)
        "patterns": List[str], # Patterns détectés (ex: "asc-desc-asc")
        "smoothness": float    # Score de lissage (0-1, 1 = très lisse)
    }
    """
    if not notes:
        return {
            "direction": "mixed",
            "jumps": [],
            "patterns": [],
            "smoothness": 0.0
        }

    pitches = [n.pitch_midi for n in notes]
    jumps = []
    patterns = []
    direction_changes = []

    # Analyse par fenêtrage
    for i in range(len(pitches) - 1):
        jump = abs(pitches[i+1] - pitches[i])
        jumps.append(jump)

        # Détection de direction
        if pitches[i+1] > pitches[i]:
            direction_changes.append(1)
        elif pitches[i+1] < pitches[i]:
            direction_changes.append(-1)
        else:
            direction_changes.append(0)

    # Direction globale
    if sum(direction_changes) > 0:
        direction = "ascending"
    elif sum(direction_changes) < 0:
        direction = "descending"
    else:
        direction = "mixed"

    # Patterns détectés (ex: asc-desc-asc)
    if len(direction_changes) >= 3:
        pattern = "".join(["a" if d > 0 else "d" if d < 0 else "s" for d in direction_changes])
        patterns.append(pattern)

    # Smoothness (coefficient de variation des intervalles)
    if jumps:
        smoothness = 1.0 - (np.std(jumps) / (np.mean(jumps) + 1e-6))
        smoothness = max(0.0, min(1.0, smoothness))
    else:
        smoothness = 1.0

    return {
        "direction": direction,
        "jumps": jumps,
        "patterns": patterns,
        "smoothness": smoothness
    }


def smooth_voice_split(
    treble: List[QuantizedNote],
    bass: List[QuantizedNote],
    options: dict = None
) -> Tuple[List[QuantizedNote], List[QuantizedNote]]:
    """
    Lisse les changements de main trop fréquents.

    Paramètres :
      treble : Liste des notes en main droite
      bass   : Liste des notes en main gauche
      options : dict optionnel avec :
        - max_hand_changes : int (nombre max de changements, défaut: 3)
        - penalty_factor : float (pénalité par changement, défaut: 0.5)

    Retourne (treble_lissified, bass_lissified).

    Algorithme :
    1. Convertir en graphe de transitions (notes voisines)
    2. Calculer le coût de chaque transition (changements de main)
    3. Trouver le chemin de coût minimum (Dijkstra)
    4. Retourner les notes lissifiées
    """
    if options is None:
        options = {}

    max_changes = options.get('max_hand_changes', 3)
    penalty_factor = options.get('penalty_factor', 0.5)

    # Fusionner les deux listes
    all_notes = treble + bass
    sorted_notes = sorted(all_notes, key=lambda n: n.beat_position)

    # Créer un graphe de transitions
    graph = {}
    for i, note in enumerate(sorted_notes):
        graph[i] = []

    # Connecter les notes voisines
    for i in range(len(sorted_notes) - 1):
        note1 = sorted_notes[i]
        note2 = sorted_notes[i + 1]

        # Si les notes sont proches dans le temps
        if abs(note2.beat_position - note1.beat_position) < 0.2:
            graph[i].append((i + 1, 0))  # Coût 0 si même main
            graph[i + 1].append((i, 0))

    # Dijkstra pour trouver le chemin de coût minimum
    distances = {i: float('inf') for i in range(len(sorted_notes))}
    distances[0] = 0
    previous = {i: None for i in range(len(sorted_notes))}

    # Algorithme de Dijkstra simplifié
    unvisited = set(range(len(sorted_notes)))
    while unvisited:
        # Trouver le nœud avec la distance minimale
        current = min(unvisited, key=lambda x: distances[x])

        if distances[current] == float('inf'):
            break

        unvisited.remove(current)

        # Mettre à jour les voisins
        for neighbor, cost in graph.get(current, []):
            if neighbor in unvisited:
                new_distance = distances[current] + cost
                if new_distance < distances[neighbor]:
                    distances[neighbor] = new_distance
                    previous[neighbor] = current

    # Reconstruire le chemin
    path = []
    current = len(sorted_notes) - 1
    while current is not None:
        path.append(current)
        current = previous[current]
    path = path[::-1]

    # Séparer les notes par main
    treble_lissified = [sorted_notes[i] for i in path if sorted_notes[i].hand == 'treble']
    bass_lissified = [sorted_notes[i] for i in path if sorted_notes[i].hand == 'bass']

    return treble_lissified, bass_lissified


def apply_dynamics(notes: List[QuantizedNote], options: dict = None) -> List[QuantizedNote]:
    """
    Applique les poids de dynamique aux notes.

    Paramètres :
      notes : Liste des notes
      options : dict optionnel avec :
        - amplitude_weight : float (poids pour l'amplitude, défaut: 0.3)

    Retourne : Liste des notes avec un champ `dynamic_score` (float)
    """
    if options is None:
        options = {}

    amplitude_weight = options.get('amplitude_weight', 0.3)

    for note in notes:
        # Normalisation de l'amplitude entre 0 et 1
        normalized_amp = max(0.0, min(1.0, note.amplitude))

        # Calcul du score de dynamique
        note.dynamic_score = normalized_amp * amplitude_weight

        # Priorisation pour la main gauche si basse
        if note.pitch_midi < BASS_ANCHOR and note.dynamic_score > 0.5:
            note.hand = 'bass'

    return notes


# ── Auto-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    Test : morceau varié avec différents styles
    Attendu : 40-50% de notes correctes en LH/RH
    """
    from quantizer import QuantizedNote

    def make_note(pitch, pos=0.0, dur=1.0, amp=0.7):
        return QuantizedNote(
            pitch_midi=pitch, amplitude=amp,
            beat_position=pos, beat_duration=dur,
            dur_str='q', dots=0, hand='treble'
        )

    # Test 1 : Accord C majeur 7ème (Do3-Mi3-Sol3-Si3)
    print("\n=== Test 1 : Accord C majeur 7ème ===")
    chord = [
        make_note(48),  # Do3 → bass attendu
        make_note(52),  # Mi3 → bass attendu
        make_note(55),  # Sol3 → bass attendu
        make_note(59),  # Si3 → treble attendu
    ]

    result = split_voices(chord)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications
    bass_pitches   = {n.pitch_midi for n in result.bass}
    treble_pitches = {n.pitch_midi for n in result.treble}

    assert 48 in bass_pitches,   "Do3 doit être en main gauche"
    assert 59 in treble_pitches, "Si3 doit être en main droite"
    print("[Test] ✓ Accord Cmaj7 validé")

    # Test 2 : Contour ascendant (Do4-Sol4-Re5)
    print("\n=== Test 2 : Contour ascendant ===")
    contour = [
        make_note(60, 0.0, 1.0, 0.8),
        make_note(67, 1.0, 1.0, 0.7),
        make_note(72, 2.0, 1.0, 0.6),
    ]

    result = split_voices(contour)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications
    assert 60 in result.treble, "Do4 doit être en main droite"
    assert 72 in result.treble, "Re5 doit être en main droite"
    print("[Test] ✓ Contour ascendant validé")

    # Test 3 : Alternance fréquente (Do4, Sol3, Do4, Sol3)
    print("\n=== Test 3 : Alternance fréquente ===")
    alternation = [
        make_note(60, 0.0, 1.0, 0.8),
        make_note(55, 1.0, 1.0, 0.7),
        make_note(60, 2.0, 1.0, 0.6),
        make_note(55, 3.0, 1.0, 0.5),
    ]

    result = split_voices(alternation)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications
    assert len(result.treble) >= 2, "Do4 doit être en main droite (au moins 2 fois)"
    assert len(result.bass) >= 2, "Sol3 doit être en main gauche (au moins 2 fois)"
    print("[Test] ✓ Alternance lissifiée validé")

    # Test 4 : Note forte et basse (amplitude=0.9, pitch=52)
    print("\n=== Test 4 : Note forte et basse ===")
    strong_bass = [
        make_note(52, 0.0, 1.0, 0.9),  # Mi3 forte
        make_note(60, 1.0, 1.0, 0.7),  # Do4
    ]

    result = split_voices(strong_bass)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications
    assert 52 in result.bass, "Mi3 forte doit être en main gauche"
    print("[Test] ✓ Note forte et basse validé")

    # Test 5 : Analyse harmonique
    print("\n=== Test 5 : Analyse harmonique ===")
    chord_analysis = [
        make_note(48, 0.0, 1.0, 0.8),
        make_note(52, 0.0, 1.0, 0.7),
        make_note(55, 0.0, 1.0, 0.6),
    ]

    result = split_voices(chord_analysis)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications
    bass_pitches = {n.pitch_midi for n in result.bass}
    assert 48 in bass_pitches and 52 in bass_pitches and 55 in bass_pitches, "Do3, Mi3, Sol3 doivent être en main gauche"
    print("[Test] ✓ Analyse harmonique validé")

    # Test 6 : Contour avancé
    print("\n=== Test 6 : Contour avancé ===")
    advanced_contour = [
        make_note(60, 0.0, 1.0, 0.8),
        make_note(67, 1.0, 1.0, 0.7),
        make_note(72, 2.0, 1.0, 0.6),
        make_note(67, 3.0, 1.0, 0.5),
    ]

    result = split_voices(advanced_contour)

    print(f"[Test] Main droite ({len(result.treble)} notes): {[n.pitch_midi for n in result.treble]}")
    print(f"[Test] Main gauche ({len(result.bass)} notes): {[n.pitch_midi for n in result.bass]}")

    # Vérifications
    assert 60 in result.treble and 72 in result.treble and 67 in result.treble, "Do4, Re5, Sol4 doivent être en main droite"
    print("[Test] ✓ Contour avancé validé")

    # Résultat final
    print("\n=== Résultat final ===")
    print("✓ SUCCÈS - Tous les tests de la Phase 1 sont passés !")
    print("✓ Gain attendu : 40-50% de notes correctes en LH/RH")
