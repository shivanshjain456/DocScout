"""Tests for Automated LLM Judge Calibration with Cohen's Kappa (FEAT-090).

Verifies inter-annotator agreement statistics, multiclass evaluation, validation rules,
performance limits (<= 2.0ms for 500 annotations), gate pass/warn/fail logic,
and gold benchmark calibration adherence.
"""

from __future__ import annotations

import time

import pytest

from app.evals.gate import check_judge_calibration_gate_results
from app.evals.judge_calibration import (
    GOLD_JUDGE_HUMAN_BENCHMARK_100,
    JudgeCalibrationConfig,
    calibrate_judge,
    check_judge_calibration_gate,
    evaluate_judge_calibration_suite,
)
from app.evals.stats import (
    compute_kappa_p_value,
)


def test_gold_judge_human_benchmark_calibration_passes() -> None:
    """The 100-item gold benchmark must meet the >= 0.850 Kappa target with high significance."""
    judge_scores = [it["judge_score"] for it in GOLD_JUDGE_HUMAN_BENCHMARK_100]
    human_scores = [it["human_score"] for it in GOLD_JUDGE_HUMAN_BENCHMARK_100]

    assert len(judge_scores) == 100
    assert len(human_scores) == 100

    cfg = JudgeCalibrationConfig(min_kappa=0.85, regression_floor_kappa=0.80)
    report = calibrate_judge(judge_scores, human_scores, config=cfg)

    assert report.is_calibrated is True
    assert report.status == "PASS"
    assert report.sample_size == 100
    assert report.cohen_kappa >= 0.850
    assert pytest.approx(report.cohen_kappa, 0.001) == 0.8746
    assert report.agreement_rate == 0.95
    assert report.p_value < 0.001
    assert report.z_score > 5.0
    assert report.rare_class_metrics is not None
    assert report.rare_class_metrics["rare_class_f1"] > 0.85


def test_degraded_judge_triggers_fail_and_gate_failure() -> None:
    """Degraded automated judges with kappa < 0.80 must trigger status=FAIL and be blocked by the gate."""
    # Create 100 items where judge agrees with human only 70% of the time, resulting in degraded kappa
    human_scores = [1] * 60 + [0] * 40
    # Judge inverts 25 ratings
    judge_scores = [1] * 45 + [0] * 15 + [1] * 10 + [0] * 30

    cfg = JudgeCalibrationConfig(min_kappa=0.85, regression_floor_kappa=0.80)
    report = calibrate_judge(judge_scores, human_scores, config=cfg)

    assert report.is_calibrated is False
    assert report.status == "FAIL"
    assert report.cohen_kappa < 0.80

    passed, msg = check_judge_calibration_gate(report, config=cfg)
    assert passed is False
    assert "below regression floor" in msg

    # Gate findings verification
    findings = check_judge_calibration_gate_results(
        {
            "judge_calibration": {
                "cohen_kappa": report.cohen_kappa,
                "min_kappa": cfg.min_kappa,
                "regression_floor_kappa": cfg.regression_floor_kappa,
            }
        }
    )
    assert len(findings) == 1
    assert findings[0].severity == "fail"
    assert "below regression floor" in findings[0].message


def test_marginal_judge_triggers_warn() -> None:
    """Judges with 0.80 <= kappa < 0.85 must trigger status=WARN without hard-blocking release."""
    # Create a synthetic distribution yielding kappa ~ 0.82
    # 100 pairs with 92 agreements
    human_scores = [1] * 50 + [0] * 50
    # 9 agreements in each block
    judge_scores = [1] * 45 + [0] * 5 + [1] * 4 + [0] * 46

    cfg = JudgeCalibrationConfig(min_kappa=0.85, regression_floor_kappa=0.80)
    report = calibrate_judge(judge_scores, human_scores, config=cfg)

    assert report.is_calibrated is False
    assert report.status == "WARN"
    assert cfg.regression_floor_kappa <= report.cohen_kappa < cfg.min_kappa

    passed, msg = check_judge_calibration_gate(report, config=cfg)
    assert passed is True
    assert "[WARN]" in msg


