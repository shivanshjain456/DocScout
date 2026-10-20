"""Test suite for O9: Incident reconstruction without content retention.

Verifies:
1. Complete request trace correlates identity, entitlement, chunk IDs, trust level, cache outcome,
   citation verdict, and final outcome with ZERO plaintext query, chunk, or answer content.
2. Content capture switch is strictly OFF by default and requires explicit compliance activation.
3. Repeated/anomalous patterns (refusal spikes, boundary violations, probing, integrity failures)
   are visible and alertable.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from app.api.audit import (
    AnomalyDetector,
    ContentCaptureConfig,
    ForensicRequestTrace,
)


def test_forensic_trace_correlates_all_axes_with_zero_content() -> None:
    """A trace correlates all operational axes without retaining any content text."""
    trace = ForensicRequestTrace(
        request_id="req-12345",
        tenant_id="tenant-corp-alpha",
        caller_fingerprint="fp-alice-89ab",
        query_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        entitlement_decision="ALLOW",
        retrieved_chunk_ids=["chunk-001", "chunk-002"],
        integrity_verdict="VERIFIED",
        cache_outcome="TIER1_HIT",
        citation_verdict="VERIFIED",
        final_outcome="SUCCESS",
        latency_ms=42.5,
    )

    data = trace.as_dict()

    # Assert all required axes exist
    assert data["request_id"] == "req-12345"
    assert data["tenant_id"] == "tenant-corp-alpha"
    assert data["caller_fingerprint"] == "fp-alice-89ab"
    assert data["query_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert data["entitlement_decision"] == "ALLOW"
    assert data["retrieved_chunk_ids"] == ["chunk-001", "chunk-002"]
    assert data["integrity_verdict"] == "VERIFIED"
    assert data["cache_outcome"] == "TIER1_HIT"
    assert data["citation_verdict"] == "VERIFIED"
    assert data["final_outcome"] == "SUCCESS"

    # Zero content invariant: verify no raw text appears anywhere in keys or string values
    for k, v in data.items():
        assert k not in ("query_text", "raw_content", "answer_text", "prompt_text")
        if isinstance(v, str) and k != "query_hash":
            assert "secret" not in v.lower()
            assert "confidential" not in v.lower()


def test_content_capture_switch_off_by_default(tmp_path: Path) -> None:
    """Content capture is disabled by default and refuses to record content."""
    # Ensure environment does not have compliance capture enabled
    with patch.dict(os.environ, {}, clear=True):
        config = ContentCaptureConfig()
        assert config.enabled is False, "Content capture must be strictly OFF by default"

        sink = tmp_path / "compliance_sink.jsonl"
        captured = config.capture(
            request_id="req-test",
            raw_query="secret confidential query",
            raw_answer="secret answer",
            destination=sink,
        )
        assert captured is False
        assert not sink.exists(), "No content sink file should be created when capture is disabled"


def test_anomaly_detector_identifies_security_patterns() -> None:
    """AnomalyDetector raises alerts on boundary violations, refusal spikes, and integrity failures."""
    detector = AnomalyDetector(window_size=10, refusal_spike_threshold=0.4)

    # 1. Normal traffic
    for i in range(5):
        detector.record(
            ForensicRequestTrace(
                request_id=f"req-ok-{i}",
                tenant_id="t1",
                caller_fingerprint="fp1",
                query_hash=f"h{i}",
                entitlement_decision="ALLOW",
                retrieved_chunk_ids=[f"c{i}"],
                integrity_verdict="VERIFIED",
                cache_outcome="MISS",
                citation_verdict="VERIFIED",
                final_outcome="SUCCESS",
            )
        )

    alerts_clean = detector.check_anomalies()
    assert len(alerts_clean) == 0

    # 2. Add an integrity failure
    detector.record(
        ForensicRequestTrace(
            request_id="req-tamper",
            tenant_id="t1",
            caller_fingerprint="fp1",
            query_hash="h_tamper",
            entitlement_decision="ALLOW",
            retrieved_chunk_ids=["c_bad"],
            integrity_verdict="TAMPERED",
            cache_outcome="MISS",
            citation_verdict="NONE",
            final_outcome="REFUSED",
        )
    )
    alerts_tamper = detector.check_anomalies()
    assert any("integrity_failure" in a for a in alerts_tamper)

    # 3. Add boundary violations (probing behavior)
    for j in range(4):
        detector.record(
            ForensicRequestTrace(
                request_id=f"req-probe-{j}",
                tenant_id="t1",
                caller_fingerprint="fp_adversary",
                query_hash=f"probe_{j}",
                entitlement_decision="DENIED",
                retrieved_chunk_ids=[],
                integrity_verdict="NONE",
                cache_outcome="MISS",
                citation_verdict="NONE",
                final_outcome="DENIED",
            )
        )

    alerts_probing = detector.check_anomalies()
    assert any("boundary_violation" in a for a in alerts_probing)
    assert any("refusal_spike" in a for a in alerts_probing)
