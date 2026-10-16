"""Tests for FEAT-097: Differential / Patch Coverage Gating (100% Diff Coverage)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.diff_coverage import (
    DiffCoverageConfig,
    DiffCoverageResult,
    evaluate_diff_coverage,
    parse_coverage_xml,
    parse_diff_lines,
)

SAMPLE_COVERAGE_XML = """<?xml version="1.0" ?>
<coverage version="7.16.2">
  <sources>
    <source>C:\\Projects\\3. PERSONAL\\DocScout-2\\docscout\\app</source>
  </sources>
  <packages>
    <package name="api">
      <classes>
        <class name="app.py" filename="api/app.py">
          <lines>
            <line number="10" hits="1"/>
            <line number="11" hits="1"/>
            <line number="12" hits="0"/>
            <line number="13" hits="1"/>
            <line number="14" hits="0"/>
            <line number="20" hits="1"/>
          </lines>
        </class>
        <class name="models.py" filename="api/models.py">
          <lines>
            <line number="5" hits="1"/>
            <line number="6" hits="1"/>
            <line number="7" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def test_parse_coverage_xml() -> None:
    """Verify Cobertura XML parsing extracts line hits per file."""
    data = parse_coverage_xml(SAMPLE_COVERAGE_XML)
    assert "app/api/app.py" in data
    assert data["app/api/app.py"][10] == 1
    assert data["app/api/app.py"][12] == 0
    assert "app/api/models.py" in data
    assert data["app/api/models.py"][5] == 1


def test_parse_diff_lines() -> None:
    """Test unified diff parsing accurately extracts modified line numbers."""
    diff = """diff --git a/app/api/app.py b/app/api/app.py
--- a/app/api/app.py
+++ b/app/api/app.py
@@ -10,3 +10,4 @@ def endpoint():
     x = 1
+    y = 2
+    z = 3
     return z
"""
    diff_map = parse_diff_lines(diff)
    assert "app/api/app.py" in diff_map
    assert diff_map["app/api/app.py"] == {11, 12}


# ============================================================================
# Evaluation Dataset: 20 pull request diff scenarios
# ============================================================================


def test_dataset_pr01_single_line_covered_passes() -> None:
    """PR 01: Single executable modified line, covered -> 100%, PASS."""
    coverage = {"app/api/app.py": {10: 1}}
    diff = "diff --git a/app/api/app.py b/app/api/app.py\n@@ -10,1 +10,1 @@\n+    res = True\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.diff_coverage_pct == 100.0
    assert res.lines_modified == 1
    assert res.lines_covered == 1
    assert len(res.uncovered_lines) == 0


def test_dataset_pr02_single_line_uncovered_fails() -> None:
    """PR 02: Single executable modified line, uncovered (hits=0) -> 0%, FAIL."""
    coverage = {"app/api/app.py": {12: 0}}
    diff = "diff --git a/app/api/app.py b/app/api/app.py\n@@ -12,1 +12,1 @@\n+    bug = False\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert res.diff_coverage_pct == 0.0
    assert res.uncovered_lines == [12]
    assert res.uncovered_by_file["app/api/app.py"] == [12]


def test_dataset_pr03_five_lines_all_covered_passes() -> None:
    """PR 03: 5 modified lines, all 5 executed in test suite -> 100%, PASS."""
    coverage = {"app/api/app.py": {1: 1, 2: 2, 3: 1, 4: 1, 5: 3}}
    diff = "diff --git a/app/api/app.py b/app/api/app.py\n@@ -1,5 +1,5 @@\n+1\n+2\n+3\n+4\n+5\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.diff_coverage_pct == 100.0
    assert res.lines_modified == 5
    assert res.lines_covered == 5


def test_dataset_pr04_partial_coverage_fails() -> None:
    """PR 04: 5 modified lines, 4 covered, 1 missed -> 80.0%, FAIL."""
    coverage = {"app/api/app.py": {1: 1, 2: 1, 3: 1, 4: 1, 5: 0}}
    diff = "diff --git a/app/api/app.py b/app/api/app.py\n@@ -1,5 +1,5 @@\n+1\n+2\n+3\n+4\n+5\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert res.diff_coverage_pct == 80.0
    assert res.uncovered_lines == [5]


def test_dataset_pr05_comments_only_passes() -> None:
    """PR 05: Comments and blank lines (non-executable) do not count as uncovered -> 100%, PASS."""
    # Line 15 is comment, so not present in coverage dict
    coverage = {"app/api/app.py": {10: 1}}
    diff = "diff --git a/app/api/app.py b/app/api/app.py\n@@ -15,1 +15,1 @@\n+# Just a comment\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.lines_modified == 0
    assert res.diff_coverage_pct == 100.0


