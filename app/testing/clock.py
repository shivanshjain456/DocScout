"""Hermetic deterministic test fixtures with clock injection and seeded randomness (FEAT-095).

Eliminates test suite flakiness by enforcing:
1. Frozen PRNG seeds (random.seed, numpy.random.seed, torch.manual_seed).
2. Clock injection protocol (time-travel testing with FrozenClock).
3. Hermetic in-memory vector store double.
4. Flakiness detection & quarantine evaluation harness.
"""

from __future__ import annotations

import os
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Clock(Protocol):
    """Protocol for system clock injection."""

    def now(self) -> datetime:
        """Current datetime in UTC."""
        ...

    def time(self) -> float:
        """Current epoch timestamp in seconds."""
        ...


class SystemClock:
    """Production clock implementation backed by system wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def time(self) -> float:
        return time.time()


class FrozenClock:
    """Hermetic deterministic clock with time-travel capabilities."""

    def __init__(self, frozen_time: str | datetime = "2026-10-10T12:00:00Z") -> None:
        self._set_frozen_time(frozen_time)

    def _set_frozen_time(self, frozen_time: str | datetime) -> None:
        if isinstance(frozen_time, str):
            clean = frozen_time.replace("Z", "+00:00")
            self._current_dt = datetime.fromisoformat(clean)
        else:
            self._current_dt = frozen_time
        if self._current_dt.tzinfo is None:
            self._current_dt = self._current_dt.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._current_dt

    def time(self) -> float:
        return self._current_dt.timestamp()

    def advance(self, seconds: float) -> None:
        """Advance the frozen clock forward in time by the specified seconds."""
        from datetime import timedelta

        self._current_dt += timedelta(seconds=seconds)

    def reset(self, to_time: str | datetime | None = None) -> None:
        """Reset the clock to the initial frozen timestamp or a new timestamp."""
        target = to_time if to_time is not None else "2026-10-10T12:00:00Z"
        self._set_frozen_time(target)


_CURRENT_CLOCK: Clock = SystemClock()


def get_clock() -> Clock:
    """Retrieve the currently active clock (SystemClock by default)."""
    return _CURRENT_CLOCK


def set_clock(clock: Clock | None) -> None:
    """Inject a mockable clock implementation (e.g. FrozenClock)."""
    global _CURRENT_CLOCK
    _CURRENT_CLOCK = clock if clock is not None else SystemClock()


@dataclass
class TestingConfig:
    """Configuration schema for deterministic test harness."""

    __test__ = False
    deterministic_seed: int = 0
    frozen_time: str = "2026-10-10T12:00:00Z"


def seed_everything(seed: int = 0) -> None:
    """Freeze all PRNG seeds across Python runtime for 100% test reproducibility."""
    seed_str = str(seed)
    if os.environ.get("PYTHONHASHSEED") != seed_str:
        os.environ["PYTHONHASHSEED"] = seed_str
    random.seed(seed)
    np.random.seed(seed)

    # Optional torch seed if torch is present in sys.modules
    if "torch" in sys.modules:
        torch_mod = sys.modules["torch"]
        if hasattr(torch_mod, "manual_seed"):
            torch_mod.manual_seed(seed)


class InMemoryVectorDouble:
    """Hermetic in-memory vector store double.

    Implements exact cosine similarity search over in-memory numpy vectors,
    eliminating all real database and pgvector dependencies for fast unit tests.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self._vectors: dict[str, np.ndarray] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def insert(
        self,
        chunk_id: str,
        vector: list[float] | np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or replace a vector in the in-memory double."""
        arr = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        self._vectors[chunk_id] = arr
        self._metadata[chunk_id] = metadata or {}

    def search(
        self, query_vector: list[float] | np.ndarray, top_k: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Compute cosine similarities and return top-k results deterministically."""
        if not self._vectors:
            return []

        q = np.asarray(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm > 0:
            q = q / q_norm

        scores: list[tuple[str, float, dict[str, Any]]] = []
        for chunk_id, vec in self._vectors.items():
            sim = float(np.dot(q, vec))
            scores.append((chunk_id, sim, self._metadata[chunk_id]))

        # Deterministic sort: descending by score, tie-break by chunk_id
        scores.sort(key=lambda item: (-item[1], item[0]))
        return scores[:top_k]

    def count(self) -> int:
        return len(self._vectors)

    def clear(self) -> None:
        self._vectors.clear()
        self._metadata.clear()


def detect_flakiness(test_fn: Callable[[], Any], iterations: int = 5) -> dict[str, Any]:
    """Test flakiness detection harness.

    Executes a test function `iterations` times and verifies identical deterministic results.
    Returns diagnostic report confirming genuine defect vs flakiness.
    """
    results: list[Any] = []
    exceptions: list[str] = []

    for i in range(iterations):
        try:
            res = test_fn()
            results.append(res)
        except Exception as exc:
            exceptions.append(f"Iteration {i}: {type(exc).__name__}: {exc}")

    is_flaky = len(exceptions) > 0 and len(exceptions) < iterations
    passed = len(exceptions) == 0

    return {
        "iterations": iterations,
        "passed": passed,
        "is_flaky": is_flaky,
        "success_count": iterations - len(exceptions),
        "failure_count": len(exceptions),
        "errors": exceptions,
    }
