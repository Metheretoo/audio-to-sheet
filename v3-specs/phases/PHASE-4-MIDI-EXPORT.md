# Phase 4 — MIDI Exporter

> **Statut** : À implémenter
> **Dépendances** : Phase 1 ✅, Phase 2 ✅, Phase 3 ✅
> **Gain attendu** : Export MIDI standard compatible avec tous les logiciels de partition

---

## Objectif

Convertir les notes quantisées (sortie de Phase 3) en un fichier MIDI standard (.mid) lisible par tout logiciel de partition (MuseScore, Sibelius, MuseScore, etc.).

---

## Contexte

Les phases 1-3 produisent une liste de notes avec:
- `note_number` (MIDI note number, 0-127)
- `start_time` (en secondes)
- `end_time` (en secondes)
- `velocity` (0-127)
- `voice` ('RH', 'LH', 'MELODY', 'BASS', 'HARMONY')
- `tie` (optionnel, pour les liaisons de continuation)

La Phase 4 doit convertir ces données en fichier MIDI Type 0 ou Type 1.

---

## Spécifications Techniques

### 1. Format MIDI

- **Type 0** : Toutes les tracks dans un seul track (plus simple)
- **Type 1** : Tracks séparés par voix (plus professionnel)
- **Choix** : Type 0 pour simplicité, avec meta-events pour les signatures

### 2. Éléments MIDI à générer

| Élément | Description |
|---------|-------------|
| **Note On/Off** | Événements de note avec velocity |
| **Tempo Map** | Meta-event TEMPO (µs par croche) aux changements de BPM |
| **Key Signature** | Meta-event key signature (F#=0, C=0, F#=−1, etc.) |
| **Time Signature** | Meta-event time signature (ex: 4/4, 3/4) |
| **Track Name** | Noms de tracks optionnels |

### 3. Conversion Tempo

```python
# BPM → microsecondes par croche
def bpm_to_microseconds(bpm):
    return int(60_000_000 / bpm)
```

### 4. Gestion des voix

- **Voix RH** → channel 0 (program 1: piano acoustique)
- **Voix LH** → channel 1 (program 1: piano acoustique)
- **Notes sans voix** → channel 0

### 5. Gestion des liaisons (tie)

- Si `note.tie == 'start'` → note.On avec sustain, mais pas de note.On suivant
- Si `note.tie == 'continue'` → pas de note.On, prolonge la note précédente
- Si `note.tie == 'end'` → note.On + note.Off pour la note prolongée

---

## Interface de Module

```python
class MIDIExporter:
    def __init__(self, bpm_map: List[TempoPoint], key_signature: str = 'C'):
        """
        Args:
            bpm_map: Liste de points de tempo [(time, bpm), ...]
            key_signature: Signature de tonalité (ex: 'C', 'G', 'F#m', '-D', etc.)
        """
        self.bpm_map = bpm_map
        self.key_signature = key_signature
    
    def export(self, notes: List[dict], output_path: str) -> str:
        """
        Exporte les notes en fichier MIDI.
        
        Args:
            notes: Liste de notes quantisées
            output_path: Chemin de sortie
        
        Returns:
            Chemin du fichier MIDI généré
        """
        pass
    
    def _build_tempo_events(self) -> List[Tuple[int, int]]:
        """
        Construit les événements de tempo MIDI ticks → microseconds.
        
        Returns:
            Liste de (ticks, microseconds_per_quarter_note)
        """
        pass
    
    def _build_time_signature(self) -> Tuple[int, int, int, int]:
        """
        Construit la signature de temps MIDI.
        
        Returns:
            (numerator, denominator, metronome, clicks_in_32_nd)
        """
        pass
```

---

## Dépendances

```python
# backend/requirements.txt
midiutil>=1.2.1      # Écriture fichiers MIDI
```

---

## Tests

### Test 1: Export basique
```python
def test_export_basic():
    exporter = MIDIExporter(
        bpm_map=[(0, 120)],
        key_signature='C'
    )
    notes = [
        {'note_number': 60, 'start_time': 0, 'end_time': 1, 'velocity': 64, 'voice': 'RH'},
        {'note_number': 64, 'start_time': 1, 'end_time': 2, 'velocity': 64, 'voice': 'RH'},
        {'note_number': 67, 'start_time': 2, 'end_time': 3, 'velocity': 64, 'voice': 'LH'},
    ]
    output = exporter.export(notes, 'test_output.mid')
    assert os.path.exists(output)
    assert os.path.getsize(output) > 0
```

### Test 2: Export avec tempo changeant
```python
def test_export_tempo_changes():
    exporter = MIDIExporter(
        bpm_map=[(0, 100), (30, 140)],
        key_signature='G'
    )
    notes = [...]  # notes sur 60 secondes
    output = exporter.export(notes, 'test_tempo.mid')
    assert os.path.exists(output)
```

### Test 3: Validation avec mido
```python
def test_validate_midi():
    exporter = MIDIExporter(
        bpm_map=[(0, 120)],
        key_signature='C'
    )
    notes = [...]
    output = exporter.export(notes, 'test_validate.mid')
    
    # Valider avec mido
    import mido
    mid = mido.MidiFile(output)
    assert mid.type in ('MIDI1', 'MID1')
    total_ticks = 0
    for track in mid.tracks:
        total_ticks += len(track)
    assert total_ticks > 0
```

---

## Intégration avec app.py

```python
# Dans backend/app.py

from midi_exporter import MIDIExporter

@app.route('/transcribe', methods=['POST'])
async def transcribe():
    # ... pipeline existant ...
    
    # Phase 4: MIDI Export
    key_sig = tonality_detector.detect_key(audio_segment)
    exporter = MIDIExporter(bpm_map=bpm_clusters, key_signature=key_sig)
    midi_path = exporter.export(quantized_notes, output_dir)
    
    return FileResponse(
        midi_path,
        media_type='audio/midi',
        filename='output.mid'
    )
```

---

## Règles

1. **Fichier MIDI Type 0** par défaut (plus compatible)
2. **Program change** : piano acoustique (program 1) sur tous les channels
3. **Ticks par quarter note** : 480 (standard)
4. **Signature de temps** : déduite du contexte musical (détection heuristique)
5. **Signature de tonalité** : utilisée si détectée par Phase 3
6. **Code en français** : commentaires et docstrings en français

---

## Ordre d'Implémentation

1. Créer `backend/midi_exporter.py`
2. Implémenter `MIDIExporter.__init__()`
3. Implémenter `MIDIExporter._build_tempo_events()`
4. Implémenter `MIDIExporter._build_time_signature()`
5. Implémenter `MIDIExporter.export()`
6. Ajouter `midiutil` à `requirements.txt`
7. Tester avec `if __name__ == "__main__"`
8. Intégrer dans `app.py`

---

**Dernière mise à jour** : 4 juillet 2026