"""
transcriber.py — Pipeline de transcription audio → MIDI (Basic Pitch, Piano Transcription, Demucs)
"""
import os
import tempfile
import numpy as np
import pretty_midi


def detect_computing_device():
    """
    Détecte le meilleur device de calcul disponible.
    
    Ordre de priorité :
    1. Intel GPU via IPEX (XPU)
    2. NVIDIA GPU (CUDA)
    3. CPU (fallback)
    
    Returns:
        torch.device: Le device détecté
    """
    import torch
    
    # 1. Vérifier IPEX / Intel XPU (pour ARC A770)
    try:
        if hasattr(torch, 'xpu') and torch.xpu.is_available():
            return torch.device("xpu:0")
    except Exception as e:
        print(f"[Transcriber] IPEX/XPU non disponible: {e}")
    
    # 2. Vérifier CUDA (NVIDIA GPU)
    try:
        if torch.cuda.is_available():
            return torch.device("cuda:0")
    except Exception as e:
        print(f"[Transcriber] CUDA non disponible: {e}")
    
    # 3. Fallback CPU
    print("[Transcriber] ⚠️  Aucun GPU détecté, utilisation du CPU (fallback)")
    print("[Transcriber] 💡 Pour accélérer le traitement:")
    print("[Transcriber]    - NVIDIA GPU: installer PyTorch CUDA")
    print("[Transcriber]    - Intel ARC: installer intel-extension-for-pytorch")
    return torch.device("cpu")

# ── Patch de compatibilité librosa >= 0.10 ────────────────────────────────────
# piano_transcription_inference appelle librosa.core.audio.resample(y, sr_native, sr, res_type=...)
# avec orig_sr et target_sr en POSITIONNELS, mais librosa >= 0.10 les a rendus keyword-only.
# On doit patcher librosa.core.audio AVANT tout import de piano_transcription_inference.
import librosa.core.audio as _lca

_orig_resample = _lca.resample

def _resample_compat(*args, orig_sr=None, target_sr=None, res_type='soxr_hq', **kwargs):
    """Accepte orig_sr/target_sr en positionnels ou en keyword."""
    if len(args) >= 3:
        return _orig_resample(args[0], orig_sr=args[1], target_sr=args[2],
                              res_type=res_type, **kwargs)
    if len(args) == 2:
        return _orig_resample(args[0], orig_sr=args[1], target_sr=target_sr,
                              res_type=res_type, **kwargs)
    if len(args) == 1:
        return _orig_resample(args[0], orig_sr=orig_sr, target_sr=target_sr,
                              res_type=res_type, **kwargs)
    return _orig_resample(*args, orig_sr=orig_sr, target_sr=target_sr,
                          res_type=res_type, **kwargs)

_lca.resample = _resample_compat
import librosa as _librosa
_librosa.resample = _resample_compat
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# ENSEMBLE VOTING — Fusion multi-modèles (configurable via config.yaml)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_available_ensemble_models() -> dict:
    """Détecte à runtime quels modèles d'ensemble sont réellement utilisables."""
    import importlib
    import os
    availability = {
        'piano_transcription': False,
        'basic_pitch': False,
        'transkun': False,
        'hft': False,
        'mt3': False,
    }
    try:
        importlib.import_module('piano_transcription_inference')
        availability['piano_transcription'] = True
    except ImportError:
        pass
    try:
        importlib.import_module('basic_pitch.inference')
        availability['basic_pitch'] = True
    except ImportError:
        pass
    try:
        importlib.import_module('transkun')
        availability['transkun'] = True
    except ImportError:
        pass
    try:
        importlib.import_module('run_hft')
        availability['hft'] = True
    except (ImportError, ModuleNotFoundError):
        pass
    mt3_path = os.environ.get('MT3_PATH', '/mt3')
    availability['mt3'] = os.path.isdir(mt3_path)
    return availability


