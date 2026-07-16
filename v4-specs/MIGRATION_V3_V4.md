# Migration V3 → V4 — Guide de migration

## Résumé des changements majeurs

| Domaine | V3 | V4 | Impact |
|---------|-----|-----|--------|
| **Architecture** | Monolithique `app.py` | Modules découplés + interfaces | 🔴 Breaking |
| **Contrats** | Implicites (docstrings) | Formalisés (API_CONTRACTS.md) | 🟢 Non-breaking |
| **Tests** | Inexistants | Stratégie complète (TEST_STRATEGY.md) | 🟢 Ajout |
| **Config** | `config.py` + args CLI | `config.yaml` centralisé | 🟡 Migration requise |
| **Exports** | MIDI basique | MIDI + MusicXML 4.0 + LilyPond PDF | 🟢 Ajout |
| **Tempo** | BPM fixe | TempoMap dynamique (madmom/librosa/fallback) | 🟢 Amélioration |
| **Voix** | Split simple registre | Multi-critères (registre, contour, harmonie, continuité) | 🟢 Amélioration |
| **Quantification** | Grille fixe | Grille configurable + fusion + staccato/legato + tuplets | 🟢 Amélioration |
| **Frontend** | Vanilla JS | Modules ES6 + Editor/Renderer/Player | 🟡 Refactor |

---

## 1. Changements Breaking (API interne)

### 1.1 Signatures de fonctions modifiées

```python
# V3
def transcribe_audio(audio_path):  # → List[Tuple]
def quantize_notes(note_events, bpm):  # → List[Dict]
def split_voices(quantized_notes):  # → Dict{treble, bass}
def build_score(voices, bpm, key):  # → Dict

# V4
def transcribe_audio(audio_path: str, config: Dict = None) -> List[NoteEvent]:
def quantize_notes(note_events: List[NoteEvent], tempo_map: TempoMap, config: Dict = None) -> List[QuantizedNote]:
def split_voices(quantized_notes: List[QuantizedNote], config: Dict = None) -> VoiceSplit:
def build_score(voices: VoiceSplit, tempo_map: TempoMap, key_sig: str = 'C', options: Dict = None) -> Dict:
```

**Action requise** : Mettre à jour tout code appelant ces fonctions directement.

### 1.2 Formats de données modifiés

| Structure | V3 | V4 |
|-----------|-----|-----|
| Note quantifiée | `Dict{onset, pitch, duration, hand}` | `QuantizedNote` dataclass (beat_position, beat_duration, dur_str, dots, tuplet, hand) |
| Séparation voix | `Dict{treble: [], bass: []}` | `VoiceSplit(treble: List[QuantizedNote], bass: List[QuantizedNote])` |
| Tempo | `float bpm` | `TempoMap(beat_times, downbeat_times, estimated_meter, global_bpm, method)` |
| ScoreData | `Dict` basique | `Dict` complet (measures[], dynamics[], metadata) |

### 1.3 Modules renommés/supprimés

| V3 | V4 | Note |
|----|-----|------|
| `app.py` (monolithe) | `backend/app.py` (API only) | Logique déplacée dans modules |
| `transcribe.py` | `backend/transcriber.py` | + interface `BaseTranscriber` |
| `quantize.py` | `backend/quantizer.py` | + `beats_to_duration()`, `duration_beats()` |
| `voice_split.py` | `backend/voice_engine.py` | Algorithme Viterbi-like |
| `tempo.py` | `backend/tempo_map.py` | + `TempoMap` class + méthodes conversion |
| `score.py` | `backend/score_builder.py` | + `build_score()` + VexFlow JSON |
| `export_midi.py` | `backend/midi_exporter.py` | + LilyPond PDF export |
| `export_musicxml.py` | `backend/musicxml_exporter.py` | Nouveau module |
| `config.py` | `config.yaml` + `backend/config.py` | YAML + validation Pydantic |

---

## 2. Migration pas à pas

### Étape 1 : Configuration

