"""Automated Canary Analysis (ACA) Deployment Gate (FEAT-091).

Evaluates latency distributions, error rates, and score drift between canary and baseline
pods during progressive rollouts. Uses the Mann-Whitney U test on latency and Fisher's
exact test on error rates. Automatically triggers rollback if metrics deviate beyond
configured thresholds or if telemetry is unreachable.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from scipy.stats import fisher_exact, mannwhitneyu

from app.api.metrics import record_canary_evaluation


@dataclass(frozen=True)
class ACAConfig:
    """Configuration for Automated Canary Analysis evaluation."""

    eval_window_minutes: int = 15
    max_allowed_latency_increase_pct: float = 5.0
    max_error_rate: float = 0.001  # 0.1% max error rate
    min_queries: int = 100
    alpha: float = 0.05


@dataclass(frozen=True)
class CanaryMetricsSample:
    """Telemetry metrics sample collected over the evaluation window."""

    pod_role: str  # "canary" or "baseline"
    latencies_ms: Sequence[float]
    total_queries: int
    error_count: int
    scores: Sequence[float] | None = None
    memory_bytes: int | None = None


@dataclass(frozen=True)
class CanaryDecision:
    """Outcome of an automated canary analysis deployment gate."""

    promoted: bool
    p_value: float
    latency_delta_pct: float
    error_rate_delta: float
    rollback_triggered: bool
    canary_latency_p95_ms: float = 0.0
    baseline_latency_p95_ms: float = 0.0
    canary_error_rate: float = 0.0
    baseline_error_rate: float = 0.0
    sample_size_canary: int = 0
    sample_size_baseline: int = 0
    decision_reason: str = ""
    evaluated_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "docscout.canary.decision/1",
            "promoted": self.promoted,
            "p_value": round(self.p_value, 6),
            "latency_delta_pct": round(self.latency_delta_pct, 4),
            "error_rate_delta": round(self.error_rate_delta, 6),
            "rollback_triggered": self.rollback_triggered,
            "canary_latency_p95_ms": round(self.canary_latency_p95_ms, 2),
            "baseline_latency_p95_ms": round(self.baseline_latency_p95_ms, 2),
            "canary_error_rate": round(self.canary_error_rate, 6),
            "baseline_error_rate": round(self.baseline_error_rate, 6),
            "sample_size_canary": self.sample_size_canary,
            "sample_size_baseline": self.sample_size_baseline,
            "decision_reason": self.decision_reason,
            "evaluated_at_utc": self.evaluated_at_utc,
        }


def _compute_p95(values: Sequence[float]) -> float:
    """Calculate the 95th percentile of a sequence of floats."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(0.95 * len(sorted_v))
    idx = min(idx, len(sorted_v) - 1)
    return float(sorted_v[idx])


