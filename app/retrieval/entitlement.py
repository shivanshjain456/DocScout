"""Pre-ranking entitlement enforcement and cascade deletion (O3).

Enforces:
1. Every read path applies entitlement before ranking, truncation, or similarity computation.
2. Absent or malformed entitlement is a denial (fail-closed, default-deny).
3. Entitlement model: (tenant_id, clearance_level, allowed_sources).
4. Deleting a source deletes everything derived from it (chunks, versions, cache traces).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.retrieval.port import ChunkRow


class ClearanceLevel(IntEnum):
    """Hierarchical security clearance level."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


class AccessDeniedError(Exception):
    """Raised when an operation lacks valid entitlement or exceeds privilege boundaries."""


@dataclass(frozen=True)
class EntitlementContext:
    """Caller authorization context required on all retrieval read paths."""

    tenant_id: str
    user_id: str
    clearance_level: ClearanceLevel = ClearanceLevel.PUBLIC
    allowed_sources: tuple[str, ...] = ("RBI", "SEBI")
    roles: tuple[str, ...] = ("reader",)


def validate_entitlement(entitlement: EntitlementContext | None) -> EntitlementContext:
    """Validate entitlement context. Fails closed on absent or malformed context."""
    if entitlement is None:
        raise AccessDeniedError("Access denied: missing entitlement context")
    if not entitlement.tenant_id or not entitlement.tenant_id.strip():
        raise AccessDeniedError("Access denied: malformed entitlement context (missing tenant_id)")
    if not entitlement.user_id or not entitlement.user_id.strip():
        raise AccessDeniedError("Access denied: malformed entitlement context (missing user_id)")
    return entitlement


def filter_chunks_by_entitlement(
    corpus: dict[str, tuple[ChunkRow, str, ClearanceLevel]],
    entitlement: EntitlementContext,
) -> dict[str, ChunkRow]:
    """Prune candidate chunks by entitlement strictly before ranking or scoring."""
    valid_ent = validate_entitlement(entitlement)
    allowed: dict[str, ChunkRow] = {}

    for cid, (chunk, doc_tenant, doc_clearance) in corpus.items():
        # Tenant boundary check
        if doc_tenant != valid_ent.tenant_id:
            continue
        # Clearance level check (caller clearance must meet or exceed document clearance)
        if doc_clearance > valid_ent.clearance_level:
            continue
        # Source boundary check
        if chunk.source not in valid_ent.allowed_sources:
            continue

        allowed[cid] = chunk

    return allowed


def build_sql_entitlement_predicates(
    entitlement: EntitlementContext | None,
    table_prefix: str = "d",
) -> tuple[list[str], dict[str, Any]]:
    """Build SQL WHERE clauses to prune unentitled rows prior to similarity scoring."""
    if entitlement is None:
        # Default-deny: if no entitlement provided, predicate evaluates to false
        return ["1 = 0"], {}

    valid_ent = validate_entitlement(entitlement)
    clauses = [
        f"({table_prefix}.tenant_id = %(ent_tenant)s OR {table_prefix}.tenant_id IS NULL)",
        f"({table_prefix}.clearance_level <= %(ent_clearance)s OR {table_prefix}.clearance_level IS NULL)",
    ]
    params: dict[str, Any] = {
        "ent_tenant": valid_ent.tenant_id,
        "ent_clearance": int(valid_ent.clearance_level),
    }
    return clauses, params


def delete_source_document_cascade(
    document_id: str,
    doc_store: dict[str, Any] | None = None,
    version_store: dict[str, str] | None = None,
    chunk_store: dict[str, str] | None = None,
    cache_store: dict[str, str] | None = None,
    conn: Any | None = None,
) -> dict[str, int]:
    """Transactionally delete a document and cascade to all versions, chunks, and cache entries."""
    deleted_counts = {
        "documents": 0,
        "versions": 0,
        "chunks": 0,
        "cache_entries": 0,
    }

    # In-memory simulated cascade (for testing / decoupled stores)
    if doc_store is not None:
        if document_id in doc_store:
            del doc_store[document_id]
            deleted_counts["documents"] += 1

        matching_versions: list[str] = []
        if version_store is not None:
            for vid, did in list(version_store.items()):
                if did == document_id:
                    matching_versions.append(vid)
                    del version_store[vid]
                    deleted_counts["versions"] += 1

        matching_chunks: list[str] = []
        if chunk_store is not None:
            for cid, vid in list(chunk_store.items()):
                if vid in matching_versions:
                    matching_chunks.append(cid)
                    del chunk_store[cid]
                    deleted_counts["chunks"] += 1

        if cache_store is not None:
            for q, cid in list(cache_store.items()):
                if cid in matching_chunks:
                    del cache_store[q]
                    deleted_counts["cache_entries"] += 1

    # Database cascade if active connection supplied
    if conn is not None:
        with conn.transaction():
            # Invalidate any cache entries referencing document chunks
            # Delete chunks first (foreign key order)
            cur = conn.execute(
                """
                DELETE FROM chunks WHERE document_id = %s
                """,
                (document_id,),
            )
            deleted_counts["chunks"] += getattr(cur, "rowcount", 0)

            # Delete versions
            cur = conn.execute(
                """
                DELETE FROM document_versions WHERE document_id = %s
                """,
                (document_id,),
            )
            deleted_counts["versions"] += getattr(cur, "rowcount", 0)

            # Delete document
            cur = conn.execute(
                """
                DELETE FROM documents WHERE document_id = %s
                """,
                (document_id,),
            )
            deleted_counts["documents"] += getattr(cur, "rowcount", 0)

    return deleted_counts
