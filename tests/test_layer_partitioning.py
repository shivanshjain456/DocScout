"""Unit and integration tests for Taxonomy Layer-Partitioned Search Indexes - FEAT-006.

Enforces:
1. 9 canonical taxonomy layers enum matching lexicon.json metadata conventions.
2. Input validation on MetadataFilter.taxonomy_layers (valid subsets accepted, invalid layer returns ValidationError / HTTP 422).
3. MetadataFilter canonical_tuple() and matches() behavior for layer purity.
4. Dense SQL query pruning clause (c.taxonomy_layer = ANY(%(taxonomy_layers)s)).
5. Lexical BM25 filtering respects taxonomy_layer with 100% layer purity.
6. RetrievalConfig default enforce_layer_pruning=True and dict serialization.
7. Fastapi API endpoint rejection with 422 on invalid taxonomy layer.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.app import app
from app.api.security import load_keys
from app.retrieval.dense import search as dense_search
from app.retrieval.lexical import BM25Index, _Posting
from app.retrieval.types import (
    VALID_TAXONOMY_LAYERS,
    ChunkMeta,
    MetadataFilter,
    RetrievalConfig,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_valid_taxonomy_layers_definition() -> None:
    """Ensure exactly 9 canonical taxonomy layers are registered."""
    assert len(VALID_TAXONOMY_LAYERS) == 9
    expected = {
        "architecture-and-data",
        "delivery-and-platform",
        "frontiers",
        "intelligence-and-ai",
        "physical-and-regulated",
        "product-and-interface",
        "quality-and-verification",
        "reliability-and-operations",
        "security-and-trust",
    }
    assert set(VALID_TAXONOMY_LAYERS) == expected


def test_metadata_filter_validation_valid_and_invalid() -> None:
    """Validate valid layers succeed and invalid layers raise ValidationError."""
    # Valid single layer
    f1 = MetadataFilter(taxonomy_layers=["security-and-trust"])
    assert f1.taxonomy_layers == ["security-and-trust"]

    # Valid multiple layers
    f2 = MetadataFilter(taxonomy_layers=["security-and-trust", "physical-and-regulated"])
    assert f2.taxonomy_layers == ["security-and-trust", "physical-and-regulated"]

    # None or empty
    f_none = MetadataFilter(taxonomy_layers=None)
    assert f_none.taxonomy_layers is None

    f_empty = MetadataFilter(taxonomy_layers=[])
    assert f_empty.taxonomy_layers == []

    # Invalid layer must raise ValidationError
    with pytest.raises(ValidationError, match="Invalid taxonomy layer"):
        MetadataFilter(taxonomy_layers=["nonexistent-layer"])

    with pytest.raises(ValidationError, match="Invalid taxonomy layer"):
        MetadataFilter(taxonomy_layers=["security-and-trust", "fake-layer"])


def test_metadata_filter_canonical_tuple() -> None:
    """canonical_tuple must sort taxonomy_layers deterministically for query caching."""
    f1 = MetadataFilter(taxonomy_layers=["security-and-trust", "architecture-and-data"])
    f2 = MetadataFilter(taxonomy_layers=["architecture-and-data", "security-and-trust"])
    assert f1.canonical_tuple() == f2.canonical_tuple()
    tup = f1.canonical_tuple()
    assert ("architecture-and-data", "security-and-trust") in tup
    assert tup[7] == ("architecture-and-data", "security-and-trust")


def test_metadata_filter_matches_layer_purity() -> None:
    """MetadataFilter.matches evaluates taxonomy_layer correctly."""
    f = MetadataFilter(taxonomy_layers=["security-and-trust", "intelligence-and-ai"])

    # Matches when layer is in filter
    meta_sec = ChunkMeta(
        chunk_id="c1",
        document_id="d1",
        source="RBI",
        published_date=None,
        fetch_ts=None,
        is_current=True,
        taxonomy_layer="security-and-trust",
    )
    assert f.matches(meta_sec) is True

    # Rejects when layer is different
    meta_phys = ChunkMeta(
        chunk_id="c2",
        document_id="d2",
        source="RBI",
        published_date=None,
        fetch_ts=None,
        is_current=True,
        taxonomy_layer="physical-and-regulated",
    )
    assert f.matches(meta_phys) is False

    # Rejects when chunk has no taxonomy layer
    meta_none = ChunkMeta(
        chunk_id="c3",
        document_id="d3",
        source="RBI",
        published_date=None,
        fetch_ts=None,
        is_current=True,
        taxonomy_layer=None,
    )
    assert f.matches(meta_none) is False

    # If filter has taxonomy_layers=None, matches any layer
    f_open = MetadataFilter(taxonomy_layers=None)
    assert f_open.matches(meta_sec) is True
    assert f_open.matches(meta_phys) is True
    assert f_open.matches(meta_none) is True


def test_retrieval_config_layer_pruning_default() -> None:
    """RetrievalConfig enables layer pruning by default and exposes it in as_dict."""
    cfg = RetrievalConfig(name="test_layer_pruning")
    assert cfg.enforce_layer_pruning is True
    cfg_dict = cfg.as_dict()
    assert cfg_dict["enforce_layer_pruning"] is True


def test_dense_sql_query_with_taxonomy_layer_filter() -> None:
    """Dense search must inject c.taxonomy_layer = ANY(...) when filter is specified."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []

    f = MetadataFilter(taxonomy_layers=["security-and-trust"])
    dense_search(
        conn=mock_conn,
        query_vector=[0.1] * 768,
        k=5,
        filter=f,
    )

    call_args = mock_conn.execute.call_args
    assert call_args is not None
    sql, params = call_args[0]
    assert "c.taxonomy_layer = ANY(%(taxonomy_layers)s)" in sql
    assert params["taxonomy_layers"] == ["security-and-trust"]
    assert "NOT d.is_synthetic" in sql


