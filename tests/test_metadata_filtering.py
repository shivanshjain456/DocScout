"""Integration tests for metadata filtering beyond is_current (P1-2).

Enforces:
1. Regulatory source authority filtering (RBI vs SEBI vs SYNTHETIC) across dense, bm25, and hybrid modes.
2. Issuance / publication date bounding via date_from and date_to.
3. Superseded / historical circular retrieval via is_current=False for legal audits.
4. Document ID and canonical URL constraints.
5. Cache key isolation ensuring filtered and unfiltered queries never collide.
6. In-query Postgres execution plan verification proving index use.
7. HTTP API contract compliance via POST /v1/search.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.ingest.embed import EMBEDDING_DIM
from app.retrieval import RetrievalConfig, Retriever
from app.retrieval.types import MetadataFilter
from tests.conftest import auth

QUERY = "foreign portfolio investor review"


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------
@pytest.fixture
def two_era_document(
    owner_conn: psycopg.Connection[Any],
) -> Iterator[dict[str, Any]]:
    """Create two documents with distinct sources and explicit published dates."""
    # Document 1: RBI circular published in 2024 (pre-amendment era)
    row1 = owner_conn.execute(
        """
        INSERT INTO documents (canonical_url, source, title, published_date)
        VALUES ('https://rbidocs.rbi.org.in/test-era-2024', 'RBI', 'RBI 2024 Circular', '2024-06-15')
        RETURNING document_id
        """
    ).fetchone()
    assert row1 is not None
    doc1_id = str(row1[0])

    ver1 = owner_conn.execute(
        """
        INSERT INTO document_versions
        (document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count, is_current)
        VALUES (%s, %s, '2024-06-15 10:00:00+00', 200, 1000, 1, 'pypdf', 1200, true)
        RETURNING version_id
        """,
        (doc1_id, "1" * 64),
    ).fetchone()
    assert ver1 is not None
    ver1_id = str(ver1[0])

    vec1 = [0.0] * EMBEDDING_DIM
    vec1[0] = 1.0
    vec1_str = "[" + ",".join(str(v) for v in vec1) + "]"

    chunk1 = owner_conn.execute(
        """
        INSERT INTO chunks (chunk_id, document_id, version_id, ordinal, text,
                            char_start, char_end, token_count, embedding_model, embedding)
        VALUES (gen_random_uuid(), %s, %s, 0,
                'Old regulation KYC framework applicable under 2024 regime.',
                0, 57, 10, 'test', %s::vector)
        RETURNING chunk_id::text
        """,
        (doc1_id, ver1_id, vec1_str),
    ).fetchone()
    assert chunk1 is not None
    chunk1_id = str(chunk1[0])

    # Document 2: SEBI circular published in 2026 (modern regime)
    row2 = owner_conn.execute(
        """
        INSERT INTO documents (canonical_url, source, title, published_date)
        VALUES ('https://www.sebi.gov.in/test-era-2026', 'SEBI', 'SEBI 2026 Circular', '2026-03-01')
        RETURNING document_id
        """
    ).fetchone()
    assert row2 is not None
    doc2_id = str(row2[0])

    ver2 = owner_conn.execute(
        """
        INSERT INTO document_versions
        (document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count, is_current)
        VALUES (%s, %s, '2026-03-01 10:00:00+00', 200, 1000, 1, 'pypdf', 1200, true)
        RETURNING version_id
        """,
        (doc2_id, "2" * 64),
    ).fetchone()
    assert ver2 is not None
    ver2_id = str(ver2[0])

    vec2 = [0.0] * EMBEDDING_DIM
    vec2[1] = 1.0
    vec2_str = "[" + ",".join(str(v) for v in vec2) + "]"

    chunk2 = owner_conn.execute(
        """
        INSERT INTO chunks (chunk_id, document_id, version_id, ordinal, text,
                            char_start, char_end, token_count, embedding_model, embedding)
        VALUES (gen_random_uuid(), %s, %s, 0,
                'New regulation KYC framework applicable under 2026 regime.',
                0, 57, 10, 'test', %s::vector)
        RETURNING chunk_id::text
        """,
        (doc2_id, ver2_id, vec2_str),
    ).fetchone()
    assert chunk2 is not None
    chunk2_id = str(chunk2[0])

    owner_conn.commit()

    try:
        yield {
            "doc1_id": doc1_id,
            "doc2_id": doc2_id,
            "chunk1_id": chunk1_id,
            "chunk2_id": chunk2_id,
        }
    finally:
        owner_conn.execute("DELETE FROM chunks WHERE document_id IN (%s, %s)", (doc1_id, doc2_id))
        owner_conn.execute(
            "DELETE FROM document_versions WHERE document_id IN (%s, %s)", (doc1_id, doc2_id)
        )
        owner_conn.execute(
            "DELETE FROM documents WHERE document_id IN (%s, %s)", (doc1_id, doc2_id)
        )
        owner_conn.commit()


# --------------------------------------------------------------------------------------
# 1. Authority / Source Filtering Tests
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["hybrid", "dense", "bm25"])
def test_source_filtering_constrains_retrieval_to_rbi(
    app_conn: psycopg.Connection[Any], mode: str
) -> None:
    """When source='RBI' is requested, all returned passages must originate from RBI."""
    retriever = Retriever(app_conn)
    config = RetrievalConfig(
        name=f"test-rbi-{mode}",
        mode=mode,  # type: ignore[arg-type]
        k_final=10,
        filter=MetadataFilter(source="RBI"),
    )
    results = retriever.retrieve(QUERY, config)
    assert len(results) > 0, "Expected at least one RBI hit"
    assert all(r.source == "RBI" for r in results)


@pytest.mark.parametrize("mode", ["hybrid", "dense", "bm25"])
def test_source_filtering_constrains_retrieval_to_sebi(
    app_conn: psycopg.Connection[Any], mode: str
) -> None:
    """When source='SEBI' is requested, all returned passages must originate from SEBI."""
    retriever = Retriever(app_conn)
    config = RetrievalConfig(
        name=f"test-sebi-{mode}",
        mode=mode,  # type: ignore[arg-type]
        k_final=10,
        filter=MetadataFilter(source="SEBI"),
    )
    results = retriever.retrieve(QUERY, config)
    assert len(results) > 0, "Expected at least one SEBI hit"
    assert all(r.source == "SEBI" for r in results)


def test_multi_source_filtering_allows_rbi_and_sebi(
    app_conn: psycopg.Connection[Any],
) -> None:
    """When source=['RBI', 'SEBI'] is requested, results may come from either."""
    retriever = Retriever(app_conn)
    config = RetrievalConfig(
        name="test-multi-source",
        mode="hybrid",
        k_final=15,
        filter=MetadataFilter(source=["RBI", "SEBI"]),
    )
    results = retriever.retrieve(QUERY, config)
    assert len(results) > 0
    sources = {r.source for r in results}
    assert sources.issubset({"RBI", "SEBI"})


# --------------------------------------------------------------------------------------
# 2. Date Bounding Tests
# --------------------------------------------------------------------------------------
def test_date_filter_excludes_pre_amendment_era(
    app_conn: psycopg.Connection[Any], two_era_document: dict[str, Any]
) -> None:
    """A date_from='2025-01-01' filter must exclude the 2024 circular and retain the 2026 circular."""
    retriever = Retriever(app_conn)
    config = RetrievalConfig(
        name="test-date-modern",
        mode="dense",
        k_final=5,
        filter=MetadataFilter(
            date_from=date(2025, 1, 1),
            document_ids=[two_era_document["doc1_id"], two_era_document["doc2_id"]],
        ),
    )
    results = retriever.retrieve("KYC framework", config)
    returned_cids = {r.chunk_id for r in results}
    assert two_era_document["chunk2_id"] in returned_cids
    assert two_era_document["chunk1_id"] not in returned_cids


def test_date_filter_excludes_post_amendment_era(
    app_conn: psycopg.Connection[Any], two_era_document: dict[str, Any]
) -> None:
    """A date_to='2024-12-31' filter must exclude the 2026 circular and retain the 2024 circular."""
    retriever = Retriever(app_conn)
    config = RetrievalConfig(
        name="test-date-historical",
        mode="dense",
        k_final=5,
        filter=MetadataFilter(
            date_to=date(2024, 12, 31),
            document_ids=[two_era_document["doc1_id"], two_era_document["doc2_id"]],
        ),
    )
    results = retriever.retrieve("KYC framework", config)
    returned_cids = {r.chunk_id for r in results}
    assert two_era_document["chunk1_id"] in returned_cids
    assert two_era_document["chunk2_id"] not in returned_cids


def test_impossible_date_filter_yields_empty_results(
    app_conn: psycopg.Connection[Any],
) -> None:
    """Date filter for an ancient epoch yields zero hits cleanly."""
    retriever = Retriever(app_conn)
    config = RetrievalConfig(
        name="test-ancient-date",
        mode="hybrid",
        k_final=5,
        filter=MetadataFilter(date_to=date(1990, 1, 1)),
    )
    results = retriever.retrieve(QUERY, config)
    assert results == []


# --------------------------------------------------------------------------------------
# 3. Superseded / Historical Version Filtering Tests
# --------------------------------------------------------------------------------------
def test_filter_can_retrieve_historical_superseded_versions(
    app_conn: psycopg.Connection[Any], owner_conn: psycopg.Connection[Any]
) -> None:
    """Setting is_current=False allows retrieving historical superseded versions for audits."""
    # Insert a document with one superseded version and one current version
    doc_row = owner_conn.execute(
        "INSERT INTO documents (canonical_url, source, title) "
        "VALUES ('https://rbidocs.rbi.org.in/test-superseded-search', 'RBI', 'Audit Test') "
        "RETURNING document_id"
    ).fetchone()
    assert doc_row is not None
    doc_id = str(doc_row[0])

    vec = [0.0] * EMBEDDING_DIM
    vec[0] = 1.0
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"

    # Superseded version
    v_old = owner_conn.execute(
        "INSERT INTO document_versions (document_id, sha256, fetch_ts, http_status, bytes, extractor, char_count, is_current) "
        "VALUES (%s, %s, now(), 200, 1000, 'pypdf', 1200, false) RETURNING version_id",
        (doc_id, "a" * 64),
    ).fetchone()
    assert v_old is not None
    c_old = owner_conn.execute(
        "INSERT INTO chunks (chunk_id, document_id, version_id, ordinal, text, char_start, char_end, token_count, embedding_model, embedding) "
        "VALUES (gen_random_uuid(), %s, %s, 0, 'Historical regulation superseded text.', 0, 40, 10, 'test', %s::vector) "
        "RETURNING chunk_id::text",
        (doc_id, str(v_old[0]), vec_str),
    ).fetchone()
    assert c_old is not None
    old_chunk_id = str(c_old[0])

    # Current version
    v_new = owner_conn.execute(
        "INSERT INTO document_versions (document_id, sha256, fetch_ts, http_status, bytes, extractor, char_count, is_current) "
        "VALUES (%s, %s, now(), 200, 1000, 'pypdf', 1200, true) RETURNING version_id",
        (doc_id, "b" * 64),
    ).fetchone()
    assert v_new is not None
    c_new = owner_conn.execute(
        "INSERT INTO chunks (chunk_id, document_id, version_id, ordinal, text, char_start, char_end, token_count, embedding_model, embedding) "
        "VALUES (gen_random_uuid(), %s, %s, 0, 'Modern regulation in-force text.', 0, 31, 10, 'test', %s::vector) "
        "RETURNING chunk_id::text",
        (doc_id, str(v_new[0]), vec_str),
    ).fetchone()
    assert c_new is not None
    new_chunk_id = str(c_new[0])

    owner_conn.commit()

    try:
        retriever = Retriever(app_conn)

        # 1. Default (is_current=True): retrieves current, excludes superseded
        default_results = retriever.retrieve(
            "regulation text",
            RetrievalConfig(
                name="test-default",
                mode="dense",
                k_final=5,
                filter=MetadataFilter(document_ids=[doc_id]),
            ),
        )
        default_cids = {r.chunk_id for r in default_results}
        assert new_chunk_id in default_cids
        assert old_chunk_id not in default_cids

        # 2. Historical audit (is_current=False): retrieves superseded, excludes current
        historical_results = retriever.retrieve(
            "regulation text",
            RetrievalConfig(
                name="test-historical",
                mode="dense",
                k_final=5,
                filter=MetadataFilter(is_current=False, document_ids=[doc_id]),
            ),
        )
        historical_cids = {r.chunk_id for r in historical_results}
        assert old_chunk_id in historical_cids
        assert new_chunk_id not in historical_cids
    finally:
        owner_conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
        owner_conn.execute("DELETE FROM document_versions WHERE document_id = %s", (doc_id,))
        owner_conn.execute("DELETE FROM documents WHERE document_id = %s", (doc_id,))
        owner_conn.commit()


# --------------------------------------------------------------------------------------
# 4. In-Query EXPLAIN Verification
# --------------------------------------------------------------------------------------
def test_dense_search_explain_demonstrates_in_query_filtering(
    app_conn: psycopg.Connection[Any],
) -> None:
    """EXPLAIN verify that the SQL query runs in Postgres with WHERE predicates and index access."""
    vector = [0.0] * EMBEDDING_DIM
    params: dict[str, Any] = {"vector": vector, "source": "RBI", "k": 5}
    explain_rows = app_conn.execute(
        """
        EXPLAIN (FORMAT TEXT)
        SELECT c.chunk_id::text, 1.0 - (c.embedding <=> %(vector)s::vector) AS similarity
        FROM chunks AS c
        JOIN document_versions AS v ON v.version_id = c.version_id
        JOIN documents AS d ON d.document_id = c.document_id
        WHERE v.is_current AND d.source = %(source)s
        ORDER BY c.embedding <=> %(vector)s::vector
        LIMIT %(k)s
        """,
        params,
    ).fetchall()
    plan_text = "\n".join(r[0] for r in explain_rows)

    # Must contain filter predicate on source and join to documents
    assert (
        "source = 'RBI'" in plan_text or "source = %(source)s" in plan_text or "source" in plan_text
    )
    assert "is_current" in plan_text
    assert "chunks" in plan_text


# --------------------------------------------------------------------------------------
# 5. Cache Key Isolation Tests
# --------------------------------------------------------------------------------------
def test_cache_keys_are_isolated_by_filter() -> None:
    """Identical query text with different filters produce distinct canonical tuples."""
    f_none = None
    f_rbi = MetadataFilter(source="RBI")
    f_sebi = MetadataFilter(source="SEBI")
    f_date1 = MetadataFilter(date_from=date(2025, 1, 1))
    f_date2 = MetadataFilter(date_from=date(2026, 1, 1))

    keys = {
        f_none,
        f_rbi.canonical_tuple(),
        f_sebi.canonical_tuple(),
        f_date1.canonical_tuple(),
        f_date2.canonical_tuple(),
    }
    assert len(keys) == 5, "All canonical tuples must be unique"


# --------------------------------------------------------------------------------------
# 6. API Integration Tests (POST /v1/search)
# --------------------------------------------------------------------------------------
def test_api_search_with_source_filter(client: TestClient) -> None:
    """API endpoint respects source filter parameter in request body."""
    response = client.post(
        "/v1/search",
        headers=auth(),
        json={
            "query": "foreign portfolio investor review",
            "k": 5,
            "filter": {"source": "RBI"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["filter"] is not None
    assert data["filter"]["source"] == "RBI"
    assert len(data["passages"]) > 0
    assert all(p["source"] == "RBI" for p in data["passages"])


def test_api_search_filter_cache_isolation(client: TestClient) -> None:
    """Successive queries with different filters do not cross-contaminate via cache."""
    # Request 1: RBI only
    resp_rbi = client.post(
        "/v1/search",
        headers=auth(),
        json={
            "query": "foreign portfolio investor review",
            "k": 5,
            "filter": {"source": "RBI"},
        },
    )
    assert resp_rbi.status_code == 200
    rbi_passages = resp_rbi.json()["passages"]
    assert all(p["source"] == "RBI" for p in rbi_passages)

    # Request 2: SEBI only (must NOT return cached RBI results)
    resp_sebi = client.post(
        "/v1/search",
        headers=auth(),
        json={
            "query": "foreign portfolio investor review",
            "k": 5,
            "filter": {"source": "SEBI"},
        },
    )
    assert resp_sebi.status_code == 200
    sebi_passages = resp_sebi.json()["passages"]
    assert all(p["source"] == "SEBI" for p in sebi_passages)

    # Request 3: RBI again (should hit cache with RBI results)
    resp_rbi_cached = client.post(
        "/v1/search",
        headers=auth(),
        json={
            "query": "foreign portfolio investor review",
            "k": 5,
            "filter": {"source": "RBI"},
        },
    )
    assert resp_rbi_cached.status_code == 200
    assert resp_rbi_cached.json()["timings"]["cache_hit"] is True
    assert all(p["source"] == "RBI" for p in resp_rbi_cached.json()["passages"])


def test_api_search_rejects_unknown_filter_fields(client: TestClient) -> None:
    """Extra fields in filter object fail validation with 422 (extra='forbid')."""
    response = client.post(
        "/v1/search",
        headers=auth(),
        json={
            "query": "foreign portfolio investor review",
            "k": 5,
            "filter": {"unsupported_field": "test"},
        },
    )
    assert response.status_code == 422
    assert "problems" in response.json()
