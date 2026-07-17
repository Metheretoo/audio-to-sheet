"""
regression_harness.py — Harnais de validation régression (Phase 7)

Objectif : comparer la sortie du pipeline (JSON score_data) contre une
référence MusicXML (Mazurka de Chopin) et produire un rapport F1/rythme/ornements.

Composants :
  1. ReferenceStore   — lecture/parsing du MusicXML référence
  2. MetricCalculator — calcul F1 notes, précision rythmique, ornements
  3. RegressionReport — formatage du rapport JSON + sauvegarde
  4. run_regression   — point d'entrée (script CLI ou appel programmatique)

Historisation :
  - Par défaut : fichier JSON local (metrics_history.json)
  - Optionnel : MongoDB via pymongo (si disponible)

Usage CLI :
  python regression_harness.py --reference reference/mazurka_op68_no3.musicxml \
                               --output output_dir
  python regression_harness.py --reference reference/mazurka_op68_no3.musicxml \
                               --metrics metrics_history.json
"""

import os
import sys
import json
import argparse
import hashlib
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path


# ── Constantes ────────────────────────────────────────────────────────────────

# Chemins par défaut
DEFAULT_REFERENCE_DIR = os.path.join(os.path.dirname(__file__), '..', 'references')
DEFAULT_METRICS_FILE  = os.path.join(os.path.dirname(__file__), '..', 'metrics_history.json')

# Seuil par défaut (peut être override via config)
DEFAULT_THRESHOLDS = {
    'f1_notes_mg': 0.90,    # F1 main gauche ≥ 90%
    'f1_notes_md': 0.90,    # F1 main droite ≥ 90%
    'precision_rythme': 0.85,  # précision rythmique ≥ 85%
    'ornements_preserves': 0.80,  # ornements ≥ 80%
    'signature_detectee': 1.0,  # signature 3/4 détectée
    'chute_metriques': 0.05,    # alerte si chute > 5%
}


# ── Données ───────────────────────────────────────────────────────────────────

@dataclass
class NoteMatch:
    """Résultat de matching d'une note."""
    note_id: str
    pitch: int
    onset: float
    expected_onset: Optional[float] = None
    onset_error: Optional[float] = None  # |onset - expected_onset|
    is_match: bool = False
    match_type: str = 'none'  # 'exact', 'temporal', 'miss', 'extra'
    is_downbeat: bool = False
    is_uncertain: bool = False


@dataclass
class OrnamentMatch:
    """Résultat de matching d'un ornament."""
    ornament_id: str
    type: str  # 'appoggiatura', 'trill', 'dottedRhythm'
    position: float
    expected_type: Optional[str] = None
    is_match: bool = False


@dataclass
class RegressionMetrics:
    """Métriques de régression."""
    # F1 notes MG
    f1_notes_mg: float = 0.0
    precision_notes_mg: float = 0.0
    recall_notes_mg: float = 0.0
    
    # F1 notes MD
    f1_notes_md: float = 0.0
    precision_notes_md: float = 0.0
    recall_notes_md: float = 0.0
    
    # Rythme
    precision_rythme: float = 0.0
    recall_rythme: float = 0.0
    avg_onset_error: float = 0.0
    max_onset_error: float = 0.0
    notes_within_50ms: float = 0.0
    notes_within_100ms: float = 0.0
    total_notes: int = 0
    matched_notes: int = 0
    
    # Ornements
    appoggiaturas_detected: int = 0
    appoggiaturas_preserved: int = 0
    trills_detected: int = 0
    trills_preserved: int = 0
    ornements_total: int = 0
    ornements_preserves: float = 0.0
    
    # Signature rythmique
    signature_detectee: bool = False
    signature_attendue: Tuple[int, int] = (3, 4)
    
    # Global
    overall_pass: bool = False
    overall_score: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class RegressionReport:
    """Rapport complet de régression."""
    timestamp: float = 0.0
    run_id: str = ''
    reference_file: str = ''
    reference_hash: str = ''
    pipeline_output: str = ''
    pipeline_output_hash: str = ''
    metrics: RegressionMetrics = field(default_factory=RegressionMetrics)
    notes_detail: List[NoteMatch] = field(default_factory=list)
    ornaments_detail: List[OrnamentMatch] = field(default_factory=list)
    thresholds: Dict[str, float] = field(default_factory=dict)
    passed: bool = False
    summary: str = ''


# ── ReferenceStore ────────────────────────────────────────────────────────────

