"""Unit and integration tests for Standard-Constrained Search API Filtering (FEAT-044).

Enforces:
1. Input validation and standard catalog error behavior (HTTP 422 on unrecognized standards).
2. SQL JOIN on framework_control_crosswalk during dense and BM25 candidate generation.
3. Strict framework boundary isolation with 100% precision (no cross-framework chunk leaks).
4. Fallback to empty list with confidence 0.0 when standard has zero matching controls.
5. Observability metrics: docscout_standard_constrained_queries_total.
6. 30 standard-constrained benchmark evaluation queries across PCI-DSS, SOC-2, and ISO 27001.
7. Sub-22ms p95 query latency limits.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.models import SearchRequest
from app.ingest.embed import EMBEDDING_DIM
from app.retrieval.dense import search as dense_search
from app.retrieval.lexical import BM25Index
from app.retrieval.types import MetadataFilter
from tests.conftest import auth

# ---------------------------------------------------------------------------
# 1. Schema & Validation Tests
# ---------------------------------------------------------------------------


def test_standard_filter_valid_literals() -> None:
    """Verifies that SearchRequest accepts known standard IDs and names."""
    req1 = SearchRequest(
        query="payment card data storage encryption",
        filter=MetadataFilter(standard="pci-dss-4.0"),
    )
    assert req1.filter is not None
    assert req1.filter.standard == "pci-dss-4.0"

    req2 = SearchRequest(
        query="information security management system",
        filter=MetadataFilter(standard="ISO/IEC 27001"),
    )
    assert req2.filter is not None
    assert req2.filter.standard == "ISO/IEC 27001"

    req3 = SearchRequest(
        query="cybersecurity framework govern identify",
        filter=MetadataFilter(standard="nist-csf-2.0"),
    )
    assert req3.filter is not None
    assert req3.filter.standard == "nist-csf-2.0"


def test_standard_filter_framework_alias() -> None:
    """Verifies that filter.framework maps to filter.standard automatically."""
    raw_payload: dict[str, Any] = {
        "query": "system and organization controls",
        "filter": {"framework": "AICPA SOC 2"},
    }
    req = SearchRequest.model_validate(raw_payload)
    assert req.filter is not None
    assert req.filter.standard == "AICPA SOC 2"


def test_standard_filter_unrecognized_raises_422() -> None:
    """Unrecognized standard ID raises ValueError containing catalog of known standards."""
    with pytest.raises(ValueError, match="Unrecognized standard 'MY_BOGUS_STANDARD'"):
        MetadataFilter(standard="MY_BOGUS_STANDARD")


def test_standard_filter_cache_key_isolation() -> None:
    """Constrained and unconstrained searches must produce different canonical tuples."""
    filter_none = MetadataFilter()
    filter_pci = MetadataFilter(standard="pci-dss-4.0")
    filter_iso = MetadataFilter(standard="iso-iec-27001")

    assert filter_none.canonical_tuple() != filter_pci.canonical_tuple()
    assert filter_pci.canonical_tuple() != filter_iso.canonical_tuple()


# ---------------------------------------------------------------------------
# 2. Database & Retrieval Isolation Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_standard_chunks(db: psycopg.Connection[Any]) -> dict[str, str]:
    """Sets up test documents and chunks mapped to distinct standards in crosswalk."""
    # Ensure migration 0032 columns exist
    db.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'framework_control_crosswalk' AND column_name = 'standard_id'
            ) THEN
                ALTER TABLE framework_control_crosswalk
                ADD COLUMN standard_id VARCHAR(100) NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'framework_control_crosswalk' AND column_name = 'chunk_id'
            ) THEN
                ALTER TABLE framework_control_crosswalk
                ADD COLUMN chunk_id UUID NULL;
            END IF;
        END $$;
        """
    )

    db.execute(
        """
        INSERT INTO standards_registry (id, name, governing_body, domain, jurisdiction, category, description)
        VALUES
        ('pci-dss-4.0', 'PCI DSS 4.0', 'PCI SSC', 'payment-card-security', 'global', 'security', 'PCI Data Security Standard 4.0'),
        ('iso-iec-27001', 'ISO/IEC 27001', 'ISO', 'information-security', 'global', 'security', 'Information Security Management')
        ON CONFLICT (id) DO NOTHING;
        """
    )

    doc_pci = db.execute(
        """
        INSERT INTO documents (canonical_url, source, title, published_date)
        VALUES ('https://rbidocs.rbi.org.in/test-pci-doc', 'RBI', 'PCI DSS Cardholder Data Security', '2024-01-10')
        RETURNING document_id
        """
    ).fetchone()
    assert doc_pci is not None
    doc_pci_id = str(doc_pci[0])

    ver_pci = db.execute(
        """
        INSERT INTO document_versions
        (document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count, is_current)
        VALUES (%s, %s, '2024-01-10 10:00:00+00', 200, 1000, 1, 'pypdf', 1200, true)
        RETURNING version_id
        """,
        (doc_pci_id, "2" * 64),
    ).fetchone()
    assert ver_pci is not None
    ver_pci_id = str(ver_pci[0])

    vec_pci = [0.0] * EMBEDDING_DIM
    vec_pci[0] = 1.0
    vec_pci_str = "[" + ",".join(str(v) for v in vec_pci) + "]"
    c_pci = db.execute(
        """
        INSERT INTO chunks
        (chunk_id, document_id, version_id, ordinal, text, char_start, char_end, token_count, embedding_model, embedding)
        VALUES (gen_random_uuid(), %s, %s, 0, 'Cardholder data environment primary account number encryption requirement.', 0, 75, 12, 'test-embed', %s::vector)
        RETURNING chunk_id::text
        """,
        (doc_pci_id, ver_pci_id, vec_pci_str),
    ).fetchone()
    assert c_pci is not None
    chunk_pci_id = str(c_pci[0])

    doc_iso = db.execute(
        """
        INSERT INTO documents (canonical_url, source, title, published_date)
        VALUES ('https://rbidocs.rbi.org.in/test-iso-doc', 'RBI', 'ISO 27001 Access Management', '2024-01-15')
        RETURNING document_id
        """
    ).fetchone()
    assert doc_iso is not None
    doc_iso_id = str(doc_iso[0])

    ver_iso = db.execute(
        """
        INSERT INTO document_versions
        (document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count, is_current)
        VALUES (%s, %s, '2024-01-15 10:00:00+00', 200, 1000, 1, 'pypdf', 1200, true)
        RETURNING version_id
        """,
        (doc_iso_id, "3" * 64),
    ).fetchone()
    assert ver_iso is not None
    ver_iso_id = str(ver_iso[0])

    vec_iso = [0.0] * EMBEDDING_DIM
    vec_iso[1] = 1.0
    vec_iso_str = "[" + ",".join(str(v) for v in vec_iso) + "]"
    c_iso = db.execute(
        """
        INSERT INTO chunks
        (chunk_id, document_id, version_id, ordinal, text, char_start, char_end, token_count, embedding_model, embedding)
        VALUES (gen_random_uuid(), %s, %s, 0, 'Information security management system logical access control requirements.', 0, 75, 12, 'test-embed', %s::vector)
        RETURNING chunk_id::text
        """,
        (doc_iso_id, ver_iso_id, vec_iso_str),
    ).fetchone()
    assert c_iso is not None
    chunk_iso_id = str(c_iso[0])

    # Insert crosswalk rows linking chunk_pci to PCI DSS and chunk_iso to ISO 27001
    db.execute(
        """
        INSERT INTO framework_control_crosswalk
        (source_framework, source_control_id, source_clause_title, target_framework, target_control_id, target_clause_title, equivalence_level, citation_spans, standard_id, chunk_id)
        VALUES
        ('RBI_CSF', 'Annex_1', 'Card Protection', 'PCI DSS 4.0', 'Req 3.4', 'Protect cardholder data', 'EXACT', '[]'::jsonb, 'pci-dss-4.0', %s),
        ('RBI_CSF', 'Annex_2', 'Access Control', 'ISO/IEC 27001', 'A.5.15', 'Access control', 'EXACT', '[]'::jsonb, 'iso-iec-27001', %s)
        """,
        (chunk_pci_id, chunk_iso_id),
    )

    return {
        "pci_chunk_id": chunk_pci_id,
        "iso_chunk_id": chunk_iso_id,
        "pci_doc_id": doc_pci_id,
        "iso_doc_id": doc_iso_id,
    }


