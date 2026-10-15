"""Unit and benchmark tests for FEAT-084: Canary Token Provenance & Leakage Assertions.

Validates:
1. CanaryConfig defaults and singleton accessor.
2. High-entropy cryptographic canary token generation.
3. Planting canaries into synthetic circular fixtures.
4. Zero-leakage assertions passing on clean production passages.
5. Immediate detection and fail-closed assertion on canary token emergence.
6. Detection of canary tokens emerging inside synthesized answer text.
7. Verification CLI script execution (scripts/verify_canaries.py).
8. Prometheus metrics emission and registration.
9. Execution latency well within the <= 5.0 second CI budget.
"""

from __future__ import annotations

import subprocess
import sys
import time

from app.api import metrics
from app.api.models import Passage
from app.evals.canary import (
    CanaryConfig,
    CanaryManager,
    get_default_canary_manager,
)


def _make_passage(rank: int, chunk_id: str, text: str) -> Passage:
    return Passage(
        rank=rank,
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source="RBI",
        canonical_url=None,
        score=0.95,
        arm_ranks={"dense": rank},
        char_start=0,
        char_end=len(text),
        text=text,
    )


def test_canary_config_defaults() -> None:
    """Validate default configuration values for FEAT-084."""
    cfg = CanaryConfig()
    assert cfg.enforce_zero_leakage_gate is True
    assert cfg.canary_prefix == "CANARY-"

    manager = get_default_canary_manager()
    assert isinstance(manager, CanaryManager)
    assert get_default_canary_manager() is manager


def test_canary_token_generation() -> None:
    """Verify cryptographic tokens are high entropy and unique."""
    manager = CanaryManager()

    t1 = manager.generate_canary("synthetic_fixture_1")
    t2 = manager.generate_canary("synthetic_fixture_2")

    assert t1.token_string.startswith("CANARY-")
    assert len(t1.token_string) == 7 + 32  # Prefix + 16 bytes hex
    assert t1.token_string != t2.token_string
    assert t1.canary_id != t2.canary_id
    assert t1.fixture_name == "synthetic_fixture_1"


def test_canary_planting() -> None:
    """Verify canary token is properly embedded in fixture text."""
    manager = CanaryManager()
    token = manager.generate_canary("fixture_aml")

    base_text = "Master Direction on Know Your Customer (KYC) norms."
    planted_text = manager.plant_canary(base_text, token)

    assert token.token_string in planted_text
    assert base_text in planted_text


def test_zero_leakage_assertion_clean_passages() -> None:
    """Verify clean production passages pass zero-leakage assertions."""
    manager = CanaryManager()
    # Register a token to track
    token = manager.generate_canary("synthetic_test_doc")

    p1 = _make_passage(1, "c1", "Banks must classify assets as NPA after 90 days.")
    p2 = _make_passage(2, "c2", "Housing finance companies must maintain net owned funds.")

    report = manager.assert_zero_leakage([p1, p2], ["A clean production answer."])

    assert report.passed_assertions is True
    assert report.leakage_detected is False
    assert len(report.leaked_canary_ids) == 0
    assert report.canaries_planted >= 1
    assert report.scanned_targets_count == 3
    assert token.token_string not in report.leaked_canary_ids


def test_leakage_assertion_catches_contaminated_passage() -> None:
    """Verify canary token emergence in production evidence trips leakage alert."""
    manager = CanaryManager()
    token = manager.generate_canary("fixture_secret")

    # Contaminated passage contains the planted canary
    contaminated_text = f"Classified synthetic rule. [Tracking: {token.token_string}]"
    p1 = _make_passage(1, "c-bad", contaminated_text)

    report = manager.assert_zero_leakage([p1])

    assert report.passed_assertions is False
    assert report.leakage_detected is True
    assert token.token_string in report.leaked_canary_ids


def test_leakage_assertion_catches_contaminated_answer() -> None:
    """Verify canary token emergence in synthesized answer trips leakage alert."""
    manager = CanaryManager()
    token = manager.generate_canary("fixture_answer")

    clean_p = _make_passage(1, "c-clean", "Regular regulatory passage.")
    bad_answer = f"According to circular, {token.token_string} applies."

    report = manager.assert_zero_leakage([clean_p], [bad_answer])

    assert report.passed_assertions is False
    assert report.leakage_detected is True
    assert token.token_string in report.leaked_canary_ids


def test_cli_verify_canaries_script() -> None:
    """Verify scripts/verify_canaries.py runs and exits 0 on clean state."""
    res = subprocess.run(
        [sys.executable, "scripts/verify_canaries.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "Canary provenance assertions passed: 0 leaked tokens." in res.stdout


def test_prometheus_metrics_registration() -> None:
    """Verify Canary Prometheus metrics are emitted."""
    manager = CanaryManager()
    _token = manager.generate_canary("fixture_metrics")

    # Clean run
    manager.assert_zero_leakage([_make_passage(1, "c1", "Safe text.")])

    body, _ = metrics.render()
    assert b"docscout_canary_audit_runs_total" in body
    assert b"docscout_canary_leakage_detected" in body


def test_execution_latency_budget() -> None:
    """Verify assertion sweep executes in << 5.0s budget."""
    manager = CanaryManager()
    for i in range(15):
        manager.generate_canary(f"synthetic_doc_{i}")

    passages = [
        _make_passage(i, f"chunk-{i}", f"Clean regulatory context sentence number {i}.")
        for i in range(50)
    ]
    answers = [f"Synthesized response number {i} without canaries." for i in range(50)]

    t0 = time.perf_counter()
    report = manager.assert_zero_leakage(passages, answers)
    elapsed_sec = time.perf_counter() - t0

    assert report.passed_assertions is True
    # Spec threshold: <= 5.0 seconds
    assert elapsed_sec <= 0.50, f"Expected sweep < 0.50s, got {elapsed_sec:.4f}s"