def test_dataset_pr06_docstrings_only_passes() -> None:
    """PR 06: Docstring modifications only -> 0 executable lines -> 100%, PASS."""
    coverage = {"app/api/app.py": {20: 1}}
    diff = 'diff --git a/app/api/app.py b/app/api/app.py\n@@ -5,1 +5,1 @@\n+    """Docstring update."""\n'
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.lines_modified == 0


def test_dataset_pr07_non_python_files_passes() -> None:
    """PR 07: Changes to Markdown, SQL, or JSON files -> 0 lines -> 100%, PASS."""
    diff = "diff --git a/docs/spec.md b/docs/spec.md\n@@ -1,1 +1,1 @@\n+# Spec\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data={})
    assert res.passed is True
    assert res.lines_modified == 0


def test_dataset_pr08_multifile_pr_all_covered_passes() -> None:
    """PR 08: Multi-file PR where all modified lines are covered -> 100%, PASS."""
    coverage = {
        "app/api/app.py": {10: 1, 11: 1},
        "app/api/models.py": {5: 1, 6: 1},
    }
    diff = (
        "diff --git a/app/api/app.py b/app/api/app.py\n@@ -10,2 +10,2 @@\n+a\n+b\n"
        "diff --git a/app/api/models.py b/app/api/models.py\n@@ -5,2 +5,2 @@\n+c\n+d\n"
    )
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.diff_coverage_pct == 100.0
    assert res.lines_modified == 4
    assert res.lines_covered == 4


def test_dataset_pr09_multifile_pr_one_uncovered_line_fails() -> None:
    """PR 09: Multi-file PR with 1 missed line in secondary file -> FAIL."""
    coverage = {
        "app/api/app.py": {10: 1, 11: 1},
        "app/api/models.py": {5: 1, 6: 0},
    }
    diff = (
        "diff --git a/app/api/app.py b/app/api/app.py\n@@ -10,2 +10,2 @@\n+a\n+b\n"
        "diff --git a/app/api/models.py b/app/api/models.py\n@@ -5,2 +5,2 @@\n+c\n+d\n"
    )
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert res.diff_coverage_pct == 75.0
    assert res.uncovered_lines == [6]
    assert res.uncovered_by_file["app/api/models.py"] == [6]


def test_dataset_pr10_legacy_module_diff_coverage_passes() -> None:
    """PR 10: Legacy file has 50% overall repo coverage, but 100% diff coverage on PR lines -> PASS."""
    # Legacy lines 1..10 are 0 hits, but modified line 20 is 1 hit
    coverage = {"app/legacy.py": {1: 0, 2: 0, 3: 0, 20: 1}}
    diff = "diff --git a/app/legacy.py b/app/legacy.py\n@@ -20,1 +20,1 @@\n+    return safe_val\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.diff_coverage_pct == 100.0
    assert res.lines_modified == 1


def test_dataset_pr11_uncovered_else_branch_fails() -> None:
    """PR 11: PR adds if/else block where else branch (line 12) is never exercised -> FAIL."""
    coverage = {"app/auth.py": {10: 1, 11: 1, 12: 0}}
    diff = "diff --git a/app/auth.py b/app/auth.py\n@@ -10,3 +10,3 @@\n+if valid:\n+    allow()\n+else:\n+    deny()\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert 12 in res.uncovered_lines


def test_dataset_pr12_uncovered_exception_handler_fails() -> None:
    """PR 12: Try/except block where except branch (line 8) is never reached -> FAIL."""
    coverage = {"app/db.py": {6: 1, 7: 1, 8: 0}}
    diff = "diff --git a/app/db.py b/app/db.py\n@@ -6,3 +6,3 @@\n+try:\n+    exec()\n+except DBError:\n+    fallback()\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert 8 in res.uncovered_lines


def test_dataset_pr13_function_definition_and_return_covered() -> None:
    """PR 13: Function definition and return statement both executed in tests -> PASS."""
    coverage = {"app/utils.py": {30: 1, 31: 1}}
    diff = "diff --git a/app/utils.py b/app/utils.py\n@@ -30,2 +30,2 @@\n+def double(x):\n+    return x * 2\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.diff_coverage_pct == 100.0


def test_dataset_pr14_new_untested_helper_fails() -> None:
    """PR 14: New helper function added without any test coverage -> 0%, FAIL."""
    coverage = {"app/helpers.py": {1: 0, 2: 0, 3: 0}}
    diff = "diff --git a/app/helpers.py b/app/helpers.py\n@@ -1,3 +1,3 @@\n+def helper():\n+    x = 1\n+    return x\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert res.diff_coverage_pct == 0.0
    assert len(res.uncovered_lines) == 3