**V3** (`config.py`) :
```python
SAMPLE_RATE = 22050
ONSET_THRESHOLD = 0.3
QUANTIZATION_GRID = 16
SPLIT_POINT = 60
```

**V4** (`config.yaml`) :
```yaml
audio:
  sample_rate: 22050
  onset_threshold: 0.3
quantization:
  grid_resolution: 32
voice_split:
  split_point_midi: 60
```

**Code migration** :
```python
# V3
from config import SAMPLE_RATE, ONSET_THRESHOLD

# V4
from backend.config import load_config
config = load_config()
sr = config['audio']['sample_rate']
threshold = config['audio']['onset_threshold']
```

### Étape 2 : Transcription

**V3** :
```python
from transcribe import transcribe_audio
events = transcribe_audio("audio.wav")
# events = [(onset, pitch, dur, vel), ...]
```

**V4** :
```python
from backend.transcriber import transcribe_audio
events = transcribe_audio("audio.wav")
# Même format NoteEvent (tuple 4 éléments) — COMPATIBLE
```

✅ **Pas de breaking change** sur le format `NoteEvent`.

### Étape 3 : Tempo Map (NOUVEAU en V4)

**V3** : BPM fixe estimé une fois
```python
bpm = estimate_tempo(audio_path)  # float
```

**V4** : `TempoMap` objet complet
```python
from backend.tempo_map import build_tempo_map
tm = build_tempo_map("audio.wav", events)
bpm = tm.global_bpm              # BPM global (médiane)
beat_times = tm.beat_times       # np.ndarray timestamps beats
downbeats = tm.downbeat_times    # temps forts
meter = tm.estimated_meter       # (4, 4)
# Conversion temps ↔ beat
beat = tm.seconds_to_beat(2.5)
sec = tm.beat_to_seconds(4.0)
local_bpm = tm.local_bpm_at(10.0)
```

### Étape 4 : Quantification

**V3** :
```python
from quantize import quantize_notes
qnotes = quantize_notes(events, bpm=120)
# qnotes = [{'pitch': 60, 'onset': 0.5, 'duration': 0.5, 'hand': 'treble'}, ...]
```

**V4** :
```python
from backend.quantizer import quantize_notes, QuantizedNote
qnotes = quantize_notes(events, tm)  # tm = TempoMap
# qnotes = [QuantizedNote(pitch_midi=60, amplitude=0.8, beat_position=0.0, beat_duration=1.0, dur_str='q', dots=0, hand='treble', tuplet=None), ...]
```

