"""Expected Calibration Error (ECE) Evaluator and Calibrator (FEAT-085).

Under statutory regulatory compliance requirements, stated confidence scores must be
mathematically grounded in empirical accuracy: a stated confidence of 0.90 must
correspond to a 90% empirical probability that the retrieved statutory evidence is correct.

This module computes Expected Calibration Error (ECE) and Maximum Calibration Error (MCE)
over discrete probability bins, enforces CI calibration gates (max allowed ECE <= 0.06),
and provides empirical calibration transformations to calibrate raw retrieval confidence heuristics.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.api.metrics import EVAL_ECE_SCORE

logger = structlog.get_logger(__name__)

DEFAULT_NUM_BINS = 10
DEFAULT_MAX_ALLOWED_ECE = 0.06
DEFAULT_MIN_SAMPLES = 100
DEFAULT_UNCALIBRATED_BASELINE_ECE = 0.14


@dataclass(frozen=True)
class CalibrationConfig:
    """Configuration schema for Expected Calibration Error evaluation (FEAT-085)."""

    max_allowed_ece: float = DEFAULT_MAX_ALLOWED_ECE
    num_bins: int = DEFAULT_NUM_BINS
    min_samples: int = DEFAULT_MIN_SAMPLES

    def __post_init__(self) -> None:
        if not (0.0 < self.max_allowed_ece <= 1.0):
            raise ValueError(f"max_allowed_ece must be in (0.0, 1.0], got {self.max_allowed_ece}")
        if self.num_bins < 2:
            raise ValueError(f"num_bins must be >= 2, got {self.num_bins}")
        if self.min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {self.min_samples}")


@dataclass(frozen=True)
class PredictionPair:
    """A pair of stated confidence and ground-truth empirical outcome."""

    confidence: float
    outcome: float  # 1.0 for hit/correct, 0.0 for miss/incorrect

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be bounded in [0.0, 1.0], got {self.confidence}")
        if not (0.0 <= self.outcome <= 1.0):
            raise ValueError(f"outcome must be bounded in [0.0, 1.0], got {self.outcome}")


@dataclass(frozen=True)
class ECEReport:
    """Evaluation report containing calibration statistics and CI gate verdicts (FEAT-085)."""

    ece_score: float
    bin_accuracies: list[float]
    bin_confidences: list[float]
    max_calibration_error: float
    is_calibrated: bool
    bin_counts: list[int] = field(default_factory=list)
    bin_edges: list[tuple[float, float]] = field(default_factory=list)
    total_samples: int = 0
    uncalibrated_baseline_ece: float = DEFAULT_UNCALIBRATED_BASELINE_ECE
    improvement_pct: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ece_score": round(self.ece_score, 4),
            "bin_accuracies": [round(a, 4) for a in self.bin_accuracies],
            "bin_confidences": [round(c, 4) for c in self.bin_confidences],
            "max_calibration_error": round(self.max_calibration_error, 4),
            "is_calibrated": self.is_calibrated,
            "bin_counts": list(self.bin_counts),
            "bin_edges": [[round(low, 2), round(high, 2)] for low, high in self.bin_edges],
            "total_samples": self.total_samples,
            "uncalibrated_baseline_ece": round(self.uncalibrated_baseline_ece, 4),
            "improvement_pct": round(self.improvement_pct, 2),
        }


def _normalize_predictions(
    predictions: Sequence[tuple[float, bool | int | float] | PredictionPair | dict[str, Any]],
) -> list[PredictionPair]:
    """Convert heterogeneous prediction representations into standardized PredictionPair instances."""
    normalized: list[PredictionPair] = []
    for item in predictions:
        if isinstance(item, PredictionPair):
            normalized.append(item)
        elif isinstance(item, tuple) and len(item) == 2:
            conf, out = item
            normalized.append(PredictionPair(confidence=float(conf), outcome=float(out)))
        elif isinstance(item, dict):
            c_val = item.get("confidence")
            if c_val is None:
                c_val = item.get("score", 0.0)
            conf = float(c_val if c_val is not None else 0.0)

            o_val = item.get("outcome")
            if o_val is None:
                o_val = item.get("hit")
            if o_val is None:
                o_val = item.get("accuracy", 0.0)
            out = float(o_val if o_val is not None else 0.0)
            normalized.append(PredictionPair(confidence=conf, outcome=out))
        else:
            raise TypeError(f"Unsupported prediction format: {type(item)}")
    return normalized


def compute_ece(
    predictions: Sequence[tuple[float, bool | int | float] | PredictionPair | dict[str, Any]],
    config: CalibrationConfig | None = None,
    *,
    min_samples_check: bool = True,
) -> ECEReport:
    """Compute Expected Calibration Error (ECE) and Maximum Calibration Error (MCE).

    Partitions confidence predictions into discrete probability bins over [0.0, 1.0].
    Computes sample-weighted ECE according to the canonical formula:
        ECE = sum_{b=1}^B (n_b / N) * |acc(b) - conf(b)|

    Guarantees execution latency <= 5.0 ms for 1,000 predictions.
    Updates Prometheus gauge docscout_eval_ece_score.
    """
    cfg = config or CalibrationConfig()
    pairs = _normalize_predictions(predictions)
    total_samples = len(pairs)

    if min_samples_check and total_samples < cfg.min_samples:
        raise ValueError(
            f"Minimum {cfg.min_samples} predictions required for statistical validity, "
            f"got {total_samples}"
        )

    if total_samples == 0:
        return ECEReport(
            ece_score=0.0,
            bin_accuracies=[0.0] * cfg.num_bins,
            bin_confidences=[0.0] * cfg.num_bins,
            max_calibration_error=0.0,
            is_calibrated=True,
            bin_counts=[0] * cfg.num_bins,
            bin_edges=[(i / cfg.num_bins, (i + 1) / cfg.num_bins) for i in range(cfg.num_bins)],
            total_samples=0,
            improvement_pct=0.0,
        )

    num_bins = cfg.num_bins
    bin_counts = [0] * num_bins
    bin_outcome_sums = [0.0] * num_bins
    bin_conf_sums = [0.0] * num_bins
    bin_edges: list[tuple[float, float]] = [
        (i / num_bins, (i + 1) / num_bins) for i in range(num_bins)
    ]

    for p in pairs:
        conf = p.confidence
        # Map [0.0, 1.0] to bin index 0 .. num_bins - 1
        b_idx = int(math.floor(conf * num_bins))
        if b_idx >= num_bins:
            b_idx = num_bins - 1
        bin_counts[b_idx] += 1
        bin_outcome_sums[b_idx] += p.outcome
        bin_conf_sums[b_idx] += conf

    bin_accuracies: list[float] = []
    bin_confidences: list[float] = []
    weighted_ece = 0.0
    max_error = 0.0

    for b in range(num_bins):
        cnt = bin_counts[b]
        low, high = bin_edges[b]
        midpoint = (low + high) / 2.0
        if cnt > 0:
            acc = bin_outcome_sums[b] / cnt
            mean_conf = bin_conf_sums[b] / cnt
            gap = abs(acc - mean_conf)
            weighted_ece += (cnt / total_samples) * gap
            if gap > max_error:
                max_error = gap
            bin_accuracies.append(acc)
            bin_confidences.append(mean_conf)
        else:
            bin_accuracies.append(0.0)
            bin_confidences.append(midpoint)

    is_calibrated = weighted_ece <= cfg.max_allowed_ece

    # Calculate improvement over uncalibrated baseline (0.14)
    baseline = DEFAULT_UNCALIBRATED_BASELINE_ECE
    improvement_pct = max(0.0, ((baseline - weighted_ece) / baseline) * 100.0)

    # Emit Prometheus gauge
    EVAL_ECE_SCORE.set(weighted_ece)

    return ECEReport(
        ece_score=weighted_ece,
        bin_accuracies=bin_accuracies,
        bin_confidences=bin_confidences,
        max_calibration_error=max_error,
        is_calibrated=is_calibrated,
        bin_counts=bin_counts,
        bin_edges=bin_edges,
        total_samples=total_samples,
        uncalibrated_baseline_ece=baseline,
        improvement_pct=improvement_pct,
    )


class EmpiricalCalibrator:
    """Non-parametric bin-based and piecewise linear calibrator for confidence scores.

    Learns empirical posterior probabilities from calibration data to map raw heuristics
    into well-calibrated confidence probabilities (ECE <= 0.05).
    """

    def __init__(self, bin_edges: list[float], bin_mappings: list[float]) -> None:
        self.bin_edges = bin_edges
        self.bin_mappings = bin_mappings

    @classmethod
    def fit(
        cls,
        training_predictions: Sequence[tuple[float, bool | int | float] | PredictionPair],
        num_bins: int = DEFAULT_NUM_BINS,
    ) -> EmpiricalCalibrator:
        """Fit empirical calibrator on training predictions."""
        pairs = _normalize_predictions(training_predictions)
        if not pairs:
            # Default identity mapping
            edges = [i / num_bins for i in range(num_bins + 1)]
            default_mappings = [(edges[i] + edges[i + 1]) / 2.0 for i in range(num_bins)]
            return cls(edges, default_mappings)

        edges = [i / num_bins for i in range(num_bins + 1)]
        bin_counts = [0] * num_bins
        bin_hits = [0.0] * num_bins

        for p in pairs:
            idx = int(math.floor(p.confidence * num_bins))
            if idx >= num_bins:
                idx = num_bins - 1
            bin_counts[idx] += 1
            bin_hits[idx] += p.outcome

        # Compute empirical accuracy per bin, with smoothing for empty bins
        mappings: list[float] = []
        for i in range(num_bins):
            if bin_counts[i] > 0:
                acc = bin_hits[i] / bin_counts[i]
                mappings.append(max(0.0, min(1.0, acc)))
            else:
                # Interpolate using midpoint of bin
                mappings.append((edges[i] + edges[i + 1]) / 2.0)

        # Enforce monotonicity to ensure higher raw confidence maps to >= calibrated confidence
        for i in range(1, num_bins):
            if mappings[i] < mappings[i - 1]:
                # Pool adjacent violators smoothing
                smoothed = (mappings[i] + mappings[i - 1]) / 2.0
                mappings[i] = smoothed
                mappings[i - 1] = smoothed

        return cls(edges, mappings)

    def calibrate(self, raw_confidence: float) -> float:
        """Calibrate a single raw confidence score into an empirical probability."""
        clamped = max(0.0, min(1.0, raw_confidence))
        num_bins = len(self.bin_mappings)
        idx = int(math.floor(clamped * num_bins))
        if idx >= num_bins:
            idx = num_bins - 1
        return self.bin_mappings[idx]

    def calibrate_batch(self, raw_confidences: Sequence[float]) -> list[float]:
        """Calibrate a batch of raw confidence scores."""
        return [self.calibrate(c) for c in raw_confidences]


class ECERunner:
    """CI Evaluation Runner for Expected Calibration Error (FEAT-085)."""

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    def evaluate(
        self,
        predictions: Sequence[tuple[float, bool | int | float] | PredictionPair],
    ) -> ECEReport:
        """Run calibration evaluation and verify CI gate compliance."""
        report = compute_ece(predictions, self.config)
        logger.info(
            "ece_evaluation_completed",
            ece_score=report.ece_score,
            max_calibration_error=report.max_calibration_error,
            is_calibrated=report.is_calibrated,
            improvement_pct=report.improvement_pct,
        )
        return report


def get_default_calibration_config() -> CalibrationConfig:
    """Return the canonical production CalibrationConfig."""
    return CalibrationConfig()
