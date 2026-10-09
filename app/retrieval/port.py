"""Retrieval port abstraction and adapter registry (P2-1).

Decouples the retrieval pipeline from the concrete pgvector datastore implementation.
Per ADR-0019, DocScout maintains a single production adapter ('pgvector') while establishing
a clean port abstraction (VectorStore Protocol) so alternative embedding dimensions, vector
engines, or test doubles can be plugged in without modifying retrieval, fusion, or API logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import psycopg

from app.retrieval import dense
from app.retrieval.types import MetadataFilter
from app.rowtypes import as_int, as_str


@dataclass(frozen=True)
class ChunkRow:
    """Attribution and display metadata hydrated for retrieved chunks."""

    document_id: str
    source: str
    text: str
    canonical_url: str | None
    char_start: int
    char_end: int
    title: str | None = None
    published_date: str | None = None


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for dense vector retrieval and chunk metadata hydration."""

    def search(
        self,
        query_vector: np.ndarray,
        k: int,
        filter: MetadataFilter | None = None,
    ) -> list[tuple[str, float]]:
        """Return the top-k (chunk_id, similarity) tuples sorted descending by similarity."""
        ...

    def fetch_metadata(
        self,
        chunk_ids: list[str],
        is_current: bool | None = True,
    ) -> dict[str, ChunkRow]:
        """Fetch display and attribution metadata for a set of chunk IDs."""
        ...


class PgVectorStore:
    """Production vector store adapter targeting PostgreSQL with pgvector extension."""

    def __init__(self, conn: psycopg.Connection[tuple[object, ...]]) -> None:
        self._conn = conn

    def search(
        self,
        query_vector: np.ndarray,
        k: int,
        filter: MetadataFilter | None = None,
    ) -> list[tuple[str, float]]:
        return dense.search(self._conn, query_vector, k, filter=filter)

    def fetch_metadata(
        self,
        chunk_ids: list[str],
        is_current: bool | None = True,
    ) -> dict[str, ChunkRow]:
        if not chunk_ids:
            return {}

        where_condition = "AND v.is_current"
        if is_current is False:
            where_condition = "AND NOT v.is_current"
        elif is_current is None:
            where_condition = ""

        query = f"""
            SELECT c.chunk_id::text, c.document_id::text, d.source, c.text,
                   d.canonical_url, c.char_start, c.char_end,
                   d.title, d.published_date::text
            FROM chunks AS c
            JOIN documents AS d ON d.document_id = c.document_id
            JOIN document_versions AS v ON v.version_id = c.version_id
            WHERE c.chunk_id = ANY(%s::uuid[]) {where_condition}
        """  # noqa: S608 - where_condition is fixed literal template; chunk_ids are parameterized
        rows = self._conn.execute(query, (chunk_ids,)).fetchall()

        result: dict[str, ChunkRow] = {}
        for chunk_id, document_id, source, text, url, start, end, title, pub_date in rows:
            result[as_str(chunk_id)] = ChunkRow(
                document_id=as_str(document_id),
                source=as_str(source),
                text=as_str(text),
                canonical_url=None if url is None else as_str(url),
                char_start=as_int(start),
                char_end=as_int(end),
                title=as_str(title) if title is not None else None,
                published_date=as_str(pub_date) if pub_date is not None else None,
            )
        return result


ADAPTER_REGISTRY: dict[str, type[VectorStore]] = {
    "pgvector": PgVectorStore,
}


def register_vector_store(name: str, adapter_cls: type[VectorStore]) -> None:
    """Register an adapter in the global registry."""
    ADAPTER_REGISTRY[name] = adapter_cls


def get_vector_store(
    name: str = "pgvector",
    conn: psycopg.Connection[tuple[object, ...]] | None = None,
) -> VectorStore:
    """Instantiate a vector store adapter by name from the registry."""
    adapter_cls = ADAPTER_REGISTRY.get(name)
    if adapter_cls is None:
        available = ", ".join(repr(k) for k in sorted(ADAPTER_REGISTRY.keys()))
        raise ValueError(
            f"Unknown vector store adapter {name!r}. Available adapters in registry: {available}"
        )
    if adapter_cls is PgVectorStore:
        if conn is None:
            raise ValueError("PgVectorStore adapter requires an active database connection")
        return PgVectorStore(conn)
    # For custom / test adapters that accept no args or optional conn
    try:
        return adapter_cls()
    except TypeError:
        if conn is not None:
            return adapter_cls(conn)  # type: ignore[call-arg]
        raise