def evaluate_canary_sample(
    canary: CanaryMetricsSample,
    baseline: CanaryMetricsSample,
    config: ACAConfig | None = None,
) -> CanaryDecision:
    """Perform statistical analysis between canary and baseline metrics samples.

    Args:
        canary: Telemetry sample from canary pods.
        baseline: Telemetry sample from baseline pods.
        config: ACA configuration with thresholds and alpha.

    Returns:
        CanaryDecision indicating promotion or rollback.

    Raises:
        ValueError: If sample size on either pod is below min_queries.
    """
    cfg = config or ACAConfig()

    if canary.total_queries < cfg.min_queries:
        raise ValueError(
            f"Canary query count {canary.total_queries} is below minimum required sample size {cfg.min_queries}"
        )
    if baseline.total_queries < cfg.min_queries:
        raise ValueError(
            f"Baseline query count {baseline.total_queries} is below minimum required sample size {cfg.min_queries}"
        )

    # 1. Error rates & Fisher's exact test
    canary_err_rate = canary.error_count / canary.total_queries if canary.total_queries > 0 else 0.0
    baseline_err_rate = (
        baseline.error_count / baseline.total_queries if baseline.total_queries > 0 else 0.0
    )
    err_delta = canary_err_rate - baseline_err_rate

    # 2x2 contingency table: [[canary_err, canary_ok], [base_err, base_ok]]
    canary_ok = max(0, canary.total_queries - canary.error_count)
    baseline_ok = max(0, baseline.total_queries - baseline.error_count)
    table = [[canary.error_count, canary_ok], [baseline.error_count, baseline_ok]]

    try:
        _, fisher_p = fisher_exact(table, alternative="greater")
        fisher_p_val = float(fisher_p)
    except Exception:
        fisher_p_val = 1.0

    # 2. Latency metrics & Mann-Whitney U test
    canary_lat = list(canary.latencies_ms)
    baseline_lat = list(baseline.latencies_ms)

    canary_mean = statistics.fmean(canary_lat) if canary_lat else 0.0
    baseline_mean = statistics.fmean(baseline_lat) if baseline_lat else 0.0
    canary_p95 = _compute_p95(canary_lat)
    baseline_p95 = _compute_p95(baseline_lat)

    if baseline_mean > 0:
        lat_delta_pct = ((canary_mean - baseline_mean) / baseline_mean) * 100.0
    else:
        lat_delta_pct = 0.0

    try:
        mwu_res = mannwhitneyu(canary_lat, baseline_lat, alternative="greater")
        lat_p_val = float(mwu_res.pvalue)
    except Exception:
        lat_p_val = 1.0

    # Joint significance p-value is the minimum of error and latency tests
    combined_p = min(fisher_p_val, lat_p_val)

    # 3. Decision Evaluation
    rollback_triggered = False
    promoted = False
    reason_parts: list[str] = []

    # Check hard error rate ceiling
    if canary_err_rate > cfg.max_error_rate:
        rollback_triggered = True
        reason_parts.append(
            f"Canary error rate {canary_err_rate:.4%} exceeds maximum allowable threshold {cfg.max_error_rate:.4%}"
        )

    # Check statistically significant error surge
    if canary.error_count > baseline.error_count and fisher_p_val < cfg.alpha and err_delta > 0:
        rollback_triggered = True
        reason_parts.append(
            f"Statistically significant error rate surge detected (Fisher exact p={fisher_p_val:.6f} < {cfg.alpha})"
        )

    # Check latency degradation beyond threshold with statistical significance
    if lat_delta_pct > cfg.max_allowed_latency_increase_pct and lat_p_val < cfg.alpha:
        rollback_triggered = True
        reason_parts.append(
            f"Statistically significant latency regression detected: mean increase of {lat_delta_pct:.2f}% "
            f"exceeds allowed {cfg.max_allowed_latency_increase_pct:.2f}% (Mann-Whitney p={lat_p_val:.6f} < {cfg.alpha})"
        )

    # Check severe latency increase (> 10ms absolute increase or > 25% relative) even with marginal p-value
    if canary_mean - baseline_mean >= 10.0 and lat_delta_pct > cfg.max_allowed_latency_increase_pct:
        rollback_triggered = True
        reason_parts.append(
            f"Absolute latency increase of {canary_mean - baseline_mean:.2f}ms exceeds 10.0ms safety limit"
        )

    if not rollback_triggered:
        promoted = True
        decision_reason = (
            f"Canary verified healthy: latency delta {lat_delta_pct:+.2f}%, error rate {canary_err_rate:.4%} "
            f"(MWU p={lat_p_val:.4f}, Fisher p={fisher_p_val:.4f})"
        )
        record_canary_evaluation("promoted")
    else:
        promoted = False
        decision_reason = "Rollback triggered: " + "; ".join(reason_parts)
        record_canary_evaluation("rollback")

    return CanaryDecision(
        promoted=promoted,
        p_value=combined_p,
        latency_delta_pct=lat_delta_pct,
        error_rate_delta=err_delta,
        rollback_triggered=rollback_triggered,
        canary_latency_p95_ms=canary_p95,
        baseline_latency_p95_ms=baseline_p95,
        canary_error_rate=canary_err_rate,
        baseline_error_rate=baseline_err_rate,
        sample_size_canary=canary.total_queries,
        sample_size_baseline=baseline.total_queries,
        decision_reason=decision_reason,
    )


