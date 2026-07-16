"""
tempo_map.py â€” DÃ©tection dynamique du tempo et construction de la TempoMap
Version : 2.0 (audio-to-sheet V2)

StratÃ©gie de dÃ©tection (par ordre de prÃ©fÃ©rence) :
  1. madmom RNNBeatProcessor  â€” le plus prÃ©cis pour la musique expressive
  2. librosa avancÃ© (onset_envelope + start_bpm estimÃ©) â€” fallback robuste
  3. IOI basique sur note_events â€” dernier recours identique Ã  V1

Interface publique :
  build_tempo_map(audio_path, note_events=None) -> TempoMap
  TempoMap.seconds_to_beat(t_seconds) -> float
  TempoMap.beat_to_seconds(beat)      -> float
  TempoMap.local_bpm_at(t_seconds)   -> float
"""

import numpy as np
import logging
from dataclasses import dataclass
from typing import Tuple, Optional, List

logger = logging.getLogger(__name__)

# â”€â”€ Dataclass principale â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class TempoMap:
    """
    ReprÃ©sentation dynamique du tempo d'un morceau.

    beat_times      : array 1D des timestamps (secondes) de chaque beat dÃ©tectÃ©
    downbeat_times  : array 1D des timestamps des temps forts (dÃ©but de mesure)
    estimated_meter : tuple (numÃ©rateur, dÃ©nominateur), ex: (4, 4)
    global_bpm      : BPM mÃ©dian sur tout le morceau
    method          : mÃ©thode ayant produit la TempoMap
    """
    beat_times:      np.ndarray
    downbeat_times:  np.ndarray
    estimated_meter: Tuple[int, int]
    global_bpm:      float
    method:          str

    def seconds_to_beat(self, t_seconds: float) -> float:
        """
        Convertit un timestamp absolu (secondes) en position de beat fractionnaire.

        Algorithme :
        - Recherche des deux beats encadrant t_seconds
        - Interpolation linÃ©aire entre eux
        - Extrapolation linÃ©aire si t_seconds est avant le 1er ou aprÃ¨s le dernier beat

        Exemple :
          beat_times = [0.0, 0.52, 1.01, 1.55]
          seconds_to_beat(0.48) â†’ 0.923  (proche du beat 1)
          seconds_to_beat(0.52) â†’ 1.000  (exactement sur le beat 1)
        """
        bt = self.beat_times

        if len(bt) == 0:
            # Fallback : division linÃ©aire simple
            beat_s = 60.0 / max(self.global_bpm, 20)
            return t_seconds / beat_s

        if len(bt) == 1:
            beat_s = 60.0 / max(self.global_bpm, 20)
            return (t_seconds - bt[0]) / beat_s + 0.0

        # Extrapolation avant le 1er beat
        if t_seconds <= bt[0]:
            dt = bt[1] - bt[0]
            return (t_seconds - bt[0]) / dt

        # Extrapolation aprÃ¨s le dernier beat
        if t_seconds >= bt[-1]:
            dt = bt[-1] - bt[-2]
            frac = (t_seconds - bt[-1]) / dt
            return float(len(bt) - 1) + frac

        # Interpolation â€” trouver l'index encadrant
        idx = int(np.searchsorted(bt, t_seconds, side='right')) - 1
        idx = max(0, min(idx, len(bt) - 2))

        t0, t1 = bt[idx], bt[idx + 1]
        frac = (t_seconds - t0) / (t1 - t0) if (t1 - t0) > 0 else 0.0
        return float(idx) + frac

    def beat_to_seconds(self, beat: float) -> float:
        """
        Inverse de seconds_to_beat.
        Convertit une position de beat fractionnaire en timestamp (secondes).
        """
        bt = self.beat_times

        if len(bt) == 0:
            beat_s = 60.0 / max(self.global_bpm, 20)
            return beat * beat_s

        if len(bt) == 1:
            beat_s = 60.0 / max(self.global_bpm, 20)
            return bt[0] + beat * beat_s

        # Extrapolation avant le 1er beat
        if beat <= 0.0:
            dt = bt[1] - bt[0]
            return bt[0] + beat * dt

        # Extrapolation aprÃ¨s le dernier beat
        if beat >= len(bt) - 1:
            dt = bt[-1] - bt[-2]
            extra = beat - (len(bt) - 1)
            return bt[-1] + extra * dt

        # Interpolation
        idx   = int(beat)
        frac  = beat - idx
        idx   = max(0, min(idx, len(bt) - 2))
        t0, t1 = bt[idx], bt[idx + 1]
        return t0 + frac * (t1 - t0)

    def local_bpm_at(self, t_seconds: float) -> float:
        """
        Retourne le BPM local Ã  un instant donnÃ©.
        Utile pour dÃ©tecter les zones de ritardando.
        """
        bt = self.beat_times
        if len(bt) < 2:
            return self.global_bpm

        if t_seconds <= bt[0]:
            return 60.0 / max(bt[1] - bt[0], 0.01)
        if t_seconds >= bt[-1]:
            return 60.0 / max(bt[-1] - bt[-2], 0.01)

        idx = int(np.searchsorted(bt, t_seconds, side='right')) - 1
        idx = max(0, min(idx, len(bt) - 2))
        dt = bt[idx + 1] - bt[idx]
        return 60.0 / max(dt, 0.01)

    def tempo_range(self) -> Tuple[float, float]:
        """Retourne (BPM_min, BPM_max) observÃ©s sur le morceau."""
        if len(self.beat_times) < 2:
            return (self.global_bpm, self.global_bpm)
        iois = np.diff(self.beat_times)
        iois = iois[iois > 0.1]  # filtrer les beats aberrants
        if len(iois) == 0:
            return (self.global_bpm, self.global_bpm)
        bpms = 60.0 / iois
        # Lissage par moyenne mobile sur 4 beats (1 mesure env.) pour éliminer les micro-variations extrêmes
        if len(bpms) >= 4:
            smoothed = np.convolve(bpms, np.ones(4)/4.0, mode='valid')
        else:
            smoothed = bpms
            
        return (float(np.percentile(smoothed, 5)), float(np.percentile(smoothed, 95)))


