#!/usr/bin/env python3
"""
AudioScore v5 — Diagnostic Environnement (Phase 0)
Vérifie tous les composants critiques avant de lancer le pipeline.

Utilisation:
    python diagnose_env.py [--fix]

Sortie:
    Rapport complet avec statut chaque composant.
"""
import sys
import os
import subprocess
import importlib.util
import platform
from pathlib import Path
from datetime import datetime

# ─── Configuration ───────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

# Composants critiques
CRITICAL_COMPONENTS = {
    "python": {
        "description": "Python 3.10+",
        "check": "system",
    },
    "librosa": {
        "description": "Traitement audio",
        "check": "import",
    },
    "numpy": {
        "description": "Calcul numérique",
        "check": "import",
    },
    "scipy": {
        "description": "Signal processing",
        "check": "import",
    },
    "soundfile": {
        "description": "Lecture/écriture audio",
        "check": "import",
    },
    "music21": {
        "description": "Génération partition",
        "check": "import",
    },
    "torch": {
        "description": "PyTorch (DL framework)",
        "check": "import",
    },
    "demucs": {
        "description": "Séparation audio",
        "check": "import",
    },
    # basic_pitch retiré: qualité inférieure sur piano classique, piano_transcription suffisant
    "piano_transcription_inference": {
        "description": "Piano Transcription",
        "check": "import",
    },
    "lameenc": {
        "description": "Encodage MP3/MIDI",
        "check": "import",
    },
    "pydub": {
        "description": "Conversion audio",
        "check": "import",
    },
    "yaml": {
        "description": "Configuration YAML",
        "check": "import",
    },
    "ffmpeg": {
        "description": "FFmpeg (conversion audio)",
        "check": "binary",
    },
    "ffprobe": {
        "description": "FFprobe (metadata audio)",
        "check": "binary",
    },
}

# ─── Fonctions de vérification ──────────────────────────────────────────────────

def check_python_version() -> dict:
    """Vérifie la version Python."""
    version = sys.version_info
    result = {
        "name": "Python",
        "description": "Python 3.10+",
        "status": "ok" if version >= (3, 10) else "warning" if version >= (3, 8) else "error",
        "details": {
            "required": "3.10+",
            "current": f"{version.major}.{version.minor}.{version.micro}",
        },
    }
    if result["status"] == "error":
        result["message"] = "⚠️  Python 3.10+ requis. Mise à jour nécessaire."
    elif result["status"] == "warning":
        result["message"] = "⚠️  Python 3.8+ accepté mais 3.10+ recommandé."
    else:
        result["message"] = "✅  Version Python OK."
    return result


def check_python_package(name: str, description: str) -> dict:
    """Vérifie qu'un package Python est installé."""
    result = {
        "name": name,
        "description": description,
        "status": "error",
        "message": "",
    }

    spec = importlib.util.find_spec(name)
    if spec is not None:
        try:
            mod = importlib.import_module(name)
            version = getattr(mod, "__version__", "inconnue")
            result["status"] = "ok"
            result["version"] = str(version)
            result["message"] = f"✅  {name} {version} installé."
        except ImportError as e:
            result["status"] = "error"
            result["message"] = f"❌ {name} présent mais import impossible: {e}"
    else:
        result["message"] = f"❌ {name} non installé."

    return result


