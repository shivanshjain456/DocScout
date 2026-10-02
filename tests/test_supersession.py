"""Superseded document versions must never be retrievable.

The domain makes this the central correctness question rather than an edge case: RBI and
SEBI amend and withdraw circulars constantly, and the gold set contains a question about a
*withdrawn* one. A compliance tool that answers from a superseded circular as though it
were in force is worse than one that answers nothing.

The combination that made this reachable is specific to this schema. `store.py` demotes
the previous version on supersession (`is_current = false`), FR-4 makes retention a
guarantee, and the application role holds no DELETE — so the old chunks necessarily remain
in `chunks`. Nothing in the retrieval path excluded them. Measured before the fix: marking
one version superseded left all ten of its chunks in the top ten.

These tests build their own two-version document rather than reusing the corpus, because
every ingested document currently has exactly one version, which is precisely why the
defect stayed invisible.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from app.ingest.embed import EMBEDDING_DIM
from app.retrieval import RetrievalConfig, Retriever
from app.retrieval.lexical import BM25Index

# Distinctive wording so a match is unambiguous and cannot be confused with corpus text.
SUPERSEDED_TEXT = (
    "Entities shall settle zorbitrage transactions within T plus nine working days "
    "under the previous zorbitrage settlement directive."
)
CURRENT_TEXT = (
    "Entities shall settle zorbitrage transactions within T plus one working day "
    "under the revised zorbitrage settlement directive."
)
QUERY = "zorbitrage settlement directive working days"


def _unit_vector() -> str:
    """A valid unit-norm embedding; `ck_chunks_unit_norm` rejects anything else."""
    values = [0.0] * EMBEDDING_DIM
    values[0] = 1.0
    return "[" + ",".join(str(v) for v in values) + "]"


@pytest.fixture
def two_version_document(
    owner_conn: psycopg.Connection[Any],
) -> Iterator[tuple[str, str, str]]:
    """One document, an old superseded version and a current one, each with a chunk.

    Committed on the session-scoped owner connection rather than written inside the
    rolled-back `db` fixture, because the assertions read through `app_conn` -- a separate
    connection, which cannot see another transaction's uncommitted rows. Torn down
    explicitly afterwards, including on failure.

    The fixture writes the superseded state directly: the behaviour under test is
    retrieval, not the demotion logic `store.py` already owns and tests.
    Returns (superseded_chunk_id, current_chunk_id, document_id).
    """
    doc_id = owner_conn.execute(
        "INSERT INTO documents (canonical_url, source, title) "
        "VALUES ('https://rbidocs.rbi.org.in/zorbitrage-test', 'RBI', 'Zorbitrage') "
        "RETURNING document_id"
    ).fetchone()
    assert doc_id is not None
    document_id = str(doc_id[0])

    chunk_ids: list[str] = []
    for index, (sha, text, is_current) in enumerate(
        [("a" * 64, SUPERSEDED_TEXT, False), ("b" * 64, CURRENT_TEXT, True)]
    ):
        version = owner_conn.execute(
            "INSERT INTO document_versions "
            "(document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, "
            " char_count, is_current) "
            "VALUES (%s, %s, now(), 200, 1000, 1, 'pypdf', 1200, %s) RETURNING version_id",
            (document_id, sha, is_current),
        ).fetchone()
        assert version is not None
        version_id = str(version[0])
        row = owner_conn.execute(
            "INSERT INTO chunks (chunk_id, document_id, version_id, ordinal, text, "
            " char_start, char_end, token_count, embedding_model, embedding) "
            "VALUES (gen_random_uuid(), %s, %s, 0, %s, %s, %s, 20, 'test', %s::vector) "
            "RETURNING chunk_id::text",
            (
                document_id,
                version_id,
                text,
                index * 10_000,
                index * 10_000 + len(text),
                _unit_vector(),
            ),
        ).fetchone()
        assert row is not None
        chunk_ids.append(str(row[0]))

    owner_conn.commit()
    try:
        yield chunk_ids[0], chunk_ids[1], document_id
    finally:
        owner_conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        owner_conn.execute("DELETE FROM document_versions WHERE document_id = %s", (document_id,))
        owner_conn.execute("DELETE FROM documents WHERE document_id = %s", (document_id,))
        owner_conn.commit()


def bm25_config() -> RetrievalConfig:
    return RetrievalConfig(name="supersession", mode="bm25", k_lexical=50, k_final=20)


# --- the lexical arm --------------------------------------------------------------------
def test_superseded_chunk_is_not_retrievable(
    app_conn: psycopg.Connection[Any], two_version_document: tuple[str, str, str]
) -> None:
    """The regression test for the defect. Fails against a retrieval path without the filter."""
    superseded, current, _ = two_version_document
    found = {hit.chunk_id for hit in Retriever(app_conn).retrieve(QUERY, bm25_config())}
    assert current in found, "the in-force version must still be retrievable"
    assert superseded not in found, "a superseded circular was served as current"


def test_superseded_text_is_absent_from_the_bm25_term_table(
    app_conn: psycopg.Connection[Any], two_version_document: tuple[str, str, str]
) -> None:
    """Excluded at index build, not after scoring.

    Superseded terms left in the table would distort document frequency and average
    document length, which changes the score of every *current* chunk — a subtler fault
    than returning the wrong row.
    """
    superseded, _, _ = two_version_document
    index = BM25Index(app_conn)
    assert index.lexemes_of(superseded) == set()


def test_corpus_statistics_count_only_current_versions(
    app_conn: psycopg.Connection[Any], two_version_document: tuple[str, str, str]
) -> None:
    index = BM25Index(app_conn)
    current_chunks = app_conn.execute(
        "SELECT count(*) FROM chunks c JOIN document_versions v USING (version_id) "
        "WHERE v.is_current"
    ).fetchone()
    assert current_chunks is not None
    assert index.n_documents == int(current_chunks[0])


# --- the dense arm ----------------------------------------------------------------------
def test_dense_arm_excludes_superseded_chunks(
    app_conn: psycopg.Connection[Any], two_version_document: tuple[str, str, str]
) -> None:
    import numpy as np

    from app.retrieval import dense

    superseded, _, _ = two_version_document
    # The exact vector both fixture chunks carry, so only the filter can separate them.
    probe = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    probe[0] = 1.0
    returned = {chunk_id for chunk_id, _ in dense.search(app_conn, probe, 200)}
    assert superseded not in returned


# --- metadata hydration -----------------------------------------------------------------
def test_metadata_lookup_refuses_a_superseded_chunk_id(
    app_conn: psycopg.Connection[Any], two_version_document: tuple[str, str, str]
) -> None:
    """Defence in depth: a stale id from a cache must not hydrate into a served passage."""
    superseded, _, _ = two_version_document
    retriever = Retriever(app_conn)
    assert retriever._metadata([superseded]) == {}  # noqa: SLF001 - no public accessor


# --- the retained row is still there ------------------------------------------------------
def test_superseded_rows_are_retained_not_deleted(
    owner_conn: psycopg.Connection[Any], two_version_document: tuple[str, str, str]
) -> None:
    """FR-4 is a retention guarantee: excluded from retrieval, never removed from storage."""
    superseded, _, document_id = two_version_document
    row = owner_conn.execute(
        "SELECT count(*) FROM chunks WHERE chunk_id = %s", (superseded,)
    ).fetchone()
    assert row is not None and int(row[0]) == 1
    versions = owner_conn.execute(
        "SELECT count(*) FROM document_versions WHERE document_id = %s", (document_id,)
    ).fetchone()
    assert versions is not None and int(versions[0]) == 2
