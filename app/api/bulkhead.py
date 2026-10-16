"""Bulkhead Concurrency Isolation & Adaptive Load Shedding (FEAT-093).

Implements the bulkhead architectural pattern isolating internal ingestion, batch evals,
and external user queries into separate concurrency pools with adaptive Little's Law
load shedding when queued latency exceeds 200ms or queue depth saturates.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.api.metrics import record_bulkhead_admission, record_bulkhead_shed

VALID_POOLS: tuple[str, ...] = ("query", "ingest", "eval", "internal")

EXCLUDED_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/livez",
        "/readyz",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
    }
)


@dataclass(frozen=True)
class BulkheadConfig:
    """Configuration for concurrency limits and adaptive load shedding."""

    pool_limits: dict[str, int] = field(
        default_factory=lambda: {
            "query": 50,
            "ingest": 10,
            "eval": 5,
            "internal": 20,
        }
    )
    max_queue_wait_ms: float = 200.0  # Max estimated queued wait time before shedding
    enable_load_shedding: bool = True
    default_service_time_ms: float = 25.0
    queue_multipliers: dict[str, int] = field(
        default_factory=lambda: {
            "query": 4,
            "ingest": 2,
            "eval": 2,
            "internal": 3,
        }
    )


@dataclass(frozen=True)
class BulkheadAdmission:
    """Outcome of a bulkhead admission request."""

    admitted: bool
    pool: str
    queue_depth: int
    estimated_wait_ms: float
    rejection_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "pool": self.pool,
            "queue_depth": self.queue_depth,
            "estimated_wait_ms": round(self.estimated_wait_ms, 2),
            "rejection_reason": self.rejection_reason,
        }


class BulkheadRejectedException(Exception):
    """Raised when an incoming request is shed or rejected by bulkhead policy."""

    def __init__(self, admission: BulkheadAdmission) -> None:
        super().__init__(admission.rejection_reason or "Request shed by bulkhead policy")
        self.admission = admission


def determine_pool(path: str, headers: Mapping[str, str] | None = None) -> str:
    """Determine the target bulkhead pool from request headers or path."""
    if headers:
        header_pool = headers.get("X-Pool") or headers.get("x-pool")
        if header_pool and header_pool.lower() in VALID_POOLS:
            return header_pool.lower()

    # Route-based pool classification
    if path.startswith(("/v1/search", "/v1/chat", "/v1/documents")):
        return "query"
    if path.startswith(("/v1/ingest", "/v1/corpus/refresh")):
        return "ingest"
    if path.startswith(("/v1/eval", "/v1/benchmark")):
        return "eval"
    return "internal"


class BulkheadManager:
    """Manages isolated concurrency semaphores and Little's Law adaptive shedding."""

    def __init__(self, config: BulkheadConfig | None = None) -> None:
        self.config = config or BulkheadConfig()
        self._active: dict[str, int] = {p: 0 for p in VALID_POOLS}
        self._queued: dict[str, int] = {p: 0 for p in VALID_POOLS}
        self._avg_service_time_ms: dict[str, float] = {
            p: self.config.default_service_time_ms for p in VALID_POOLS
        }
        self._semaphores: dict[str, asyncio.Semaphore] = {
            p: asyncio.Semaphore(self.config.pool_limits.get(p, 20)) for p in VALID_POOLS
        }
        self._lock = asyncio.Lock()

    def get_pool_limit(self, pool: str) -> int:
        return self.config.pool_limits.get(pool, 20)

    def get_active(self, pool: str) -> int:
        return self._active.get(pool, 0)

    def get_queued(self, pool: str) -> int:
        return self._queued.get(pool, 0)

    def estimate_wait_time_ms(self, pool: str, queued: int) -> float:
        """Estimate queue wait time using Little's Law: W = (Q + 1) * S / limit."""
        limit = max(1, self.get_pool_limit(pool))
        s_avg = self._avg_service_time_ms.get(pool, self.config.default_service_time_ms)
        return ((queued + 1) * s_avg) / limit

    def check_admission(
        self,
        pool: str,
        priority: str = "normal",
        tenant_tier: str = "growth",
    ) -> BulkheadAdmission:
        """Synchronously check admission and Little's Law shedding rules in <= 0.05ms."""
        norm_pool = pool if pool in VALID_POOLS else "internal"
        limit = self.get_pool_limit(norm_pool)
        active = self._active.get(norm_pool, 0)
        queued = self._queued.get(norm_pool, 0)

        # If pool has spare capacity and no queue, admit immediately
        if active < limit and queued == 0:
            return BulkheadAdmission(
                admitted=True,
                pool=norm_pool,
                queue_depth=0,
                estimated_wait_ms=0.0,
            )

        if not self.config.enable_load_shedding:
            return BulkheadAdmission(
                admitted=True,
                pool=norm_pool,
                queue_depth=queued,
                estimated_wait_ms=self.estimate_wait_time_ms(norm_pool, queued),
            )

        # 1. Hard queue capacity check
        multiplier = self.config.queue_multipliers.get(norm_pool, 3)
        max_queue = limit * multiplier
        if queued >= max_queue:
            record_bulkhead_shed(norm_pool, reason="queue_capacity_exceeded")
            return BulkheadAdmission(
                admitted=False,
                pool=norm_pool,
                queue_depth=queued,
                estimated_wait_ms=self.estimate_wait_time_ms(norm_pool, queued),
                rejection_reason=f"Bulkhead pool '{norm_pool}' queue saturated ({queued}/{max_queue})",
            )

        # 2. Adaptive Little's Law wait time check
        est_wait_ms = self.estimate_wait_time_ms(norm_pool, queued)

        # Priority and tenant tier thresholds
        wait_threshold = self.config.max_queue_wait_ms
        norm_pri = priority.lower()
        norm_tier = tenant_tier.lower()

        if norm_pri == "low" or norm_tier == "starter":
            wait_threshold = min(wait_threshold, 100.0)

        if est_wait_ms > wait_threshold:
            record_bulkhead_shed(norm_pool, reason="latency_sla_shed")
            return BulkheadAdmission(
                admitted=False,
                pool=norm_pool,
                queue_depth=queued,
                estimated_wait_ms=est_wait_ms,
                rejection_reason=(
                    f"Estimated queue wait {est_wait_ms:.1f}ms exceeds {wait_threshold:.1f}ms SLA limit"
                ),
            )

        return BulkheadAdmission(
            admitted=True,
            pool=norm_pool,
            queue_depth=queued,
            estimated_wait_ms=est_wait_ms,
        )

    @asynccontextmanager
    async def acquire(
        self,
        pool: str,
        priority: str = "normal",
        tenant_tier: str = "growth",
    ) -> AsyncIterator[BulkheadAdmission]:
        """Async context manager to safely acquire a bulkhead slot or shed excess load."""
        norm_pool = pool if pool in VALID_POOLS else "internal"
        admission = self.check_admission(norm_pool, priority=priority, tenant_tier=tenant_tier)

        if not admission.admitted:
            raise BulkheadRejectedException(admission)

        semaphore = self._semaphores[norm_pool]
        t0 = time.perf_counter()

        # Update queue tracking
        async with self._lock:
            self._queued[norm_pool] += 1
            record_bulkhead_admission(norm_pool, self._active[norm_pool], self._queued[norm_pool])

        acquired = False
        try:
            # Wait for available concurrency slot with bounded timeout
            timeout_s = max(0.01, self.config.max_queue_wait_ms / 1000.0)
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=timeout_s)
                acquired = True
            except TimeoutError:
                record_bulkhead_shed(norm_pool, reason="queue_wait_timeout")
                timed_out_admission = BulkheadAdmission(
                    admitted=False,
                    pool=norm_pool,
                    queue_depth=self._queued.get(norm_pool, 0),
                    estimated_wait_ms=self.config.max_queue_wait_ms,
                    rejection_reason="Timed out waiting for bulkhead concurrency slot",
                )
                raise BulkheadRejectedException(timed_out_admission) from None

            async with self._lock:
                self._queued[norm_pool] = max(0, self._queued[norm_pool] - 1)
                self._active[norm_pool] += 1
                record_bulkhead_admission(
                    norm_pool, self._active[norm_pool], self._queued[norm_pool]
                )

            yield admission

        finally:
            if acquired:
                service_ms = (time.perf_counter() - t0) * 1000.0
                semaphore.release()
                async with self._lock:
                    self._active[norm_pool] = max(0, self._active[norm_pool] - 1)
                    # Exponential moving average for service time (alpha = 0.1)
                    current_avg = self._avg_service_time_ms[norm_pool]
                    self._avg_service_time_ms[norm_pool] = 0.9 * current_avg + 0.1 * service_ms
                    record_bulkhead_admission(
                        norm_pool, self._active[norm_pool], self._queued[norm_pool]
                    )
            else:
                async with self._lock:
                    self._queued[norm_pool] = max(0, self._queued[norm_pool] - 1)
                    record_bulkhead_admission(
                        norm_pool, self._active[norm_pool], self._queued[norm_pool]
                    )

    def get_telemetry(self) -> dict[str, dict[str, Any]]:
        """Return snapshot telemetry across all bulkhead pools."""
        return {
            p: {
                "active": self._active.get(p, 0),
                "limit": self.get_pool_limit(p),
                "queued": self._queued.get(p, 0),
                "queue_capacity": self.get_pool_limit(p) * self.config.queue_multipliers.get(p, 3),
                "avg_service_time_ms": round(
                    self._avg_service_time_ms.get(p, self.config.default_service_time_ms), 2
                ),
            }
            for p in VALID_POOLS
        }


# Global default bulkhead manager instance
GLOBAL_BULKHEAD: BulkheadManager = BulkheadManager()


def get_bulkhead_manager() -> BulkheadManager:
    """Return the active global bulkhead manager."""
    return GLOBAL_BULKHEAD


def set_bulkhead_manager(manager: BulkheadManager) -> None:
    """Set the active global bulkhead manager (for testing and reconfiguration)."""
    global GLOBAL_BULKHEAD
    GLOBAL_BULKHEAD = manager


def get_bulkhead_telemetry() -> dict[str, dict[str, Any]]:
    """Return snapshot telemetry from the active global bulkhead manager."""
    return GLOBAL_BULKHEAD.get_telemetry()
