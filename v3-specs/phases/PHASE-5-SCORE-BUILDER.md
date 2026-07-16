# Phase 5 — Score Builder (PDF / IMG)

> **État** : À créer
> **Création** : 4 juillet 2026
> **Statut** : ❌ NON COMMENCÉ

---

## Objectif

Générer une partition musicale visuelle (PDF et/ou image PNG) à partir du JSON de notes quantisées produit par la Phase 4.

---

## Entrée

```json
{
  "notes": [
    {
      "pitch": 60,
      "start_beat": 0.0,
      "end_beat": 1.0,
      "velocity": 100,
      "voice": "right",
      "chord": {"root": "C", "quality": "major", "beat": 0}
    },
    ...
  ],
  "key_signature": {"tonic": "C", "mode": "major"},
  "time_signature": {"numerator": 4, "denominator": 4},
  "tempo_map": [
    {"beat": 0.0, "bpm": 120.0},
    ...
  ]
}
```

---

## Sortie

### Format PDF (partition standard)

```
outputs/score_{timestamp}.pdf
```

- Partition musicale standard (notes, clés, mesures, indications)
- Port de piano (grand port : treble + bass clef)
- Séparation LH/RH par voice
- Indications de tonalité et tempo

### Format Image (aperçu rapide)

```
outputs/score_{timestamp}.png
```

- Rendu PNG du PDF (1 page = 1 image)
- Résolution : 300 DPI minimum

---

## Spécifications Techniques

### 1. Structure de la Partition

```python
class ScoreBuilder:
    """Génère une partition PDF/PNG à partir de notes quantisées."""
    
    def __init__(self, config: ScoreConfig):
        self.config = config
        self.pages = []
    
    def build(self, score_data: ScoreData) -> ScoreOutput:
        """
        Génère la partition complète.
        
        Args:
            score_data: Notes + métadonnées musicales
            
        Returns:
            ScoreOutput avec paths vers PDF et PNG
        """
        self.pages = self._layout_pages(score_data)
        pdf_path = self._render_pdf(self.pages)
        png_path = self._render_png(pdf_path)
        return ScoreOutput(pdf_path=pdf_path, png_path=png_path)
    
    def _layout_pages(self, score_data: ScoreData) -> List[Page]:
        """Divise le morceau en pages/lignes lisibles."""
        ...
    
    def _render_pdf(self, pages: List[Page]) -> str:
        """Rend les pages en PDF."""
        ...
    
    def _render_png(self, pdf_path: str) -> str:
        """Convertit PDF en PNG."""
        ...
```

### 2. Config du Score

```python
@dataclass
class ScoreConfig:
    """Configuration du rendu de partition."""
    page_width: float = 8.5  # inches (letter)
    page_height: float = 11.0
    margin: float = 1.0
    staff_height: float = 0.6  # inches
    systems_per_page: int = 4
    staff_spacing: float = 0.8  # inches
    use_grand_staff: bool = True  # Grand port piano
    clef_left: str = "bass"
    clef_right: str = "treble"
    font_size: float = 12.0
    note_head_size: float = 0.15  # inches
    show_chord_symbols: bool = True
    show_tempo_indications: bool = True
    show_key_signature: bool = True
    show_time_signature: bool = True
```

### 3. Structure de données

```python
@dataclass
class NoteEvent:
    """Note individuelle dans la partition."""
    pitch: int              # MIDI note number (0-127)
    start_beat: float       # Position de début en beats
    end_beat: float         # Position de fin en beats
    velocity: int           # Vélocité (0-127)
    voice: str              # "left", "right", "both"
    chord: Optional[ChordInfo] = None
    lyric: Optional[str] = None


@dataclass
class ChordInfo:
    """Information d'accord."""
    root: str               # Note racine (C, D#, etc.)
    quality: str            # "major", "minor", "dom7", etc.
    bass: Optional[str] = None  # Renversement


@dataclass
class Measure:
    """Un mesure de la partition."""
    measure_num: int
    beats: List[NoteEvent]  # Notes dans cette mesure
    chord: ChordInfo        # Accord principal de la mesure


@dataclass
class System:
    """Une ligne (système) de partition."""
    measures: List[Measure]
    start_beat: float
    end_beat: float


@dataclass
class Page:
    """Une page de partition."""
    systems: List[System]
    page_number: int


@dataclass
class ScoreOutput:
    """Sortie du Score Builder."""
    pdf_path: str
    png_path: str
    page_count: int
    duration_beats: float
```

