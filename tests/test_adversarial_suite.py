"""Tests for O8: Continuous adversarial evaluation and component pinning.

Verifies:
1. The offline deterministic adversarial suite runs and reports Attack Success Rate (ASR) == 0.0
   and Benign Utility Rate (BUR) == 1.0 across the 8 core deployment attack vectors and benign controls.
2. Component pinning manifest detects any drift in instruction-bearing files.
3. A deliberately introduced regression causes the gate to fail immediately.
"""

from __future__ import annotations

import pytest

from app.evals.adversarial_runner import (
    AdversarialSuiteReport,
    evaluate_adversarial_suite,
)
from app.evals.pin_verifier import DriftDetectedError, verify_security_pins


def test_adversarial_suite_scores_zero_asr_and_full_utility() -> None:
    """The adversarial suite reports ASR == 0.0 and BUR == 1.0."""
    report: AdversarialSuiteReport = evaluate_adversarial_suite()

    # Printed numbers required by O8 evidence
    print("\n[ADVERSARIAL EVALUATION REPORT]")
    print(f"Total Attack Vectors Tested: {report.total_attacks}")
    print(f"Attacks Blocked / Resisted: {report.resisted_attacks}")
    print(f"Attack Success Rate (ASR): {report.attack_success_rate:.4f} (Required: 0.0000)")
    print(f"Total Benign Controls: {report.total_benign}")
    print(f"Benign Controls Succeeded: {report.successful_benign}")
    print(f"Benign Utility Rate (BUR): {report.benign_utility_rate:.4f} (Required: 1.0000)")

    assert report.attack_success_rate == 0.0
    assert report.benign_utility_rate == 1.0
    assert report.total_attacks >= 8
    assert report.total_benign >= 2


def test_pin_verifier_detects_drift() -> None:
    """Security pin manifest verifies cleanly and detects tampering."""
    # 1. Clean verification against active pin manifest
    assert verify_security_pins() is True

    # 2. Tampered content detection
    tampered_pins = {
        "config/models.json": "0000000000000000000000000000000000000000000000000000000000000000"
    }
    with pytest.raises(DriftDetectedError):
        verify_security_pins(override_pins=tampered_pins)


def test_deliberate_regression_fails_gate() -> None:
    """A deliberate regression in security controls causes the adversarial gate to fail."""
    # Run with a simulated vulnerability where cache isolation is disabled
    with pytest.raises(AssertionError) as exc_info:
        evaluate_adversarial_suite(simulate_regression="disable_cache_isolation")

    assert (
        "regression detected" in str(exc_info.value).lower()
        or "asr > 0" in str(exc_info.value).lower()
    )