# â”€â”€ Fonction principale â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_tempo_map(
    audio_path: str,
    note_events: Optional[list] = None,
    start_bpm: Optional[float] = None
) -> TempoMap:
    """
    Construit une TempoMap dynamique depuis un fichier audio.

    Ordre de tentative :
      1. madmom  (RNN beat tracker — le plus précis)
      2. librosa avancé (onset_envelope)
      3. Fallback IOI sur note_events (identique à V1, sans amélioration drift)

    Paramètres :
      audio_path   : chemin absolu vers le fichier audio (MP3, WAV, FLAC)
      note_events  : optionnel — utilisé pour le fallback IOI
      start_bpm    : hint de BPM pour guider l'algorithme

    Retourne : TempoMap
    """
    import traceback

    # Tentative 1 : madmom
    try:
        # --- Monkey-patch numpy for legacy madmom (removed in numpy 1.24) ---
        if not hasattr(np, 'float'):
            np.float = float
        if not hasattr(np, 'bool'):
            np.bool = np.bool_
        if not hasattr(np, 'complex'):
            np.complex = complex
        if not hasattr(np, 'object'):
            np.object = object
        if not hasattr(np, 'int'):
            np.int = int
        # --------------------------------------------------------------------
        
        from madmom.features.beats import RNNBeatProcessor  # noqa — verif import
        result = _build_with_madmom(audio_path, start_bpm=start_bpm)
        logger.info(f"[TempoMap] OK madmom -- BPM={result.global_bpm:.1f}, "
              f"mesure={result.estimated_meter}, beats={len(result.beat_times)}")
        return result
    except ImportError as e:
        logger.warning(f"[TempoMap] madmom non disponible, repli sur librosa avance: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[TempoMap] madmom a echoue ({type(e).__name__}: {e})", exc_info=True)
        logger.info("[TempoMap] repli sur librosa")

    # Tentative 2 : librosa avancÃ©
    try:
        result = _build_with_librosa(audio_path, start_bpm=start_bpm)
        logger.info(f"[TempoMap] OK librosa_advanced -- BPM={result.global_bpm:.1f}, "
              f"mesure={result.estimated_meter}, beats={len(result.beat_times)}")
        return result
    except Exception as e:
        logger.error(f"[TempoMap] librosa a echoue ({type(e).__name__}: {e})", exc_info=True)
        logger.info("[TempoMap] repli sur fallback IOI")

    # Tentative 3 : fallback IOI
    result = _build_fallback(note_events, start_bpm=start_bpm)
    logger.info(f"[TempoMap] ATTENTION fallback IOI -- BPM={result.global_bpm:.1f} (drift non corrige)")
    return result


