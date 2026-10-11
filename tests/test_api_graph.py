"""Unit and API integration tests for Concept Subgraph Projection - FEAT-004.

Enforces:
1. Endpoint authentication: GET /v1/graph/subgraph/{doc_id} requires API key (401).
2. Input validation: doc_id format regex, depth in [1, 2], max_nodes in [5, 50].
3. RFC-7807 problem details or 404 when document not found.
4. Correct SubgraphResponse schema: nodes, edges, root_id.
5. Cycle-safe 2-hop ego network extraction.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def graph_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_subgraph_endpoint_requires_auth(graph_client: TestClient) -> None:
    """Unauthenticated calls to /v1/graph/subgraph/{doc_id} must receive 401."""
    resp = graph_client.get("/v1/graph/subgraph/doc-00000000-0000")
    assert resp.status_code == 401


def test_subgraph_invalid_doc_id_format(graph_client: TestClient) -> None:
    """doc_id must match regex ^doc-[a-z0-9\\-]+$."""
    resp = graph_client.get("/v1/graph/subgraph/invalid_doc_123", headers=auth(PRIMARY_KEY))
    assert resp.status_code == 422


def test_subgraph_invalid_depth(graph_client: TestClient) -> None:
    """depth must be 1 or 2."""
    resp = graph_client.get(
        "/v1/graph/subgraph/doc-noti-280?depth=3",
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 422


def test_subgraph_invalid_max_nodes(graph_client: TestClient) -> None:
    """max_nodes must be between 5 and 50."""
    resp = graph_client.get(
        "/v1/graph/subgraph/doc-noti-280?max_nodes=100",
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 422


def test_subgraph_nonexistent_doc_returns_404(graph_client: TestClient) -> None:
    """Non-existent document must return 404 Not Found."""
    resp = graph_client.get(
        "/v1/graph/subgraph/doc-nonexistent-9999",
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 404


def test_subgraph_valid_projection(graph_client: TestClient) -> None:
    """Valid document must return SubgraphResponse with nodes and edges."""
    resp = graph_client.get(
        "/v1/graph/subgraph/doc-noti280digitallending?depth=2&max_nodes=25",
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert "root_id" in data
    assert data["root_id"] == "doc-noti280digitallending"
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)
    assert len(data["nodes"]) > 1
    assert len(data["edges"]) > 0

    first_node = data["nodes"][0]
    assert "id" in first_node
    assert "label" in first_node
    assert "domain" in first_node
    assert "level" in first_node
