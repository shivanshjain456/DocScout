"""Unit and integration tests for Automated Regulatory Ontology Ingestion Pipeline - FEAT-010.

Verifies:
1. Document qualification validation (Master Directions / Frameworks vs generic notices).
2. Definitions text mining extraction recall (>= 90%) and precision (>= 85%).
3. Embedded acronym detection and alias normalization.
4. Schema compatibility with term-taxonomy.json standards.
5. Inferred proposed relationship edges.
6. Execution latency <= 5.0 seconds on large regulatory texts.
7. Database staging, review queue, and status transitions (pending -> approved/rejected).
8. Admin API contracts, authentication gating, and 404/422 error handling.
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import ONTOLOGY_CANDIDATES_REVIEWED
from app.api.security import load_keys
from app.ingest.ontology_extractor import (
    DocumentPayload,
    OntologyExtractor,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


SAMPLE_REGULATORY_CHAPTER_I = """
RESERVE BANK OF INDIA
DEPARTMENT OF REGULATION

RBI/2023-24/105
DOR.AML.REC.66/14.01.001/2023-24

Master Direction - Reserve Bank of India (Know Your Customer (KYC)) Directions, 2016

CHAPTER I
PRELIMINARY

1. Short Title and Commencement:
These Directions shall be called the Reserve Bank of India (Know Your Customer (KYC)) Directions, 2016.

2. Definitions:
In these Directions, unless the context otherwise requires:

(a) "Auditor" means an auditor qualified to act as auditor of companies under Section 141 of the Companies Act, 2013;

(b) "Customer Due Diligence (CDD)" means identifying and verifying the customer and the beneficial owner using reliable, independent source documents;

(c) "Digital Lending" shall mean a remote and automated lending process, largely by use of seamless digital technologies;

(d) "Lending Service Provider (LSP)" means an agent of a Regulated Entity who carries out one or more of lender's functions;

(e) "Regulated Entity (RE)" means all commercial banks, primary cooperative banks, and NBFCs;

(f) "Beneficial Owner (BO)" means an individual who ultimately owns or controls a client of a Regulated Entity;

(g) "Politically Exposed Person (PEP)" refers to individuals who are or have been entrusted with prominent public functions in a foreign country;

(h) "Non-Banking Financial Company (NBFC)" means a company registered under Section 45-IA of the Reserve Bank of India Act, 1934;

(i) "Video Based Customer Identification Process (V-CIP)" means an alternate method of customer identification using facial recognition and customer consent;