def run_ensemble_transcription(audio_path, options):
    """
    Exécute la transcription en mode ensemble (vote multi-modèles).
    Auto-détection des modèles disponibles + filtrage transparent.
    
    Args:
        audio_path: Chemin vers le fichier audio
        options: Dictionnaire d'options (peut contenir 'ensemble' pour override)
        
    Returns:
        tuple: (note_events, midi_data, pedal_intervals) fusionnés
    """
    import time
    import numpy as np
    from collections import defaultdict
    import pretty_midi
    
    print("[Ensemble] Démarrage de la transcription en mode ensemble...")
    t0 = time.perf_counter()
    
    ensemble_config = options.get('ensemble', {})
    
    # Configuration par défaut des modèles (poids)
    # NOTE : basic_pitch retiré du défaut (qualité inférieure sur classique)
    # Pour l'activer, l'ajouter manuellement dans config.yaml ou options['ensemble']['models']
    default_models = [
        {'name': 'piano_transcription', 'weight': 1.5, 'onset_weight': 1.2, 'pitch_weight': 1.0, 'duration_weight': 1.0},
        {'name': 'transkun',           'weight': 1.3, 'onset_weight': 1.1, 'pitch_weight': 1.1, 'duration_weight': 1.1},
        # {'name': 'basic_pitch',      'weight': 1.0, 'onset_weight': 1.0, 'pitch_weight': 1.0, 'duration_weight': 0.8},
        # {'name': 'hft',              'weight': 1.2, 'onset_weight': 1.0, 'pitch_weight': 1.0, 'duration_weight': 1.0},
    ]
    models_config = ensemble_config.get('models', default_models)

    # PHASE 3 : filtrer selon la dispo réelle des modèles
    availability = _detect_available_ensemble_models()
    print(f"[Ensemble] Modèles disponibles : "
          f"{[k for k, v in availability.items() if v]}")

    filtered_models = [m for m in models_config if availability.get(m['name'], False)]
    if len(filtered_models) < len(models_config):
        skipped = [m['name'] for m in models_config if not availability.get(m['name'], False)]
        print(f"[Ensemble] ⚠ Modèles indisponibles, ignorés : {skipped}")

    if not filtered_models:
        raise RuntimeError(
            "Ensemble impossible : aucun modèle installé. "
            "Vérifie : pip install piano_transcription_inference basic_pitch transkun"
        )

    if len(filtered_models) < 2:
        print(f"[Ensemble] Un seul modèle dispo ({filtered_models[0]['name']}), "
              f"bascule sur mode single-model.")
        # Fallback direct au modèle disponible
        model_fn = {
            'piano_transcription': run_piano_transcription,
            'basic_pitch': run_basic_pitch,
            'transkun': run_transkun,
        }.get(filtered_models[0]['name'])
        if model_fn:
            return model_fn(audio_path, options)
        raise RuntimeError(f"Modèle {filtered_models[0]['name']} non implémenté pour fallback")

    models_config = filtered_models

    onset_tolerance = ensemble_config.get('onset_tolerance', 0.05)  # secondes
    pitch_tolerance = ensemble_config.get('pitch_tolerance', 1)      # demi-tons
    min_votes = ensemble_config.get('min_votes', 2)
    velocity_aggregation = ensemble_config.get('velocity_aggregation', 'weighted_mean')
    duration_aggregation = ensemble_config.get('duration_aggregation', 'median')
    
    # Exécuter chaque modèle
    all_model_results = {}
    model_functions = {
        'piano_transcription': run_piano_transcription,
        'basic_pitch': run_basic_pitch,
        'transkun': run_transkun,
        'hft': lambda p, o: __import__('run_hft', fromlist=['run_hft']).run_hft(p, o),
        'mt3': run_mt3,
    }
    
    for model_cfg in models_config:
        model_name = model_cfg['name']
        if model_name not in model_functions:
            print(f"[Ensemble] ⚠️ Modèle '{model_name}' non disponible, ignoré")
            continue
            
        print(f"[Ensemble] Exécution du modèle: {model_name} (poids: {model_cfg['weight']})")
        try:
            model_options = options.copy()
            note_events, midi_data, pedal_intervals = model_functions[model_name](audio_path, model_options)
            all_model_results[model_name] = {
                'notes': note_events,
                'midi': midi_data,
                'pedal': pedal_intervals,
                'weight': model_cfg['weight'],
                'onset_weight': model_cfg.get('onset_weight', 1.0),
                'pitch_weight': model_cfg.get('pitch_weight', 1.0),
                'duration_weight': model_cfg.get('duration_weight', 1.0),
            }
            print(f"[Ensemble]   → {len(note_events)} notes détectées")
        except Exception as e:
            print(f"[Ensemble] ⚠️ Erreur modèle {model_name}: {e}")
            continue
    
    if not all_model_results:
        raise RuntimeError("Aucun modèle n'a réussi à transcrire l'audio")
    
    # ── FUSION PAR VOTE PONDÉRÉ ──────────────────────────────────────────────
    print(f"[Ensemble] Fusion de {len(all_model_results)} modèles...")
    
    # Collecter toutes les notes de tous les modèles
    all_notes = []  # liste de (onset, pitch, duration, velocity, model_name, model_weight, onset_w, pitch_w, dur_w)
    for model_name, result in all_model_results.items():
        w = result['weight']
        ow = result['onset_weight']
        pw = result['pitch_weight']
        dw = result['duration_weight']
        for note in result['notes']:
            onset, pitch, duration, velocity = note
            all_notes.append((onset, pitch, duration, velocity, model_name, w, ow, pw, dw))
    
    if not all_notes:
        raise RuntimeError("Aucune note détectée par aucun modèle")
    
    # Grouper les notes similaires (même onset ± tolérance, même pitch ± tolérance)
    # Algorithme: clustering simple par onset puis pitch
    all_notes.sort(key=lambda x: (x[0], x[1]))  # trier par onset puis pitch
    
    clusters = []
    for note in all_notes:
        onset, pitch, duration, velocity, mname, mw, mow, mpw, mdw = note
        
        # Chercher un cluster existant compatible
        assigned = False
        for cluster in clusters:
            # Vérifier si compatible avec le représentant du cluster
            rep_onset = cluster['rep_onset']
            rep_pitch = cluster['rep_pitch']
            
            if abs(onset - rep_onset) <= onset_tolerance and abs(pitch - rep_pitch) <= pitch_tolerance:
                cluster['notes'].append(note)
                assigned = True
                break
        
        if not assigned:
            # Nouveau cluster
            clusters.append({
                'rep_onset': onset,
                'rep_pitch': pitch,
                'notes': [note]
            })
    
    # Filtrer les clusters par nombre minimum de votes
    valid_clusters = [c for c in clusters if len(c['notes']) >= min_votes]
    print(f"[Ensemble] {len(clusters)} clusters formés, {len(valid_clusters)} retenus (min_votes={min_votes})")
    
    # Agréger chaque cluster valide
    fused_notes = []
    for cluster in valid_clusters:
        notes = cluster['notes']
        
        # Calculer les poids totaux
        total_weight = sum(n[5] for n in notes)  # model weight
        
        # Onset: moyenne pondérée par onset_weight * model_weight
        weighted_onset = sum(n[0] * n[6] * n[5] for n in notes) / sum(n[6] * n[5] for n in notes)
        
        # Pitch: vote majoritaire pondéré par pitch_weight * model_weight
        pitch_votes = defaultdict(float)
        for n in notes:
            pitch_votes[n[1]] += n[7] * n[5]  # pitch_weight * model_weight
        fused_pitch = max(pitch_votes.items(), key=lambda x: x[1])[0]
        
        # Durée: selon méthode configurée
        if duration_aggregation == 'median':
            durations = [n[2] for n in notes]
            fused_duration = float(np.median(durations))
        elif duration_aggregation == 'mean':
            fused_duration = float(np.mean([n[2] for n in notes]))
        elif duration_aggregation == 'weighted_mean':
            fused_duration = sum(n[2] * n[8] * n[5] for n in notes) / sum(n[8] * n[5] for n in notes)
        else:
            fused_duration = float(np.median([n[2] for n in notes]))
        
        # Vélocité: selon méthode configurée
        velocities = [n[3] for n in notes]
        weights = [n[5] for n in notes]  # model weights
        
        if velocity_aggregation == 'max':
            fused_velocity = max(velocities)
        elif velocity_aggregation == 'mean':
            fused_velocity = float(np.mean(velocities))
        elif velocity_aggregation == 'weighted_mean':
            fused_velocity = sum(v * w for v, w in zip(velocities, weights)) / sum(weights)
        else:
            fused_velocity = float(np.mean(velocities))
        
        fused_notes.append((
            weighted_onset,
            fused_pitch,
            fused_duration,
            int(round(fused_velocity))
        ))
    
    # Trier par onset
    fused_notes.sort(key=lambda x: x[0])
    
    # Créer un objet MIDI fusionné (utiliser le MIDI du modèle principal comme base)
    primary_model = max(all_model_results.items(), key=lambda x: x[1]['weight'])[0]
    fused_midi = all_model_results[primary_model]['midi']
    
    # Mettre à jour le MIDI avec les notes fusionnées
    if fused_midi:
        # Supprimer les notes existantes et ajouter les fusionnées
        for inst in fused_midi.instruments:
            inst.notes.clear()
        
        for onset, pitch, duration, velocity in fused_notes:
            note = pretty_midi.Note(
                velocity=min(127, max(0, velocity)),
                pitch=pitch,
                start=onset,
                end=onset + duration
            )
            # Ajouter au premier instrument (piano)
            if fused_midi.instruments:
                fused_midi.instruments[0].notes.append(note)
            else:
                # Créer un instrument piano par défaut
                piano = pretty_midi.Instrument(program=0, is_drum=False, name='Piano')
                piano.notes.append(note)
                fused_midi.instruments.append(piano)
    
    dt = time.perf_counter() - t0
    print(f"[Ensemble] Terminé en {dt:.2f}s — {len(fused_notes)} notes fusionnées")
    # Pour les pédales, on prend celles du modèle principal s'il y en a
    fused_pedals = all_model_results[primary_model].get('pedal', [])
    
    return fused_notes, fused_midi, fused_pedals


