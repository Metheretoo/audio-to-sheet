"\"\"\"
PATCH — transcriber.run_ensemble_transcription (Phase 3)

Objectif : mode ensemble propre et robuste en local.
  1. Détecter à runtime les modèles réellement installés (skip mt3 si /mt3 absent,
     skip hft si le module Python n'est pas là, etc.).
  2. Éviter les logs d'erreur bruyants pour des modèles qui ne peuvent pas tourner
     sur l'environnement (mt3 = Docker uniquement).
  3. Retomber automatiquement sur les modèles disponibles.

CONSTAT actuel (transcriber.py:100-148) :
  - `models_config` liste par défaut : piano_transcription, basic_pitch, transkun, hft.
  - `model_functions` mappe aussi `mt3` (mais mt3 n'est jamais dans la liste par défaut,
    OK).
  - `hft` est mappé via `__import__('run_hft', fromlist=['run_hft']).run_hft(p, o)` —
    ça lève ImportError silencieusement dans le try/except.
  - `transkun` s'exécute via subprocess (`python -m transkun.transcribe`) → OK
    si `pip install transkun` a marché (déjà dans requirements.txt).

À APPLIQUER : remplacer les blocs `models_config = ensemble_config.get(...)` et
`model_functions = {...}` (lignes ~103-124) par le code ci-dessous.
\"\"\"

# ============================================================================
# À AJOUTER en tête du fichier transcriber.py (une seule fois, après les imports)
# ============================================================================

def _detect_available_ensemble_models() -> dict:
    \"\"\"
    Détecte à runtime quels modèles d'ensemble sont réellement utilisables.
    Renvoie un dict {model_name: bool}.
    \"\"\"
    import importlib
    import os
    availability = {
        'piano_transcription': False,
        'basic_pitch': False,
        'transkun': False,
        'hft': False,
        'mt3': False,
    }

    # piano_transcription_inference (lib pip)
    try:
        importlib.import_module('piano_transcription_inference')
        availability['piano_transcription'] = True
    except ImportError:
        pass

    # basic_pitch (lib pip Spotify)
    try:
        importlib.import_module('basic_pitch.inference')
        availability['basic_pitch'] = True
    except ImportError:
        pass

    # transkun (exécuté via subprocess, on vérifie que le module est là)
    try:
        importlib.import_module('transkun')
        availability['transkun'] = True
    except ImportError:
        pass

    # hft (via run_hft.py local)
    try:
        # run_hft.py existe dans backend/ mais il importe des libs externes qui
        # peuvent manquer. Tentative d'import réelle.
        importlib.import_module('run_hft')
        availability['hft'] = True
    except (ImportError, ModuleNotFoundError):
        pass

    # mt3 : uniquement si /mt3 existe (chemin Docker)
    mt3_path = os.environ.get('MT3_PATH', '/mt3')
    availability['mt3'] = os.path.isdir(mt3_path)

    return availability


# ============================================================================
# À REMPLACER dans run_ensemble_transcription() aux alentours de la ligne 100
# ============================================================================

def run_ensemble_transcription(audio_path, options):
    \"\"\"
    Exécute la transcription en mode ensemble (vote multi-modèles).
    Auto-détection des modèles disponibles + filtrage transparent.
    \"\"\"
    import time
    from collections import defaultdict
    import numpy as np
    import pretty_midi

    print(\"[Ensemble] Démarrage de la transcription en mode ensemble...\")
    t0 = time.perf_counter()

    ensemble_config = options.get('ensemble', {})

    # Configuration par défaut des modèles (poids)
    default_models = [
        {'name': 'piano_transcription', 'weight': 1.5, 'onset_weight': 1.2, 'pitch_weight': 1.0, 'duration_weight': 1.0},
        {'name': 'transkun',           'weight': 1.3, 'onset_weight': 1.1, 'pitch_weight': 1.1, 'duration_weight': 1.1},
        {'name': 'basic_pitch',        'weight': 1.0, 'onset_weight': 1.0, 'pitch_weight': 1.0, 'duration_weight': 0.8},
        {'name': 'hft',                'weight': 1.2, 'onset_weight': 1.0, 'pitch_weight': 1.0, 'duration_weight': 1.0},
    ]
    models_config = ensemble_config.get('models', default_models)

    # PHASE 3 : filtrer selon la dispo réelle des modèles
    availability = _detect_available_ensemble_models()
    print(f\"[Ensemble] Modèles disponibles : \"
          f\"{[k for k, v in availability.items() if v]}\")

    filtered_models = [m for m in models_config if availability.get(m['name'], False)]
    if len(filtered_models) < len(models_config):
        skipped = [m['name'] for m in models_config if not availability.get(m['name'], False)]
        print(f\"[Ensemble] ⚠ Modèles indisponibles, ignorés : {skipped}\")

    if not filtered_models:
        # Fallback : au moins piano_transcription doit être là
        raise RuntimeError(
            \"Ensemble impossible : aucun modèle installé. \"
            \"Vérifie : pip install piano_transcription_inference basic_pitch transkun\"
        )

    if len(filtered_models) < 2:
        # Un seul modèle → ce n'est plus un vrai ensemble
        print(f\"[Ensemble] Un seul modèle dispo ({filtered_models[0]['name']}), \"
              f\"bascule sur mode single-model.\")
        return model_functions[filtered_models[0]['name']](audio_path, options)

    models_config = filtered_models

    onset_tolerance = ensemble_config.get('onset_tolerance', 0.05)
    pitch_tolerance = ensemble_config.get('pitch_tolerance', 1)
    min_votes = ensemble_config.get('min_votes', 2)
    velocity_aggregation = ensemble_config.get('velocity_aggregation', 'weighted_mean')
    duration_aggregation = ensemble_config.get('duration_aggregation', 'median')

    # Mapping nom → fonction (mt3 retiré du défaut mais laissé pour override manuel)
    model_functions = {
        'piano_transcription': run_piano_transcription,
        'basic_pitch': run_basic_pitch,
        'transkun': run_transkun,
        'hft': lambda p, o: __import__('run_hft', fromlist=['run_hft']).run_hft(p, o),
        'mt3': run_mt3,
    }

    # ... (le reste de la fonction reste INCHANGÉ : boucle d'exécution des modèles,
    #      clustering, fusion, agrégation, MIDI final)


# ============================================================================
# Modifications config.yaml (Phase 3, section ensemble)
# ============================================================================
\"\"\"
Dans `config.yaml`, section `ensemble.models`, RETIRER l'entrée `hft` du défaut
(sauf si tu l'installes) et REORDONNER par poids décroissant :

  models:
    - name: \"piano_transcription\"
      weight: 1.5
      onset_weight: 1.2
      pitch_weight: 1.0
      duration_weight: 1.0
    - name: \"transkun\"           # 2ème position (fort en polyphonie classique)
      weight: 1.3
      onset_weight: 1.1
      pitch_weight: 1.1
      duration_weight: 1.1
    - name: \"basic_pitch\"
      weight: 1.0
      onset_weight: 1.0
      pitch_weight: 1.0
      duration_weight: 0.8
    # - name: \"hft\"              # décommenter uniquement si hft est installé
    # - name: \"mt3\"              # UNIQUEMENT en env Docker avec /mt3 monté
\"\"\"


# ============================================================================
# Test rapide (à mettre dans un fichier _test_ensemble_availability.py à la racine)
# ============================================================================
\"\"\"
# Lancement : python backend/_test_ensemble_availability.py
from backend.transcriber import _detect_available_ensemble_models

avail = _detect_available_ensemble_models()
print(\"Modèles d'ensemble disponibles sur cette machine :\")
for name, ok in avail.items():
    print(f\"  {'✅' if ok else '❌'} {name}\")

n_avail = sum(1 for v in avail.values() if v)
if n_avail < 2:
    print(f\"
⚠ Seulement {n_avail} modèle(s) dispo — l'ensemble ne sera pas actif.\")
    print(\"Installe au minimum piano_transcription_inference + transkun.\")
else:
    print(f\"
✅ {n_avail} modèles dispos, ensemble opérationnel.\")
\"\"\"
"