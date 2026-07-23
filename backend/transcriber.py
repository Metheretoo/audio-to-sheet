"""
transcriber.py — Pipeline de transcription audio → MIDI (Basic Pitch, Piano Transcription, Demucs)
"""
import os
import sys
import tempfile
import numpy as np
import pretty_midi


# ── P1.2 : Exception personnalisée pour le mode strict ─────────────────────────

class PipelineError(Exception):
    """
    Exception levée en mode strict lorsqu'une étape critique du pipeline échoue.
    
    En mode strict, toute erreur critique arrête immédiatement le pipeline
    au lieu de continuer avec un fallback silencieux.
    """
    pass


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
    # P1.6 : Warning structuré au lieu de print muet
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
# NUMBA DISABLE — Empêcher la compilation JIT massive et le debug bytecode
# ─────────────────────────────────────────────────────────────────────────────

# Désactiver le debug numba AVANT tout import de numba/madmom
# Sans ceci, la première exécution de DBNBeatTrackingProcessor génère
# des milliers de lignes de bytecode debug (18 538+ lignes) et bloque le traitement.
import os
os.environ.setdefault('NUMBA_DEBUG', '0')
os.environ.setdefault('NUMBA_DEBUG_BYTEARRAY', '0')
os.environ.setdefault('NUMBA_DEBUG_TYPEINFER', '0')
os.environ.setdefault('NUMBA_DUMP_BYTECODE', '0')
os.environ.setdefault('NUMBA_DUMP_LLVM', '0')
os.environ.setdefault('NUMBA_DEBUG_ARRAY_OPT', '0')
os.environ.setdefault('NUMBA_DEBUG_ARRAY_OPT_PASSMANAGER', '0')

# ─────────────────────────────────────────────────────────────────────────────
# ENSEMBLE VOTING — Délégué à ensemble_voter.py
# ─────────────────────────────────────────────────────────────────────────────
# La logique complète de transcription ensemble est centralisée dans
# ensemble_voter.py pour éviter la duplication de code.
# Voir ensemble_voter.run_ensemble_transcription() et detect_available_ensemble_models().


