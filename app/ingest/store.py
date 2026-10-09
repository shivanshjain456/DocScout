"""Transactional persistence — FR-4, FR-5, NFR-8, ARCHITECTURE §3.1.

One transaction per document, as ARCHITECTURE §3.1 specifies: a document, its version and
all of its chunks become visible together or not at all. A partially stored document is
worse than an absent one, because it is retrievable and incomplete.

The three rules this module implements, and where each is really enforced:

* **FR-5, de-duplicate by content hash first, then canonical URL.** The hash is checked
  before anything else, so the same payload served from two URLs stores one document. The
  check here is an optimisation and a source of honest reporting; the actual guarantee is
  `uq_versions_sha256`, which is global and will reject a duplicate even if this code is
  wrong or two ingests race.
* **FR-4, a changed hash at a known URL is a new version.** The previous current version
  is demoted in the same transaction that inserts the new one, so `uq_versions_one_current`
  is never transiently violated. Nothing is deleted — the application role has no DELETE
  privilege to do it with.
* **NFR-8, idempotent restartable ingestion.** Re-running over an unchanged corpus
  performs no writes at all. `version_exists` lets the pipeline establish that with one
  indexed SELECT per document, before paying for extraction and embedding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.ingest.chunk import Chunk
from app.ingest.ids import chunk_id
from app.ingest.source import SourceDocument


class Action(StrEnum):
    """What storing a document actually did."""

    INSERTED = "inserted"
    SUPERSEDED = "superseded"
    SKIPPED_UNCHANGED = "skipped_unchanged"
    SKIPPED_DUPLICATE_CONTENT = "skipped_duplicate_content"


@dataclass(frozen=True)
class PreparedDocument:
    """A document that has been extracted, cleaned, chunked and embedded."""

    document: SourceDocument
    text: str
    char_count: int
    clean_chars: int
    pages: int | None
    extractor: str
    chunks: list[Chunk]
    embeddings: np.ndarray
    embedding_model: str
    #: Invisible / private-use codepoints blanked during cleaning, keyed by "U+XXXX NAME".
    #: Carried here only so the ingest report can surface it; nothing is written to the
    #: database, because the blanked text itself is the stored record.
    invisible_removed: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StoreOutcome:
    """The result of attempting to store one document."""

    url: str
    action: Action
    document_id: UUID | None
    version_id: UUID | None
    chunks_written: int
    detail: str = ""

    @property
    def wrote(self) -> bool:
        return self.action in {Action.INSERTED, Action.SUPERSEDED}


def connect(dsn: str) -> psycopg.Connection[Any]:
    """Open a connection with the pgvector adapter registered.

    `autocommit=True` is deliberate: it means nothing is implicitly inside a transaction,
    so every write is inside an *explicit* `conn.transaction()` block and the per-document
    atomicity boundary is visible in the code rather than implied by connection state.
    """
    conn: psycopg.Connection[Any] = psycopg.connect(
        dsn, autocommit=True, application_name="docscout-ingest"
    )
    register_vector(conn)
    return conn


def version_exists(conn: psycopg.Connection[Any], sha256: str) -> bool:
    """True if this exact payload is already stored (NFR-8 fast path)."""
    row = conn.execute("SELECT 1 FROM document_versions WHERE sha256 = %s", (sha256,)).fetchone()
    return row is not None


def row_counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Current row counts, used as ingest evidence rather than as a claim."""
    row = conn.execute(
        """
        SELECT (SELECT count(*) FROM documents),
               (SELECT count(*) FROM document_versions),
               (SELECT count(*) FROM document_versions WHERE is_current),
               (SELECT count(*) FROM chunks)
        """
    ).fetchone()
    if row is None:  # pragma: no cover - a scalar aggregate always returns a row
        raise RuntimeError("row count query returned nothing")
    return {
        "documents": int(row[0]),
        "document_versions": int(row[1]),
        "current_versions": int(row[2]),
        "chunks": int(row[3]),
    }


