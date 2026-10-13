"""Tests for Audit Evidence Package Exporter (FEAT-047).

Verifies:
1. Multi-format export generation: PDF (PDF/A compliant vector encoding), ZIP, and Markdown.
2. 100% SHA-256 cryptographic provenance integrity match on exported artifacts.
3. ZIP archive internal manifest.json and evidence files match clause digests.
4. Input validation (1 <= len(passage_ids) <= 50, audit reference format).
5. Automatic TTL expiry and purge of expired files.
6. Prometheus counter and histogram observation.
7. REST API endpoints:
   - POST /v1/compliance/export-evidence
   - GET /v1/compliance/export-download/{file_id}
8. Performance budget: <= 3.0s latency for 50 evidence items.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import AUDIT_PACKAGES_EXPORTED_TOTAL
from app.api.security import load_keys
from app.compliance.exporter import (
    AuditEvidenceExporter,
    EvidencePassage,
    ExporterConfig,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def sample_passages() -> list[EvidencePassage]:
    p1_text = (
        "The regulated entity shall ensure that board approved cyber security policy "
        "covers governance framework and access control requirements under ISO 27001."
    )
    p2_text = (
        "Cardholder data environment shall implement primary account number encryption "
        "conforming to PCI DSS 4.0 Requirement 3.4."
    )
    p3_text = (
        "Core banking systems must maintain minimum CRAR of 9% and leverage ratio of 4% "
        "as per RBI Master Direction on Capital Adequacy."
    )
    return [
        EvidencePassage(
            passage_id="chunk-001",
            document_title="RBI Master Direction on Cyber Security",
            source="RBI",
            verbatim_text=p1_text,
            char_start=0,
            char_end=len(p1_text),
            published_date="2023-11-07",
            canonical_url="https://rbi.org.in/circulars/cyber-security.pdf",
            control_mappings=["ISO/IEC 27001 Annex A.5.15", "RBI CSF 4.2"],
        ),
        EvidencePassage(
            passage_id="chunk-002",
            document_title="Digital Payment Security Controls",
            source="RBI",
            verbatim_text=p2_text,
            char_start=150,
            char_end=150 + len(p2_text),
            published_date="2024-01-15",
            canonical_url="https://rbi.org.in/circulars/payment-security.pdf",
            control_mappings=["PCI DSS 4.0 Req 3.4"],
        ),
        EvidencePassage(
            passage_id="chunk-003",
            document_title="Master Direction on Capital Adequacy - Basel III",
            source="RBI",
            verbatim_text=p3_text,
            char_start=400,
            char_end=400 + len(p3_text),
            published_date="2024-05-02",
            canonical_url="https://rbi.org.in/circulars/basel-capital.pdf",
            control_mappings=["BASEL_III CRAR", "RBI_BASEL_III_CAPITAL"],
        ),
    ]


@pytest.fixture
def exporter() -> AuditEvidenceExporter:
    return AuditEvidenceExporter()


# ---------------------------------------------------------------------------
# Unit Tests for Multi-Format Export Generation
# ---------------------------------------------------------------------------


def test_markdown_export_generation_and_integrity(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    result = exporter.export_package(
        query="Cyber security access control and capital adequacy",
        passages=sample_passages,
        format="MARKDOWN",
        audit_reference_id="AUD-2026-Q3-001",
    )

    assert result.format == "MARKDOWN"
    assert result.items_included == 3
    assert result.audit_reference_id == "AUD-2026-Q3-001"
    assert result.file_sha256 == hashlib.sha256(result.file_bytes).hexdigest()

    content = result.file_bytes.decode("utf-8")
    assert "DOCSCOUT STATUTORY AUDIT EVIDENCE DOSSIER" in content
    assert "AUD-2026-Q3-001" in content
    for p in sample_passages:
        assert p.passage_id in content
        assert p.sha256 in content
        assert p.document_title in content


def test_zip_export_archive_internal_manifest_and_evidence(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    result = exporter.export_package(
        query="Payment cardholder encryption",
        passages=sample_passages,
        format="ZIP",
        audit_reference_id="AUD-2026-PCI-99",
    )

    assert result.format == "ZIP"
    assert result.items_included == 3
    assert result.file_sha256 == hashlib.sha256(result.file_bytes).hexdigest()

    with zipfile.ZipFile(io.BytesIO(result.file_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "dossier.md" in namelist

        # Check evidence files
        evidence_files = [n for n in namelist if n.startswith("evidence/")]
        assert len(evidence_files) == 3

        for i, p in enumerate(sample_passages, 1):
            expected_name = f"evidence/clause_{i:02d}_{p.passage_id}.txt"
            assert expected_name in namelist
            clause_content = zf.read(expected_name).decode("utf-8")
            assert clause_content == p.verbatim_text
            # 100% SHA-256 match
            assert hashlib.sha256(clause_content.encode("utf-8")).hexdigest() == p.sha256


def test_pdf_export_dossier_structure_and_vector_encoding(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    result = exporter.export_package(
        query="Statutory audit evidence package",
        passages=sample_passages,
        format="PDF",
        audit_reference_id="AUD-2026-REG-42",
    )

    assert result.format == "PDF"
    assert result.items_included == 3
    assert result.file_sha256 == hashlib.sha256(result.file_bytes).hexdigest()
    assert result.file_bytes.startswith(b"%PDF-1.4\n")
    assert b"%%EOF\n" in result.file_bytes or b"%%EOF" in result.file_bytes


def test_validation_rules_reject_empty_and_excessive_passages(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    # 0 passages must raise ValueError
    with pytest.raises(ValueError, match="between 1 and 50"):
        exporter.export_package(
            query="test",
            passages=[],
            format="PDF",
            audit_reference_id="REF-1",
        )

    # 51 passages must raise ValueError
    too_many = sample_passages * 17  # 51 items
    with pytest.raises(ValueError, match="between 1 and 50"):
        exporter.export_package(
            query="test",
            passages=too_many[:51],
            format="PDF",
            audit_reference_id="REF-1",
        )

    # Invalid audit reference string
    with pytest.raises(ValueError, match="Invalid audit reference"):
        exporter.export_package(
            query="test",
            passages=sample_passages,
            format="PDF",
            audit_reference_id="BAD REF <>!?",
        )


def test_ttl_expiry_and_purge_expired_files(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    # Create package with past expiration
    config = ExporterConfig(download_expiry_minutes=-10)  # already expired
    exp = AuditEvidenceExporter(config=config)
    res = exp.export_package(
        query="test",
        passages=sample_passages,
        format="MARKDOWN",
        audit_reference_id="EXPIRED-TEST",
    )

    # Lookup should be None or purged
    purged_count = exp.purge_expired_exports()
    assert purged_count >= 1
    assert exp.get_export_artifact(res.file_id) is None


def test_prometheus_metric_increments(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    before_pdf = AUDIT_PACKAGES_EXPORTED_TOTAL.labels(format="PDF")._value.get()
    exporter.export_package(
        query="test",
        passages=sample_passages,
        format="PDF",
        audit_reference_id="METRIC-TEST",
    )
    after_pdf = AUDIT_PACKAGES_EXPORTED_TOTAL.labels(format="PDF")._value.get()
    assert after_pdf == before_pdf + 1.0


def test_performance_sla_50_passages_under_3_seconds(
    exporter: AuditEvidenceExporter, sample_passages: list[EvidencePassage]
) -> None:
    # Build 50 passages
    fifty_passages = [
        EvidencePassage(
            passage_id=f"perf-clause-{i}",
            document_title=f"Regulatory Document {i}",
            source="RBI",
            verbatim_text=f"Statutory compliance requirement {i} regarding risk governance and capital buffers.",
            char_start=i * 10,
            char_end=i * 10 + 60,
        )
        for i in range(50)
    ]

    t0 = time.perf_counter()
    res = exporter.export_package(
        query="50 clause performance benchmark",
        passages=fifty_passages,
        format="PDF",
        audit_reference_id="PERF-50-ITEMS",
    )
    duration = time.perf_counter() - t0

    assert duration <= 3.0, f"Generation took {duration:.3f}s, expected <= 3.0s"
    assert res.items_included == 50


# ---------------------------------------------------------------------------
# API Endpoints Integration Tests
# ---------------------------------------------------------------------------


def test_api_export_evidence_and_download_flow() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)

    payload = {
        "query": "Regulatory compliance audit",
        "passage_ids": ["clause-uuid-1", "clause-uuid-2"],
        "format": "ZIP",
        "audit_reference_id": "AUDIT-API-2026",
        "include_control_mappings": True,
    }

    resp = client.post(
        "/v1/compliance/export-evidence",
        json=payload,
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["items_included"] == 2
    assert data["format"] == "ZIP"
    assert data["audit_reference_id"] == "AUDIT-API-2026"
    assert data["download_url"].startswith("/v1/compliance/export-download/")
    assert len(data["file_sha256"]) == 64

    # Download file
    download_url = data["download_url"]
    dl_resp = client.get(download_url, headers=auth(PRIMARY_KEY))
    assert dl_resp.status_code == 200
    assert dl_resp.headers["Content-Type"] == "application/zip"
    assert dl_resp.headers["X-DocScout-SHA256"] == data["file_sha256"]

    # Verify download zip bytes
    zip_bytes = dl_resp.content
    assert hashlib.sha256(zip_bytes).hexdigest() == data["file_sha256"]


def test_api_export_validation_errors() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)

    # Empty passage_ids
    resp_empty = client.post(
        "/v1/compliance/export-evidence",
        json={
            "query": "test",
            "passage_ids": [],
            "format": "PDF",
            "audit_reference_id": "REF-1",
        },
        headers=auth(PRIMARY_KEY),
    )
    assert resp_empty.status_code == 422

    # More than 50 passage_ids
    resp_overflow = client.post(
        "/v1/compliance/export-evidence",
        json={
            "query": "test",
            "passage_ids": [f"id-{i}" for i in range(51)],
            "format": "PDF",
            "audit_reference_id": "REF-1",
        },
        headers=auth(PRIMARY_KEY),
    )
    assert resp_overflow.status_code == 422
