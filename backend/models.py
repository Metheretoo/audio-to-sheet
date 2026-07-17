"""
models.py — Modèles Pydantic pour validation des options pipeline (Phase 1.8)

Validation typée des paramètres de transcription avant passage au pipeline.
"""
import sys
import os
import logging
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from copy import deepcopy

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Types littéraux
# ─────────────────────────────────────────────────────────────────────────────

TranscriberType = Literal[
    'piano_transcription',
    'basic_pitch',
    'transkun',
    'hft',
    'mt3',
    'ensemble',
]

QuantizationLevel = Literal[
    'none',
    'light',
    'standard',
    'heavy',
    'rubato',
    'triplets',
]

PresetType = Literal[
    'rapide',
    'equilibre',
    'classique',
    'studio',
    'jazz',
    'standard',
]


# ─────────────────────────────────────────────────────────────────────────────
# [P4] Seuils d'ornements configurables
# ─────────────────────────────────────────────────────────────────────────────

class OrnamentThresholds(BaseModel):
    """Seuils de détection d'ornements (Phase 4)."""
    # Appoggiature : note courte juste avant un temps fort
    appoggiatura_max_duration_beats: float = Field(
        default=0.25,
        gt=0.01,
        le=1.0,
        description='Durée max d\'une appoggiature en beats (0.01-1.0)',
    )
    appoggiatura_max_interval_beats: float = Field(
        default=0.5,
        gt=0.01,
        le=2.0,
        description='Interval max avant temps fort pour appoggiature en beats',
    )
    # Trille : alternance rapide de 2 hauteurs
    trill_min_notes: int = Field(
        default=3,
        ge=2,
        le=10,
        description='Nombre min de notes pour détecter un trille',
    )
    trill_max_note_duration_beats: float = Field(
        default=0.25,
        gt=0.01,
        le=1.0,
        description='Durée max d\'une note de trille en beats',
    )
    trill_pitch_interval_min: int = Field(
        default=1,
        ge=1,
        le=4,
        description='Interval de demi-tons minimum pour un trille',
    )
    # Rythmes pointés
    dotted_rhythm_tolerance_beats: float = Field(
        default=0.1,
        gt=0.01,
        le=0.5,
        description='Tolérance pour détecter un rythme pointé en beats',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Options de transcription
# ─────────────────────────────────────────────────────────────────────────────

class TranscriptionOptions(BaseModel):
    """Validation Pydantic des options du pipeline de transcription."""

    # ── Modèles ──────────────────────────────────────────────────────────
    transcriber: TranscriberType = Field(
        default='piano_transcription',
        description='Modèle de transcription à utiliser',
    )
    preset: PresetType = Field(
        default='standard',
        description='Preset de configuration',
    )

    # ── Seuils ───────────────────────────────────────────────────────────
    onset_threshold: float = Field(
        default=0.5,
        ge=0.01,
        le=1.0,
        description='Seuil de détection d\'onset (0.01-1.0)',
    )
    frame_threshold: float = Field(
        default=0.1,
        ge=0.01,
        le=1.0,
        description='Seuil de détection de frame (0.01-1.0)',
    )
    offset_threshold: float = Field(
        default=0.3,
        ge=0.01,
        le=1.0,
        description='Seuil de détection d\'offset (0.01-1.0)',
    )

    # ── Démucs ───────────────────────────────────────────────────────────
    use_demucs: bool = Field(
        default=False,
        description='Activer la séparation Demucs',
    )

    # ── Notes courtes ────────────────────────────────────────────────────
    remove_short_notes: bool = Field(
        default=False,
        description='Filtrer les notes trop courtes',
    )
    minimum_note_duration: int = Field(
        default=50,
        ge=10,
        le=500,
        description='Durée minimale d\'une note en ms (10-500)',
    )

    # ── Fusion de notes ──────────────────────────────────────────────────
    merge_near_notes: bool = Field(
        default=False,
        description='Fusionner les notes proches',
    )
    merge_gap_ms: int = Field(
        default=30,
        ge=5,
        le=200,
        description='Écart maximal pour fusion en ms (5-200)',
    )

    # ── Partition ────────────────────────────────────────────────────────
    time_sig: str = Field(
        default='4/4',
        pattern=r'^\d+/\d+$',
        description='Signature rythmique (ex: 4/4, 3/4)',
    )
    key_sig: str = Field(
        default='C',
        description='Tonalité (ex: C, G, F#, Am)',
    )
    tempo: Optional[float] = Field(
        default=None,
        gt=20,
        lt=300,
        description='Tempo fixe en BPM (20-300)',
    )

    # ── Détections ───────────────────────────────────────────────────────
    detect_tempo: bool = Field(
        default=True,
        description='Détecter le tempo automatiquement',
    )
    detect_meter: bool = Field(
        default=True,
        description='Détecter la mesure automatiquement',
    )
    detect_key: bool = Field(
        default=True,
        description='Détecter la tonalité automatiquement',
    )

    # ── Quantification ───────────────────────────────────────────────────
    quantization_level: QuantizationLevel = Field(
        default='standard',
        description='Niveau de quantification rythmique',
    )

    # ── Séparation mains ─────────────────────────────────────────────────
    split_hands: bool = Field(
        default=False,
        description='Séparer les mains (treble/bass)',
    )

    # ── Ornaments (Phase 4) ────────────────────────────────────────────
    enable_rubato: bool = Field(
        default=False,
        description='Activer le support rubato',
    )
    enable_triplets: bool = Field(
        default=False,
        description='Activer les triolets',
    )

    # Seuils d'ornements configurables (P4.1)
    ornament_thresholds: OrnamentThresholds = Field(
        default_factory=OrnamentThresholds,
        description='Seuils de détection d\'ornements',
    )

    # Détection explicite des ornements (P4.2 + P4.3)
    detect_appoggiaturas: bool = Field(
        default=True,
        description='Détecter les appoggiatures comme grace notes',
    )
    detect_trills: bool = Field(
        default=True,
        description='Détecter les trilles comme symboles tr',
    )

    # ── Mode strict ──────────────────────────────────────────────────────
    strict_mode: bool = Field(
        default=False,
        description='Mode strict : arrêter sur erreur critique',
    )

    # ── Validations ──────────────────────────────────────────────────────

    @field_validator('time_sig')
    @classmethod
    def validate_time_sig(cls, v: str) -> str:
        """Vérifier que la signature rythmique est valide."""
        try:
            num, den = v.split('/')
            num, den = int(num), int(den)
            if num not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                raise ValueError
            if den not in (1, 2, 4, 8):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError('Signature rythmique invalide. Format: numérateur/dénominateur (ex: 4/4, 3/8)')
        return v

    @field_validator('onset_threshold', 'frame_threshold', 'offset_threshold')
    @classmethod
    def clamp_threshold(cls, v: float) -> float:
        """Assurer que les seuils sont dans la plage valide."""
        return max(0.01, min(1.0, v))

    @model_validator(mode='after')
    def validate_consistency(self):
        """Vérifier la cohérence entre les options."""
        if self.detect_tempo and self.tempo:
            logger.warning(
                "[TranscriptionOptions] detect_tempo=True ET tempo fixé — "
                "le tempo fixe sera prioritaire."
            )
        if self.preset == 'rapide' and self.transcriber == 'piano_transcription':
            logger.warning(
                "[TranscriptionOptions] Preset 'rapide' avec transcriber piano_transcription — "
                "considéré comme volontaire."
            )
        return self

    # ── Méthodes utilitaires ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Convertir en dictionnaire pour le pipeline."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> 'TranscriptionOptions':
        """Créer depuis un dictionnaire (validation implicite)."""
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields()})

    def summary(self) -> str:
        """Retourner un résumé lisible des options."""
        lines = [
            f"transcriber={self.transcriber}",
            f"preset={self.preset}",
            f"onset={self.onset_threshold:.3f} frame={self.frame_threshold:.3f} offset={self.offset_threshold:.3f}",
            f"quantization={self.quantization_level}",
            f"detect=[tempo={self.detect_tempo} meter={self.detect_meter} key={self.detect_key}]",
        ]
        if self.tempo:
            lines.append(f"tempo={self.tempo:.1f}")
        if self.use_demucs:
            lines.append("demucs=enabled")
        if self.split_hands:
            lines.append("split_hands=enabled")
        if self.detect_appoggiaturas:
            lines.append("appoggiaturas=enabled")
        if self.detect_trills:
            lines.append("trills=enabled")
        return ', '.join(lines)

    def __str__(self):
        return f"TranscriptionOptions({self.summary()})"


