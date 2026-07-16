"""
note_filter.py — Filtres post-transcription pour nettoyer les artefacts IA
Version : 4.0

Responsabilités :
- filter_ghost_notes : Supprime les notes parasites (très courtes, très faibles, 
  incohérentes harmoniquement).
- apply_pedal_aware_shortening : Raccourcit visuellement les notes tenues très 
  longtemps si la pédale forte (CC64) est enfoncée, pour alléger la partition.
"""

def filter_ghost_notes(notes: list[dict], options: dict) -> list[dict]:
    """
    Supprime les notes parasites (fantômes) générées par l'IA.
    
    Critères d'élimination (combinés) :
    - Durée extrêmement courte (< 50ms) ET faible vélocité.
    - Notes très isolées.
    
    Args:
        notes: liste de dict {'onset': float, 'pitch': int, 'duration': float, 'velocity': float}
        options: Dictionnaire d'options (ex: 'min_velocity', 'min_duration')
        
    Returns:
        Liste filtrée.
    """
    min_velocity = options.get("ghost_min_velocity", 0.1) # 0-1
    min_duration = options.get("ghost_min_duration", 0.05) # en secondes
    
    filtered = []
    for n in notes:
        # Éliminer les notes inaudibles et très courtes
        if n['velocity'] < min_velocity and n['duration'] < min_duration:
            continue
        filtered.append(n)
        
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