def transcribe_audio(audio_path, options=None, warnings=None):
    """
    Transcrit un fichier audio en événements de notes.
    
    Args:
        audio_path: Chemin vers le fichier audio
        options: dict contenant les clés transcriber, use_demucs, detect_tempo, etc.
        warnings: WarningCollector optionnel pour collecter les warnings structurés
        
    Returns:
        tuple: (note_events, midi_data, pedal_intervals, tempo, warning_msgs)
    """
    if options is None:
        options = {
            'transcriber': 'piano_transcription',
            'use_demucs': False,
            'detect_tempo': True,
            'onset_threshold': 0.5,
            'frame_threshold': 0.25
        }
    
    # P1.1 : Utiliser le collecteur si fourni, sinon fallback liste
    if warnings is None:
        warnings = WarningCollector()
    original_audio_path = audio_path
    

    # ── 1. Prétraitement Audio : Isolation Demucs ─────────────────────────────
    if options.get('use_demucs', False):
        print(f"[Transcriber DEBUG] use_demucs est TRUE. Options reçues: {options}")
        try:
            audio_path = run_demucs_isolation(audio_path, None)
        except Exception as e:
            warnings.add('demucs', 'warning', f'Demucs échoué: {e}. Désactivé.')
            audio_path = original_audio_path
        print(f"[Transcriber DEBUG] Chemin audio après Demucs: {audio_path}")
    else:
        print(f"[Transcriber DEBUG] use_demucs est FALSE. Options reçues: {options}")
    
    # ── 2. Moteur de transcription ────────────────────────────────────────────
    transcriber_choice = options.get('transcriber', 'piano_transcription')
    note_events = None
    midi_data = None
    pedal_intervals = []
    uncertain_indices = None  # P6.2 : indices des notes incertaines (ensemble mode)
  
    # Ensemble Voting (multi-modèles) — délégué à ensemble_voter.py
    if transcriber_choice == 'ensemble':
        from ensemble_voter import run_ensemble_transcription
        fused_result = run_ensemble_transcription(audio_path, options)
        # fused_result est un FusedResult avec attributs .notes, .midi, .pedals, .uncertain_ids
        note_events = fused_result.notes
        midi_data = fused_result.midi
        pedal_intervals = fused_result.pedals
        # P6.2 : indices incertains retournés directement
        uncertain_indices = fused_result.uncertain_ids
        if uncertain_indices:
            print(f"[Transcriber] P6.2 : {len(uncertain_indices)} notes marquées comme 'incertaines'")
  
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
        tempo_warn, tempo = detect_tempo_librosa(original_audio_path)
        if tempo_warn:
            warnings._warnings.extend(tempo_warn.warnings_full())
        if tempo:
            print(f"[Transcriber] Tempo détecté par Librosa : {tempo} BPM")

    if not tempo:
        tempo = estimate_tempo_from_events(note_events)
        print(f"[Transcriber] Tempo estimé à partir des notes : {tempo} BPM")

    # ── 3.5 Protection basse (main gauche) ───────────────────────────────────
    # [CRITIQUE] Les notes basses sont supprimées PAR LE MODÈLE (onset_threshold élevé).
    # Le filtrage harmonique ne supprime plus les basses (BASS_THRESHOLD = 55).
    # Mais le modèle supprime les notes AVANT de retourner les résultats.
    # Solution : on s'assure que les notes basses ont une vélocité suffisante
    # pour survivre au filtrage harmonique.
    
    if note_events and isinstance(note_events, list) and note_events and isinstance(note_events[0], tuple):
        notes_dict = [
            {
                'onset': n[0],
                'pitch': n[1],
                'duration': n[2],
                'velocity': (n[3] / 127.0) if n[3] > 1 else float(n[3])
            }
            for n in note_events
        ]
    else:
        notes_dict = note_events if note_events else []
    
    # Protection basse : forcer la conservation des notes graves (< BASS_ANCHOR)
    from voice_engine import BASS_ANCHOR
    _bass_protection_level = float(options.get('bass_protection_velocity', 0.0))
    _protected_count = 0
    if _bass_protection_level > 0.0:
        # Pour les notes graves, on force la vélocité à un niveau minimum
        # pour qu'elles survivent au filtrage harmonique (BASS_VELOCITY_PROTECTION_THRESHOLD = 0.35)
        for n in notes_dict:
            if n['pitch'] < BASS_ANCHOR:
                old_vel = n['velocity']
                # Force la vélocité à un minimum de 0.35 (seuil de protection harmonique)
                n['velocity'] = max(n['velocity'], 0.35)
                if old_vel < 0.35:
                    _protected_count += 1
        if _protected_count > 0:
            print(f"[Transcriber] 🎹 Protection basse ({_bass_protection_level:.2f}): {_protected_count} notes graves protégées (pitch < {BASS_ANCHOR}, vélocité forcée ≥ 0.35)")
    
    # ── 3.6 Filtrage harmonique UNIVERSEL (tous transcripteurs) ─────────────
    # [FIX CRITIQUE] Le filtrage était DANS run_piano_transcription() → inaccessible pour transkun.
    # On l'applique ICI dans transcribe_audio() pour qu'il s'applique à TOUS les transcripteurs.
    if notes_dict:
        harmonic_method = options.get('harmonic_filter', 'classical-strong')
        
        # [FIX CRITIQUE] Adapter automatiquement le mode harmonique selon le transcripteur
        # Transkun détecte beaucoup de graves → classical-strong supprime trop de notes graves
        # Si l'utilisateur n'a PAS explicitement configuré harmonic_filter, adapter automatiquement
        # transkun-chord = Transkun + filtre contextuel par accord (supprime notes parasites dans accords)
        if transcriber_choice == 'transkun' and harmonic_method == 'classical-strong':
            harmonic_method = 'transkun-chord'
            print(f"[Transcriber] 🔄 Harmonique adapté automatiquement: classical-strong → transkun-chord (notes parasites dans accords)")
        # Si des paramètres manuels fins sont fournis, utiliser la méthode 'custom'
        custom_params = {
            'velocity_ratio': options.get('harmonic_velocity_ratio'),
            'protection_threshold': options.get('harmonic_protection_threshold'),
            'time_tolerance': options.get('harmonic_time_tolerance'),
            'bass_threshold': options.get('harmonic_bass_threshold'),
        }
        has_custom = any(v is not None for v in custom_params.values())
        effective_method = 'custom' if has_custom else harmonic_method
        
        # [FIX CRITIQUE] Transmettre bass_protection_velocity au filtrage harmonique
        # Ce paramètre n'est PAS dans custom_params car il est géré séparément
        # Mais il DOIT être dans options pour que harmonic_filter le trouve
        bass_vel = options.get('bass_protection_velocity')
        if bass_vel is not None:
            # S'assurer que le seuil est bien transmis à harmonic_filter
            print(f"[Transcriber] bass_protection_velocity transmis: {bass_vel}")
        
        if effective_method and effective_method != 'off':
            try:
                from harmonic_filter import filter_ghost_notes as harmonic_filter
                # Transmettre les paramètres manuels dans options
                if has_custom:
                    options['_custom_harmonic'] = {k: v for k, v in custom_params.items() if v is not None}
                    print(f"[Transcriber] 🎹 Paramètres harmoniques manuels activés: {list(options['_custom_harmonic'].keys())}")
                before_count = len(notes_dict)
                notes_dict = harmonic_filter(notes_dict, options, method=effective_method)
                after_count = len(notes_dict)
                removed = before_count - after_count
                if removed > 0:
                    print(f"[Transcriber] 🎹 Filtrage harmonique ({harmonic_method}): {before_count} → {after_count} notes ({removed} supprimés)")
                else:
                    print(f"[Transcriber] 🎹 Filtrage harmonique ({harmonic_method}): {after_count} notes (rien supprimé)")
            except Exception as e:
                print(f"[Transcriber] ⚠ harmonic_filter indisponible ({e})")
        
        # Convertir notes_dict → note_events si nécessaire
        if isinstance(note_events, list) and note_events and isinstance(note_events[0], tuple):
            note_events = [
                (n['onset'], n['pitch'], n['duration'], int(round(n['velocity'] * 127)))
                for n in notes_dict
            ]
    
    # P6.2 : Retourner uncertain_indices dans le tuple (5e élément)
    return note_events, midi_data, pedal_intervals, tempo, warnings.warnings(), uncertain_indices


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
        # [FIX CRITIQUE] Utiliser sys.executable pour forcer le Python du venv
        # Sinon "python" peut aller chercher sur C:/ProgramData/... ou autre PATH système
        cmd = [
            sys.executable, "-m", "transkun.transcribe",
            audio_path,
            temp_midi_path,
            "--device", device_arg
        ]
        
        # [FIX] Ajouter le venv Scripts au PATH pour que les .exe de Transkun soient trouvables
        # Le venv utilise moduleconf, sox, seaborn etc. qui ont des dépendances natives (.exe)
        venv_scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(sys.executable))), 'Scripts')
        env = os.environ.copy()
        if 'PATH' in env:
            env['PATH'] = venv_scripts + ';' + env['PATH']
        else:
            env['PATH'] = venv_scripts
        
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        
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

        # [FIX] Extraire la pédale (CC64 = sustain) depuis le MIDI Transkun.
        # value >= 64 -> pédale enfoncée ; < 64 -> relâchée.
        # Auparavant : return ... , [] -> la pédale était systématiquement perdue.
        pedal_intervals = []
        for instrument in midi_data.instruments:
            pedal_down = None
            cc64 = sorted(
                [c for c in instrument.control_changes if c.number == 64],
                key=lambda c: c.time
            )
            for cc in cc64:
                if cc.value >= 64 and pedal_down is None:
                    pedal_down = cc.time
                elif cc.value < 64 and pedal_down is not None:
                    pedal_intervals.append((pedal_down, cc.time))
                    pedal_down = None
        pedal_intervals.sort(key=lambda p: p[0])
        print(f"[Transcriber] Transkun : {len(note_events)} notes, {len(pedal_intervals)} pédales extraites du MIDI")

        
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
    offset_threshold = float(options.get('offset_threshold', 0.3))
    transcriber.onset_threshold   = onset_threshold
    transcriber.frame_threshold   = frame_threshold
    transcriber.offset_threshold  = offset_threshold  # [FIX] typo corrigée + découplé de l'onset (défaut 0.3)
    print(f"[Piano] Seuils appliqués : onset={onset_threshold:.2f}, frame={frame_threshold:.2f}, offset={offset_threshold:.2f}")
    
    # =========================================================
    # [NOUVEAU] Seuil minimum pour les basses (Option B - version simple)
    # Si use_adaptive_threshold=True, le seuil des basses est limité
    # par bass_onset_threshold (seuil minimum garanti).
    # Le modèle utilise un seuil UNIFORME (il ne supporte pas dict).
    # La protection basse se fait APRÈS via bass_protection_velocity.
    # =========================================================
    from voice_engine import BASS_ANCHOR
    bass_onset_threshold = float(options.get('bass_onset_threshold', 0.15))
    use_adaptive_threshold = options.get('use_adaptive_threshold', True)
    
    if use_adaptive_threshold:
        # Pour les basses : utiliser le PLUS PETIT des deux seuils
        # (le seuil le PLUS BAS = le PLUS SENSIBLE)
        effective_onset = min(onset_threshold, bass_onset_threshold)
        print(f"[Piano] Seuil adaptatif activé : basses(min={effective_onset:.2f}), aigus={onset_threshold:.2f}")
        # Appliquer le seuil adaptatif aux basses
        if effective_onset < onset_threshold:
            transcriber.onset_threshold = effective_onset
            print(f"[Piano] → Seuil basal réduit à {effective_onset:.2f} pour protéger les basses")
    else:
        print(f"[Piano] Seuil adaptatif désactivé — seuil unique: {onset_threshold:.2f}")

    # =========================================================
    # LOAD AUDIO (CPU)
    # =========================================================
    prof.start("io_audio")

    audio, _ = load_audio(audio_path, sr=sample_rate, mono=True)

    prof.stop()

    # =========================================================
    # INFERENCE (GPU CORE) — avec seuils adaptatifs si activés
    # =========================================================
    prof.start("inference")

    print(f"[Piano] Inference sur: {actual_device}")
    
    # Préparer les options de transcription
    # piano_transcription_inference supporte onset_threshold/frame_threshold/offset_threshold
    # comme arguments NOMMÉS de .transcribe(). C'est PLUS fiable que les attributs.
    print(f"[Piano] Seuils passés à transcribe() : onset={onset_threshold:.2f}, frame={frame_threshold:.2f}, offset={offset_threshold:.2f}")
    
    with torch.no_grad():
        transcribed_dict = transcriber.transcribe(
            audio,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            offset_threshold=offset_threshold,
        )
    
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