---

## Algorithme de Layout

### 1. Calcul de la largeur des mesures

```
1. Pour chaque mesure:
   - Compter le nombre de beats (time signature)
   - Estimer la largeur nécessaire:
     width = num_beats * BEAT_WIDTH_FACTOR
   - BEAT_WIDTH_FACTOR = 0.8 inches par beat (ajustable)

2. Trouver la largeur maximale parmi toutes les mesures
3. Si width > page_width - 2*margin:
   - Diviser la mesure en sous-groupes
   - Ou réduire BEAT_WIDTH_FACTOR
```

### 2. Placement des notes sur les ports

```
Grand Port (Piano):
┌─────────────────────────────────────┐
│  Port supérieur (clé de Sol)        │ ← Right Hand
│  ┌───┬───┬───┬───┬───┬───┬───┬───┐│
│  │   │   │   │   │   │   │   │   ││
│  ├───┼───┼───┼───┼───┼───┼───┼───┤│
│  │   │   │   │   │   │   │   │   ││
│  └───┴───┴───┴───┴───┴───┴───┴───┘│
│                                     │
│  Port inférieur (clé d'Fa)          │ ← Left Hand
│  ┌───┬───┬───┬───┬───┬───┬───┬───┐│
│  │   │   │   │   │   │   │   │   ││
│  ├───┼───┼───┼───┼───┼───┼───┼───┤│
│  │   │   │   │   │   │   │   │   ││
│  └───┴───┴───┴───┴───┴───┴───┴───┘│
└─────────────────────────────────────┘
```

### 3. Règles de placement

```python
def place_note(note: NoteEvent, staff_type: str) -> Position:
    """
    Calcule la position d'une note sur le port.
    """
    if staff_type == "treble":
        # Clé de Sol: MIDI 60 = C4 (1ère octave ajoutée)
        # Position Y = base_y - (pitch - 60) * NOTE_SPACING
        base_pitch = 60  # C4 en clé de Sol
    elif staff_type == "bass":
        # Clé de Fa: MIDI 48 = C3 (2ème octave ajoutée)
        base_pitch = 48  # C3 en clé de Fa
    
    y = staff_base_y - (note.pitch - base_pitch) * LINE_SPACING
    x = measure_start_x + (note.start_beat - measure_start_beat) * BEAT_WIDTH
    
    return Position(x, y)
```

---

## Bibliothèque recommandée

### Option 1: music21 (Recommandé)

```python
from music21 import stream, note, key, timeSignature, harmony
from music21 import converter, midi
from music21 import layout, page

def build_score_with_music21(score_data: ScoreData) -> stream.Score:
    """Construit un score music21 à partir des données."""
    s = stream.Score()
    
    # Indication de tonalité
    key_expr = key.Key(score_data.key_signature)
    s.insert(0, key_expr)
    
    # Indication de mesure
    ts = timeSignature.TimeSignature(
        f"{score_data.time_signature['numerator']}/{score_data.time_signature['denominator']}"
    )
    s.insert(0, ts)
    
    # Partition de piano
    piano_staff = stream.Part(name="Piano")
    
    # Main droite (clé de Sol)
    right_part = stream.Part(name="Right Hand")
    treble_clef = clef.TrebleClef()
    right_part.insert(0, treble_clef)
    
    for n in score_data.right_hand_notes:
        note_obj = note.Note(n.pitch)
        note_obj.quarterLength = n.end_beat - n.start_beat
        note_obj.stealTimeFrom(n)
        right_part.append(note_obj)
    
    piano_staff.append(right_part)
    
    # Main gauche (clé de Fa)
    left_part = stream.Part(name="Left Hand")
    bass_clef = clef.BassClef()
    left_part.insert(0, bass_clef)
    
    for n in score_data.left_hand_notes:
        note_obj = note.Note(n.pitch)
        note_obj.quarterLength = n.end_beat - n.start_beat
        left_part.append(note_obj)
    
    piano_staff.append(left_part)
    
    s.append(piano_staff)
    return s
```