# â”€â”€ ImplÃ©mentations des stratÃ©gies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_with_madmom(audio_path: str, start_bpm: Optional[float] = None) -> TempoMap:
    """
    Beat tracking avec madmom RNN.
    Utilise DBNBeatTrackingProcessor pour les beats et
    DBNDownBeatTrackingProcessor pour les downbeats.
    """
    from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor

    # Beat tracking
    if start_bpm:
        proc_beat = DBNBeatTrackingProcessor(fps=100, min_bpm=start_bpm*0.8, max_bpm=start_bpm*1.2)
    else:
        proc_beat = DBNBeatTrackingProcessor(fps=100)
    act_beat  = RNNBeatProcessor()(audio_path)
    beat_times = np.array(proc_beat(act_beat), dtype=float)

    if len(beat_times) < 2:
        raise ValueError("madmom n'a pas dÃ©tectÃ© suffisamment de beats")

    # Downbeat tracking pour la mesure
    downbeat_times = _detect_downbeats_madmom(audio_path, beat_times)
    meter = _detect_meter(beat_times, downbeat_times)

    # BPM médian (robuste aux outliers)
    iois = np.diff(beat_times)
    iois = iois[(iois > 0.15) & (iois < 3.0)]  # filtrer les IOI aberrants
    global_bpm = float(np.median(60.0 / iois)) if len(iois) > 0 else 120.0

    # Correction de l'octave du tempo (si le tracker a divisé par 2)
    if start_bpm and global_bpm < start_bpm * 0.75:
        new_beats = []
        for i in range(len(beat_times) - 1):
            new_beats.append(beat_times[i])
            new_beats.append((beat_times[i] + beat_times[i+1]) / 2.0)
        new_beats.append(beat_times[-1])
        beat_times = np.array(new_beats)
        
        # Recalculer le downbeat si on a doublé la grille (facultatif, mais plus précis)
        downbeat_times = _detect_downbeats_madmom(audio_path, beat_times)
        meter = _detect_meter(beat_times, downbeat_times)
        
        iois = np.diff(beat_times)
        iois = iois[(iois > 0.15) & (iois < 3.0)]
        global_bpm = float(np.median(60.0 / iois)) if len(iois) > 0 else 120.0

    return TempoMap(
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        estimated_meter=meter,
        global_bpm=global_bpm,
        method='madmom'
    )