def transcribe_audio(audio_path, options=None):
    """
    Transcrit un fichier audio en événements de notes.
    options: dict contenant les clés :
      - transcriber ('basic_pitch', 'piano_transcription')
      - use_demucs (bool)
      - detect_tempo (bool)
      - onset_threshold (float)
      - frame_threshold (float)
    """
    if options is None:
        options = {
            'transcriber': 'piano_transcription',
            'use_demucs': False,
            'detect_tempo': True,
            'onset_threshold': 0.5,
            'frame_threshold': 0.25
        }
    
    print(f"[Transcriber] Options reçues : {options}")
    
    warning_msgs = []
    original_audio_path = audio_path
    

    # ── 1. Prétraitement Audio : Isolation Demucs ─────────────────────────────
    if options.get('use_demucs', False):
        print(f"[Transcriber DEBUG] use_demucs est TRUE. Options reçues: {options}")
        audio_path = run_demucs_isolation(audio_path, warning_msgs)
        print(f"[Transcriber DEBUG] Chemin audio après Demucs: {audio_path}")
    else:
        print(f"[Transcriber DEBUG] use_demucs est FALSE. Options reçues: {options}")
    
    # ── 2. Moteur de transcription ────────────────────────────────────────────
    transcriber_choice = options.get('transcriber', 'piano_transcription')
    note_events = None
    midi_data = None
    pedal_intervals = []
  
    # Ensemble Voting (multi-modèles)
    if transcriber_choice == 'ensemble':
        note_events, midi_data, pedal_intervals = run_ensemble_transcription(audio_path, options)
  
    # Piano Transcription (recommandé)
    elif transcriber_choice == 'piano_transcription':
        note_events, midi_data, pedal_intervals = run_piano_transcription(audio_path, options)
  
    # Transkun (Haute Expressivité / SOTA)
    elif transcriber_choice == 'transkun':
        note_events, midi_data, pedal_intervals = run_transkun(audio_path, options)
        
    elif transcriber_choice == 'hft':
        from run_hft import run_hft
        note_events, midi_data, pedal_intervals = run_hft(audio_path, options)

    # Google MT3 (Multi-Task Multitrack)
    elif transcriber_choice == 'mt3':
        note_events, midi_data, pedal_intervals = run_mt3(audio_path, options)

    # Basic Pitch (rapide / fallback)
    elif transcriber_choice == 'basic_pitch':
        note_events, midi_data, pedal_intervals = run_basic_pitch(audio_path, options)
    
    else:
        raise ValueError(f"Transcripteur inconnu: {transcriber_choice}. "
                         f"Choix valides: piano_transcription, basic_pitch, transkun, hft, mt3, ensemble")


    # Nettoyer l'audio isolé temporaire si Demucs a été utilisé
    if audio_path != original_audio_path and os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except Exception:
            pass

    # ── 3. Estimation / Détection du tempo ────────────────────────────────────
    tempo = None
    if options.get('detect_tempo', True):
        tempo = detect_tempo_librosa(original_audio_path)
        if tempo:
            print(f"[Transcriber] Tempo détecté par Librosa : {tempo} BPM")

    if not tempo:
        tempo = estimate_tempo_from_events(note_events)
        print(f"[Transcriber] Tempo estimé à partir des notes : {tempo} BPM")

    return note_events, midi_data, pedal_intervals, tempo, warning_msgs


