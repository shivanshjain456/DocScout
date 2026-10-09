"""Knowledge-Graph assisted retrieval over regulatory provisions (P2-2).

Enables multi-hop cross-circular candidate expansion by traversing grounded relationships
('amends', 'supersedes', 'cites', 'implements', 'references') between provisions.
When graph traversal finds connected provisions across regulatory circulars, those chunks
are expanded into the candidate pool and fused with dense and lexical rankings.
If no graph neighbors exist, execution cleanly falls back to standard hybrid fusion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import psycopg

from app.rowtypes import as_str

# Relationship weights for graph candidate proximity scoring
RELATION_WEIGHTS: dict[str, float] = {
    "amends": 1.0,
    "supersedes": 1.0,
    "implements": 0.9,
    "references": 0.85,
    "cites": 0.8,
}


@dataclass(frozen=True)
class GraphTraversalResult:
    """Outcome of a knowledge-graph traversal."""

    expanded_chunks: list[tuple[str, float]]  # (chunk_id, graph_score)
    duration_ms: float
    hops_traversed: int


def traverse_graph_neighbors(
    conn: psycopg.Connection[tuple[object, ...]],
    seed_chunk_ids: list[str],
    max_hops: int = 1,
    limit: int = 25,
) -> GraphTraversalResult:
    """Traverse graph edges starting from seed chunk IDs to expand connected regulatory chunks."""
    start_time = time.perf_counter()
    if not seed_chunk_ids:
        return GraphTraversalResult(expanded_chunks=[], duration_ms=0.0, hops_traversed=0)

    # 1. 1-hop traversal: find edges where seed chunk is directly cited or its document participates
    query = """
        WITH seed_docs AS (
            SELECT DISTINCT document_id
            FROM chunks
            WHERE chunk_id = ANY(%s::uuid[])
        ),
        seed_nodes AS (
            SELECT n.node_id, n.document_id
            FROM graph_nodes n
            WHERE n.document_id IN (SELECT document_id FROM seed_docs)
        ),
        direct_edges AS (
            -- Outgoing edges from seed nodes
            SELECT
                e.relation,
                e.target_document_id AS target_doc,
                e.chunk_id AS edge_chunk
            FROM graph_edges e
            WHERE e.source_node_id IN (SELECT node_id FROM seed_nodes)
               OR e.chunk_id = ANY(%s::uuid[])

            UNION ALL

            -- Incoming edges to seed nodes (e.g. provisions citing the seed)
            SELECT
                e.relation,
                e.source_document_id AS target_doc,
                e.chunk_id AS edge_chunk
            FROM graph_edges e
            WHERE e.target_node_id IN (SELECT node_id FROM seed_nodes)
        ),
        target_chunks AS (
            -- Expand to chunks belonging to target documents or directly tagged on edges
            SELECT DISTINCT
                c.chunk_id::text,
                de.relation,
                c.ordinal
            FROM direct_edges de
            JOIN chunks c ON (
                (de.edge_chunk IS NOT NULL AND c.chunk_id = de.edge_chunk)
                OR (de.target_doc IS NOT NULL AND c.document_id = de.target_doc)
            )
            JOIN document_versions v ON v.version_id = c.version_id AND v.is_current
            WHERE c.chunk_id != ALL(%s::uuid[])
        )
        SELECT
            chunk_id,
            relation,
            ordinal
        FROM target_chunks
        LIMIT %s;
    """  # noqa: S608 - all inputs are parameterized

    rows = conn.execute(query, (seed_chunk_ids, seed_chunk_ids, seed_chunk_ids, limit)).fetchall()

    expanded: dict[str, float] = {}
    for r in rows:
        cid = as_str(r[0])
        rel = as_str(r[1])
        rel_weight = RELATION_WEIGHTS.get(rel, 0.7)
        # Give higher priority to earlier ordinals within connected documents
        score = rel_weight
        if cid not in expanded or score > expanded[cid]:
            expanded[cid] = score

    sorted_chunks = sorted(expanded.items(), key=lambda x: x[1], reverse=True)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    return GraphTraversalResult(
        expanded_chunks=sorted_chunks,
        duration_ms=duration_ms,
        hops_traversed=1 if sorted_chunks else 0,
    )
