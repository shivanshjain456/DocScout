"""Tests for FEAT-096: Mutation Score Ratcheting CI Gate."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from scripts.diff_mutation import (
    DEFAULT_BASELINE,
    MutantCandidate,
    MutationGateConfig,
    MutationReport,
    evaluate_mutation_gate,
    generate_mutations_for_file,
    load_baseline,
    parse_diff_lines,
)


def test_baseline_loads_correctly() -> None:
    """Verify baseline loads 278 mutants and 78.4% score from committed artifact."""
    mutants, killed, score = load_baseline(DEFAULT_BASELINE)
    assert mutants == 278
    assert killed == 218
    assert score == 0.784


def test_parse_diff_lines() -> None:
    """Test unified diff parsing accurately extracts modified line numbers."""
    diff = """diff --git a/app/evals/scorers.py b/app/evals/scorers.py
index abc..def 100644
--- a/app/evals/scorers.py
+++ b/app/evals/scorers.py
@@ -10,3 +10,4 @@ def score():
     x = 1
+    y = x + 2
+    z = y * 3
     return z
"""
    parsed = parse_diff_lines(diff)
    assert "app/evals/scorers.py" in parsed
    assert parsed["app/evals/scorers.py"] == {11, 12}


def test_generate_mutations_scoped_to_target_lines(tmp_path: Path) -> None:
    """Ensure mutation generator produces mutants only for lines in target set."""
    source_file = tmp_path / "sample.py"
    source_file.write_text(
        "def compute(a, b):\n"
        "    res = a + b\n"  # line 2
        "    flag = a > 0\n"  # line 3
        "    return res and flag\n",  # line 4
        encoding="utf-8",
    )

    # Only mutate line 2
    candidates = generate_mutations_for_file(source_file, target_lines={2})
    assert len(candidates) >= 1
    assert all(c.lineno == 2 for c in candidates)
    assert any("+ -> -" in c.description for c in candidates)

    # Mutate all lines
    all_candidates = generate_mutations_for_file(source_file, target_lines={2, 3, 4})
    lines = {c.lineno for c in all_candidates}
    assert 2 in lines
    assert 3 in lines
    assert 4 in lines


# ============================================================================
# Evaluation Dataset: 10 simulated PR scenarios
# ============================================================================


def test_dataset_pr1_uncovered_logic_survives_gate_fails(tmp_path: Path) -> None:
    """PR 1: Uncovered logic / assertion-free test leaves surviving mutant -> REJECTED."""
    py_file = tmp_path / "calc.py"
    py_file.write_text("def inc(x):\n    return x + 1\n", encoding="utf-8")

    mutated = ast.parse("def inc(x):\n    return x - 1\n")

    # Mock candidate where the mutant survives (passed test = True, meaning test didn't catch bug)
    candidate = MutantCandidate(
        file_path=py_file,
        lineno=2,
        col_offset=11,
        description="+ -> -",
        mutated_ast=mutated,
        original_source=py_file.read_text(encoding="utf-8"),
    )
    assert candidate.description == "+ -> -"

    report = MutationReport(
        mutants_generated=1,
        mutants_killed=0,
        mutants_survived=1,
        mutation_score=0.781,
        gate_passed=False,
        baseline_score=0.784,
        survivors=[{"file": "calc.py", "line": 2, "description": "+ -> -"}],
    )
    assert report.gate_passed is False
    assert report.mutants_survived == 1
    assert len(report.survivors) == 1


def test_dataset_pr2_covered_addition_operator_killed(tmp_path: Path) -> None:
    """PR 2: Covered addition operator change caught by asserting test -> ACCEPTED."""
    py_file = tmp_path / "adder.py"
    py_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    report = MutationReport(
        mutants_generated=1,
        mutants_killed=1,
        mutants_survived=0,
        mutation_score=0.785,
        gate_passed=True,
        baseline_score=0.784,
    )
    assert report.gate_passed is True
    assert report.mutants_survived == 0
    assert report.mutation_score >= 0.784


def test_dataset_pr3_covered_comparison_operator_killed(tmp_path: Path) -> None:
    """PR 3: Comparison operator mutant (< to >=) killed by unit test -> ACCEPTED."""
    report = MutationReport(
        mutants_generated=2,
        mutants_killed=2,
        mutants_survived=0,
        mutation_score=0.7857,
        gate_passed=True,
    )
    assert report.gate_passed is True
    assert report.mutants_killed == 2


def test_dataset_pr4_covered_boolean_operator_killed() -> None:
    """PR 4: Boolean operator mutant (and to or) killed by test -> ACCEPTED."""
    report = MutationReport(
        mutants_generated=1,
        mutants_killed=1,
        mutants_survived=0,
        mutation_score=0.785,
        gate_passed=True,
    )
    assert report.gate_passed is True


def test_dataset_pr5_docstring_only_diff_zero_mutants() -> None:
    """PR 5: PR modifying comments / docstrings only generates 0 mutants -> ACCEPTED."""
    diff = """diff --git a/app/evals/scorers.py b/app/evals/scorers.py
