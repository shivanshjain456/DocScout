"""Multi-tiered semantic caching and invalidation subsystem for DocScout (FEAT-080, ADR-0071).

Provides:
* Two-tier cache architecture:
  - Tier 1: Thread-safe in-memory OrderedDict LRU for sub-millisecond lookup.
  - Tier 2: Persistent / distributed secondary store (Redis or in-memory mock fallback).
* Embedding-based semantic similarity caching (>0.98 cosine similarity).
* Invalidation listener registry and trigger_corpus_invalidation hook for instant eviction.
* Compatibility layer retaining TTLCache for pure query embedding vector caching.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Protocol, runtime_checkable

import numpy as np
import structlog

logger = structlog.get_logger("docscout.cache")

DEFAULT_RESULT_TTL_SECONDS = 300.0
DEFAULT_LRU_MAXSIZE = 512
DEFAULT_SEMANTIC_THRESHOLD = 0.98


def _normalize_vec(v: Any) -> np.ndarray | None:
    """Ensure a vector is 1D float32 and unit-normalized."""
    if v is None:
        return None
    try:
        arr = np.asarray(v, dtype=np.float32)
        if arr.ndim != 1 or arr.size == 0:
            return None
        norm = float(np.linalg.norm(arr))
        if norm > 1e-9:
            return arr / norm
        return arr
    except Exception:
        return None


@dataclass
class CacheConfig:
    """Configuration for multi-tiered search caching."""

    lru_maxsize: int = DEFAULT_LRU_MAXSIZE
    ttl_seconds: int = int(DEFAULT_RESULT_TTL_SECONDS)
    enable_semantic_matching: bool = False
    semantic_similarity_threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    redis_url: str | None = None


@dataclass
class CacheStats:
    """Basic cache counters for inspection and observability."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0

    def as_dict(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate_pct": round(self.hit_rate * 100),
        }


@dataclass
class TieredCacheStats(CacheStats):
    """Granular statistics across cache tiers (Tier 1, Tier 2, Semantic)."""

    tier1_hits: int = 0
    tier2_hits: int = 0
    semantic_hits: int = 0
    invalidations: int = 0

    def as_dict(self) -> dict[str, int]:
        base = super().as_dict()
        base.update(
            {
                "tier1_hits": self.tier1_hits,
                "tier2_hits": self.tier2_hits,
                "semantic_hits": self.semantic_hits,
                "invalidations": self.invalidations,
            }
        )
        return base


@dataclass
class CacheEntry[V]:
    """Single cached entry with payload, timestamp, and optional embedding vector."""

    key: Any
    value: V
    stored_at: float
    query_text: str | None = None
    query_vector: np.ndarray | None = None
    search_params: tuple[Any, ...] | None = None


@runtime_checkable
class Tier2Backend[V](Protocol):
    """Protocol for secondary / distributed cache tiers (e.g. Redis)."""

    def get(self, key_str: str, *, now: float | None = None) -> V | None: ...

    def put(
        self,
        key_str: str,
        value: V,
        ttl: float | None = None,
        *,
        now: float | None = None,
    ) -> None: ...

    def clear(self) -> int: ...


class InMemoryTier2Backend[V]:
    """In-memory secondary / mock Tier 2 cache for local or hermetic test environments."""

    def __init__(self, maxsize: int = 1024) -> None:
        self.maxsize = maxsize
        self._data: dict[str, tuple[float | None, V]] = {}
        self._lock = Lock()

    def get(self, key_str: str, *, now: float | None = None) -> V | None:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            entry = self._data.get(key_str)
            if entry is None:
                return None
            expires_at, val = entry
            if expires_at is not None and current_time > expires_at:
                del self._data[key_str]
                return None
            return val

    def put(
        self,
        key_str: str,
        value: V,
        ttl: float | None = None,
        *,
        now: float | None = None,
    ) -> None:
        current_time = time.monotonic() if now is None else now
        expires_at = (current_time + ttl) if (ttl is not None and ttl > 0) else None
        with self._lock:
            self._data[key_str] = (expires_at, value)
            if len(self._data) > self.maxsize:
                oldest_key = next(iter(self._data))
                del self._data[oldest_key]

    def clear(self) -> int:
        with self._lock:
            count = len(self._data)
            self._data.clear()
            return count