**Différences clés** :
- Position/durée en **beats** (pas secondes)
- `dur_str` + `dots` au lieu de durée float
- `hand` assigné par `voice_engine` (pas dans quantizer)
- Support `tuplet` (ex: `(3, 3 notes sur 2 temps)

### Étape 5 : Séparation des voix

**V3** :
```python
from voice_split import split_voices
voices = split_voices(qnotes)
# voices = {'treble': [...], 'bass': [...]}
```

**V4** :
```python
from backend.voice_engine import split_voices, VoiceSplit
vs = split_voices(qnotes)
# vs = VoiceSplit(treble=[QuantizedNote...], bass=[QuantizedNote...])
# vs.treble, vs.bass sont des listes typées
```

### Étape 6 : Construction de la partition

**V3** :
```python
from score import build_score
score = build_score(voices, bpm=120, key='C')
# score = {'measures': [...], 'tempo': 120, ...}
```

**V4** :
```python
from backend.score_builder import build_score
score = build_score(vs, tm, key_sig='C', options={'detect_dynamics': True})
# score = ScoreData complet avec measures[], dynamics[], metadata
```

### Étape 7 : Exports

**V3** :
```python
from export_midi import export_midi
export_midi(score, "output.mid")
```

**V4** :
```python
from backend.midi_exporter import export_midi, export_lilypond_pdf
from backend.musicxml_exporter import export_musicxml

export_midi(score, qnotes, "output.mid")           # MIDI Type 1
export_musicxml(score, "output.musicxml")          # MusicXML 4.0
export_lilypond_pdf(score, "output.pdf")           # PDF via LilyPond
```

---

## 3. Script de migration automatique

```python
# scripts/migrate_v3_to_v4.py
"""
Script d'aide à la migration V3 → V4.
Ne modifie PAS le code, génère un rapport de changements nécessaires.
"""
import ast
import sys
from pathlib import Path

V3_IMPORTS = {
    'transcribe': 'backend.transcriber',
    'quantize': 'backend.quantizer',
    'voice_split': 'backend.voice_engine',
    'tempo': 'backend.tempo_map',
    'score': 'backend.score_builder',
    'export_midi': 'backend.midi_exporter',
    'config': 'backend.config',
}

V3_FUNCTIONS = {
    'transcribe_audio': ('backend.transcriber', 'transcribe_audio'),
    'quantize_notes': ('backend.quantizer', 'quantize_notes'),
    'split_voices': ('backend.voice_engine', 'split_voices'),
    'estimate_tempo': ('backend.tempo_map', 'build_tempo_map'),
    'build_score': ('backend.score_builder', 'build_score'),
    'export_midi': ('backend.midi_exporter', 'export_midi'),
}

def scan_file(filepath: Path):
    """Analyse un fichier Python pour détecter les patterns V3."""
    issues = []
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in V3_IMPORTS:
                    issues.append({
                        'line': node.lineno,
                        'type': 'import',
                        'old': alias.name,
                        'new': V3_IMPORTS[alias.name],
                        'message': f"Import '{alias.name}' → '{V3_IMPORTS[alias.name]}'"
                    })
        elif isinstance(node, ast.ImportFrom):
            if node.module in V3_IMPORTS:
                issues.append({
                    'line': node.lineno,
                    'type': 'import_from',
                    'old': node.module,
                    'new': V3_IMPORTS[node.module],
                    'message': f"from '{node.module}' → from '{V3_IMPORTS[node.module]}'"
                })

        # Appels de fonctions
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in V3_FUNCTIONS:
                    old_mod, new_func = V3_FUNCTIONS[node.func.id]
                    issues.append({
                        'line': node.lineno,
                        'type': 'call',
                        'old': f"{old_mod}.{node.func.id}",
                        'new': f"{V3_FUNCTIONS[node.func.id][0]}.{new_func}",
                        'message': f"Appel {node.func.id}() signature changée (voir guide)"
                    })
    return issues

def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
    all_issues = []
    for py_file in root.rglob('*.py'):
        if 'venv' in py_file.parts or '__pycache__' in py_file.parts:
            continue
        issues = scan_file(py_file)
        if issues:
            all_issues.append((py_file, issues))

    # Rapport
    print(f"\n{'='*60}")
    print(f"RAPPORT MIGRATION V3 → V4")
    print(f"{'='*60}")
    print(f"Fichiers analysés: {len(list(root.rglob('*.py')))}")
    print(f"Fichiers avec issues: {len(all_issues)}")
    print(f"Total issues: {sum(len(i) for _, i in all_issues)}")
    print(f"{'='*60}\n")

    for filepath, issues in all_issues:
        print(f"📄 {filepath}")
        for issue in issues:
            print(f"  Line {issue['line']}: {issue['message']}")
        print()

if __name__ == '__main__':
    main()
```

**Utilisation** :
```bash
cd audio-to-sheet
python scripts/migrate_v3_to_v4.py .
```

---

## 4. Checklist de validation post-migration

### Tests unitaires
- [ ] `pytest tests/unit/test_transcriber.py` — NoteEvent format inchangé
- [ ] `pytest tests/unit/test_tempo_map.py` — TempoMap contrats respectés
- [ ] `pytest tests/unit/test_quantizer.py` — QuantizedNote grille alignée
- [ ] `pytest tests/unit/test_voice_engine.py` — VoiceSplit exhaustif
- [ ] `pytest tests/unit/test_score_builder.py` — ScoreData mesures remplies
- [ ] `pytest tests/unit/test_midi_exporter.py` — MIDI Type 1 valide
- [ ] `pytest tests/unit/test_musicxml_exporter.py` — MusicXML 4.0 valide

### Tests d'intégration
- [ ] `pytest tests/integration/test_pipeline.py` — Pipeline complet 3+ fixtures
- [ ] `pytest tests/integration/test_exporters.py` — Tous formats exportés
- [ ] `pytest tests/integration/test_api.py` — API HTTP fonctionnelle

### Tests E2E
- [ ] `pytest tests/e2e/test_webapp.py` — Upload → Affichage → Play → Export

### Régression visuelle
- [ ] Comparer PDF LilyPond V3 vs V4 sur même audio
- [ ] Comparer MusicXML V3 vs V4 (si export V3 existait)
- [ ] Vérifier rendu VexFlow frontend identique

### Performance
- [ ] Temps transcription < V3 + 20%
- [ ] Mémoire < 500MB pour 5min audio
- [ ] Pas de fuite mémoire sur 10 jobs consécutifs

---

## 5. Rollback plan

Si problèmes critiques en production :

```bash
# 1. Tag current V4
git tag v4.0.0-rollback-candidate

# 2. Revenir à V3
git checkout v3-stable  # ou tag V3 connu bon

# 3. Redéployer
./run_prod.bat  # ou docker-compose up -d

# 4. Investiguer sur branche à part
git checkout -b hotfix/v4-issue main
```

**Branches de référence** :
- `main` → V4 (développement)
- `v3-stable` → V3 dernière version stable
- `v3-maintenance` → corrections V3 si nécessaire

---

## 6. FAQ Migration

**Q: Mon code appelle `quantize_notes(events, 120)` avec un BPM fixe. Comment migrer ?**
R: Créez un `TempoMap` minimal :
```python
from backend.tempo_map import TempoMap
import numpy as np
tm = TempoMap(
    beat_times=np.arange(0, 100, 60/120),  # beats réguliers 120 BPM
    downbeat_times=np.arange(0, 100, 60/120 * 4),
    estimated_meter=(4, 4),
    global_bpm=120.0,
    method="manual"
)
qnotes = quantize_notes(events, tm)
```

**Q: Je n'ai pas madmom/librosa installé. Le fallback marche-t-il ?**
R: Oui, `tempo_map.build_tempo_map()` essaie madmom → librosa → fallback IOI. Le fallback utilise les intervalles inter-onset des `note_events` fournis. Assurez-vous de passer `note_events` en second argument.

**Q: Les exports MIDI V4 sont-ils compatibles avec les logiciels V3 ?**
R: Oui, MIDI Type 1 standard GM. Seule différence : V4 inclut les changements de tempo (si `TempoMap` fourni) et velocity = amplitude × 127.

**Q: Comment désactiver la détection de dynamique ?**
R: `build_score(vs, tm, options={'detect_dynamics': False})`

**Q: Le frontend V3 marche-t-il avec l'API V4 ?**
R: Non, l'API a changé (`/api/transcribe` retourne `job_id`, polling `/api/job/<id>`). Le frontend V4 (`frontend/js/app.js`) gère ce flux asynchrone.

---

## 7. Versions et compatibilité

| Version | Date | Compatibilité arrière |
|---------|------|----------------------|
| V1 | 2024-Q1 | — |
| V2 | 2024-Q2 | ❌ Breaking (nouveaux formats) |
| V3 | 2024-Q3 | ❌ Breaking (architecture) |
| **V4** | **2024-Q4** | **❌ Breaking (API interne)** |
| V4.1 | 2025-Q1 | ✅ Patch (bugfixes seulement) |
| V4.2 | 2025-Q2 | ✅ Minor (nouvelles features, pas de breaking) |
| V5.0 | 2025-Q3 | ❌ Major (nouvelle architecture plugin) |

**Règle** : V4.x = compatible V4.0. V5.0 = breaking.

---

## 8. Support

- **Documentation** : `v4-specs/` (ce dossier)
- **Issues** : GitHub Issues avec label `migration-v4`
- **Contact** : Équipe audio-to-sheet