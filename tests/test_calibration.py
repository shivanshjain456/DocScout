"""Unit and integration test suite for Expected Calibration Error Evaluator (FEAT-085)."""

import time

import pytest

from app.api.metrics import EVAL_ECE_SCORE
from app.evals.calibration import (
    CalibrationConfig,
    ECEReport,
    ECERunner,
    EmpiricalCalibrator,
    PredictionPair,
    compute_ece,
    get_default_calibration_config,
)


def test_calibration_config_defaults_and_validation() -> None:
    """Verify default parameters and boundary validation in CalibrationConfig."""
    cfg = get_default_calibration_config()
    assert cfg.max_allowed_ece == 0.06
    assert cfg.num_bins == 10
    assert cfg.min_samples == 100

    # Custom valid config
    custom = CalibrationConfig(max_allowed_ece=0.04, num_bins=20, min_samples=50)
    assert custom.max_allowed_ece == 0.04
    assert custom.num_bins == 20
    assert custom.min_samples == 50

    # Invalid max_allowed_ece
    with pytest.raises(ValueError, match="max_allowed_ece must be in"):
        CalibrationConfig(max_allowed_ece=0.0)
    with pytest.raises(ValueError, match="max_allowed_ece must be in"):
        CalibrationConfig(max_allowed_ece=1.5)

    # Invalid num_bins
    with pytest.raises(ValueError, match="num_bins must be >= 2"):
        CalibrationConfig(num_bins=1)

    # Invalid min_samples
    with pytest.raises(ValueError, match="min_samples must be >= 1"):
        CalibrationConfig(min_samples=0)


def test_prediction_pair_validation() -> None:
    """Verify input validation bounds on PredictionPair."""
    valid = PredictionPair(confidence=0.75, outcome=1.0)
    assert valid.confidence == 0.75
    assert valid.outcome == 1.0

    # Confidence out of bounds
    with pytest.raises(ValueError, match="confidence must be bounded"):
        PredictionPair(confidence=-0.1, outcome=1.0)
    with pytest.raises(ValueError, match="confidence must be bounded"):
        PredictionPair(confidence=1.05, outcome=1.0)

    # Outcome out of bounds
    with pytest.raises(ValueError, match="outcome must be bounded"):
        PredictionPair(confidence=0.5, outcome=2.0)
    with pytest.raises(ValueError, match="outcome must be bounded"):
        PredictionPair(confidence=0.5, outcome=-0.5)


def test_compute_ece_perfect_calibration() -> None:
    """Verify that perfectly calibrated predictions achieve ECE = 0.0."""
    # Create 1,000 predictions across 10 bins where in each bin confidence == accuracy
    predictions: list[tuple[float, float]] = []
    # 10 bins: for bin b with center (b + 0.5)/10, put 100 samples
    for b in range(10):
        conf = (b + 0.5) / 10.0
        # To get empirical accuracy == conf, create 100 samples where conf fraction are 1.0
        num_hits = int(round(conf * 100))
        predictions.extend([(conf, 1.0)] * num_hits + [(conf, 0.0)] * (100 - num_hits))

    report = compute_ece(predictions)
    assert len(predictions) == 1000
    assert report.is_calibrated is True
    assert report.ece_score == pytest.approx(0.0, abs=1e-5)
    assert report.max_calibration_error == pytest.approx(0.0, abs=1e-5)


def test_compute_ece_complete_miscalibration() -> None:
    """Verify that completely miscalibrated predictions achieve ECE = 1.0."""
    # 100 predictions with 100% confidence, but 0% accuracy
    predictions = [(1.0, 0.0) for _ in range(100)]
    report = compute_ece(predictions)
    assert report.ece_score == pytest.approx(1.0, abs=1e-5)
    assert report.max_calibration_error == pytest.approx(1.0, abs=1e-5)
    assert report.is_calibrated is False


