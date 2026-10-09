"""Dense retrieval over pgvector.

Only chunks belonging to the **current** version of a document are returned. Superseded
versions are retained in the database -- FR-4 makes retention a guarantee and the
application role holds no DELETE -- so without this predicate an amended circular keeps
answering questions as though it were in force. That is the worst failure available to a
compliance tool, and it was reachable: measured before this filter existed, marking one
version superseded left all ten of its chunks in the top ten.

Scaling note, stated rather than discovered later: this is a post-filter on a column the
HNSW index does not cover, so at corpus scale pgvector may have to over-fetch to fill k.
At 170 chunks the planner chooses a sequential scan regardless. The fix when that stops
being true is `hnsw.iterative_scan = relaxed_order`, or denormalising `is_current` onto
`chunks` so a partial index can carry it -- not removing the predicate.

Why cosine distance (`<=>`) when ADR-0002 guarantees unit-norm vectors and inner product
would be marginally cheaper: with L2-normalised vectors the two give identical rankings,
so the only difference is failure behaviour. If normalisation ever regresses, cosine keeps
ranking by angle while inner product silently starts ranking by magnitude -- a bug that
produces plausible-looking results and no error. The schema's HNSW index is built with
vector_cosine_ops, and an opclass only accelerates its own operator, so the choice is also
the only one that uses the index.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import psycopg

from app.retrieval.types import MetadataFilter
from app.rowtypes import as_float, as_str


def search(
    conn: psycopg.Connection[tuple[object, ...]],
    query_vector: np.ndarray,
    k: int,
    filter: MetadataFilter | None = None,
) -> list[tuple[str, float]]:
    """Return the top-k (chunk_id, similarity), highest similarity first.

    Similarity is 1 - cosine distance, so it rises with relevance like the BM25 score
    does. Fusion is rank-based and does not care, but a report that prints raw scores
    should not print one column where bigger is better next to one where it is not.

    Filtering (P1-2) is executed in-query so Postgres can leverage index scans on
    documents (source, published_date) and document_versions (is_current, fetch_ts).
    """
    vector = np.asarray(query_vector, dtype=np.float32).tolist()
    params: dict[str, Any] = {"vector": vector, "k": k}
    where_clauses: list[str] = []

    # Version currency filter
    is_curr = filter.is_current if filter is not None else True
    if is_curr is True:
        where_clauses.append("v.is_current")
    elif is_curr is False:
        where_clauses.append("NOT v.is_current")

    if filter is not None:
        if filter.source is not None:
            if isinstance(filter.source, str):
                where_clauses.append("d.source = %(source)s")
                params["source"] = filter.source
            else:
                where_clauses.append("d.source = ANY(%(sources)s)")
                params["sources"] = list(filter.source)

        if filter.date_from is not None:
            where_clauses.append("COALESCE(d.published_date, v.fetch_ts::date) >= %(date_from)s")
            params["date_from"] = filter.date_from

        if filter.date_to is not None:
            where_clauses.append("COALESCE(d.published_date, v.fetch_ts::date) <= %(date_to)s")
            params["date_to"] = filter.date_to

        if filter.document_ids is not None:
            where_clauses.append("c.document_id = ANY(%(document_ids)s::uuid[])")
            params["document_ids"] = filter.document_ids

        if filter.canonical_url is not None:
            where_clauses.append("d.canonical_url = %(canonical_url)s")
            params["canonical_url"] = filter.canonical_url

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        SELECT c.chunk_id::text, 1.0 - (c.embedding <=> %(vector)s::vector) AS similarity
        FROM chunks AS c
        JOIN document_versions AS v ON v.version_id = c.version_id
        JOIN documents AS d ON d.document_id = c.document_id
        {where_sql}
        ORDER BY c.embedding <=> %(vector)s::vector
        LIMIT %(k)s
    """  # noqa: S608 - predicate templates are fixed literals; all dynamic values are securely bound in params
    rows = conn.execute(query, params).fetchall()

    return [(as_str(r[0]), as_float(r[1])) for r in rows]
