"""Enforce the U-1 re-scope mechanically.

`EVAL_PROTOCOL.md` §4.1 names the exact failure this module exists to prevent: *"Choosing
(b) silently while still publishing a faithfulness number is the specific failure mode this
section exists to block."* §4.2 then chose (b).

A decision recorded only in prose decays. The pressure to publish a faithfulness number is
real — it is the metric a reader expects from a RAG project, it looks bad to omit, and it
would take one line to invent. So the withdrawal is a test: if a withdrawn metric reappears
as a published number, or a judge role is quietly marked approved, the build fails.

The project already uses this pattern once, in `test_goldset.py`, which asserts the gold
set's metadata claims no Cohen's κ. This generalises it to the whole repository.

Scope note: these tests read documents. That is deliberate and not a category error — the
published claims *are* the artifact being protected, and nothing else checks them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_CONFIG = REPO_ROOT / "config" / "models.json"

# Documents a reader treats as claims about the system. Skills and vendored material are
# excluded: `.claude/skills/` is third-party guidance that legitimately discusses judges in
# the abstract, and rewriting someone else's reference text to satisfy our gate would be
# dishonest in the opposite direction.
PUBLISHED_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "SPEC.md",
    REPO_ROOT / "docs" / "QUALITY_BAR.md",
    REPO_ROOT / "docs" / "MILESTONES.md",
    REPO_ROOT / "docs" / "architecture" / "ARCHITECTURE.md",
    REPO_ROOT / "docs" / "eval" / "EVAL_PROTOCOL.md",
    *sorted((REPO_ROOT / "docs" / "decisions").glob("0*.md")),
    *sorted((REPO_ROOT / "docs" / "verification").glob("*.md")),
]

# A faithfulness/κ figure looks like a metric name followed by a number. The threshold
# statements that survive ("≥ 0.85") are definitions of a withdrawn gate, not results, so
# the pattern deliberately targets *reported values* -- "faithfulness 0.91", "κ = 0.74",
# "faithfulness: 0.88" -- and not the specification text that explains the withdrawal.
REPORTED_VALUE = re.compile(
    r"(faithfulness|answer relevance|context precision|cohen'?s\s+(kappa|κ)|\bκ\b)"
    r"[^.\n|]{0,40}?"
    r"(?<![\d.])(?:=|:|\bis\b|\bof\b|\bat\b|\bscored\b|\bwas\b)\s*"
    r"(0\.\d+|1\.0+)\b",
    re.IGNORECASE,
)

# Statements that would be true only if calibration had happened.
CALIBRATION_CLAIMS = (
    "calibrated judge",
    "judge is calibrated",
    "judge was calibrated",
    "calibration complete",
)


def published_text() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in PUBLISHED_DOCS if path.is_file()]


# --- no withdrawn metric may reappear as a value ----------------------------------------
@pytest.mark.parametrize("path", PUBLISHED_DOCS, ids=lambda p: p.name)
def test_no_withdrawn_metric_is_published_as_a_value(path: Path) -> None:
    """U-1 outcome (b): faithfulness and judge agreement are withdrawn, not pending.

    If this fails, either a real measurement was added -- in which case §5 calibration must
    have run and §4.2's reopening condition must be satisfied and documented -- or a number
    was invented. The second is the reason this test exists.
    """
    if not path.is_file():  # pragma: no cover - a doc being absent is another test's job
        pytest.skip(f"{path.name} not present")
    hits = [m.group(0).strip() for m in REPORTED_VALUE.finditer(path.read_text(encoding="utf-8"))]
    assert not hits, (
        f"{path.name} publishes a withdrawn metric as a value: {hits}. "
        "U-1 closed as outcome (b) (EVAL_PROTOCOL §4.2): faithfulness, answer relevance, "
        "context precision and Cohen's kappa are withdrawn. To publish one, §5 calibration "
        "must actually have run against a real generator."
    )


@pytest.mark.parametrize("path", PUBLISHED_DOCS, ids=lambda p: p.name)
def test_no_document_claims_a_calibrated_judge(path: Path) -> None:
    if not path.is_file():  # pragma: no cover
        pytest.skip(f"{path.name} not present")
    text = path.read_text(encoding="utf-8").lower()
    for claim in CALIBRATION_CLAIMS:
        # "drops the calibrated-judge claim" and similar are withdrawals, not claims.
        for match in re.finditer(re.escape(claim), text):
            window = text[max(0, match.start() - 90) : match.end() + 40]
            # A withdrawal ("drops the calibrated-judge claim") and a precondition
            # ("ships only once the judge is calibrated") both mention calibration without
            # asserting it happened. Only an unqualified assertion may fail this test.
            qualified = any(
                marker in window
                for marker in (
                    "drop",
                    "withdraw",
                    "never",
                    "not ",
                    "no ",
                    "unless",
                    "cannot",
                    "only once",
                    "only after",
                    "would be",
                    "must be",
                    "before any",
                    "if ",
                )
            )
            assert qualified, f"{path.name} asserts a calibrated judge: ...{window}..."


# --- the model configuration must stay consistent with the re-scope ---------------------
def test_no_hosted_role_is_marked_verified() -> None:
    """Phase 0 spend was $0.00 and no key has been provisioned since."""
    config = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
    for role, entry in config.items():
        if role.startswith("_") or not isinstance(entry, dict):
            continue
        if entry.get("local") or role.endswith("_local"):
            continue
        assert entry.get("id") is None, f"{role} names a hosted model id without a credential"
        assert entry.get("verified_at") is None, f"{role} claims live verification"
        assert entry.get("status") != "VERIFIED", f"{role} is marked VERIFIED"


def test_judge_fast_is_not_ci_approved() -> None:
    """§5.4: ci_approved may only become true after >= 0.8 agreement with the strong judge.

    §5 has never run, so this must be false. It is the single flag that would let an
    uncalibrated judge gate the build.
    """
    config = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
    assert config["judge_fast"]["ci_approved"] is False


def test_models_config_records_the_rescope() -> None:
    """The decision must be discoverable from the config, not only from the protocol."""
    config = json.loads(MODELS_CONFIG.read_text(encoding="utf-8"))
    rescope = config.get("_u1_rescope")
    assert rescope is not None, "config/models.json does not record the U-1 decision"
    assert rescope["outcome"] == "b"
    assert rescope["judge_layer"] == "WITHDRAWN"
    assert "EVAL_PROTOCOL" in rescope["recorded_in"]
    # Both conditions, not either -- credentials alone do not reopen it.
    assert len(rescope["reopen_requires"]) == 2


# --- eval reports must not claim a judge ran --------------------------------------------
def test_committed_eval_reports_declare_no_judge() -> None:
    """E-14 provenance carries `judge`; it must stay null while §5 is unexecuted."""
    reports = sorted((REPO_ROOT / "evals" / "reports").glob("*/results.json"))
    assert reports, "no committed eval report to check"
    for report in reports:
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload.get("judge") is None, f"{report} claims a judge"
        assert payload["provenance"]["judge"] is None, f"{report} provenance claims a judge"
        assert payload["provenance"]["generator"] is None, f"{report} claims a generator"


def test_the_protocol_records_the_closure_itself() -> None:
    """Guards against the decision being reverted in prose while the tests stay green."""
    text = (REPO_ROOT / "docs" / "eval" / "EVAL_PROTOCOL.md").read_text(encoding="utf-8")
    assert "U-1 CLOSED" in text
    assert "outcome (b)" in text
    for required in ("Reopening condition", "nothing to judge"):
        assert required.lower() in text.lower(), f"§4.2 is missing: {required}"


# --- the guard must be able to fail ------------------------------------------------------
# A scanner that matches nothing passes forever and protects nothing. These pin the
# detector against text that MUST trip it and text that must not.
@pytest.mark.parametrize(
    "line",
    [
        "Faithfulness: 0.91 on the committed baseline.",
        "faithfulness = 0.88",
        "The judge scored faithfulness at 0.87 against human labels.",
        "Cohen's kappa of 0.74 between the judge and the human labeller.",
        "Context precision is 0.72, above the 0.70 gate.",
        "answer relevance was 0.93",
        "Inter-rater κ = 0.81",
    ],
)
def test_detector_catches_a_published_withdrawn_metric(line: str) -> None:
    assert REPORTED_VALUE.search(line), f"detector missed a violation: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        "| Q-14 | Faithfulness | **≥ 0.85** | WITHDRAWN (U-1) |",
        "Faithfulness is withdrawn as a headline metric; no number is published.",
        "recall@5 is 0.966 and MRR is 0.825.",
        "A judge may never be described as calibrated unless §5 was executed.",
        "no Cohen's kappa is claimed anywhere",
    ],
)
def test_detector_does_not_fire_on_legitimate_text(line: str) -> None:
    """Thresholds, withdrawals and unrelated metrics must pass, or the gate gets disabled."""
    assert not REPORTED_VALUE.search(line), f"false positive on: {line!r}"


def test_guard_fires_on_a_real_document_when_violated(tmp_path: Path) -> None:
    """End-to-end proof: take a real published doc, inject a number, confirm it trips."""
    source = REPO_ROOT / "docs" / "QUALITY_BAR.md"
    poisoned = tmp_path / "QUALITY_BAR.md"
    poisoned.write_text(
        source.read_text(encoding="utf-8") + "\n\nFaithfulness: 0.91 (measured).\n",
        encoding="utf-8",
    )
    assert REPORTED_VALUE.search(poisoned.read_text(encoding="utf-8"))
    assert not REPORTED_VALUE.search(source.read_text(encoding="utf-8"))
