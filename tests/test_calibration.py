"""Tests validating the committed judge calibration artifact per EVAL_PROTOCOL.md §5."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_DIR = REPO_ROOT / "evals" / "calibration" / "20261008T200000Z"
CALIBRATION_JSON = CALIBRATION_DIR / "judge_calibration.json"
DOUBLE_LABELED_JSONL = CALIBRATION_DIR / "double_labeled_sample.jsonl"
REPORT_MD = CALIBRATION_DIR / "calibration_report.md"


def test_calibration_artifacts_exist() -> None:
    assert CALIBRATION_JSON.is_file(), f"missing {CALIBRATION_JSON}"
    assert DOUBLE_LABELED_JSONL.is_file(), f"missing {DOUBLE_LABELED_JSONL}"
    assert REPORT_MD.is_file(), f"missing {REPORT_MD}"


def test_calibration_artifact_schema_and_minimum_size() -> None:
    data = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    assert data["schema"] == "docscout.eval.calibration/1"
    # §5.1 requires 60-100 items
    assert 60 <= data["sample_size"] <= 100
    assert data["strata"]["canaries"] >= 1
    assert data["strata"]["unanswerable"] >= 5


def test_calibration_reports_cohens_kappa_and_rare_class_metrics() -> None:
    data = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    faith = data["faithfulness"]["judge_vs_human"]

    # E-11: kappa and rare class metrics must be reported alongside agreement
    assert "kappa" in faith
    assert "observed_agreement" in faith
    assert "rare_class_f1" in faith
    assert "confusion_matrix" in faith
    assert faith["observed_agreement"] >= 0.85
    assert faith["kappa"] >= 0.70


def test_inter_rater_human_reliability_is_reported() -> None:
    data = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    human = data["faithfulness"]["inter_human"]
    assert human["kappa"] >= 0.70
    assert human["observed_agreement"] >= 0.85


def test_canary_defense_is_one_hundred_percent() -> None:
    data = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    canary = data["canary_resistance"]
    assert canary["pass_rate"] == 1.0
    assert canary["canaries_tested"] == canary["canaries_resisted"]


def test_double_labeled_dataset_lines_match_sample_size() -> None:
    lines = [
        line.strip()
        for line in DOUBLE_LABELED_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    data = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    assert len(lines) == data["sample_size"]

    sample = json.loads(lines[0])
    assert "human_rater_1" in sample
    assert "human_rater_2" in sample
    assert "judge_result" in sample
