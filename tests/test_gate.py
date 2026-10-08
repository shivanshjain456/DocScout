"""Tests for the eval regression gate.

A gate is only worth having if it fails when it should. These tests are written against
`evaluate()`, which is pure, so every rule can be exercised without a database, a model or
a prior run on disk.

The fixtures are shaped like real results.json / baseline records rather than minimal
stubs, because the gate reads nested provenance fields and a stub that omits them would
pass tests the real artifact would fail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.evals import gate

GOLD_SHA = "a" * 64
MANIFEST_SHA = "b" * 64


def make_results(
    *,
    recall: float = 0.97,
    mrr: float = 0.84,
    ndcg: float = 0.86,
    items: int = 131,
    goldset_version: str = "1.0.0",
    goldset_sha: str = GOLD_SHA,
    manifest_sha: str = MANIFEST_SHA,
    chunks: int = 170,
    per_item: dict[str, float] | None = None,
) -> dict[str, Any]:
    per_item = (
        per_item if per_item is not None else {f"g-{i:03d}": 1.0 for i in range(1, items + 1)}
    )
    return {
        "run_utc": "2026-10-02T00:00:00Z",
        "items_scored": items,
        "provenance": {
            "goldset_version": goldset_version,
            "goldset_sha256": goldset_sha,
            "corpus_manifest_digest": manifest_sha,
            "corpus_chunks_in_db": chunks,
        },
        "configs": [
            {
                "config": {"name": "dense-only"},
                "metrics": {"5": {"recall": 0.90, "mrr": 0.70, "ndcg": 0.72}},
                "items": [],
            },
            {
                "config": {"name": gate.SERVING_CONFIG},
                "metrics": {"5": {"recall": recall, "mrr": mrr, "ndcg": ndcg}},
                "items": [{"item_id": k, "recall_at": {"5": v}} for k, v in per_item.items()],
            },
        ],
    }


def make_baseline(
    *,
    run_utc: str = "2026-10-01T00:00:00Z",
    recall: float = 0.97,
    mrr: float = 0.84,
    ndcg: float = 0.86,
    items: int = 131,
    goldset_version: str = "1.0.0",
    goldset_sha: str = GOLD_SHA,
    manifest_sha: str = MANIFEST_SHA,
    chunks: int = 170,
    per_item: dict[str, float] | None = None,
) -> dict[str, Any]:
    per_item = (
        per_item if per_item is not None else {f"g-{i:03d}": 1.0 for i in range(1, items + 1)}
    )
    return {
        "run_utc": run_utc,
        "goldset_version": goldset_version,
        "goldset_sha256": goldset_sha,
        "corpus_manifest_digest": manifest_sha,
        "corpus_chunks_in_db": chunks,
        "items_scored": items,
        "metrics": {"recall": recall, "mrr": mrr, "ndcg": ndcg},
        "per_item_recall": per_item,
    }


def failures(result: gate.GateResult) -> list[str]:
    return [f.message for f in result.findings if f.severity == "fail"]


# --- the 1pp rule ------------------------------------------------------------------------
def test_identical_run_passes() -> None:
    result = gate.evaluate(make_results(), [make_baseline()])
    assert result.passed
    assert failures(result) == []


def test_drop_beyond_one_point_fails() -> None:
    result = gate.evaluate(make_results(recall=0.955), [make_baseline(recall=0.97)])
    assert not result.passed
    assert any("recall@5 fell 1.50pp" in m for m in failures(result))


def test_drop_inside_the_threshold_passes() -> None:
    """0.9pp is within tolerance. The gate must not fail on sub-threshold movement."""
    result = gate.evaluate(make_results(recall=0.961), [make_baseline(recall=0.97)])
    assert result.passed


def test_threshold_is_exclusive_at_exactly_one_point() -> None:
    """Exactly 1.00pp is not 'greater than 1 point' and must pass.

    Pinned because an off-by-one here makes the gate fail builds the specification says
    are acceptable, and the fix would look like loosening the rule.
    """
    result = gate.evaluate(make_results(recall=0.96), [make_baseline(recall=0.97)])
    assert result.passed


def test_regression_in_ranking_alone_fails() -> None:
    """Recall held, MRR collapsed. A gate watching only recall would wave this through."""
    result = gate.evaluate(make_results(mrr=0.80), [make_baseline(mrr=0.84)])
    assert not result.passed
    assert any("mrr@5 fell" in m for m in failures(result))


def test_improvement_passes_and_is_reported() -> None:
    result = gate.evaluate(make_results(recall=0.99), [make_baseline(recall=0.97)])
    assert result.passed
    assert any(f.kind == "improvement" for f in result.findings)


def test_comparison_is_against_the_mean_of_the_window() -> None:
    baselines = [
        make_baseline(run_utc="2026-09-01T00:00:00Z", recall=0.99),
        make_baseline(run_utc="2026-09-15T00:00:00Z", recall=0.97),
        make_baseline(run_utc="2026-10-01T00:00:00Z", recall=0.95),
    ]
    result = gate.evaluate(make_results(recall=0.97), baselines)
    assert result.comparison["recall"]["baseline_mean"] == pytest.approx(0.97)
    assert result.passed


# --- invariants --------------------------------------------------------------------------
def test_gold_set_mutated_without_a_version_bump_fails() -> None:
    """The silent-ruler-swap failure: same version, different contents."""
    result = gate.evaluate(make_results(goldset_sha="c" * 64), [make_baseline()])
    assert not result.passed
    assert any("without a version bump" in m for m in failures(result))


def test_gold_set_version_bump_is_a_warning_not_a_failure() -> None:
    result = gate.evaluate(
        make_results(goldset_version="1.1.0", goldset_sha="c" * 64), [make_baseline()]
    )
    assert result.passed
    assert any(f.severity == "warn" and "different rulers" in f.message for f in result.findings)


def test_corpus_change_fails_because_metrics_are_not_comparable() -> None:
    result = gate.evaluate(make_results(manifest_sha="d" * 64), [make_baseline()])
    assert not result.passed
    assert any("different corpora" in m for m in failures(result))


def test_vanishing_items_fail_even_when_every_metric_improves() -> None:
    """The false green this gate exists to prevent.

    Drop the hard items and recall rises to a perfect score. Without the invariant the
    gate would report an improvement.
    """
    result = gate.evaluate(
        make_results(recall=1.0, mrr=1.0, ndcg=1.0, items=80), [make_baseline(items=131)]
    )
    assert not result.passed
    assert any("items vanished" in m for m in failures(result))


def test_chunk_count_drift_with_an_unchanged_manifest_warns() -> None:
    result = gate.evaluate(make_results(chunks=168), [make_baseline(chunks=170)])
    assert result.passed
    assert any("re-ingest may be incomplete" in f.message for f in result.findings)


# --- the noise floor ---------------------------------------------------------------------
def test_noise_floor_is_reported_when_the_threshold_is_below_it() -> None:
    """A small gold set with scattered per-item differences cannot resolve 1pp."""
    previous = {f"g-{i:03d}": (1.0 if i % 2 else 0.0) for i in range(1, 41)}
    current = {f"g-{i:03d}": (1.0 if i % 3 else 0.0) for i in range(1, 41)}
    result = gate.evaluate(
        make_results(per_item=current, items=40),
        [make_baseline(per_item=previous, items=40)],
    )
    assert result.noise["available"] is True
    assert result.noise["minimum_detectable_effect_pp"] > 1.0
    assert any("below this gold set's noise floor" in f.message for f in result.findings)


def test_noise_floor_degrades_gracefully_without_per_item_data() -> None:
    baseline = make_baseline()
    del baseline["per_item_recall"]
    result = gate.evaluate(make_results(), [baseline])
    assert result.noise["available"] is False
    assert result.passed


# --- bootstrapping and failure modes -----------------------------------------------------
def test_no_baselines_passes_but_says_so() -> None:
    result = gate.evaluate(make_results(), [])
    assert result.passed
    assert any("no accepted baselines yet" in f.message for f in result.findings)


def test_missing_serving_config_is_an_error_not_a_pass() -> None:
    results = make_results()
    results["configs"] = [
        c for c in results["configs"] if c["config"]["name"] != gate.SERVING_CONFIG
    ]
    with pytest.raises(gate.GateError, match="no configuration named"):
        gate.evaluate(results, [make_baseline()])


def test_gate_result_serialises_for_the_raw_artifact() -> None:
    result = gate.evaluate(make_results(recall=0.95), [make_baseline()])
    payload = json.loads(json.dumps(result.as_dict()))
    assert payload["passed"] is False
    assert payload["threshold_pp"] == 1.0
    assert payload["comparison"]["recall"]["delta_pp"] < 0


# --- the real ledger ---------------------------------------------------------------------
def test_committed_baselines_match_the_schema_the_gate_reads() -> None:
    """Guards against a ledger entry that the gate cannot interpret."""
    for path in sorted(gate.BASELINES_DIR.glob("*.json")):
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        assert record["schema"] == "docscout.eval.baseline/1", path
        for key in (
            "run_utc",
            "goldset_version",
            "goldset_sha256",
            "corpus_manifest_digest",
            "items_scored",
            "metrics",
            "per_item_recall",
        ):
            assert key in record, f"{path} missing {key}"
        for metric in gate.GATED_METRICS:
            assert metric in record["metrics"], f"{path} missing metric {metric}"
