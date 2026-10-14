"""Unit, integration, and benchmark tests for Automated Stage Exit Criteria Validator (FEAT-053).

Validates:
1. 20 stage promotion evaluation test cases (10 valid passing cases, 10 lacking evidence / incomplete blocked).
2. HTTP 412 Precondition Failed response when exit criteria are unsatisfied.
3. Administrative override gating: minimum 15 characters justification, recorded audit trail.
4. Latency performance: p95 evaluation <= 6.0ms.
5. Multi-tenant isolation: strict tenant scoping of validation history and evidence.
6. REST API endpoints: POST /v1/playbooks/{run_id}/validate-exit and POST /v1/playbooks/{run_id}/promote.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.workflows.engine import (
    BUILTIN_PLAYBOOKS,
    PlaybookEngine,
    PlaybookEngineConfig,
)
from app.workflows.exit_validator import (
    ExitCriteriaPreconditionFailedError,
    ExitCriteriaValidator,
    ExitValidatorConfig,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


@pytest.fixture
def custom_engine() -> PlaybookEngine:
    config = PlaybookEngineConfig(
        allow_stage_skipping=False,
        auto_verify_exit_criteria=True,
    )
    return PlaybookEngine(config=config)


@pytest.fixture
def exit_validator(custom_engine: PlaybookEngine) -> ExitCriteriaValidator:
    config = ExitValidatorConfig(enforce_strict_exit=True, min_override_length=15)
    return ExitCriteriaValidator(config=config, engine=custom_engine)


def test_validator_blocks_when_milestones_incomplete(
    custom_engine: PlaybookEngine,
    exit_validator: ExitCriteriaValidator,
) -> None:
    """Stage promotion is blocked 100% of the time when stage deliverables are incomplete."""
    run = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-test-01",
        assigned_lead="Chief Architect",
    )

    result = exit_validator.validate_stage_exit(
        run_id=run.run_id,
        current_stage=1,
        tenant_id="tenant-test-01",
    )

    assert not result.can_advance
    assert len(result.blocking_issues) > 0
    assert any("M1-1" in b for b in result.blocking_issues)
    assert any(c.status == "FAILED" for c in result.checks_evaluated)


def test_validator_passes_when_all_milestones_complete(
    custom_engine: PlaybookEngine,
    exit_validator: ExitCriteriaValidator,
) -> None:
    """Stage promotion succeeds when all stage deliverables have verified evidence."""
    run = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-test-02",
        assigned_lead="Lead SRE",
    )

    # Complete all stage 1 milestones
    custom_engine.complete_milestone(
        run_id=run.run_id,
        milestone_id="M1-1",
        tenant_id="tenant-test-02",
        evidence_doc_id="ADR-0041-DECOUPLE",
        notes="Domain boundaries verified and documented in repository.",
    )
    custom_engine.complete_milestone(
        run_id=run.run_id,
        milestone_id="M1-2",
        tenant_id="tenant-test-02",
        evidence_doc_id="ADR-0042-CONTRACTS",
        notes="All database models decoupled without circular imports.",
    )

    result = exit_validator.validate_stage_exit(
        run_id=run.run_id,
        current_stage=1,
        tenant_id="tenant-test-02",
    )

    assert result.can_advance
    assert len(result.blocking_issues) == 0
    assert all(c.status == "PASSED" for c in result.checks_evaluated)


def test_administrative_override_enforcement(
    custom_engine: PlaybookEngine,
    exit_validator: ExitCriteriaValidator,
) -> None:
    """Administrative overrides require a minimum 15 character justification and permit promotion."""
    run = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-override-01",
        assigned_lead="VP Compliance",
    )

    # 1. Reject override shorter than 15 characters
    res_short = exit_validator.validate_stage_exit(
        run_id=run.run_id,
        current_stage=1,
        tenant_id="tenant-override-01",
        override_justification="Too short",
    )
    assert not res_short.can_advance
    assert not res_short.override_applied
    assert any("at least 15 characters" in b for b in res_short.blocking_issues)

    # 2. Accept override with valid justification >= 15 characters
    res_valid = exit_validator.validate_stage_exit(
        run_id=run.run_id,
        current_stage=1,
        tenant_id="tenant-override-01",
        override_justification="Architectural review verified under emergency regulatory provision.",
    )
    assert res_valid.can_advance
    assert res_valid.override_applied


def test_20_stage_promotion_evaluation_dataset(
    custom_engine: PlaybookEngine,
    exit_validator: ExitCriteriaValidator,
) -> None:
    """Evaluate 20 distinct stage promotion test cases: 10 valid passing and 10 blocked lacking evidence."""
    playbook_ids = [p.playbook_id for p in BUILTIN_PLAYBOOKS]

    # 10 Blocked Cases (Lacking deliverables / failing simulated telemetry)
    for i in range(10):
        pid = playbook_ids[i % len(playbook_ids)]
        run = custom_engine.start_run(
            playbook_id=pid,
            tenant_id=f"tenant-blocked-{i}",
            assigned_lead="Auditor",
        )
        # Without completing milestones, exit criteria MUST fail
        result = exit_validator.validate_stage_exit(
            run_id=run.run_id,
            current_stage=1,
            tenant_id=f"tenant-blocked-{i}",
        )
        assert not result.can_advance, f"Expected run {run.run_id} ({pid}) to be blocked"
        assert len(result.blocking_issues) >= 1

    # 10 Valid Passing Cases
    for i in range(10):
        pid = playbook_ids[i % len(playbook_ids)]
        run = custom_engine.start_run(
            playbook_id=pid,
            tenant_id=f"tenant-passed-{i}",
            assigned_lead="Lead Engineer",
        )
        template = custom_engine.get_template(pid)
        assert template is not None
        stage1 = template.stages[0]

        # Complete all milestones for stage 1
        for m in stage1.milestones:
            custom_engine.complete_milestone(
                run_id=run.run_id,
                milestone_id=m.id,
                tenant_id=f"tenant-passed-{i}",
                evidence_doc_id=f"TEST-EVIDENCE-{m.id}",
                notes=f"Automated compliance signoff for deliverable {m.title}",
            )

        result = exit_validator.validate_stage_exit(
            run_id=run.run_id,
            current_stage=1,
            tenant_id=f"tenant-passed-{i}",
        )
        assert result.can_advance, f"Expected run {run.run_id} ({pid}) to pass exit criteria"
        assert len(result.blocking_issues) == 0


def test_engine_advance_stage_blocked_by_exit_validator(
    custom_engine: PlaybookEngine,
) -> None:
    """PlaybookEngine.advance_stage raises ExitCriteriaPreconditionFailedError when criteria fail."""
    run = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-advance-block",
        assigned_lead="Lead Architect",
    )

    with pytest.raises(ExitCriteriaPreconditionFailedError) as exc_info:
        custom_engine.advance_stage(run_id=run.run_id, tenant_id="tenant-advance-block")

    assert "Exit criteria for Stage 1 not yet satisfied" in str(exc_info.value)
    assert len(exc_info.value.blocking_issues) > 0


def test_engine_advance_stage_succeeds_with_override(
    custom_engine: PlaybookEngine,
) -> None:
    """PlaybookEngine.advance_stage advances when valid override justification is supplied."""
    run = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-advance-override",
        assigned_lead="Lead Architect",
    )

    promoted = custom_engine.advance_stage(
        run_id=run.run_id,
        tenant_id="tenant-advance-override",
        override_justification="Exemption granted per regulatory compliance memorandum 2026-B.",
    )

    assert promoted.current_stage == 2


def test_rest_api_validate_exit_endpoint(
    test_client: TestClient, api_headers: dict[str, str]
) -> None:
    """REST API POST /v1/playbooks/{run_id}/validate-exit returns structured validation report."""
    # 1. Start a run
    start_resp = test_client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.ai-assurance",
            "tenant_id": "tenant-api-test-01",
            "assigned_lead": "AI Safety Officer",
        },
    )
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]

    # 2. Validate exit (should be blocked initially)
    val_resp = test_client.post(
        f"/v1/playbooks/{run_id}/validate-exit?tenant_id=tenant-api-test-01",
        headers=api_headers,
    )
    assert val_resp.status_code == 200
    data = val_resp.json()
    assert not data["can_advance"]
    assert len(data["blocking_issues"]) > 0
    assert len(data["checks_evaluated"]) > 0


def test_rest_api_promote_endpoint_blocked_with_412(
    test_client: TestClient, api_headers: dict[str, str]
) -> None:
    """REST API POST /v1/playbooks/{run_id}/promote returns HTTP 412 when exit criteria fail."""
    start_resp = test_client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.vendor-risk",
            "tenant_id": "tenant-api-test-412",
            "assigned_lead": "Vendor Auditor",
        },
    )
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]

    promote_resp = test_client.post(
        f"/v1/playbooks/{run_id}/promote?tenant_id=tenant-api-test-412",
        headers=api_headers,
        json={"current_stage": 1},
    )
    assert promote_resp.status_code == 412
    assert "Stage exit criteria not satisfied" in promote_resp.json()["detail"]


def test_rest_api_promote_endpoint_succeeds_with_override(
    test_client: TestClient, api_headers: dict[str, str]
) -> None:
    """REST API POST /v1/playbooks/{run_id}/promote succeeds when valid override justification is given."""
    start_resp = test_client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.vendor-risk",
            "tenant_id": "tenant-api-test-override",
            "assigned_lead": "Vendor Auditor",
        },
    )
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]

    promote_resp = test_client.post(
        f"/v1/playbooks/{run_id}/promote?tenant_id=tenant-api-test-override",
        headers=api_headers,
        json={
            "current_stage": 1,
            "override_justification": "Approved regulatory exception signed by CCO and audit partner.",
        },
    )
    assert promote_resp.status_code == 200
    assert promote_resp.json()["current_stage"] == 2


def test_exit_validation_performance_latency_p95(
    custom_engine: PlaybookEngine,
    exit_validator: ExitCriteriaValidator,
) -> None:
    """Execution latency for stage exit criteria evaluation remains under 6.0ms (p95)."""
    run = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-perf-01",
        assigned_lead="Performance Lead",
    )

    latencies: list[float] = []
    iterations = 100

    for _ in range(iterations):
        t0 = time.perf_counter()
        exit_validator.validate_stage_exit(
            run_id=run.run_id,
            current_stage=1,
            tenant_id="tenant-perf-01",
        )
        latencies.append((time.perf_counter() - t0) * 1000.0)

    latencies.sort()
    p95_idx = int(0.95 * len(latencies))
    p95_latency = latencies[p95_idx]

    assert p95_latency <= 6.0, (
        f"Exit validator p95 latency {p95_latency:.3f}ms exceeded 6.0ms limit."
    )


def test_multi_tenant_isolation(
    custom_engine: PlaybookEngine,
    exit_validator: ExitCriteriaValidator,
) -> None:
    """Exit criteria validation is strictly isolated between tenants."""
    run_a = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-alpha",
        assigned_lead="Lead Alpha",
    )
    run_b = custom_engine.start_run(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-beta",
        assigned_lead="Lead Beta",
    )

    # Complete Alpha
    custom_engine.complete_milestone(
        run_id=run_a.run_id,
        milestone_id="M1-1",
        tenant_id="tenant-alpha",
        evidence_doc_id="DOC-ALPHA-1",
        notes="Decoupling complete for alpha tenant.",
    )
    custom_engine.complete_milestone(
        run_id=run_a.run_id,
        milestone_id="M1-2",
        tenant_id="tenant-alpha",
        evidence_doc_id="DOC-ALPHA-2",
        notes="Contracts drafted for alpha tenant.",
    )

    res_alpha = exit_validator.validate_stage_exit(
        run_id=run_a.run_id,
        current_stage=1,
        tenant_id="tenant-alpha",
    )
    assert res_alpha.can_advance

    # Beta should still be blocked
    res_beta = exit_validator.validate_stage_exit(
        run_id=run_b.run_id,
        current_stage=1,
        tenant_id="tenant-beta",
    )
    assert not res_beta.can_advance

    # Alpha cannot access Beta's run
    with pytest.raises(ValueError):
        exit_validator.validate_stage_exit(
            run_id=run_b.run_id,
            current_stage=1,
            tenant_id="tenant-alpha",
        )
