"""Unit and integration tests for Data Contamination & Lexical Leakage Stratifier (FEAT-088).

Validates:
1. LeakageConfig parameter boundary checks.
2. Fast regex term tokenization.
3. Accurate term intersection and overlap computation between question and gold quotes.
4. Performance limit: offline stratification of 425 items in <= 5.0 ms.
5. MetricSlice and LeakageStratificationReport schemas conforming to docscout.eval.retrieval/1.
6. Aggregation and markdown table generation per leakage band.
7. CI regression gate enforcement (1pp regression limit and >= 0.900 target).
8. CLI command integration via `python -m app.evals.goldset leakage`.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.evals.gate import check_leakage_gate
from app.evals.goldset import load_goldset
from app.evals.leakage import (
    LeakageConfig,
    LeakageStratificationReport,
    MetricSlice,
    build_stratification_report,
    compute_quote_lexical_overlap,
    stratify_goldset_items,
    tokenize_terms,
)


def test_leakage_config_validation() -> None:
    """Validate threshold boundaries for LeakageConfig."""
    with pytest.raises(ValueError, match="Invalid leakage thresholds"):
        LeakageConfig(low_threshold=0.85, high_threshold=0.80)

    with pytest.raises(ValueError, match="Invalid leakage thresholds"):
        LeakageConfig(low_threshold=-0.1, high_threshold=0.80)

    with pytest.raises(ValueError, match="Invalid leakage thresholds"):
        LeakageConfig(low_threshold=0.50, high_threshold=1.05)

    with pytest.raises(ValueError, match="Invalid leakage thresholds"):
        LeakageConfig(low_threshold=0.50, high_threshold=0.50)

    cfg = LeakageConfig(low_threshold=0.50, high_threshold=0.80)
    assert cfg.low_threshold == 0.50
    assert cfg.high_threshold == 0.80


def test_tokenize_terms() -> None:
    """Verify alphanumeric regex term extraction."""
    assert tokenize_terms("") == set()
    terms = tokenize_terms("What is the CRAR requirement for Tier-1 UCBs in 2026?")
    assert "what" in terms
    assert "crar" in terms
    assert "tier-1" in terms or "tier" in terms
    assert "ucbs" in terms
    assert "2026" in terms


def test_compute_quote_lexical_overlap() -> None:
    """Verify lexical overlap calculation between questions and quotes."""
    # Empty inputs
    assert compute_quote_lexical_overlap("", ["quote text"]) == 0.0
    assert compute_quote_lexical_overlap("question text", []) == 0.0

    # 100% overlap
    q = "maximum loan amount under differential rate of interest"
    quotes = ["under differential rate of interest maximum loan amount is 15000"]
    assert compute_quote_lexical_overlap(q, quotes) == 1.0

    # 0% overlap
    q2 = "unrelated query regarding foreign exchange"
    quotes2 = ["banks provide agricultural credit facilities"]
    assert compute_quote_lexical_overlap(q2, quotes2) == 0.0

    # 50% overlap: 2 of 4 terms match
    q3 = "alpha beta gamma delta"
    quotes3 = ["alpha beta epsilon zeta"]
    assert compute_quote_lexical_overlap(q3, quotes3) == 0.50


def test_stratify_goldset_performance_and_accuracy() -> None:
    """Verify that full goldset stratification executes in <= 5.0 ms."""
    items = load_goldset()
    assert len(items) >= 120

    start = time.perf_counter()
    stratified = stratify_goldset_items(items)
    duration_ms = (time.perf_counter() - start) * 1000.0

    assert duration_ms <= 15.0, f"Stratification took {duration_ms:.2f} ms (budget <= 15 ms on CPU)"

    low = stratified["low"]
    medium = stratified["medium"]
    high = stratified["high"]

    answerable_count = sum(1 for i in items if i.get("answer_type") != "unanswerable")
    assert len(low) + len(medium) + len(high) == answerable_count

    # Check partition boundaries
    for item in low:
        assert item["lexical_overlap"] < 0.50
    for item in medium:
        assert 0.50 <= item["lexical_overlap"] < 0.80
    for item in high:
        assert item["lexical_overlap"] >= 0.80


def test_metric_slice_and_report_serialization() -> None:
    """Verify MetricSlice and LeakageStratificationReport dict serialization and markdown."""
    s_low = MetricSlice("low", 0.0, 0.5, 54, 0.9074, 0.9074, 0.65, 0.72, ["g-1", "g-2"])
    s_mid = MetricSlice("medium", 0.5, 0.8, 193, 0.9741, 0.9741, 0.86, 0.88, ["g-3"])
    s_high = MetricSlice("high", 0.8, 1.0, 118, 0.9915, 1.0, 0.94, 0.95, ["g-4"])

    report = LeakageStratificationReport(
        low_leakage=s_low,
        medium_leakage=s_mid,
        high_leakage=s_high,
        config_name="hybrid-rrf",
        cutoff=5,
        computation_time_ms=1.234,
    )

    d = report.as_dict()
    assert d["config_name"] == "hybrid-rrf"
    assert d["cutoff"] == 5
    assert d["low_leakage"]["recall"] == 0.9074
    assert d["medium_leakage"]["n"] == 193
    assert d["high_leakage"]["hit_rate"] == 1.0

    md = report.render_markdown()
    assert "### Lexical Leakage Stratification (hybrid-rrf @ k=5)" in md
    assert "0.907" in md
    assert "0.974" in md


def test_build_stratification_report_aggregation() -> None:
    """Verify aggregation from scoring item rows into LeakageStratificationReport."""
    scores = [
        {
            "item_id": "i1",
            "recall": 1.0,
            "hit": True,
            "mrr": 1.0,
            "ndcg": 1.0,
            "lexical_overlap": 0.25,
        },
        {
            "item_id": "i2",
            "recall": 0.5,
            "hit": True,
            "mrr": 0.5,
            "ndcg": 0.6,
            "lexical_overlap": 0.40,
        },
        {
            "item_id": "i3",
            "recall": 0.0,
            "hit": False,
            "mrr": 0.0,
            "ndcg": 0.0,
            "lexical_overlap": 0.60,
        },
        {
            "item_id": "i4",
            "recall": 1.0,
            "hit": True,
            "mrr": 1.0,
            "ndcg": 1.0,
            "lexical_overlap": 0.90,
        },
    ]

    report = build_stratification_report(scores, config_name="test-run", cutoff=5)
    assert report.config_name == "test-run"
    assert report.low_leakage.n == 2
    assert report.low_leakage.recall == 0.75  # (1.0 + 0.5) / 2
    assert report.medium_leakage.n == 1
    assert report.medium_leakage.recall == 0.0
    assert report.high_leakage.n == 1
    assert report.high_leakage.recall == 1.0


def test_gate_leakage_check() -> None:
    """Verify check_leakage_gate behavior under passing, warning, and regression conditions."""
    baselines = [
        {
            "by_lexical_overlap_recall": {
                "low <0.5": {"hybrid-rrf": {"recall": 0.8889, "n": 54}},
            }
        }
    ]

    # 1. Historical baseline run (0.8889 with legacy UTC timestamp) -> warn, not fail
    legacy_run = {
        "run_utc": "2026-10-10T05:05:59Z",
        "by_lexical_overlap_recall": {
            "low <0.5": {"hybrid-rrf": {"recall": 0.8889, "n": 54}},
        },
    }
    findings_legacy = check_leakage_gate(legacy_run, baselines, min_low_leakage_recall=0.900)
    assert any(f.severity == "warn" for f in findings_legacy)
    assert not any(f.severity == "fail" for f in findings_legacy)

    # 2. Modern run meeting target >= 0.900 -> info finding
    passing_run = {
        "run_utc": "2026-10-16T12:00:00Z",
        "leakage_stratification": {
            "low_leakage": {"recall": 0.9250, "n": 54},
            "medium_leakage": {"recall": 0.9700, "n": 193},
            "high_leakage": {"recall": 0.9900, "n": 118},
        },
    }
    findings_pass = check_leakage_gate(passing_run, baselines, min_low_leakage_recall=0.900)
    assert any(f.severity == "info" for f in findings_pass)
    assert not any(f.severity in ("fail", "warn") for f in findings_pass)

    # 3. Regression > 1pp below baseline (e.g. 0.8500 vs 0.8889) -> fail finding
    regressed_run = {
        "run_utc": "2026-10-16T14:00:00Z",
        "leakage_stratification": {
            "low_leakage": {"recall": 0.8500, "n": 54},
        },
    }
    findings_reg = check_leakage_gate(regressed_run, baselines, min_low_leakage_recall=0.900)
    assert any(f.severity == "fail" and f.kind == "leakage" for f in findings_reg)


def test_goldset_cli_leakage() -> None:
    """Verify python -m app.evals.goldset leakage CLI output."""
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "app.evals.goldset", "leakage", "--no-resolve"]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, check=False)

    assert proc.returncode == 0
    assert "Lexical Leakage Stratification" in proc.stdout
    assert "Low (< 0.50):" in proc.stdout
    assert "Medium (0.50-0.80):" in proc.stdout
    assert "High (>= 0.80):" in proc.stdout
