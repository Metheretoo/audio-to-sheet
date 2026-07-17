"""
Script d'installation automatique pour audio-to-sheet.
À lancer après un clone ou une réinstallation :
    python backend/setup.py

Ordre critique :
1. Installer numpy < 1.27 AVANT madmom (madmom force numpy 2.x par ses meta-données)
2. Installer madmom
3. Patcher madmom pour compatibilité Python 3.10+ / numpy 1.26
"""
import subprocess
import sys
import os
import re

venv_python = os.path.join(os.path.dirname(__file__), '..', 'venv', 'Scripts', 'python.exe')
if not os.path.exists(venv_python):
    venv_python = sys.executable

pip = venv_python + " -m pip"

def run(cmd, desc):
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"  {cmd}")
    print('='*60)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERREUR: {result.stderr[-500:]}")
        return False
    # Afficher uniquement les lignes importantes
    for line in result.stdout.splitlines():
        if 'Successfully' in line or 'already' in line or 'ERROR' in line or 'install' in line.lower():
            print(f"  {line.strip()}")
    return True

def patch_madmom():
    """Patch madmom pour compatibilité Python 3.10+ et numpy >= 1.24."""
    print(f"\n{'='*60}")
    print("  Patch de madmom")
    print('='*60)
    
    import importlib
    import madmom
    madmom_path = os.path.dirname(importlib.import_module('madmom').__file__)
    
    count = 0
    
    # Patch 1: MutableSequence
    for root, dirs, files in os.walk(madmom_path):
        for f in files:
            if f == 'processors.py':
                fp = os.path.join(root, f)
                c = open(fp, encoding='utf-8').read()
                if 'from collections import MutableSequence' in c:
                    c = c.replace('from collections import MutableSequence', 'from collections.abc import MutableSequence')
                    open(fp, 'w', encoding='utf-8').write(c)
                    print(f"  ✅ processors.py: MutableSequence patché")
                    count += 1
    
    # Patch 2: np.float, np.int, np.bool, np.complex, np.object (PAS np.float32 etc.)
    pat = re.compile(r'\bnp\.(float|int|bool|complex|object)\b(?!\d)')
    for root, dirs, files in os.walk(madmom_path):
        for f in files:
            if f.endswith('.py'):
                fp = os.path.join(root, f)
                c = open(fp, encoding='utf-8').read()
                matches = pat.findall(c)
                if matches:
                    c = pat.sub(lambda m: {'float':'float','int':'int','bool':'bool','complex':'complex','object':'object'}[m.group(1)], c)
                    open(fp, 'w', encoding='utf-8').write(c)
                    rel = os.path.relpath(fp, madmom_path)
                    print(f"  ✅ {rel}: {len(matches)} remplacement(s)")
                    count += len(matches)
    
    print(f"\n  ✅ madmom patché: {count} modification(s)")
    return count > 0

def main():
    print("=" * 60)
    print("  INSTALLATION AUDIO-TO-SHEET")
    print("=" * 60)
    
    # Étape 1: numpy AVANT madmom
    run(f"{pip} install \"numpy>=1.23,<1.27\"", "  [1/5] Installation numpy compatible madmom")
    
    # Étape 2: cython (prérequis madmom)
    run(f"{pip} install cython==0.29.36", "  [2/5] Installation cython (prérequis madmom)")
    
    # Étape 3: madmom
    run(f"{pip} install madmom>=0.16", "  [3/5] Installation madmom")
    
    # Étape 4: Patcher madmom
    patch_madmom()
    
    # Étape 5: Dépendances principales
    run(f"{pip} install -r {os.path.join(os.path.dirname(__file__), 'requirements.txt')}",
        "  [4/5] Installation des dépendances principales")
    
    # Étape 6: transkun
    run(f"{pip} install transkun", "  [5/6] Installation transkun")
    
    print(f"\n{'='*60}")
    print("  INSTALLATION TERMINEE")
    print('='*60)
    print("""
  Pour vérifier:
    python backend\\verify_prerequisites.py

  Pour lancer:
    python backend\\app.py
""")

if __name__ == '__main__':
    main()