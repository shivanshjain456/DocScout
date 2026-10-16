"""Chaos engineering fault injection harness and resilience validation (FEAT-094).

Provides controlled, synthetic fault injection during automated test execution:
- PostgreSQL socket timeouts & connection drops
- Temporary pgvector crashes & dense retrieval failures
- OCR.Space API timeouts & corrupted responses
- Embedding model transient errors & memory pressure
- Redis / cache failures with transparent in-memory fallback
- Database connection pool exhaustion & load shedding
- Corrupted multipart document upload payloads
- Bounded latency injection and graceful degradation assertions

Input validation:
- Active ONLY when environment variable `DOCSCOUT_CHAOS_TESTING=1`.
- Any unhandled exception or uncontained crash fails the chaos test suite.
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger("docscout.chaos")


class ChaosFaultType(StrEnum):
    """Supported chaos fault injection modes."""

    DB_TIMEOUT = "db_timeout"
    DB_DISCONNECT = "db_disconnect"
    PGVECTOR_CRASH = "pgvector_crash"
    OCR_TIMEOUT = "ocr_timeout"
    OCR_CORRUPT_PAYLOAD = "ocr_corrupt_payload"
    EMBEDDER_FAILURE = "embedder_failure"
    CACHE_FAILURE = "cache_failure"
    POOL_EXHAUSTION = "pool_exhaustion"
    LATENCY_SPIKE = "latency_spike"
    NETWORK_PARTITION = "network_partition"


@dataclass
class ChaosConfig:
    """Configuration for chaos fault injection."""

    max_fault_duration_ms: int = 5000
    enabled: bool = field(
        default_factory=lambda: (
            os.environ.get("DOCSCOUT_CHAOS_TESTING", "0") in ("1", "true", "yes")
        )
    )


class ChaosTestReport(BaseModel):
    """Output schema for chaos test suite execution."""

    faults_injected: int = 0
    graceful_degradations: int = 0
    unhandled_exceptions: int = 0
    passed: bool = True
    details: list[dict[str, Any]] = Field(default_factory=list)


# Process-wide active fault registry
_ACTIVE_FAULTS: dict[str, dict[str, Any]] = {}


def is_chaos_enabled() -> bool:
    """Returns True only when DOCSCOUT_CHAOS_TESTING is explicitly set."""
    return os.environ.get("DOCSCOUT_CHAOS_TESTING", "0") in ("1", "true", "yes")


def get_active_faults() -> list[str]:
    """List of currently active fault names."""
    return list(_ACTIVE_FAULTS.keys())


def is_fault_active(fault_type: str | ChaosFaultType) -> bool:
    """Check if a specific fault type is actively injected."""
    if not is_chaos_enabled():
        return False
    key = fault_type.value if isinstance(fault_type, ChaosFaultType) else str(fault_type)
    return key in _ACTIVE_FAULTS


def get_fault_params(fault_type: str | ChaosFaultType) -> dict[str, Any]:
    """Retrieve parameters for an active fault."""
    key = fault_type.value if isinstance(fault_type, ChaosFaultType) else str(fault_type)
    return _ACTIVE_FAULTS.get(key, {})


@contextmanager
def inject_fault(
    fault_type: str | ChaosFaultType,
    delay_ms: int = 0,
    error_code: int = 500,
    drop_rate: float = 1.0,
    error_message: str | None = None,
    config: ChaosConfig | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager to inject a synthetic fault during chaos testing.

    Raises ValueError if DOCSCOUT_CHAOS_TESTING is not enabled.
    Enforces max_fault_duration_ms on injected delays.
    Logs structured chaos event marker.
    """
    if not is_chaos_enabled():
        raise ValueError(
            "Fault injection active only when DOCSCOUT_CHAOS_TESTING=1. "
            "Set environment variable DOCSCOUT_CHAOS_TESTING=1 to enable."
        )

    cfg = config or ChaosConfig()
    bounded_delay_ms = min(max(0, delay_ms), cfg.max_fault_duration_ms)
    key = fault_type.value if isinstance(fault_type, ChaosFaultType) else str(fault_type)

    fault_info = {
        "fault_type": key,
        "delay_ms": bounded_delay_ms,
        "error_code": error_code,
        "drop_rate": drop_rate,
        "error_message": error_message or f"Simulated {key} chaos fault",
        "injected_at": time.time(),
    }

    _ACTIVE_FAULTS[key] = fault_info

    # Structured observability marker
    logger.warning(
        "chaos.fault_injected",
        fault_type=key,
        delay_ms=bounded_delay_ms,
        error_code=error_code,
        drop_rate=drop_rate,
    )
    print(f"[CHAOS] Injected fault: {key} (delay={bounded_delay_ms}ms, error={error_code})")

    # If delay_ms > 0, sleep synchronously for up to bounded_delay_ms / 1000.0
    if bounded_delay_ms > 0:
        time.sleep(bounded_delay_ms / 1000.0)

    try:
        yield fault_info
    finally:
        _ACTIVE_FAULTS.pop(key, None)
        logger.info("chaos.fault_cleared", fault_type=key)
        print(f"[CHAOS] Cleared fault: {key}")


class ChaosHarness:
    """Resilience testing harness that coordinates scenario execution and generates reports."""

    def __init__(self, config: ChaosConfig | None = None) -> None:
        self.config = config or ChaosConfig()
        self.report = ChaosTestReport()

    def record_scenario(
        self,
        name: str,
        fault_type: str | ChaosFaultType,
        graceful: bool,
        unhandled: bool,
        recovery_time_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record the outcome of a chaos test scenario."""
        self.report.faults_injected += 1
        if graceful:
            self.report.graceful_degradations += 1
        if unhandled:
            self.report.unhandled_exceptions += 1
            self.report.passed = False

        self.report.details.append(
            {
                "scenario": name,
                "fault_type": fault_type.value
                if isinstance(fault_type, ChaosFaultType)
                else str(fault_type),
                "graceful": graceful,
                "unhandled": unhandled,
                "recovery_time_ms": round(recovery_time_ms, 2),
                **(metadata or {}),
            }
        )

    def evaluate(self) -> ChaosTestReport:
        """Evaluate overall pass/fail status."""
        self.report.passed = (
            self.report.unhandled_exceptions == 0
            and self.report.graceful_degradations == self.report.faults_injected
            and self.report.faults_injected >= 10
        )
        return self.report