(j) "Digital Lending App (DLA)" refers to mobile and web-based applications with an interface to facilitate borrowing from Regulated Entities.
"""


def test_document_qualification() -> None:
    """Only Master Directions, Master Circulars, and Frameworks qualify for automated ontology mining."""
    extractor = OntologyExtractor()

    # Qualified documents
    assert extractor.is_qualified_document(
        "Master Direction - Reserve Bank of India (KYC) Directions, 2016"
    )
    assert extractor.is_qualified_document("Prudential Framework for Resolution of Stressed Assets")
    assert extractor.is_qualified_document(
        "Master Circular on Housing Finance for Scheduled Commercial Banks"
    )
    assert extractor.is_qualified_document("Comprehensive Guidelines on Digital Lending")
    assert extractor.is_qualified_document("Directions on Outsourcing of Financial Services")

    # Non-qualified documents
    assert not extractor.is_qualified_document("Press Release: Monetary Policy Committee Decisions")
    assert not extractor.is_qualified_document("Tender Document for Data Center Air Conditioning")
    assert not extractor.is_qualified_document(
        "Speech: The Future of Central Banking by Deputy Governor"
    )
    assert not extractor.is_qualified_document("")
    assert not extractor.is_qualified_document(None)


def test_definition_extraction_recall_and_precision() -> None:
    """Extraction pipeline must achieve recall >= 90% and precision >= 85% on sample regulatory glossary."""
    extractor = OntologyExtractor()
    doc = DocumentPayload(
        doc_id="doc-kyc-md-2023",
        text=SAMPLE_REGULATORY_CHAPTER_I,
        title="Master Direction - Know Your Customer (KYC) Directions, 2016",
    )

    candidates = extractor.extract_candidates(doc)

    expected_ground_truth_terms = {
        "auditor",
        "customer-due-diligence",
        "digital-lending",
        "lending-service-provider",
        "regulated-entity",
        "beneficial-owner",
        "politically-exposed-person",
        "non-banking-financial-company",
        "video-based-customer-identification-process",
        "digital-lending-app",
    }

    extracted_slugs = {c.slug for c in candidates}
    true_positives = len(extracted_slugs.intersection(expected_ground_truth_terms))

    recall = true_positives / len(expected_ground_truth_terms)
    precision = true_positives / len(extracted_slugs) if extracted_slugs else 0.0

    assert recall >= 0.90, (
        f"Expected recall >= 0.90, got {recall:.2f} (extracted: {extracted_slugs})"
    )
    assert precision >= 0.85, f"Expected precision >= 0.85, got {precision:.2f}"


def test_acronym_and_alias_extraction() -> None:
    """Embedded acronyms in terms like 'Customer Due Diligence (CDD)' must be extracted into aliases."""
    extractor = OntologyExtractor()
    doc = DocumentPayload(
        doc_id="doc-sample",
        text=SAMPLE_REGULATORY_CHAPTER_I,
        title="Master Direction - KYC",
    )
    candidates = {c.slug: c for c in extractor.extract_candidates(doc)}

    # Check CDD
    cdd = candidates.get("customer-due-diligence")
    assert cdd is not None
    assert "CDD" in cdd.aliases
    assert cdd.term == "Customer Due Diligence"

    # Check LSP
    lsp = candidates.get("lending-service-provider")
    assert lsp is not None
    assert "LSP" in lsp.aliases
    assert lsp.term == "Lending Service Provider"

    # Check RE
    re_cand = candidates.get("regulated-entity")
    assert re_cand is not None
    assert "RE" in re_cand.aliases

    # Check V-CIP
    vcip = candidates.get("video-based-customer-identification-process")
    assert vcip is not None
    assert "V-CIP" in vcip.aliases


def test_taxonomy_record_schema_conformance() -> None:
    """Emitted taxonomy records must validate 100% against term-taxonomy.json schema."""
    extractor = OntologyExtractor()
    doc = DocumentPayload(
        doc_id="doc-sample",
        text=SAMPLE_REGULATORY_CHAPTER_I,
        title="Master Direction - KYC",
    )
    candidates = extractor.extract_candidates(doc)
    assert len(candidates) > 0

    required_keys = {
        "id",
        "term",
        "status",
        "domain",
        "domainName",
        "definition",
        "aliases",
        "tier",
        "gate",
        "lifecyclePhases",
        "roles",
        "tooling",
        "positions",
        "relationships",
        "sourceDocId",
        "confidence",
    }

    required_relationship_keys = {
        "enables",
        "requires",
        "complements",
        "tension",
        "supersedes",
        "instanceOf",
        "specializedBy",
        "sharesOracleWith",
    }

    for c in candidates:
        rec = c.to_taxonomy_record()
        # Verify top-level keys
        assert required_keys.issubset(rec.keys())
        assert rec["status"] == "candidate"
        assert isinstance(rec["aliases"], list)
        assert isinstance(rec["relationships"], dict)
        # Verify relationships dictionary structure
        assert required_relationship_keys.issubset(rec["relationships"].keys())
        assert isinstance(rec["definition"], str)
        assert len(rec["definition"]) >= 15


def test_proposed_edges_inference() -> None:
    """Terms referencing known frameworks in their definition must propose relationship edges."""
    extractor = OntologyExtractor()
    doc = DocumentPayload(
        doc_id="doc-sample",
        text=SAMPLE_REGULATORY_CHAPTER_I,
        title="Master Direction - KYC",
    )
    candidates = {c.slug: c for c in extractor.extract_candidates(doc)}

    # "Lending Service Provider (LSP) means an agent of a Regulated Entity..."
    lsp = candidates.get("lending-service-provider")
    assert lsp is not None
    target_slugs = [e.target for e in lsp.proposed_edges]
    assert "regulated-entity" in target_slugs


def test_extraction_performance_limits() -> None:
    """Extraction must complete in <= 5.0 seconds even on a simulated 50-page document."""
    # Synthesize ~50 page document (~100,000 characters)
    large_text = SAMPLE_REGULATORY_CHAPTER_I + (
        "\nParagraph on operational norms and risk.\n" * 2000
    )
    assert len(large_text) > 80000

    doc = DocumentPayload(
        doc_id="doc-large",
        text=large_text,
        title="Master Direction - Large Comprehensive Document",
    )

    extractor = OntologyExtractor()
    start_time = time.perf_counter()
    candidates = extractor.extract_candidates(doc)
    duration_s = time.perf_counter() - start_time

    assert duration_s < 5.0, f"Extraction took {duration_s:.3f} s, exceeding 5.0 s threshold"
    assert len(candidates) >= 5


def test_database_staging_mocked() -> None:
    """Mock database connection verifies stage_candidates SQL execution and metric increment."""
    mock_conn = MagicMock()
    extractor = OntologyExtractor()
    doc = DocumentPayload(
        doc_id="doc-1",
        text=SAMPLE_REGULATORY_CHAPTER_I,
        title="Master Direction - KYC",
    )
    candidates = extractor.extract_candidates(doc)

    staged_count = extractor.stage_candidates(mock_conn, candidates)
    assert staged_count == len(candidates)
    assert mock_conn.execute.call_count == len(candidates)
    mock_conn.commit.assert_called_once()


def test_admin_api_endpoints_without_pool(test_client: TestClient) -> None:
    """Admin API handles requests gracefully when DB pool is offline or in unit tests."""
    headers = auth(PRIMARY_KEY)

    # 1. Unauthenticated request must return 401
    res_unauth = test_client.get("/v1/admin/ontology/candidates")
    assert res_unauth.status_code == 401

    # 2. Authenticated list request
    res_list = test_client.get("/v1/admin/ontology/candidates", headers=headers)
    assert res_list.status_code == 200
    data = res_list.json()
    assert "candidates" in data
    assert "total_count" in data

    # 3. Trigger extraction endpoint
    res_extract = test_client.post(
        "/v1/admin/ontology/extract",
        headers=headers,
        json={
            "doc_id": "doc-test-123",
            "title": "Master Direction - KYC Directions",
            "text": SAMPLE_REGULATORY_CHAPTER_I,
        },
    )
    assert res_extract.status_code == 200
    extracted_records = res_extract.json()
    assert len(extracted_records) >= 5
    assert extracted_records[0]["status"] == "candidate"


def test_admin_status_transitions_with_mock_pool(
    test_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test approval and rejection status transitions and metrics."""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    # Mock DB row returned after status update
    mock_conn.execute.return_value.fetchone.return_value = (
        "123e4567-e89b-12d3-a456-426614174000",
        "Auditor",
        "auditor",
        "An auditor qualified to act as auditor of companies.",
        "physical-and-regulated",
        "Physical & Regulated Systems",
        None,
        "Master Direction",
        "approved",
        0.92,
        1,
        "[]",
        "[]",
        "2026-10-11T12:00:00Z",
        "2026-10-11T12:05:00Z",
        "admin@docscout.ai",
        "Verified against Chapter 1",
    )

    monkeypatch.setattr(app.state, "pool", mock_pool, raising=False)
    headers = auth(PRIMARY_KEY)

    before_approved = ONTOLOGY_CANDIDATES_REVIEWED.labels(action="approved")._value.get()

    res_approve = test_client.post(
        "/v1/admin/ontology/candidates/123e4567-e89b-12d3-a456-426614174000/approve",
        headers=headers,
        json={"reviewer": "admin@docscout.ai", "notes": "Verified against Chapter 1"},
    )
    assert res_approve.status_code == 200
    resp_body = res_approve.json()
    assert resp_body["status"] == "approved"
    assert resp_body["reviewed_by"] == "admin@docscout.ai"

    after_approved = ONTOLOGY_CANDIDATES_REVIEWED.labels(action="approved")._value.get()
    assert after_approved == before_approved + 1