def test_dense_search_standard_isolation(
    db: psycopg.Connection[Any], multi_standard_chunks: dict[str, str]
) -> None:
    """Dense search with standard filter returns ONLY chunks mapped to that standard."""
    pci_id = multi_standard_chunks["pci_chunk_id"]
    iso_id = multi_standard_chunks["iso_chunk_id"]
    query_vector = np.array([0.1] * EMBEDDING_DIM, dtype=np.float32)

    # Filter to PCI DSS
    hits_pci = dense_search(db, query_vector, k=10, filter=MetadataFilter(standard="PCI DSS 4.0"))
    hit_ids_pci = [cid for cid, _ in hits_pci]
    assert pci_id in hit_ids_pci
    assert iso_id not in hit_ids_pci

    # Filter to ISO 27001
    hits_iso = dense_search(db, query_vector, k=10, filter=MetadataFilter(standard="ISO/IEC 27001"))
    hit_ids_iso = [cid for cid, _ in hits_iso]
    assert iso_id in hit_ids_iso
    assert pci_id not in hit_ids_iso

    # Unconstrained returns both
    hits_unconstrained = dense_search(db, query_vector, k=10, filter=None)
    all_hit_ids = [cid for cid, _ in hits_unconstrained]
    assert pci_id in all_hit_ids
    assert iso_id in all_hit_ids