# ── P1.4 : Import de tonality_detector avec gestion ImportError ─────────────────

_tonality_detector_available = False
_tonality_detector_error = None
_detect_tonality_fn = None

try:
    from tonality_detector import detect_tonality as _dt_fn
    _tonality_detector_available = True
    _detect_tonality_fn = _dt_fn
except ImportError as e:
    _tonality_detector_error = str(e)
except Exception as e:
    _tonality_detector_error = str(e)


def detect_tonality_safe(note_events, audio_path=None, sr=22050, warnings=None):
    """
    Détecte la tonalité en utilisant tonality_detector si disponible.
    
    P1.4 : Si tonality_detector n'est pas disponible, retourne un warning
    structuré au lieu de planter avec ImportError.
    
    Args:
        note_events: Liste d'événements notes (tuple ou dict)
        audio_path: Chemin optionnel vers le fichier audio
        sr: Sample rate
        warnings: WarningCollector optionnel pour ajouter un warning si indisponible
        
    Returns:
        dict: {
            'key': str (12 pitches),
            'mode': 'major' | 'minor',
            'confidence': float 0-1,
            'source': 'tonality_detector' | 'fallback_pitch_class' | 'default',
            'error': str | None
        }
    """
    # Si tonality_detector est disponible, l'utiliser
    if _tonality_detector_available and _detect_tonality_fn is not None:
        try:
            result = _detect_tonality_fn(note_events, audio_path, sr)
            result['source'] = 'tonality_detector'
            result['error'] = None
            return result
        except Exception as e:
            # Le module est importé mais a échoué à l'exécution
            if warnings is not None:
                warnings.add_warning('tonality', f'tonality_detector a échoué : {e}')
            # Fallback vers détection par pitch class
            return _detect_from_pitch_class(note_events)
    
    # tonality_detector indisponible → warning + fallback
    if warnings is not None:
        warnings.add_warning(
            'tonality',
            f'tonality_detector indisponible ({_tonality_detector_error}). '
            'Utilisation de la détection par distribution de hauteurs (fallback).'
        )
    return _detect_from_pitch_class(note_events)


