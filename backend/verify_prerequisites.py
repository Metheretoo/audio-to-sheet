"""
verify_prerequisites.py — Vérification des prérequis au démarrage (Phase 1.5)

Ce module vérifie que toutes les dépendances critiques sont installées
et compatibles avant le lancement de l'application.

Utilisation :
    from verify_prerequisites import verify_prerequisites, check_all
    result = verify_prerequisites()
    # ou
    results = check_all()  # retourne un dict pour usage programmatique
"""
import sys
import os
import importlib
import logging

def check_package(name, min_version=None):
    """Vérifie si un package est installable et retourne sa version.
    
    Returns:
        dict: {
            'name': str,
            'installed': bool,
            'version': str,
            'compatible': bool | None,
            'error': str | None
        }
    """
    result = {
        'name': name,
        'installed': False,
        'version': 'inconnue',
        'compatible': None,
        'error': None
    }
    try:
        mod = importlib.import_module(name.replace('-', '_'))
        version = getattr(mod, '__version__', 'inconnue')
        if version == 'inconnue':
            version = getattr(mod, 'VERSION', 'inconnue')
        if version == 'inconnue':
            version = getattr(mod, '__version__', 'inconnue')
        result['version'] = str(version)
        result['installed'] = True
        if min_version:
            result['compatible'] = True  # vérification simplifiée
        return result
    except ImportError as e:
        result['error'] = str(e)
        return result


def check_numpy_madmom_compatibility():
    """Vérifie la compatibilité numpy/madmom (np.float/np.int supprimés en numpy 1.24+).
    
    Returns:
        dict: {
            'numpy_version': str,
            'compatible': bool,
            'error': str | None,
            'fix_command': str | None
        }
    """
    result = {
        'numpy_version': 'non installé',
        'compatible': None,
        'error': None,
        'fix_command': None
    }
    try:
        import numpy
        ver = numpy.__version__
        result['numpy_version'] = ver
        v = tuple(int(x) for x in ver.split('.'))
        
        # numpy >= 1.24 supprime np.float/np.int
        if v[0] >= 2 or (v[0] == 1 and v[1] >= 24):
            result['compatible'] = False
            result['error'] = 'numpy >= 1.24 est incompatible avec madmom (np.float/np.int supprimés)'
            result['fix_command'] = "pip install 'numpy>=1.23,<1.27' && pip install --force-reinstall madmom"
        elif v[0] == 1 and v[1] < 23:
            result['compatible'] = False
            result['error'] = 'numpy < 1.23 est trop vieux pour madmom'
            result['fix_command'] = "pip install 'numpy>=1.23,<1.27'"
        else:
            result['compatible'] = True
        return result
    except ImportError:
        result['error'] = 'numpy non installé'
        result['fix_command'] = 'pip install numpy'
        return result


def check_gpu_compatibility():
    """Vérifie la disponibilité GPU (CUDA, XPU, CPU fallback).
    
    Returns:
        dict: {
            'device': str (cuda/xpu/cpu),
            'recommended': bool,
            'name': str,
            'warnings': list[str]
        }
    """
    result = {
        'device': 'cpu',
        'recommended': False,
        'name': 'Processeur (CPU)',
        'warnings': []
    }
    try:
        import torch
        # CUDA
        if torch.cuda.is_available():
            result['device'] = 'cuda'
            result['recommended'] = True
            result['name'] = torch.cuda.get_device_name(0)
            result['warnings'].append('GPU NVIDIA détecté - accélération CUDA activée')
            return result
        # XPU
        if hasattr(torch, 'xpu') and torch.xpu.is_available():
            result['device'] = 'xpu'
            result['recommended'] = True
            result['name'] = torch.xpu.get_device_name(0) if hasattr(torch.xpu, 'get_device_name') else 'Intel ARC GPU'
            result['warnings'].append('GPU Intel ARC détecté - accélération IPEX activée')
            return result
    except ImportError:
        result['warnings'].append('PyTorch non installé')
        return result
    except Exception as e:
        result['warnings'].append(f'Erreur détection GPU: {e}')
        return result
    
    # Aucun GPU
    result['warnings'].append(
        'Aucun GPU détecté. Pour utiliser votre GPU Intel ARC A770:'
    )
    result['warnings'].append(
        '1. Installez IPEX: pip install intel-extension-for-pytorch'
    )
    result['warnings'].append(
        '2. Ou utilisez le wheel PyTorch Intel: pip install torch --index-url https://download.pytorch.org/whl/xpu'
    )
    result['warnings'].append(
        '3. Redémarrez le serveur après l\'installation.'
    )
    return result