def _estimate_bar_length(audio_path: str, beat_times: np.ndarray) -> int:
    """
    Estime le nombre de temps par mesure (2, 3, 4 ou 6) à partir de l'intensité
    sonore (onset strength) à chaque position de beat : le 1er temps d'une
    mesure est en général plus accentué que les suivants, on cherche donc la
    période qui maximise ce contraste d'accentuation.

    BUG CORRIGÉ (v4.2) : les fallbacks précédents ("Mazurka toujours détectée
    en 4/4") découpaient AVEUGLÉMENT les beats par groupes de 4
    (`beat_times[::4]`) dès que madmom échouait ou n'était pas utilisé,
    forçant artificiellement (4, 4) en sortie de `_detect_meter`, quelle que
    soit la vraie mesure du morceau. Une Mazurka (3/4) n'avait donc AUCUNE
    chance d'être détectée correctement, même avec la détection automatique
    activée. music21 (utilisé pour la tonalité) n'intervient pas ici : le
    repérage de la mesure dépend uniquement du suivi audio (ce module).
    """
    if len(beat_times) < 8:
        return 4
    try:
        import librosa
        y, sr = librosa.load(audio_path, sr=None, mono=True)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
        onset_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr)

        def _strength_at(t, window=0.07):
            # Maximum local dans une fenêtre de ±70ms autour du beat : plus
            # robuste qu'une valeur ponctuelle (sensible au moindre décalage
            # entre le temps du beat et la frame d'onset la plus proche).
            mask = (onset_times >= t - window) & (onset_times <= t + window)
            if not np.any(mask):
                idx = int(np.searchsorted(onset_times, t))
                idx = min(max(idx, 0), len(onset_env) - 1)
                return float(onset_env[idx])
            return float(np.max(onset_env[mask]))

        strengths = np.array([_strength_at(t) for t in beat_times])
        overall_mean = float(np.mean(strengths)) if len(strengths) > 0 else 1.0

        # NOTE (v4.2) : on compare le 1er temps de chaque groupe candidat aux
        # autres (hypothèse standard : le 1er temps d'une mesure est le plus
        # accentué — vrai pour la grande majorité des musiques). Une
        # recherche exhaustive de déphasage a été tentée pour couvrir les cas
        # atypiques (ex: la Mazurka, qui accentue traditionnellement le 2ᵉ
        # temps), mais s'est révélée numériquement instable (biais de
        # comparaisons multiples favorisant les grands n, erreurs d'octave
        # rythmique). Pour ces cas particuliers, mieux vaut un override manuel
        # de la mesure (fonctionnel, cf. case "Détection automatique") que
        # cette heuristique. On garde donc l'approche simple, plus fiable sur
        # le cas standard, avec une normalisation numériquement sûre (BUG
        # CORRIGÉ : diviser par l'écart-type des "autres temps" explosait
        # pour n=2, qui n'a qu'une seule valeur "autre" — écart-type nul).
        best_n, best_score = 4, -1.0
        for n in (2, 3, 4, 6):
            if len(strengths) < n * 2:
                continue
            group_means = [float(np.mean(strengths[i::n])) for i in range(n)]
            accented_strength = group_means[0]
            others_avg = float(np.mean(group_means[1:]))
            contrast = (accented_strength - others_avg) / (overall_mean + 1e-6)
            if contrast > best_score:
                best_score = contrast
                best_n = n
        return best_n
    except Exception as e:
        logger.info(f"[TempoMap] Estimation du nombre de temps/mesure échouée ({e}), repli sur 4")
        return 4


def _detect_downbeats_madmom(audio_path: str, beat_times: np.ndarray) -> np.ndarray:
    """
    Détecte les downbeats (temps forts) avec madmom.
    En cas d'échec, estime la mesure réelle via l'intensité sonore plutôt que
    de forcer aveuglément des groupes de 4 (cf. _estimate_bar_length).
    """
    try:
        from madmom.features.downbeats import (
            RNNDownBeatProcessor,
            DBNDownBeatTrackingProcessor,
        )
        proc_db = DBNDownBeatTrackingProcessor(beats_per_bar=[2, 3, 4], fps=100)
        act_db  = RNNDownBeatProcessor()(audio_path)
        downbeats_raw = proc_db(act_db)  # array [(time, beat_in_bar), ...]

        # Extraire uniquement les downbeats (beat_in_bar == 1)
        downbeat_times = np.array(
            [row[0] for row in downbeats_raw if int(row[1]) == 1],
            dtype=float
        )
        if len(downbeat_times) > 0:
            return downbeat_times
    except Exception as e:
        logger.info(f"[TempoMap] Downbeat detection échouée ({e}), fallback heuristique")

    # Fallback heuristique : estimer le nombre réel de temps par mesure
    # (BUG CORRIGÉ v4.2 : n'est plus figé à 4)
    n = _estimate_bar_length(audio_path, beat_times)
    if len(beat_times) >= n:
        return beat_times[::n]
    return beat_times[:1] if len(beat_times) > 0 else np.array([0.0])


