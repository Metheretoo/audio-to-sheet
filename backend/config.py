"""
AudioScore — Configuration centralisée avec validation Pydantic
Charge config.yaml et expose des settings typés pour tout le backend.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from functools import lru_cache

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ─────────────────────────────────────────────────────────────────────────────
# Modèles de configuration par section
# ─────────────────────────────────────────────────────────────────────────────

class TranscriberModelConfig(BaseModel):
    model_path: str
    model_type: Literal["onnx", "pytorch"] = "onnx"
    onset_threshold: float = Field(ge=0.0, le=1.0, default=0.3)
    frame_threshold: float = Field(ge=0.0, le=1.0, default=0.3)
    minimum_note_length: float = Field(gt=0, default=50.0)
    # Paramètres spécifiques par modèle
    multiple_pitch_bends: bool = False
    melodia_trick: bool = True
    hq_mode: bool = False


class EnsembleModelWeight(BaseModel):
    """Poids d'un modèle dans l'ensemble"""
    name: str
    weight: float = 1.0
    onset_weight: float = 1.0
    pitch_weight: float = 1.0
    duration_weight: float = 1.0


class EnsembleConfig(BaseModel):
    """Configuration de l'ensemble voting"""
    enabled: bool = False
    models: list[EnsembleModelWeight] = Field(default_factory=list)
    onset_tolerance: float = Field(ge=0.0, le=1.0, default=0.05)
    pitch_tolerance: int = Field(ge=0, le=12, default=1)
    min_votes: int = Field(ge=1, le=10, default=2)
    velocity_aggregation: Literal["max", "mean", "weighted_mean"] = "weighted_mean"
    duration_aggregation: Literal["median", "mean", "weighted_mean"] = "median"


class TranscriberConfig(BaseModel):
    default: Literal["basic_pitch", "piano_transcription", "transkun", "hft", "ensemble"] = "piano_transcription"
    models: dict[str, TranscriberModelConfig] = Field(default_factory=dict)
    ensemble: EnsembleConfig = Field(default_factory=EnsembleConfig)

    @model_validator(mode="after")
    def validate_default_exists(self) -> "TranscriberConfig":
        if self.default not in self.models and self.default != "ensemble":
            raise ValueError(f"Modèle par défaut '{self.default}' non défini dans models")
        return self


class DemucsConfig(BaseModel):
    enabled: bool = True
    model: Literal["htdemucs", "htdemucs_ft", "mdx_extra"] = "htdemucs"
    device: Literal["auto", "cuda", "mps", "cpu"] = "auto"
    shifts: int = Field(ge=0, le=10, default=1)
    overlap: float = Field(ge=0.0, le=0.5, default=0.25)
    segment_length: float = Field(gt=0, default=7.8)
    two_stems: Literal["piano", "vocals", "drums", "bass", "other"] = "piano"


class QuantizationLevelConfig(BaseModel):
    grid_resolution: float = Field(gt=0, default=0.25)
    ioi_tolerance: float = Field(ge=0.0, le=1.0, default=0.15)
    swing_ratio: float = Field(gt=0, default=1.0)
    detect_tuples: bool = False
    # Paramètres avancés
    adaptive_tempo: bool = False
    tuple_types: list[Literal["triplet", "quadruplet"]] = Field(default_factory=list)


