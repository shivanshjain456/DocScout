"""Tests for the retrieval port abstraction and adapter registry (P2-1).

Validates:
1. Protocol conformance of PgVectorStore to VectorStore.
2. Independent operation of Retriever with an in-memory VectorStore double (zero DB required).
3. Parity between PgVectorStore adapter and direct dense.search SQL.
4. Error handling and dynamic extension in the adapter registry.
5. Exact output and rank preservation through Retriever with the port.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import psycopg
import pytest

from app.ingest.embed import EMBEDDING_DIM
from app.retrieval import dense
from app.retrieval.port import (
    ChunkRow,
    PgVectorStore,
    VectorStore,
    get_vector_store,
    register_vector_store,
)
from app.retrieval.search import Retriever
from app.retrieval.types import SERVING_CONFIG, MetadataFilter, RetrievalConfig


class InMemoryVectorStore:
    """In-memory test double conforming to VectorStore with zero PostgreSQL dependency."""

    def __init__(self) -> None:
        self.vectors: dict[str, np.ndarray] = {}
        self.metadata: dict[str, ChunkRow] = {}

    def add(self, chunk_id: str, vector: np.ndarray, meta: ChunkRow) -> None:
        self.vectors[chunk_id] = vector
        self.metadata[chunk_id] = meta

    def search(
        self,
        query_vector: np.ndarray,
        k: int,
        filter: MetadataFilter | None = None,
    ) -> list[tuple[str, float]]:
        hits: list[tuple[str, float]] = []
        q = np.asarray(query_vector, dtype=np.float32)
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0.0:
            return []

        for cid, vec in self.vectors.items():
            meta = self.metadata.get(cid)
            if filter is not None and not filter.matches(meta):  # type: ignore[arg-type]
                continue
            v = np.asarray(vec, dtype=np.float32)
            v_norm = float(np.linalg.norm(v))
            if v_norm == 0.0:
                sim = 0.0
            else:
                sim = float(np.dot(q, v) / (q_norm * v_norm))
            hits.append((cid, sim))

        hits.sort(key=lambda x: x[1], reverse=True)
        return hits[:k]

    def fetch_metadata(
        self,
        chunk_ids: list[str],
        is_current: bool | None = True,
    ) -> dict[str, ChunkRow]:
        result: dict[str, ChunkRow] = {}
        for cid in chunk_ids:
            if cid in self.metadata:
                result[cid] = self.metadata[cid]
        return result


class DummyEmbedder:
    """Deterministic dummy embedder returning a fixed non-zero vector."""

    def encode_query(self, query: str) -> np.ndarray:
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        vec[0] = 1.0
        return vec


def test_vector_store_protocol_conformance() -> None:
    """PgVectorStore and InMemoryVectorStore must both satisfy VectorStore Protocol."""
    dummy_conn = object()
    pg_store = PgVectorStore(dummy_conn)  # type: ignore[arg-type]
    assert isinstance(pg_store, VectorStore)

    mem_store = InMemoryVectorStore()
    assert isinstance(mem_store, VectorStore)


def test_retriever_runs_with_in_memory_vector_store_without_database() -> None:
    """Retriever must execute dense retrieval through the port with zero DB connection."""
    store = InMemoryVectorStore()
    cid1 = "11111111-1111-5111-8111-111111111111"
    cid2 = "22222222-2222-5222-8222-222222222222"

    v1 = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v1[0] = 1.0  # high similarity to DummyEmbedder
    v2 = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v2[1] = 1.0  # orthogonal similarity (0.0)

    store.add(
        cid1,
        v1,
        ChunkRow(
            document_id="doc-1",
            source="RBI",
            text="Digital lending guidelines cooling-off period is 3 days.",
            canonical_url="https://rbi.org.in/dl.pdf",
            char_start=0,
            char_end=58,
            title="RBI Digital Lending Guidelines",
            published_date="2024-01-15",
        ),
    )
    store.add(
        cid2,
        v2,
        ChunkRow(
            document_id="doc-2",
            source="SEBI",
            text="Unrelated securities market regulation.",
            canonical_url=None,
            char_start=0,
            char_end=39,
            title="SEBI Clause",
            published_date="2023-05-10",
        ),
    )

    # Initialize Retriever with vector_store directly, conn=None
    retriever = Retriever(vector_store=store, embedder=DummyEmbedder())  # type: ignore[arg-type]
    config = RetrievalConfig(name="test-dense", mode="dense", k_dense=5, k_final=5)

    results = retriever.retrieve("cooling off period", config)
    assert len(results) == 2
    assert results[0].chunk_id == cid1
    assert results[0].score > results[1].score
    assert results[0].title == "RBI Digital Lending Guidelines"
    assert results[0].source == "RBI"
    assert results[0].canonical_url == "https://rbi.org.in/dl.pdf"
    assert "Digital lending" in results[0].text


def test_retriever_without_conn_and_without_store_raises() -> None:
    """Retriever must fail fast if neither conn nor vector_store is provided."""
    with pytest.raises(ValueError, match="Retriever requires either an active database"):
        Retriever(conn=None, vector_store=None)


def test_registry_lookup_and_error_handling() -> None:
    """Registry must enforce presence of registered adapter and reject unknowns."""
    with pytest.raises(ValueError, match="PgVectorStore adapter requires an active database"):
        get_vector_store("pgvector", conn=None)

    with pytest.raises(ValueError, match="Unknown vector store adapter 'nonexistent'"):
        get_vector_store("nonexistent")

    class CustomTestStore:
        def search(self, *args: Any, **kwargs: Any) -> list[tuple[str, float]]:
            return []

        def fetch_metadata(self, *args: Any, **kwargs: Any) -> dict[str, ChunkRow]:
            return {}

    register_vector_store("custom_unit_test", CustomTestStore)
    adapter = get_vector_store("custom_unit_test")
    assert isinstance(adapter, CustomTestStore)


def test_pgvector_adapter_parity_with_direct_dense_search(
    app_conn: psycopg.Connection[Any],
) -> None:
    """PgVectorStore.search must produce exact identical hits and scores to dense.search."""
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vec[0] = 0.5
    vec[1] = 0.5
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm

    k = 5
    direct_hits = dense.search(app_conn, vec, k=k)
    store = PgVectorStore(app_conn)
    store_hits = store.search(vec, k=k)

    assert len(direct_hits) == len(store_hits)
    for (d_id, d_score), (s_id, s_score) in zip(direct_hits, store_hits, strict=True):
        assert d_id == s_id
        assert pytest.approx(d_score, abs=1e-6) == s_score

    # Fetch metadata through adapter
    chunk_ids = [cid for cid, _ in store_hits]
    meta = store.fetch_metadata(chunk_ids)
    assert len(meta) == len(chunk_ids)
    for cid in chunk_ids:
        assert cid in meta
        row = meta[cid]
        assert isinstance(row.text, str)
        assert len(row.text) > 0
        assert row.char_end > row.char_start


def test_retriever_serving_config_end_to_end_parity(
    app_conn: psycopg.Connection[Any],
) -> None:
    """Retriever with PgVectorStore must execute hybrid-rrf seamlessly and return valid hits."""
    retriever = Retriever(app_conn)
    query = "What is the cooling-off period for digital loans?"
    results = retriever.retrieve(query, SERVING_CONFIG)

    assert len(results) > 0
    assert results[0].rank == 1
    assert results[0].score > 0.0
    assert len(results[0].text) > 0
    assert results[0].document_id != ""
