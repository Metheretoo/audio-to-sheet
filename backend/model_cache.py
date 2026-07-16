"""
AudioScore — Cache intelligent des modèles (Singleton LRU + préchargement asynchrone)
Évite le rechargement répété des modèles IA lourds.
"""
from __future__ import annotations

import threading
import time
import weakref
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class ModelEntry(Generic[T]):
    """Entrée de cache pour un modèle"""
    model: T
    model_name: str
    loader_name: str
    size_mb: float = 0.0
    load_time: float = 0.0
    last_access: float = field(default_factory=time.time)
    access_count: int = 0
    metadata: dict = field(default_factory=dict)


class ModelCache:
    """
    Cache singleton LRU pour les modèles IA avec:
    - Préchargement asynchrone au démarrage
    - Chargement paresseux (lazy loading) à la demande
    - Éviction LRU quand la limite est atteinte
    - Thread-safe
    - Métriques d'utilisation
    """
    _instance: Optional["ModelCache"] = None
    _lock = threading.RLock()

    def __new__(cls) -> "ModelCache":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # Configuration (sera mise à jour via apply_config)
        self._max_models: int = 3
        self._enabled: bool = True
        self._lazy_load: bool = True
        self._cache_dir: str = "models/.cache"

        # Stockage LRU (OrderedDict: clé = model_name, valeur = ModelEntry)
        self._cache: OrderedDict[str, ModelEntry] = OrderedDict()

        # Chargements en cours (pour éviter les doublons)
        self._loading: dict[str, Future] = {}

        # Pool de threads pour chargement asynchrone
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ModelLoader")

        # Callbacks optionnels
        self._on_load_start: Optional[Callable[[str], None]] = None
        self._on_load_complete: Optional[Callable[[str, Any], None]] = None
        self._on_load_error: Optional[Callable[[str, Exception], None]] = None
        self._on_evict: Optional[Callable[[str], None]] = None

        # Statistiques
        self._stats = {
            "hits": 0,
            "misses": 0,
            "loads": 0,
            "evictions": 0,
            "errors": 0,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────────

    def apply_config(self, config) -> None:
        """Applique la configuration depuis AppConfig.model_cache"""
        if hasattr(config, "enabled"):
            self._enabled = config.enabled
        if hasattr(config, "max_models_in_memory"):
            self._max_models = max(1, config.max_models_in_memory)
            self._enforce_limit()
        if hasattr(config, "lazy_load"):
            self._lazy_load = config.lazy_load
        if hasattr(config, "cache_dir"):
            self._cache_dir = config.cache_dir
        if hasattr(config, "preload_on_startup"):
            self.preload_models(config.preload_on_startup)

    def set_callbacks(
        self,
        on_load_start: Optional[Callable[[str], None]] = None,
        on_load_complete: Optional[Callable[[str, Any], None]] = None,
        on_load_error: Optional[Callable[[str, Exception], None]] = None,
        on_evict: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Définit les callbacks pour événements de cache"""
        self._on_load_start = on_load_start
        self._on_load_complete = on_load_complete
        self._on_load_error = on_load_error
        self._on_evict = on_evict

    # ─────────────────────────────────────────────────────────────────────────
    # API principale
    # ─────────────────────────────────────────────────────────────────────────

    def get(self, model_name: str) -> Optional[Any]:
        """
        Récupère un modèle du cache (marque comme récemment utilisé).
        Retourne None si pas en cache.
        """
        if not self._enabled:
            return None

        with self._lock:
            if model_name in self._cache:
                entry = self._cache.pop(model_name)
                entry.last_access = time.time()
                entry.access_count += 1
                self._cache[model_name] = entry  # Remet à la fin (MRU)
                self._stats["hits"] += 1
                logger.debug(f"[ModelCache] HIT: {model_name}")
                return entry.model

            self._stats["misses"] += 1
            logger.debug(f"[ModelCache] MISS: {model_name}")
            return None

    def get_or_load(
        self,
        model_name: str,
        loader_fn: Callable[[], Any],
        loader_name: str = "default",
        size_mb: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> Any:
        """
        Récupère un modèle du cache ou le charge via loader_fn.
        Thread-safe: si un chargement est déjà en cours, l'attend.
        """
        if not self._enabled:
            return loader_fn()

        # 1. Vérifier le cache
        cached = self.get(model_name)
        if cached is not None:
            return cached

        # 2. Vérifier si chargement en cours
        with self._lock:
            if model_name in self._loading:
                future = self._loading[model_name]
            else:
                # 3. Lancer le chargement
                future = self._executor.submit(self._load_model, model_name, loader_fn, loader_name, size_mb, metadata)
                self._loading[model_name] = future

        # 4. Attendre le résultat
        try:
            model = future.result()
            return model
        except Exception as e:
            self._stats["errors"] += 1
            if self._on_load_error:
                self._on_load_error(model_name, e)
            raise

    def _load_model(
        self,
        model_name: str,
        loader_fn: Callable[[], Any],
        loader_name: str,
        size_mb: float,
        metadata: Optional[dict],
    ) -> Any:
        """Charge le modèle (exécuté dans le thread pool)"""
        start_time = time.time()

        if self._on_load_start:
            self._on_load_start(model_name)

        logger.info(f"[ModelCache] Loading model: {model_name} (loader: {loader_name})")

        try:
            model = loader_fn()
            load_time = time.time() - start_time

            # Estimer la taille si non fournie
            if size_mb == 0.0:
                size_mb = self._estimate_model_size(model)

            # Créer l'entrée et ajouter au cache
            entry = ModelEntry(
                model=model,
                model_name=model_name,
                loader_name=loader_name,
                size_mb=size_mb,
                load_time=load_time,
                metadata=metadata or {},
            )

            with self._lock:
                self._cache[model_name] = entry
                self._enforce_limit()
                self._loading.pop(model_name, None)

            self._stats["loads"] += 1

            if self._on_load_complete:
                self._on_load_complete(model_name, model)

            logger.info(f"[ModelCache] Loaded: {model_name} ({size_mb:.1f} MB, {load_time:.2f}s)")
            return model

        except Exception as e:
            with self._lock:
                self._loading.pop(model_name, None)
            logger.error(f"[ModelCache] Failed to load {model_name}: {e}")
            raise

    def _estimate_model_size(self, model: Any) -> float:
        """Estime la taille d'un modèle en Mo"""
        try:
            import torch
            if isinstance(model, torch.nn.Module):
                param_size = sum(p.numel() * p.element_size() for p in model.parameters())
                buffer_size = sum(b.numel() * b.element_size() for b in model.buffers())
                return (param_size + buffer_size) / (1024 ** 2)
        except Exception:
            pass
        return 0.0

    def _enforce_limit(self) -> None:
        """Éviction LRU si limite dépassée"""
        while len(self._cache) > self._max_models:
            oldest_name, oldest_entry = self._cache.popitem(last=False)  # FIFO = LRU
            self._stats["evictions"] += 1
            logger.info(f"[ModelCache] Evicted (LRU): {oldest_name}")
            if self._on_evict:
                self._on_evict(oldest_name)
            # Libérer la mémoire explicitement
            del oldest_entry.model

    # ─────────────────────────────────────────────────────────────────────────
    # Préchargement
    # ─────────────────────────────────────────────────────────────────────────

    def preload_models(self, model_names: list[str], loader_map: Optional[dict[str, Callable]] = None) -> None:
        """
        Précharge une liste de modèles de façon asynchrone.
        Nécessite un loader_map: {model_name: loader_fn}
        """
        if not self._enabled or not model_names:
            return

        if loader_map is None:
            logger.warning("[ModelCache] preload_models appelé sans loader_map")
            return

        for model_name in model_names:
            if model_name in self._cache:
                continue
            if model_name in self._loading:
                continue
            if model_name not in loader_map:
                logger.warning(f"[ModelCache] Pas de loader pour {model_name}")
                continue

            loader_fn = loader_map[model_name]
            # Lancer en arrière-plan sans bloquer
            self._executor.submit(self.get_or_load, model_name, loader_fn, "preload")

        logger.info(f"[ModelCache] Préchargement lancé pour: {model_names}")

    def wait_for_preload(self, model_names: list[str], timeout: float = 60.0) -> dict[str, bool]:
        """Attend la fin du préchargement pour une liste de modèles"""
        results = {}
        start = time.time()
        for name in model_names:
            if name in self._loading:
                try:
                    remaining = timeout - (time.time() - start)
                    if remaining <= 0:
                        results[name] = False
                        continue
                    self._loading[name].result(timeout=remaining)
                    results[name] = True
                except Exception:
                    results[name] = False
            elif name in self._cache:
                results[name] = True
            else:
                results[name] = False
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Gestion du cache
    # ─────────────────────────────────────────────────────────────────────────

    def evict(self, model_name: str) -> bool:
        """Évince un modèle spécifique du cache"""
        with self._lock:
            if model_name in self._cache:
                entry = self._cache.pop(model_name)
                del entry.model
                self._stats["evictions"] += 1
                if self._on_evict:
                    self._on_evict(model_name)
                logger.info(f"[ModelCache] Evicted manually: {model_name}")
                return True
            return False

    def clear(self) -> None:
        """Vide complètement le cache"""
        with self._lock:
            for entry in self._cache.values():
                del entry.model
            self._cache.clear()
            logger.info("[ModelCache] Cache cleared")

    def contains(self, model_name: str) -> bool:
        """Vérifie si un modèle est en cache"""
        with self._lock:
            return model_name in self._cache

    def is_loading(self, model_name: str) -> bool:
        """Vérifie si un modèle est en cours de chargement"""
        with self._lock:
            return model_name in self._loading

    # ─────────────────────────────────────────────────────────────────────────
    # Introspection & stats
    # ─────────────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Retourne les statistiques du cache"""
        with self._lock:
            total_size = sum(e.size_mb for e in self._cache.values())
            return {
                **self._stats,
                "cached_models": len(self._cache),
                "loading_models": len(self._loading),
                "total_size_mb": round(total_size, 1),
                "max_models": self._max_models,
                "hit_rate": round(
                    self._stats["hits"] / max(1, self._stats["hits"] + self._stats["misses"]) * 100, 1
                ),
            }

    def get_cached_models(self) -> list[dict]:
        """Liste les modèles en cache avec leurs métadonnées"""
        with self._lock:
            return [
                {
                    "name": entry.model_name,
                    "loader": entry.loader_name,
                    "size_mb": round(entry.size_mb, 1),
                    "load_time": round(entry.load_time, 2),
                    "last_access": entry.last_access,
                    "access_count": entry.access_count,
                    "metadata": entry.metadata,
                }
                for entry in self._cache.values()
            ]

    def print_summary(self) -> None:
        """Affiche un résumé du cache"""
        stats = self.get_stats()
        models = self.get_cached_models()

        print(f"\n{'='*60}")
        print(f"AudioScore — Model Cache")
        print(f"{'='*60}")
        print(f"Enabled:          {self._enabled}")
        print(f"Max models:       {stats['max_models']}")
        print(f"Cached models:    {stats['cached_models']}")
        print(f"Loading:          {stats['loading_models']}")
        print(f"Total size:       {stats['total_size_mb']:.1f} MB")
        print(f"Hits:             {stats['hits']}")
        print(f"Misses:           {stats['misses']}")
        print(f"Hit rate:         {stats['hit_rate']:.1f}%")
        print(f"Loads:            {stats['loads']}")
        print(f"Evictions:        {stats['evictions']}")
        print(f"Errors:           {stats['errors']}")
        if models:
            print(f"\nCached models:")
            for m in models:
                print(f"  - {m['name']} ({m['loader']}, {m['size_mb']:.1f} MB, "
                      f"loaded in {m['load_time']:.2f}s, accessed {m['access_count']}x)")
        print(f"{'='*60}\n")

    # ─────────────────────────────────────────────────────────────────────────
    # Nettoyage
    # ─────────────────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Arrêt propre: vide le cache et ferme le thread pool"""
        self.clear()
        self._executor.shutdown(wait=True)
        logger.info("[ModelCache] Shutdown complete")


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions utilitaires globales
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_model_cache() -> ModelCache:
    """Retourne l'instance singleton du ModelCache"""
    return ModelCache()


def cached_model(model_name: str, loader_name: str = "default", size_mb: float = 0.0):
    """
    Décorateur pour mettre en cache le résultat d'une fonction de chargement.

    Usage:
        @cached_model("piano_transcription", "piano_transcription_loader")
        def load_piano_model():
            return torch.load(...)
    """
    def decorator(loader_fn: Callable[[], Any]) -> Callable[[], Any]:
        def wrapper() -> Any:
            cache = get_model_cache()
            return cache.get_or_load(model_name, loader_fn, loader_name, size_mb)
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Context manager pour chargement groupé
# ─────────────────────────────────────────────────────────────────────────────

class ModelLoadContext:
    """
    Context manager pour charger plusieurs modèles ensemble.

    Usage:
        with ModelLoadContext() as ctx:
            model1 = ctx.get_or_load("model1", load_fn1)
            model2 = ctx.get_or_load("model2", load_fn2)
        # Tous les modèles sont chargés (ou en cours)
    """
    def __init__(self):
        self.cache = get_model_cache()
        self._futures: dict[str, Future] = {}

    def get_or_load(
        self,
        model_name: str,
        loader_fn: Callable[[], Any],
        loader_name: str = "default",
        size_mb: float = 0.0,
    ) -> Any:
        """Lance le chargement sans bloquer, retourne un Future"""
        if model_name in self.cache._cache:
            return self.cache._cache[model_name].model

        if model_name in self.cache._loading:
            return self.cache._loading[model_name]

        future = self.cache._executor.submit(
            self.cache._load_model, model_name, loader_fn, loader_name, size_mb, None
        )
        self.cache._loading[model_name] = future
        self._futures[model_name] = future
        return future

    def wait_all(self, timeout: float = 120.0) -> dict[str, Any]:
        """Attend tous les chargements et retourne les modèles"""
        results = {}
        for name, future in self._futures.items():
            try:
                results[name] = future.result(timeout=timeout)
            except Exception as e:
                results[name] = e
        return results

    def __enter__(self) -> "ModelLoadContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Optionnel: attendre la fin des chargements
        pass