def _build_with_librosa(audio_path: str, start_bpm: Optional[float] = None) -> TempoMap:
    """
    Beat tracking avec librosa en mode avancÃ©.

    AmÃ©liorations vs V1 :
    - Utilise onset_envelope avec aggregate=np.median (plus robuste)
    - Passe start_bpm estimÃ© pour rÃ©duire les erreurs d'octave (94 vs 138)
    - Trim les silences initiaux pour une meilleure ancre de tempo
    """
    import librosa

    logger.info("[TempoMap] Chargement audio pour librosa...")
    y, sr = librosa.load(audio_path, sr=None, mono=True)

    # Trim les silences de dÃ©but et calculer le dÃ©calage
    y_trimmed, index = librosa.effects.trim(y, top_db=40)
    start_silence_s = float(index[0]) / sr

    # Onset strength avec agrÃ©gation mÃ©diane (plus robuste que la moyenne)
    onset_env = librosa.onset.onset_strength(
        y=y_trimmed, sr=sr,
        aggregate=np.median,
        fmax=8000  # limiter aux frÃ©quences pertinentes pour piano
    )

    # Estimation prÃ©liminaire du tempo (pour Ã©viter les erreurs d'octave)
    if start_bpm:
        tempo_preliminary = start_bpm
    else:
        tempo_preliminary = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)[0]

        # Si tempo hors plage plausible, corriger par doublement/division
        while tempo_preliminary < 50:
            tempo_preliminary *= 2
        while tempo_preliminary > 220:
            tempo_preliminary /= 2

    # Beat tracking avec start_bpm ancrÃ© sur l'estimation prÃ©liminaire
    _, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        start_bpm=float(tempo_preliminary),
        tightness=100  # plus de flexibilitÃ© tempo
    )

    # Convertir en secondes et rajouter le dÃ©calage du silence de dÃ©but
    beat_times = librosa.frames_to_time(beat_frames, sr=sr) + start_silence_s

    if len(beat_times) < 2:
        raise ValueError("librosa n'a pas dÃ©tectÃ© suffisamment de beats")

    # Downbeats heuristiques et BPM global
    iois = np.diff(beat_times)
    global_bpm = float(np.median(60.0 / iois[(iois > 0.15) & (iois < 3.0)]))

    # Correction de l'octave du tempo (si le tracker a divisé par 2)
    if start_bpm and global_bpm < start_bpm * 0.75:
        new_beats = []
        for i in range(len(beat_times) - 1):
            new_beats.append(beat_times[i])
            new_beats.append((beat_times[i] + beat_times[i+1]) / 2.0)
        new_beats.append(beat_times[-1])
        beat_times = np.array(new_beats)
        
        iois = np.diff(beat_times)
        global_bpm = float(np.median(60.0 / iois[(iois > 0.15) & (iois < 3.0)]))

    # BUG CORRIGÉ (v4.2) : downbeat_times = beat_times[::4] forçait ici aussi
    # systématiquement (4, 4), quelle que soit la vraie mesure du morceau.
    bar_len = _estimate_bar_length(audio_path, beat_times)
    downbeat_times = beat_times[::bar_len] if len(beat_times) >= bar_len else beat_times
    meter = _detect_meter(beat_times, downbeat_times)

    return TempoMap(
        beat_times=beat_times,
        downbeat_times=downbeat_times,
        estimated_meter=meter,
        global_bpm=global_bpm,
        method='librosa_advanced'
    )


def _build_fallback(
    note_events: Optional[list] = None,
    default_bpm: float = 120.0,
    start_bpm: Optional[float] = None
) -> TempoMap:
    """
    Dernier recours : TempoMap synthÃ©tique Ã  BPM fixe (identique Ã  V1).
    UtilisÃ© si madmom et librosa Ã©chouent tous les deux.
    Ne corrige pas le drift â€” Ã©quivalent V1.
    """
    if start_bpm:
        bpm = start_bpm
        logger.info(f"[TempoMap] Fallback avec tempo utilisateur: {bpm} BPM")
    else:
        # Estimer BPM depuis les IOI des note_events
        bpm = default_bpm
        if note_events and len(note_events) >= 4:
            onsets = sorted(float(e[0]) for e in note_events)
            iois   = np.diff(onsets[:60])
            iois   = iois[(iois > 0.05) & (iois < 2.0)]
            if len(iois) > 0:
                med = float(np.median(iois))
                bpm = 60.0 / med
                while bpm < 60:
                    bpm *= 2
                while bpm > 210:
                    bpm /= 2
                bpm = round(bpm, 1)

    # GÃ©nÃ©rer des beats synthÃ©tiques linÃ©aires sur 5 minutes max
    beat_s = 60.0 / max(bpm, 20)
    n_beats = min(int(300 / beat_s) + 1, 2000)
    beat_times = np.array([i * beat_s for i in range(n_beats)])

    return TempoMap(
        beat_times=beat_times,
        downbeat_times=beat_times[::4],
        estimated_meter=(4, 4),
        global_bpm=bpm,
        method='fallback'
    )