# ── Fonctions moteurs de transcription ────────────────────────────────────────

def run_transkun(audio_path, options):
    """
    Exécute la transcription via Transkun (SOTA Transformers).
    Utilise une approche de fichier MIDI intermédiaire pour la robustesse.
    """
    import tempfile
    import subprocess
    import midi_parser
    import time
    
    print(f'[Transcriber] Exécution Transkun...')
    
    # Détection du device
    device_info = detect_computing_device()
    # On passe directement le type (ex: "xpu", "cuda" ou "cpu")
    device_arg = device_info.type
    print(f'[Transcriber] Transkun device choisi : {device_arg} (Détecté: {device_info})')
    
    # Créer un fichier MIDI temporaire
    fd, temp_midi_path = tempfile.mkstemp(suffix='.mid')
    os.close(fd)
    
    try:
        t0 = time.perf_counter()
        # Appel externe pour isoler la mémoire et éviter les conflits de dépendances
        cmd = [
            "python", "-m", "transkun.transcribe",
            audio_path,
            temp_midi_path,
            "--device", device_arg
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"[Transcriber] Erreur Transkun : {result.stderr}")
            raise RuntimeError(f"Transkun a échoué: {result.stderr}")
            
        dt = time.perf_counter() - t0
        print(f"[Transcriber] Transkun terminé en {dt:.2f}s")
        
        # Lire le fichier MIDI généré avec pretty_midi et le convertir
        # en note_events standard : (onset_s, pitch_midi, duration_s, velocity_norm)
        import pretty_midi
        midi_data = pretty_midi.PrettyMIDI(temp_midi_path)
        
        note_events = []
        for instrument in midi_data.instruments:
            for note in instrument.notes:
                velocity_norm = note.velocity / 127.0
                note_events.append((
                    note.start,          # onset (s)
                    note.pitch,          # MIDI pitch
                    note.end - note.start,  # duration (s)
                    velocity_norm        # amplitude [0.0 - 1.0]
                ))
        
        # Trier par ordre chronologique
        note_events.sort(key=lambda x: x[0])
        print(f"[Transcriber] Transkun : {len(note_events)} notes extraites du MIDI")
        
        return note_events, midi_data, []
        
    finally:
        if os.path.exists(temp_midi_path):
            os.remove(temp_midi_path)

def run_basic_pitch(audio_path, options):
    """Exécute la transcription via Basic Pitch."""
    from basic_pitch.inference import predict
    
    onset_threshold = options.get('onset_threshold', 0.5)
    frame_threshold = options.get('frame_threshold', 0.25)
    minimum_note_length = options.get('minimum_note_duration', 50)

    print(f'[Transcriber] Exécution Basic Pitch (seuil={onset_threshold})')

    # Transcription avec conversion WAV automatique en cas d'erreur
    try:
        model_output, midi_data, basic_events = predict(
            audio_path,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=minimum_note_length,
            melodia_trick=True,
        )
    except Exception as e:
        print(f'[Transcriber] Erreur Basic Pitch directe, tentative après conversion WAV ({e})')
        wav_path = _to_wav(audio_path)
        try:
            model_output, midi_data, basic_events = predict(
                wav_path,
                onset_threshold=onset_threshold,
                frame_threshold=frame_threshold,
                minimum_note_length=minimum_note_length,
                melodia_trick=True,
            )
        finally:
            if wav_path != audio_path and os.path.exists(wav_path):
                os.remove(wav_path)

    # Convertir au format commun : (onset_sec, pitch, duration_sec, velocity)
    note_events = []
    for event in basic_events:
        start_s = float(event[0])
        end_s = float(event[1])
        pitch = int(event[2])
        amplitude = float(event[3]) if len(event) > 3 else 0.8
        velocity = int(min(127, amplitude * 127))
        duration = max(end_s - start_s, 0.05)
        note_events.append((start_s, pitch, duration, velocity))
    return note_events, midi_data, []