### Option 2: cairosvg + cairo (Direct)

```python
# Dessin direct avec Cairo
import cairo

def draw_staff(ctx, x, y, width, height):
    """Dessine un port (5 lignes)."""
    line_spacing = height / 6
    for i in range(5):
        line_y = y + i * line_spacing
        ctx.move_to(x, line_y)
        ctx.line_to(x + width, line_y)
        ctx.stroke()

def draw_note(ctx, x, y, note_type="quarter"):
    """Dessine une note."""
    if note_type in ["whole", "half"]:
        # Note ronde ou blanche (ovide vide)
        ctx.ellipse(x - 5, y - 3, 10, 6)
        ctx.stroke()
    else:
        # Note noire (ovide pleine + hampe)
        ctx.ellipse(x - 5, y - 3, 10, 6)
        ctx.fill()
        # Hampe
        ctx.move_to(x + 5, y - 3)
        ctx.line_to(x + 5, y - 20)
        ctx.stroke()
```

### Option 3: reportlab + custom music fonts

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Enregistrer une police de notes musicales
pdfmetrics.registerFont(TTFont('Bravura', 'Bravura.ttf'))

def draw_score_pdf(canvas_obj, score_data):
    """Dessine la partition avec ReportLab."""
    canvas_obj.setStrokeColorRGB(0, 0, 0)
    canvas_obj.setFillColorRGB(0, 0, 0)
    
    # Dessiner les ports
    for system in score_data.systems:
        for staff in system.staff_list:
            draw_staff(canvas_obj, staff.x, staff.y, staff.width, staff.height)
    
    # Dessiner les notes
    for note in score_data.notes:
        draw_note(canvas_obj, note.x, note.y)
```

---

## Dépendances à ajouter

```txt
# v3-specs/requirements-v3.txt (ajouts)
music21>=8.0.0          # Pour la génération de partitions musicales
reportlab>=4.0.0        # Alternative pour PDF
cairocffi>=1.6.0        # Alternative pour le rendu vectoriel
pillow>=10.0.0          # Pour conversion PDF→PNG
```

---

## Interface API

### Endpoint de génération

```
POST /score
Content-Type: application/json

Request:
{
  "notes": [...],           // Données de la Phase 4
  "config": {
    "page_size": "letter",  // "letter", "a4", "legal"
    "orientation": "portrait", // "portrait", "landscape"
    "margins": "normal",    // "narrow", "normal", "wide"
    "show_chords": true,
    "show_tempo": true
  }
}

Response:
{
  "pdf_url": "/outputs/score_123456.pdf",
  "png_url": "/outputs/score_123456.png",
  "page_count": 3,
  "duration_beats": 256.0
}
```

### Téléchargement

```
GET /score/{score_id}/pdf
Content-Type: application/pdf
Response: [PDF file binary]