# ─────────────────────────────────────────────────────────────────────────────
# Validation factory (wrapper pour le caller)
# ─────────────────────────────────────────────────────────────────────────────

def validate_options(data: dict) -> tuple[TranscriptionOptions | None, list[str]]:
    """
    Valider les options de transcription.

    Returns:
        (options, errors) — options=None si erreurs, errors=[] si OK
    """
    errors = []
    try:
        options = TranscriptionOptions.model_validate(data)
        return options, []
    except Exception as e:
        # Extraire les erreurs Pydantic
        if hasattr(e, 'errors'):
            for err in e.errors():
                field = ' → '.join(str(loc) for loc in err.get('loc', []))
                msg = err.get('msg', str(err.get('ctx', {})))
                errors.append(f"  • {field}: {msg}")
        else:
            errors.append(f"  • {str(e)}")
        return None, errors


# ─────────────────────────────────────────────────────────────────────────────
# [P4] Présets prédéfinis avec ornements
# ─────────────────────────────────────────────────────────────────────────────

# Valeurs par défaut des ornements (utilisées par les presets)
_DEFAULT_ORNAMENT_THRESHOLDS = {
    'appoggiatura_max_duration_beats': 0.25,
    'appoggiatura_max_interval_beats': 0.5,
    'trill_min_notes': 3,
    'trill_max_note_duration_beats': 0.25,
    'trill_pitch_interval_min': 1,
    'dotted_rhythm_tolerance_beats': 0.1,
}

