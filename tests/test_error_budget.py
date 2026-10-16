"""Tests for Error Budget Policy & Multi-Window Burn Rate Alerting (FEAT-092).

Verifies 30-day error budget calculation, 1-hour 14.4x rapid burn detection, 6-hour 6.0x
elevated burn detection, automated deployment freeze policies, fail-safe blackout handling,
sub-millisecond calculation execution, and Prometheus alert rules.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from app.api.error_budget import (
    WindowSample,
    compute_burn_rate,
    evaluate_error_budget,
    evaluate_error_budget_failsafe,
)
from app.api.metrics import (
    ERROR_BUDGET_BURN_RATE,
    ERROR_BUDGET_DEPLOYMENT_FROZEN,
    ERROR_BUDGET_REMAINING_RATIO,
)


def test_healthy_budget_allows_deployments() -> None:
    """Healthy error budget (e.g. 80% remaining) allows deployments with zero freeze."""
    # 10,000 requests, 2 errors (allowed errors at 99.9% = 10)
    # consumed = 2 / 10 = 20% -> 80% budget remaining
    sample_30d = WindowSample(total_requests=10000, error_requests=2)
    sample_1h = WindowSample(total_requests=500, error_requests=0)
    sample_6h = WindowSample(total_requests=2500, error_requests=1)

    status = evaluate_error_budget(
        sample_30d=sample_30d,
        sample_1h=sample_1h,
        sample_6h=sample_6h,
        latency_p95_ms=25.0,
    )

    assert status.budget_remaining_pct == pytest.approx(80.0, rel=1e-3)
    assert status.is_deployment_frozen is False
    assert status.current_burn_rate_1h == 0.0
    assert "Error budget healthy" in status.status_message

    # Verify Prometheus gauge metrics updated
    assert ERROR_BUDGET_DEPLOYMENT_FROZEN._value.get() == 0.0
    assert ERROR_BUDGET_REMAINING_RATIO.labels(slo="availability")._value.get() == pytest.approx(
        0.80, rel=1e-3
    )


def test_depleted_error_budget_triggers_deployment_freeze() -> None:
    """Error budget falling below 10% remaining automatically freezes deployments."""
    # 10,000 requests, allowed errors = 10.
    # 10 errors -> 100% budget consumed -> 0% remaining
    sample_depleted = WindowSample(total_requests=10000, error_requests=10)
    status_depleted = evaluate_error_budget(sample_30d=sample_depleted)

    assert status_depleted.budget_remaining_pct == 0.0
    assert status_depleted.is_deployment_frozen is True
    assert "Deployment freeze active" in status_depleted.status_message

    # 10,000 requests, 9.5 (or 9) errors -> 90% consumed -> 10% remaining
    # 10,000 requests, 10 errors on 99.9% SLO with freeze threshold 10%
    sample_near_empty = WindowSample(
        total_requests=20000, error_requests=19
    )  # 19/20 = 95% consumed -> 5% left
    status_near_empty = evaluate_error_budget(sample_30d=sample_near_empty)

    assert status_near_empty.budget_remaining_pct == pytest.approx(5.0, rel=1e-3)
    assert status_near_empty.is_deployment_frozen is True
    assert ERROR_BUDGET_DEPLOYMENT_FROZEN._value.get() == 1.0


def test_rapid_burn_rate_14_4x_detected_and_triggers_freeze() -> None:
    """1-hour rapid burn rate >= 14.4x triggers an immediate deployment freeze."""
    # 1-hour window: 200 requests, 3 errors
    # error rate = 3 / 200 = 0.015 (1.5%)
    # allowed error rate at 99.9% = 0.001 (0.1%)
    # burn rate = 0.015 / 0.001 = 15.0x (> 14.4x threshold)
    sample_1h = WindowSample(total_requests=200, error_requests=3, window_duration_hours=1.0)
    burn_1h = compute_burn_rate(sample_1h, availability_target=0.999)
    assert burn_1h == pytest.approx(15.0, rel=1e-3)

    sample_30d = WindowSample(total_requests=10000, error_requests=2)
    status = evaluate_error_budget(
        sample_30d=sample_30d,
        sample_1h=sample_1h,
    )

    assert status.current_burn_rate_1h >= 14.4
    assert status.is_deployment_frozen is True
    assert "rapid burn active" in status.status_message.lower()
    assert ERROR_BUDGET_BURN_RATE.labels(window="1h")._value.get() == pytest.approx(15.0, rel=1e-3)


def test_elevated_burn_rate_6x_computed_correctly() -> None:
    """6-hour elevated burn rate >= 6.0x is accurately computed."""
    # 6-hour window: 1000 requests, 7 errors
    # error rate = 7 / 1000 = 0.007
    # burn rate = 0.007 / 0.001 = 7.0x (>= 6.0x threshold)
    sample_6h = WindowSample(total_requests=1000, error_requests=7, window_duration_hours=6.0)
    burn_6h = compute_burn_rate(sample_6h, availability_target=0.999)
    assert burn_6h == pytest.approx(7.0, rel=1e-3)


def test_minimum_sample_size_validation() -> None:
    """Input validation must reject observation windows below 1,000 requests."""
    sample_too_small = WindowSample(total_requests=999, error_requests=0)

    with pytest.raises(ValueError, match="below minimum requirement 1000"):
        evaluate_error_budget(sample_30d=sample_too_small)


def test_failsafe_freeze_on_monitoring_blackout() -> None:
    """If monitoring or metric collection fails, fail-safe halts non-essential deployments."""
    status = evaluate_error_budget_failsafe(reason="Prometheus connection timeout")

    assert status.is_deployment_frozen is True
    assert status.budget_remaining_pct == 0.0
    assert "Fail-safe deployment freeze triggered" in status.status_message
    assert ERROR_BUDGET_DEPLOYMENT_FROZEN._value.get() == 1.0


def test_latency_slo_breach_freezes_deployment_when_budget_low() -> None:
    """Latency SLO breach (p95 > 50ms) freezes deployment when remaining budget is < 50%."""
    # 10,000 requests, 6 errors -> 40% budget remaining (< 50%)
    sample_30d = WindowSample(total_requests=10000, error_requests=6)

    # With healthy latency (25ms <= 50ms) -> not frozen (40% > 10% threshold)
    status_healthy_lat = evaluate_error_budget(
        sample_30d=sample_30d,
        latency_p95_ms=25.0,
    )
    assert status_healthy_lat.is_deployment_frozen is False

    # With breached latency (65ms > 50ms) -> frozen
    status_breached_lat = evaluate_error_budget(
        sample_30d=sample_30d,
        latency_p95_ms=65.0,
    )
    assert status_breached_lat.is_deployment_frozen is True
    assert "Latency SLO breached" in status_breached_lat.status_message


def test_calculation_execution_sub_millisecond() -> None:
    """Pure mathematical calculation of error budget and burn rates must execute in <= 1.0ms."""
    sample_30d = WindowSample(total_requests=50000, error_requests=15)
    sample_1h = WindowSample(total_requests=1500, error_requests=1)
    sample_6h = WindowSample(total_requests=8000, error_requests=4)

    # Warmup
    evaluate_error_budget(sample_30d, sample_1h, sample_6h, latency_p95_ms=30.0)

    # 1000 iterations
    start_t = time.perf_counter()
    iterations = 1000
    for _ in range(iterations):
        evaluate_error_budget(sample_30d, sample_1h, sample_6h, latency_p95_ms=30.0)
    elapsed_total = time.perf_counter() - start_t
    avg_ms = (elapsed_total / iterations) * 1000.0

    assert avg_ms <= 1.0, f"Average execution took {avg_ms:.4f}ms, budget is 1.0ms"


def test_prometheus_alert_rules_file_validity() -> None:
    """Verifies that infra/prometheus/rules/alerts.yml defines required SRE alert rules."""
    rules_path = Path("infra/prometheus/rules/alerts.yml")
    assert rules_path.exists(), "Alerts rules file must exist"

    with open(rules_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    groups = data.get("groups", [])
    assert len(groups) >= 1
    rules = groups[0].get("rules", [])

    alert_names = [r.get("alert") for r in rules]
    assert "DocScoutErrorBudgetRapidBurn" in alert_names
    assert "DocScoutErrorBudgetElevatedBurn" in alert_names
    assert "DocScoutDeploymentFrozen" in alert_names

    # Check rapid burn alert configuration
    rapid_burn = next(r for r in rules if r.get("alert") == "DocScoutErrorBudgetRapidBurn")
    assert rapid_burn["labels"]["severity"] == "critical"
    assert rapid_burn["for"] == "2m"