# â”€â”€ DÃ©tection de mesure â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _detect_meter(
    beat_times: np.ndarray,
    downbeat_times: np.ndarray
) -> Tuple[int, int]:
    """
    DÃ©tecte la mesure (numÃ©rateur, dÃ©nominateur) Ã  partir des beats et downbeats.

    Algorithme :
    1. Calculer le nombre moyen de beats entre deux downbeats consÃ©cutifs
    2. Arrondir Ã  l'entier le plus proche parmi : 2, 3, 4, 5, 6
    3. Mapper vers (numÃ©rateur, dÃ©nominateur) standard

    Si les downbeats sont insuffisants ou ambigus â†’ retourner (4, 4) par dÃ©faut.
    """
    METER_MAP = {
        2: (2, 4),
        3: (3, 4),
        4: (4, 4),
        5: (5, 4),
        6: (6, 8),
    }

    if len(downbeat_times) < 2 or len(beat_times) < 4:
        return (4, 4)

    # Compter les beats entre downbeats consÃ©cutifs
    beats_between = []
    for i in range(len(downbeat_times) - 1):
        t_start = downbeat_times[i]
        t_end   = downbeat_times[i + 1]
        n = int(np.sum((beat_times >= t_start) & (beat_times < t_end)))
        if 1 <= n <= 8:
            beats_between.append(n)

    if not beats_between:
        return (4, 4)

    median_beats = int(round(float(np.median(beats_between))))
    return METER_MAP.get(median_beats, (4, 4))


# â”€â”€ Auto-test â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import sys
    import os

    test_file = None
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    else:
        # Chercher le fichier MP3 de test dans le rÃ©pertoire parent
        parent = os.path.join(os.path.dirname(__file__), '..')
        for f in os.listdir(parent):
            if f.endswith('.mp3') or f.endswith('.wav'):
                test_file = os.path.join(parent, f)
                break

    if not test_file or not os.path.exists(test_file):
        print("[Test] Aucun fichier audio trouvÃ©. Passer le chemin en argument.")
        print("Usage: python tempo_map.py <chemin_audio>")
        sys.exit(1)

    print("\n" + "="*60)
    print(f"[Test] Analyse de : {os.path.basename(test_file)}")
    print("="*60 + "\n")

    tm = build_tempo_map(test_file)

    print("\n-- Resultats --")
    print(f"  Methode         : {tm.method}")
    print(f"  BPM global      : {tm.global_bpm:.2f}")
    print(f"  Mesure          : {tm.estimated_meter[0]}/{tm.estimated_meter[1]}")
    print(f"  Nombre de beats : {len(tm.beat_times)}")
    t_range = tm.tempo_range()
    print(f"  Plage BPM       : [{t_range[0]:.1f} - {t_range[1]:.1f}]")
    print(f"  5 premiers beats (s) : {[round(b, 3) for b in tm.beat_times[:5]]}")

    print("\n-- Tests de conversion --")
    all_ok = True
    for t in [1.0, 5.0, 10.0, 20.0, 30.0]:
        if t > tm.beat_times[-1] + 5:
            continue
        b  = tm.seconds_to_beat(t)
        t2 = tm.beat_to_seconds(b)
        err_ms = abs(t - t2) * 1000
        status = "OK" if err_ms < 10.0 else "FAIL"
        if err_ms >= 10.0:
            all_ok = False
        print(f"  [{status}]  {t:.1f}s -> beat {b:.3f} -> {t2:.3f}s  (erreur: {err_ms:.2f}ms)")

    print("\n-- Tempo local --")
    for t in [0.0, 5.0, 15.0, 30.0]:
        if t > tm.beat_times[-1] + 5:
            continue
        bpm_loc = tm.local_bpm_at(t)
        print(f"  BPM a {t:.0f}s : {bpm_loc:.1f}")

    if all_ok:
        print("\n[Test] SUCCES - Tous les tests de conversion sont passes (<10ms d'erreur)")
    else:
        print("\n[Test] ATTENTION - Certaines conversions depassent 10ms")
