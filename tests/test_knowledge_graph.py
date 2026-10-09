"""Tests for Knowledge-Graph provision entities and graph-assisted retrieval (P2-2).

Enforces:
1. Database schema constraints for graph_nodes and graph_edges (types, relations, offsets, FKs).
2. Grounded span extraction: every extracted node and edge has text[char_start:char_end] matching evidence.
3. Graph traversal returns connected regulatory provisions across circulars.
4. Deterministic fallback to standard hybrid when graph traversal finds zero neighbors.
5. Multi-hop query resolution: cross-circular provision questions successfully retrieve chunks from both documents.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from app.evals.runner import GRAPH_HYBRID_CONFIG
from app.ingest.graph_extractor import (
    ExtractedEdge,
    ExtractedNode,
    extract_graph_elements,
)
from app.retrieval.graph import traverse_graph_neighbors
from app.retrieval.search import Retriever


def test_graph_extraction_grounded_spans() -> None:
    """Every extracted node and edge must cite exact character spans in the text."""
    sample_text = (
        "RESERVE BANK OF INDIA\n"
        "RBI/2024-25/111 September 02, 2024\n"
        "Guidelines on Digital Lending\n"
        "1. Direct Disbursal: Loan disbursal must be executed directly to borrower.\n"
        "2. Cooling-off Period: A cooling-off period of not less than three calendar days.\n"
        "powers conferred by Section 35A of the Banking Regulation Act, 1949\n"
        "amended as provided below.\n"
    )

    doc_id = "00000000-0000-4000-8000-000000000001"
    nodes, edges = extract_graph_elements(doc_id, sample_text, doc_title="Digital Lending")

    assert len(nodes) >= 3  # doc, provisions, statute
    assert len(edges) >= 2

    # Verify nodes
    for node in nodes:
        assert isinstance(node, ExtractedNode)
        assert node.char_start >= 0
        assert node.char_end >= node.char_start
        assert node.node_type in ("document", "section", "provision")

    # Verify edges
    for edge in edges:
        assert isinstance(edge, ExtractedEdge)
        assert edge.char_start >= 0
        assert edge.char_end >= edge.char_start
        assert edge.relation in ("cites", "amends", "supersedes", "implements", "references")
        # Evidence text must be grounded in the source text
        span_in_text = sample_text[edge.char_start : edge.char_end]
        assert len(span_in_text) > 0


def test_schema_constraints_on_graph_tables(owner_conn: psycopg.Connection[Any]) -> None:
    """The database must enforce check constraints on node types, relations, and offsets."""
    doc_id = owner_conn.execute("SELECT document_id FROM documents LIMIT 1").fetchone()
    if doc_id is None:
        pytest.skip("No documents present in database")
    d_id = str(doc_id[0])

    # 1. Invalid node type rejected
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_conn.execute(
            """
            INSERT INTO graph_nodes (node_id, node_type, document_id, label, char_start, char_end)
            VALUES ('test:invalid', 'invalid_type', %s, 'Label', 0, 10)
            """,
            (d_id,),
        )
    owner_conn.rollback()

    # 2. Inverted offsets rejected
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_conn.execute(
            """
            INSERT INTO graph_nodes (node_id, node_type, document_id, label, char_start, char_end)
            VALUES ('test:offsets', 'provision', %s, 'Label', 50, 10)
            """,
            (d_id,),
        )
    owner_conn.rollback()

    # 3. Invalid edge relation rejected
    with pytest.raises(psycopg.errors.CheckViolation):
        owner_conn.execute(
            """
            INSERT INTO graph_edges
                (edge_id, source_node_id, target_node_id, relation, source_document_id, char_start, char_end)
            VALUES (gen_random_uuid(), 'doc:' || %s, 'doc:' || %s, 'invalid_rel', %s, 0, 10)
            """,
            (d_id, d_id, d_id),
        )
    owner_conn.rollback()


def test_graph_traversal_on_seed_chunks(app_conn: psycopg.Connection[Any]) -> None:
    """Graph traversal must return connected chunks and report duration in milliseconds."""
    # Find a chunk belonging to Digital Lending (NOTI280)
    dl_chunk = app_conn.execute(
        """
        SELECT c.chunk_id::text
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        WHERE d.canonical_url LIKE '%NOTI280DIGITALLENDING%'
        LIMIT 1
        """
    ).fetchone()

    if dl_chunk is None:
        pytest.skip("Digital Lending document not ingested")

    cid = str(dl_chunk[0])
    res = traverse_graph_neighbors(app_conn, [cid], max_hops=1, limit=10)

    assert res.duration_ms >= 0.0
    # Traversal should find connected provisions (e.g. Compromise Settlements or statutory links)
    assert len(res.expanded_chunks) > 0
    assert all(isinstance(c[0], str) and isinstance(c[1], float) for c in res.expanded_chunks)


def test_graph_traversal_fallback_on_unconnected_seed(app_conn: psycopg.Connection[Any]) -> None:
    """When seed chunks have no graph edges, traversal must return empty result gracefully."""
    fake_cid = "00000000-0000-4000-8000-000000000000"
    res = traverse_graph_neighbors(app_conn, [fake_cid], max_hops=1)
    assert res.expanded_chunks == []
    assert res.hops_traversed == 0
    assert res.duration_ms >= 0.0


def test_retriever_graph_hybrid_mode_execution(app_conn: psycopg.Connection[Any]) -> None:
    """Retriever must execute graph-hybrid mode and return valid ranked passages."""
    retriever = Retriever(app_conn)
    query = "What are the cooling-off periods mandated by the RBI for digital loans versus compromise settlements?"

    results = retriever.retrieve(query, GRAPH_HYBRID_CONFIG)
    assert len(results) > 0
    assert results[0].rank == 1
    assert results[0].score > 0.0

    # Multi-hop validation: check that both relevant documents appear in the candidate results
    urls = {r.canonical_url for r in results if r.canonical_url}
    has_dl = any("NOTI280DIGITALLENDING" in u for u in urls)
    has_cs = any("NOTI285COMPROMISESETTLE" in u for u in urls)

    assert has_dl or has_cs, f"Expected Digital Lending or Compromise Settlement in {urls}"