GET /score/{score_id}/png
Content-Type: image/png
Response: [PNG file binary]
```

---

## Règles de Notation Musicale

### 1. Clés d'armure

```python
KEY_SIGNATURES = {
    "C": {"sharps": 0, "flats": 0},
    "G": {"sharps": 1, "flats": 0},
    "D": {"sharps": 2, "flats": 0},
    "A": {"sharps": 3, "flats": 0},
    "E": {"sharps": 4, "flats": 0},
    "B": {"sharps": 5, "flats": 0},
    "F#": {"sharps": 6, "flats": 0},
    "Gb": {"sharps": 0, "flats": 1},
    "Ab": {"sharps": 0, "flats": 4},
    "Bb": {"sharps": 0, "flats": 2},
    "Eb": {"sharps": 0, "flats": 3},
    "F": {"sharps": 0, "flats": 1},
}
```

### 2. Formes de notes

```
Ronde (whole)     : ○  (2/2, half note)
Blanche (half)    : ◌  (1/1, half note)
Noire (quarter)   : ♩  (1/4, quarter note)
Croche (eighth)   : ♪  (1/8, eighth note) + barre
Double croche      : ♫  (1/16, sixteenth note) + 2 barres
```

### 3. Regroupement par mesure

```
Règle: Les notes doivent être groupées par mesure selon le time signature.
Exemple: 4/4 → 4 beats par mesure

Mesure 1: [♪ ♩ ♩] (1 + 2 + 1 = 4 beats)
Mesure 2: [♩ ♩ ♩ ♩] (1 + 1 + 1 + 1 = 4 beats)
Mesure 3: [♪ ♪ ♩] (0.5 + 0.5 + 2 + 2 = 4 beats)
```

### 4. Ligatures de phrasing

```
Notes liées (même pitch, mesures consécutives):
- Dessiner un arc de cercle au-dessus/sous les notes
- Direction de la ligature dépend de la position verticale

Notes non liées:
- Hampe individuelle pour chaque note
```

---

## Gestion des cas edge

### 1. Notes hors tessiture

```python
def validate_note_pitch(pitch: int, voice: str) -> bool:
    """Vérifie que la note est dans la tessiture du piano."""
    if pitch < 21 or pitch > 108:  # A0 - C8
        return False
    if voice == "right" and pitch < 59:  # B4 minimum
        return False
    if voice == "left" and pitch > 72:  # C6 maximum
        return False
    return True
```

### 2. Mesures incomplètes

```python
def fill_measure(measure: Measure, time_sig: TimeSignature):
    """Ajoute des silences si la mesure est incomplète."""
    current_beats = sum(n.quarterLength for n in measure.beats)
    remaining = time_sig.numerator - current_beats
    
    if remaining > 0:
        # Ajouter un silence de longueur appropriée
        rest = Rest()
        rest.quarterLength = remaining
        measure.beats.append(rest)
```

### 3. Changements de tempo

```python
def add_tempo_indication(system: System, tempo_map: List[TempoPoint]):
    """Ajoute les indications de tempo sur le système."""
    for point in tempo_map:
        if system.start_beat <= point.beat <= system.end_beat:
            indication = TextElement(
                text=f"♩ = {int(point.bpm)}",
                x=point.x_position,
                y=system.y - 1.0  # Au-dessus du premier port
            )
            system.elements.append(indication)
```

---

## Tests unitaires

```python
import pytest

