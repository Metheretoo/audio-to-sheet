"""
Patch madmom pour compatibilité Python 3.10+ et numpy >= 1.24.
À lancer : python backend/patch_madmom.py
"""
import os
import re
import sys

# Chemin vers le site-packages de madmom
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
venv_path = os.path.join(project_dir, 'venv', 'Lib', 'site-packages')
madmom_path = os.path.join(venv_path, 'madmom')

if not os.path.isdir(madmom_path):
    # Essayer le chemin Linux
    madmom_path = os.path.join(venv_path.replace('Lib', 'lib'), 'madmom')

if not os.path.isdir(madmom_path):
    print(f"❌ madmom introuvable. Chemins essayés:")
    print(f"  Windows: {madmom_path}")
    alt = os.path.join(venv_path.replace('Lib', 'lib'), 'madmom')
    print(f"  Linux: {alt}")
    sys.exit(1)

print(f"Patch de: {madmom_path}")

# Regex pour trouver np.float, np.int, np.bool, np.complex, np.object
np_legacy_pat = re.compile(r'\bnp\.(float|int|bool|complex|object)\b')

count = 0
for root, dirs, files in os.walk(madmom_path):
    for f in files:
        if f.endswith('.py'):
            fp = os.path.join(root, f)
            try:
                c = open(fp, encoding='utf-8').read()
                matches = np_legacy_pat.findall(c)
                if matches:
                    c = np_legacy_pat.sub(lambda m: f'np.{m.group(1)}64' if m.group(1) in ('float', 'int') else m.group(0), c)
                    # Pour bool/complex/object, remplacer directement
                    c = c.replace('np.bool', 'bool')
                    c = c.replace('np.complex', 'complex')
                    c = c.replace('np.object', 'object')
                    open(fp, 'w', encoding='utf-8').write(c)
                    rel = os.path.relpath(fp, madmom_path)
                    print(f"  ✅ {rel}: {len(matches)} remplacement(s)")
                    count += len(matches)
            except Exception as e:
                print(f"  ⚠️  Erreur {fp}: {e}")

# Patch MutableSequence import
print("\n--- Patch MutableSequence ---")
for root, dirs, files in os.walk(madmom_path):
    for f in files:
        if f == 'processors.py':
            fp = os.path.join(root, f)
            c = open(fp, encoding='utf-8').read()
            if 'from collections import MutableSequence' in c:
                c = c.replace('from collections import MutableSequence', 'from collections.abc import MutableSequence')
                open(fp, 'w', encoding='utf-8').write(c)
                print(f"  ✅ {os.path.relpath(fp, madmom_path)}: MutableSequence patché")

print(f"\n✅ Total: {count} remplacement(s) numpy legacy effectué(s)")