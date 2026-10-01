"""Dense retrieval over pgvector.

Why cosine distance (`<=>`) when ADR-0002 guarantees unit-norm vectors and inner product
would be marginally cheaper: with L2-normalised vectors the two give identical rankings,
so the only difference is failure behaviour. If normalisation ever regresses, cosine keeps
ranking by angle while inner product silently starts ranking by magnitude -- a bug that
produces plausible-looking results and no error. The schema's HNSW index is built with
vector_cosine_ops, and an opclass only accelerates its own operator, so the choice is also
the only one that uses the index.
"""

from __future__ import annotations

import numpy as np
import psycopg

from app.rowtypes import as_float, as_str


def search(
    conn: psycopg.Connection[tuple[object, ...]],
    query_vector: np.ndarray,
    k: int,
) -> list[tuple[str, float]]:
    """Return the top-k (chunk_id, similarity), highest similarity first.

    Similarity is 1 - cosine distance, so it rises with relevance like the BM25 score
    does. Fusion is rank-based and does not care, but a report that prints raw scores
    should not print one column where bigger is better next to one where it is not.
    """
    vector = np.asarray(query_vector, dtype=np.float32).tolist()
    rows = conn.execute(
        """
        SELECT chunk_id::text, 1.0 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (vector, vector, k),
    ).fetchall()
    return [(as_str(r[0]), as_float(r[1])) for r in rows]
