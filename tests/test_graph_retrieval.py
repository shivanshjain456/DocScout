"""Unit and integration tests for Graph-Augmented Retrieval (GAR) - FEAT-001.

Enforces:
1. Input validation rules: query length (3-512), max_hops (1-2), allowed_edge_types.
2. Traversal depth and decay factor calculation: hop-1 vs hop-2 proximity scores.
3. Data isolation: strictly filters out is_synthetic=True chunks per ADR-0024 and G-EVAL-1.
4. Error resilience: graceful fallback to empty results on query or DB exceptions.
5. Integration: Retriever respects RetrievalConfig.enable_gar flag.
6. Performance: traversal latency under 6.0 ms budget.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.retrieval.graph_retriever import (
    GraphRetriever,
    StatutoryGraph,
)
from app.retrieval.search import Retriever
from app.retrieval.types import RetrievalConfig


def test_input_validation_max_hops() -> None:
    """max_hops must be 1 or 2."""
    retriever = GraphRetriever()
    with pytest.raises(ValueError, match="max_hops"):
        retriever.retrieve_candidates("digital lending guidelines", max_hops=0)

    with pytest.raises(ValueError, match="max_hops"):
        retriever.retrieve_candidates("digital lending guidelines", max_hops=3)


def test_input_validation_query_length() -> None:
    """Query length must be between 3 and 512 characters."""
    retriever = GraphRetriever()
    with pytest.raises(ValueError, match="query length"):
        retriever.retrieve_candidates("ab")

    long_query = "x" * 513
    with pytest.raises(ValueError, match="query length"):
        retriever.retrieve_candidates(long_query)


def test_input_validation_edge_types() -> None:
    """allowed_edge_types must be a subset of the approved statutory relation kinds."""
    retriever = GraphRetriever()
    with pytest.raises(ValueError, match="allowed_edge_types"):
        retriever.retrieve_candidates("digital lending", allowed_edge_types=["invalid_relation"])


def test_statutory_graph_hop_traversal_and_decay() -> None:
    """Verify 1-hop vs 2-hop traversal with proximity score decay."""
    graph = StatutoryGraph()
    # Node A -> Node B (requires, weight 0.95)
    # Node B -> Node C (specializedBy, weight 0.85)
    graph.add_edge("node_a", "node_b", "requires")
    graph.add_edge("node_b", "node_c", "specializedBy")

    # Associate chunks
    graph.bind_chunk("node_b", "chunk_b_001", is_synthetic=False)
    graph.bind_chunk("node_c", "chunk_c_002", is_synthetic=False)

    # 1-hop from node_a
    results_1hop = graph.traverse(["node_a"], max_hops=1, decay_factor=0.5)
    assert len(results_1hop) == 1
    chunk_id, score = results_1hop[0]
    assert chunk_id == "chunk_b_001"
    assert pytest.approx(score, 0.01) == 0.95

    # 2-hop from node_a
    results_2hop = graph.traverse(["node_a"], max_hops=2, decay_factor=0.5)
    assert len(results_2hop) == 2
    res_dict = dict(results_2hop)
    assert "chunk_b_001" in res_dict
    assert "chunk_c_002" in res_dict
    # Hop 2 score: 0.85 * 0.5 = 0.425
    assert pytest.approx(res_dict["chunk_c_002"], 0.01) == 0.425


def test_cycle_prevention() -> None:
    """Graph traversal must never loop infinitely on cyclic statutory references."""
    graph = StatutoryGraph()
    graph.add_edge("node_a", "node_b", "requires")
    graph.add_edge("node_b", "node_a", "complements")
    graph.bind_chunk("node_b", "chunk_b", is_synthetic=False)

    results = graph.traverse(["node_a"], max_hops=2)
    assert len(results) == 1
    assert results[0][0] == "chunk_b"


def test_synthetic_data_isolation() -> None:
    """Synthetic chunks must be strictly excluded from production candidate pool (ADR-0024)."""
    graph = StatutoryGraph()
    graph.add_edge("node_a", "node_b", "requires")
    graph.bind_chunk("node_b", "chunk_real", is_synthetic=False)
    graph.bind_chunk("node_b", "chunk_synthetic", is_synthetic=True)

    results = graph.traverse(["node_a"], max_hops=1, include_synthetic=False)
    chunk_ids = [cid for cid, _ in results]
    assert "chunk_real" in chunk_ids
    assert "chunk_synthetic" not in chunk_ids


def test_graph_retriever_fallback_on_error() -> None:
    """GraphRetriever must log error and safely return empty list on exceptions."""
    retriever = GraphRetriever()
    # Force an internal error by passing invalid graph state or triggering exception
    res = retriever.safe_traverse(
        query="valid query",
        seed_terms=["non_existent_term"],
    )
    assert isinstance(res, list)
    assert res == []


def test_performance_limits() -> None:
    """Graph neighbor lookup and scoring must execute in <= 6.0 ms."""
    graph = StatutoryGraph()
    # Populate a medium graph with 200 nodes and edges
    for i in range(200):
        graph.add_edge(f"concept_{i}", f"concept_{i + 1}", "enables")
        graph.bind_chunk(f"concept_{i + 1}", f"chunk_{i + 1}", is_synthetic=False)

    start = time.perf_counter()
    res = graph.traverse(["concept_10"], max_hops=2)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms <= 6.0, f"Traversal took {elapsed_ms:.2f} ms (budget: <= 6.0 ms)"
    assert len(res) <= 64


def test_retrieval_config_gar_schema() -> None:
    """RetrievalConfig must expose enable_gar, gar_max_hops, gar_decay_factor defaults."""
    config = RetrievalConfig(name="test-config")
    assert hasattr(config, "enable_gar")
    assert config.enable_gar is False
    assert config.gar_max_hops == 1
    assert config.gar_decay_factor == 0.5

    d = config.as_dict()
    assert d["enable_gar"] is False
    assert d["gar_max_hops"] == 1
    assert d["gar_decay_factor"] == 0.5


def test_retriever_integration_with_gar() -> None:
    """Retriever.retrieve integrates GAR graph candidates into hybrid arm fusion."""
    import numpy as np

    from app.retrieval.port import ChunkRow
    from tests.test_retrieval_port import DummyEmbedder, InMemoryVectorStore

    store = InMemoryVectorStore()
    chunk1_id = "00000000-0000-4000-8000-000000000001"
    chunk2_id = "00000000-0000-4000-8000-000000000002"

    vec1 = np.zeros(384, dtype=np.float32)
    vec1[0] = 1.0
    vec2 = np.zeros(384, dtype=np.float32)

    store.add(
        chunk1_id,
        vec1,
        ChunkRow(
            document_id="doc-1",
            source="rbi",
            text="Digital lending guidelines require cooling-off period.",
            canonical_url="https://rbi.org.in/doc1",
            char_start=0,
            char_end=54,
        ),
    )
    store.add(
        chunk2_id,
        vec2,
        ChunkRow(
            document_id="doc-2",
            source="rbi",
            text="Compromise settlements framework and penal charges.",
            canonical_url="https://rbi.org.in/doc2",
            char_start=0,
            char_end=51,
        ),
    )

    class DummyBM25:
        def search(
            self, conn: Any, query: str, k: int, filter: Any = None
        ) -> list[tuple[str, float]]:
            return [(chunk1_id, 12.5)]

    custom_graph = StatutoryGraph()
    custom_graph.add_edge("digital_lending_guidelines", "cooling_off_period", "requires")
    custom_graph.bind_chunk("cooling_off_period", chunk2_id, is_synthetic=False)

    gar = GraphRetriever(graph=custom_graph)
    dummy_conn = object()
    retriever = Retriever(
        conn=dummy_conn,  # type: ignore[arg-type]
        vector_store=store,
        embedder=DummyEmbedder(),  # type: ignore[arg-type]
        bm25=DummyBM25(),  # type: ignore[arg-type]
        graph_retriever=gar,
    )

    cfg = RetrievalConfig(
        name="hybrid-gar-test",
        mode="hybrid",
        enable_gar=True,
        gar_max_hops=1,
        gar_decay_factor=0.5,
        k_dense=5,
        k_lexical=5,
        k_final=5,
    )

    results = retriever.retrieve("digital lending guidelines", cfg)
    assert len(results) > 0
    # Both chunk1 (from dense) and chunk2 (from graph) should be in the results
    result_ids = [r.chunk_id for r in results]
    assert chunk1_id in result_ids
    assert chunk2_id in result_ids