@dataclass(frozen=True)
class SyncState:
    """Operational freshness and sync state of the corpus (P0-2)."""

    last_checked_at: datetime
    last_manifest_sha: str | None
    check_status: str
    documents_checked: int
    documents_current: int
    documents_superseded: int
    details: dict[str, Any]
    updated_at: datetime


def get_sync_state(conn: psycopg.Connection[Any]) -> SyncState | None:
    """Read the singleton corpus sync state, or None if uninitialised."""
    try:
        row = conn.execute(
            """
            SELECT last_checked_at, last_manifest_sha, check_status,
                   documents_checked, documents_current, documents_superseded,
                   details, updated_at
              FROM corpus_sync_state
             WHERE id = 1
            """
        ).fetchone()
        if row is None:
            return None
        return SyncState(
            last_checked_at=row[0],
            last_manifest_sha=str(row[1]) if row[1] is not None else None,
            check_status=str(row[2]),
            documents_checked=int(row[3]),
            documents_current=int(row[4]),
            documents_superseded=int(row[5]),
            details=row[6] if isinstance(row[6], dict) else {},
            updated_at=row[7],
        )
    except Exception:  # noqa: BLE001 - if table is missing or query fails, return None
        return None


def record_sync_state(
    conn: psycopg.Connection[Any],
    *,
    last_checked_at: datetime | None = None,
    last_manifest_sha: str | None = None,
    check_status: str = "ok",
    details: dict[str, Any] | None = None,
) -> SyncState:
    """Upsert the singleton sync state with current document and version counts."""
    checked_at = last_checked_at or datetime.now(UTC)
    meta = details or {}

    with conn.transaction():
        counts = row_counts(conn)
        docs_checked = counts["documents"]
        docs_current = counts["current_versions"]
        docs_superseded = counts["document_versions"] - counts["current_versions"]

        row = conn.execute(
            """
            INSERT INTO corpus_sync_state
                (id, last_checked_at, last_manifest_sha, check_status,
                 documents_checked, documents_current, documents_superseded,
                 details, updated_at)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (id) DO UPDATE SET
                last_checked_at = EXCLUDED.last_checked_at,
                last_manifest_sha = COALESCE(EXCLUDED.last_manifest_sha, corpus_sync_state.last_manifest_sha),
                check_status = EXCLUDED.check_status,
                documents_checked = EXCLUDED.documents_checked,
                documents_current = EXCLUDED.documents_current,
                documents_superseded = EXCLUDED.documents_superseded,
                details = EXCLUDED.details,
                updated_at = now()
            RETURNING last_checked_at, last_manifest_sha, check_status,
                      documents_checked, documents_current, documents_superseded,
                      details, updated_at
            """,
            (
                checked_at,
                last_manifest_sha,
                check_status,
                docs_checked,
                docs_current,
                docs_superseded,
                json.dumps(meta),
            ),
        ).fetchone()

    if row is None:
        raise RuntimeError("failed to record corpus sync state")

    return SyncState(
        last_checked_at=row[0],
        last_manifest_sha=str(row[1]) if row[1] is not None else None,
        check_status=str(row[2]),
        documents_checked=int(row[3]),
        documents_current=int(row[4]),
        documents_superseded=int(row[5]),
        details=row[6] if isinstance(row[6], dict) else {},
        updated_at=row[7],
    )


def _existing_version_for_hash(
    conn: psycopg.Connection[Any], sha256: str
) -> tuple[UUID, UUID, str] | None:
    row = conn.execute(
        """
        SELECT v.version_id, v.document_id, d.canonical_url
          FROM document_versions v
          JOIN documents d ON d.document_id = v.document_id
         WHERE v.sha256 = %s
        """,
        (sha256,),
    ).fetchone()
    if row is None:
        return None
    return UUID(str(row[0])), UUID(str(row[1])), str(row[2])


