"""Ingestion orchestration — ARCHITECTURE §3.1 stages, end to end.

fetch (from the manifest) → extract → guard → clean → chunk → embed → store.

Two ordering decisions worth stating, because both are about honesty rather than speed:

* **The content-hash check runs before extraction and embedding, not after.** It is what
  makes NFR-8 real in practice: re-running over an unchanged corpus does no work and no
  writes, instead of spending four minutes re-embedding 170 chunks to discover it had
  nothing to store.
* **A bad document is recorded, not fatal; a bad corpus is fatal.** An extraction failure
  or a document under FR-3's floor is per-document news: it is counted, named in the
  report, and the run continues, because the flagged-document count is itself an M2
  deliverable. A manifest that disagrees with the bytes on disk aborts the run — that is
  not one bad document, it is a corpus that is not what it claims to be.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from app.ingest.chunk import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_TOKENS,
    Chunk,
    chunk_document,
    uncovered_characters,
)
from app.ingest.clean import clean_preserving_offsets
from app.ingest.embed import Embedder
from app.ingest.errors import ExtractionError, ShortExtractionError
from app.ingest.extract import assert_extraction_long_enough, extract
from app.ingest.source import SourceDocument
from app.ingest.store import (
    Action,
    PreparedDocument,
    StoreOutcome,
    row_counts,
    store_document,
    version_exists,
)


@dataclass
class DocumentResult:
    """What happened to one document, in enough detail to audit the run."""

    url: str
    source: str
    status: str
    action: str | None = None
    document_id: str | None = None
    version_id: str | None = None
    chunks: int = 0
    char_count: int = 0
    clean_chars: int = 0
    pages: int | None = None
    extractor: str | None = None
    token_min: int | None = None
    token_mean: float | None = None
    token_max: int | None = None
    uncovered_chars: int | None = None
    elapsed_ms: int = 0
    detail: str = ""


@dataclass
class IngestReport:
    """A full ingest run, serialisable as the evidence for M2 exit criterion 4."""

    started_at: str
    finished_at: str = ""
    duration_s: float = 0.0
    embedding_model: str = ""
    chunk_size: int = CHUNK_SIZE
    chunk_overlap: int = CHUNK_OVERLAP
    max_tokens: int = MAX_TOKENS
    counts_before: dict[str, int] = field(default_factory=dict)
    counts_after: dict[str, int] = field(default_factory=dict)
    documents: list[DocumentResult] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        counted: dict[str, int] = {
            "documents_seen": len(self.documents),
            "chunks_written": sum(d.chunks for d in self.documents),
            "failed": sum(1 for d in self.documents if d.status == "failed"),
        }
        for action in Action:
            counted[str(action)] = sum(1 for d in self.documents if d.action == str(action))
        return counted

    @property
    def wrote_anything(self) -> bool:
        return self.counts_before != self.counts_after

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration_s, 3),
            "embedding_model": self.embedding_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "max_tokens": self.max_tokens,
            "counts_before": self.counts_before,
            "counts_after": self.counts_after,
            "totals": self.totals,
            "documents": [asdict(d) for d in self.documents],
        }

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "ingest.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n")
        return path


@dataclass(frozen=True)
class ChunkedDocument:
    """The canonical text of a document and the chunks cut from it, before embedding.

    Separated from `prepare_document` because two callers need the geometry without the
    vectors: the ingester, which goes on to embed, and the gold-set resolver, which only
    needs to know which chunk a quoted passage falls in. Keeping one definition is the
    point -- a second copy of extract → clean → chunk could drift from the shipped
    pipeline, and a gold set pinned against a drifted chunker cites chunks that do not
    exist (ADR-0005).
    """

    text: str
    clean_chars: int
    pages: int | None
    extractor: str
    chunks: list[Chunk]


def chunk_source_document(
    document: SourceDocument, count_tokens: Callable[[str], int]
) -> ChunkedDocument:
    """Run extract → clean → guard → chunk. No embedding, no database."""
    extraction = extract(document.content, media_type=document.media_type)
    if not extraction.text.strip():
        raise ExtractionError(f"{document.url}: {extraction.extractor} produced no text")

    text = clean_preserving_offsets(extraction.text)
    clean_chars = assert_extraction_long_enough(text, url=document.url)

    chunks = chunk_document(text, count_tokens)
    if not chunks:
        raise ExtractionError(f"{document.url}: cleaning left no chunkable text")

    return ChunkedDocument(
        text=text,
        clean_chars=clean_chars,
        pages=extraction.pages,
        extractor=extraction.extractor,
        chunks=chunks,
    )


def prepare_document(document: SourceDocument, embedder: Embedder) -> PreparedDocument:
    """Run the pure stages: extract → clean → guard → chunk → embed.

    Raises `ExtractionError` or `ShortExtractionError` for a document that must not be
    stored. Touches no database.
    """
    cut = chunk_source_document(document, embedder.count_tokens)
    embeddings = embedder.encode_passages([c.text for c in cut.chunks])

    return PreparedDocument(
        document=document,
        text=cut.text,
        # The length of the text the offsets index into. Cleaning is length-preserving,
        # so this equals the raw extraction length; `clean_chars` is the non-whitespace
        # count FR-3's floor is tested against.
        char_count=len(cut.text),
        clean_chars=cut.clean_chars,
        pages=cut.pages,
        extractor=cut.extractor,
        chunks=cut.chunks,
        embeddings=embeddings,
        embedding_model=embedder.model_id,
    )


def _result_from_outcome(
    document: SourceDocument,
    prepared: PreparedDocument,
    outcome: StoreOutcome,
    elapsed_ms: int,
) -> DocumentResult:
    tokens = [c.token_count for c in prepared.chunks]
    return DocumentResult(
        url=document.url,
        source=document.source,
        status="ok",
        action=str(outcome.action),
        document_id=str(outcome.document_id) if outcome.document_id else None,
        version_id=str(outcome.version_id) if outcome.version_id else None,
        chunks=outcome.chunks_written,
        char_count=prepared.char_count,
        clean_chars=prepared.clean_chars,
        pages=prepared.pages,
        extractor=prepared.extractor,
        token_min=min(tokens),
        token_mean=round(sum(tokens) / len(tokens), 1),
        token_max=max(tokens),
        uncovered_chars=uncovered_characters(prepared.text, prepared.chunks),
        elapsed_ms=elapsed_ms,
        detail=outcome.detail,
    )


def run_ingest(
    documents: Iterable[SourceDocument],
    conn: psycopg.Connection[Any],
    embedder: Embedder,
    *,
    dry_run: bool = False,
    on_progress: Any = None,
) -> IngestReport:
    """Ingest `documents`, returning a report of what happened to each."""
    report = IngestReport(
        started_at=datetime.now(UTC).isoformat(),
        embedding_model=embedder.model_id,
    )
    report.counts_before = row_counts(conn)
    run_started = time.perf_counter()

    for document in documents:
        started = time.perf_counter()

        # NFR-8 fast path: skip before paying for extraction and embedding.
        if version_exists(conn, document.sha256):
            result = DocumentResult(
                url=document.url,
                source=document.source,
                status="ok",
                action=str(Action.SKIPPED_UNCHANGED),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                detail="content hash already stored; no extraction or embedding performed",
            )
            report.documents.append(result)
            if on_progress:
                on_progress(result)
            continue

        try:
            prepared = prepare_document(document, embedder)
        except (ExtractionError, ShortExtractionError) as exc:
            result = DocumentResult(
                url=document.url,
                source=document.source,
                status="failed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                detail=f"{type(exc).__name__}: {exc}",
            )
            report.documents.append(result)
            if on_progress:
                on_progress(result)
            continue

        if dry_run:
            tokens = [c.token_count for c in prepared.chunks]
            result = DocumentResult(
                url=document.url,
                source=document.source,
                status="ok",
                action="dry_run",
                chunks=len(prepared.chunks),
                char_count=prepared.char_count,
                clean_chars=prepared.clean_chars,
                pages=prepared.pages,
                extractor=prepared.extractor,
                token_min=min(tokens),
                token_mean=round(sum(tokens) / len(tokens), 1),
                token_max=max(tokens),
                uncovered_chars=uncovered_characters(prepared.text, prepared.chunks),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                detail="dry run: nothing written",
            )
        else:
            outcome = store_document(conn, prepared)
            result = _result_from_outcome(
                document, prepared, outcome, int((time.perf_counter() - started) * 1000)
            )

        report.documents.append(result)
        if on_progress:
            on_progress(result)

    report.duration_s = time.perf_counter() - run_started
    report.finished_at = datetime.now(UTC).isoformat()
    report.counts_after = row_counts(conn)
    return report


@dataclass
class VerificationReport:
    """Result of re-reading stored chunks and re-checking FR-7 against the source."""

    versions_checked: int = 0
    chunks_checked: int = 0
    offset_mismatches: list[str] = field(default_factory=list)
    missing_versions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.offset_mismatches and not self.missing_versions

    def to_dict(self) -> dict[str, Any]:
        return {
            "versions_checked": self.versions_checked,
            "chunks_checked": self.chunks_checked,
            "offset_mismatches": self.offset_mismatches,
            "missing_versions": self.missing_versions,
            "ok": self.ok,
        }


def verify_stored_chunks(
    documents: Iterable[SourceDocument], conn: psycopg.Connection[Any]
) -> VerificationReport:
    """Re-derive each document's text and check every stored chunk against it.

    `chunk_document` already enforces FR-7 before anything is written, so this answers a
    different question: did the text survive the round trip through Postgres unchanged?
    An encoding or normalisation difference between what was embedded and what is stored
    would leave offsets that no longer bracket the stored text, and a citation would quote
    the wrong span while every pre-store check still passed.
    """
    report = VerificationReport()

    for document in documents:
        row = conn.execute(
            "SELECT version_id FROM document_versions WHERE sha256 = %s", (document.sha256,)
        ).fetchone()
        if row is None:
            report.missing_versions.append(document.url)
            continue

        extraction = extract(document.content, media_type=document.media_type)
        text = clean_preserving_offsets(extraction.text)

        rows = conn.execute(
            """
            SELECT ordinal, text, char_start, char_end
              FROM chunks WHERE version_id = %s ORDER BY ordinal
            """,
            (row[0],),
        ).fetchall()

        report.versions_checked += 1
        for ordinal, stored_text, char_start, char_end in rows:
            report.chunks_checked += 1
            if text[char_start:char_end] != stored_text:
                report.offset_mismatches.append(f"{document.url}#{ordinal}")

    return report