def run_mt3(audio_path, options):
    """
    Exécute la transcription via le modèle Google MT3 (Multi-Task Multitrack).
    Utilise l'implémentation PyTorch kunato/mt3-pytorch, cloné dans /mt3 (Docker).
    """
    import time
    import sys
    import tempfile
    import pretty_midi
    
    # Localiser le dossier MT3 (variable d'env Docker ou chemin local de dev)
    mt3_path = os.environ.get('MT3_PATH', '/mt3')
    
    if not os.path.isdir(mt3_path):
        raise RuntimeError(
            f"Le dossier MT3 est introuvable à '{mt3_path}'. "
            "Assurez-vous que le Dockerfile a bien cloné kunato/mt3-pytorch dans /mt3."
        )
    
    # Ajouter le dossier MT3 au path Python pour importer InferenceHandler
    if mt3_path not in sys.path:
        sys.path.insert(0, mt3_path)
    
    print(f'[Transcriber] Exécution de Google MT3 depuis {mt3_path}...')
    t0 = time.perf_counter()
    
    try:
        from inference import InferenceHandler
    except ImportError as e:
        raise RuntimeError(f"Impossible d'importer InferenceHandler depuis {mt3_path}: {e}")
    
    # Chemin vers les poids pré-entraînés (sous-dossier pretrained du dépôt)
    pretrained_path = os.path.join(mt3_path, 'pretrained')
    
    # Créer un dossier temporaire pour le MIDI de sortie
    fd, temp_midi_path = tempfile.mkstemp(suffix='.mid')
    os.close(fd)
    
    try:
        handler = InferenceHandler(pretrained_path)
        # inference() produit un fichier MIDI dans le même dossier ou retourne un objet
        result = handler.inference(audio_path)
        
        dt = time.perf_counter() - t0
        print(f"[Transcriber] MT3 terminé en {dt:.2f}s")
        
        # Si handler.inference retourne un chemin, le lire
        if isinstance(result, str) and os.path.exists(result):
            midi_data = pretty_midi.PrettyMIDI(result)
        elif hasattr(result, 'instruments'):
            # result est déjà un objet pretty_midi
            midi_data = result
        else:
            raise RuntimeError(f"Format de retour MT3 inattendu: {type(result)}")
        
        note_events = []
        for instrument in midi_data.instruments:
            for note in instrument.notes:
                velocity_norm = note.velocity / 127.0
                note_events.append((
                    note.start,
                    note.pitch,
                    note.end - note.start,
                    velocity_norm
                ))
        
        note_events.sort(key=lambda x: x[0])
        print(f"[Transcriber] MT3 : {len(note_events)} notes extraites")
        return note_events, midi_data, []
        
    finally:
        if os.path.exists(temp_midi_path):
            os.remove(temp_midi_path)




