"""Section-Aware Context Window Expansion (FEAT-075, ADR-0066).

When a retrieved chunk is a subsection or legal proviso, automatically pulls adjacent
sibling clauses from the same section to provide complete legal context and prevent
out-of-context misinterpretation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import psycopg
import structlog

from app.api.metrics import (
    SECTION_EXPANSION_DURATION_SECONDS,
    SECTION_EXPANSIONS_TOTAL,
)
from app.retrieval.port import ChunkRow

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SiblingChunk(ChunkRow):
    """A sibling chunk belonging to the same statutory section."""

    chunk_id: str = ""
    ordinal: int = 0
    clause_hierarchy: list[str] = field(default_factory=list)
    is_proviso: bool = False
    position: Literal["preceding", "following", "core"] = "core"


@dataclass(frozen=True)
class ExpandedPassage:
    """A core passage stitched together with adjacent sibling clauses within the same section."""

    core_chunk_id: UUID
    expanded_text: str
    sibling_chunks: list[ChunkRow]
    total_chars: int
    preceding_count: int = 0
    following_count: int = 0
    section_title: str | None = None
    is_proviso: bool = False


class SectionExpander:
    """Expands retrieved chunks with adjacent sibling clauses within the same section (FEAT-075)."""

    def __init__(
        self,
        conn: psycopg.Connection[Any] | None = None,
        *,
        in_memory_chunks: list[dict[str, Any]] | None = None,
    ) -> None:
        self._conn = conn
        self._in_memory_chunks: list[dict[str, Any]] | None = in_memory_chunks

    def expand(
        self,
        passage: Any,
        max_sibling_clauses: int = 2,
    ) -> ExpandedPassage:
        """Expand passage with preceding and following sibling clauses within same section.

        Inputs:
            passage: A Passage, Retrieved, ChunkRow, UUID, or chunk_id string.
            max_sibling_clauses: Maximum sibling clauses to fetch on each side (1 <= n <= 4).
        """
        # 1. Input validation
        if not (1 <= max_sibling_clauses <= 4):
            raise ValueError(
                f"max_sibling_clauses must be between 1 and 4, got {max_sibling_clauses}"
            )

        core_chunk_str = ""
        core_text = ""
        if isinstance(passage, str):
            core_chunk_str = passage.strip()
        elif isinstance(passage, UUID):
            core_chunk_str = str(passage)
        elif hasattr(passage, "chunk_id"):
            core_chunk_str = str(passage.chunk_id).strip()
            core_text = getattr(passage, "text", "") or ""
        else:
            raise ValueError(
                f"passage must be a Passage, Retrieved, ChunkRow, UUID, or chunk_id string; got {type(passage)}"
            )

        try:
            core_uuid = UUID(core_chunk_str)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(f"Invalid chunk_id UUID: {core_chunk_str!r}") from exc

        started = time.perf_counter()

        try:
            # 2. Check in-memory store or database
            if self._in_memory_chunks is not None:
                return self._expand_in_memory(core_uuid, core_text, max_sibling_clauses, started)

            if self._conn is None:
                SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded").inc()
                return ExpandedPassage(
                    core_chunk_id=core_uuid,
                    expanded_text=core_text,
                    sibling_chunks=[],
                    total_chars=len(core_text),
                )

            return self._expand_from_db(core_uuid, core_text, max_sibling_clauses, started)
        except Exception as exc:
            logger.warning("section_expansion_failed", chunk_id=str(core_uuid), error=str(exc))
            SECTION_EXPANSIONS_TOTAL.labels(status="fallback").inc()
            return ExpandedPassage(
                core_chunk_id=core_uuid,
                expanded_text=core_text,
                sibling_chunks=[],
                total_chars=len(core_text),
            )

    def _expand_in_memory(
        self,
        core_uuid: UUID,
        fallback_text: str,
        max_siblings: int,
        started: float,
    ) -> ExpandedPassage:
        if self._in_memory_chunks is None:
            raise RuntimeError("in_memory_chunks is not initialized")
        chunk_str = str(core_uuid)
        core_row = next(
            (c for c in self._in_memory_chunks if str(c.get("chunk_id")) == chunk_str),
            None,
        )
        if core_row is None:
            SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded").inc()
            return ExpandedPassage(
                core_chunk_id=core_uuid,
                expanded_text=fallback_text,
                sibling_chunks=[],
                total_chars=len(fallback_text),
            )

        doc_id = str(core_row.get("document_id", ""))
        core_text = core_row.get("text", "") or fallback_text
        char_start = int(core_row.get("char_start", 0))
        char_end = int(core_row.get("char_end", 0))
        hierarchy = list(core_row.get("clause_hierarchy", []))
        is_proviso = bool(core_row.get("is_proviso", False))
        sec_root = hierarchy[0] if hierarchy else None

        # Filter candidate siblings in same document
        doc_chunks = [c for c in self._in_memory_chunks if str(c.get("document_id")) == doc_id]

        # Preceding siblings
        preceding: list[dict[str, Any]] = []
        for c in sorted(doc_chunks, key=lambda x: int(x.get("char_start", 0)), reverse=True):
            c_id = str(c.get("chunk_id", ""))
            c_end = int(c.get("char_end", 0))
            c_hier = list(c.get("clause_hierarchy", []))
            if c_id != chunk_str and c_end <= char_start:
                if sec_root is not None and c_hier and c_hier[0] != sec_root:
                    break  # crossed section boundary
                preceding.append(c)
                if len(preceding) >= max_siblings:
                    break
        preceding.reverse()

        # Following siblings
        following: list[dict[str, Any]] = []
        for c in sorted(doc_chunks, key=lambda x: int(x.get("char_start", 0))):
            c_id = str(c.get("chunk_id", ""))
            c_start = int(c.get("char_start", 0))
            c_hier = list(c.get("clause_hierarchy", []))
            if c_id != chunk_str and c_start >= char_end:
                if sec_root is not None and c_hier and c_hier[0] != sec_root:
                    break  # crossed section boundary
                following.append(c)
                if len(following) >= max_siblings:
                    break

        if not preceding and not following:
            SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded").inc()
            return ExpandedPassage(
                core_chunk_id=core_uuid,
                expanded_text=core_text,
                sibling_chunks=[],
                total_chars=len(core_text),
                is_proviso=is_proviso,
                section_title=sec_root,
            )

        # Assemble sibling ChunkRow objects
        sibling_objs: list[ChunkRow] = []
        for p in preceding:
            sibling_objs.append(
                SiblingChunk(
                    chunk_id=str(p.get("chunk_id", "")),
                    document_id=doc_id,
                    source=str(p.get("source", "")),
                    text=str(p.get("text", "")),
                    canonical_url=p.get("canonical_url"),
                    char_start=int(p.get("char_start", 0)),
                    char_end=int(p.get("char_end", 0)),
                    title=p.get("title"),
                    published_date=p.get("published_date"),
                    document_class=p.get("document_class"),
                    authority_tier=p.get("authority_tier"),
                    ordinal=int(p.get("ordinal", 0)),
                    clause_hierarchy=list(p.get("clause_hierarchy", [])),
                    is_proviso=bool(p.get("is_proviso", False)),
                    position="preceding",
                )
            )
        for f in following:
            sibling_objs.append(
                SiblingChunk(
                    chunk_id=str(f.get("chunk_id", "")),
                    document_id=doc_id,
                    source=str(f.get("source", "")),
                    text=str(f.get("text", "")),
                    canonical_url=f.get("canonical_url"),
                    char_start=int(f.get("char_start", 0)),
                    char_end=int(f.get("char_end", 0)),
                    title=f.get("title"),
                    published_date=f.get("published_date"),
                    document_class=f.get("document_class"),
                    authority_tier=f.get("authority_tier"),
                    ordinal=int(f.get("ordinal", 0)),
                    clause_hierarchy=list(f.get("clause_hierarchy", [])),
                    is_proviso=bool(f.get("is_proviso", False)),
                    position="following",
                )
            )

        text_parts = (
            [str(p.get("text", "")) for p in preceding]
            + [core_text]
            + [str(f.get("text", "")) for f in following]
        )
        expanded_str = "\n\n".join(t.strip() for t in text_parts if t.strip())

        elapsed = time.perf_counter() - started
        SECTION_EXPANSION_DURATION_SECONDS.observe(elapsed)
        SECTION_EXPANSIONS_TOTAL.labels(status="expanded").inc()

        return ExpandedPassage(
            core_chunk_id=core_uuid,
            expanded_text=expanded_str,
            sibling_chunks=sibling_objs,
            total_chars=len(expanded_str),
            preceding_count=len(preceding),
            following_count=len(following),
            section_title=sec_root,
            is_proviso=is_proviso,
        )

    def _expand_from_db(
        self,
        core_uuid: UUID,
        fallback_text: str,
        max_siblings: int,
        started: float,
    ) -> ExpandedPassage:
        if self._conn is None:
            raise RuntimeError("Database connection is not initialized")
        chunk_str = str(core_uuid)

        # 1. Fetch core chunk
        row = self._conn.execute(
            """
            SELECT c.document_id::text, c.ordinal, c.text, c.char_start, c.char_end,
                   c.clause_hierarchy, c.is_proviso, d.source, d.canonical_url, d.title
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            WHERE c.chunk_id = %s AND NOT d.is_synthetic
            """,
            (chunk_str,),
        ).fetchone()

        if row is None:
            SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded").inc()
            return ExpandedPassage(
                core_chunk_id=core_uuid,
                expanded_text=fallback_text,
                sibling_chunks=[],
                total_chars=len(fallback_text),
            )

        (
            doc_id,
            ordinal,
            db_text,
            char_start,
            char_end,
            hierarchy_raw,
            is_proviso,
            source,
            canonical_url,
            doc_title,
        ) = row

        core_text = db_text if db_text else fallback_text
        hierarchy = list(hierarchy_raw) if hierarchy_raw else []
        sec_root = hierarchy[0] if hierarchy else None

        # 2. Fetch preceding sibling chunks
        preceding_rows = self._conn.execute(
            """
            SELECT c.chunk_id::text, c.document_id::text, c.text, c.char_start, c.char_end,
                   c.ordinal, c.clause_hierarchy, c.is_proviso
            FROM chunks c
            WHERE c.document_id = %s
              AND c.char_end <= %s
              AND c.chunk_id != %s
            ORDER BY c.char_start DESC
            LIMIT %s
            """,
            (doc_id, char_start, chunk_str, max_siblings * 2),
        ).fetchall()

        preceding_valid: list[Any] = []
        for prow in preceding_rows:
            p_cid, p_doc, p_text, p_start, p_end, p_ord, p_hier_raw, p_proviso = prow
            p_hier = list(p_hier_raw) if p_hier_raw else []
            if sec_root is not None and p_hier and p_hier[0] != sec_root:
                break  # crossed section boundary
            preceding_valid.append(prow)
            if len(preceding_valid) >= max_siblings:
                break
        preceding_valid.reverse()

        # 3. Fetch following sibling chunks
        following_rows = self._conn.execute(
            """
            SELECT c.chunk_id::text, c.document_id::text, c.text, c.char_start, c.char_end,
                   c.ordinal, c.clause_hierarchy, c.is_proviso
            FROM chunks c
            WHERE c.document_id = %s
              AND c.char_start >= %s
              AND c.chunk_id != %s
            ORDER BY c.char_start ASC
            LIMIT %s
            """,
            (doc_id, char_end, chunk_str, max_siblings * 2),
        ).fetchall()

        following_valid: list[Any] = []
        for frow in following_rows:
            f_cid, f_doc, f_text, f_start, f_end, f_ord, f_hier_raw, f_proviso = frow
            f_hier = list(f_hier_raw) if f_hier_raw else []
            if sec_root is not None and f_hier and f_hier[0] != sec_root:
                break  # crossed section boundary
            following_valid.append(frow)
            if len(following_valid) >= max_siblings:
                break

        if not preceding_valid and not following_valid:
            SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded").inc()
            return ExpandedPassage(
                core_chunk_id=core_uuid,
                expanded_text=core_text,
                sibling_chunks=[],
                total_chars=len(core_text),
                is_proviso=bool(is_proviso),
                section_title=sec_root,
            )

        # 4. Construct SiblingChunk list and stitched text
        sibling_objs: list[ChunkRow] = []
        for p_cid, p_doc, p_text, p_start, p_end, p_ord, p_hier_raw, p_proviso in preceding_valid:
            sibling_objs.append(
                SiblingChunk(
                    chunk_id=p_cid,
                    document_id=p_doc,
                    source=source or "",
                    text=p_text or "",
                    canonical_url=canonical_url,
                    char_start=p_start,
                    char_end=p_end,
                    title=doc_title,
                    ordinal=p_ord,
                    clause_hierarchy=list(p_hier_raw) if p_hier_raw else [],
                    is_proviso=bool(p_proviso),
                    position="preceding",
                )
            )

        for f_cid, f_doc, f_text, f_start, f_end, f_ord, f_hier_raw, f_proviso in following_valid:
            sibling_objs.append(
                SiblingChunk(
                    chunk_id=f_cid,
                    document_id=f_doc,
                    source=source or "",
                    text=f_text or "",
                    canonical_url=canonical_url,
                    char_start=f_start,
                    char_end=f_end,
                    title=doc_title,
                    ordinal=f_ord,
                    clause_hierarchy=list(f_hier_raw) if f_hier_raw else [],
                    is_proviso=bool(f_proviso),
                    position="following",
                )
            )

        text_parts = [r[2] for r in preceding_valid] + [core_text] + [r[2] for r in following_valid]
        expanded_str = "\n\n".join(t.strip() for t in text_parts if t and t.strip())

        elapsed = time.perf_counter() - started
        SECTION_EXPANSION_DURATION_SECONDS.observe(elapsed)
        SECTION_EXPANSIONS_TOTAL.labels(status="expanded").inc()

        return ExpandedPassage(
            core_chunk_id=core_uuid,
            expanded_text=expanded_str,
            sibling_chunks=sibling_objs,
            total_chars=len(expanded_str),
            preceding_count=len(preceding_valid),
            following_count=len(following_valid),
            section_title=sec_root,
            is_proviso=bool(is_proviso),
        )


def expand_section_context(
    passage: Any,
    conn: psycopg.Connection[Any] | None = None,
    max_sibling_clauses: int = 2,
    *,
    in_memory_chunks: list[dict[str, Any]] | None = None,
) -> ExpandedPassage:
    """Convenience functional wrapper for SectionExpander.expand()."""
    expander = SectionExpander(conn=conn, in_memory_chunks=in_memory_chunks)
    return expander.expand(passage, max_sibling_clauses=max_sibling_clauses)