PRESET_VALUES: dict[str, dict] = {
    'rapide': {
        'transcriber': 'basic_pitch',
        'onset_threshold': 0.5,
        'frame_threshold': 0.1,
        'offset_threshold': 0.3,
        'quantization_level': 'light',
        'use_demucs': False,
        'remove_short_notes': False,
        'minimum_note_duration': 50,
        'merge_near_notes': False,
        'merge_gap_ms': 30,
        'split_hands': False,
        'detect_tempo': False,
        'detect_meter': True,
        'detect_key': False,
        'enable_rubato': False,
        'enable_triplets': False,
        'detect_appoggiaturas': False,
        'detect_trills': False,
        'ornament_thresholds': _DEFAULT_ORNAMENT_THRESHOLDS,
        'strict_mode': False,
    },
    'equilibre': {
        'transcriber': 'piano_transcription',
        'onset_threshold': 0.5,
        'frame_threshold': 0.1,
        'offset_threshold': 0.3,
        'quantization_level': 'standard',
        'use_demucs': False,
        'remove_short_notes': False,
        'minimum_note_duration': 20,
        'merge_near_notes': False,
        'merge_gap_ms': 10,
        'split_hands': True,
        'detect_tempo': True,
        'detect_meter': True,
        'detect_key': True,
        'enable_rubato': False,
        'enable_triplets': False,
        'detect_appoggiaturas': True,
        'detect_trills': True,
        'ornament_thresholds': _DEFAULT_ORNAMENT_THRESHOLDS,
        'strict_mode': False,
    },
    'classique': {
        'transcriber': 'piano_transcription',
        'onset_threshold': 1.0,
        'frame_threshold': 0.1,
        'offset_threshold': 0.3,
        'quantization_level': 'standard',
        'use_demucs': False,
        'remove_short_notes': False,
        'minimum_note_duration': 50,
        'merge_near_notes': False,
        'merge_gap_ms': 30,
        'split_hands': True,
        'detect_tempo': True,
        'detect_meter': True,
        'detect_key': True,
        'enable_rubato': True,
        'enable_triplets': True,
        'detect_appoggiaturas': True,
        'detect_trills': True,
        # Seuils adaptés au Classique (ornements plus sensibles)
        'ornament_thresholds': {
            'appoggiatura_max_duration_beats': 0.17,
            'appoggiatura_max_interval_beats': 0.5,
            'trill_min_notes': 3,
            'trill_max_note_duration_beats': 0.17,
            'trill_pitch_interval_min': 1,
            'dotted_rhythm_tolerance_beats': 0.08,
        },
        'strict_mode': False,
    },
    'studio': {
        'transcriber': 'piano_transcription',
        'onset_threshold': 0.5,
        'frame_threshold': 0.1,
        'offset_threshold': 0.3,
        'quantization_level': 'standard',
        'use_demucs': True,
        'remove_short_notes': False,
        'minimum_note_duration': 20,
        'merge_near_notes': False,
        'merge_gap_ms': 10,
        'split_hands': True,
        'detect_tempo': True,
        'detect_meter': True,
        'detect_key': True,
        'enable_rubato': True,
        'enable_triplets': True,
        'detect_appoggiaturas': True,
        'detect_trills': True,
        'ornament_thresholds': _DEFAULT_ORNAMENT_THRESHOLDS,
        'strict_mode': False,
    },
    'jazz': {
        'transcriber': 'piano_transcription',
        'onset_threshold': 0.5,
        'frame_threshold': 0.1,
        'offset_threshold': 0.3,
        'quantization_level': 'heavy',
        'use_demucs': False,
        'remove_short_notes': False,
        'minimum_note_duration': 20,
        'merge_near_notes': False,
        'merge_gap_ms': 10,
        'split_hands': True,
        'detect_tempo': True,
        'detect_meter': True,
        'detect_key': True,
        'enable_rubato': False,
        'enable_triplets': False,
        'detect_appoggiaturas': True,
        'detect_trills': False,
        # Le jazz utilise beaucoup de rythmes pointés
        'ornament_thresholds': {
            'appoggiatura_max_duration_beats': 0.33,
            'appoggiatura_max_interval_beats': 0.5,
            'trill_min_notes': 4,
            'trill_max_note_duration_beats': 0.33,
            'trill_pitch_interval_min': 2,
            'dotted_rhythm_tolerance_beats': 0.05,
        },
        'strict_mode': False,
    },
}


def apply_preset(preset_name: str) -> dict:
    """Récupérer les valeurs d'un preset (copie profonde pour mutation safe)."""
    values = PRESET_VALUES.get(preset_name)
    if not values:
        raise ValueError(f"Preset inconnu: {preset_name}. Presets disponibles: {', '.join(PRESET_VALUES.keys())}")
    return deepcopy(values)


# [P4] Helpers pour sérialiser/désérialiser les ornements
def _dict_to_ornament_thresholds(thresholds_dict: dict) -> OrnamentThresholds:
    """Convertir un dict en OrnamentThresholds."""
    if thresholds_dict is None:
        return OrnamentThresholds()
    # Filtrer les champs non pertinents
    valid_keys = OrnamentThresholds.model_fields.keys()
    filtered = {k: v for k, v in thresholds_dict.items() if k in valid_keys}
    return OrnamentThresholds(**filtered)


def _ornament_thresholds_to_dict(thresholds: OrnamentThresholds) -> dict:
    """Convertir OrnamentThresholds en dict."""
    return thresholds.model_dump()