class TestScoreBuilder:
    
    def test_simple_scale(self):
        """Test: Une gamme de Do majeur."""
        notes = [
            {"pitch": 60, "start_beat": 0, "end_beat": 1, "velocity": 80, "voice": "right"},
            {"pitch": 62, "start_beat": 1, "end_beat": 2, "velocity": 80, "voice": "right"},
            {"pitch": 64, "start_beat": 2, "end_beat": 3, "velocity": 80, "voice": "right"},
            {"pitch": 65, "start_beat": 3, "end_beat": 4, "velocity": 80, "voice": "right"},
        ]
        score_data = ScoreData(
            notes=notes,
            key_signature={"tonic": "C", "mode": "major"},
            time_signature={"numerator": 4, "denominator": 4}
        )
        
        builder = ScoreBuilder()
        output = builder.build(score_data)
        
        assert output.pdf_path is not None
        assert output.png_path is not None
        assert output.page_count >= 1
    
    def test_chord_placement(self):
        """Test: Accord placé correctement sur les deux ports."""
        notes = [
            {"pitch": 64, "start_beat": 0, "end_beat": 2, "velocity": 80, "voice": "right"},
            {"pitch": 67, "start_beat": 0, "end_beat": 2, "velocity": 80, "voice": "right"},
            {"pitch": 72, "start_beat": 0, "end_beat": 2, "velocity": 80, "voice": "right"},
            {"pitch": 48, "start_beat": 0, "end_beat": 2, "velocity": 70, "voice": "left"},
            {"pitch": 52, "start_beat": 0, "end_beat": 2, "velocity": 70, "voice": "left"},
            {"pitch": 55, "start_beat": 0, "end_beat": 2, "velocity": 70, "voice": "left"},
        ]
        score_data = ScoreData(
            notes=notes,
            key_signature={"tonic": "C", "mode": "major"},
            time_signature={"numerator": 4, "denominator": 4}
        )
        
        builder = ScoreBuilder()
        output = builder.build(score_data)
        
        assert output.pdf_path is not None
        assert output.page_count >= 1
    
    def test_multi_page(self):
        """Test: Un morceau long génère plusieurs pages."""
        notes = [
            {"pitch": 60 + i, "start_beat": float(i), "end_beat": float(i + 1), "velocity": 80, "voice": "right"}
            for i in range(200)  # 200 beats ≈ 50 mesures de 4/4
        ]
        score_data = ScoreData(
            notes=notes,
            key_signature={"tonic": "C", "mode": "major"},
            time_signature={"numerator": 4, "denominator": 4}
        )
        
        builder = ScoreBuilder()
        output = builder.build(score_data)
        
        assert output.page_count > 1
    
    def test_key_signature_applied(self):
        """Test: L'armure est appliquée correctement."""
        notes = [
            {"pitch": 62, "start_beat": i, "end_beat": i + 1, "velocity": 80, "voice": "right"}
            for i in range(4)  # F# en Do majeur
        ]
        score_data = ScoreData(
            notes=notes,
            key_signature={"tonic": "G", "mode": "major"},  # 1 dièse
            time_signature={"numerator": 4, "denominator": 4}
        )
        
        builder = ScoreBuilder()
        output = builder.build(score_data)
        
        assert output.pdf_path is not None
```

---

## Pipeline Complet (intégré)

```
Phase 1: Audio Upload
    ↓  AudioSegment (FLAC/MP3/WAV)
Phase 2: Voice Engine
    ↓  List[VoiceEvent] (transcription)
Phase 3: Tempo Map
    ↓  List[BPMCluster] (tempo estimation)
Phase 4: Quantizer
    ↓  List[Note] (notes quantisées)
Phase 5: MIDI Export
    ↓  .mid file
Phase 6: Score Builder
    ↓  PDF + PNG (partition visuelle)
```

---

## Dépendances à ajouter à `requirements-v3.txt`

```txt
# Phase 5 - Score Builder
music21>=8.0.0
reportlab>=4.0.0
cairocffi>=1.6.0
```

---

## Checklist d'implémentation

- [ ] Créer `v3-specs/phases/PHASE-5-SCORE-BUILDER.md` (ce fichier)
- [ ] Implémenter `ScoreBuilder` class
- [ ] Implémenter `_layout_pages()` (division en systèmes/pages)
- [ ] Implémenter `_render_pdf()` (rendu PDF via music21)
- [ ] Implémenter `_render_png()` (conversion PDF→PNG)
- [ ] Gérer clés d'armure
- [ ] Gérer indications de tempo
- [ ] Gérer indications de tonalité
- [ ] Gérer accords/chords
- [ ] Gérer separation LH/RH
- [ ] Gérer mesures incomplètes
- [ ] Gérer notes hors tessiture
- [ ] Gérer ligatures de phrasing
- [ ] Écrire tests unitaires
- [ ] Intégrer dans `app.py`
- [ ] Ajouter endpoint `/score`
- [ ] Ajouter endpoints de téléchargement
- [ ] Tester avec fichiers réels

---

**Dernière mise à jour** : 4 juillet 2026