def _detect_from_pitch_class(note_events):
    """
    Fallback : détection de tonalité par distribution de pitch classes.
    
    Implémentation simplifiée inspirée de tonality_detector mais
    sans dépendances externes (soundfile, librosa).
    """
    if not note_events or len(note_events) == 0:
        return {
            'key': 'C',
            'mode': 'major',
            'confidence': 0.0,
            'source': 'fallback_pitch_class',
            'error': None,
            'profile': [0.0] * 12
        }
    
    # Compter les pitch classes
    pitch_class_counts = [0] * 12
    for event in note_events:
        if isinstance(event, dict):
            midi_note = event.get('midi_note', event.get('pitch_midi', 0))
        elif isinstance(event, (list, tuple)):
            midi_note = int(event[1])
        else:
            continue
        pc = int(midi_note) % 12
        pitch_class_counts[pc] += 1
    
    # Normaliser
    total = sum(pitch_class_counts)
    if total == 0:
        return {
            'key': 'C',
            'mode': 'major',
            'confidence': 0.0,
            'source': 'fallback_pitch_class',
            'error': None,
            'profile': [0.0] * 12
        }
    
    chroma = np.array(pitch_class_counts, dtype=float) / total
    
    # Profils Krumhansl-Schmuckler
    MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 3.54, 2.36, 3.17, 2.88, 3.32]
    MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 4.57, 2.48, 3.70, 4.77, 3.18, 2.30]
    keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    
    best_major_corr = -float('inf')
    best_minor_corr = -float('inf')
    major_key = 0
    minor_key = 0
    
    for rot in range(12):
        rotated_major = np.roll(MAJOR_PROFILE, rot)
        corr_m = float(np.dot(chroma, rotated_major) / (np.linalg.norm(chroma) * np.linalg.norm(rotated_major) + 1e-10))
        if corr_m > best_major_corr:
            best_major_corr = corr_m
            major_key = rot
        
        rotated_minor = np.roll(MINOR_PROFILE, rot)
        corr_mi = float(np.dot(chroma, rotated_minor) / (np.linalg.norm(chroma) * np.linalg.norm(rotated_minor) + 1e-10))
        if corr_mi > best_minor_corr:
            best_minor_corr = corr_mi
            minor_key = rot
    
    if best_major_corr > best_minor_corr:
        key = keys[major_key]
        mode = "major"
        confidence = min(max(best_major_corr / 5.0, 0.0), 1.0)
        profile = [float(x) for x in np.roll(MAJOR_PROFILE, major_key)]
    else:
        key = keys[minor_key]
        mode = "minor"
        confidence = min(max(best_minor_corr / 5.0, 0.0), 1.0)
        profile = [float(x) for x in np.roll(MINOR_PROFILE, minor_key)]
    
    return {
        'key': key,
        'mode': mode,
        'confidence': round(confidence, 4),
        'source': 'fallback_pitch_class',
        'error': None,
        'profile': profile
    }