class QuantizationConfig(BaseModel):
    default: Literal["none", "light", "standard", "heavy", "rubato", "triplets"] = "standard"
    levels: dict[str, QuantizationLevelConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_default_exists(self) -> "QuantizationConfig":
        if self.default not in self.levels:
            raise ValueError(f"Niveau de quantification par défaut '{self.default}' non défini")
        return self


class DynamicHandSplitConfig(BaseModel):
    analyze_range: int = Field(ge=12, le=48, default=24)
    hand_overlap: int = Field(ge=0, le=12, default=2)
    density_weight: float = Field(ge=0.0, le=1.0, default=0.6)


class MLHandSplitConfig(BaseModel):
    model_path: str = "models/hand_split.onnx"
    confidence_threshold: float = Field(ge=0.0, le=1.0, default=0.6)
    fallback: Literal["fixed", "dynamic"] = "dynamic"


class HandSplitConfig(BaseModel):
    method: Literal["fixed", "dynamic", "ml"] = "dynamic"
    fixed_split_point: int = Field(ge=0, le=127, default=57)
    dynamic: DynamicHandSplitConfig = Field(default_factory=DynamicHandSplitConfig)
    ml: MLHandSplitConfig = Field(default_factory=MLHandSplitConfig)


class TempoDetectorConfig(BaseModel):
    detector: Literal["librosa", "madmom", "beatnet"] = "librosa"
    min_bpm: int = Field(ge=20, le=300, default=40)
    max_bpm: int = Field(ge=20, le=300, default=220)
    default_bpm: int = Field(ge=20, le=300, default=120)
    madmom: dict[str, Any] = Field(default_factory=dict)
    beatnet: dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_bpm")
    @classmethod
    def max_gt_min(cls, v: int, info) -> int:
        if "min_bpm" in info.data and v <= info.data["min_bpm"]:
            raise ValueError("max_bpm doit être > min_bpm")
        return v


class KeyDetectorConfig(BaseModel):
    detector: Literal["krumhansl", "keyfinder", "madmom"] = "krumhansl"
    krumhansl: dict[str, Any] = Field(default_factory=dict)


class PedalConfig(BaseModel):
    enabled: bool = True
    onset_threshold: float = Field(ge=0.0, le=1.0, default=0.3)
    release_threshold: float = Field(ge=0.0, le=1.0, default=0.2)
    min_pedal_duration: float = Field(ge=0.0, default=0.1)


class OrnamentsConfig(BaseModel):
    enabled: bool = True
    grace_note_max_duration: float = Field(gt=0, default=0.15)
    trill_min_speed: float = Field(gt=0, default=8.0)
    mordent_max_duration: float = Field(gt=0, default=0.2)


class ScoreConfig(BaseModel):
    preset: Literal["standard", "jazz", "classical"] = "standard"
    detect_dynamics: bool = True
    detect_pedal: bool = True
    suggest_fingerings: bool = False
    write_chord_symbols: bool = False
    key_detection: Literal["krumhansl", "temperley", "manual"] = "krumhansl"
    manual_key: str | None = None


class DeviceConfig(BaseModel):
    preference: Literal["auto", "cuda", "mps", "cpu"] = "auto"
    cpu_threads: int = Field(ge=0, default=0)
    gpu_memory_fraction: float = Field(gt=0.0, le=1.0, default=0.85)
    allow_fallback: bool = True
    batch_size: dict[str, int] = Field(default_factory=lambda: {"auto": True, "cpu": 1, "cuda": 4, "mps": 2})


class ModelCacheConfig(BaseModel):
    enabled: bool = True
    max_models_in_memory: int = Field(ge=1, le=10, default=3)
    preload_on_startup: list[str] = Field(default_factory=list)
    lazy_load: bool = True
    cache_dir: str = "models/.cache"


class PipelineStageConfig(BaseModel):
    name: str
    weight: int = Field(gt=0, default=10)
    description: str = ""
    optional: bool = False


class PipelineConfig(BaseModel):
    stages: list[PipelineStageConfig] = Field(default_factory=list)
    progress_update_interval: float = Field(gt=0, default=0.1)
    timeout_per_stage: int = Field(gt=0, default=300)

    @property
    def total_weight(self) -> int:
        return sum(s.weight for s in self.stages)


class ExportConfig(BaseModel):
    formats: list[Literal["pdf", "midi", "musicxml"]] = Field(default_factory=lambda: ["pdf", "midi", "musicxml"])
    pdf: dict[str, Any] = Field(default_factory=lambda: {"page_size": "A4", "margin_mm": 12, "title": "AudioScore — Partition Piano"})
    midi: dict[str, Any] = Field(default_factory=lambda: {"ticks_per_beat": 480, "include_pedal": True})
    musicxml: dict[str, Any] = Field(default_factory=lambda: {"use_music21": True, "validate_xsd": True, "version": "4.0"})


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535, default=5000)
    debug: bool = False
    max_content_length: int = Field(gt=0, default=100 * 1024 * 1024)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:5000"])
    sse_heartbeat_interval: int = Field(gt=0, default=15)