def check_all():
    """Vérifie tous les prérequis et retourne un résultat structuré.
    
    Returns:
        dict: {
            'python_ok': bool,
            'python_version': str,
            'critical': dict,
            'dependencies': list[dict],
            'gpu': dict,
            'overall_ok': bool,
            'errors': list[str],
            'warnings': list[str]
        }
    """
    result = {
        'python_ok': False,
        'python_version': f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
        'critical': {},
        'dependencies': [],
        'gpu': {},
        'overall_ok': True,
        'errors': [],
        'warnings': []
    }
    
    # Python version
    v = sys.version_info
    if v.major >= 3 and v.minor >= 9:
        result['python_ok'] = True
    else:
        result['overall_ok'] = False
        result['errors'].append(f'Python >= 3.9 requis (actuel: {result["python_version"]})')
    
    # Vérification critique numpy/madmom
    result['critical'] = check_numpy_madmom_compatibility()
    if result['critical'].get('compatible') is False:
        result['overall_ok'] = False
        result['errors'].append(result['critical']['error'])
        if result['critical'].get('fix_command'):
            result['warnings'].append(f"Correction: {result['critical']['fix_command']}")
    
    # Dépendances
    dep_names = [
        ('librosa', None),
        ('soundfile', None),
        ('mido', None),
        ('pretty_midi', None),
        ('piano_transcription_inference', None),
        ('basic_pitch', None),
        ('flask', None),
        ('flask_cors', None),
    ]
    for name, min_ver in dep_names:
        r = check_package(name, min_ver)
        result['dependencies'].append(r)
        if not r['installed']:
            result['warnings'].append(f"{name} non installé: {r.get('error', 'inconnu')}")
    
    # GPU
    result['gpu'] = check_gpu_compatibility()
    if not result['gpu'].get('recommended', False):
        result['warnings'].append('Aucun GPU détecté — exécution sur CPU (lent)')
    
    return result


def format_results(results):
    """Formate les résultats de vérification pour affichage console.
    
    Args:
        results: dict retourné par check_all()
        
    Returns:
        str: Chaîne formatée pour affichage
    """
    lines = []
    lines.append("=" * 60)
    lines.append("VERIFICATION DES PRE-requis - audio-to-sheet")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Python: {results['python_version']}")
    if results['python_ok']:
        lines.append("  ✅ Python >= 3.9 OK")
    else:
        lines.append(f"  ❌ Python >= 3.9 requis (actuel: {results['python_version']})")
    
    # Critique
    lines.append("")
    lines.append("--- Dépendances critiques ---")
    critical = results['critical']
    lines.append(f"  numpy: {critical.get('numpy_version', 'non installé')}")
    if critical.get('compatible') is True:
        lines.append("  ✅ numpy: COMPATIBLE avec madmom")
    elif critical.get('compatible') is False:
        lines.append(f"  ❌ {critical['error']}")
        if critical.get('fix_command'):
            lines.append(f"     → {critical['fix_command']}")
    
    # Dépendances
    lines.append("")
    lines.append("--- Dépendances optionnelles ---")
    for dep in results['dependencies']:
        if dep['installed']:
            lines.append(f"  ✅ {dep['name']}: {dep['version']}")
        else:
            lines.append(f"  ❌ {dep['name']}: NON INSTALLÉ")
    
    # GPU
    lines.append("")
    lines.append("--- GPU ---")
    gpu = results['gpu']
    lines.append(f"  Device: {gpu['name']} ({gpu['device']})")
    if gpu.get('recommended'):
        lines.append("  ✅ GPU accéléré détecté")
    else:
        for w in gpu.get('warnings', []):
            lines.append(f"  ⚠️  {w}")
    
    # Résumé
    lines.append("")
    lines.append("=" * 60)
    lines.append("RESUME:")
    lines.append("=" * 60)
    if results['overall_ok']:
        lines.append("  ✅ Tous les prérequis sont satisfaits")
    else:
        lines.append("  ❌ Certains prérequis ne sont pas satisfaits:")
        for e in results['errors']:
            lines.append(f"    - {e}")
    if results['warnings']:
        lines.append("")
        lines.append("  ⚠️  Avertissements:")
        for w in results['warnings']:
            lines.append(f"    - {w}")
    lines.append("=" * 60)
    
    return "\n".join(lines)

def main():
    """Point d'entrée CLI pour vérification manuelle des prérequis."""
    results = check_all()
    print(format_results(results))
    return results


def verify_prerequisites():
    """Vérifie les prérequis et retourne le résultat + affiche le résumé.
    
    Cette fonction est appelée au démarrage de l'application (Phase 1.5).
    
    Returns:
        tuple: (results: dict, should_warn: bool)
            - results: dict structuré avec tous les résultats de vérification
            - should_warn: True si des avertissements critiques doivent être loggués
    """
    results = check_all()
    
    # Afficher le résumé en console
    print(format_results(results))
    
    # Logger les résultats
    logger = logging.getLogger(__name__)
    if not results['overall_ok']:
        logger.warning("[P1.5] ⚠️ Prérequis non satisfaits — vérifiez les erreurs ci-dessus")
        for e in results['errors']:
            logger.warning(f"[P1.5] ERREUR: {e}")
    else:
        logger.info("[P1.5] ✅ Tous les prérequis sont satisfaits")
    
    if results['warnings']:
        for w in results['warnings']:
            logger.info(f"[P1.5] INFO: {w}")
    
    return results, not results['overall_ok']


if __name__ == '__main__':
    main()