def test_compute_ece_heterogeneous_input_formats() -> None:
    """Verify tuple, dict, and PredictionPair inputs produce identical ECE."""
    raw_tuples = [(0.8, 1.0)] * 50 + [(0.2, 0.0)] * 50
    dict_inputs = [{"confidence": 0.8, "outcome": 1.0}] * 50 + [{"score": 0.2, "hit": 0.0}] * 50
    obj_inputs = [PredictionPair(0.8, 1.0)] * 50 + [PredictionPair(0.2, 0.0)] * 50

    rep1 = compute_ece(raw_tuples)
    rep2 = compute_ece(dict_inputs)
    rep3 = compute_ece(obj_inputs)

    assert rep1.ece_score == rep2.ece_score == rep3.ece_score
    assert rep1.bin_accuracies == rep2.bin_accuracies == rep3.bin_accuracies


def test_compute_ece_min_samples_enforcement() -> None:
    """Verify that fewer than min_samples triggers ValueError unless check is disabled."""
    few_predictions = [(0.9, 1.0)] * 20
    with pytest.raises(ValueError, match="Minimum 100 predictions required"):
        compute_ece(few_predictions)

    # Allowed when min_samples_check=False
    report = compute_ece(few_predictions, min_samples_check=False)
    assert report.total_samples == 20


def test_empirical_calibrator_fits_and_calibrates() -> None:
    """Verify EmpiricalCalibrator reduces ECE from ~0.14 to <= 0.05 (>= 60% improvement)."""
    import random

    rng = random.Random(42)  # noqa: S311
    # Generate uncalibrated baseline predictions with ECE ~ 0.14
    # Over-confident predictions: raw confidence is higher than true accuracy
    train_pairs: list[tuple[float, float]] = []
    test_pairs: list[tuple[float, float]] = []

    for _ in range(1000):
        raw_conf = rng.uniform(0.1, 0.99)
        # True probability is compressed / lower than stated confidence
        true_prob = max(0.0, raw_conf - 0.15)
        outcome = 1.0 if rng.random() < true_prob else 0.0
        train_pairs.append((raw_conf, outcome))

    for _ in range(1000):
        raw_conf = rng.uniform(0.1, 0.99)
        true_prob = max(0.0, raw_conf - 0.15)
        outcome = 1.0 if rng.random() < true_prob else 0.0
        test_pairs.append((raw_conf, outcome))

    uncalibrated_report = compute_ece(test_pairs)
    assert uncalibrated_report.ece_score > 0.06  # Confirms uncalibrated baseline fails gate

    calibrator = EmpiricalCalibrator.fit(train_pairs, num_bins=10)
    calibrated_test_pairs = [(calibrator.calibrate(conf), outcome) for conf, outcome in test_pairs]

    calibrated_report = compute_ece(calibrated_test_pairs)
    assert isinstance(calibrated_report, ECEReport)
    assert calibrated_report.ece_score <= 0.05
    assert calibrated_report.is_calibrated is True
    assert calibrated_report.improvement_pct >= 60.0


def test_ece_runner_and_report_serialization() -> None:
    """Verify ECERunner execution, report structure, and serialization."""
    runner = ECERunner(CalibrationConfig(max_allowed_ece=0.06, min_samples=50))
    pairs = [(0.5, 0.5)] * 60
    report = runner.evaluate(pairs)

    assert isinstance(report, ECEReport)
    assert EVAL_ECE_SCORE._value.get() == pytest.approx(report.ece_score, abs=1e-5)
    data = report.as_dict()
    assert "ece_score" in data
    assert "bin_accuracies" in data
    assert "bin_confidences" in data
    assert "max_calibration_error" in data
    assert "is_calibrated" in data
    assert "bin_counts" in data
    assert "bin_edges" in data
    assert "total_samples" in data
    assert data["total_samples"] == 60


def test_ece_computation_latency_performance_limit() -> None:
    """Verify ECE calculation over 1,000 predictions executes in <= 5.0 ms."""
    predictions = [(float(i % 100) / 100.0, float(i % 2)) for i in range(1000)]

    # Warmup
    compute_ece(predictions)

    start = time.perf_counter()
    report = compute_ece(predictions)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert report.total_samples == 1000
    # Must be well under the 5.0 ms SLA budget
    assert elapsed_ms <= 5.0