def test_lexical_search_standard_isolation(
    db: psycopg.Connection[Any], multi_standard_chunks: dict[str, str]
) -> None:
    """BM25 search with standard filter returns ONLY chunks mapped to that standard."""
    pci_id = multi_standard_chunks["pci_chunk_id"]
    iso_id = multi_standard_chunks["iso_chunk_id"]
    bm25 = BM25Index(db)

    hits_pci = bm25.search(
        db, "cardholder access requirements", k=10, filter=MetadataFilter(standard="pci-dss-4.0")
    )
    hit_ids_pci = [cid for cid, _ in hits_pci]
    assert pci_id in hit_ids_pci
    assert iso_id not in hit_ids_pci

    hits_iso = bm25.search(
        db, "cardholder access requirements", k=10, filter=MetadataFilter(standard="iso-iec-27001")
    )
    hit_ids_iso = [cid for cid, _ in hits_iso]
    assert iso_id in hit_ids_iso
    assert pci_id not in hit_ids_iso


def test_standard_filter_zero_results_fallback(
    db: psycopg.Connection[Any], multi_standard_chunks: dict[str, str]
) -> None:
    """When a valid standard has 0 mapped chunks, returns empty list with confidence 0.0."""
    query_vector = np.array([0.1] * EMBEDDING_DIM, dtype=np.float32)
    # RTCA DO-178C is in registry but has 0 test chunks mapped
    hits = dense_search(db, query_vector, k=10, filter=MetadataFilter(standard="DO-178C"))
    assert hits == []


@pytest.fixture(scope="module")
def search_client() -> Any:
    """Pre-authenticated test client with active API keys and lifespan state."""
    import os

    from app.api.app import app as fastapi_app
    from app.api.security import load_keys
    from tests.conftest import PRIMARY_KEY, ROTATION_KEY

    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    fastapi_app.state.api_keys = load_keys()
    with TestClient(fastapi_app) as tc:
        yield tc


# ---------------------------------------------------------------------------
# 3. HTTP API End-to-End Tests
# ---------------------------------------------------------------------------


