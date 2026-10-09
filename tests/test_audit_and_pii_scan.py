"""Tests for durable retrieval audit logging and corpus secret/PII scanning (P1-1).

Verifies:
1. Retrieval events write an append-only, durable audit record to `retrieval_audit_log`.
2. Query privacy: query text is hashed with SHA-256; raw query is NEVER stored by default.
3. Key privacy: key fingerprint is stored; raw API key is NEVER stored.
4. Cache hits and misses both record audit events with latency and chunk IDs.
5. Ingestion-time scanner (`app.ingest.scanner`) detects candidate secrets and PII.
6. Secrets are masked in finding samples; raw secrets never leak into reports.
7. PII findings never block ingestion (preventing false positive outages on public circulars).
8. Synthetic secrets trigger quarantine or warnings per documented policy.
9. Repo-level secret scanning (`gitleaks`) is distinct from extracted corpus text scanning.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest
from starlette.testclient import TestClient

from app.api.audit import (
    RetrievalAuditRecord,
    get_recent_audit_records,
    hash_query,
    record_retrieval_event,
)
from app.config import key_fingerprint
from app.ingest.embed import Embedder
from app.ingest.pipeline import (
    chunk_source_document,
    run_ingest,
)
from app.ingest.scanner import (
    ScanFinding,
    SecretPolicyViolation,
    evaluate_scan_policy,
    scan_text,
)
from app.ingest.source import SourceDocument
from app.ingest.store import Action
from tests.conftest import PRIMARY_KEY, auth

# ======================================================================================
# Part 1: Retrieval Audit Log (OWASP LLM09, G12)
# ======================================================================================


def test_search_writes_durable_retrieval_audit_record(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """A search request writes an audit row recording key fingerprint, query hash, and chunk IDs."""
    expected_fp = key_fingerprint(PRIMARY_KEY)
    query_text = "What is the capital requirement for small finance banks?"
    expected_hash = hash_query(query_text)

    response = client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={"query": query_text, "k": 3, "use_cache": False},
    )
    assert response.status_code == 200
    passages = response.json().get("passages", [])
    assert len(passages) > 0
    expected_chunk_ids = [p["chunk_id"] for p in passages]

    # Query latest audit log entry for this query hash
    records = get_recent_audit_records(app_conn, limit=5)
    matching = [r for r in records if r.query_hash == expected_hash]
    assert len(matching) > 0, "No audit record found for executed query hash"

    record = matching[0]
    assert record.key_fingerprint == expected_fp
    assert record.mode == "hybrid"
    assert record.k == 3
    assert record.returned_chunk_ids == expected_chunk_ids
    assert record.latency_ms > 0.0
    assert record.cache_hit is False


def test_query_and_key_privacy_invariants(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """Audit table stores query hash and key fingerprint, NEVER plaintext query or raw key."""
    unique_query = f"Confidential regulatory query {datetime.now(UTC).timestamp()}"
    query_hash = hash_query(unique_query)

    response = client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={"query": unique_query, "k": 2, "use_cache": False},
    )
    assert response.status_code == 200

    row = app_conn.execute(
        "SELECT * FROM retrieval_audit_log WHERE query_hash = %s", (query_hash,)
    ).fetchone()
    assert row is not None

    # Inspect all row values: neither raw query nor raw API key may appear anywhere
    row_text = " ".join(str(val) for val in row)
    assert unique_query not in row_text, "Plaintext query text leaked into audit log row!"
    assert PRIMARY_KEY not in row_text, "Raw API key leaked into audit log row!"


def test_cache_hit_records_audit_event_with_cache_flag(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """Repeated search hits cache and logs an audit record with cache_hit=True."""
    query = "Settlement timelines for payment aggregators"
    q_hash = hash_query(query)

    # First request: populates cache
    res1 = client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={"query": query, "k": 3, "use_cache": True},
    )
    assert res1.status_code == 200

    # Second request: cache hit
    res2 = client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={"query": query, "k": 3, "use_cache": True},
    )
    assert res2.status_code == 200
    assert res2.json()["timings"]["cache_hit"] is True

    # Check that an audit record with cache_hit=True was created
    records = get_recent_audit_records(app_conn, limit=10)
    hit_records = [r for r in records if r.query_hash == q_hash and r.cache_hit]
    assert len(hit_records) > 0, "No audit record recorded for cache hit"


def test_file_audit_sink_appends_jsonl_record(tmp_path: Path) -> None:
    """When DOCSCOUT_AUDIT_LOG_FILE is set, audit events are written to the JSONL sink."""
    log_file = tmp_path / "retrieval_audit.jsonl"
    record = RetrievalAuditRecord(
        key_fingerprint="fp_test_0001",
        query_hash="a" * 64,
        mode="hybrid",
        k=5,
        returned_chunk_ids=["00000000-0000-0000-0000-000000000001"],
        latency_ms=14.5,
        cache_hit=False,
    )

    with patch.dict("os.environ", {"DOCSCOUT_AUDIT_LOG_FILE": str(log_file)}):
        record_retrieval_event(None, record)

    assert log_file.is_file()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["key_fingerprint"] == "fp_test_0001"
    assert parsed["query_hash"] == "a" * 64
    assert parsed["k"] == 5
    assert parsed["cache_hit"] is False


def test_audit_failure_resilience_does_not_break_search(
    client: TestClient,
) -> None:
    """If database audit insertion fails, search still succeeds with 200 OK."""
    with patch("app.api.app.record_retrieval_event") as mock_record:
        mock_record.side_effect = Exception("Simulated DB connection pool timeout")
        # Search must complete without crashing
        response = client.post(
            "/v1/search",
            headers=auth(PRIMARY_KEY),
            json={"query": "NBFC regulatory framework", "k": 2},
        )
        assert response.status_code == 200
        assert len(response.json()["passages"]) > 0


# ======================================================================================
# Part 2: Corpus Secret and PII Scanning (OWASP LLM02, G13)
# ======================================================================================


def test_scanner_detects_secrets_and_masks_samples() -> None:
    """scan_text detects candidate API keys, private keys, and canary secrets with masked samples."""
    sample_text = (
        "Here is an internal configuration: AWS_KEY="
        + "AKIA"
        + "IOSFODNN7EXAMPLE.\n"
        + "And the private key:\n"
        + "-----BEGIN "
        + "RSA PRIVATE "
        + "KEY-----\nMIIEowIBAAKCAQEA...\n"
        + "-----END "
        + "RSA PRIVATE "
        + "KEY-----\n"
        + "OpenAI API token: "
        + "sk-"
        + "abc12345678901234567890\n"
        + "GitHub token: "
        + "ghp_"
        + "1234567890abcdef1234567890abcdef1234\n"
        + "Canary secret: "
        + "CANARY-SECRET-"
        + "xyz987654321\n"
    )

    findings = scan_text(sample_text)
    secret_findings = [f for f in findings if f.category == "secret"]
    rule_ids = {f.rule_id for f in secret_findings}

    assert "SEC001" in rule_ids  # AWS Key
    assert "SEC002" in rule_ids  # Private Key header
    assert "SEC003" in rule_ids  # GitHub PAT
    assert "SEC005" in rule_ids  # sk- key
    assert "SEC007" in rule_ids  # Canary secret

    # Every secret sample MUST be masked (never plaintext)
    for f in secret_findings:
        assert f.sample_masked != ""
        assert "*" in f.sample_masked or "[redacted" in f.sample_masked


def test_scanner_detects_candidate_pii_and_masks_samples() -> None:
    """scan_text detects emails, phone numbers, PAN, and Aadhaar numbers with masking."""
    sample_text = (
        "For compliance queries, contact nodalofficer@fintech-bank.co.in or call +91 9876543210.\n"
        "Authorized signatory PAN: ABCDE1234F, Aadhaar reference: 9876 5432 1098.\n"
    )

    findings = scan_text(sample_text)
    pii_findings = [f for f in findings if f.category == "pii"]
    rule_ids = {f.rule_id for f in pii_findings}

    assert "PII001" in rule_ids  # Email
    assert "PII002" in rule_ids  # Phone
    assert "PII003" in rule_ids  # PAN
    assert "PII004" in rule_ids  # Aadhaar

    email_finding = next(f for f in pii_findings if f.rule_id == "PII001")
    assert "@" in email_finding.sample_masked
    assert "n***@fintech-bank.co.in" == email_finding.sample_masked

    pan_finding = next(f for f in pii_findings if f.rule_id == "PII003")
    assert pan_finding.sample_masked == "AB***4F"


def test_scan_policy_quarantine_warn_and_fail_modes() -> None:
    """Secrets quarantine or fail per policy; PII findings NEVER block or quarantine."""
    secret_finding = ScanFinding(
        category="secret",
        rule_id="SEC001",
        description="AWS Key",
        char_start=0,
        char_end=20,
        sample_masked="AKIA********MPLE",
        severity="critical",
    )
    pii_finding = ScanFinding(
        category="pii",
        rule_id="PII001",
        description="Email",
        char_start=30,
        char_end=50,
        sample_masked="a***@example.com",
        severity="low",
    )

    # 1. PII alone NEVER quarantines or fails under any policy
    status_pii, is_quarantined_pii = evaluate_scan_policy([pii_finding], policy="fail")
    assert status_pii == "ok"
    assert is_quarantined_pii is False

    # 2. Secret under "warn"
    status_warn, is_quarantined_warn = evaluate_scan_policy([secret_finding], policy="warn")
    assert status_warn == "warn"
    assert is_quarantined_warn is False

    # 3. Secret under "quarantine"
    status_q, is_quarantined_q = evaluate_scan_policy([secret_finding], policy="quarantine")
    assert status_q == "quarantined"
    assert is_quarantined_q is True

    # 4. Secret under "fail"
    with pytest.raises(SecretPolicyViolation):
        evaluate_scan_policy([secret_finding], policy="fail")


def test_chunking_and_ingestion_with_synthetic_secret() -> None:
    """Ingestion pipeline flags candidate secret in document and records it in report."""
    raw_content = (
        b"RESERVE BANK OF INDIA\n"
        b"SYNTHETIC CIRCULAR WITH TEST SECRET\n\n"
        b"Clause 1: All scheduled commercial banks and payment system operators shall configure "
        b"their integration gateways using the provisioned credential key "
        + b"AKIA"
        + b"IOSFODNN7EXAMPLE "
        + b"for quarterly regulatory compliance and central transaction reporting.\n"
        b"Clause 2: Settlement to merchants shall be completed within the established window of "
        b"T+1 working days from the original date of debit or authorization.\n"
        b"Clause 3: Failure to comply with these directions shall attract supervisory penalties "
        b"and statutory action under Section 30 of the Payment and Settlement Systems Act, 2007.\n"
        b"Clause 4: Commercial banks must maintain an immutable audit trail of all settlement events.\n"
        b"For clarifications, contact the designated desk: compliance-desk@rbi.org.in.\n"
    )

    doc = SourceDocument(
        url="https://rbi.example/synthetic-secret-doc",
        source="RBI",
        sha256=hashlib.sha256(raw_content).hexdigest(),
        content=raw_content,
        media_type="text/plain",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=None,
        authority="Reserve Bank of India",
        is_injection_canary=False,
    )

    cut = chunk_source_document(doc, lambda s: max(1, len(s) // 4))
    assert len(cut.secret_findings) >= 1
    assert any(f["rule_id"] == "SEC001" for f in cut.secret_findings)
    assert len(cut.pii_findings) >= 1
    assert any(f["rule_id"] == "PII001" for f in cut.pii_findings)


def test_ingest_quarantine_policy_stops_storing_leaked_document(
    app_conn: psycopg.Connection[Any],
) -> None:
    """When policy is quarantine, a document with candidate secrets is quarantined and not stored."""
    raw_content = (
        b"RESERVE BANK OF INDIA\n"
        b"SECRET LEAK CANARY CIRCULAR\n\n"
        b"Clause 1: The administrative authentication credential "
        + b"CANARY-SECRET-"
        + b"9876543210abcdef "
        + b"shall be utilized for verification of inter-bank high-value clearance operations.\n"
        b"Clause 2: This instruction takes effect immediately across all reporting entities and "
        b"authorized non-bank payment aggregators operating within the domestic settlement zone.\n"
        b"Clause 3: Every reporting institution shall submit monthly balance verification certificates "
        b"duly signed by their designated compliance head and external audit representatives.\n"
        b"Clause 4: In case of discrepancies, immediate reporting must be filed within 24 hours.\n"
    )

    doc = SourceDocument(
        url="https://rbi.example/canary-quarantine-test",
        source="RBI",
        sha256=hashlib.sha256(raw_content).hexdigest(),
        content=raw_content,
        media_type="text/plain",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=None,
        authority="Reserve Bank of India",
        is_injection_canary=False,
    )

    embedder = Embedder()
    with patch.dict("os.environ", {"DOCSCOUT_CORPUS_SECRET_POLICY": "quarantine"}):
        with app_conn.transaction(force_rollback=True):
            report = run_ingest([doc], app_conn, embedder)
            assert report.totals["quarantined"] == 1
            assert report.totals["total_secret_findings"] >= 1
            doc_res = report.documents[0]
            assert doc_res.status == "quarantined"
            assert doc_res.action == str(Action.QUARANTINED)
            assert doc_res.chunks == 0


def test_gitleaks_distinction_repo_vs_corpus() -> None:
    """Clarifies that gitleaks guards git history while the corpus scanner guards runtime text.

    Gitleaks operates via pre-commit and CI on git blobs/diffs.
    Corpus scanner operates at ingestion on extracted text from external regulatory files.
    """
    synthetic_corpus_string = "AKIA" + "IOSFODNN7EXAMPLE"
    findings = scan_text(synthetic_corpus_string)
    assert len(findings) == 1
    assert findings[0].rule_id == "SEC001"
    # Ensure sample is properly masked
    assert findings[0].sample_masked != synthetic_corpus_string
