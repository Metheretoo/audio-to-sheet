"""
note_filter.py — Filtres post-transcription pour nettoyer les artefacts IA
Version : 5.0

Responsabilités :
- filter_ghost_notes : Supprime les notes parasites (très courtes, très faibles, 
  incohérentes harmoniquement).
- apply_pedal_aware_shortening : Raccourcit visuellement les notes tenues très 
  longtemps si la pédale forte (CC64) est enfoncée, pour alléger la partition.
- _is_protected_bass_note : Vérifie si une note grave est protégée (main gauche).
"""

# Seuil par défaut pour la protection basse (vélocité normalisée 0-1)
# Les notes graves en dessous de ce seuil sont considérées comme des basses légitimes
# et ne sont JAMAIS supprimées par le filtrage.
#
# PROTECTION PROGRESSIVE (pondération) :
# - velocity < 0.15  → protection maximale (basses jouées doucement)
# - velocity 0.15-0.30 → protection forte (basses jouées normalement)  
# - velocity 0.30-0.50 → protection réduite mais présente
# - velocity > 0.50  → protection faible (notes mélodiques aiguës)
BASS_PROTECTION_THRESHOLD = 0.35

# Pitch MIDI en dessous duquel on considère une note comme "grave"
# Ajusté de 36 (C1) à 55 (B1) : la zone de basse du piano s'étend jusqu'à B1
BASS_PITCH_CUTOFF = 55


def _get_bass_protection_threshold(options: dict) -> float:
    """
    Récupère le seuil de protection basse depuis les options.
    
    Args:
        options: Dictionnaire d'options contenant éventuellement 'bass_protection_velocity'
        
    Returns:
        float: Seuil de vélocité normalisé (0-1)
    """
    # Lire le seuil depuis options (transmis par l'UI via server.py)
    bass_vel = options.get('bass_protection_velocity', None)
    if bass_vel is not None:
        return float(bass_vel)
    return BASS_PROTECTION_THRESHOLD


def _is_protected_bass_note(note: dict, options: dict) -> bool:
    """
    Vérifie si une note grave est protégée (main gauche légitime).
    
    Une note est protégée si :
    1. Son pitch est en dessous de BASS_PITCH_CUTOFF (grave)
    2. Sa vélocité est en dessous du seuil de protection basse
       (car les basses jouées normalement ont une vélocité plus faible)
    
    PROTECTION PROGRESSIVE :
    - velocity < seuil * 0.35  → protection maximale (basses jouées doucement)
    - velocity seuil * 0.35-0.50 → protection forte (basses jouées normalement)
    - velocity > seuil * 0.50  → protection réduite mais présente
    
    Args:
        note: dict avec clés 'pitch' et 'velocity'
        options: Dictionnaire d'options
    
    Returns:
        bool: True si la note est protégée et ne doit pas être supprimée
    """
    # Vérifier si c'est une note grave
    if note.get('pitch', 60) >= BASS_PITCH_CUTOFF:
        return False
    
    # Obtenir le seuil de protection
    threshold = _get_bass_protection_threshold(options)
    
    # Seuil bas : en dessous de 35% du seuil → protection minimale
    low_threshold = threshold * 0.35
    
    # Vérifier si la vélocité est en dessous du seuil bas
    # (les basses jouées normalement ont une vélocité plus faible)
    if note.get('velocity', 1.0) <= low_threshold:
        return True
    
    # Même si la vélocité est plus élevée, on protège les basses très graves (< 24 = Do0)
    # car elles sont presque toujours jouées à la main gauche
    if note.get('pitch', 60) < 24:
        return True
    
    return False


def filter_ghost_notes(notes: list[dict], options: dict) -> list[dict]:
    """
    Supprime les notes parasites (fantômes) générées par l'IA.
    
    Critères d'élimination (combinés) :
    - Durée extrêmement courte (< 50ms) ET faible vélocité.
    - Notes très isolées.
    
    PROTECTION BASSE : Les notes graves protégées (main gauche) sont JAMAIS supprimées,
    même si elles répondent aux critères d'élimination.
    
    Args:
        notes: liste de dict {'onset': float, 'pitch': int, 'duration': float, 'velocity': float}
        options: Dictionnaire d'options (ex: 'min_velocity', 'min_duration', 'bass_protection_velocity')
        
    Returns:
        Liste filtrée.
    """
    min_velocity = options.get("ghost_min_velocity", 0.1) # 0-1
    min_duration = options.get("ghost_min_duration", 0.05) # en secondes
    
    filtered = []
    protected_count = 0
    removed_count = 0
    
    for n in notes:
        # [NOUVEAU] Vérifier si la note est protégée (basse main gauche)
        if _is_protected_bass_note(n, options):
            filtered.append(n)
            protected_count += 1
            continue
        
        # Éliminer les notes inaudibles et très courtes (UNIQUEMENT si non protégée)
        if n['velocity'] < min_velocity and n['duration'] < min_duration:
            removed_count += 1
            continue
        filtered.append(n)
    
    if protected_count > 0 or removed_count > 0:
        print(f"[note_filter] filter_ghost_notes: {removed_count} notes supprimées, {protected_count} basses protégées")
        
    return filtered

def apply_pedal_aware_shortening(notes: list[dict], pedals: list[tuple[float, float]], options: dict) -> list[dict]:
    """
    Raccourcit les notes qui durent longtemps artificiellement à cause de la pédale.
    
    En musique classique/piano, on n'écrit pas une ronde liée à une blanche si la pédale 
    est enfoncée, on écrit juste une noire (ou blanche) et on indique la pédale.
    
    Algorithme :
    Pour chaque note, si elle s'étend largement dans une zone de pédale, 
    et qu'elle dépasse un seuil de durée visuelle, on peut la raccourcir 
    à une durée plus lisible (ex: 1 seconde max, ou jusqu'au prochain changement harmonique).
    
    Args:
        notes: liste de dict {'onset': float, 'pitch': int, 'duration': float, 'velocity': float}
        pedals: liste de tuples (start_time, end_time) en secondes
        options: Dictionnaire d'options (ex: 'max_visual_duration')
        
    Returns:
        Liste avec durées potentiellement raccourcies.
    """
    if not pedals:
        return notes
        
    max_visual_duration = options.get("pedal_max_visual_duration", 1.0) # secondes
    
    # Trier les pédales pour recherche rapide
    pedals.sort(key=lambda x: x[0])
    
    result = []
    for n in notes:
        onset = n['onset']
        duration = n['duration']
        end = onset + duration
        
        # Chercher si la note commence dans une zone de pédale
        in_pedal = False
        pedal_end = None
        for p_start, p_end in pedals:
            if p_start <= onset <= p_end:
                in_pedal = True
                pedal_end = p_end
                break
            elif p_start > onset:
                break
                
        # Si la note est très longue et couverte par la pédale, on la raccourcit visuellement
        new_duration = duration
        if in_pedal and duration > max_visual_duration:
            # On raccourcit à max_visual_duration, sauf si la pédale se lève avant
            # auquel cas la note s'arrête naturellement au lever de pédale (ou on garde la durée max)
            limit = min(onset + max_visual_duration, pedal_end)
            new_duration = max(limit - onset, 0.1) # min 100ms
            
        result.append({
            'onset': onset,
            'pitch': n['pitch'],
            'duration': new_duration,
            'velocity': n['velocity']
        })
        
    return result
