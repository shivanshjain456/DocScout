"""A small bounded cache with counters, used to make caching measurable.

Why not `functools.lru_cache`: it has no TTL, no bound you can inspect, no hit/miss
counters you can serve, and no way to clear one entry. Artifact 3 requires the *measured*
effect of caching, and a cache you cannot interrogate cannot be measured -- the benchmark
would be reduced to timing the same call twice and asserting the second was faster.

Two layers, because they expire for different reasons:

* The embedding cache maps a query string to its vector. That mapping is pure: it can only
  change if the embedding model changes, which changes the whole index anyway. It is
  bounded but effectively permanent within a process.
* The result cache maps (query, mode, k) to a response. That mapping depends on the corpus
  and must not outlive an ingest, so it carries a TTL and is cleared explicitly.

Eviction is strict LRU on a bound, not a heuristic, so memory is predictable on a 1.9 GiB
box: the result cache holds at most `maxsize` responses of at most `k` passages.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock

import structlog

logger = structlog.get_logger("docscout.cache")

DEFAULT_RESULT_TTL_SECONDS = 300.0


@dataclass
class CacheStats:
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
                # Expired entries are removed on read rather than by a sweeper thread:
                # one fewer thread to manage, and an entry nobody reads costs only memory,
                # which the LRU bound already caps.
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