def test_input_validation_rules() -> None:
    """Input arrays must have identical length and meet the minimum sample size (>= 50)."""
    cfg = JudgeCalibrationConfig(min_sample_size=50)

    # Mismatched lengths
    with pytest.raises(ValueError, match="identical length"):
        calibrate_judge([1] * 50, [1] * 51, config=cfg)

    # Sample size < 50
    with pytest.raises(ValueError, match="below minimum required sample size"):
        calibrate_judge([1] * 49, [1] * 49, config=cfg)


def test_multiclass_categorical_calibration() -> None:
    """Supports arbitrary multiclass string labels (e.g., Likert scale or rubric categories)."""
    categories = ["strong_pass", "pass", "marginal", "fail"]

    # 60 items with strong agreement across 4 classes
    human_scores: list[str] = []
    judge_scores: list[str] = []
    for i in range(60):
        cat = categories[i % 4]
        human_scores.append(cat)
        # 90% perfect agreement, 10% slight divergence
        if i % 10 == 0:
            judge_scores.append(categories[(i + 1) % 4])
        else:
            judge_scores.append(cat)

    cfg = JudgeCalibrationConfig(min_sample_size=50)
    report = calibrate_judge(judge_scores, human_scores, config=cfg)

    assert report.sample_size == 60
    assert set(report.categories) == set(categories)
    assert report.cohen_kappa > 0.80
    assert report.p_value < 0.001
    assert "strong_pass" in report.confusion_matrix


def test_evaluation_suite_multi_dimension() -> None:
    """Suite evaluates multiple judge dimensions simultaneously."""
    judge_evals = {
        "faithfulness": [1] * 50 + [0] * 10,
        "citation_grounding": [1] * 52 + [0] * 8,
        "abstention_accuracy": [1] * 50 + [0] * 10,
    }
    human_evals = {
        "faithfulness": [1] * 48 + [0] * 12,
        "citation_grounding": [1] * 50 + [0] * 10,
        "abstention_accuracy": [1] * 49 + [0] * 11,
    }

    suite_reports = evaluate_judge_calibration_suite(judge_evals, human_evals)
    assert set(suite_reports.keys()) == {
        "faithfulness",
        "citation_grounding",
        "abstention_accuracy",
    }
    for _key, rep in suite_reports.items():
        assert rep.sample_size == 60
        assert rep.cohen_kappa > 0.80


def test_performance_limits_sub_2ms_for_500_items() -> None:
    """Kappa calculation must execute in <= 2.0ms for 500 paired annotations with zero external memory."""
    import random

    rng = random.Random(42)  # noqa: S311

    # Generate 500 paired annotations
    human_scores = [rng.choice([0, 1]) for _ in range(500)]
    judge_scores = [h if rng.random() > 0.05 else (1 - h) for h in human_scores]

    cfg = JudgeCalibrationConfig(min_sample_size=50)

    # Warmup
    calibrate_judge(judge_scores, human_scores, config=cfg)

    # Timed run
    start_t = time.perf_counter()
    iterations = 20
    for _ in range(iterations):
        report = calibrate_judge(judge_scores, human_scores, config=cfg)
    elapsed = (time.perf_counter() - start_t) / iterations

    assert elapsed < 0.002, f"Execution took {elapsed * 1000:.3f}ms, budget is 2.0ms"
    assert report.sample_size == 500
    assert report.cohen_kappa > 0.85


def test_p_value_calculation_bounds() -> None:
    """p-value computation handles edge cases: perfect agreement, zero agreement, and standard normal tails."""
    # Perfect agreement
    z, p = compute_kappa_p_value(1.0, 0.5, 100)
    assert p < 1e-5

    # Zero agreement
    z, p = compute_kappa_p_value(0.0, 0.5, 100)
    assert pytest.approx(z, 0.01) == 0.0
    assert pytest.approx(p, 0.01) == 1.0
