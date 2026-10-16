"""Error Budget Policy & Multi-Window Burn Rate Alerting (FEAT-092).

Implements Google SRE standards for 30-day rolling error budgets (availability SLO 99.9%,
latency p95 < 50ms) with multi-window burn rate computation (1-hour 14.4x critical page,
6-hour 6.0x warning ticket) and automated deployment freeze gates when budget drops below 10%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.api.metrics import update_error_budget_metrics


@dataclass(frozen=True)
class SLOConfig:
    """Service Level Objective and Error Budget configuration."""

    availability_target: float = 0.999  # 99.9% availability
    latency_p95_target_ms: float = 50.0  # p95 latency < 50ms
    freeze_threshold_pct: float = 10.0  # Freeze deployments when < 10% budget left
    min_requests: int = 1000  # Minimum sample size required in 30-day window


@dataclass(frozen=True)
class WindowSample:
    """Operational telemetry sample for a given observation window."""

    total_requests: int
    error_requests: int
    window_duration_hours: float = 1.0


@dataclass(frozen=True)
class ErrorBudgetStatus:
    """Calculated error budget consumption and policy enforcement status."""

    budget_remaining_pct: float
    current_burn_rate_1h: float
    current_burn_rate_6h: float
    is_deployment_frozen: bool
    total_requests_30d: int = 0
    error_requests_30d: int = 0
    availability_slo: float = 0.999
    latency_p95_ms: float = 0.0
    status_message: str = ""
    evaluated_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "docscout.error_budget.status/1",
            "budget_remaining_pct": round(self.budget_remaining_pct, 4),
            "current_burn_rate_1h": round(self.current_burn_rate_1h, 4),
            "current_burn_rate_6h": round(self.current_burn_rate_6h, 4),
            "is_deployment_frozen": self.is_deployment_frozen,
            "total_requests_30d": self.total_requests_30d,
            "error_requests_30d": self.error_requests_30d,
            "availability_slo": round(self.availability_slo, 4),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "status_message": self.status_message,
            "evaluated_at_utc": self.evaluated_at_utc,
        }


def compute_burn_rate(
    window: WindowSample,
    availability_target: float = 0.999,
) -> float:
    """Compute the error budget burn rate multiple over a given window.

    Burn rate = (Errors / Total) / (1 - SLO)
    A burn rate of 1.0 consumes 100% of the budget in 30 days.
    A burn rate of 14.4 consumes 2% of budget in 1 hour.
    """
    if window.total_requests <= 0:
        return 0.0

    allowed_rate = 1.0 - availability_target
    if allowed_rate <= 0:
        return 0.0

    observed_error_rate = window.error_requests / window.total_requests
    return observed_error_rate / allowed_rate


def evaluate_error_budget(
    sample_30d: WindowSample,
    sample_1h: WindowSample | None = None,
    sample_6h: WindowSample | None = None,
    latency_p95_ms: float = 0.0,
    config: SLOConfig | None = None,
) -> ErrorBudgetStatus:
    """Evaluate error budget consumption, burn rates, and deployment freeze policies.

    Args:
        sample_30d: 30-day rolling window request and error counts.
        sample_1h: Optional 1-hour window telemetry for rapid burn detection.
        sample_6h: Optional 6-hour window telemetry for elevated burn detection.
        latency_p95_ms: Measured p95 retrieval latency over the evaluation window.
        config: SLO configuration parameters.

    Returns:
        ErrorBudgetStatus containing remaining budget, burn rates, and freeze status.

    Raises:
        ValueError: If sample_30d total requests is below min_requests.
    """
    cfg = config or SLOConfig()

    if sample_30d.total_requests < cfg.min_requests:
        raise ValueError(
            f"30-day total requests {sample_30d.total_requests} is below minimum requirement {cfg.min_requests}"
        )

    # 1. Compute 30-day remaining budget
    allowed_rate = round(1.0 - cfg.availability_target, 8)
    allowed_errors = sample_30d.total_requests * allowed_rate
    if allowed_errors > 0:
        if sample_30d.error_requests >= allowed_errors:
            budget_remaining_ratio = 0.0
            budget_remaining_pct = 0.0
        else:
            consumed_ratio = sample_30d.error_requests / allowed_errors
            budget_remaining_ratio = max(0.0, 1.0 - consumed_ratio)
            budget_remaining_pct = round(budget_remaining_ratio * 100.0, 6)
    else:
        budget_remaining_ratio = 1.0 if sample_30d.error_requests == 0 else 0.0
        budget_remaining_pct = budget_remaining_ratio * 100.0

    # 2. Compute burn rates
    burn_1h = compute_burn_rate(sample_1h, cfg.availability_target) if sample_1h else 0.0
    burn_6h = compute_burn_rate(sample_6h, cfg.availability_target) if sample_6h else 0.0

    # 3. Deployment Freeze Policy
    # Freeze triggered if:
    # - Budget remaining < freeze_threshold_pct (default 10%)
    # - Rapid burn rate >= 14.4x active (burning 2% budget/hour)
    # - Latency p95 > target (50ms) AND budget remaining < 50%
    freeze_reasons: list[str] = []

    if budget_remaining_pct < cfg.freeze_threshold_pct:
        freeze_reasons.append(
            f"Error budget depleted: {budget_remaining_pct:.2f}% remaining is below {cfg.freeze_threshold_pct:.1f}% freeze threshold"
        )

    if burn_1h >= 14.4:
        freeze_reasons.append(
            f"Critical 1-hour rapid burn active ({burn_1h:.1f}x >= 14.4x threshold)"
        )

    if latency_p95_ms > cfg.latency_p95_target_ms and budget_remaining_pct < 50.0:
        freeze_reasons.append(
            f"Latency SLO breached (p95 {latency_p95_ms:.1f}ms > {cfg.latency_p95_target_ms:.1f}ms) with reduced budget"
        )

    is_frozen = len(freeze_reasons) > 0

    if is_frozen:
        status_msg = "Deployment freeze active: " + "; ".join(freeze_reasons)
    else:
        status_msg = (
            f"Error budget healthy: {budget_remaining_pct:.2f}% remaining "
            f"(1h burn={burn_1h:.2f}x, 6h burn={burn_6h:.2f}x, p95={latency_p95_ms:.1f}ms)"
        )

    # 4. Update Prometheus metrics
    update_error_budget_metrics(
        budget_remaining_ratio=budget_remaining_ratio,
        burn_rate_1h=burn_1h,
        burn_rate_6h=burn_6h,
        is_frozen=is_frozen,
        slo="availability",
    )

    return ErrorBudgetStatus(
        budget_remaining_pct=budget_remaining_pct,
        current_burn_rate_1h=burn_1h,
        current_burn_rate_6h=burn_6h,
        is_deployment_frozen=is_frozen,
        total_requests_30d=sample_30d.total_requests,
        error_requests_30d=sample_30d.error_requests,
        availability_slo=cfg.availability_target,
        latency_p95_ms=latency_p95_ms,
        status_message=status_msg,
    )


def evaluate_error_budget_failsafe(
    reason: str = "Metric collection failed or monitoring blackout",
    config: SLOConfig | None = None,
) -> ErrorBudgetStatus:
    """Fail-safe fallback: assume budget is consumed and halt non-essential deployments."""
    cfg = config or SLOConfig()
    status_msg = f"Fail-safe deployment freeze triggered: {reason}"

    update_error_budget_metrics(
        budget_remaining_ratio=0.0,
        burn_rate_1h=0.0,
        burn_rate_6h=0.0,
        is_frozen=True,
        slo="availability",
    )

    return ErrorBudgetStatus(
        budget_remaining_pct=0.0,
        current_burn_rate_1h=0.0,
        current_burn_rate_6h=0.0,
        is_deployment_frozen=True,
        availability_slo=cfg.availability_target,
        status_message=status_msg,
    )
