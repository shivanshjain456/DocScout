"""Automated Canary Analysis (ACA) Deployment Infrastructure (FEAT-091)."""

from infra.canary.analysis import (
    ACAConfig,
    CanaryDecision,
    CanaryMetricsSample,
    evaluate_canary_from_prometheus,
    evaluate_canary_sample,
)

__all__ = [
    "ACAConfig",
    "CanaryDecision",
    "CanaryMetricsSample",
    "evaluate_canary_from_prometheus",
    "evaluate_canary_sample",
]