def check_binary(name: str, description: str) -> dict:
    """Vérifie qu'un binaire est disponible dans le PATH."""
    result = {
        "name": name,
        "description": description,
        "status": "error",
        "message": "",
    }

    try:
        proc = subprocess.run(
            [name, "-version"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if proc.returncode == 0:
            result["status"] = "ok"
            # Extraire la première ligne comme version
            first_line = proc.stdout.strip().split("\n")[0]
            result["version"] = first_line
            result["message"] = f"✅  {name} disponible ({first_line})"
        else:
            result["message"] = f"❌ {name} non disponible."
    except FileNotFoundError:
        result["message"] = f"❌ {name} non trouvé dans le PATH."
    except subprocess.TimeoutExpired:
        result["message"] = f"❌ {name} timeout lors de la vérification."

    return result


def check_config_file() -> dict:
    """Vérifie le fichier de configuration."""
    result = {
        "name": "config.yaml",
        "description": "Configuration AudioScore",
        "status": "error",
        "message": "",
    }

    if not CONFIG_FILE.exists():
        result["message"] = f"❌ config.yaml introuvable dans {PROJECT_ROOT}"
        return result

    try:
        import yaml
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Vérifier les sections critiques (noms réels dans config.yaml)
        required_sections = ["transcriber", "pipeline", "quantization", "export", "server", "device", "model_cache"]
        missing = [s for s in required_sections if s not in config]

        if missing:
            result["status"] = "warning"
            result["message"] = f"⚠️  config.yaml OK mais sections manquantes: {', '.join(missing)}"
        else:
            result["status"] = "ok"
            result["message"] = f"✅  config.yaml valide avec toutes les sections critiques."

    except Exception as e:
        result["message"] = f"❌ Erreur lecture config.yaml: {e}"

    return result


def check_directories() -> dict:
    """Vérifie les répertoires critiques."""
    dirs_to_check = {
        "backend": BACKEND_DIR,
        "frontend": FRONTEND_DIR,
        "uploads": PROJECT_ROOT / "uploads",
        "outputs": PROJECT_ROOT / "outputs",
    }

    result = {
        "name": "directories",
        "description": "Répertoires critiques",
        "status": "ok",
        "details": {},
        "message": "",
    }

    for name, path in dirs_to_check.items():
        if path.exists() and path.is_dir():
            result["details"][name] = f"✅  {path}"
        else:
            result["status"] = "warning" if name in ["uploads", "outputs"] else "error"
            result["details"][name] = f"{'⚠️' if result['status'] == 'warning' else '❌'} {path} (introuvable)"

    result["message"] = "Répertoires vérifiés (voir détails)."
    return result


def check_gpu() -> dict:
    """Vérifie la disponibilité GPU pour PyTorch."""
    result = {
        "name": "gpu",
        "description": "GPU pour accélération PyTorch",
        "status": "warning",
        "message": "",
    }

    try:
        import torch
        gpu_info = []
        if torch.cuda.is_available():
            gpu_info.append(f"CUDA: {torch.cuda.get_device_name(0)}")
        if hasattr(torch, 'xpu') and torch.xpu.is_available():
            gpu_info.append(f"XPU: {torch.xpu.get_device_name(0)}")
        if gpu_info:
            result["status"] = "ok"
            result["gpu_name"] = ", ".join(gpu_info)
            result["message"] = f"✅  GPU disponible: {result['gpu_name']}"
        else:
            result["message"] = "⚠️  GPU non disponible. Calcul CPU uniquement (plus lent)."
    except ImportError:
        result["status"] = "error"
        result["message"] = "❌ PyTorch non installé."
    except Exception as e:
        result["status"] = "warning"
        result["message"] = f"⚠️  Vérification GPU impossible: {e}"

    return result


def check_models_directory() -> dict:
    """Vérifie les modèles IA disponibles."""
    result = {
        "name": "models",
        "description": "Modèles IA disponibles",
        "status": "warning",
        "message": "",
        "models": [],
    }

    # Vérifier les répertoires de modèles courants
    model_dirs = [
        PROJECT_ROOT / "models",
        Path.home() / ".cache" / "torchaudio",
        Path.home() / ".demucs",
    ]

    for model_dir in model_dirs:
        if model_dir.exists():
            result["models"].append(str(model_dir))
            # Lister les fichiers
            try:
                files = list(model_dir.glob("*"))
                result["model_count"] = len(files)
            except:
                pass

    if result["models"]:
        result["status"] = "ok"
        result["message"] = f"✅  Modèles trouvés dans {len(result['models'])} répertoire(s)."
    else:
        result["message"] = "⚠️  Aucun répertoire de modèles trouvé (téléchargement automatique possible)."

    return result


# ─── Rapport principal ──────────────────────────────────────────────────────────

def run_diagnostic(fix_mode: bool = False) -> dict:
    """Exécute le diagnostic complet."""
    print("\n" + "=" * 70)
    print("  AudioScore v5 — Diagnostic Environnement")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Plateforme: {platform.system()} {platform.release()}")
    print(f"  Projet: {PROJECT_ROOT}")
    print("=" * 70 + "\n")

    results = []

    # 1. Python
    results.append(check_python_version())

    # 2. Packages Python
    for name, config in CRITICAL_COMPONENTS.items():
        if name == "python":
            continue  # Déjà fait
        check_type = config["check"]
        desc = config["description"]

        if check_type == "import":
            results.append(check_python_package(name, desc))
        elif check_type == "binary":
            results.append(check_binary(name, desc))

    # 3. Configuration
    results.append(check_config_file())

    # 4. Répertoires
    results.append(check_directories())

    # 5. GPU
    results.append(check_gpu())

    # 6. Modèles
    results.append(check_models_directory())

    # ─── Résumé ────────────────────────────────────────────────────────────────
    ok_count = sum(1 for r in results if r["status"] == "ok")
    warning_count = sum(1 for r in results if r["status"] == "warning")
    error_count = sum(1 for r in results if r["status"] == "error")

    print("\n" + "-" * 70)
    print("  RÉSULTATS DÉTAILLÉS")
    print("-" * 70)

    for r in results:
        print(f"\n  {r['message']}")
        if "details" in r:
            for k, v in r["details"].items():
                print(f"    - {k}: {v}")

    print("\n" + "=" * 70)
    print("  RÉSUMÉ")
    print("=" * 70)
    print(f"  ✅  OK      : {ok_count}")
    print(f"  ⚠️  Warning : {warning_count}")
    print(f"  ❌  Error   : {error_count}")
    print("=" * 70)

    # Verdict
    if error_count > 0:
        print(f"\n  ❌  DIAGNOSTIC ÉCHOUÉ — {error_count} erreur(s) critique(s)")
        print("      Corrigez les erreurs avant de lancer le pipeline.")
        return {"status": "error", "errors": error_count, "warnings": warning_count, "ok": ok_count}
    elif warning_count > 0:
        print(f"\n  ⚠️  DIAGNOSTIC AVEC AVERTISSEMENTS — {warning_count} avertissement(s)")
        print("      Le pipeline peut fonctionner mais certaines fonctionnalités seront limitées.")
        return {"status": "warning", "errors": 0, "warnings": warning_count, "ok": ok_count}
    else:
        print("\n  ✅  DIAGNOSTIC RÉUSSI — Environnement prêt!")
        return {"status": "ok", "errors": 0, "warnings": 0, "ok": ok_count}


# ─── Point d'entrée ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    fix_mode = "--fix" in sys.argv
    try:
        result = run_diagnostic(fix_mode=fix_mode)
        sys.exit(0 if result["status"] in ["ok", "warning"] else 1)
    except KeyboardInterrupt:
        print("\n\nDiagnostic interrompu.")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nErreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)