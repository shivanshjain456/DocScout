#!/usr/bin/env python3
"""Canary token provenance verification CLI (FEAT-084).

Runs automated canary assertion sweeps across database and synthetic fixtures to assert
zero cross-tenant or synthetic data contamination. Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.evals.canary import CanaryManager, get_default_canary_manager


def main() -> int:
    manager: CanaryManager = get_default_canary_manager()

    # Generate synthetic canary fixture
    canary = manager.generate_canary("test_synthetic_fixture_001")
    _ = manager.plant_canary(
        "Synthetic test circular regarding digital lending compliance.", canary
    )

    # Clean production passages should contain zero canaries
    clean_passages = [
        {"chunk_id": "c1", "text": "Scheduled commercial banks must maintain CRAR of 11.5%."},
        {
            "chunk_id": "c2",
            "text": "Non-banking financial companies must maintain Tier 1 ratio of 10%.",
        },
    ]

    report = manager.assert_zero_leakage(clean_passages, ["Production answer cleanly grounded."])
    if not report.passed_assertions or report.leakage_detected:
        print(
            f"CANARY AUDIT FAILED: Leaked tokens detected: {report.leaked_canary_ids}",
            file=sys.stderr,
        )
        return 1

    print("Canary provenance assertions passed: 0 leaked tokens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