class FrontendConfig(BaseModel):
    default_language: str = "fr"
    supported_languages: list[str] = Field(default_factory=lambda: ["fr", "en", "es", "de", "ja", "zh"])
    theme: Literal["light", "dark", "auto"] = "auto"
    practice_mode: dict[str, Any] = Field(default_factory=lambda: {
        "default_tempo_range": [50, 100],
        "metronome_volume": 0.3,
        "loop_crossfade": 0.1
    })


# ─────────────────────────────────────────────────────────────────────────────
# Configuration racine
# ─────────────────────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    transcriber: TranscriberConfig = Field(default_factory=TranscriberConfig)
    demucs: DemucsConfig = Field(default_factory=DemucsConfig)
    quantization: QuantizationConfig = Field(default_factory=QuantizationConfig)
    hand_split: HandSplitConfig = Field(default_factory=HandSplitConfig)
    tempo: TempoDetectorConfig = Field(default_factory=TempoDetectorConfig)
    key: KeyDetectorConfig = Field(default_factory=KeyDetectorConfig)
    pedal: PedalConfig = Field(default_factory=PedalConfig)
    ornaments: OrnamentsConfig = Field(default_factory=OrnamentsConfig)
    score: ScoreConfig = Field(default_factory=ScoreConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    model_cache: ModelCacheConfig = Field(default_factory=ModelCacheConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    frontend: FrontendConfig = Field(default_factory=FrontendConfig)

    # Chemins résolus (non dans YAML)
    project_root: Path = Field(exclude=True, default_factory=lambda: Path(__file__).parent.parent)
    models_dir: Path = Field(exclude=True, default_factory=lambda: Path(__file__).parent.parent / "models")
    uploads_dir: Path = Field(exclude=True, default_factory=lambda: Path(__file__).parent.parent / "uploads")
    outputs_dir: Path = Field(exclude=True, default_factory=lambda: Path(__file__).parent.parent / "outputs")

    def resolve_model_path(self, relative_path: str) -> Path:
        """Résout un chemin relatif vers le dossier models/"""
        return (self.models_dir / relative_path).resolve()

    def ensure_dirs(self) -> None:
        """Crée les dossiers nécessaires s'ils n'existent pas"""
        for d in [self.models_dir, self.uploads_dir, self.outputs_dir, self.models_dir / ".cache"]:
            d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Chargement & singleton
# ─────────────────────────────────────────────────────────────────────────────

_config_instance: AppConfig | None = None


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Charge la configuration depuis config.yaml + variables d'environnement"""
    global _config_instance

    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Fichier de configuration introuvable: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f) or {}

    # Surcharge par variables d'environnement (prefix AUDIOSCORE_)
    env_overrides = _load_env_overrides()
    yaml_data = _deep_merge(yaml_data, env_overrides)

    _config_instance = AppConfig(**yaml_data)
    _config_instance.ensure_dirs()
    return _config_instance


def _load_env_overrides() -> dict[str, Any]:
    """Charge les overrides depuis variables d'environnement AUDIOSCORE_*"""
    overrides = {}
    prefix = "AUDIOSCORE_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            # AUDIOSCORE_TRANSCRIBER_DEFAULT -> transcriber.default
            config_key = key[len(prefix):].lower()
            parsed_value = _parse_env_value(value)
            _set_nested(overrides, config_key.split("_"), parsed_value)
    return overrides


def _parse_env_value(value: str) -> Any:
    """Parse une valeur d'environnement en type Python"""
    # Booléens
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    # Nombres
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    # Listes (séparées par virgules)
    if "," in value:
        return [v.strip() for v in value.split(",")]
    return value


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    """Définit une valeur imbriquée dans un dict"""
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def _deep_merge(base: dict, override: dict) -> dict:
    """Fusionne récursivement deux dictionnaires"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Retourne l'instance de configuration (singleton)"""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance


def reset_config() -> None:
    """Force le rechargement de la configuration (utile pour les tests)"""
    global _config_instance
    _config_instance = None
    get_config.cache_clear()