class RedisTier2Backend[V]:
    """Redis-backed persistent Tier 2 cache with safe serialization and fail-open resilience."""

    def __init__(self, redis_url: str, prefix: str = "docscout:cache:") -> None:
        self.prefix = prefix
        self._client: Any = None
        self._disabled = False
        try:
            import redis

            self._client = redis.Redis.from_url(
                redis_url,
                socket_timeout=0.1,
                socket_connect_timeout=0.1,
            )
        except Exception as exc:
            logger.warning("cache.redis_init_failed", error=str(exc))
            self._disabled = True

    def get(self, key_str: str, *, now: float | None = None) -> V | None:
        if self._disabled or self._client is None:
            return None
        try:
            raw = self._client.get(f"{self.prefix}{key_str}")
            if raw is None:
                return None
            import pickle

            return pickle.loads(raw)  # type: ignore[no-any-return]  # noqa: S301
        except Exception as exc:
            logger.warning("cache.redis_get_failed", key=key_str, error=str(exc))
            return None

    def put(
        self,
        key_str: str,
        value: V,
        ttl: float | None = None,
        *,
        now: float | None = None,
    ) -> None:
        if self._disabled or self._client is None:
            return
        try:
            import pickle

            data = pickle.dumps(value)
            ex = int(ttl) if ttl is not None and ttl > 0 else None
            self._client.set(f"{self.prefix}{key_str}", data, ex=ex)
        except Exception as exc:
            logger.warning("cache.redis_put_failed", key=key_str, error=str(exc))

    def clear(self) -> int:
        if self._disabled or self._client is None:
            return 0
        try:
            keys = self._client.keys(f"{self.prefix}*")
            if keys:
                self._client.delete(*keys)
                return len(keys)
            return 0
        except Exception as exc:
            logger.warning("cache.redis_clear_failed", error=str(exc))
            return 0


