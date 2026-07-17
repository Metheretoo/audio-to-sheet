"""
Script de vérification des prérequis pour audio-to-sheet.
À lancer après les patches : python backend/verify_prerequisites.py
"""
import sys
import importlib

def check_package(name, min_version=None):
    """Vérifie si un package est installable et retourne sa version."""
    try:
        mod = importlib.import_module(name.replace('-', '_'))
        version = getattr(mod, '__version__', 'inconnue')
        status = "OK"
        if min_version:
            status = f"OK (>= {min_version})"
        return f"  ✅ {name}: {version}"
    except ImportError:
        return f"  ❌ {name}: NON INSTALLÉ"

def main():
    print("=" * 60)
    print("VERIFICATION DES PRE-requis - audio-to-sheet")
    print("=" * 60)
    
    results = []
    
    # Python version
    print(f"\nPython: {sys.version}")
    v = sys.version_info
    if v.major < 3 or v.minor < 9:
        print("  ❌ Python >= 3.9 requis")
    else:
        print("  ✅ Python >= 3.9 OK")
    
    # numpy (CRITIQUE pour madmom)
    print("\n--- Dépendances critiques ---")
    try:
        import numpy
        ver = numpy.__version__
        v = tuple(int(x) for x in ver.split('.'))
        # numpy < 1.24 nécessaire pour madmom (np.float/np.int supprimés en 1.24)
        if v[0] < 1 or (v[0] == 1 and v[1] < 23) or v[0] >= 2 or (v[0] == 1 and v[1] >= 24):
            if v[0] >= 2 or (v[0] == 1 and v[1] >= 24):
                print(f"  ❌ numpy {ver}: INCOMPATIBLE avec madmom (numpy >= 1.24 supprime np.float/np.int)")
                print(f"     → pip install 'numpy>=1.23,<1.27'")
                print(f"     → pip install --force-reinstall madmom")
            else:
                print(f"  ⚠️  numpy {ver}: TROP VIEUX pour madmom (requiert >= 1.23)")
            print(f"  ⚠️  numpy {ver}: INCOMPATIBLE avec madmom (np.float/np.int supprimés)")
        else:
            print(f"  ✅ numpy {ver}: COMPATIBLE avec madmom")
    except ImportError:
        print("  ❌ numpy: NON INSTALLÉ")
    
    # madmom
    try:
        import madmom
        ver = madmom.__version__
        print(f"  ✅ madmom {ver}: INSTALLÉ")
    except ImportError:
        print("  ❌ madmom: NON INSTALLÉ")
        print("     → pip install madmom")
        print("     → pip install cython==0.29.36 (prérequis)")
    except AttributeError as e:
        print(f"  ⚠️  madmom: ERREUR d'import ({e})")
        print("     → Vérifie que numpy < 1.27 est installé")
        print("     → pip install 'numpy>=1.23,<1.27'")
        print("     → pip install --force-reinstall madmom")
    
    # librosa
    print("\n--- Audio / ML ---")
    results.append(check_package('librosa'))
    results.append(check_package('soundfile'))
    results.append(check_package('mido'))
    results.append(check_package('pretty_midi'))
    
    # Deep learning
    print("\n--- Deep Learning ---")
    try:
        import torch
        print(f"  ✅ PyTorch: {torch.__version__}")
        if torch.xpu.is_available():
            print("  ✅ Intel XPU (ARC GPU) détecté")
        elif torch.cuda.is_available():
            print("  ✅ CUDA (NVIDIA GPU) détecté")
        else:
            print("  ⚠️  Aucun GPU détecté - exécution sur CPU (lent)")
    except ImportError:
        print("  ❌ PyTorch: NON INSTALLÉ")
    
    # Piano transcription
    print("\n--- Transcription piano ---")
    results.append(check_package('piano_transcription_inference'))
    results.append(check_package('basic_pitch'))
    results.append(check_package('transkun'))
    
    # Web framework
    print("\n--- Web framework ---")
    results.append(check_package('flask'))
    results.append(check_package('flask_cors'))
    results.append(check_package('waitress'))
    
    # Demucs
    print("\n--- Audio separation ---")
    results.append(check_package('demucs'))
    
    # Résumé
    print("\n" + "=" * 60)
    print("RESUME:")
    print("=" * 60)
    for r in results:
        print(r)
    
    # Vérification numpy madmom
    print("\n--- Vérification numpy/madmom ---")
    try:
        import numpy as np
        if not hasattr(np, 'float'):
            print("  ❌ numpy n'a pas np.float - madmom NE FONCTIONNERA PAS")
            print("     → pip install 'numpy>=1.23,<1.27'")
        else:
            print("  ✅ numpy a np.float - madmom devrait fonctionner")
    except:
        print("  ⚠️  Impossible de vérifier numpy")

if __name__ == '__main__':
    main()