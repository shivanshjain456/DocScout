"""Tests for Automated Canary Analysis (ACA) Deployment Gate (FEAT-091).

Verifies Mann-Whitney U latency distribution testing, Fisher's exact error rate testing,
100-query minimum sample validation, fail-safe abort on unreachable telemetry,
10ms latency regression detection, sub-2.0s execution performance, and Prometheus metrics.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from infra.canary.analysis import (
    ACAConfig,
    CanaryMetricsSample,
    evaluate_canary_from_prometheus,
    evaluate_canary_sample,
)
from infra.canary.analysis import (
    main as canary_main,
)


def _generate_normal_latencies(
    mean_ms: float,
    std_ms: float,
    count: int,
    seed: int,
) -> list[float]:
    """Generate reproducible latency samples."""
    rng = random.Random(seed)  # noqa: S311
    latencies: list[float] = []
    for _ in range(count):
        val = rng.gauss(mean_ms, std_ms)
        latencies.append(max(1.0, round(val, 2)))
    return latencies


def test_healthy_canary_is_promoted_without_false_positives() -> None:
    """Healthy canary deployment with matching latency and 0 errors must be promoted (zero false positives)."""
    # 200 queries each, mean ~ 25ms, std 3ms, 0 errors
    baseline_lat = _generate_normal_latencies(mean_ms=25.0, std_ms=3.0, count=200, seed=101)
    canary_lat = _generate_normal_latencies(mean_ms=24.8, std_ms=3.0, count=200, seed=102)

    canary = CanaryMetricsSample(
        pod_role="canary",
        latencies_ms=canary_lat,
        total_queries=200,
        error_count=0,
    )
    baseline = CanaryMetricsSample(
        pod_role="baseline",
        latencies_ms=baseline_lat,
        total_queries=200,
        error_count=0,
    )

    cfg = ACAConfig(max_allowed_latency_increase_pct=5.0, max_error_rate=0.001, alpha=0.05)
    decision = evaluate_canary_sample(canary, baseline, config=cfg)

    assert decision.promoted is True
    assert decision.rollback_triggered is False
    assert decision.p_value > 0.05
    assert decision.canary_error_rate == 0.0
    assert decision.latency_delta_pct < 5.0
    assert "Canary verified healthy" in decision.decision_reason

    # Verify output dictionary matches schema
    d_dict = decision.as_dict()
    assert d_dict["schema"] == "docscout.canary.decision/1"
    assert d_dict["promoted"] is True
    assert d_dict["rollback_triggered"] is False


def test_ten_ms_latency_regression_triggers_automated_rollback() -> None:
    """Seeded 10ms latency regression in canary must automatically trigger rollback."""
    # Baseline mean 25ms, Canary mean 35ms (+10ms regression)
    baseline_lat = _generate_normal_latencies(mean_ms=25.0, std_ms=3.0, count=150, seed=201)
    canary_lat = _generate_normal_latencies(mean_ms=35.0, std_ms=3.0, count=150, seed=202)

    canary = CanaryMetricsSample(
        pod_role="canary",
        latencies_ms=canary_lat,
        total_queries=150,
        error_count=0,
    )
    baseline = CanaryMetricsSample(
        pod_role="baseline",
        latencies_ms=baseline_lat,
        total_queries=150,
        error_count=0,
    )

    cfg = ACAConfig(max_allowed_latency_increase_pct=5.0, max_error_rate=0.001, alpha=0.05)
    decision = evaluate_canary_sample(canary, baseline, config=cfg)

    assert decision.promoted is False
    assert decision.rollback_triggered is True
    assert decision.p_value < 0.001
    assert decision.latency_delta_pct > 30.0
    assert (
        "latency regression detected" in decision.decision_reason.lower()
        or "safety limit" in decision.decision_reason.lower()
    )


def test_elevated_error_rate_triggers_automated_rollback() -> None:
    """Error rate exceeding 0.1% or statistically significant error surge must trigger rollback."""
    latencies = _generate_normal_latencies(mean_ms=20.0, std_ms=2.0, count=200, seed=301)

    # Canary has 3 errors out of 200 (1.5% > 0.1% max_error_rate)
    canary = CanaryMetricsSample(
        pod_role="canary",
        latencies_ms=latencies,
        total_queries=200,
        error_count=3,
    )
    baseline = CanaryMetricsSample(
        pod_role="baseline",
        latencies_ms=latencies,
        total_queries=200,
        error_count=0,
    )

    cfg = ACAConfig(max_error_rate=0.001)
    decision = evaluate_canary_sample(canary, baseline, config=cfg)

    assert decision.promoted is False
    assert decision.rollback_triggered is True
    assert decision.canary_error_rate == 0.015
    assert "exceeds maximum allowable threshold" in decision.decision_reason


def test_minimum_sample_size_validation() -> None:
    """Evaluation must reject sample sizes below 100 queries."""
    cfg = ACAConfig(min_queries=100)

    # Canary with 99 queries
    canary = CanaryMetricsSample(
        pod_role="canary",
        latencies_ms=[20.0] * 99,
        total_queries=99,
        error_count=0,
    )
    baseline = CanaryMetricsSample(
        pod_role="baseline",
        latencies_ms=[20.0] * 100,
        total_queries=100,
        error_count=0,
    )

    with pytest.raises(ValueError, match="Canary query count 99 is below minimum"):
        evaluate_canary_sample(canary, baseline, config=cfg)

    # Baseline with 99 queries
    canary_valid = CanaryMetricsSample(
        pod_role="canary",
        latencies_ms=[20.0] * 100,
        total_queries=100,
        error_count=0,
    )
    baseline_invalid = CanaryMetricsSample(
        pod_role="baseline",
        latencies_ms=[20.0] * 50,
        total_queries=50,
        error_count=0,
    )

    with pytest.raises(ValueError, match="Baseline query count 50 is below minimum"):
        evaluate_canary_sample(canary_valid, baseline_invalid, config=cfg)


def test_failsafe_abort_on_unreachable_prometheus() -> None:
    """If Prometheus telemetry is unreachable, fail-safe abort and trigger rollback."""
    # Attempting to query an unreachable local port
    decision = evaluate_canary_from_prometheus(
        canary_endpoint="http://127.0.0.1:59999/metrics",
        baseline_endpoint="http://127.0.0.1:59999/metrics",
    )

    assert decision.promoted is False
    assert decision.rollback_triggered is True
    assert "telemetry unreachable" in decision.decision_reason.lower()


def test_performance_limits_sub_two_seconds() -> None:
    """Statistical evaluation must complete in <= 2.0s for 1000 queries."""
    canary_lat = _generate_normal_latencies(mean_ms=25.0, std_ms=4.0, count=1000, seed=401)
    baseline_lat = _generate_normal_latencies(mean_ms=24.9, std_ms=4.0, count=1000, seed=402)

    canary = CanaryMetricsSample(
        pod_role="canary",
        latencies_ms=canary_lat,
        total_queries=1000,
        error_count=0,
    )
    baseline = CanaryMetricsSample(
        pod_role="baseline",
        latencies_ms=baseline_lat,
        total_queries=1000,
        error_count=0,
    )

    start_t = time.perf_counter()
    decision = evaluate_canary_sample(canary, baseline)
    elapsed = time.perf_counter() - start_t

    assert elapsed < 2.0, f"Analysis took {elapsed:.4f}s, budget is 2.0s"
    assert decision.sample_size_canary == 1000


def test_cli_execution_with_metric_files(tmp_path: Path) -> None:
    """CLI execution must output JSON decision and return exit code 0 on healthy and 1 on rollback."""
    canary_file = tmp_path / "canary.json"
    baseline_file = tmp_path / "baseline.json"

    healthy_canary = {
        "latencies_ms": [20.0] * 120,
        "total_queries": 120,
        "error_count": 0,
    }
    baseline_data = {
        "latencies_ms": [20.0] * 120,
        "total_queries": 120,
        "error_count": 0,
    }

    canary_file.write_text(json.dumps(healthy_canary), encoding="utf-8")
    baseline_file.write_text(json.dumps(baseline_data), encoding="utf-8")

    # Run CLI on healthy data
    code = canary_main(
        [
            "--canary-metrics",
            str(canary_file),
            "--baseline-metrics",
            str(baseline_file),
        ]
    )
    assert code == 0

    # Introduce regression in canary file
    regressed_canary = {
        "latencies_ms": [35.0] * 120,  # 35ms vs 20ms (+75% regression)
        "total_queries": 120,
        "error_count": 5,
    }
    canary_file.write_text(json.dumps(regressed_canary), encoding="utf-8")

    code_regressed = canary_main(
        [
            "--canary-metrics",
            str(canary_file),
            "--baseline-metrics",
            str(baseline_file),
        ]
    )
    assert code_regressed == 1