def test_lexical_bm25_layer_partitioned_search() -> None:
    """BM25Index.search must filter candidates by taxonomy_layer with 100% purity."""
    idx = BM25Index.__new__(BM25Index)
    idx._n = 2
    idx._avgdl = 10.0
    idx._doc_len = {"chunk_sec": 10, "chunk_phys": 10}
    idx._chunk_meta = {
        "chunk_sec": ChunkMeta(
            chunk_id="chunk_sec",
            document_id="doc1",
            source="RBI",
            published_date=None,
            fetch_ts=None,
            is_current=True,
            taxonomy_layer="security-and-trust",
        ),
        "chunk_phys": ChunkMeta(
            chunk_id="chunk_phys",
            document_id="doc2",
            source="RBI",
            published_date=None,
            fetch_ts=None,
            is_current=True,
            taxonomy_layer="physical-and-regulated",
        ),
    }
    idx._postings = {
        "cyber": [
            _Posting(chunk_id="chunk_sec", tf=2),
            _Posting(chunk_id="chunk_phys", tf=2),
        ]
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [("cyber",)]

    # Search with layer filter restricted to security-and-trust
    filt_sec = MetadataFilter(taxonomy_layers=["security-and-trust"])
    results_sec = idx.search(mock_conn, "cyber", k=10, filter=filt_sec)
    assert len(results_sec) == 1
    assert results_sec[0][0] == "chunk_sec"

    # Search with layer filter restricted to physical-and-regulated
    filt_phys = MetadataFilter(taxonomy_layers=["physical-and-regulated"])
    results_phys = idx.search(mock_conn, "cyber", k=10, filter=filt_phys)
    assert len(results_phys) == 1
    assert results_phys[0][0] == "chunk_phys"

    # Search without layer filter returns both
    results_all = idx.search(mock_conn, "cyber", k=10, filter=None)
    assert len(results_all) == 2


def test_api_search_endpoint_validates_taxonomy_layers(test_client: TestClient) -> None:
    """POST /v1/search must return 422 on invalid taxonomy layer in filter."""
    resp = test_client.post(
        "/v1/search",
        headers=auth(PRIMARY_KEY),
        json={
            "query": "cyber security directions",
            "filter": {"taxonomy_layers": ["invalid-taxonomy-layer"]},
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data
