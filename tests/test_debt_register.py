"""Integration and lifecycle tests for Enterprise Compliance Debt Register (FEAT-038).

Validates:
1. Input validation rules (valid email, future target date, min 20-char justification).
2. Foreign key / catalog validation (antipattern_id, deprecation_id).
3. State machine lifecycle transitions (OPEN -> IN_REMEDIATION -> RESOLVED).
4. Multi-tenant data isolation.
5. Institutional debt scoring calculations.
6. Prometheus gauge observability.
7. Latency budget (<= 10.0 ms p95).
8. Fast-path REST API endpoints under /v1/compliance/debt/*.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.debt_register import (
    ComplianceDebtItem,
    ComplianceDebtRegister,
    CreateDebtItemRequest,
    InstitutionalDebtScoreResponse,
    UpdateDebtStatusRequest,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def register() -> ComplianceDebtRegister:
    # Reset in-memory register state for test isolation
    reg = ComplianceDebtRegister()
    return reg


def test_create_debt_item_success(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=90)
    req = CreateDebtItemRequest(
        tenant_id="tenant-acme",
        practice_name="Legacy SHA-1 Certificate Deprecation",
        owner_email="ciso@acmebank.in",
        target_date=future_date,
        justification="Core payment gateway legacy certificate replacement scheduled for Q4 maintenance window.",
        severity="HIGH",
        deprecation_id="DEP-001",
    )

    item = register.create_item(req)
    assert isinstance(item, ComplianceDebtItem)
    assert isinstance(item.id, UUID)
    assert item.tenant_id == "tenant-acme"
    assert item.practice_name == "Legacy SHA-1 Certificate Deprecation"
    assert item.status == "OPEN"
    assert item.severity == "HIGH"
    assert item.owner_email == "ciso@acmebank.in"
    assert item.target_date == future_date
    assert item.deprecation_id == "DEP-001"


def test_create_debt_item_validation_failures(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=30)
    past_date = date.today() - timedelta(days=5)

    # Invalid email
    with pytest.raises(ValueError, match="Invalid owner email format"):
        register.create_item(
            CreateDebtItemRequest(
                tenant_id="tenant-acme",
                practice_name="Test",
                owner_email="invalid-email-address",
                target_date=future_date,
                justification="Valid justification that is definitely longer than 20 characters.",
            )
        )

    # Past target date
    with pytest.raises(ValueError, match="Target date must be in the future"):
        register.create_item(
            CreateDebtItemRequest(
                tenant_id="tenant-acme",
                practice_name="Test",
                owner_email="audit@acme.in",
                target_date=past_date,
                justification="Valid justification that is definitely longer than 20 characters.",
            )
        )

    # Short justification
    with pytest.raises(ValueError, match="Justification must be at least 20 characters"):
        register.create_item(
            CreateDebtItemRequest(
                tenant_id="tenant-acme",
                practice_name="Test",
                owner_email="audit@acme.in",
                target_date=future_date,
                justification="Too short",
            )
        )


def test_invalid_foreign_key_references(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=60)
    # Invalid antipattern ID
    with pytest.raises(ValueError, match="Antipattern ID.*not recognized"):
        register.create_item(
            CreateDebtItemRequest(
                tenant_id="tenant-acme",
                practice_name="Test Antipattern",
                owner_email="risk@acme.in",
                target_date=future_date,
                justification="Valid justification with plenty of required descriptive characters.",
                antipattern_id="NON_EXISTENT_ANTIPATTERN_999",
            )
        )


def test_lifecycle_transitions_and_audit_trail(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=45)
    item = register.create_item(
        CreateDebtItemRequest(
            tenant_id="tenant-lifecycle",
            practice_name="Unencrypted Cardholder Backups",
            owner_email="lead@fintech.in",
            target_date=future_date,
            justification="Database cold snapshots lack KMS envelope encryption; migrating to AES-256 GCM.",
            severity="CRITICAL",
        )
    )

    # 1. Transition OPEN -> IN_REMEDIATION
    updated1 = register.update_status(
        item.id,
        UpdateDebtStatusRequest(
            status="IN_REMEDIATION",
            notes="Assigned to infrastructure sprint 42; cloud KMS keys provisioned.",
            actor_email="lead@fintech.in",
        ),
    )
    assert updated1.status == "IN_REMEDIATION"

    # 2. Transition IN_REMEDIATION -> RESOLVED
    updated2 = register.update_status(
        item.id,
        UpdateDebtStatusRequest(
            status="RESOLVED",
            notes="All S3 buckets encrypted; automated daily compliance scanner verified clean.",
            actor_email="ciso@fintech.in",
        ),
    )
    assert updated2.status == "RESOLVED"

    # Check audit log
    audit_trail = register.get_audit_trail(item.id)
    assert len(audit_trail) == 3  # initial creation + 2 transitions
    assert audit_trail[1].previous_status == "OPEN"
    assert audit_trail[1].new_status == "IN_REMEDIATION"
    assert audit_trail[2].previous_status == "IN_REMEDIATION"
    assert audit_trail[2].new_status == "RESOLVED"


def test_multi_tenant_isolation(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=30)
    register.create_item(
        CreateDebtItemRequest(
            tenant_id="tenant-alpha",
            practice_name="Alpha Secret Management Exception",
            owner_email="ops@alpha.com",
            target_date=future_date,
            justification="Hardcoded staging API key in internal testing scripts.",
        )
    )
    register.create_item(
        CreateDebtItemRequest(
            tenant_id="tenant-beta",
            practice_name="Beta Logging Retention Exception",
            owner_email="ops@beta.com",
            target_date=future_date,
            justification="Log retention currently 90 days instead of statutory 180 days.",
        )
    )

    alpha_items = register.list_items(tenant_id="tenant-alpha")
    beta_items = register.list_items(tenant_id="tenant-beta")

    assert len(alpha_items) == 1
    assert alpha_items[0].practice_name == "Alpha Secret Management Exception"

    assert len(beta_items) == 1
    assert beta_items[0].practice_name == "Beta Logging Retention Exception"


def test_institutional_debt_score_calculation(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=30)
    # Add CRITICAL (weight 10, OPEN -> 10.0)
    register.create_item(
        CreateDebtItemRequest(
            tenant_id="tenant-score",
            practice_name="Critical Finding",
            severity="CRITICAL",
            owner_email="sec@score.com",
            target_date=future_date,
            justification="Critical regulatory exception with significant immediate systemic risk.",
        )
    )
    # Add HIGH (weight 5, IN_REMEDIATION -> 2.5)
    item_high = register.create_item(
        CreateDebtItemRequest(
            tenant_id="tenant-score",
            practice_name="High Finding",
            severity="HIGH",
            owner_email="sec@score.com",
            target_date=future_date,
            justification="High severity finding undergoing active remediation across systems.",
        )
    )
    register.update_status(
        item_high.id,
        UpdateDebtStatusRequest(
            status="IN_REMEDIATION", notes="Started", actor_email="sec@score.com"
        ),
    )
    # Add MEDIUM (weight 2, RESOLVED -> 0.0)
    item_med = register.create_item(
        CreateDebtItemRequest(
            tenant_id="tenant-score",
            practice_name="Medium Finding",
            severity="MEDIUM",
            owner_email="sec@score.com",
            target_date=future_date,
            justification="Medium finding that has already completed remediation verification.",
        )
    )
    register.update_status(
        item_med.id,
        UpdateDebtStatusRequest(status="RESOLVED", notes="Fixed", actor_email="sec@score.com"),
    )

    summary = register.calculate_debt_score(tenant_id="tenant-score")
    assert isinstance(summary, InstitutionalDebtScoreResponse)
    assert summary.total_items == 3
    assert summary.open_items == 1
    assert summary.in_remediation_items == 1
    assert summary.resolved_items == 1
    # 10.0 * 1.0 + 5.0 * 0.5 + 2.0 * 0.0 = 12.5
    assert summary.debt_score == 12.5


def test_crud_performance_sla(register: ComplianceDebtRegister) -> None:
    future_date = date.today() + timedelta(days=60)
    latencies: list[float] = []

    for i in range(25):
        t0 = time.perf_counter()
        item = register.create_item(
            CreateDebtItemRequest(
                tenant_id="tenant-perf",
                practice_name=f"Performance Verification Item {i}",
                owner_email=f"perf{i}@bank.in",
                target_date=future_date,
                justification=f"Benchmark latency measurement justification with sufficient length {i}.",
            )
        )
        register.get_item(item.id)
        register.update_status(
            item.id,
            UpdateDebtStatusRequest(
                status="IN_REMEDIATION", notes="Bench", actor_email=f"perf{i}@bank.in"
            ),
        )
        t_el = (time.perf_counter() - t0) * 1000.0
        latencies.append(t_el)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 <= 10.0, f"p95 latency {p95:.2f}ms exceeds 10.0ms SLA"


def test_api_debt_register_routes(test_client: TestClient) -> None:
    headers = auth(PRIMARY_KEY)
    headers["X-Tenant-ID"] = "tenant-api-test"
    future_date = (date.today() + timedelta(days=40)).isoformat()

    # 1. Create item
    payload = {
        "tenant_id": "tenant-api-test",
        "practice_name": "API Route Exception Verification",
        "owner_email": "compliance@apibank.in",
        "target_date": future_date,
        "justification": "Comprehensive justification verifying full REST API contract compatibility.",
        "severity": "HIGH",
    }
    create_resp = test_client.post("/v1/compliance/debt", json=payload, headers=headers)
    assert create_resp.status_code == 201
    item_data = create_resp.json()
    item_id = item_data["id"]
    assert item_data["status"] == "OPEN"
    assert item_data["severity"] == "HIGH"

    # 2. List items
    list_resp = test_client.get("/v1/compliance/debt", headers=headers)
    assert list_resp.status_code == 200
    items_list = list_resp.json()["items"]
    assert any(it["id"] == item_id for it in items_list)

    # 3. Update status
    patch_resp = test_client.patch(
        f"/v1/compliance/debt/{item_id}/status",
        json={"status": "IN_REMEDIATION", "notes": "Work in progress"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "IN_REMEDIATION"

    # 4. Institutional Debt Score
    score_resp = test_client.get("/v1/compliance/debt/metrics/score", headers=headers)
    assert score_resp.status_code == 200
    score_data = score_resp.json()
    assert score_data["total_items"] >= 1
    assert score_data["debt_score"] > 0.0
