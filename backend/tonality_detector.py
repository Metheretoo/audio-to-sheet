"""
Tonality Detector V3 — Krumhansl-Schmuckler + Parncutt

Utilise la transformée de Fourier sur les frames audio pour estimer
la tonalité (key) et la mode (major/minor) d'un segment audio.

Retourne un dict:
{
    "key": "C", "D#", ...  (12 pitches)
    "mode": "major" | "minor"
    "confidence": float 0-1
    "profile": list[float]  # corrélations K-S pour les 12 hauteurs
}
"""

import numpy as np
from typing import Dict, List, Tuple, Optional

# ─── Krumhansl-Schmuckler profiles (normalized) ────────────────────────────────
MAJOR_PROFILE = [
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
    2.52, 3.54, 2.36, 3.17, 2.88, 3.32
]

MINOR_PROFILE = [
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
    4.57, 2.48, 3.70, 4.77, 3.18, 2.30
]


def _normalize_vector(v: np.ndarray) -> np.ndarray:
    """Normalise un vecteur à la norme L2."""
    norm = np.linalg.norm(v)
    if norm < 1e-10:
        return v
    return v / norm


def _compute_autocorrelation(spec: np.ndarray) -> np.ndarray:
    """
    Autocorrélation du spectre pour lisser les proils de hauteur.
    
    Args:
        spec: FFT magnitudes (1D array)
    
    Returns:
        Autocorrelation lissée
    """
    # Convoluer avec un noyau gaussien pour lisser
    kernel_size = 7
    sigma = 1.5
    x = np.arange(kernel_size) - kernel_size // 2
    kernel = np.exp(-x**2 / (2 * sigma**2))
    kernel /= kernel.sum()
    
    smoothed = np.convolve(spec, kernel, mode='same')
    return smoothed


def _get_pianochord_corr(
    spectrum: np.ndarray,
    profile: List[float],
    rotation: int
) -> float:
    """
    Calcule la corrélation entre le spectre et le profil K-S tourné.
    
    Args:
        spectrum: Vecteur de magnitudes FFT (12 valeurs)
        profile: Profil Krumhansl-Schmuckler (major ou minor)
        rotation: Nombre de rotations circulaires
    
    Returns:
        Coefficient de corrélation
    """
    # Extraire les 12 hauteurs du spectre (chroma features)
    # Chaque hauteur = somme des magnitudes sur les octaves pour cette note
    chroma = np.zeros(12)
    notes_per_octave = len(spectrum) // 12
    
    for i in range(12):
        start = i * notes_per_octave
        end = start + notes_per_octave
        chroma[i] = np.sum(spectrum[start:end])
    
    # Tourner le profil
    rotated_profile = np.roll(profile, rotation)
    
    # Corrélation de Pearson
    if np.linalg.norm(chroma) < 1e-10 or np.linalg.norm(rotated_profile) < 1e-10:
        return 0.0
    
    corr = np.dot(chroma, rotated_profile) / (
        np.linalg.norm(chroma) * np.linalg.norm(rotated_profile)
    )
    
    return float(corr)


def detect_key_mode(
    audio_segment: np.ndarray,
    sr: int
) -> Dict:
    """
    Détecte la tonalité et le mode d'un segment audio.
    
    Args:
        audio_segment: Tableau d'audio (mono, normalisé -1 à 1)
        sr: Sample rate (ex: 22050)
    
    Returns:
        Dict avec key, mode, confidence, profile
    """
    if len(audio_segment) == 0:
        return {
            "key": "C",
            "mode": "major",
            "confidence": 0.0,
            "profile": [0.0] * 12
        }
    
    # ── 1. FFT ──
    n_fft = 4096
    magnitudes = np.abs(
        np.fft.rfft(audio_segment[:n_fft])
    )
    
    # ── 2. Lissage ──
    smoothed = _compute_autocorrelation(magnitudes)
    
    # ── 3. Meilleure corrélation (Krumhansl-Schmuckler) ──
    keys = ["C", "C#", "D", "D#", "E", "F",
            "F#", "G", "G#", "A", "A#", "B"]
    
    best_major_corr = -float('inf')
    best_minor_corr = -float('inf')
    major_key = 0
    minor_key = 0
    
    for rot in range(12):
        corr_m = _get_pianochord_corr(smoothed, MAJOR_PROFILE, rot)
        if corr_m > best_major_corr:
            best_major_corr = corr_m
            major_key = rot
        
        corr_mi = _get_pianochord_corr(smoothed, MINOR_PROFILE, rot)
        if corr_mi > best_minor_corr:
            best_minor_corr = corr_mi
            minor_key = rot
    
    # ── 4. Décision Major vs Minor ──
    if best_major_corr > best_minor_corr:
        key = keys[major_key]
        mode = "major"
        confidence = float(best_major_corr)
        profile = [float(x) for x in np.roll(MAJOR_PROFILE, major_key)]
    else:
        key = keys[minor_key]
        mode = "minor"
        confidence = float(best_minor_corr)
        profile = [float(x) for x in np.roll(MINOR_PROFILE, minor_key)]
    
    # Normaliser la confiance
    confidence = min(max(confidence / 5.0, 0.0), 1.0)
    
    return {
        "key": key,
        "mode": mode,
        "confidence": round(confidence, 4),
        "profile": profile
    }