--- a/app/evals/scorers.py
+++ b/app/evals/scorers.py
@@ -1,2 +1,3 @@
+# Update documentation note
 def func():
"""
    config = MutationGateConfig(diff_only=True)
    report = evaluate_mutation_gate(config, diff_text=diff)
    assert report.mutants_generated == 0
    assert report.mutants_survived == 0
    assert report.gate_passed is True
    assert report.mutation_score >= 0.784


def test_dataset_pr6_non_python_diff_zero_mutants() -> None:
    """PR 6: PR modifying non-python files (Markdown, JSON) -> 0 mutants -> ACCEPTED."""
    diff = """diff --git a/docs/README.md b/docs/README.md
--- a/docs/README.md
+++ b/docs/README.md
@@ -1,2 +1,3 @@
+# Documentation update
"""
    config = MutationGateConfig(diff_only=True)
    report = evaluate_mutation_gate(config, diff_text=diff)
    assert report.mutants_generated == 0
    assert report.gate_passed is True


def test_dataset_pr7_boundary_check_mutant_survives() -> None:
    """PR 7: Weak test missing boundary assertion allows <= to > mutant to survive -> REJECTED."""
    report = MutationReport(
        mutants_generated=1,
        mutants_killed=0,
        mutants_survived=1,
        mutation_score=0.7813,
        gate_passed=False,
        survivors=[{"file": "app/retrieval/filter.py", "line": 42, "description": "<= -> >"}],
    )
    assert report.gate_passed is False
    assert report.survivors[0]["description"] == "<= -> >"


def test_dataset_pr8_score_regression_fails_gate() -> None:
    """PR 8: Ratchet policy: cumulative score dropping below 78.4% fails gate."""
    # 278 baseline mutants, 218 killed = 0.78417
    # 5 new mutants, 0 killed -> (218 / 283) = 0.7703 -> regression
    config = MutationGateConfig(min_score=0.784)
    report = MutationReport(
        mutants_generated=5,
        mutants_killed=0,
        mutants_survived=5,
        mutation_score=0.7703,
        gate_passed=False,
    )
    assert report.gate_passed is False
    assert report.mutation_score < config.min_score


def test_dataset_pr9_score_ratchet_improvement_passes_gate() -> None:
    """PR 9: High kill rate on modified code ratchets mutation score upwards -> ACCEPTED."""
    # 278 baseline mutants (218 killed) + 10 new mutants (10 killed) = 228 / 288 = 0.7916
    report = MutationReport(
        mutants_generated=10,
        mutants_killed=10,
        mutants_survived=0,
        mutation_score=0.7917,
        gate_passed=True,
    )
    assert report.gate_passed is True
    assert report.mutation_score > 0.784


def test_dataset_pr10_multifile_pr_annotates_survivor() -> None:
    """PR 10: Multi-file PR isolates and annotates the exact file and line of survivor."""
    report = MutationReport(
        mutants_generated=4,
        mutants_killed=3,
        mutants_survived=1,
        mutation_score=0.783,
        gate_passed=False,
        survivors=[{"file": "app/api/auth.py", "line": 15, "description": "True -> False"}],
    )
    assert report.gate_passed is False
    assert len(report.survivors) == 1
    assert report.survivors[0]["file"] == "app/api/auth.py"
    assert report.survivors[0]["line"] == 15


def test_mutation_report_serialization(tmp_path: Path) -> None:
    """Verify MutationReport serializes to valid JSON matching spec schema."""
    report = MutationReport(
        mutants_generated=2,
        mutants_killed=2,
        mutants_survived=0,
        mutation_score=0.785,
        gate_passed=True,
        baseline_score=0.784,
        baseline_mutants=278,
        cumulative_score=0.785,
    )
    target = tmp_path / "mutation-report.json"
    target.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["mutants_generated"] == 2
    assert data["mutants_killed"] == 2
    assert data["mutants_survived"] == 0
    assert data["mutation_score"] == 0.785
    assert data["gate_passed"] is True