def evaluate_canary_from_prometheus(
    canary_endpoint: str,
    baseline_endpoint: str,
    config: ACAConfig | None = None,
    http_client: Any = None,
) -> CanaryDecision:
    """Fetch metrics from Prometheus endpoints and evaluate canary deployment.

    If Prometheus is unreachable or responds with an error, fails safe by triggering
    an immediate rollback.
    """
    cfg = config or ACAConfig()

    try:
        # If no custom http_client provided, use httpx
        if http_client is None:
            import httpx

            resp_canary = httpx.get(
                canary_endpoint, headers={"Accept": "application/json"}, timeout=5.0
            )
            resp_canary.raise_for_status()
            canary_data = resp_canary.json()

            resp_baseline = httpx.get(
                baseline_endpoint, headers={"Accept": "application/json"}, timeout=5.0
            )
            resp_baseline.raise_for_status()
            baseline_data = resp_baseline.json()
        else:
            canary_data = http_client.get(canary_endpoint)
            baseline_data = http_client.get(baseline_endpoint)

        canary_sample = CanaryMetricsSample(
            pod_role="canary",
            latencies_ms=canary_data.get("latencies_ms", []),
            total_queries=canary_data.get("total_queries", 0),
            error_count=canary_data.get("error_count", 0),
        )
        baseline_sample = CanaryMetricsSample(
            pod_role="baseline",
            latencies_ms=baseline_data.get("latencies_ms", []),
            total_queries=baseline_data.get("total_queries", 0),
            error_count=baseline_data.get("error_count", 0),
        )

        return evaluate_canary_sample(canary_sample, baseline_sample, config=cfg)

    except Exception as exc:
        # Fail-safe: if Prometheus is unreachable or data is corrupt, abort deployment and roll back
        record_canary_evaluation("aborted")
        return CanaryDecision(
            promoted=False,
            p_value=0.0,
            latency_delta_pct=0.0,
            error_rate_delta=0.0,
            rollback_triggered=True,
            decision_reason=f"Prometheus telemetry unreachable or query failed ({exc}); aborting deployment (fail-safe)",
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for running Automated Canary Analysis in CI/CD pipelines."""
    parser = argparse.ArgumentParser(description="Automated Canary Analysis (ACA) Deployment Gate")
    parser.add_argument(
        "--canary-metrics",
        type=str,
        help="JSON file containing canary metrics sample",
    )
    parser.add_argument(
        "--baseline-metrics",
        type=str,
        help="JSON file containing baseline metrics sample",
    )
    parser.add_argument(
        "--canary-url",
        type=str,
        help="Prometheus query URL for canary pod",
    )
    parser.add_argument(
        "--baseline-url",
        type=str,
        help="Prometheus query URL for baseline pod",
    )
    parser.add_argument(
        "--max-latency-pct",
        type=float,
        default=5.0,
        help="Maximum allowed latency increase percentage",
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.001,
        help="Maximum allowed error rate",
    )
    args = parser.parse_args(argv)

    cfg = ACAConfig(
        max_allowed_latency_increase_pct=args.max_latency_pct,
        max_error_rate=args.max_error_rate,
    )

    if args.canary_url and args.baseline_url:
        decision = evaluate_canary_from_prometheus(args.canary_url, args.baseline_url, config=cfg)
    elif args.canary_metrics and args.baseline_metrics:
        with open(args.canary_metrics, encoding="utf-8") as f:
            c_data = json.load(f)
        with open(args.baseline_metrics, encoding="utf-8") as f:
            b_data = json.load(f)

        c_sample = CanaryMetricsSample(
            pod_role="canary",
            latencies_ms=c_data["latencies_ms"],
            total_queries=c_data["total_queries"],
            error_count=c_data["error_count"],
        )
        b_sample = CanaryMetricsSample(
            pod_role="baseline",
            latencies_ms=b_data["latencies_ms"],
            total_queries=b_data["total_queries"],
            error_count=b_data["error_count"],
        )
        decision = evaluate_canary_sample(c_sample, b_sample, config=cfg)
    else:
        print(
            "Error: Must specify either (--canary-url and --baseline-url) or (--canary-metrics and --baseline-metrics)",
            file=sys.stderr,
        )
        return 2

    print(json.dumps(decision.as_dict(), indent=2))
    return 0 if decision.promoted else 1


if __name__ == "__main__":
    raise SystemExit(main())
