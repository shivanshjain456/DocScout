"""Tests for Outcome Area O3: Access Decisions Precede Ranking.

Enforces:
1. Every read path applies entitlement before ranking, before truncation, and before similarity computation.
2. Absent or malformed entitlement is a denial, never a default-allow.
3. A caller cannot infer existence of content they may not read (disjoint identifiers, no score leakage).
4. Deleting a source deletes everything derived from it.
"""

from __future__ import annotations

import pytest

from app.retrieval.entitlement import (
    AccessDeniedError,
    ClearanceLevel,
    EntitlementContext,
    delete_source_document_cascade,
    filter_chunks_by_entitlement,
    validate_entitlement,
)
from app.retrieval.port import ChunkRow


@pytest.fixture
def sample_corpus() -> dict[str, tuple[ChunkRow, str, ClearanceLevel]]:
    """Sample corpus spanning two tenants and multiple clearance levels.

    Returns dict mapping chunk_id -> (ChunkRow, tenant_id, clearance_level).
    """
    return {
        # Tenant Alpha - Public
        "chunk-alpha-pub": (
            ChunkRow(
                document_id="doc-alpha-pub",
                source="RBI",
                text="Public liquidity framework for bank Alpha.",
                canonical_url="https://alpha.bank/pub.pdf",
                char_start=0,
                char_end=42,
            ),
            "tenant-alpha",
            ClearanceLevel.PUBLIC,
        ),
        # Tenant Alpha - Restricted
        "chunk-alpha-priv": (
            ChunkRow(
                document_id="doc-alpha-priv",
                source="RBI",
                text="Restricted supervisory audit report for bank Alpha.",
                canonical_url="https://alpha.bank/priv.pdf",
                char_start=0,
                char_end=52,
            ),
            "tenant-alpha",
            ClearanceLevel.RESTRICTED,
        ),
        # Tenant Beta - Public
        "chunk-beta-pub": (
            ChunkRow(
                document_id="doc-beta-pub",
                source="SEBI",
                text="Public securities filing for fund Beta.",
                canonical_url="https://beta.fund/pub.pdf",
                char_start=0,
                char_end=39,
            ),
            "tenant-beta",
            ClearanceLevel.PUBLIC,
        ),
        # Tenant Beta - Confidential
        "chunk-beta-conf": (
            ChunkRow(
                document_id="doc-beta-conf",
                source="SEBI",
                text="Confidential insider compliance matrix for fund Beta.",
                canonical_url="https://beta.fund/conf.pdf",
                char_start=0,
                char_end=53,
            ),
            "tenant-beta",
            ClearanceLevel.CONFIDENTIAL,
        ),
    }


def test_two_identity_fixture_asserts_disjointness(
    sample_corpus: dict[str, tuple[ChunkRow, str, ClearanceLevel]],
) -> None:
    """Two identities from different tenants receive strictly disjoint sets of identifiers."""
    user_alpha = EntitlementContext(
        tenant_id="tenant-alpha",
        user_id="user-a1",
        clearance_level=ClearanceLevel.RESTRICTED,
        allowed_sources=("RBI",),
    )
    user_beta = EntitlementContext(
        tenant_id="tenant-beta",
        user_id="user-b1",
        clearance_level=ClearanceLevel.CONFIDENTIAL,
        allowed_sources=("SEBI",),
    )

    allowed_alpha = filter_chunks_by_entitlement(sample_corpus, user_alpha)
    allowed_beta = filter_chunks_by_entitlement(sample_corpus, user_beta)

    # Must be completely disjoint
    assert set(allowed_alpha.keys()).isdisjoint(set(allowed_beta.keys()))
    assert "chunk-alpha-pub" in allowed_alpha
    assert "chunk-alpha-priv" in allowed_alpha
    assert "chunk-beta-pub" not in allowed_alpha
    assert "chunk-beta-conf" not in allowed_alpha

    assert "chunk-beta-pub" in allowed_beta
    assert "chunk-beta-conf" in allowed_beta
    assert "chunk-alpha-pub" not in allowed_beta


def test_missing_or_malformed_entitlement_fails_closed() -> None:
    """Missing, None, or empty entitlement context triggers an immediate denial."""
    with pytest.raises(AccessDeniedError):
        validate_entitlement(None)

    with pytest.raises(AccessDeniedError):
        validate_entitlement(EntitlementContext(tenant_id="", user_id="user-1"))

    with pytest.raises(AccessDeniedError):
        validate_entitlement(EntitlementContext(tenant_id="tenant-1", user_id=""))


def test_scores_not_exposed_to_unentitled_callers(
    sample_corpus: dict[str, tuple[ChunkRow, str, ClearanceLevel]],
) -> None:
    """Unentitled callers do not receive candidates, similarity scores, or ranking positions."""
    # Reader with PUBLIC clearance in tenant-alpha querying against corpus
    public_alpha_reader = EntitlementContext(
        tenant_id="tenant-alpha",
        user_id="user-pub",
        clearance_level=ClearanceLevel.PUBLIC,
        allowed_sources=("RBI",),
    )

    allowed = filter_chunks_by_entitlement(sample_corpus, public_alpha_reader)

    # Restricted document must not exist in candidate pool prior to scoring
    assert "chunk-alpha-priv" not in allowed
    assert "chunk-beta-pub" not in allowed
    assert "chunk-beta-conf" not in allowed
    assert list(allowed.keys()) == ["chunk-alpha-pub"]


def test_source_deletion_cascades_everything() -> None:
    """Deleting a source document deletes the document, its versions, chunks, and cache traces."""
    # Simulated store
    doc_store: dict[str, str] = {"doc-1": "Document Title"}
    version_store: dict[str, str] = {"ver-1": "doc-1", "ver-2": "doc-1"}
    chunk_store: dict[str, str] = {"c-1": "ver-1", "c-2": "ver-2"}
    cache_store: dict[str, str] = {"query-1": "c-1", "query-2": "c-2"}

    deleted_summary = delete_source_document_cascade(
        document_id="doc-1",
        doc_store=doc_store,
        version_store=version_store,
        chunk_store=chunk_store,
        cache_store=cache_store,
    )

    assert deleted_summary["documents"] == 1
    assert deleted_summary["versions"] == 2
    assert deleted_summary["chunks"] == 2
    assert deleted_summary["cache_entries"] == 2

    assert "doc-1" not in doc_store
    assert len(version_store) == 0
    assert len(chunk_store) == 0
    assert len(cache_store) == 0