class ReferenceStore:
    """
    Lit et parse un MusicXML de référence pour en extraire :
    - Les notes (pitch, onset, duration, main)
    - Les downbeats
    - Les ornements
    - La signature rythmique
    """
    
    NS = {
        'musicxml': 'http://www.musicxml.org/dtds',
        'mvx': 'http://www.mvsoft.com/musicxml',
        'partwise': 'http://www.musicxml.org/partwise',
    }
    
    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self.tree = ET.parse(xml_path)
        self.root = self.tree.getroot()
        
        # Notes extraites
        self.notes: List[Dict[str, Any]] = []
        self.downbeats: List[float] = []
        self.ornaments: List[Dict[str, Any]] = []
        self.time_signature: Tuple[int, int] = (4, 4)
        self.tempo: Optional[float] = None
        self.key_signature: str = 'C'
        
        self._parse()
    
    def _parse(self):
        """Parse le MusicXML pour extraire les données musicales."""
        # Parcourir toutes les mesures
        for measure in self.root.iter('measure'):
            measure_num = int(measure.get('number', 0))
            
            # Extraire la signature rythmique
            for time_elem in measure.iter('time'):
                beats_elem = time_elem.find('beats')
                if beats_elem is not None:
                    beat_type_elem = time_elem.find('beat-type')
                    if beat_type_elem is not None:
                        self.time_signature = (
                            int(beats_elem.text),
                            int(beat_type_elem.text)
                        )
            
            # Extraire les notes
            for note_elem in measure.iter('note'):
                pitch_elem = note_elem.find('pitch') if note_elem.find('pitch') is not None else note_elem.find('unpitched')
                step_elem = note_elem.find('step')
                octave_elem = note_elem.find('octave')
                
                if step_elem is None or octave_elem is None:
                    continue
                
                step_to_midi = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
                pitch = step_to_midi.get(step_elem.text.upper(), 60)
                
                alter_elem = note_elem.find('alter')
                if alter_elem is not None and alter_elem.text:
                    pitch += int(alter_elem.text)
                
                midi_pitch = 12 + int(octave_elem.text) * 12 + pitch
                
                # Duration
                dur_elem = note_elem.find('duration')
                duration_beats = float(dur_elem.text) if dur_elem is not None and dur_elem.text else 1.0
                
                # Onset (beat position dans la mesure)
                measure_num_elem = note_elem.find('measure')
                beat_elem = note_elem.find('beam')  # beam pour les mesures rythmiques
                
                # Note name (clef)
                note_name = step_elem.text.upper()
                if alter_elem is not None:
                    note_name += alter_elem.text
                note_name += str(octave_elem.text)
                
                # Main (MG/MD) — approximation basée sur le pitch
                is_bass = midi_pitch < 48  # en dessous de F2
                
                # Ornements
                ornament_type = None
                grace = note_elem.find('grace')
                if grace is not None:
                    ornament_type = 'graceNote'
                
                trill = note_elem.find('.//trill-mark') or note_elem.find('ornaments', self.NS).find('trill-mark') if note_elem.find('ornaments', self.NS) is not None else None
                if trill is not None:
                    ornament_type = 'trill'
                
                # Tempo
                direction_elem = note_elem.find('../direction')  # direction dans la mesure
                if direction_elem is not None:
                    tempo_elem = direction_elem.find('.//metronome')
                    if tempom_elem is not None:
                        bpm_elem = tempom_elem.find('.//bpm')
                        if bpm_elem is not None:
                            self.tempo = float(bpm_elem.text)
                
                self.notes.append({
                    'measure': measure_num,
                    'pitch': midi_pitch,
                    'duration_beats': duration_beats,
                    'is_bass': is_bass,
                    'ornament_type': ornament_type,
                    'note_name': note_name,
                })
        
        # Chercher les downbeats (premier temps de chaque mesure)
        for measure in self.root.iter('measure'):
            measure_num = int(measure.get('number', 0))
            for barline in measure.iter('barline'):
                if barline.get('bar-style', '') == 'heavy':
                    self.downbeats.append(measure_num)
        
        # Chercher les ornements explicites
        for ornament_elem in self.root.iter('.//ornaments'):
            for trill in ornament_elem.iter('trill-mark'):
                # Trouver la note associée
                parent = trill.getparent()
                if parent is not None:
                    measure = parent.getparent()
                    if measure is not None:
                        self.ornaments.append({
                            'type': 'trill',
                            'measure': int(measure.get('number', 0)),
                        })
            
            for grace_note in ornament_elem.iter('grace'):
                parent = grace_note.getparent()
                if parent is not None:
                    measure = parent.getparent()
                    if measure is not None:
                        self.ornaments.append({
                            'type': 'graceNote',
                            'measure': int(measure.get('number', 0)),
                        })
    
    def get_notes_by_hand(self, hand: str = 'all') -> List[Dict]:
        """Retourne les notes filtrées par main."""
        if hand == 'mg':
            return [n for n in self.notes if n['is_bass']]
        elif hand == 'md':
            return [n for n in self.notes if not n['is_bass']]
        return self.notes
    
    def get_ornament_types(self) -> List[str]:
        """Retourne les types d'ornements présents."""
        return list(set(o['type'] for o in self.ornaments))
    
    def file_hash(self) -> str:
        """Hash du fichier de référence."""
        h = hashlib.md5()
        with open(self.xml_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()


# ── PipelineOutputParser ──────────────────────────────────────────────────────

class PipelineOutputParser:
    """
    Parse le JSON de sortie du pipeline (score_data) pour en extraire :
    - Les notes (pitch, onset, duration, main)
    - Les downbeats
    - Les ornements
    """
    
    def __init__(self, score_data: Dict[str, Any]):
        self.data = score_data
        self.notes: List[Dict[str, Any]] = []
        self.downbeats: List[float] = []
        self.ornaments: List[Dict[str, Any]] = []
        self.time_signature: Tuple[int, int] = (4, 4)
        self.tempo: Optional[float] = None
        self.key_signature: str = 'C'
        
        self._parse()
    
    def _parse(self):
        """Parse le score_data JSON."""
        # Méta
        self.tempo = self.data.get('tempo')
        self.time_signature = tuple(self.data.get('timeSignature', [4, 4]))
        self.key_signature = self.data.get('keySignature', 'C')
        
        # Downbeats
        detected_meter = self.data.get('detectedMeter', [])
        if detected_meter:
            self.downbeats = [m for m in self.data.get('measures', []) if m.get('isDownbeat', False)]
        
        # Notes par mesure
        for measure in self.data.get('measures', []):
            measure_num = measure.get('measureNumber', 0)
            
            for hand_key in ['treble', 'bass']:
                is_bass = (hand_key == 'bass')
                for note in measure.get(hand_key, []):
                    pitch = note.get('midiPitch', 60)
                    start_beat = note.get('startBeat', 0)
                    duration = note.get('duration', 1.0)
                    
                    self.notes.append({
                        'measure': measure_num,
                        'pitch': pitch,
                        'start_beat': start_beat,
                        'duration_beats': duration,
                        'is_bass': is_bass,
                        'amplitude': note.get('amplitude', 0.5),
                        'id': note.get('id', ''),
                    })
        
        # Ornements
        ornaments_data = self.data.get('ornaments', {})
        for app in ornaments_data.get('appoggiaturas', []):
            self.ornaments.append({
                'type': 'graceNote',
                'measure': app.get('measure', 0),
                'position': app.get('beatPosition', 0),
                'pitch': app.get('pitch', 60),
            })
        
        for trill in ornaments_data.get('trills', []):
            self.ornaments.append({
                'type': 'trill',
                'measure': trill.get('measure', 0),
                'position': trill.get('startBeat', 0),
            })
    
    def get_notes_by_hand(self, hand: str = 'all') -> List[Dict]:
        """Retourne les notes filtrées par main."""
        if hand == 'mg':
            return [n for n in self.notes if n['is_bass']]
        elif hand == 'md':
            return [n for n in self.notes if not n['is_bass']]
        return self.notes
    
    def file_hash(self) -> str:
        """Hash du contenu du score_data."""
        content = json.dumps(self.data, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()


# ── MetricCalculator ──────────────────────────────────────────────────────────

class MetricCalculator:
    """Calcule les métriques F1, précision rythmique, ornements."""
    
    def __init__(
        self,
        reference: ReferenceStore,
        output: PipelineOutputParser,
        tolerance_onset: float = 0.05,  # 50ms tolérance par défaut
        tolerance_pitch: int = 1,  # ±1 demi-ton
    ):
        self.ref = reference
        self.out = output
        self.tolerance_onset = tolerance_onset
        self.tolerance_pitch = tolerance_pitch
        self.notes_detail: List[NoteMatch] = []
        self.ornaments_detail: List[OrnamentMatch] = []
    
    def calculate_all(self) -> RegressionMetrics:
        """Calcule toutes les métriques et retourne le résultat."""
        metrics = RegressionMetrics()
        
        # 1. Matching des notes
        self.notes_detail = self._match_notes()
        
        # 2. F1 notes MG
        metrics.f1_notes_mg, metrics.precision_notes_mg, metrics.recall_notes_mg = self._compute_f1('mg')
        
        # 3. F1 notes MD
        metrics.f1_notes_md, metrics.precision_notes_md, metrics.recall_notes_md = self._compute_f1('md')
        
        # 4. Métriques rythmiques
        self._compute_rhythm_metrics(metrics)
        
        # 5. Ornements
        self._compute_ornament_metrics(metrics)
        
        # 6. Signature rythmique
        metrics.signature_detectee = (self.out.time_signature == self.ref.time_signature)
        metrics.signature_attendue = self.ref.time_signature
        
        # 7. Score global
        metrics.overall_score = self._compute_overall_score(metrics)
        metrics.overall_pass = self._check_thresholds(metrics)
        
        # 8. Warnings
        metrics.warnings = self._generate_warnings(metrics)
        
        return metrics
    
    def _match_notes(self) -> List[NoteMatch]:
        """
        Associe chaque note du pipeline à une note de référence la plus proche.
        Algorithme : pour chaque note output, trouver la note ref la plus proche
        si dans la tolérance de pitch et onset.
        """
        matches = []
        ref_notes = self.ref.notes
        out_notes = self.out.notes
        
        # Marquer les notes déjà matchées
        ref_matched = [False] * len(ref_notes)
        out_matched = [False] * len(out_notes)
        
        for i, out_note in enumerate(out_notes):
            match = NoteMatch(
                note_id=out_note.get('id', f'out_{i}'),
                pitch=out_note['pitch'],
                onset=out_note.get('start_beat', out_note.get('onset', 0)),
            )
            
            best_dist = float('inf')
            best_idx = -1
            
            for j, ref_note in enumerate(ref_notes):
                if ref_matched[j]:
                    continue
                
                # Distance de pitch
                pitch_dist = abs(out_note['pitch'] - ref_note['pitch'])
                if pitch_dist > self.tolerance_pitch:
                    continue
                
                # Distance d'onset (convertire en secondes si nécessaire)
                # Approximation : beat * (60 / tempo)
                tempo = self.out.tempo or 120.0
                onset_diff = abs(match.onset - ref_note.get('beat_position', ref_note.get('measure', 0))) * (60.0 / tempo)
                
                if onset_diff < best_dist:
                    best_dist = onset_diff
                    best_idx = j
            
            if best_idx >= 0 and best_dist <= self.tolerance_onset:
                match.expected_onset = ref_notes[best_idx].get('beat_position', ref_notes[best_idx].get('measure', 0)) * (60.0 / (self.out.tempo or 120.0))
                match.onset_error = best_dist
                match.is_match = True
                match.match_type = 'exact' if best_dist < 0.02 else 'temporal'
                ref_matched[best_idx] = True
                out_matched[i] = True
            else:
                match.match_type = 'extra'  # note extra (fausse positive)
        
        # Notes de référence non matchées = fausses négatives
        for j, ref_note in enumerate(ref_notes):
            if not ref_matched[j]:
                # Créer un match "miss" pour chaque note manquante
                matches.append(NoteMatch(
                    note_id=f'ref_{j}',
                    pitch=ref_note['pitch'],
                    onset=ref_note.get('beat_position', ref_note.get('measure', 0)) * (60.0 / (self.out.tempo or 120.0)),
                    expected_onset=ref_note.get('beat_position', ref_note.get('measure', 0)) * (60.0 / (self.out.tempo or 120.0)),
                    onset_error=float('inf'),
                    is_match = False,
                    match_type = 'miss',
                ))
        
        matches.extend(self.notes_detail)  # ajouter les matches déjà créés
        return matches
    
    def _compute_f1(self, hand: str) -> Tuple[float, float, float]:
        """Calcule F1, precision, recall pour une main."""
        tp = fp = fn = 0
        
        for match in self.notes_detail:
            is_hand = (
                (hand == 'mg' and match.pitch < 48) or
                (hand == 'md' and match.pitch >= 48) or
                (hand == 'all')
            )
            if not is_hand:
                continue
            
            if match.is_match:
                tp += 1
            elif match.match_type == 'extra':
                fp += 1
            elif match.match_type == 'miss':
                fn += 1
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return f1, precision, recall
    
    def _compute_rhythm_metrics(self, metrics: RegressionMetrics):
        """Calcule les métriques de précision rythmique."""
        errors = []
        for match in self.notes_detail:
            if match.onset_error is not None and match.onset_error != float('inf'):
                errors.append(match.onset_error)
        
        if errors:
            metrics.avg_onset_error = sum(errors) / len(errors)
            metrics.max_onset_error = max(errors)
            metrics.notes_within_50ms = sum(1 for e in errors if e <= 0.05)
            metrics.notes_within_100ms = sum(1 for e in errors if e <= 0.10)
            metrics.total_notes = len(errors)
            metrics.matched_notes = sum(1 for e in errors if e <= self.tolerance_onset)
            metrics.precision_rythme = metrics.matched_notes / metrics.total_notes if metrics.total_notes > 0 else 0.0
            metrics.recall_rythme = metrics.matched_notes / metrics.total_notes if metrics.total_notes > 0 else 0.0
        else:
            metrics.avg_onset_error = float('inf')
            metrics.max_onset_error = float('inf')
    
    def _compute_ornament_metrics(self, metrics: RegressionMetrics):
        """Calcule les métriques d'ornements."""
        ref_ornaments = self.ref.ornaments
        out_ornaments = self.out.ornaments
        
        # Compter par type
        ref_types = {}
        for o in ref_ornaments:
            ref_types.setdefault(o['type'], 0)
            ref_types[o['type']] += 1
        
        out_types = {}
        for o in out_ornaments:
            out_types.setdefault(o['type'], 0)
            out_types[o['type']] += 1
        
        metrics.appoggiaturas_detected = out_types.get('graceNote', 0)
        metrics.appoggiaturas_preserved = sum(
            1 for o in out_ornaments 
            if o['type'] == 'graceNote' and any(
                r['type'] == 'graceNote' and abs(o.get('measure', 0) - r['measure']) <= 1
                for r in ref_ornaments
            )
        )
        
        metrics.trills_detected = out_types.get('trill', 0)
        metrics.trills_preserved = sum(
            1 for o in out_ornaments 
            if o['type'] == 'trill' and any(
                r['type'] == 'trill' and abs(o.get('measure', 0) - r['measure']) <= 1
                for r in ref_ornaments
            )
        )
        
        metrics.ornements_total = len(ref_ornaments)
        preserved = metrics.appoggiaturas_preserved + metrics.trills_preserved
        metrics.ornements_preserves = preserved / len(ref_ornaments) if ref_ornaments else 1.0
        
        # Détail
        for o in ref_ornaments:
            self.ornaments_detail.append(OrnamentMatch(
                ornament_id=f"ref_{o.get('measure', 0)}_{o['type']}",
                type=o['type'],
                position=o.get('measure', 0),
                is_match=any(
                    out['type'] == o['type'] and abs(out.get('measure', 0) - o['measure']) <= 1
                    for out in out_ornaments
                ),
            ))
    
    def _compute_overall_score(self, metrics: RegressionMetrics) -> float:
        """Calcule le score global (moyenne pondérée)."""
        weights = {
            'f1_mg': 0.20,
            'f1_md': 0.20,
            'rythme': 0.25,
            'ornements': 0.15,
            'signature': 0.20,
        }
        
        score = 0.0
        score += metrics.f1_notes_mg * weights['f1_mg']
        score += metrics.f1_notes_md * weights['f1_md']
        score += metrics.precision_rythme * weights['rythme']
        score += metrics.ornements_preserves * weights['ornements']
        score += (1.0 if metrics.signature_detectee else 0.0) * weights['signature']
        
        return round(score, 4)
    
    def _check_thresholds(self, metrics: RegressionMetrics) -> bool:
        """Vérifie si toutes les métriques passent les seuils."""
        thresholds = DEFAULT_THRESHOLDS
        
        checks = [
            ('f1_notes_mg', metrics.f1_notes_mg >= thresholds.get('f1_notes_mg', 0.90)),
            ('f1_notes_md', metrics.f1_notes_md >= thresholds.get('f1_notes_md', 0.90)),
            ('precision_rythme', metrics.precision_rythme >= thresholds.get('precision_rythme', 0.85)),
            ('ornements_preserves', metrics.ornements_preserves >= thresholds.get('ornements_preserves', 0.80)),
            ('signature_detectee', metrics.signature_detectee if metrics.signature_attendue == (3, 4) else True),
        ]
        
        all_passed = all(c for _, c in checks)
        
        if not all_passed:
            failed = [name for name, c in checks if not c]
            metrics.warnings.append(f"Seuils échoués : {', '.join(failed)}")
        
        return all_passed
    
    def _generate_warnings(self, metrics: RegressionMetrics) -> List[str]:
        """Génère les warnings du rapport."""
        warnings = []
        
        if metrics.f1_notes_mg < 0.7:
            warnings.append("F1 main gauche < 70% — attention, la MG est mal transcrite")
        elif metrics.f1_notes_mg < 0.9:
            warnings.append(f"F1 main gauche = {metrics.f1_notes_mg:.2%} — cible ≥ 90%")
        
        if metrics.f1_notes_md < 0.7:
            warnings.append("F1 main droite < 70% — attention")
        elif metrics.f1_notes_md < 0.9:
            warnings.append(f"F1 main droite = {metrics.f1_notes_md:.2%} — cible ≥ 90%")
        
        if metrics.precision_rythme < 0.7:
            warnings.append(f"Précision rythmique = {metrics.precision_rythme:.2%} — critique")
        elif metrics.precision_rythme < 0.85:
            warnings.append(f"Précision rythmique = {metrics.precision_rythme:.2%} — cible ≥ 85%")
        
        if metrics.ornements_preserves < 0.5:
            warnings.append(f"Ornements préservés = {metrics.ornements_preserves:.2%} — critique")
        elif metrics.ornements_preserves < 0.8:
            warnings.append(f"Ornements préservés = {metrics.ornements_preserves:.2%} — cible ≥ 80%")
        
        if not metrics.signature_detectee and metrics.signature_attendue == (3, 4):
            warnings.append("Signature 3/4 non détectée — attendu pour Mazurka")
        
        return warnings


# ── RegressionReport ──────────────────────────────────────────────────────────

class RegressionReport:
    """Formatte et sauvegarde le rapport de régression."""
    
    def __init__(
        self,
        reference_file: str,
        reference_hash: str,
        pipeline_output: Dict[str, Any],
        pipeline_output_hash: str,
        metrics: RegressionMetrics,
        notes_detail: List[NoteMatch],
        ornaments_detail: List[OrnamentMatch],
        thresholds: Dict[str, float] = None,
    ):
        self.report = RegressionReport()
        self.report.timestamp = time.time()
        self.report.run_id = hashlib.md5(f"{self.report.timestamp}_{reference_file}".encode()).hexdigest()[:12]
        self.report.reference_file = reference_file
        self.report.reference_hash = reference_hash
        self.report.pipeline_output = json.dumps(pipeline_output, indent=2)[:5000]  # troncature
        self.report.pipeline_output_hash = pipeline_output_hash
        self.report.metrics = metrics
        self.report.notes_detail = notes_detail
        self.report.ornaments_detail = ornaments_detail
        self.report.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.report.passed = metrics.overall_pass
        self.report.summary = self._generate_summary()
    
    def _generate_summary(self) -> str:
        """Génère un résumé lisible du rapport."""
        m = self.report.metrics
        lines = [
            f"=== RAPPORT RÉGRESSION v5 ===",
            f"Run ID: {self.report.run_id}",
            f"Référence: {self.report.reference_file}",
            f"Score global: {self.report.overall_score:.2%}",
            f"Statut: {'✅ PASS' if self.report.passed else '❌ FAIL'}",
            f"",
            f"--- Métriques F1 Notes ---",
            f"  MG: {m.f1_notes_mg:.2%} (precision={m.precision_notes_mg:.2%}, recall={m.recall_notes_mg:.2%})",
            f"  MD: {m.f1_notes_md:.2%} (precision={m.precision_notes_md:.2%}, recall={m.recall_notes_md:.2%})",
            f"",
            f"--- Métriques Rythmiques ---",
            f"  Précision: {m.precision_rythme:.2%}",
            f"  Erreur moyenne onset: {m.avg_onset_error:.4f}s",
            f"  Erreur max onset: {m.max_onset_error:.4f}s",
            f"  Notes ±50ms: {m.notes_within_50ms}/{m.total_notes}",
            f"  Notes ±100ms: {m.notes_within_100ms}/{m.total_notes}",
            f"",
            f"--- Ornements ---",
            f"  Appoggiatures: {m.appoggiaturas_preserved}/{m.appoggiaturas_detected} préservées",
            f"  Trills: {m.trills_preserved}/{m.trills_detected} préservées",
            f"  Taux ornements: {m.ornements_preserves:.2%}",
            f"",
            f"--- Signature rythmique ---",
            f"  Détectée: {m.signature_detectee}",
            f"  Attendue: {m.signature_attendue[0]}/{m.signature_attendue[1]}",
        ]
        
        if m.warnings:
            lines.append(f"\n--- Warnings ---")
            for w in m.warnings:
                lines.append(f"  ⚠️  {w}")
        
        return '\n'.join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit le rapport en dict sérialisable."""
        return {
            'timestamp': self.report.timestamp,
            'run_id': self.report.run_id,
            'reference_file': self.report.reference_file,
            'reference_hash': self.report.reference_hash,
            'pipeline_output_hash': self.report.pipeline_output_hash,
            'metrics': {
                'f1_notes_mg': self.report.metrics.f1_notes_mg,
                'precision_notes_mg': self.report.metrics.precision_notes_mg,
                'recall_notes_mg': self.report.metrics.recall_notes_mg,
                'f1_notes_md': self.report.metrics.f1_notes_md,
                'precision_notes_md': self.report.metrics.precision_notes_md,
                'recall_notes_md': self.report.metrics.recall_notes_md,
                'precision_rythme': self.report.metrics.precision_rythme,
                'recall_rythme': self.report.metrics.recall_rythme,
                'avg_onset_error': self.report.metrics.avg_onset_error,
                'max_onset_error': self.report.metrics.max_onset_error,
                'notes_within_50ms': self.report.metrics.notes_within_50ms,
                'notes_within_100ms': self.report.metrics.notes_within_100ms,
                'total_notes': self.report.metrics.total_notes,
                'matched_notes': self.report.metrics.matched_notes,
                'appoggiaturas_detected': self.report.metrics.appoggiaturas_detected,
                'appoggiaturas_preserved': self.report.metrics.appoggiaturas_preserved,
                'trills_detected': self.report.metrics.trills_detected,
                'trills_preserved': self.report.metrics.trills_preserved,
                'ornements_preserves': self.report.metrics.ornements_preserves,
                'signature_detectee': self.report.metrics.signature_detectee,
                'signature_attendue': list(self.report.metrics.signature_attendue),
                'overall_score': self.report.metrics.overall_score,
                'overall_pass': self.report.metrics.overall_pass,
                'warnings': self.report.metrics.warnings,
                'errors': self.report.metrics.errors,
            },
            'thresholds': self.report.thresholds,
            'passed': self.report.passed,
            'summary': self.report.summary,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Sérialise le rapport en JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def save(self, filepath: str):
        """Sauvegarde le rapport dans un fichier JSON."""
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json(indent=2))
        print(f"[RegressionReport] Rapport sauvegardé : {filepath}")
    
    def print_summary(self):
        """Affiche le résumé du rapport."""
        print("\n" + "=" * 60)
        print(self.report.summary)
        print("=" * 60 + "\n")


# ── MetricsHistory (JSON file-based) ──────────────────────────────────────────

class MetricsHistory:
    """
    Historisation des métriques de régression.
    
    Par défaut : fichier JSON local.
    Optionnel : MongoDB via pymongo.
    """
    
    def __init__(
        self,
        json_path: str = None,
        mongo_uri: str = None,
        mongo_db: str = 'regression_metrics',
        mongo_collection: str = 'history',
    ):
        self.json_path = json_path or DEFAULT_METRICS_FILE
        self.mongo_uri = mongo_uri
        self.mongo_db = mongo_db
        self.mongo_collection = mongo_collection
        self._mongo_client = None
    
    def load_history(self) -> List[Dict[str, Any]]:
        """Charge l'historique existant depuis le fichier JSON."""
        if not os.path.exists(self.json_path):
            return []
        
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
        except (json.JSONDecodeError, IOError) as e:
            print(f"[MetricsHistory] Erreur lecture JSON : {e}")
        
        return []
    
    def save_report(self, report: RegressionReport):
        """Sauvegarde un rapport dans l'historique."""
        # Sauvegarde JSON
        history = self.load_history()
        history.append(report.to_dict())
        
        # Garder les 100 derniers rapports
        history = history[-100:]
        
        os.makedirs(os.path.dirname(self.json_path) if os.path.dirname(self.json_path) else '.', exist_ok=True)
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        
        print(f"[MetricsHistory] Rapport sauvegardé dans {self.json_path} ({len(history)} rapports)")
        
        # Sauvegarde MongoDB si configurée
        if self.mongo_uri:
            self._save_to_mongo(report)
    
    def _save_to_mongo(self, report: RegressionReport):
        """Sauvegarde dans MongoDB (si disponible)."""
        try:
            import pymongo
            if self._mongo_client is None:
                self._mongo_client = pymongo.MongoClient(self.mongo_uri)
            
            db = self._mongo_client[self.mongo_db]
            collection = db[self.mongo_collection]
            
            report_data = report.to_dict()
            report_data['_id'] = report.report.run_id  # utiliser run_id comme _id
            collection.replace_one({'_id': report.report.run_id}, report_data, upsert=True)
            
            print(f"[MetricsHistory] Rapport sauvegardé dans MongoDB ({self.mongo_db}.{self.mongo_collection})")
        except ImportError:
            print("[MetricsHistory] pymongo non installé — MongoDB ignoré")
        except Exception as e:
            print(f"[MetricsHistory] Erreur MongoDB : {e}")
    
    def get_latest(self, n: int = 10) -> List[Dict[str, Any]]:
        """Retourne les N derniers rapports."""
        history = self.load_history()
        return history[-n:] if history else []
    
    def get_trend(self, metric: str = 'overall_score') -> List[Dict[str, Any]]:
        """Retourne la tendance d'une métrique."""
        history = self.load_history()
        return [
            {
                'run_id': h.get('run_id', ''),
                'timestamp': h.get('timestamp', 0),
                'value': h.get('metrics', {}).get(metric, 0),
                'passed': h.get('passed', False),
            }
            for h in history
        ]


# ── MongoDB Storage (optionnel) ───────────────────────────────────────────────

class MetricsMongoStore:
    """
    Stockage des métriques dans MongoDB.
    
    Utilisé si pymongo est installé et mongo_uri est configuré.
    """
    
    def __init__(
        self,
        uri: str = 'mongodb://localhost:27017',
        db_name: str = 'regression_metrics',
        collection_name: str = 'history',
    ):
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        self._connect()
    
    def _connect(self):
        """Connecte à MongoDB."""
        try:
            import pymongo
            self._client = pymongo.MongoClient(self.uri)
            db = self._client[self.db_name]
            self._collection = db[self.collection_name]
            print(f"[MetricsMongoStore] Connecté à MongoDB : {self.db_name}.{self.collection_name}")
        except ImportError:
            print("[MetricsMongoStore] pymongo non installé — MongoDB désactivé")
        except Exception as e:
            print(f"[MetricsMongoStore] Erreur connexion MongoDB : {e}")
    
    def save_report(self, report: RegressionReport):
        """Sauvegarde un rapport."""
        if self._collection is None:
            return
        
        data = report.to_dict()
        data['_id'] = report.report.run_id
        self._collection.replace_one({'_id': report.report.run_id}, data, upsert=True)
        print(f"[MetricsMongoStore] Rapport sauvegardé : {report.report.run_id}")
    
    def get_latest(self, n: int = 10) -> List[Dict[str, Any]]:
        """Retourne les N derniers rapports."""
        if self._collection is None:
            return []
        
        return list(self._collection.find().sort('timestamp', -1).limit(n))
    
    def close(self):
        """Ferme la connexion."""
        if self._client:
            self._client.close()


# ── Point d'entrée principal ──────────────────────────────────────────────────

def run_regression(
    reference_path: str,
    pipeline_output: Dict[str, Any],
    tolerance_onset: float = 0.05,
    tolerance_pitch: int = 1,
    thresholds: Dict[str, float] = None,
    metrics_history_path: str = None,
    mongo_uri: str = None,
    save_report: bool = True,
    output_dir: str = None,
) -> RegressionReport:
    """
    Exécute le harnais de régression complet.
    
    Args:
        reference_path: Chemin vers le MusicXML référence
        pipeline_output: Dict score_data du pipeline
        tolerance_onset: Tolérance onset en secondes (défaut 50ms)
        tolerance_pitch: Tolérance pitch en demi-tons (défaut ±1)
        thresholds: Seuils personnalisés
        metrics_history_path: Chemin fichier historique JSON
        mongo_uri: URI MongoDB (optionnel)
        save_report: Sauvegarder le rapport
        output_dir: Répertoire de sortie pour le rapport
        
    Returns:
        RegressionReport complet
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS
    
    # 1. Charger la référence
    print(f"[Regression] Chargement référence : {reference_path}")
    reference = ReferenceStore(reference_path)
    ref_hash = reference.file_hash()
    print(f"[Regression] {len(reference.notes)} notes, {len(reference.ornaments)} ornements, signature {reference.time_signature}")
    
    # 2. Parser la sortie du pipeline
    print(f"[Regression] Parsing sortie pipeline...")
    output = PipelineOutputParser(pipeline_output)
    out_hash = output.file_hash()
    print(f"[Regression] {len(output.notes)} notes, {len(output.ornaments)} ornements, signature {output.time_signature}")
    
    # 3. Calculer les métriques
    print(f"[Regression] Calcul des métriques...")
    calculator = MetricCalculator(
        reference=reference,
        output=output,
        tolerance_onset=tolerance_onset,
        tolerance_pitch=tolerance_pitch,
    )
    metrics = calculator.calculate_all()
    
    # 4. Créer le rapport
    report = RegressionReport(
        reference_file=reference_path,
        reference_hash=ref_hash,
        pipeline_output=pipeline_output,
        pipeline_output_hash=out_hash,
        metrics=metrics,
        notes_detail=calculator.notes_detail,
        ornaments_detail=calculator.ornaments_detail,
        thresholds=thresholds,
    )
    
    # 5. Sauvegarder
    if save_report:
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            report_path = os.path.join(output_dir, 'regression_report.json')
        else:
            report_path = metrics_history_path or DEFAULT_METRICS_FILE
        
        report.save(report_path)
        
        # Sauvegarder dans l'historique
        history = MetricsHistory(
            json_path=metrics_history_path,
            mongo_uri=mongo_uri,
        )
        history.save_report(report)
    
    # 6. Afficher le résumé
    report.print_summary()
    
    return report


def main():
    """Point d'entrée CLI."""
    parser = argparse.ArgumentParser(
        description='Harnais de validation régression V5 (Phase 7)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  # Comparer une sortie pipeline contre la référence
  python regression_harness.py --reference references/mazurka.musicxml --output output_dir

  # Avec fichier d'historique personnalisé
  python regression_harness.py --reference references/mazurka.musicxml --metrics my_metrics.json

  # Avec MongoDB
  python regression_harness.py --reference references/mazurka.musicxml --mongo-uri mongodb://localhost:27017
        """,
    )
    
    parser.add_argument(
        '--reference', '-r',
        required=True,
        help='Chemin vers le MusicXML référence (ex: references/mazurka_op68_no3.musicxml)'
    )
    parser.add_argument(
        '--output', '-o',
        help='Répertoire de sortie pour le rapport'
    )
    parser.add_argument(
        '--metrics', '-m',
        default=DEFAULT_METRICS_FILE,
        help='Chemin fichier historique JSON (défaut: metrics_history.json)'
    )
    parser.add_argument(
        '--pipeline-output', '-p',
        help='Chemin vers le JSON de sortie du pipeline (score_data)'
    )
    parser.add_argument(
        '--tolerance-onset', '-t',
        type=float,
        default=0.05,
        help='Tolérance onset en secondes (défaut: 0.05s = 50ms)'
    )
    parser.add_argument(
        '--tolerance-pitch', '-P',
        type=int,
        default=1,
        help='Tolérance pitch en demi-tons (défaut: 1)'
    )
    parser.add_argument(
        '--mongo-uri',
        help='URI MongoDB pour l\'historisation (optionnel)'
    )
    parser.add_argument(
        '--json-only',
        action='store_true',
        help='Ne pas afficher le résumé console'
    )
    parser.add_argument(
        '--history',
        action='store_true',
        help='Afficher l\'historique des métriques'
    )
    
    args = parser.parse_args()
    
    # Mode historique
    if args.history:
        history = MetricsHistory(json_path=args.metrics)
        latest = history.get_latest(10)
        if latest:
            print(f"\n=== Historique des {len(latest)} derniers rapports ===")
            for h in latest:
                status = '✅' if h.get('passed', False) else '❌'
                score = h.get('metrics', {}).get('overall_score', 0)
                print(f"  {status} {h.get('run_id', 'N/A')} — score={score:.2%} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(h.get('timestamp', 0)))}")
        else:
            print("Aucun rapport dans l'historique.")
        return
    
    # Vérifier que le pipeline output est fourni ou lu depuis output_dir
    pipeline_output = None
    if args.pipeline_output:
        with open(args.pipeline_output, 'r', encoding='utf-8') as f:
            pipeline_output = json.load(f)
    elif args.output:
        # Chercher score_data.json dans output_dir
        possible_paths = [
            os.path.join(args.output, 'score_data.json'),
            os.path.join(args.output, 'output', 'score_data.json'),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    pipeline_output = json.load(f)
                print(f"[Regression] Pipeline output chargé depuis : {path}")
                break
    
    if pipeline_output is None:
        print("[Regression] ⚠️  Aucun pipeline output trouvé. Utilisation d'un score_data vide.")
        pipeline_output = {
            'tempo': 120,
            'timeSignature': [3, 4],
            'keySignature': 'A',
            'totalMeasures': 0,
            'measures': [],
            'ornaments': {'appoggiaturas': [], 'trills': [], 'dottedRhythms': []},
        }
    
    # Exécuter la régression
    report = run_regression(
        reference_path=args.reference,
        pipeline_output=pipeline_output,
        tolerance_onset=args.tolerance_onset,
        tolerance_pitch=args.tolerance_pitch,
        thresholds=DEFAULT_THRESHOLDS,
        metrics_history_path=args.metrics,
        mongo_uri=args.mongo_uri,
        save_report=not args.json_only,
        output_dir=args.output,
    )
    
    # Retourner un code d'exit basé sur le statut
    sys.exit(0 if report.report.passed else 1)


if __name__ == '__main__':
    main()