class WarningCollector:
    """
    Collecteur de warnings structuré pour le pipeline.
    
    Accumule les warnings avec catégorie, niveau de sévérité et message.
    Le pipeline retourne warnings() au frontend via score_data['warnings'].
    
    En mode strict (strict_mode=True), les warnings de niveau 'error' lèvent
    une exception au lieu d'être simplement collectés.
    """
    
    def __init__(self, strict_mode=False):
        self._warnings = []
        self._strict_mode = strict_mode
    
    def add(self, category, level, message):
        """Ajouter un warning structuré."""
        entry = {
            'category': category,
            'level': level,
            'message': message,
        }
        self._warnings.append(entry)
        
        # P1.2 : Mode strict — lever une exception pour les erreurs critiques
        if self._strict_mode and level == 'error':
            raise PipelineError(
                f"[{category.upper()}] {message}"
            )
    
    def add_critical(self, category, message):
        """Ajouter un warning de niveau error (raccourci)."""
        self.add(category, 'error', message)
    
    def add_warning(self, category, message):
        """Ajouter un warning de niveau warning (raccourci)."""
        self.add(category, 'warning', message)
    
    def add_info(self, category, message):
        """Ajouter un warning de niveau info (raccourci)."""
        self.add(category, 'info', message)
    
    def warnings(self):
        """Retourne la liste des messages (pour compatibilité backward)."""
        return [w['message'] for w in self._warnings]
    
    def warnings_full(self):
        """Retourne les warnings complets avec métadonnées."""
        return list(self._warnings)
    
    def has_errors(self):
        return any(w['level'] == 'error' for w in self._warnings)
    
    def has_warnings(self):
        return any(w['level'] == 'warning' for w in self._warnings)
    
    def clear(self):
        """Vider le collecteur."""
        self._warnings.clear()
    
    def __bool__(self):
        return len(self._warnings) > 0


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
    """Détecte le tempo à l'aide de librosa.beat.beat_track().
    
    Returns:
        tuple: (warnings_collected, tempo) — warnings est un WarningCollector
    """
    warnings = WarningCollector()
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
            return warnings, int(round(tempo_val))
        else:
            warnings.add_warning('tempo', f'Tempo hors plage: {tempo_val} BPM (40-250 requis)')
    except Exception as e:
        warnings.add_warning('tempo', f'Détection tempo Librosa échouée: {e}')
    return warnings, None


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
    
    Supporte un callback de progression pour le SSE progress :
        progress_cb(step: str, message: str, progress: float) -> None
    """
    
    def __init__(self):
        self.name = "TranscriptionPipeline v3"
    
    def run(self, input_path, output_dir, options=None, progress_cb=None):
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
        
        def _cb(step, message, progress):
            if progress_cb:
                try:
                    progress_cb(step, message, progress)
                except Exception as e:
                    print(f"[Pipeline] ⚠ progress_cb error: {e}")
        
        # [DEBUG] Forcer un flush des logs pour tracer le pipeline
        import sys; sys.stdout.flush()
        
        _cb('init', 'Démarrage de la transcription...', 0.0)

        options = options or {
            'transcriber': 'piano_transcription',
            'use_demucs': False,
            'detect_tempo': True,
            'onset_threshold': 0.5,
            'frame_threshold': 0.25,
        }

        # ── 1. Transcription brute (audio → note_events) ─────────────────────
        _cb('load_audio', 'Chargement du fichier audio...', 0.05)
        _cb('demucs', 'Prétraitement audio (Demucs)...', 0.15)
        _cb('transcription', 'Transcription IA en cours...', 0.25)
        print(f"[Pipeline] >>> Appel transcribe_audio()...", flush=True)
        
        # P1.1 : Collecteur de warnings structuré
        # P1.2 : Support du mode strict via option 'strict_mode'
        strict_mode = options.get('strict_mode', False)
        pipeline_warnings = WarningCollector(strict_mode=strict_mode)
        
        print(f"[Pipeline] [1/8] Transcription audio (onset detection + modèle IA)...")
        note_events, midi_data, pedal_intervals, raw_tempo, _warnings_list, uncertain_indices = transcribe_audio(
            input_path, options, warnings=pipeline_warnings
        )
        print(f"[Pipeline] <<< transcribe_audio() terminé: {len(note_events)} notes", flush=True)
        _cb('transcription', f'Transcription terminée: {len(note_events)} notes brutes', 0.35)
        
        # P1.2 : Erreur critique — aucune note détectée
        if strict_mode and not note_events:
            pipeline_warnings.add_critical('transcription', 'Aucune note détectée dans l\'audio')
        
        if not note_events:
            raise ValueError("Aucune note détectée dans l'audio")
        print(f"[Pipeline] {len(note_events)} notes brutes")

        # ── 1.5 Filtrage + P5.1 pedal-aware shortening ─────────────────────
        # [P5] IMPORTANT : apply_pedal_aware_shortening est APPLIQUÉ APRÈS la quantification
        # pour préserver les durées cohérentes avec la pédale.
        # La quantification se fait en beats, apply_pedal_aware_shortening
        # se fait en secondes AVANT quantification → on inverse l'ordre.
        
        _cb('filtering', 'Filtrage des notes et analyse de la pédale...', 0.38)
        
        notes_dict = [
            {
                'onset': n[0],
                'pitch': n[1],
                'duration': n[2],
                'velocity': (n[3] / 127.0) if n[3] > 1 else float(n[3])
            }
            for n in note_events
        ]
        try:
            from note_filter import filter_ghost_notes
            notes_dict = filter_ghost_notes(notes_dict, options)
            print(f"[Pipeline] {len(notes_dict)} notes après filter_ghost_notes")
        except Exception as e:
            print(f"[Pipeline] ⚠ note_filter.filter_ghost_notes indisponible ({e})")
        
        # [NOTE] Le filtrage harmonique est maintenant appliqué UNIVERSELLEMENT
        # dans transcribe_audio() (lignes ~210), AVANT le retour du pipeline.
        # Il ne doit PAS être appliqué à nouveau ici pour éviter le double filtrage.
        # ── P5.1 : apply_pedal_aware_shortening AVANT quantification ─────────
        # On raccourcit les notes en secondes AVANT de quantifier en beats.
        # Si on le faisait après quantification, les durées seraient déjà
        # arrondies et incohérentes avec les temps réels de la pédale.
        try:
            from note_filter import apply_pedal_aware_shortening
            notes_dict = apply_pedal_aware_shortening(notes_dict, pedal_intervals or [], options)
            print(f"[Pipeline] {len(notes_dict)} notes après apply_pedal_aware_shortening (P5.1)")
        except Exception as e:
            print(f"[Pipeline] ⚠ note_filter.apply_pedal_aware_shortening indisponible ({e})")

        remove_short = options.get('remove_short_notes', False)
        min_dur_s = options.get('minimum_note_duration', 50) / 1000.0
        if remove_short:
            notes_dict = [n for n in notes_dict if n['duration'] >= min_dur_s]

        if options.get('merge_near_notes', False):
            merge_gap_s = options.get('merge_gap_ms', 30) / 1000.0
            notes_dict.sort(key=lambda n: (n['pitch'], n['onset']))
            merged = []
            for n in notes_dict:
                if merged and merged[-1]['pitch'] == n['pitch']:
                    gap = n['onset'] - (merged[-1]['onset'] + merged[-1]['duration'])

                    # Fusion uniquement si le silence est très court
                    if 0 <= gap <= merge_gap_s:
                        prev = merged[-1]
                        prev['duration'] = (n['onset'] + n['duration']) - prev['onset']
                        prev['velocity'] = max(prev['velocity'], n['velocity'])
                    else:
                        merged.append(dict(n))
                else:
                    merged.append(dict(n))
            notes_dict = merged
            notes_dict.sort(key=lambda n: n['onset'])

        # ── P5.2 : Vélocité standardisée 0-127 ──────────────────────────────
        # Conversion de velocity [0.0-1.0] → [0-127] avec préservation
        # de la dynamique originale (max/médiane pondérée).
        original_velocities = [n['velocity'] for n in notes_dict if n['velocity'] > 0]
        if original_velocities:
            max_amp = max(original_velocities)
            median_amp = sorted(original_velocities)[len(original_velocities) // 2]
            print(f"[Pipeline] P5.3 : max_amplitude={max_amp:.3f}, median_amplitude={median_amp:.3f}")
        
        note_events = [
            (
                n['onset'],
                n['pitch'],
                n['duration'],
                int(round(n['velocity'] * 127)) if n['velocity'] <= 1.0 else int(n['velocity']),
            )
            for n in notes_dict
        ]
        print(f"[Pipeline] {len(note_events)} notes après filtrage complet (P5.2)")

        # ── 2. Tempo Map ─────────────────────────────────────────────────────
        _cb('tempomap', 'Analyse du tempo et de la mesure...', 0.50)
        print(f"[Pipeline] >>> build_tempo_map()...", flush=True)
        
        user_tempo = options.get('tempo')
        start_bpm = float(user_tempo) if user_tempo else None
        tm = build_tempo_map(input_path, note_events, start_bpm=start_bpm)
        print(f"[Pipeline] <<< build_tempo_map() terminé: BPM={tm.global_bpm}", flush=True)
        display_bpm = tm.global_bpm
        if start_bpm and not options.get('detect_tempo', True):
            display_bpm = start_bpm

        # ── 3. Quantification (V4 tempo-map-aware, fallback V3) ──────────────
        quantization_level = options.get('quantization_level', 'standard')
        _cb('quantization', 'Quantification rythmique...', 0.55)
        print(f"[Pipeline] >>> Quantification ({quantization_level})...", flush=True)
        quantized_notes = None
        quantizer_method = 'unknown'
        try:
            from tempo_quantizer import quantize_notes as quantize_notes_v4
            print(f"[Pipeline] >>> Import tempo_quantizer...", flush=True)
            quantized_notes = quantize_notes_v4(
                note_events,
                bpm=tm.global_bpm,
                quantization_level=quantization_level,
                enable_rubato=options.get('enable_rubato', False),
                enable_triplets=options.get('enable_triplets', False),
                tempo_map=tm,
                quantization_sensitivity=options.get('quantization_sensitivity'),
            )
            quantizer_method = 'tempo_quantizer (V4)'
            print(f"[Pipeline] <<< Quantizer V4 OK ({quantization_level})", flush=True)
        except Exception as e:
            # P1.2 : Erreur critique en mode strict
            if strict_mode:
                pipeline_warnings.add_critical('quantizer', f'Quantizer V4 indisponible et aucune alternative : {e}')
            print(f"[Pipeline] ⚠ Quantizer V4 indisponible ({e}), fallback V3")
            try:
                from quantizer import quantize_notes as quantize_notes_v3
                print(f"[Pipeline] >>> Import quantizer (fallback)...", flush=True)
                quantized_notes = quantize_notes_v3(
                    note_events,
                    bpm=tm.global_bpm,
                    quantization_level=quantization_level,
                    enable_rubato=options.get('enable_rubato', False),
                    enable_triplets=options.get('enable_triplets', False),
                    tempo_map=tm,
                    quantization_sensitivity=options.get('quantization_sensitivity'),
                )
                quantizer_method = 'quantizer (V3 fallback)'
                print(f"[Pipeline] <<< Quantizer V3 OK", flush=True)
            except Exception as e2:
                if strict_mode:
                    pipeline_warnings.add_critical('quantizer', f'Tous les quantizers ont échoué : V4({e}), V3({e2})')
                raise
        print(f"[Pipeline] <<< {len(quantized_notes)} notes quantisées ({quantizer_method})", flush=True)
        _cb('quantization', f'Quantification terminée: {len(quantized_notes)} notes', 0.70)

        # ── 4. Analyse harmonique (TOUJOURS) ──────────────────────────────
        _cb('harmony', 'Analyse harmonique et détection de tonalité...', 0.70)
        print(f"[Pipeline] >>> Analyse harmonique...", flush=True)
        
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
                key_name = harmonic_ctx.global_key or options.get('key_sig', 'C')
                print(f"[Pipeline] <<< Tonalité détectée: {key_name}", flush=True)
            else:
                key_name = options.get('key_sig', 'C')
                print(f"[Pipeline] <<< Tonalité manuelle respectée: {key_name}", flush=True)
        except Exception as e:
            # P1.2 : Erreur critique en mode strict (harmonie nécessaire pour split LH/MD)
            if strict_mode:
                pipeline_warnings.add_critical('harmony', f'Analyse harmonique en échec : {e}')
            print(f"[Pipeline] <<< Analyse harmonique en échec ({e})", flush=True)

        # ── 5. Séparation LH/RH guidée par harmonie (FIX #3) ─────────────────
        _cb('voice_split', 'Séparation mains gauche/droite...', 0.78)
        print(f"[Pipeline] >>> Split LH/RH...", flush=True)
        
        try:
            if harmonic_ctx is not None:
                from voice_engine import split_with_harmony
                print(f"[Pipeline] >>> split_with_harmony...", flush=True)
                voices = split_with_harmony(quantized_notes, harmonic_ctx, options)
                print(f"[Pipeline] <<< split_with_harmony OK", flush=True)
                print("[Pipeline] Split LH/RH : split_with_harmony (guidé)")
            else:
                print(f"[Pipeline] >>> split_voices (fallback)...", flush=True)
                voices = split_voices(quantized_notes, options=options)
                print(f"[Pipeline] <<< split_voices OK", flush=True)
                print("[Pipeline] Split LH/RH : split_voices (fallback)")
        except Exception as e:
            # P1.2 : Erreur critique en mode strict (split nécessaire pour partition)
            if strict_mode:
                pipeline_warnings.add_critical('voice_split', f'Séparation LH/RH en échec : {e}')
            print(f"[Pipeline] <<< split_with_harmony échoué ({e}), fallback split_voices", flush=True)
            voices = split_voices(quantized_notes, options=options)

        # ── 6. Construction du score ─────────────────────────────────────────
        _cb('score_build', 'Construction de la partition...', 0.85)
        print(f"[Pipeline] >>> build_score()...", flush=True)
        
        time_sig_str = options.get('time_sig', '4/4')
        try:
            ts_parts = time_sig_str.split('/')
            time_signature = [int(ts_parts[0]), int(ts_parts[1])]
        except Exception:
            time_signature = list(tm.estimated_meter)

        show_chords = options.get('chord_symbols', True) or (preset == 'jazz')

        score_options = {
            'detect_key': options.get('detect_key', True),  # Conserver la valeur originale de detect_key
            'time_sig': time_signature,
            'display_bpm': display_bpm,
            'write_chord_symbols': show_chords,
            'detect_dynamics': True,
        }
        
        # [DEBUG] Confirmer que detect_key et key_sig sont bien transmis
        print(f"[Pipeline DEBUG] detect_key={options.get('detect_key', True)} | key_sig={options.get('key_sig', 'C')} | score_options={score_options}")

        pedal_beats_list = []
        if pedal_intervals:
            for p_start, p_end in pedal_intervals:
                pedal_beats_list.append(
                    (tm.seconds_to_beat(p_start), tm.seconds_to_beat(p_end))
                )

        # [P6] Collecter les IDs de notes incertaines (fallback single-model)
        uncertain_note_ids = list(uncertain_indices) if uncertain_indices else []
        if uncertain_note_ids:
            print(f"[Pipeline] {len(uncertain_note_ids)} notes marquées comme 'incertaines' (P6)")

        # CORRECTION BUG TONALITÉ : passer la tonalité MANUELLE (options.get('key_sig'))
        # au lieu de key_name (détection harmonique). build_score() choisira ensuite :
        # - si detect_key=True : lance le détecteur Krumhansl-Schmuckler
        # - si detect_key=False : utilise key_sig tel quel (la tonalité manuelle)
        score_data = build_score(
            voices, tm,
            key_sig=options.get('key_sig', 'C'),  # ← tonalité manuelle de l'UI
            options=score_options,
            harmonic_ctx=harmonic_ctx,
            pedals=pedal_beats_list,
            uncertain_note_ids=uncertain_note_ids,  # [P6]
        )

        # ── [SMOOTH] Simplification rythmique + BPM ×2 ───────────────────────
        enable_smooth = options.get('enable_smooth', False)
        if enable_smooth:
            _cb('smooth', 'Simplification rythmique (Smooth)...', 0.88)
            print("[Pipeline] >>> Smooth mode actif : simplification rythmique...", flush=True)
            try:
                from rhythm_simplifier import simplify_rhythm
                score_data = simplify_rhythm(score_data)
                print("[Pipeline] <<< Simplification rythmique terminée", flush=True)
            except Exception as e:
                print(f"[Pipeline] ⚠ rhythm_simplifier indisponible ({e})", flush=True)

        score_data.setdefault('metadata', {})['warnings'] = pipeline_warnings.warnings()

        # ── 2.5 [P3.5] Transmettre métadonnées TempoMap au score_data ───────
        score_data['tempoMapMethod']  = tm.method
        score_data['detectedMeter']   = list(tm.estimated_meter)
        score_data['tempoRange']      = tm.tempo_range() if hasattr(tm, 'tempo_range') else []
        score_data['tempoConfidence'] = (
            0.85 if tm.method == 'madmom'
            else (0.6 if tm.method == 'librosa_advanced' else 0.3)
        )
        print(f"[Pipeline] TempoMap: method={tm.method} BPM={tm.global_bpm:.1f} "
              f"meter={tm.estimated_meter} beats={len(tm.beat_times)} "
              f"downbeats={len(tm.downbeat_times)}")

        # ── 2.6 [P3.5] Vérifier cohérence signature détectée vs demandée ──
        if options.get('detect_meter', True):
            detected = tm.estimated_meter
            if detected[0] == 3 and options.get('time_sig', '4/4') == '3/4':
                print("[Pipeline] ✓ Signature 3/4 détectée et confirmée (Mazurka OK)")
            elif detected[0] != int(options.get('time_sig', '4/4').split('/')[0]):
                print(f"[Pipeline] ⚠ Signature auto ({detected[0]}/{detected[1]}) ≠ "
                      f"manuelle ({options.get('time_sig', '4/4')})")
        else:
            print(f"[Pipeline] Tempo utilisateur: {options.get('tempo', 'auto')} BPM")

        # ── 7. Export MIDI + MusicXML réel (FIX #5) ──────────────────────────
        _cb('export', 'Export MIDI et MusicXML...', 0.92)
        
        os.makedirs(output_dir, exist_ok=True)
        midi_path = os.path.join(output_dir, 'output.mid')
        xml_path = os.path.join(output_dir, 'score.musicxml')

        # P1.2 : Export MIDI — erreur critique si échec
        try:
            from midi_parser import score_to_midi
            score_to_midi(score_data, midi_path)
        except Exception as e:
            if strict_mode:
                pipeline_warnings.add_critical('midi_export', f'Export MIDI en échec : {e}')
            raise

        # P1.3 : Export MusicXML — plus jamais de stub vide
        try:
            from musicxml_exporter import export_musicxml
            export_musicxml(score_data, xml_path)
            print(f"[Pipeline] MusicXML généré : {xml_path}")
        except Exception as e:
            # P1.2 : En mode strict, lever une exception
            if strict_mode:
                pipeline_warnings.add_critical('musicxml_export', f'Export MusicXML en échec : {e}')
                raise
            # P1.3 : En mode normal, lever quand même (plus de stub)
            # Mais on continue si music21 n'est pas installé (erreur courante en dev)
            if 'music21' in str(e) or 'ModuleNotFoundError' in str(type(e).__bases__):
                pipeline_warnings.add_warning('musicxml_export', f'music21 non disponible : {e}')
                xml_path = None  # Indique que le fichier n'a pas été généré
            else:
                pipeline_warnings.add_critical('musicxml_export', f'Export MusicXML en échec : {e}')
                raise
        print(f"[Pipeline] <<< build_score() terminé", flush=True)

        # ── 8. Métadonnées pour le frontend ──────────────────────────────────
        score_data['midi_path'] = midi_path
        score_data['xml_path'] = xml_path
        score_data['note_count'] = len(quantized_notes)
        score_data['warnings'] = pipeline_warnings.warnings()
        score_data['warnings_full'] = pipeline_warnings.warnings_full()
        score_data['tempoMapMethod'] = tm.method
        score_data['tempoConfidence'] = (
            0.85 if tm.method == 'madmom'
            else (0.6 if tm.method == 'librosa_advanced' else 0.3)
        )
        score_data['tempoRange'] = tm.tempo_range()
        score_data['detectedMeter'] = tm.estimated_meter

        _cb('done', f'Terminé — MIDI: {midi_path} | XML: {xml_path}', 1.0)
        
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