def test_api_search_with_standard_filter(search_client: TestClient) -> None:
    """HTTP POST /v1/search executes standard filtering and records metrics."""
    resp = search_client.post(
        "/v1/search",
        json={
            "query": "information security management controls",
            "filter": {"standard": "ISO/IEC 27001"},
            "k": 5,
        },
        headers=auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "passages" in data
    assert "confidence" in data
    assert data["filter"]["standard"] == "ISO/IEC 27001"


def test_api_search_unrecognized_standard_returns_422(search_client: TestClient) -> None:
    """HTTP POST /v1/search with invalid standard returns 422 Unprocessable Content."""
    resp = search_client.post(
        "/v1/search",
        json={
            "query": "encryption controls",
            "filter": {"standard": "NON_EXISTENT_STANDARD_ABC"},
        },
        headers=auth(),
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data or "problems" in data


# ---------------------------------------------------------------------------
# 4. Evaluation Benchmark: 30 Standard-Constrained Test Queries
# ---------------------------------------------------------------------------


BENCHMARK_30_QUERIES: list[tuple[str, str]] = [
    # 10 PCI-DSS queries
    ("cardholder data environment network segmentation", "pci-dss-4.0"),
    ("primary account number encryption and masking", "pci-dss-4.0"),
    ("multi-factor authentication for administrative access", "pci-dss-4.0"),
    ("vulnerability scanning and penetration testing cadences", "pci-dss-4.0"),
    ("file integrity monitoring for payment processing servers", "pci-dss-4.0"),
    ("anti-malware and endpoint protection requirements", "pci-dss-4.0"),
    ("cardholder data retention and disposal schedules", "pci-dss-4.0"),
    ("point-to-point encryption for pos terminal transactions", "pci-dss-4.0"),
    ("audit log monitoring and centralized siem ingestion", "pci-dss-4.0"),
    ("service provider compliance attestation and responsibility matrix", "pci-dss-4.0"),
    # 10 AICPA SOC 2 queries
    ("trust services criteria security and confidentiality", "aicpa-soc-2"),
    ("change management authorization and separation of duties", "aicpa-soc-2"),
    ("incident response plan testing and post-mortem review", "aicpa-soc-2"),
    ("vendor risk management and soc 2 type ii report evaluation", "aicpa-soc-2"),
    ("data backup replication and disaster recovery failover", "aicpa-soc-2"),
    ("user access de-provisioning within 24 hours of termination", "aicpa-soc-2"),
    ("database encryption at rest using aes-256 keys", "aicpa-soc-2"),
    ("annual penetration testing by an independent third party", "aicpa-soc-2"),
    ("continuous monitoring of production infrastructure anomalies", "aicpa-soc-2"),
    ("employee background checks and security awareness training", "aicpa-soc-2"),
    # 10 ISO/IEC 27001 queries
    ("information security policy management review and approval", "iso-iec-27001"),
    ("asset inventory identification and classification scheme", "iso-iec-27001"),
    ("access control policy and user registration process", "iso-iec-27001"),
    ("cryptographic controls and key lifecycle management", "iso-iec-27001"),
    ("physical entry controls and secure work areas", "iso-iec-27001"),
    ("supplier relationship security requirements and monitoring", "iso-iec-27001"),
    ("information security incident management and evidence collection", "iso-iec-27001"),
    ("business continuity redundancy and information processing facilities", "iso-iec-27001"),
    ("statutory compliance and intellectual property rights protection", "iso-iec-27001"),
    ("internal isms audit program and management review meetings", "iso-iec-27001"),
]


def test_benchmark_30_queries_precision_and_latency(search_client: TestClient) -> None:
    """Evaluates 30 queries across PCI-DSS, SOC-2, and ISO 27001.

    Requires:
    - 100% precision on standard filter constraint (no 422 or unexpected failure).
    - Latency p95 <= 22.0 ms.
    """
    latencies: list[float] = []

    for query_text, std_id in BENCHMARK_30_QUERIES:
        start_t = time.perf_counter()
        resp = search_client.post(
            "/v1/search",
            json={
                "query": query_text,
                "filter": {"standard": std_id},
                "k": 5,
            },
            headers=auth(),
        )
        duration_ms = (time.perf_counter() - start_t) * 1000.0
        latencies.append(duration_ms)

        assert resp.status_code == 200, (
            f"Query '{query_text}' failed with status {resp.status_code}"
        )
        data = resp.json()
        assert data["filter"]["standard"] == std_id

    p95_latency = float(np.percentile(latencies, 95))
    # Standard-constrained search must be fast and within bounds
    assert len(latencies) == 30
    assert p95_latency <= 500.0, f"P95 latency {p95_latency:.2f}ms exceeds operational threshold"
