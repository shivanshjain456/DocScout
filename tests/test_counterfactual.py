"""Unit and integration tests for Counterfactual Robustness Testing Suite (FEAT-087).

Validates:
1. Input validation constraints on CounterfactualConfig.
2. Canonical generation of 50 synthetic test items across 5 categories.
3. Substantive perturbation correctness with syntactic validity.
4. Grounded answer evaluation achieving >= 98% adherence and zero parametric leakage.
5. Strict parametric leakage detection failing on memorized real-world facts.
6. Unvalidated LLM baseline failing threshold due to 35% parametric leakage.
7. Execution latency budget <= 15.0 seconds.
8. Synthetic data isolation and cleanup guarantees (is_synthetic = True).
9. CLI entrypoint execution and report export.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.evals.counterfactual import (
    CounterfactualConfig,
    CounterfactualEvaluator,
    CounterfactualGenerator,
    CounterfactualItem,
    PerturbationRule,
    get_default_counterfactual_evaluator,
)


def test_input_validation() -> None:
    """Validate boundary rules on CounterfactualConfig parameters."""
    with pytest.raises(ValueError, match="min_robustness_score must be between 0.0 and 1.0"):
        CounterfactualConfig(min_robustness_score=-0.1)

    with pytest.raises(ValueError, match="min_robustness_score must be between 0.0 and 1.0"):
        CounterfactualConfig(min_robustness_score=1.5)

    with pytest.raises(ValueError, match="target_adherence_rate must be between 0.0 and 1.0"):
        CounterfactualConfig(target_adherence_rate=-0.05)

    with pytest.raises(ValueError, match="target_adherence_rate must be between 0.0 and 1.0"):
        CounterfactualConfig(target_adherence_rate=1.05)

    with pytest.raises(ValueError, match="max_execution_seconds must be positive"):
        CounterfactualConfig(max_execution_seconds=0.0)

    cfg = CounterfactualConfig(min_robustness_score=0.95, target_adherence_rate=0.98)
    assert cfg.min_robustness_score == 0.95
    assert cfg.target_adherence_rate == 0.98
    assert cfg.max_execution_seconds == 15.0


def test_canonical_generation_suite() -> None:
    """Verify that exactly 50 canonical items are generated across 5 regulatory categories."""
    generator = CounterfactualGenerator()
    items = generator.generate_suite()

    assert len(items) == 50, f"Expected 50 items, got {len(items)}"

    categories = {item.category for item in items}
    expected_categories = {
        "numeric_amount",
        "ratio_percentage",
        "timeline",
        "penalty_value",
        "entity_name",
    }
    assert categories == expected_categories

    for item in items:
        assert item.is_synthetic is True
        assert item.item_id.startswith("cf-")
        assert len(item.question) > 10
        assert len(item.original_evidence) > 10
        assert len(item.counterfactual_evidence) > 10
        assert len(item.counterfactual_key_points) >= 1
        assert len(item.parametric_forbidden_strings) >= 1
        assert item.perturbation_rule.target_text != item.perturbation_rule.counterfactual_text
        assert item.perturbation_rule.target_text in item.original_evidence
        assert item.perturbation_rule.counterfactual_text in item.counterfactual_evidence


def test_grounded_docscout_achieves_100_percent_adherence() -> None:
    """Assert that grounded DocScout engine achieves 100% adherence and 0% parametric leakage."""
    evaluator = get_default_counterfactual_evaluator()
    items = evaluator.generator.generate_suite()

    grounded_answers = evaluator.simulate_grounded_engine(items)
    result = evaluator.evaluate_suite(grounded_answers, items)

    assert result.items_tested == 50
    assert result.correct_counterfactual_answers == 50
    assert result.parametric_leakage_detected == 0
    assert result.adherence_rate == 1.0
    assert result.robustness_score == 1.0
    assert result.passed is True
    assert result.to_dict()["passed"] is True


def test_parametric_leakage_detection() -> None:
    """Verify that an answer reciting real-world parametric facts triggers leakage detection."""
    evaluator = CounterfactualEvaluator()
    items = evaluator.generator.generate_suite()

    # DRI loan limit item cf-001 (target: ₹15,000, counterfactual: ₹25,000)
    item_cf001 = next(it for it in items if it.item_id == "cf-001")

    # 1. Answer with real-world parametric fact
    leaked_answer = (
        "Under the Differential Rate of Interest scheme, banks provide finance up to ₹15,000 "
        "at 4 per cent per annum."
    )
    res_leak = evaluator.evaluate_answer(item_cf001, leaked_answer)
    assert res_leak.parametric_leakage is True
    assert res_leak.adhered is False
    assert "₹15,000" in res_leak.matched_parametric

    # 2. Answer strictly adhering to counterfactual context
    counterfactual_answer = (
        "Under the Differential Rate of Interest scheme, banks provide finance up to ₹25,000 "
        "at 4 per cent per annum."
    )
    res_cf = evaluator.evaluate_answer(item_cf001, counterfactual_answer)
    assert res_cf.parametric_leakage is False
    assert res_cf.adhered is True
    assert "₹25,000" in res_cf.matched_counterfactual


def test_unvalidated_baseline_fails_threshold() -> None:
    """Verify that unvalidated baseline with 35% parametric leakage fails the robustness gate."""
    evaluator = CounterfactualEvaluator(CounterfactualConfig(min_robustness_score=0.95))
    items = evaluator.generator.generate_suite()

    # Simulate unvalidated LLM baseline that recites memorized real-world facts 35% of the time
    baseline_answers = evaluator.simulate_parametric_engine(items, leakage_rate=0.35)
    result = evaluator.evaluate_suite(baseline_answers, items)

    assert result.items_tested == 50
    assert result.parametric_leakage_detected > 0
    assert result.robustness_score < 0.95
    assert result.passed is False


def test_execution_performance_budget() -> None:
    """Assert that evaluating the complete 50-item suite executes well within the 15-second budget."""
    evaluator = CounterfactualEvaluator()
    items = evaluator.generator.generate_suite()
    grounded_answers = evaluator.simulate_grounded_engine(items)

    start = time.perf_counter()
    result = evaluator.evaluate_suite(grounded_answers, items)
    duration = time.perf_counter() - start

    assert duration <= 15.0, f"Execution took {duration:.2f}s, exceeding 15.0s budget"
    assert result.execution_time_seconds <= 15.0


def test_data_isolation_cleanup() -> None:
    """Assert that synthetic fixtures are strictly marked is_synthetic=True and purged on cleanup."""
    generator = CounterfactualGenerator()
    items = generator.generate_suite()
    assert len(items) == 50
    assert all(it.is_synthetic for it in items)

    purged_count = generator.cleanup()
    assert purged_count == 50
    assert len(generator._synthetic_items) == 0


def test_empty_or_irrelevant_answer_handling() -> None:
    """Verify handling when an engine produces an empty or completely unrelated response."""
    evaluator = CounterfactualEvaluator()
    rule = PerturbationRule(
        target_text="18 months",
        counterfactual_text="30 months",
        category="timeline",
    )
    item = CounterfactualItem(
        item_id="cf-test",
        original_item_id="g-test",
        question="What is the timeline?",
        original_evidence="The timeline is 18 months.",
        counterfactual_evidence="The timeline is 30 months.",
        original_key_points=["18 months"],
        counterfactual_key_points=["30 months"],
        parametric_forbidden_strings=["18 months"],
        perturbation_rule=rule,
        category="timeline",
        is_synthetic=True,
    )

    empty_res = evaluator.evaluate_answer(item, "")
    assert empty_res.adhered is False
    assert empty_res.parametric_leakage is False

    irrelevant_res = evaluator.evaluate_answer(item, "The weather in Mumbai is pleasant today.")
    assert irrelevant_res.adhered is False
    assert irrelevant_res.parametric_leakage is False


def test_cli_script_execution() -> None:
    """Verify that scripts/generate_counterfactuals.py executes and exits 0 in evaluate mode."""
    repo_root = Path(__file__).resolve().parent.parent
    cli_path = repo_root / "scripts" / "generate_counterfactuals.py"

    cmd = [sys.executable, str(cli_path), "--evaluate", "--baseline"]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, check=False)

    assert proc.returncode == 0, (
        f"CLI exited with {proc.returncode}. Output:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "DocScout Gate Passed: True" in proc.stdout
    assert "Baseline Gate Passed: False" in proc.stdout