def test_dataset_pr15_custom_threshold_relaxed() -> None:
    """PR 15: Config with required_percentage=90.0% passes on 95%, but 100.0% default fails."""
    # 20 lines: 19 covered, 1 uncovered = 95.0%
    lines = {i: (1 if i < 20 else 0) for i in range(1, 21)}
    coverage = {"app/service.py": lines}
    diff = "diff --git a/app/service.py b/app/service.py\n@@ -1,20 +1,20 @@\n" + "".join(
        f"+{i}\n" for i in range(1, 21)
    )

    strict_cfg = DiffCoverageConfig(required_percentage=100.0)
    strict_res = evaluate_diff_coverage(strict_cfg, diff_text=diff, coverage_data=coverage)
    assert strict_res.passed is False
    assert strict_res.diff_coverage_pct == 95.0

    relaxed_cfg = DiffCoverageConfig(required_percentage=90.0)
    relaxed_res = evaluate_diff_coverage(relaxed_cfg, diff_text=diff, coverage_data=coverage)
    assert relaxed_res.passed is True


def test_dataset_pr16_dataclass_definition_covered() -> None:
    """PR 16: Dataclass definition covered at import time -> 100%, PASS."""
    coverage = {"app/schema.py": {10: 1, 11: 1}}
    diff = "diff --git a/app/schema.py b/app/schema.py\n@@ -10,2 +10,2 @@\n+@dataclass\n+class Config:\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.diff_coverage_pct == 100.0


def test_dataset_pr17_single_line_bug_fix_covered() -> None:
    """PR 17: Single line bug fix covered by unit test assertion -> 100%, PASS."""
    coverage = {"app/fix.py": {42: 1}}
    diff = "diff --git a/app/fix.py b/app/fix.py\n@@ -42,1 +42,1 @@\n+    clean = text.strip()\n"
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.lines_covered == 1


def test_dataset_pr18_twenty_lines_fully_covered() -> None:
    """PR 18: Larger PR with 20 modified lines, all 20 covered -> 100%, PASS."""
    lines = {i: 1 for i in range(1, 21)}
    coverage = {"app/pipeline.py": lines}
    diff = "diff --git a/app/pipeline.py b/app/pipeline.py\n@@ -1,20 +1,20 @@\n" + "".join(
        f"+{i}\n" for i in range(1, 21)
    )
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is True
    assert res.lines_modified == 20
    assert res.lines_covered == 20
    assert res.diff_coverage_pct == 100.0


def test_dataset_pr19_pure_deletion_passes() -> None:
    """PR 19: Pure deletion PR (no added lines) -> 0 modified lines -> 100%, PASS."""
    diff = (
        "diff --git a/app/old.py b/app/old.py\n@@ -10,3 +10,0 @@\n-def deprecated():\n-    pass\n"
    )
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data={})
    assert res.passed is True
    assert res.lines_modified == 0
    assert res.diff_coverage_pct == 100.0


def test_dataset_pr20_complex_refactoring_annotates_uncovered_line() -> None:
    """PR 20: Complex refactoring across 3 files with 1 uncovered edge-case line -> FAIL."""
    coverage = {
        "app/a.py": {1: 1, 2: 1},
        "app/b.py": {10: 1, 11: 1},
        "app/c.py": {50: 1, 51: 0},
    }
    diff = (
        "diff --git a/app/a.py b/app/a.py\n@@ -1,2 +1,2 @@\n+1\n+2\n"
        "diff --git a/app/b.py b/app/b.py\n@@ -10,2 +10,2 @@\n+10\n+11\n"
        "diff --git a/app/c.py b/app/c.py\n@@ -50,2 +50,2 @@\n+50\n+51\n"
    )
    res = evaluate_diff_coverage(DiffCoverageConfig(), diff_text=diff, coverage_data=coverage)
    assert res.passed is False
    assert res.lines_modified == 6
    assert res.lines_covered == 5
    assert res.diff_coverage_pct == 83.33
    assert res.uncovered_lines == [51]
    assert "app/c.py" in res.uncovered_by_file
    assert res.uncovered_by_file["app/c.py"] == [51]


def test_diff_coverage_result_serialization(tmp_path: Path) -> None:
    """Verify DiffCoverageResult serializes to valid JSON matching spec schema."""
    result = DiffCoverageResult(
        lines_modified=10,
        lines_covered=10,
        diff_coverage_pct=100.0,
        uncovered_lines=[],
        passed=True,
    )
    target = tmp_path / "diff-coverage.json"
    target.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["lines_modified"] == 10
    assert data["lines_covered"] == 10
    assert data["diff_coverage_pct"] == 100.0
    assert data["uncovered_lines"] == []
    assert data["passed"] is True