def detect_key_from_audio(
    audio_path: str,
    segment_duration: float = 10.0,
    sr: int = 22050
) -> Dict:
    """
    Détecte la tonalité depuis un fichier audio.
    
    Args:
        audio_path: Chemin vers le fichier audio
        segment_duration: Durée du segment à analyser (sec)
        sr: Sample rate
    
    Returns:
        Dict avec key, mode, confidence, profile
    """
    try:
        import soundfile as sf
        audio, file_sr = sf.read(
            audio_path,
            start=0,
            duration=segment_duration,
            dtype='float32'
        )
        
        # Convertir en mono si stéréo
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        
        # Resample si nécessaire
        if file_sr != sr:
            import librosa
            audio = librosa.resample(audio, file_sr, sr)
        
        return detect_key_mode(audio, sr)
    
    except ImportError:
        # Fallback: retourne C major par défaut
        return {
            "key": "C",
            "mode": "major",
            "confidence": 0.0,
            "profile": [0.0] * 12
        }


def detect_tonality(note_events, audio_path=None, sr=22050):
    """
    Détecte la tonalité à partir de notes MIDI ou d'un fichier audio.
    
    Cette fonction est l'interface principale appelée par le pipeline.
    
    Args:
        note_events: Liste d'événements notes (tuple ou dict) avec clé 'midi_note'
        audio_path: Chemin optionnel vers le fichier audio original
        sr: Sample rate si audio_path est fourni
    
    Returns:
        Dict avec key, mode, confidence, scale, profile
    """
    # Si des notes MIDI sont fournies, les utiliser pour la détection
    if note_events and len(note_events) > 0:
        return detect_key_from_notes(note_events)
    
    # Fallback: utiliser le fichier audio
    if audio_path:
        result = detect_key_from_audio(audio_path, sr=sr)
        result['scale'] = result.get('mode', 'major')
        return result
    
    # Default
    return {
        "key": "C",
        "mode": "major",
        "scale": "major",
        "confidence": 0.0,
        "profile": [0.0] * 12
    }


def detect_key_from_notes(note_events):
    """
    Détecte la tonalité à partir d'un ensemble de notes MIDI.
    
    Utilise la distribution des hauteurs (pitch class distribution)
    pour déterminer la tonalité la plus probable.
    
    Args:
        note_events: Liste d'événements avec clé 'midi_note' (valeur MIDI 0-127)
    
    Returns:
        Dict avec key, mode, confidence, scale, profile
    """
    # Compter les pitch classes (notes sans octave)
    pitch_class_counts = [0] * 12
    for event in note_events:
        if isinstance(event, dict):
            midi_note = event.get('midi_note', event.get('pitch_midi', 0))
        elif isinstance(event, (list, tuple)):
            # Format V3 : (onset_sec, pitch_midi, duration_sec, velocity)
            midi_note = int(event[1])
        else:
            continue
        
        # Extraire la pitch class (note dans une octave)
        pc = int(midi_note) % 12
        pitch_class_counts[pc] += 1
    
    # Normaliser le vecteur
    total = sum(pitch_class_counts)
    if total == 0:
        return {
            "key": "C",
            "mode": "major",
            "scale": "major",
            "confidence": 0.0,
            "profile": [0.0] * 12
        }
    
    chroma = np.array(pitch_class_counts, dtype=float) / total
    
    # Lisser avec un noyau gaussien
    kernel_size = 5
    sigma = 0.8
    x = np.arange(kernel_size) - kernel_size // 2
    kernel = np.exp(-x**2 / (2 * sigma**2))
    kernel /= kernel.sum()
    chroma_smoothed = np.convolve(chroma, kernel, mode='same')
    
    # Trouver la meilleure corrélation avec les profils K-S
    keys = ["C", "C#", "D", "D#", "E", "F",
            "F#", "G", "G#", "A", "A#", "B"]
    
    best_major_corr = -float('inf')
    best_minor_corr = -float('inf')
    major_key = 0
    minor_key = 0
    
    for rot in range(12):
        # Corrélation avec profil majeur
        rotated_major = np.roll(MAJOR_PROFILE, rot)
        corr_m = np.dot(chroma_smoothed, rotated_major) / (
            np.linalg.norm(chroma_smoothed) * np.linalg.norm(rotated_major) + 1e-10
        )
        if corr_m > best_major_corr:
            best_major_corr = corr_m
            major_key = rot
        
        # Corrélation avec profil mineur
        rotated_minor = np.roll(MINOR_PROFILE, rot)
        corr_mi = np.dot(chroma_smoothed, rotated_minor) / (
            np.linalg.norm(chroma_smoothed) * np.linalg.norm(rotated_minor) + 1e-10
        )
        if corr_mi > best_minor_corr:
            best_minor_corr = corr_mi
            minor_key = rot
    
    # Décision Major vs Minor
    if best_major_corr > best_minor_corr:
        key = keys[major_key]
        mode = "major"
        scale = "major"
        confidence = float(best_major_corr)
        profile = [float(x) for x in np.roll(MAJOR_PROFILE, major_key)]
    else:
        key = keys[minor_key]
        mode = "minor"
        scale = "minor"
        confidence = float(best_minor_corr)
        profile = [float(x) for x in np.roll(MINOR_PROFILE, minor_key)]
    
    # Normaliser la confiance
    confidence = min(max(confidence / 5.0, 0.0), 1.0)
    
    return {
        "key": key,
        "mode": mode,
        "scale": scale,
        "confidence": round(confidence, 4),
        "profile": profile
    }