def store_document(conn: psycopg.Connection[Any], prepared: PreparedDocument) -> StoreOutcome:
    """Store one prepared document in a single transaction.

    Returns a `StoreOutcome` describing what happened; raises only on genuine faults, not
    on the ordinary outcomes of a document already being present.
    """
    doc = prepared.document

    if len(prepared.chunks) != len(prepared.embeddings):
        raise ValueError(
            f"{doc.url}: {len(prepared.chunks)} chunks but {len(prepared.embeddings)} embeddings"
        )

    try:
        with conn.transaction():
            # FR-5, content half. Authoritative inside the transaction, so a concurrent
            # ingest cannot slip a duplicate in between this check and the insert.
            existing = _existing_version_for_hash(conn, doc.sha256)
            if existing is not None:
                version_id, document_id, canonical_url = existing
                same_url = canonical_url == doc.url
                return StoreOutcome(
                    url=doc.url,
                    action=(
                        Action.SKIPPED_UNCHANGED if same_url else Action.SKIPPED_DUPLICATE_CONTENT
                    ),
                    document_id=document_id,
                    version_id=version_id,
                    chunks_written=0,
                    detail=(
                        "payload already stored for this URL"
                        if same_url
                        else f"identical payload already stored under {canonical_url}"
                    ),
                )

            # FR-5, URL half.
            row = conn.execute(
                "SELECT document_id FROM documents WHERE canonical_url = %s", (doc.url,)
            ).fetchone()

            if row is None:
                inserted = conn.execute(
                    """
                    INSERT INTO documents (canonical_url, source, authority, detail_page)
                    VALUES (%s, %s, %s, %s)
                    RETURNING document_id
                    """,
                    (doc.url, doc.source, doc.authority, doc.detail_page),
                ).fetchone()
                if inserted is None:  # pragma: no cover - RETURNING always yields a row
                    raise RuntimeError("document insert returned no id")
                document_id = UUID(str(inserted[0]))
                action = Action.INSERTED
            else:
                document_id = UUID(str(row[0]))
                # FR-4: demote the previous current version in the same transaction.
                demoted = conn.execute(
                    """
                    UPDATE document_versions SET is_current = false
                     WHERE document_id = %s AND is_current
                    """,
                    (document_id,),
                )
                action = Action.SUPERSEDED if demoted.rowcount > 0 else Action.INSERTED

            version_row = conn.execute(
                """
                INSERT INTO document_versions
                    (document_id, sha256, fetch_ts, http_status, bytes, pages,
                     extractor, char_count, is_current)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                RETURNING version_id
                """,
                (
                    document_id,
                    doc.sha256,
                    doc.fetch_ts,
                    doc.http_status,
                    doc.bytes_len,
                    prepared.pages,
                    prepared.extractor,
                    prepared.char_count,
                ),
            ).fetchone()
            if version_row is None:  # pragma: no cover - RETURNING always yields a row
                raise RuntimeError("version insert returned no id")
            version_id = UUID(str(version_row[0]))

            rows = [
                (
                    chunk_id(doc.sha256, chunk.char_start, chunk.char_end),
                    document_id,
                    version_id,
                    chunk.ordinal,
                    chunk.text,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.token_count,
                    prepared.embedding_model,
                    embedding,
                )
                for chunk, embedding in zip(prepared.chunks, prepared.embeddings, strict=True)
            ]
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chunks
                        (chunk_id, document_id, version_id, ordinal, text, char_start,
                         char_end, token_count, embedding_model, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )

            return StoreOutcome(
                url=doc.url,
                action=action,
                document_id=document_id,
                version_id=version_id,
                chunks_written=len(rows),
            )

    except psycopg.errors.UniqueViolation as exc:
        # Another ingest stored this payload between the check and the insert. The
        # transaction has rolled back, so the outcome is the same as having seen it.
        if exc.diag.constraint_name == "uq_versions_sha256":
            return StoreOutcome(
                url=doc.url,
                action=Action.SKIPPED_DUPLICATE_CONTENT,
                document_id=None,
                version_id=None,
                chunks_written=0,
                detail="lost a race with a concurrent ingest storing the same payload",
            )
        raise