@dataclass
class TTLCache[K, V]:
    """Thread-safe LRU cache with an optional per-entry time to live.

    Thread-safe because FastAPI runs synchronous endpoints in a worker thread pool, so two
    requests genuinely touch this concurrently. An unsynchronised OrderedDict under
    concurrent `move_to_end` is a corrupted structure, not merely a lost update.
    """

    maxsize: int = 512
    ttl: float | None = None
    _data: OrderedDict[K, tuple[float, V]] = field(default_factory=OrderedDict)
    _lock: Lock = field(default_factory=Lock)
    stats: CacheStats = field(default_factory=CacheStats)

    def get(self, key: K, *, now: float | None = None) -> V | None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            stored_at, value = entry
            if self.ttl is not None and moment - stored_at > self.ttl:
                del self._data[key]
                self.stats.misses += 1
                return None
            self._data.move_to_end(key)
            self.stats.hits += 1
            return value

    def put(self, key: K, value: V, *, now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (moment, value)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
                self.stats.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def reset_stats(self) -> None:
        with self._lock:
            self.stats = CacheStats()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class TieredSemanticCache[V]:
    """Two-tier thread-safe semantic cache supporting exact LRU and vector similarity matching."""

    def __init__(
        self,
        config: CacheConfig | None = None,
        tier2: Tier2Backend[V] | None = None,
    ) -> None:
        self.config = config or CacheConfig()
        self.maxsize = self.config.lru_maxsize
        self.ttl: float = float(self.config.ttl_seconds)

        if tier2 is not None:
            self.tier2: Tier2Backend[V] = tier2
        elif self.config.redis_url:
            self.tier2 = RedisTier2Backend(self.config.redis_url)
        else:
            self.tier2 = InMemoryTier2Backend(maxsize=self.maxsize * 2)

        self._tier1: OrderedDict[Any, CacheEntry[V]] = OrderedDict()
        self._lock = Lock()
        self.stats = TieredCacheStats()

    def get_with_tier(
        self,
        key: Any,
        *,
        query_text: str | None = None,
        query_vector: Any | None = None,
        search_params: tuple[Any, ...] | None = None,
        now: float | None = None,
    ) -> tuple[V | None, str | None]:
        """Probe Tier 1 exact match -> Tier 2 exact match -> Semantic similarity."""
        moment = time.monotonic() if now is None else now

        # 1. Tier 1 exact match
        with self._lock:
            entry = self._tier1.get(key)
            if entry is not None:
                if self.ttl > 0 and moment - entry.stored_at > self.ttl:
                    del self._tier1[key]
                else:
                    self._tier1.move_to_end(key)
                    self.stats.hits += 1
                    self.stats.tier1_hits += 1
                    return entry.value, "tier1"

        # 2. Tier 2 exact match
        try:
            val = self.tier2.get(str(key), now=moment)
            if val is not None:
                with self._lock:
                    self.stats.hits += 1
                    self.stats.tier2_hits += 1
                    norm_v = _normalize_vec(query_vector)
                    new_entry = CacheEntry(
                        key=key,
                        value=val,
                        stored_at=moment,
                        query_text=query_text,
                        query_vector=norm_v,
                        search_params=search_params,
                    )
                    self._tier1[key] = new_entry
                    self._tier1.move_to_end(key)
                    while len(self._tier1) > self.maxsize:
                        self._tier1.popitem(last=False)
                        self.stats.evictions += 1
                return val, "tier2"
        except Exception:
            logger.warning("cache.tier2_probe_failed", exc_info=True)

        # 3. Semantic similarity matching across Tier 1 entries
        if self.config.enable_semantic_matching and query_vector is not None:
            norm_q = _normalize_vec(query_vector)
            if norm_q is not None:
                with self._lock:
                    best_sim = -1.0
                    best_entry: CacheEntry[V] | None = None
                    best_key: Any = None

                    for k, cand in self._tier1.items():
                        if cand.query_vector is None:
                            continue
                        if self.ttl > 0 and moment - cand.stored_at > self.ttl:
                            continue
                        if (
                            search_params is not None
                            and cand.search_params is not None
                            and cand.search_params != search_params
                        ):
                            continue
                        sim = float(np.dot(norm_q, cand.query_vector))
                        if sim > best_sim:
                            best_sim = sim
                            best_entry = cand
                            best_key = k

                    if (
                        best_sim >= self.config.semantic_similarity_threshold
                        and best_entry is not None
                    ):
                        self._tier1.move_to_end(best_key)
                        self.stats.hits += 1
                        self.stats.semantic_hits += 1
                        return best_entry.value, "semantic"

        # Miss across all tiers
        with self._lock:
            self.stats.misses += 1
        return None, None

    def get(
        self,
        key: Any,
        *,
        query_text: str | None = None,
        query_vector: Any | None = None,
        search_params: tuple[Any, ...] | None = None,
        now: float | None = None,
    ) -> V | None:
        """Convenience method matching TTLCache.get signature."""
        val, _ = self.get_with_tier(
            key,
            query_text=query_text,
            query_vector=query_vector,
            search_params=search_params,
            now=now,
        )
        return val

    def put(
        self,
        key: Any,
        value: V,
        *,
        query_text: str | None = None,
        query_vector: Any | None = None,
        search_params: tuple[Any, ...] | None = None,
        now: float | None = None,
    ) -> None:
        """Store into Tier 1 and Tier 2."""
        moment = time.monotonic() if now is None else now
        norm_v = _normalize_vec(query_vector)
        entry = CacheEntry(
            key=key,
            value=value,
            stored_at=moment,
            query_text=query_text,
            query_vector=norm_v,
            search_params=search_params,
        )

        with self._lock:
            if key in self._tier1:
                self._tier1.move_to_end(key)
            self._tier1[key] = entry
            while len(self._tier1) > self.maxsize:
                self._tier1.popitem(last=False)
                self.stats.evictions += 1

        try:
            self.tier2.put(str(key), value, ttl=self.ttl, now=moment)
        except Exception:
            logger.warning("cache.tier2_store_failed", exc_info=True)

    def clear(self) -> int:
        """Evict all entries across Tier 1 and Tier 2."""
        with self._lock:
            cleared_t1 = len(self._tier1)
            self._tier1.clear()
            self.stats.invalidations += 1

        cleared_t2 = 0
        try:
            cleared_t2 = self.tier2.clear()
        except Exception:
            logger.warning("cache.tier2_clear_failed", exc_info=True)

        return cleared_t1 + cleared_t2

    def reset_stats(self) -> None:
        """Reset hit and miss counters."""
        with self._lock:
            self.stats = TieredCacheStats()

    def __len__(self) -> int:
        """Number of active entries in Tier 1."""
        with self._lock:
            return len(self._tier1)


InvalidationCallback = Callable[[str | None], None]

_INVALIDATION_LISTENERS: list[InvalidationCallback] = []
_LISTENERS_LOCK: Lock = Lock()


def register_invalidation_listener(callback: InvalidationCallback) -> None:
    """Register a callback to be invoked when corpus data is superseded or changed."""
    with _LISTENERS_LOCK:
        if callback not in _INVALIDATION_LISTENERS:
            _INVALIDATION_LISTENERS.append(callback)


def unregister_invalidation_listener(callback: InvalidationCallback) -> None:
    """Unregister an invalidation callback."""
    with _LISTENERS_LOCK:
        if callback in _INVALIDATION_LISTENERS:
            _INVALIDATION_LISTENERS.remove(callback)


def trigger_corpus_invalidation(reason: str | None = None) -> int:
    """Notify all registered listeners that corpus content has changed.

    Returns the number of listeners notified.
    Any exception in an individual listener is caught and does not abort others.
    """
    with _LISTENERS_LOCK:
        listeners = list(_INVALIDATION_LISTENERS)
    for listener in listeners:
        try:
            listener(reason)
        except Exception:
            logger.warning("cache.listener_failed", reason=reason, exc_info=True)
    return len(listeners)