def run_piano_transcription(audio_path, options):
    """Piano transcription + profiling CPU/GPU/IO (version pro)."""
    import os
    import time
    import torch
    import requests
    import tempfile
    import pretty_midi

    from piano_transcription_inference import PianoTranscription, sample_rate, load_audio
    from piano_transcription_inference.utilities import write_events_to_midi

    # =========================================================
    # PROFILER SIMPLE INTÉGRÉ
    # =========================================================
    class Profiler:
        def __init__(self):
            self.steps = []

        def start(self, name):
            self._synchronize()
            self.t0 = time.perf_counter()
            self.name = name

        def _synchronize(self):
            """Synchronise le device actif."""
            # IPEX / Intel XPU
            try:
                if hasattr(torch, 'xpu') and torch.xpu.is_available():
                    torch.xpu.synchronize()
                    return
            except Exception:
                pass
            # CUDA
            try:
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
            except Exception:
                pass

        def stop(self):
            self._synchronize()
            dt = time.perf_counter() - self.t0
            self.steps.append((self.name, dt))

        def report(self):
            print("\n========== PIPELINE PROFILE ==========")
            total = sum(t for _, t in self.steps)

            for name, dt in self.steps:
                pct = (dt / total * 100) if total > 0 else 0
                print(f"{name:20s} : {dt:8.3f}s ({pct:5.1f}%)")

            print("TOTAL:", round(total, 3), "s")
            print("======================================\n")

    prof = Profiler()

    # =========================================================
    # DEVICE SELECTION (améliorée pour Intel ARC A770)
    # =========================================================
    device = detect_computing_device()
    print(f"[Transcriber] Device utilisé: {device}")
    
    # Message d'aide si CPU détecté
    if device.type == 'cpu':
        print("[Transcriber] ⚠️  EXÉCUTION SUR CPU DÉTECTÉE !")
        print("[Transcriber] Pour utiliser votre GPU Intel ARC A770 :")
        print("[Transcriber]   1. Installez IPEX : pip install intel-extension-for-pytorch")
        print("[Transcriber]   2. Redémarrez le serveur")
        print("[Transcriber] Voir backend/setup_gpu.bat pour l'installation automatique.")

    # =========================================================
    # CHECKPOINT DOWNLOAD
    # =========================================================
    checkpoint_dir = os.path.join(os.path.expanduser('~'), 'piano_transcription_inference_data')
    checkpoint_path = os.path.join(
        checkpoint_dir,
        'note_F1=0.9677_pedal_F1=0.9186.pth'
    )

    if not os.path.exists(checkpoint_path) or os.path.getsize(checkpoint_path) < 1.6e8:
        os.makedirs(checkpoint_dir, exist_ok=True)
        print("[Piano] Téléchargement modèle...")

        url = "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
        r = requests.get(url, stream=True)
        r.raise_for_status()

        with open(checkpoint_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    # =========================================================
    # LOAD MODEL (avec IPEX pour Intel ARC A770 XPU)
    # =========================================================
    prof.start("model_init")

    transcriber = None
    actual_device = device
    use_ipex = False
    
    # ETAPE 1: Charger et déplacer le modèle sur le device détecté
    try:
        if device.type == 'xpu':
            print(f"[Piano] Chargement du modele sur XPU (Intel ARC)...")
            transcriber = PianoTranscription(device="xpu:0")
            transcriber.model.to("xpu:0") # Patch pour forcer le déplacement (la lib ignore "xpu")
            actual_device = torch.device("xpu:0")
        elif device.type == 'cuda':
            print(f"[Piano] Chargement du modele sur CUDA...")
            transcriber = PianoTranscription(device="cuda:0")
            actual_device = torch.device("cuda:0")
        else:
            print(f"[Piano] Chargement du modele sur CPU...")
            transcriber = PianoTranscription(device="cpu")
            actual_device = torch.device("cpu")
        
        transcriber.model.eval()
    except Exception as e:
        prof.stop()
        raise RuntimeError(f"Impossible de charger le modele de transcription: {e}")
    
    prof.stop()

    # =========================================================
    # APPLIQUER LES SEUILS DE DÉTECTION (depuis les options)
    # La librairie expose ces seuils comme attributs modifiables
    # avant l'appel à .transcribe().
    # Valeurs par défaut lib : onset=0.3, frame=0.1, offset=0.3
    # =========================================================
    onset_threshold = float(options.get('onset_threshold', 0.3))
    frame_threshold = float(options.get('frame_threshold', 0.1))
    transcriber.onset_threshold   = onset_threshold
    transcriber.frame_threshold   = frame_threshold
    transcriber.offset_threshod   = onset_threshold  # cohérent avec onset
    print(f"[Piano] Seuils appliqués : onset={onset_threshold:.2f}, frame={frame_threshold:.2f}")

    # =========================================================
    # LOAD AUDIO (CPU)
    # =========================================================
    prof.start("io_audio")

    audio, _ = load_audio(audio_path, sr=sample_rate, mono=True)

    prof.stop()

    # =========================================================
    # INFERENCE (GPU CORE)
    # =========================================================
    prof.start("inference")

    print(f"[Piano] Inference sur: {actual_device}")
    
    with torch.no_grad():
        transcribed_dict = transcriber.transcribe(audio, None)
    
    prof.stop()

    # =========================================================
    # POSTPROCESS (CPU)
    # =========================================================
    prof.start("postprocess")

    est_note_events = transcribed_dict["est_note_events"]

    note_events = []
    for event in est_note_events:
        onset = event["onset_time"]
        offset = event["offset_time"]
        pitch = event["midi_note"]
        velocity = int(event["velocity"])  # déjà en 0-127
        duration = max(offset - onset, 0.05)  # durée en secondes, min 50ms
        note_events.append((onset, pitch, duration, velocity))

    pedal_events_raw = transcribed_dict.get("est_pedal_events", [])
    pedal_intervals = []
    for p in pedal_events_raw:
        pedal_intervals.append((float(p["onset_time"]), float(p["offset_time"])))

    prof.stop()

    # =========================================================
    # MIDI EXPORT (CPU)
    # =========================================================
    prof.start("midi_export")

    temp_midi = tempfile.mktemp(suffix=".mid")

    try:
        write_events_to_midi(
            start_time=0,
            note_events=est_note_events,
            pedal_events=transcribed_dict.get("est_pedal_events", []),
            midi_path=temp_midi
        )

        midi_data = pretty_midi.PrettyMIDI(temp_midi)

    finally:
        if os.path.exists(temp_midi):
            os.remove(temp_midi)

    prof.stop()

    # =========================================================
    # REPORT
    # =========================================================
    prof.report()

    return note_events, midi_data, pedal_intervals


# ── Prétraitement Audio : Isolation Demucs ────────────────────────────────────

def run_demucs_isolation(audio_path, warning_msgs):
    """Isole le piano de l'audio via Demucs (subprocess, compatible toutes versions)."""
    import subprocess
    import glob
    import sys
    
    print(f"[Demucs] Démarrage de l'isolation du piano...")
    
    out_dir = tempfile.mkdtemp(prefix="demucs_")
    
    try:
        cmd = [
            sys.executable, '-m', 'demucs',
            '--two-stems', 'other',
            '-n', 'htdemucs',
            '-o', out_dir,
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            raise RuntimeError(f"Demucs a échoué :\n{result.stderr[-2000:]}")

        # Chercher le fichier 'other' généré
        pattern = os.path.join(out_dir, '**', 'other.*')
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            # Fallback : chercher n'importe quel WAV/MP3 dans le répertoire de sortie
            pattern2 = os.path.join(out_dir, '**', '*.*')
            all_files = glob.glob(pattern2, recursive=True)
            matches = [f for f in all_files if os.path.splitext(f)[1].lower() in ('.wav', '.mp3', '.flac')]

        if not matches:
            raise ValueError("Piste 'other' introuvable dans la sortie Demucs.")

        # Copier vers un fichier temporaire pour ne pas dépendre du répertoire Demucs
        ext = os.path.splitext(matches[0])[1]
        temp_wav = tempfile.mktemp(suffix=f"_piano{ext}")
        import shutil as _shutil
        _shutil.copy2(matches[0], temp_wav)
        print(f"[Demucs] Audio isolé sauvegardé temporairement dans : {temp_wav}")
        return temp_wav

    finally:
        # Nettoyage du répertoire de travail Demucs
        import shutil as _shutil
        _shutil.rmtree(out_dir, ignore_errors=True)



# ── Analyse Musicale ──────────────────────────────────────────────────────────

def detect_tempo_librosa(audio_path):
    """Détecte le tempo à l'aide de librosa.beat.beat_track()."""
    try:
        import librosa
        print(f"[Librosa] Analyse du tempo pour {os.path.basename(audio_path)}...")
        y, sr = librosa.load(audio_path, sr=None)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        
        if hasattr(tempo, '__len__'):
            tempo_val = float(tempo[0])
        else:
            tempo_val = float(tempo)
            
        if 40 <= tempo_val <= 250:
            return int(round(tempo_val))
    except Exception as e:
        print(f"[Librosa] Échec de la détection du tempo : {e}")
    return None


def estimate_tempo_from_events(note_events, default=120):
    """Estime le tempo à partir des intervalles inter-attaques (IOI) (fallback)."""
    if not note_events or len(note_events) < 4:
        return default

    onsets = sorted(float(e[0]) for e in note_events)
    iois   = np.diff(onsets[:60])
    iois   = iois[(iois > 0.05) & (iois < 2.0)]

    if len(iois) == 0:
        return default

    med = float(np.median(iois))
    bpm = 60.0 / med

    while bpm < 60:
        bpm *= 2
    while bpm > 210:
        bpm /= 2

    return int(round(bpm))


def _to_wav(audio_path):
    """Convertit MP3/FLAC → WAV via librosa."""
    import librosa
    import soundfile as sf

    ext      = os.path.splitext(audio_path)[1].lower()
    wav_path = audio_path.replace(ext, '_tmp.wav')
    y, sr    = librosa.load(audio_path, sr=None, mono=True)
    sf.write(wav_path, y, sr)
    return wav_path


# ── Classe Pipeline pour app.py ─────────────────────────────────────────────────

class TranscriptionPipeline:
    """
    Pipeline de transcription audio → MIDI/MusicXML.
    
    Utilise les fonctions existantes de transcriber.py et intègre
    les modules de quantisation, détection de tonalité et construction de partition.
    """
    
    def __init__(self):
        self.name = "TranscriptionPipeline v3"
    
    def run(self, input_path, output_dir, options=None):
        """
        Exécute le pipeline complet de transcription.
        
        Args:
            input_path: Chemin vers le fichier audio d'entrée
            output_dir: Répertoire où sauvegarder les fichiers de sortie
            options: dictionnaire des options de transcription
            
        Returns:
            dict: Résultats du pipeline avec clés:
                - midi_path: Chemin du fichier MIDI généré
                - xml_path: Chemin du fichier MusicXML généré
                - note_count: Nombre de notes détectées
                - tempo: Tempo détectée en BPM
                - key: Tonalité détectée
                - time_signature: Mesure détectée
                - warnings: Liste d'avertissements
        """
        import os
        import midi_parser
        from tempo_map import build_tempo_map
        from quantizer import quantize_notes
        from voice_engine import split_voices
        from score_builder import build_score

        print(f"[Pipeline] Début de la transcription: {input_path}")

        options = options or {
            'transcriber': 'piano_transcription',
            'use_demucs': False,
            'detect_tempo': True,
            'onset_threshold': 0.5,
            'frame_threshold': 0.25,
        }

        # ── 1. Transcription brute (audio → note_events) ─────────────────────
        note_events, midi_data, pedal_intervals, raw_tempo, warning_msgs = transcribe_audio(
            input_path, options
        )
        if not note_events:
            raise ValueError("Aucune note détectée dans l'audio")
        print(f"[Pipeline] {len(note_events)} notes brutes")

        # ── 1.5 Filtrage note_filter (FIX #2) ─────────────────────────────────
        notes_dict = [
            {'onset': n[0], 'pitch': n[1], 'duration': n[2],
             'velocity': (n[3] / 127.0) if n[3] > 1 else float(n[3])}
            for n in note_events
        ]
        try:
            from note_filter import filter_ghost_notes, apply_pedal_aware_shortening
            notes_dict = filter_ghost_notes(notes_dict, options)
            notes_dict = apply_pedal_aware_shortening(notes_dict, pedal_intervals or [], options)
            print(f"[Pipeline] {len(notes_dict)} notes après note_filter (ghost + pedal-aware)")
        except Exception as e:
            print(f"[Pipeline] ⚠ note_filter indisponible ({e}), fallback filtrage naïf")

        remove_short = options.get('remove_short_notes', False)
        min_dur_s = options.get('minimum_note_duration', 50) / 1000.0
        if remove_short:
            notes_dict = [n for n in notes_dict if n['duration'] >= min_dur_s]

        if options.get('merge_near_notes', False):
            merge_gap_s = options.get('merge_gap_ms', 30) / 1000.0
            notes_dict.sort(key=lambda n: (n['pitch'], n['onset']))
            merged = []
            for n in notes_dict:
                if merged and merged[-1]['pitch'] == n['pitch'] and \
                   (n['onset'] - (merged[-1]['onset'] + merged[-1]['duration'])) < merge_gap_s:
                    prev = merged[-1]
                    prev['duration'] = (n['onset'] + n['duration']) - prev['onset']
                    prev['velocity'] = max(prev['velocity'], n['velocity'])
                else:
                    merged.append(dict(n))
            notes_dict = merged
            notes_dict.sort(key=lambda n: n['onset'])

        note_events = [
            (n['onset'], n['pitch'], n['duration'],
             int(round(n['velocity'] * 127)) if n['velocity'] <= 1 else int(n['velocity']))
            for n in notes_dict
        ]
        print(f"[Pipeline] {len(note_events)} notes après filtrage complet")

        # ── 2. Tempo Map ─────────────────────────────────────────────────────
        user_tempo = options.get('tempo')
        start_bpm = float(user_tempo) if user_tempo else None
        tm = build_tempo_map(input_path, note_events, start_bpm=start_bpm)
        display_bpm = tm.global_bpm
        if start_bpm and not options.get('detect_tempo', True):
            display_bpm = start_bpm

        # ── 3. Quantification ────────────────────────────────────────────────
        quantization_level = options.get('quantization_level', 'standard')
        quantized_notes = quantize_notes(
            note_events,
            bpm=tm.global_bpm,
            quantization_level=quantization_level,
            enable_rubato=options.get('enable_rubato', False),
            enable_triplets=options.get('enable_triplets', False),
            tempo_map=tm,
        )
        print(f"[Pipeline] {len(quantized_notes)} notes quantisées ({quantization_level})")

        # ── 4. Analyse harmonique (TOUJOURS, pas seulement en preset jazz) ──
        preset = options.get('preset', 'standard')
        harmonic_ctx = None
        key_name = options.get('key_sig', 'C')
        try:
            from harmonic_analyzer import build_harmonic_context
            from piano_roll import group_into_slices, fuse_arpeggios

            pedal_beats = []
            if pedal_intervals:
                for p_start, p_end in pedal_intervals:
                    pedal_beats.append(
                        (tm.seconds_to_beat(p_start), tm.seconds_to_beat(p_end))
                    )

            slices = group_into_slices(quantized_notes, pedal_events=pedal_beats or None)
            slices = fuse_arpeggios(slices)
            harmonic_ctx = build_harmonic_context(slices)

            if options.get('detect_key', True):
                key_name = harmonic_ctx.global_key
                print(f"[Pipeline] Tonalité détectée: {key_name}")
        except Exception as e:
            print(f"[Pipeline] ⚠ Analyse harmonique en échec ({e})")

        # ── 5. Séparation LH/RH guidée par harmonie (FIX #3) ─────────────────
        try:
            if harmonic_ctx is not None:
                from voice_engine import split_with_harmony
                voices = split_with_harmony(quantized_notes, harmonic_ctx, options)
                print("[Pipeline] Split LH/RH : split_with_harmony (guidé)")
            else:
                voices = split_voices(quantized_notes, options=options)
                print("[Pipeline] Split LH/RH : split_voices (fallback)")
        except Exception as e:
            print(f"[Pipeline] ⚠ split_with_harmony échoué ({e}), fallback split_voices")
            voices = split_voices(quantized_notes, options=options)

        # ── 6. Construction du score ─────────────────────────────────────────
        time_sig_str = options.get('time_sig', '4/4')
        try:
            ts_parts = time_sig_str.split('/')
            time_signature = [int(ts_parts[0]), int(ts_parts[1])]
        except Exception:
            time_signature = list(tm.estimated_meter)

        show_chords = options.get('chord_symbols', True) or (preset == 'jazz')

        score_options = {
            'detect_key': False,
            'time_sig': time_signature,
            'display_bpm': display_bpm,
            'write_chord_symbols': show_chords,
            'detect_dynamics': True,
        }

        pedal_beats_list = []
        if pedal_intervals:
            for p_start, p_end in pedal_intervals:
                pedal_beats_list.append(
                    (tm.seconds_to_beat(p_start), tm.seconds_to_beat(p_end))
                )

        score_data = build_score(
            voices, tm,
            key_sig=key_name,
            options=score_options,
            harmonic_ctx=harmonic_ctx,
            pedals=pedal_beats_list,
        )

        score_data.setdefault('metadata', {})['warnings'] = warning_msgs

        # ── 7. Export MIDI + MusicXML réel (FIX #5) ──────────────────────────
        os.makedirs(output_dir, exist_ok=True)
        midi_path = os.path.join(output_dir, 'output.mid')
        xml_path = os.path.join(output_dir, 'score.musicxml')

        midi_parser.score_to_midi(score_data, midi_path)

        try:
            from musicxml_exporter import export_musicxml
            export_musicxml(score_data, xml_path)
            print(f"[Pipeline] MusicXML généré : {xml_path}")
        except Exception as e:
            print(f"[Pipeline] ⚠ Export MusicXML en échec ({e}), stub écrit")
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?><score-partwise></score-partwise>')

        # ── 8. Métadonnées pour le frontend ──────────────────────────────────
        score_data['midi_path'] = midi_path
        score_data['xml_path'] = xml_path
        score_data['note_count'] = len(quantized_notes)
        score_data['warnings'] = warning_msgs
        score_data['tempoMapMethod'] = tm.method
        score_data['tempoConfidence'] = (
            0.85 if tm.method == 'madmom'
            else (0.6 if tm.method == 'librosa_advanced' else 0.3)
        )
        score_data['tempoRange'] = tm.tempo_range()
        score_data['detectedMeter'] = tm.estimated_meter

        print(f"[Pipeline] Terminé — MIDI: {midi_path} | XML: {xml_path}")
        return score_data
    
    def _detect_time_signature(self, note_events, tempo):
        """
        Détecte la mesure (time signature) à partir des notes.
        
        Utilise l'analyse des intervalles entre les attaques de notes
        pour estimer la pulsation et la mesure.
        """
        if not note_events or len(note_events) < 4:
            return (4, 4)  # Default: 4/4
        
        # Calculer les IOI (Inter-Onset Intervals)
        onsets = sorted([e[0] for e in note_events])
        iois = [onsets[i+1] - onsets[i] for i in range(len(onsets)-1)]
        
        if not iois:
            return (4, 4)
        
        # Estimer la durée totale et le nombre de mesures
        total_duration = onsets[-1] - onsets[0]
        if total_duration == 0:
            return (4, 4)
        
        # Estimer le BPM à partir des IOI
        beat_duration = 60.0 / tempo if tempo else 0.5
        
        # Estimer le nombre de temps par mesure (généralement 3 ou 4)
        # Analyser la régularité des accents
        strong_beats = [i for i, ioi in enumerate(iois) if abs(ioi - beat_duration) < beat_duration * 0.3]
        
        if len(strong_beats) < 2:
            return (4, 4)  # Default
        
        # Estimer le nombre de temps par mesure
        measures = []
        for i in range(len(strong_beats) - 1):
            measure_duration = onsets[strong_beats[i+1]] - onsets[strong_beats[i]]
            beats_per_measure = round(measure_duration / beat_duration)
            if 2 <= beats_per_measure <= 7:
                measures.append(beats_per_measure)
        
        if not measures:
            return (4, 4)
        
        # Trouver la mesure la plus fréquente
        from collections import Counter
        most_common = Counter(measures).most_common(1)[0][0]
        
        # Choisir le dénominateur selon le tempo
        if tempo > 120:
            denominator = 8
        else:
            denominator = 4
        
        return (most_common, denominator)
