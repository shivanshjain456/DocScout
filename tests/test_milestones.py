"""Unit, benchmark, and integration test suite for 4-Stage Progressive Milestone Tracker (FEAT-052).

Covers granular milestone completion across all 4 stages, evidence attachment,
statutory note length validation, inactive stage blocking, multi-tenant isolation,
zero orphaned records on reset, performance budget (p95 <= 4.0ms), and REST API endpoints.
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
    PlaybookRunNotFoundError,
)
from app.workflows.milestone_tracker import (
    MilestoneConfig,
    MilestoneTracker,
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
def engine() -> PlaybookEngine:
    return PlaybookEngine()


@pytest.fixture
def tracker(engine: PlaybookEngine) -> MilestoneTracker:
    return MilestoneTracker(
        engine=engine, config=MilestoneConfig(require_evidence_attachment=False)
    )


@pytest.fixture
def strict_tracker(engine: PlaybookEngine) -> MilestoneTracker:
    return MilestoneTracker(engine=engine, config=MilestoneConfig(require_evidence_attachment=True))


# ==============================================================================
# 1. Milestone Completion & Granular Stage Progress Tests
# ==============================================================================


def test_complete_milestone_updates_stage_progress(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    run = engine.start_playbook("playbook.foundations-30d", tenant_id="tenant-m1")
    assert run.current_stage == 1

    # Stage 1 has 2 milestones: M1-1 and M1-2
    progress1 = tracker.record_milestone(
        run_id=run.run_id,
        milestone_id="M1-1",
        tenant_id="tenant-m1",
        notes="Verified domain boundary mappings and interfaces.",
    )
    assert progress1.stage_number == 1
    assert progress1.total_milestones == 2
    assert progress1.completed_milestones == 1
    assert progress1.completion_ratio == 0.5
    assert not progress1.exit_ready

    # Complete second milestone in Stage 1
    progress2 = tracker.record_milestone(
        run_id=run.run_id,
        milestone_id="M1-2",
        tenant_id="tenant-m1",
        evidence_doc_id="ADR-0042",
        notes="Architectural decoupling contracts signed off.",
    )
    assert progress2.stage_number == 1
    assert progress2.total_milestones == 2
    assert progress2.completed_milestones == 2
    assert progress2.completion_ratio == 1.0
    assert progress2.exit_ready


def test_complete_milestone_rejects_inactive_stage_milestone(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    run = engine.start_playbook("playbook.foundations-30d", tenant_id="tenant-m2")
    assert run.current_stage == 1

    # M2-1 belongs to Stage 2, but current stage is 1
    with pytest.raises(InvalidStateTransitionError, match="inactive stage"):
        tracker.record_milestone(
            run_id=run.run_id,
            milestone_id="M2-1",
            tenant_id="tenant-m2",
            notes="Attempting premature stage 2 milestone completion.",
        )


def test_notes_length_validation_enforces_minimum_10_characters(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    run = engine.start_playbook("playbook.foundations-30d", tenant_id="tenant-m3")

    # Short notes (< 10 chars) must be rejected
    with pytest.raises(ValueError, match="at least 10 characters"):
        tracker.record_milestone(
            run_id=run.run_id,
            milestone_id="M1-1",
            tenant_id="tenant-m3",
            notes="too short",
        )


def test_strict_tracker_enforces_evidence_attachment(
    engine: PlaybookEngine, strict_tracker: MilestoneTracker
) -> None:
    run = engine.start_playbook("playbook.ai-assurance", tenant_id="tenant-m4")

    # Missing evidence document ID must be rejected when require_evidence_attachment=True
    with pytest.raises(ValueError, match="Evidence document ID attachment required"):
        strict_tracker.record_milestone(
            run_id=run.run_id,
            milestone_id="M1-1",
            tenant_id="tenant-m4",
            evidence_doc_id=None,
            notes="Verified AI model risk controls without evidence doc.",
        )

    # Providing evidence document ID succeeds
    progress = strict_tracker.record_milestone(
        run_id=run.run_id,
        milestone_id="M1-1",
        tenant_id="tenant-m4",
        evidence_doc_id="EVID-MODEL-CARD-001",
        notes="Verified AI model risk controls with signed model card.",
    )
    assert progress.completed_milestones == 1


def test_milestone_completion_on_nonexistent_run_raises_not_found(
    tracker: MilestoneTracker,
) -> None:
    with pytest.raises(PlaybookRunNotFoundError):
        tracker.record_milestone(
            run_id="nonexistent-run-id",
            milestone_id="M1-1",
            notes="Testing nonexistent run error handling.",
        )


# ==============================================================================
# 2. 4-Stage Progressive Progression & Exit Readiness
# ==============================================================================


def test_list_stage_progress_returns_all_4_stages(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    run = engine.start_playbook("playbook.vendor-risk", tenant_id="tenant-m5")
    stages = tracker.list_stage_progress(run.run_id, tenant_id="tenant-m5")
    assert len(stages) == 4
    for i, sp in enumerate(stages, 1):
        assert sp.stage_number == i
        assert sp.total_milestones >= 1
        assert sp.completed_milestones == 0
        assert sp.completion_ratio == 0.0
        assert not sp.exit_ready


def test_reset_milestones_cleans_records_with_zero_orphans(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    run = engine.start_playbook("playbook.foundations-30d", tenant_id="tenant-m6")
    tracker.record_milestone(
        run_id=run.run_id,
        milestone_id="M1-1",
        tenant_id="tenant-m6",
        notes="First milestone sign-off prior to reset.",
    )
    p_before = tracker.get_stage_progress(run.run_id, 1, tenant_id="tenant-m6")
    assert p_before.completed_milestones >= 1

    # Reset
    tracker.reset_milestones(run.run_id, tenant_id="tenant-m6")
    p_after = tracker.get_stage_progress(run.run_id, 1, tenant_id="tenant-m6")
    assert p_after.completed_milestones == 0


# ==============================================================================
# 3. Multi-Tenant Isolation Tests
# ==============================================================================


def test_tenant_isolation_on_milestones(engine: PlaybookEngine, tracker: MilestoneTracker) -> None:
    run = engine.start_playbook("playbook.ai-assurance", tenant_id="tenant-alpha")

    # Tenant Beta cannot record milestone on Tenant Alpha's run
    with pytest.raises(PlaybookRunNotFoundError):
        tracker.record_milestone(
            run_id=run.run_id,
            milestone_id="M1-1",
            tenant_id="tenant-beta",
            notes="Cross tenant intrusion attempt notes.",
        )

    # Tenant Beta cannot view stage progress of Tenant Alpha's run
    with pytest.raises(PlaybookRunNotFoundError):
        tracker.get_stage_progress(run.run_id, 1, tenant_id="tenant-beta")


# ==============================================================================
# 4. Evaluation Dataset: 10 End-to-End Milestone Lifecycle Test Runs
# ==============================================================================


def test_evaluation_dataset_10_end_to_end_milestone_lifecycle_runs(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    """10 end-to-end milestone lifecycle runs verifying 100% data integrity."""
    playbooks = [
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
    ]

    completed_stages_count = 0

    for idx, pb_id in enumerate(playbooks):
        tenant = f"e2e-tenant-{idx}"
        run = engine.start_playbook(pb_id, tenant_id=tenant)
        tmpl = engine.get_template(pb_id)
        assert tmpl is not None

        # Execute Stage 1 milestones
        stage_1 = tmpl.stages[0]
        for milestone in stage_1.milestones:
            progress = tracker.record_milestone(
                run_id=run.run_id,
                milestone_id=milestone.id,
                tenant_id=tenant,
                evidence_doc_id=f"EVID-{milestone.id}",
                notes=f"Audit evidence recorded for {milestone.title}",
            )

        assert progress.stage_number == 1
        assert progress.completed_milestones == len(stage_1.milestones)
        assert progress.completion_ratio == 1.0
        assert progress.exit_ready
        completed_stages_count += 1

    assert completed_stages_count == 10


# ==============================================================================
# 5. Performance Limit: Milestone Update Execution <= 4.0 ms
# ==============================================================================


def test_milestone_update_execution_latency_under_4ms_p95(
    engine: PlaybookEngine, tracker: MilestoneTracker
) -> None:
    latencies: list[float] = []

    for i in range(50):
        tenant = f"perf-ms-tenant-{i}"
        run = engine.start_playbook("playbook.foundations-30d", tenant_id=tenant)

        t0 = time.perf_counter()
        tracker.record_milestone(
            run_id=run.run_id,
            milestone_id="M1-1",
            tenant_id=tenant,
            notes="Performance testing milestone sign-off duration.",
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

    latencies.sort()
    p95_index = int(0.95 * len(latencies))
    p95_latency = latencies[p95_index]
    assert p95_latency <= 4.0, (
        f"Milestone update p95 latency {p95_latency:.2f}ms exceeded 4.0ms budget"
    )


# ==============================================================================
# 6. REST API Endpoint Integration Tests
# ==============================================================================


def test_api_complete_milestone_returns_stage_progress(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    # Start run
    start_resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.foundations-30d",
            "tenant_id": "tenant-api-ms",
            "assigned_lead": "Architecture Lead",
        },
    )
    assert start_resp.status_code == 200
    run_id = start_resp.json()["run_id"]

    # Record milestone via POST /v1/playbooks/{run_id}/milestones/{milestone_id}
    ms_resp = client.post(
        f"/v1/playbooks/{run_id}/milestones/M1-1?tenant_id=tenant-api-ms",
        headers=api_headers,
        json={
            "milestone_id": "M1-1",
            "evidence_doc_id": "DOC-ARCH-001",
            "notes": "Verified architecture boundary separation.",
        },
    )
    assert ms_resp.status_code == 200
    progress = ms_resp.json()
    assert progress["stage_number"] == 1
    assert progress["completed_milestones"] == 1
    assert progress["total_milestones"] == 2
    assert progress["completion_ratio"] == 0.5
    assert not progress["exit_ready"]


def test_api_get_stage_progress(client: TestClient, api_headers: dict[str, str]) -> None:
    start_resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.ai-assurance",
            "tenant_id": "tenant-api-stage-get",
            "assigned_lead": "AI Officer",
        },
    )
    run_id = start_resp.json()["run_id"]

    resp = client.get(
        f"/v1/playbooks/{run_id}/stages/1/progress?tenant_id=tenant-api-stage-get",
        headers=api_headers,
    )
    assert resp.status_code == 200
    stage_data = resp.json()
    assert stage_data["stage_number"] == 1
    assert "stage_name" in stage_data
    assert stage_data["total_milestones"] >= 1


def test_api_list_playbook_progress(client: TestClient, api_headers: dict[str, str]) -> None:
    start_resp = client.post(
        "/v1/playbooks/start",
        headers=api_headers,
        json={
            "playbook_id": "playbook.vendor-risk",
            "tenant_id": "tenant-api-progress-all",
            "assigned_lead": "Vendor Manager",
        },
    )
    run_id = start_resp.json()["run_id"]

    resp = client.get(
        f"/v1/playbooks/{run_id}/progress?tenant_id=tenant-api-progress-all",
        headers=api_headers,
    )
    assert resp.status_code == 200
    all_stages = resp.json()
    assert isinstance(all_stages, list)
    assert len(all_stages) == 4
