"""
AudioScore — Gestionnaire de matériel unifié (GPU/CPU)
Détection automatique, fallback, optimisation mémoire, batch sizing.
"""
from __future__ import annotations

import os
import platform
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional
from functools import lru_cache

import torch


DeviceType = Literal["cuda", "mps", "cpu"]


@dataclass
class DeviceInfo:
    """Informations sur le dispositif de calcul détecté"""
    device_type: DeviceType
    device_name: str
    device_index: int = 0
    total_memory_gb: float = 0.0
    free_memory_gb: float = 0.0
    compute_capability: tuple[int, int] | None = None
    is_available: bool = True
    driver_version: str | None = None
    torch_version: str = torch.__version__


class DeviceManager:
    """
    Gestionnaire singleton pour la détection et la configuration du matériel.
    Gère CUDA, MPS (Apple Silicon), CPU avec fallback automatique.
    """
    _instance: Optional["DeviceManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "DeviceManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        self._device_info: DeviceInfo | None = None
        self._preferred_device: DeviceType = "auto"
        self._cpu_threads: int = 0
        self._gpu_memory_fraction: float = 0.85
        self._allow_fallback: bool = True
        self._batch_sizes: dict[DeviceType, int] = {"cpu": 1, "cuda": 4, "mps": 2}
        self._auto_batch_size: bool = True

        # Détection initiale
        self._detect_device()
        self._configure_torch()

    # ─────────────────────────────────────────────────────────────────────────
    # Détection matériel
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_device(self) -> None:
        """Détecte le meilleur dispositif disponible"""
        # 1. Essayer CUDA
        if torch.cuda.is_available():
            self._device_info = self._detect_cuda()
            return

        # 2. Essayer MPS (Apple Silicon)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self._device_info = self._detect_mps()
            return

        # 3. Fallback CPU
        self._device_info = self._detect_cpu()

    def _detect_cuda(self) -> DeviceInfo:
        """Détecte les informations CUDA"""
        device_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(current_device)

        total_mem = props.total_memory / (1024 ** 3)
        # Estimer la mémoire libre
        try:
            free_mem = (torch.cuda.mem_get_info(current_device)[0]) / (1024 ** 3)
        except AttributeError:
            # Ancienne version de PyTorch
            free_mem = total_mem * 0.8

        return DeviceInfo(
            device_type="cuda",
            device_name=props.name,
            device_index=current_device,
            total_memory_gb=round(total_mem, 2),
            free_memory_gb=round(free_mem, 2),
            compute_capability=(props.major, props.minor),
            is_available=True,
            driver_version=torch.version.cuda,
        )

    def _detect_mps(self) -> DeviceInfo:
        """Détecte les informations MPS (Apple Silicon)"""
        # MPS n'expose pas facilement la VRAM, on estime
        # Sur macOS unified memory, la "VRAM" = RAM système partagée
        try:
            import psutil
            total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
            # Estimation conservatrice : 50% de la RAM pour le GPU
            estimated_vram = total_ram_gb * 0.5
        except ImportError:
            estimated_vram = 8.0  # Fallback par défaut

        return DeviceInfo(
            device_type="mps",
            device_name="Apple Silicon GPU",
            device_index=0,
            total_memory_gb=round(estimated_vram, 2),
            free_memory_gb=round(estimated_vram * 0.7, 2),
            is_available=True,
        )

    def _detect_cpu(self) -> DeviceInfo:
        """Détecte les informations CPU"""
        cpu_name = platform.processor() or platform.machine()
        cpu_count = os.cpu_count() or 4

        return DeviceInfo(
            device_type="cpu",
            device_name=f"{cpu_name} ({cpu_count} cores)",
            device_index=0,
            total_memory_gb=0.0,
            free_memory_gb=0.0,
            is_available=True,
        )

    def _configure_torch(self) -> None:
        """Configure PyTorch selon le dispositif détecté"""
        if self._device_info.device_type == "cpu":
            # Optimiser les threads CPU
            threads = self._cpu_threads or min(8, os.cpu_count() or 4)
            torch.set_num_threads(threads)
            torch.set_num_interop_threads(threads)
            os.environ["OMP_NUM_THREADS"] = str(threads)
            os.environ["MKL_NUM_THREADS"] = str(threads)

        elif self._device_info.device_type == "cuda":
            # Configurer la fraction de mémoire GPU
            if self._gpu_memory_fraction < 1.0:
                torch.cuda.set_per_process_memory_fraction(self._gpu_memory_fraction)

        elif self._device_info.device_type == "mps":
            # MPS n'a pas de configuration de mémoire explicite
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # API publique
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def device(self) -> torch.device:
        """Retourne le torch.device à utiliser"""
        return torch.device(self._device_info.device_type)

    @property
    def device_type(self) -> DeviceType:
        """Type de dispositif: 'cuda', 'mps', ou 'cpu'"""
        return self._device_info.device_type

    @property
    def device_info(self) -> DeviceInfo:
        """Informations complètes sur le dispositif"""
        return self._device_info

    @property
    def is_gpu(self) -> bool:
        """True si GPU disponible (CUDA ou MPS)"""
        return self._device_info.device_type in ("cuda", "mps")

    @property
    def cpu_threads(self) -> int:
        return self._cpu_threads

    @cpu_threads.setter
    def cpu_threads(self, value: int) -> None:
        self._cpu_threads = max(1, value)
        if self._device_info.device_type == "cpu":
            torch.set_num_threads(self._cpu_threads)
            torch.set_num_interop_threads(self._cpu_threads)

    @property
    def gpu_memory_fraction(self) -> float:
        return self._gpu_memory_fraction

    @gpu_memory_fraction.setter
    def gpu_memory_fraction(self, value: float) -> None:
        self._gpu_memory_fraction = max(0.1, min(1.0, value))
        if self._device_info.device_type == "cuda":
            torch.cuda.set_per_process_memory_fraction(self._gpu_memory_fraction)

    @property
    def allow_fallback(self) -> bool:
        return self._allow_fallback

    @allow_fallback.setter
    def allow_fallback(self, value: bool) -> None:
        self._allow_fallback = value

    def get_batch_size(self, model_size_mb: float = 100) -> int:
        """
        Calcule la taille de batch optimale selon le dispositif et la taille du modèle.

        Args:
            model_size_mb: Taille estimée du modèle en Mo

        Returns:
            Batch size recommandé
        """
        if not self._auto_batch_size:
            return self._batch_sizes.get(self._device_info.device_type, 1)

        if self._device_info.device_type == "cuda":
            # Estimation : VRAM libre / (taille_modèle * 3 pour gradients + activations)
            available = self._device_info.free_memory_gb * 1024  # Mo
            estimated_per_sample = model_size_mb * 3
            batch = max(1, int(available / estimated_per_sample))
            return min(batch, self._batch_sizes.get("cuda", 4))

        elif self._device_info.device_type == "mps":
            # MPS : mémoire unifiée, plus conservateur
            available = self._device_info.free_memory_gb * 1024
            estimated_per_sample = model_size_mb * 4
            batch = max(1, int(available / estimated_per_sample))
            return min(batch, self._batch_sizes.get("mps", 2))

        else:
            return self._batch_sizes.get("cpu", 1)

    def set_batch_sizes(self, cpu: int = 1, cuda: int = 4, mps: int = 2, auto: bool = True) -> None:
        """Configure les tailles de batch par dispositif"""
        self._batch_sizes = {"cpu": cpu, "cuda": cuda, "mps": mps}
        self._auto_batch_size = auto

    def empty_cache(self) -> None:
        """Vide le cache du dispositif actuel"""
        if self._device_info.device_type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        elif self._device_info.device_type == "mps":
            torch.mps.empty_cache()
        # CPU : pas de cache à vider

    def get_memory_stats(self) -> dict[str, float]:
        """Retourne les statistiques de mémoire actuelles"""
        stats = {
            "device_type": self._device_info.device_type,
            "total_gb": self._device_info.total_memory_gb,
        }

        if self._device_info.device_type == "cuda":
            allocated = torch.cuda.memory_allocated() / (1024 ** 3)
            reserved = torch.cuda.memory_reserved() / (1024 ** 3)
            free, total = torch.cuda.mem_get_info()
            stats.update({
                "allocated_gb": round(allocated, 2),
                "reserved_gb": round(reserved, 2),
                "free_gb": round(free / (1024 ** 3), 2),
                "total_gb": round(total / (1024 ** 3), 2),
            })
        elif self._device_info.device_type == "mps":
            try:
                allocated = torch.mps.current_allocated_memory() / (1024 ** 3)
                stats.update({
                    "allocated_gb": round(allocated, 2),
                    "free_gb": round(self._device_info.free_memory_gb - allocated, 2),
                })
            except AttributeError:
                pass

        return stats

    def print_summary(self) -> None:
        """Affiche un résumé du matériel détecté"""
        info = self._device_info
        print(f"\n{'='*50}")
        print(f"AudioScore — Device Manager")
        print(f"{'='*50}")
        print(f"Device:           {info.device_type.upper()} ({info.device_name})")
        print(f"Torch version:    {info.torch_version}")
        if info.device_type == "cuda":
            print(f"CUDA version:     {info.driver_version}")
            print(f"Compute capability: {info.compute_capability[0]}.{info.compute_capability[1]}")
        print(f"Total memory:     {info.total_memory_gb:.2f} GB")
        print(f"Free memory:      {info.free_memory_gb:.2f} GB")
        print(f"CPU threads:      {self._cpu_threads or 'auto'}")
        print(f"GPU memory frac:  {self._gpu_memory_fraction:.0%}")
        print(f"Batch sizes:      CPU={self._batch_sizes['cpu']}, CUDA={self._batch_sizes['cuda']}, MPS={self._batch_sizes['mps']}")
        print(f"Auto batch size:  {self._auto_batch_size}")
        print(f"Allow fallback:   {self._allow_fallback}")
        print(f"{'='*50}\n")

    # ─────────────────────────────────────────────────────────────────────────
    # Configuration depuis config.yaml
    # ─────────────────────────────────────────────────────────────────────────

    def apply_config(self, config) -> None:
        """Applique la configuration depuis AppConfig.device"""
        if hasattr(config, "preference"):
            self._preferred_device = config.preference
        if hasattr(config, "cpu_threads") and config.cpu_threads > 0:
            self.cpu_threads = config.cpu_threads
        if hasattr(config, "gpu_memory_fraction"):
            self.gpu_memory_fraction = config.gpu_memory_fraction
        if hasattr(config, "allow_fallback"):
            self.allow_fallback = config.allow_fallback
        if hasattr(config, "batch_size"):
            bs = config.batch_size
            if isinstance(bs, dict):
                self.set_batch_sizes(
                    cpu=bs.get("cpu", 1),
                    cuda=bs.get("cuda", 4),
                    mps=bs.get("mps", 2),
                    auto=bs.get("auto", True)
                )

        # Re-détecter si préférence changée
        if hasattr(config, "preference") and config.preference != "auto":
            self._force_device(config.preference)

    def _force_device(self, device_type: DeviceType) -> None:
        """Force l'utilisation d'un dispositif spécifique (avec fallback si autorisé)"""
        if device_type == "cuda" and not torch.cuda.is_available():
            if self._allow_fallback:
                print("[DeviceManager] CUDA non disponible, fallback CPU")
                self._device_info = self._detect_cpu()
            else:
                raise RuntimeError("CUDA demandé mais non disponible")
        elif device_type == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            if self._allow_fallback:
                print("[DeviceManager] MPS non disponible, fallback CPU")
                self._device_info = self._detect_cpu()
            else:
                raise RuntimeError("MPS demandé mais non disponible")
        elif device_type == "cpu":
            self._device_info = self._detect_cpu()
        else:
            # Auto ou dispositif disponible
            self._detect_device()

        self._configure_torch()


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions utilitaires globales
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_device_manager() -> DeviceManager:
    """Retourne l'instance singleton du DeviceManager"""
    return DeviceManager()


def get_device() -> torch.device:
    """Shortcut pour obtenir le torch.device actuel"""
    return get_device_manager().device


def get_device_type() -> DeviceType:
    """Shortcut pour obtenir le type de dispositif"""
    return get_device_manager().device_type


def empty_cache() -> None:
    """Shortcut pour vider le cache"""
    get_device_manager().empty_cache()


def print_device_summary() -> None:
    """Shortcut pour afficher le résumé"""
    get_device_manager().print_summary()


# ─────────────────────────────────────────────────────────────────────────────
# Context manager pour dispositif temporaire
# ─────────────────────────────────────────────────────────────────────────────

class DeviceContext:
    """
    Context manager pour changer temporairement de dispositif.

    Usage:
        with DeviceContext("cpu"):
            model = load_model()  # Chargé sur CPU
        # Retourne au dispositif par défaut
    """
    def __init__(self, device_type: DeviceType):
        self.device_type = device_type
        self.manager = get_device_manager()
        self.previous_device = self.manager._device_info

    def __enter__(self) -> torch.device:
        self.manager._force_device(self.device_type)
        return self.manager.device

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.manager._device_info = self.previous_device
        self.manager._configure_torch()