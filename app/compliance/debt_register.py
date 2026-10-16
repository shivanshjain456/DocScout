"""Enterprise Compliance Debt Register (FEAT-038).

Tracks active compliance exceptions, deprecated procedures, and remediation target dates
across the enterprise with strict multi-tenant isolation, audit logging, and institutional
debt score calculation.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.metrics import OPEN_COMPLIANCE_DEBT_ITEMS
from app.api.security import require_api_key
from app.compliance.antipattern_scanner import get_default_antipattern_scanner
from app.compliance.deprecation_engine import get_default_deprecation_engine

logger = structlog.get_logger("docscout.compliance.debt_register")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SEVERITY_WEIGHTS: dict[str, float] = {
    "CRITICAL": 10.0,
    "HIGH": 5.0,
    "MEDIUM": 2.0,
    "LOW": 1.0,
}

STATUS_MULTIPLIERS: dict[str, float] = {
    "OPEN": 1.0,
    "IN_REMEDIATION": 0.5,
    "RESOLVED": 0.0,
}


class CreateDebtItemRequest(BaseModel):
    """Payload to register a new compliance debt item."""

    practice_name: str = Field(min_length=2, max_length=250)
    deprecation_id: str | None = None
    antipattern_id: str | None = None
    owner_email: str
    target_date: date
    justification: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "HIGH"
    tenant_id: str = "default"


class UpdateDebtStatusRequest(BaseModel):
    """Payload to transition status of a compliance debt item."""

    status: Literal["OPEN", "IN_REMEDIATION", "RESOLVED"]
    notes: str | None = None
    actor_email: str = "compliance@docscout.ai"


class ComplianceDebtItem(BaseModel):
    """Canonical model for an enterprise compliance debt item."""

    id: UUID
    tenant_id: str
    practice_name: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    status: Literal["OPEN", "IN_REMEDIATION", "RESOLVED"]
    owner_email: str
    target_date: date
    justification: str
    deprecation_id: str | None = None
    antipattern_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ComplianceDebtAuditEntry(BaseModel):
    """Audit entry recording compliance debt state transitions."""

    id: UUID
    debt_item_id: UUID
    tenant_id: str
    previous_status: str | None
    new_status: str
    actor_email: str
    transition_notes: str | None
    timestamp: datetime


class InstitutionalDebtScoreResponse(BaseModel):
    """Aggregated institutional compliance debt summary and score."""

    tenant_id: str
    total_items: int
    open_items: int
    in_remediation_items: int
    resolved_items: int
    debt_score: float
    severity_breakdown: dict[str, int]


class DebtItemListResponse(BaseModel):
    """List response for compliance debt items."""

    items: list[ComplianceDebtItem]
    total: int


class DebtRegisterConfig(BaseModel):
    """Configuration for enterprise compliance debt registry."""

    allow_overdue_extensions: bool = False


class ComplianceDebtRegister:
    """Enterprise Compliance Debt Register managing multi-tenant lifecycle & scoring."""

    def __init__(self, config: DebtRegisterConfig | None = None) -> None:
        self.config = config or DebtRegisterConfig()
        self._items: dict[UUID, ComplianceDebtItem] = {}
        self._audit_logs: dict[UUID, list[ComplianceDebtAuditEntry]] = {}

    def _validate_create_request(self, req: CreateDebtItemRequest) -> None:
        """Validate email, date, length, and catalog associations."""
        if not EMAIL_REGEX.match(req.owner_email.strip()):
            raise ValueError(f"Invalid owner email format: '{req.owner_email}'")

        if req.target_date <= date.today():
            raise ValueError(
                f"Target date must be in the future (got {req.target_date}, today is {date.today()})"
            )

        if len(req.justification.strip()) < 20:
            raise ValueError(
                f"Justification must be at least 20 characters (got {len(req.justification.strip())})"
            )

        if req.antipattern_id:
            scanner = get_default_antipattern_scanner()
            if not scanner.get_rule(req.antipattern_id):
                raise ValueError(
                    f"Antipattern ID '{req.antipattern_id}' not recognized in compliance catalog"
                )

        if req.deprecation_id:
            engine = get_default_deprecation_engine()
            # If not in engine or custom prefix check
            if not engine.get_deprecation(req.deprecation_id) and not req.deprecation_id.startswith(
                "DEP-"
            ):
                raise ValueError(
                    f"Deprecation ID '{req.deprecation_id}' not recognized in compliance catalog"
                )

    def create_item(self, req: CreateDebtItemRequest) -> ComplianceDebtItem:
        """Create a new compliance debt item with validation and initial audit entry."""
        self._validate_create_request(req)

        item_id = uuid4()
        now = datetime.now(UTC)
        item = ComplianceDebtItem(
            id=item_id,
            tenant_id=req.tenant_id.strip(),
            practice_name=req.practice_name.strip(),
            severity=req.severity,
            status="OPEN",
            owner_email=req.owner_email.strip(),
            target_date=req.target_date,
            justification=req.justification.strip(),
            deprecation_id=req.deprecation_id,
            antipattern_id=req.antipattern_id,
            created_at=now,
            updated_at=now,
        )

        self._items[item_id] = item
        audit_entry = ComplianceDebtAuditEntry(
            id=uuid4(),
            debt_item_id=item_id,
            tenant_id=item.tenant_id,
            previous_status=None,
            new_status="OPEN",
            actor_email=req.owner_email.strip(),
            transition_notes="Initial creation of compliance debt exception item.",
            timestamp=now,
        )
        self._audit_logs[item_id] = [audit_entry]

        self._refresh_metrics(item.tenant_id)
        return item

    def get_item(self, item_id: UUID, tenant_id: str | None = None) -> ComplianceDebtItem | None:
        """Retrieve a specific compliance debt item, enforcing tenant boundary if provided."""
        item = self._items.get(item_id)
        if not item:
            return None
        if tenant_id and item.tenant_id != tenant_id:
            return None
        return item

    def update_status(
        self,
        item_id: UUID,
        req: UpdateDebtStatusRequest,
        tenant_id: str | None = None,
    ) -> ComplianceDebtItem:
        """Transition status of an existing compliance debt item and log audit record."""
        item = self.get_item(item_id, tenant_id=tenant_id)
        if not item:
            raise KeyError(f"Compliance debt item '{item_id}' not found")

        prev_status = item.status
        now = datetime.now(UTC)

        updated_item = item.model_copy(
            update={
                "status": req.status,
                "updated_at": now,
            }
        )
        self._items[item_id] = updated_item

        audit_entry = ComplianceDebtAuditEntry(
            id=uuid4(),
            debt_item_id=item_id,
            tenant_id=item.tenant_id,
            previous_status=prev_status,
            new_status=req.status,
            actor_email=req.actor_email.strip(),
            transition_notes=req.notes.strip() if req.notes else None,
            timestamp=now,
        )
        self._audit_logs.setdefault(item_id, []).append(audit_entry)

        self._refresh_metrics(item.tenant_id)
        return updated_item

    def list_items(
        self,
        tenant_id: str,
        status_filter: str | None = None,
        severity_filter: str | None = None,
    ) -> list[ComplianceDebtItem]:
        """List items partitioned strictly by tenant_id."""
        results: list[ComplianceDebtItem] = []
        for it in self._items.values():
            if it.tenant_id != tenant_id:
                continue
            if status_filter and it.status != status_filter:
                continue
            if severity_filter and it.severity != severity_filter:
                continue
            results.append(it)
        results.sort(key=lambda x: (x.target_date, x.created_at))
        return results

    def get_audit_trail(
        self, item_id: UUID, tenant_id: str | None = None
    ) -> list[ComplianceDebtAuditEntry]:
        """Retrieve audit history for a debt item."""
        item = self.get_item(item_id, tenant_id=tenant_id)
        if not item:
            return []
        return list(self._audit_logs.get(item_id, []))

    def calculate_debt_score(self, tenant_id: str) -> InstitutionalDebtScoreResponse:
        """Compute aggregated institutional debt score and severity breakdown."""
        tenant_items = self.list_items(tenant_id=tenant_id)
        total = len(tenant_items)
        open_count = 0
        in_remed_count = 0
        resolved_count = 0
        score = 0.0
        breakdown: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

        today = date.today()
        for it in tenant_items:
            breakdown[it.severity] = breakdown.get(it.severity, 0) + 1
            if it.status == "OPEN":
                open_count += 1
            elif it.status == "IN_REMEDIATION":
                in_remed_count += 1
            elif it.status == "RESOLVED":
                resolved_count += 1

            weight = SEVERITY_WEIGHTS.get(it.severity, 1.0)
            mult = STATUS_MULTIPLIERS.get(it.status, 0.0)

            # Apply overdue penalty if target date has passed and not resolved
            if it.status != "RESOLVED" and it.target_date < today:
                mult *= 1.5

            score += weight * mult

        return InstitutionalDebtScoreResponse(
            tenant_id=tenant_id,
            total_items=total,
            open_items=open_count,
            in_remediation_items=in_remed_count,
            resolved_items=resolved_count,
            debt_score=round(score, 2),
            severity_breakdown=breakdown,
        )

    def _refresh_metrics(self, tenant_id: str) -> None:
        """Update Prometheus gauge for active items per tenant and severity."""
        severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        for sev in severities:
            count = sum(
                1
                for it in self._items.values()
                if it.tenant_id == tenant_id and it.severity == sev and it.status != "RESOLVED"
            )
            OPEN_COMPLIANCE_DEBT_ITEMS.labels(tenant_id=tenant_id, severity=sev).set(count)


_DEFAULT_REGISTER: ComplianceDebtRegister | None = None


def get_default_debt_register() -> ComplianceDebtRegister:
    """Return the global default ComplianceDebtRegister instance."""
    global _DEFAULT_REGISTER
    if _DEFAULT_REGISTER is None:
        _DEFAULT_REGISTER = ComplianceDebtRegister()
    return _DEFAULT_REGISTER


router = APIRouter(prefix="/v1/compliance/debt", tags=["compliance-debt"])


def _extract_tenant(
    x_tenant_id: str | None = Header(default=None),
) -> str:
    return x_tenant_id or "default"


@router.post("", response_model=ComplianceDebtItem, status_code=status.HTTP_201_CREATED)
def create_debt_item(
    payload: CreateDebtItemRequest,
    tenant_id: str = Depends(_extract_tenant),
    fingerprint: str = Depends(require_api_key),
) -> ComplianceDebtItem:
    """Create a new compliance debt item with multi-tenant isolation."""
    # Ensure tenant matches header if provided
    if tenant_id and payload.tenant_id == "default":
        payload.tenant_id = tenant_id

    register = get_default_debt_register()
    try:
        return register.create_item(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("", response_model=DebtItemListResponse)
def list_debt_items(
    tenant_id: str = Depends(_extract_tenant),
    status_filter: str | None = Query(default=None, alias="status"),
    severity_filter: str | None = Query(default=None, alias="severity"),
    fingerprint: str = Depends(require_api_key),
) -> DebtItemListResponse:
    """List compliance debt items for the authenticated tenant."""
    register = get_default_debt_register()
    items = register.list_items(
        tenant_id=tenant_id,
        status_filter=status_filter,
        severity_filter=severity_filter,
    )
    return DebtItemListResponse(items=items, total=len(items))


@router.get("/metrics/score", response_model=InstitutionalDebtScoreResponse)
def get_institutional_debt_score(
    tenant_id: str = Depends(_extract_tenant),
    fingerprint: str = Depends(require_api_key),
) -> InstitutionalDebtScoreResponse:
    """Calculate institutional compliance debt score and severity breakdown."""
    register = get_default_debt_register()
    return register.calculate_debt_score(tenant_id=tenant_id)


@router.get("/{item_id}", response_model=ComplianceDebtItem)
def get_debt_item(
    item_id: UUID,
    tenant_id: str = Depends(_extract_tenant),
    fingerprint: str = Depends(require_api_key),
) -> ComplianceDebtItem:
    """Retrieve details for a single compliance debt item."""
    register = get_default_debt_register()
    item = register.get_item(item_id, tenant_id=tenant_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Compliance debt item '{item_id}' not found",
        )
    return item


@router.patch("/{item_id}/status", response_model=ComplianceDebtItem)
def update_debt_status(
    item_id: UUID,
    payload: UpdateDebtStatusRequest,
    tenant_id: str = Depends(_extract_tenant),
    fingerprint: str = Depends(require_api_key),
) -> ComplianceDebtItem:
    """Transition the lifecycle status of a compliance debt item."""
    register = get_default_debt_register()
    try:
        return register.update_status(item_id, payload, tenant_id=tenant_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{item_id}/audit", response_model=list[ComplianceDebtAuditEntry])
def get_debt_audit_trail(
    item_id: UUID,
    tenant_id: str = Depends(_extract_tenant),
    fingerprint: str = Depends(require_api_key),
) -> list[ComplianceDebtAuditEntry]:
    """Retrieve full audit transition history for a debt item."""
    register = get_default_debt_register()
    item = register.get_item(item_id, tenant_id=tenant_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Compliance debt item '{item_id}' not found",
        )
    return register.get_audit_trail(item_id, tenant_id=tenant_id)
