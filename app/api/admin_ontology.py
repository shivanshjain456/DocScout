"""Admin API for Regulatory Ontology Candidate Review & Staging (FEAT-010).

Provides human review, approval, and rejection workflows for staged ontology additions.
Guarantees:
- Zero unsupervised direct mutation of production term-taxonomy.json.
- Audit trail on all reviewer approvals and rejections.
- Protected by API key authentication.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.api.metrics import ONTOLOGY_CANDIDATES_REVIEWED
from app.api.security import require_api_key
from app.ingest.ontology_extractor import (
    DocumentPayload,
    OntologyExtractor,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/admin/ontology", tags=["admin-ontology"])


class StagedCandidateSummary(BaseModel):
    """Summary of a staged ontology candidate term."""

    candidate_id: str
    term: str
    slug: str
    definition: str
    domain: str
    domain_name: str
    source_document_id: str | None
    source_title: str | None
    status: Literal["pending", "approved", "rejected"]
    confidence: float
    frequency: int
    proposed_edges: list[dict[str, Any]]
    aliases: list[str]
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    reviewer_notes: str | None = None


class ReviewDecisionRequest(BaseModel):
    """Payload for approving or rejecting a staged candidate."""

    reviewer: str = Field(min_length=2, max_length=100)
    notes: str | None = Field(default=None, max_length=500)


class ExtractTriggerRequest(BaseModel):
    """Payload to trigger extraction analysis on document text."""

    doc_id: str
    text: str = Field(min_length=10)
    title: str | None = None


class CandidateListResponse(BaseModel):
    """List response for staged ontology candidates."""

    candidates: list[StagedCandidateSummary]
    total_count: int
    status_filter: str | None


@router.get("/candidates", response_model=CandidateListResponse)
def list_staged_candidates(
    request: Request,
    status_filter: Literal["pending", "approved", "rejected", "all"] = "pending",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    fingerprint: str = Depends(require_api_key),
) -> CandidateListResponse:
    """List staged regulatory terms awaiting or having completed review."""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        return CandidateListResponse(candidates=[], total_count=0, status_filter=status_filter)

    candidates: list[StagedCandidateSummary] = []
    total = 0

    try:
        with pool.connection() as conn:
            # Query count
            where_sql = "WHERE 1=1"
            params: list[Any] = []
            if status_filter != "all":
                where_sql += " AND status = %s"
                params.append(status_filter)

            count_row = conn.execute(
                f"SELECT count(*) FROM ontology_staging {where_sql}",  # noqa: S608
                tuple(params),
            ).fetchone()
            total = int(count_row[0]) if count_row else 0

            # Query items
            query_sql = f"""
                SELECT
                    candidate_id::text, term, slug, definition, domain, domain_name,
                    source_document_id::text, source_title, status, confidence, frequency,
                    proposed_edges, aliases, created_at, reviewed_at, reviewed_by, reviewer_notes
                FROM ontology_staging
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """  # noqa: S608
            fetch_params = params + [limit, offset]
            rows = conn.execute(query_sql, tuple(fetch_params)).fetchall()

            for r in rows:
                edges_val = r[11]
                if isinstance(edges_val, str):
                    edges_val = json.loads(edges_val)
                elif not isinstance(edges_val, list):
                    edges_val = []

                aliases_val = r[12]
                if isinstance(aliases_val, str):
                    aliases_val = json.loads(aliases_val)
                elif not isinstance(aliases_val, list):
                    aliases_val = []

                candidates.append(
                    StagedCandidateSummary(
                        candidate_id=r[0],
                        term=r[1],
                        slug=r[2],
                        definition=r[3],
                        domain=r[4],
                        domain_name=r[5],
                        source_document_id=r[6],
                        source_title=r[7],
                        status=r[8],
                        confidence=float(r[9]),
                        frequency=int(r[10]),
                        proposed_edges=edges_val,
                        aliases=aliases_val,
                        created_at=r[13],
                        reviewed_at=r[14],
                        reviewed_by=r[15],
                        reviewer_notes=r[16],
                    )
                )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query ontology candidates: {exc}",
        ) from exc

    return CandidateListResponse(
        candidates=candidates,
        total_count=total,
        status_filter=status_filter,
    )


@router.post("/candidates/{candidate_id}/approve", response_model=StagedCandidateSummary)
def approve_candidate(
    candidate_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> StagedCandidateSummary:
    """Approve a staged ontology term, transitioning it to approved status."""
    return _update_candidate_status(
        request, candidate_id, "approved", payload.reviewer, payload.notes
    )


@router.post("/candidates/{candidate_id}/reject", response_model=StagedCandidateSummary)
def reject_candidate(
    candidate_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> StagedCandidateSummary:
    """Reject a staged ontology term."""
    return _update_candidate_status(
        request, candidate_id, "rejected", payload.reviewer, payload.notes
    )


@router.post("/extract", response_model=list[dict[str, Any]])
def trigger_extraction(
    payload: ExtractTriggerRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> list[dict[str, Any]]:
    """Trigger automated extraction on document text and optionally stage candidates."""
    extractor = OntologyExtractor()
    doc_payload = DocumentPayload(
        doc_id=payload.doc_id,
        text=payload.text,
        title=payload.title,
    )
    candidates = extractor.extract_candidates(doc_payload)

    pool = getattr(request.app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                extractor.stage_candidates(conn, candidates)
        except Exception as exc:
            logger.warning("extract_trigger_stage_failed", error=str(exc))

    return [c.to_taxonomy_record() for c in candidates]


def _update_candidate_status(
    request: Request,
    candidate_id: str,
    new_status: Literal["approved", "rejected"],
    reviewer: str,
    notes: str | None,
) -> StagedCandidateSummary:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool not configured",
        )

    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE ontology_staging
                SET status = %s,
                    reviewed_by = %s,
                    reviewer_notes = %s,
                    reviewed_at = clock_timestamp()
                WHERE candidate_id = %s::uuid
                RETURNING
                    candidate_id::text, term, slug, definition, domain, domain_name,
                    source_document_id::text, source_title, status, confidence, frequency,
                    proposed_edges, aliases, created_at, reviewed_at, reviewed_by, reviewer_notes
                """,
                (new_status, reviewer, notes, candidate_id),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Candidate {candidate_id} not found",
                )

            conn.commit()
            ONTOLOGY_CANDIDATES_REVIEWED.labels(action=new_status).inc()

            edges_val = row[11]
            if isinstance(edges_val, str):
                edges_val = json.loads(edges_val)
            elif not isinstance(edges_val, list):
                edges_val = []

            aliases_val = row[12]
            if isinstance(aliases_val, str):
                aliases_val = json.loads(aliases_val)
            elif not isinstance(aliases_val, list):
                aliases_val = []

            return StagedCandidateSummary(
                candidate_id=row[0],
                term=row[1],
                slug=row[2],
                definition=row[3],
                domain=row[4],
                domain_name=row[5],
                source_document_id=row[6],
                source_title=row[7],
                status=row[8],
                confidence=float(row[9]),
                frequency=int(row[10]),
                proposed_edges=edges_val,
                aliases=aliases_val,
                created_at=row[13],
                reviewed_at=row[14],
                reviewed_by=row[15],
                reviewer_notes=row[16],
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update candidate status: {exc}",
        ) from exc
