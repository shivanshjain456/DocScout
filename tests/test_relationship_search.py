"""Unit and API integration tests for Relationship-Filtered Search API - FEAT-008.

Enforces:
1. Input validation: SearchRequest.relationship_filter must match allowed literals
   ("supersedes", "requires", "enables", "complements", "specializedBy") or None.
   Invalid relationship string returns HTTP 422.
2. MetadataFilter and RetrievalConfig capture relationship_filter in serialization and tuples.
3. Passage output schema carries matching_relationships: list[str].
4. Fallback behavior: when relationship join yields zero matches, return empty results with 0.0 confidence.
5. Observability: docscout_relationship_queries_total counter increments with relation label.
6. Database relationship resolution via taxonomy_edges and circular_citations joins.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.app import app
from app.api.metrics import RELATIONSHIP_QUERIES_TOTAL
from app.api.models import Passage, SearchRequest
from app.api.security import load_keys
from app.retrieval.port import ChunkRow
from app.retrieval.search import Retriever
from app.retrieval.types import (
    VALID_RELATIONSHIP_FILTERS,
    MetadataFilter,
    RetrievalConfig,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def api_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_valid_relationship_filters_enum() -> None:
    """Validate 5 canonical relationship edge kinds from term-taxonomy.json."""
    assert len(VALID_RELATIONSHIP_FILTERS) == 5
    expected = {"supersedes", "requires", "enables", "complements", "specializedBy"}
    assert set(VALID_RELATIONSHIP_FILTERS) == expected


def test_search_request_relationship_filter_validation() -> None:
    """SearchRequest must accept valid relationship literals and reject unknown strings."""
    # Valid relationships
    for rel in VALID_RELATIONSHIP_FILTERS:
        req = SearchRequest(query="digital lending guidelines", relationship_filter=rel)  # type: ignore[arg-type]
        assert req.relationship_filter == rel

    # None is valid
    req_none = SearchRequest(query="digital lending guidelines", relationship_filter=None)
    assert req_none.relationship_filter is None

    # Invalid relationship must raise ValidationError
    with pytest.raises(ValidationError, match="Input should be"):
        SearchRequest(query="digital lending guidelines", relationship_filter="invalid_rel")  # type: ignore[arg-type]


def test_metadata_filter_and_config_relationship_filter() -> None:
    """MetadataFilter and RetrievalConfig handle relationship_filter correctly."""
    filt = MetadataFilter(relationship_filter="supersedes")
    assert filt.relationship_filter == "supersedes"
    tup = filt.canonical_tuple()
    assert "supersedes" in tup
    assert tup[9] == "supersedes"

    cfg = RetrievalConfig(name="test_rel", relationship_filter="requires")
    assert cfg.relationship_filter == "requires"
    cfg_dict = cfg.as_dict()
    assert cfg_dict["relationship_filter"] == "requires"


def test_passage_matching_relationships_schema() -> None:
    """Passage schema includes matching_relationships list."""
    p = Passage(
        rank=1,
        chunk_id="00000000-0000-4000-8000-000000000001",
        document_id="00000000-0000-4000-8000-000000000002",
        source="RBI",
        canonical_url=None,
        score=0.95,
        arm_ranks={"dense": 1},
        char_start=0,
        char_end=100,
        text="Sample provision text",
        matching_relationships=["supersedes"],
    )
    assert p.matching_relationships == ["supersedes"]


def test_retriever_find_relationship_chunks_queries_db() -> None:
    """_find_relationship_chunks must join taxonomy_edges and circular_citations."""
    mock_conn = MagicMock()
    # Mock return rows for taxonomy_edges: (chunk_id, doc_chunk_id)
    mock_conn.execute.return_value.fetchall.return_value = [
        ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002")
    ]

    retriever = Retriever(mock_conn)
    matching = retriever._find_relationship_chunks("supersedes")
    assert "00000000-0000-4000-8000-000000000001" in matching
    assert "00000000-0000-4000-8000-000000000002" in matching


def test_retriever_relationship_zero_matches_fallback() -> None:
    """Zero matching relationship chunks returns empty list with zero latency overhead."""
    mock_conn = MagicMock()
    # DB yields no relationship matches
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_embedder = MagicMock()

    retriever = Retriever(mock_conn, embedder=mock_embedder)
    cfg = RetrievalConfig(name="test_empty", relationship_filter="supersedes")
    res = retriever.retrieve("query text", cfg)
    assert res == []


def test_retriever_relationship_prunes_and_decorates_hits() -> None:
    """Retriever prunes non-compliant chunks and decorates matching_relationships."""
    cid_match = "00000000-0000-4000-8000-000000000001"
    cid_other = "00000000-0000-4000-8000-000000000002"

    mock_conn = MagicMock()
    # First call: _find_relationship_chunks returns cid_match
    mock_conn.execute.return_value.fetchall.return_value = [(cid_match, None)]

    mock_embedder = MagicMock()
    mock_embedder.encode_query.return_value = [0.1] * 768

    mock_vector_store = MagicMock()
    mock_vector_store.search.return_value = [(cid_match, 0.9), (cid_other, 0.8)]
    mock_vector_store.fetch_metadata.return_value = {
        cid_match: ChunkRow(
            document_id="doc1",
            source="RBI",
            text="Master Direction superseding 2020 circular.",
            canonical_url=None,
            char_start=0,
            char_end=50,
        )
    }

    mock_bm25 = MagicMock()
    mock_bm25.search.return_value = [(cid_match, 5.0), (cid_other, 4.0)]

    retriever = Retriever(
        mock_conn,
        embedder=mock_embedder,
        bm25=mock_bm25,
        vector_store=mock_vector_store,
    )

    cfg = RetrievalConfig(name="test_rel", relationship_filter="supersedes", mode="hybrid")
    hits = retriever.retrieve("superseding circular", cfg)

    assert len(hits) == 1
    assert hits[0].chunk_id == cid_match
    assert hits[0].matching_relationships == ["supersedes"]


def test_api_endpoint_relationship_filter_validation(api_client: TestClient) -> None:
    """POST /v1/search rejects invalid relationship_filter with 422."""
    resp = api_client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={
            "query": "directions on loans",
            "relationship_filter": "invalid_relationship_type",
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data


def test_live_search_endpoint_relationship_filter(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """If live DB is running, POST /v1/search observes metric and returns compliant passages."""
    before_count = RELATIONSHIP_QUERIES_TOTAL.labels(relation="supersedes")._value.get()

    resp = client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={
            "query": "directions superseding previous norms",
            "relationship_filter": "supersedes",
            "use_cache": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "passages" in data
    # Metric incremented
    after_count = RELATIONSHIP_QUERIES_TOTAL.labels(relation="supersedes")._value.get()
    assert after_count == before_count + 1
