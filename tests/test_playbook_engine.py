"""Unit, benchmark, and integration test suite for Interactive Compliance Playbook Runtime (FEAT-051).

Covers all 12 statutory compliance playbooks, 24 simulated enterprise execution runs,
strict 4-stage sequential state machines, exit criteria gating, multi-tenant isolation,
performance budget validation (p95 <= 8ms), and REST API endpoints.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.workflows.engine import (
    InvalidStateTransitionError,
    PlaybookEngine,
    PlaybookEngineConfig,
    PlaybookNotFoundError,
    PlaybookRunNotFoundError,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


@pytest.fixture
def fresh_engine() -> PlaybookEngine:
    return PlaybookEngine()


@pytest.fixture(autouse=True)
def _reset_default_playbook_engine() -> None:
    from app.workflows.engine import BUILTIN_PLAYBOOKS, get_default_playbook_engine

    engine = get_default_playbook_engine()
    engine._templates = {t.playbook_id: t for t in BUILTIN_PLAYBOOKS}
    engine._runs.clear()


# ==============================================================================
# 1. Template Catalog & Statutory Coverage Tests
# ==============================================================================


def test_builtin_playbook_catalog_contains_12_statutory_playbooks(
    fresh_engine: PlaybookEngine,
) -> None:
    templates = fresh_engine.list_templates()
    assert len(templates) == 12

    expected_ids = {
        "playbook.foundations-30d",
        "playbook.deploy-confidence-60d",
        "playbook.ai-assurance",
        "playbook.incident-readiness",
        "playbook.regulated-release",
        "playbook.crypto-migration",
        "playbook.resilience",
        "playbook.data-governance",
        "playbook.vendor-risk",
        "playbook.audit-prep",
        "playbook.zero-trust",
        "playbook.continuous-compliance",
    }
    actual_ids = {t.playbook_id for t in templates}
    assert actual_ids == expected_ids


def test_every_template_has_4_stages_with_milestones_and_exit_criteria(
    fresh_engine: PlaybookEngine,
) -> None:
    for template in fresh_engine.list_templates():
        assert template.total_stages == 4
        assert len(template.stages) == 4
        for stage in template.stages:
            assert stage.stage_number in (1, 2, 3, 4)
            assert len(stage.stage_name) > 0
            assert len(stage.description) > 0
            assert len(stage.milestones) >= 1
            assert len(stage.exit_criteria) >= 1
            for m in stage.milestones:
                assert len(m.id) > 0
                assert len(m.title) > 0
                assert len(m.role) > 0


# ==============================================================================
# 2. State Machine & Stage Progression Logic Tests
# ==============================================================================


def test_start_playbook_instantiates_active_run_at_stage_1(
    fresh_engine: PlaybookEngine,
) -> None:
    run = fresh_engine.start_playbook(
        playbook_id="playbook.foundations-30d",
        tenant_id="tenant-alpha",
        assigned_lead="Chief Architect",
    )
    assert run.current_stage == 1
    assert run.status == "ACTIVE"
    assert run.total_stages == 4
    assert run.assigned_lead == "Chief Architect"
    assert run.tenant_id == "tenant-alpha"
    assert "stage_history" in run.stage_data
    assert len(run.stage_data["stage_history"]) == 1
    assert run.stage_data["stage_history"][0]["stage_number"] == 1


def test_start_playbook_raises_for_invalid_id(
    fresh_engine: PlaybookEngine,
) -> None:
    with pytest.raises(PlaybookNotFoundError):
        fresh_engine.start_playbook("nonexistent.playbook.id")


def test_start_playbook_raises_for_empty_assigned_lead(
    fresh_engine: PlaybookEngine,
) -> None:
    with pytest.raises(ValueError, match="assigned_lead must be non-empty"):
        fresh_engine.start_playbook("playbook.foundations-30d", assigned_lead="   ")


def test_exit_criteria_blocks_advance_when_milestones_incomplete(
    fresh_engine: PlaybookEngine,
) -> None:
    run = fresh_engine.start_playbook("playbook.foundations-30d")

    # Advancing without completing Stage 1 milestones must raise InvalidStateTransitionError
    with pytest.raises(
        InvalidStateTransitionError, match="Exit criteria for Stage 1 not yet satisfied"
    ):
        fresh_engine.advance_stage(run.run_id)


def test_stage_skipping_prohibited_under_strict_config(
    fresh_engine: PlaybookEngine,
) -> None:
    run = fresh_engine.start_playbook("playbook.foundations-30d")

    # Attempting to jump directly from Stage 1 to Stage 3
    with pytest.raises(InvalidStateTransitionError, match="Invalid stage skip from 1 to 3"):
        fresh_engine.advance_stage(run.run_id, target_stage=3)


def test_successful_progression_across_all_4_stages(
    fresh_engine: PlaybookEngine,
) -> None:
    playbook_id = "playbook.foundations-30d"
    template = fresh_engine.get_template(playbook_id)
    assert template is not None

    run = fresh_engine.start_playbook(playbook_id, tenant_id="tenant-beta")

    # Progress through stages 1 to 4
    for stage in template.stages:
        assert run.current_stage == stage.stage_number
        assert run.status == "ACTIVE"

        # Complete all milestones for current stage
        for milestone in stage.milestones:
            run = fresh_engine.complete_milestone(
                run_id=run.run_id,
                milestone_id=milestone.id,
                tenant_id="tenant-beta",
                notes=f"Audit verified {milestone.id}",
            )

        # Advance to next stage (or complete at stage 4)
        run = fresh_engine.advance_stage(run.run_id, tenant_id="tenant-beta")

    assert run.current_stage == 4
    assert run.status == "COMPLETED"


def test_advancing_completed_run_raises_error(
    fresh_engine: PlaybookEngine,
) -> None:
    # Use relaxed config without auto exit check for fast test
    relaxed_engine = PlaybookEngine(config=PlaybookEngineConfig(auto_verify_exit_criteria=False))
    run = relaxed_engine.start_playbook("playbook.foundations-30d")
    for _ in range(4):
        run = relaxed_engine.advance_stage(run.run_id)
    assert run.status == "COMPLETED"

    with pytest.raises(InvalidStateTransitionError, match="already COMPLETED"):
        relaxed_engine.advance_stage(run.run_id)


# ==============================================================================
# 3. Multi-Tenant Isolation Tests
# ==============================================================================


def test_multi_tenant_isolation_prevents_cross_tenant_access(
    fresh_engine: PlaybookEngine,
) -> None:
    run_a = fresh_engine.start_playbook("playbook.vendor-risk", tenant_id="tenant-x")

    # Tenant Y cannot see Tenant X's run
    run_lookup = fresh_engine.get_run(run_a.run_id, tenant_id="tenant-y")
    assert run_lookup is None

    # Tenant Y cannot advance Tenant X's run
    with pytest.raises(PlaybookRunNotFoundError):
        fresh_engine.advance_stage(run_a.run_id, tenant_id="tenant-y")

    # Tenant Y cannot complete milestone on Tenant X's run
    with pytest.raises(PlaybookRunNotFoundError):
        fresh_engine.complete_milestone(run_a.run_id, "M1-1", tenant_id="tenant-y")


# ==============================================================================
# 4. Evaluation Dataset: 24 Simulated Enterprise Playbook Execution Runs
# ==============================================================================


def test_evaluation_dataset_24_simulated_runs_100_percent_adherence(
    fresh_engine: PlaybookEngine,
) -> None:
    """Simulate 24 enterprise execution runs across all 12 playbooks.

    - Run 1..12: Happy-path enterprise run completing all milestones and certifying all 4 stages.
    - Run 13..24: Exit-criteria enforcement run verifying blocked transitions on missing milestones.
    """
    templates = fresh_engine.list_templates()
    assert len(templates) == 12

    completed_runs_count = 0
    blocked_enforcements_count = 0

    # Part A: 12 Successful end-to-end runs
    for tmpl in templates:
        tenant = f"enterprise-{tmpl.domain}-pass"
        run = fresh_engine.start_playbook(tmpl.playbook_id, tenant_id=tenant)

        for stage in tmpl.stages:
            for milestone in stage.milestones:
                run = fresh_engine.complete_milestone(
                    run_id=run.run_id,
                    milestone_id=milestone.id,
                    tenant_id=tenant,
                    evidence_doc_id="EVID-DOC-001",
                    notes="Statutory verification signed off by compliance lead.",
                )
            run = fresh_engine.advance_stage(run.run_id, tenant_id=tenant)

        assert run.status == "COMPLETED"
        assert run.current_stage == 4
        completed_runs_count += 1

    # Part B: 12 Exit criteria enforcement runs
    for tmpl in templates:
        tenant = f"enterprise-{tmpl.domain}-blocked"
        run = fresh_engine.start_playbook(tmpl.playbook_id, tenant_id=tenant)

        # Do NOT complete milestones; advance must fail
        with pytest.raises(
            InvalidStateTransitionError, match="Exit criteria for Stage 1 not yet satisfied"
        ):
            fresh_engine.advance_stage(run.run_id, tenant_id=tenant)

        assert run.status == "ACTIVE"
        assert run.current_stage == 1
        blocked_enforcements_count += 1

    assert completed_runs_count == 12
    assert blocked_enforcements_count == 12
    assert completed_runs_count + blocked_enforcements_count == 24


# ==============================================================================
# 5. Performance Budget: State Transition Evaluation Latency <= 8.0 ms p95
# ==============================================================================


def test_state_transition_evaluation_latency_under_8ms_p95(
    fresh_engine: PlaybookEngine,
) -> None:
    relaxed_engine = PlaybookEngine(config=PlaybookEngineConfig(auto_verify_exit_criteria=False))
    latencies: list[float] = []

    for i in range(50):
        run = relaxed_engine.start_playbook("playbook.ai-assurance", tenant_id=f"perf-tenant-{i}")
        t0 = time.perf_counter()
        relaxed_engine.advance_stage(run.run_id, tenant_id=f"perf-tenant-{i}")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

    latencies.sort()
    p95_index = int(0.95 * len(latencies))
    p95_latency = latencies[p95_index]
    assert p95_latency <= 8.0, f"p95 latency {p95_latency:.2f}ms exceeded 8.0ms budget"


# ==============================================================================
# 6. REST API Endpoint Integration Tests
# ==============================================================================


def test_api_list_playbook_templates(client: TestClient, api_headers: dict[str, str]) -> None:
    resp = client.get("/v1/playbooks/templates", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 12
    first = data[0]
    assert "playbook_id" in first
    assert "title" in first
    assert "domain" in first
    assert "stages" in first
    assert len(first["stages"]) == 4


def test_api_start_playbook_run(client: TestClient, api_headers: dict[str, str]) -> None:
    resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.ai-assurance",
            "tenant_id": "tenant-api-test",
            "assigned_lead": "Lead AI Governance Officer",
        },
    )
    assert resp.status_code == 200
    run = resp.json()
    assert run["playbook_id"] == "playbook.ai-assurance"
    assert run["tenant_id"] == "tenant-api-test"
    assert run["assigned_lead"] == "Lead AI Governance Officer"
    assert run["current_stage"] == 1
    assert run["status"] == "ACTIVE"


def test_api_get_playbook_run(client: TestClient, api_headers: dict[str, str]) -> None:
    # First start a run
    start_resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.incident-readiness",
            "tenant_id": "tenant-get-test",
            "assigned_lead": "SRE Director",
        },
    )
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]

    # Fetch run
    get_resp = client.get(
        f"/v1/playbooks/runs/{run_id}?tenant_id=tenant-get-test",
        headers=api_headers,
    )
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["run_id"] == run_id
    assert fetched["current_stage"] == 1


def test_api_advance_blocked_without_milestones(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    # Start run
    start_resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.foundations-30d",
            "tenant_id": "tenant-advance-fail",
            "assigned_lead": "Compliance Lead",
        },
    )
    run_id = start_resp.json()["run_id"]

    # Advancing immediately should return 400 Bad Request
    adv_resp = client.post(
        f"/v1/playbooks/runs/{run_id}/advance?tenant_id=tenant-advance-fail",
        headers=api_headers,
        json={},
    )
    assert adv_resp.status_code == 400
    assert "Exit criteria for Stage 1 not yet satisfied" in adv_resp.json()["detail"]


def test_api_complete_milestone_and_advance(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    # Start run
    start_resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.foundations-30d",
            "tenant_id": "tenant-adv-success",
            "assigned_lead": "Compliance Lead",
        },
    )
    run_id = start_resp.json()["run_id"]

    # Complete Stage 1 milestones (M1-1, M1-2)
    m1_resp = client.post(
        f"/v1/playbooks/runs/{run_id}/milestones/M1-1?tenant_id=tenant-adv-success",
        headers=api_headers,
        json={"milestone_id": "M1-1", "notes": "Mapped database boundaries."},
    )
    assert m1_resp.status_code == 200

    m2_resp = client.post(
        f"/v1/playbooks/runs/{run_id}/milestones/M1-2?tenant_id=tenant-adv-success",
        headers=api_headers,
        json={"milestone_id": "M1-2", "notes": "Drafted decoupling ADR."},
    )
    assert m2_resp.status_code == 200

    # Advance to Stage 2
    adv_resp = client.post(
        f"/v1/playbooks/runs/{run_id}/advance?tenant_id=tenant-adv-success",
        headers=api_headers,
        json={},
    )
    assert adv_resp.status_code == 200
    assert adv_resp.json()["current_stage"] == 2


def test_api_list_playbook_runs(client: TestClient, api_headers: dict[str, str]) -> None:
    client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.ai-assurance",
            "tenant_id": "tenant-list-test",
            "assigned_lead": "Auditor",
        },
    )
    resp = client.get(
        "/v1/playbooks/runs?tenant_id=tenant-list-test",
        headers=api_headers,
    )
    assert resp.status_code == 200
    runs = resp.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1
    assert runs[0]["tenant_id"] == "tenant-list-test"


def test_api_unauthorized_access_rejected(client: TestClient) -> None:
    resp = client.get("/v1/playbooks/templates")
    assert resp.status_code in (401, 403)
