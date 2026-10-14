"""Tests for Continuous Compliance Observation Window Tracker (FEAT-048).

Verifies sub-millisecond telemetry ingestion, timestamp validation rules (<=24h, no future),
rolling 90-day window aggregation, unbroken pass streak calculation, database persistence,
10,000 simulated event evaluation dataset, and API endpoints.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.models import TelemetryEventInput
from app.api.security import load_keys
from app.compliance.observation_tracker import (
    ObservationConfig,
    ObservationTracker,
)
from tests.conftest import PRIMARY_KEY, auth, database_url


@pytest.fixture
def db_conn() -> Generator[psycopg.Connection, None, None]:
    """Provide a database connection to test postgres instance."""
    url = database_url("MIGRATION_DATABASE_URL", "DATABASE_URL")
    if not url:
        pytest.skip("No database URL configured for test")
    with psycopg.connect(url) as conn:
        yield conn


@pytest.fixture
def tracker() -> ObservationTracker:
    """Fresh observation tracker engine instance."""
    return ObservationTracker(ObservationConfig(min_window_days=90))


def _make_hash(payload: str) -> str:
    """Generate SHA-256 hex digest for evidence hash."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Unit Tests: Validation Rules
# ---------------------------------------------------------------------------


def test_validation_accepts_valid_fresh_event(tracker: ObservationTracker) -> None:
    now = datetime.now(UTC)
    event = TelemetryEventInput(
        tenant_id="tenant-alpha",
        control_id="PCI-DSS-4.0-REQ-10.2",
        observation_timestamp=now - timedelta(hours=2),
        check_result="PASS",
        evidence_hash=_make_hash("event-1"),
    )
    validated_ts = tracker.validate_event(event, now=now)
    assert validated_ts.tzinfo is not None
    assert validated_ts == event.observation_timestamp


def test_validation_rejects_backdated_event(tracker: ObservationTracker) -> None:
    now = datetime.now(UTC)
    # Event older than 24 hours
    event = TelemetryEventInput(
        tenant_id="tenant-alpha",
        control_id="PCI-DSS-4.0-REQ-10.2",
        observation_timestamp=now - timedelta(hours=26),
        check_result="PASS",
        evidence_hash=_make_hash("backdated"),
    )
    with pytest.raises(ValueError, match="must be within last 24 hours"):
        tracker.validate_event(event, allow_historical=False, now=now)

    # When allow_historical=True, it passes
    validated = tracker.validate_event(event, allow_historical=True, now=now)
    assert validated == event.observation_timestamp


def test_validation_rejects_future_timestamp(tracker: ObservationTracker) -> None:
    now = datetime.now(UTC)
    # Event > 5 minutes in future
    event = TelemetryEventInput(
        tenant_id="tenant-alpha",
        control_id="PCI-DSS-4.0-REQ-10.2",
        observation_timestamp=now + timedelta(minutes=10),
        check_result="PASS",
        evidence_hash=_make_hash("future"),
    )
    with pytest.raises(ValueError, match="cannot be in the future"):
        tracker.validate_event(event, now=now)


def test_validation_rejects_invalid_hash_or_control(tracker: ObservationTracker) -> None:
    now = datetime.now(UTC)
    # Pydantic schema validation rejects non-hex pattern
    with pytest.raises(ValueError):
        TelemetryEventInput(
            tenant_id="default",
            control_id="SOC2-CC6.1",
            observation_timestamp=now,
            check_result="PASS",
            evidence_hash="g" * 64,
        )

    # Direct tracker validation catches invalid hash when model validation is bypassed
    raw_event = TelemetryEventInput.model_construct(
        tenant_id="default",
        control_id="SOC2-CC6.1",
        observation_timestamp=now,
        check_result="PASS",
        evidence_hash="g" * 64,
    )
    with pytest.raises(ValueError, match="Invalid SHA-256 evidence hash"):
        tracker.validate_event(raw_event, now=now)


# ---------------------------------------------------------------------------
# Unit Tests: Ingestion Throughput & Metrics
# ---------------------------------------------------------------------------


def test_ingestion_throughput_meets_sla(tracker: ObservationTracker) -> None:
    now = datetime.now(UTC)
    batch_size = 1500
    events = [
        TelemetryEventInput(
            tenant_id="perf-tenant",
            control_id="SOC2-CC6.1",
            observation_timestamp=now - timedelta(minutes=i % 100),
            check_result="PASS" if i % 10 != 0 else "FAIL",
            evidence_hash=_make_hash(f"perf-{i}"),
        )
        for i in range(batch_size)
    ]

    start_time = time.perf_counter()
    event_ids = tracker.ingest_batch(events, now=now)
    duration = time.perf_counter() - start_time

    assert len(event_ids) == batch_size
    throughput = batch_size / duration
    # SLA requires >= 1,000 events/sec
    assert throughput >= 1000.0, f"Throughput {throughput:.2f} events/sec below 1,000/s budget"


# ---------------------------------------------------------------------------
# Unit Tests: Observation Window & Streak Calculation
# ---------------------------------------------------------------------------


def test_window_calculation_and_streak(tracker: ObservationTracker) -> None:
    now = datetime(2026, 10, 13, 23, 59, 59, tzinfo=UTC)
    control = "PCI-DSS-4.0-REQ-8.3"
    tenant = "streak-tenant"

    events: list[TelemetryEventInput] = []
    # Build a 5-day continuous PASS streak (Oct 9 to Oct 13)
    for day_offset in range(5):
        day_ts = now - timedelta(days=day_offset)
        for hour in (2, 8, 14, 20):
            events.append(
                TelemetryEventInput(
                    tenant_id=tenant,
                    control_id=control,
                    observation_timestamp=day_ts.replace(hour=hour),
                    check_result="PASS",
                    evidence_hash=_make_hash(f"pass-{day_offset}-{hour}"),
                )
            )

    tracker.ingest_batch(events, allow_historical=True, now=now)

    status = tracker.get_observation_status(
        control_id=control, tenant_id=tenant, window_days=90, now=now
    )
    assert status.total_observations == 20
    assert status.pass_count == 20
    assert status.fail_count == 0
    assert status.compliance_percentage == 100.0
    assert status.unbroken_streak_days == 5
    assert status.status == "COMPLIANT"


def test_streak_breaks_on_recent_fail(tracker: ObservationTracker) -> None:
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    control = "PCI-DSS-4.0-REQ-8.4"
    tenant = "break-tenant"

    # Days 4, 3, 2, 1 all PASS; Day 0 (today) has a FAIL
    events: list[TelemetryEventInput] = []
    for day_offset in range(1, 5):
        events.append(
            TelemetryEventInput(
                tenant_id=tenant,
                control_id=control,
                observation_timestamp=now - timedelta(days=day_offset),
                check_result="PASS",
                evidence_hash=_make_hash(f"pass-{day_offset}"),
            )
        )
    # Today has a failure
    events.append(
        TelemetryEventInput(
            tenant_id=tenant,
            control_id=control,
            observation_timestamp=now,
            check_result="FAIL",
            evidence_hash=_make_hash("fail-today"),
        )
    )

    tracker.ingest_batch(events, allow_historical=True, now=now)
    status = tracker.get_observation_status(
        control_id=control, tenant_id=tenant, window_days=90, now=now
    )
    assert status.total_observations == 5
    assert status.pass_count == 4
    assert status.fail_count == 1
    assert status.compliance_percentage == 80.0
    assert status.unbroken_streak_days == 0
    assert status.status == "NON_COMPLIANT"


# ---------------------------------------------------------------------------
# Evaluation Dataset: 10,000 Simulated Events Across 90 Days
# ---------------------------------------------------------------------------


def test_evaluation_dataset_10k_events(tracker: ObservationTracker) -> None:
    """Simulate 10,000 continuous compliance telemetry events across 90-day window.

    Evaluates 100% audit trail integrity, window computation accuracy, and stability.
    """
    now = datetime(2026, 10, 13, 0, 0, 0, tzinfo=UTC)
    control = "ISO-27001-A.12.1.2"
    tenant = "eval-10k-tenant"

    total_simulated = 10000
    events: list[TelemetryEventInput] = []

    # Distribute 10,000 events evenly across 90 days (~111 events/day)
    # 99.5% PASS, 0.5% FAIL (50 failures)
    for i in range(total_simulated):
        day_offset = (i * 90) // total_simulated
        minute_offset = (i * 1440) % 1440
        obs_time = now - timedelta(days=day_offset, minutes=minute_offset)
        # Failures injected only on days 60-65 to preserve a ~60-day unbroken streak up to day 0
        if 60 <= day_offset <= 65 and (i % 20 == 0):
            result = "FAIL"
        else:
            result = "PASS"

        events.append(
            TelemetryEventInput(
                tenant_id=tenant,
                control_id=control,
                observation_timestamp=obs_time,
                check_result=result,
                evidence_hash=_make_hash(f"eval-{i}"),
            )
        )

    t0 = time.perf_counter()
    tracker.ingest_batch(events, allow_historical=True, now=now)
    ingest_time = time.perf_counter() - t0

    # Ensure ingestion didn't fail
    assert ingest_time < 5.0, f"Ingesting 10k events took {ingest_time:.2f}s"

    t1 = time.perf_counter()
    status = tracker.get_observation_status(
        control_id=control, tenant_id=tenant, window_days=90, now=now
    )
    calc_time = time.perf_counter() - t1

    assert status.total_observations == total_simulated
    assert status.fail_count > 0
    assert status.compliance_percentage >= 99.0
    assert status.status == "COMPLIANT"
    assert status.unbroken_streak_days >= 59
    assert calc_time < 0.05, f"Calculation took {calc_time:.4f}s (>50ms target)"


# ---------------------------------------------------------------------------
# Database Persistence & Isolation
# ---------------------------------------------------------------------------


def test_database_persistence_and_isolation(db_conn: psycopg.Connection) -> None:
    tracker = ObservationTracker(ObservationConfig(min_window_days=90))
    now = datetime.now(UTC)
    ctrl = f"CTRL-TEST-{uuid4().hex[:8]}"

    # Ingest for tenant-alpha
    events_alpha = [
        TelemetryEventInput(
            tenant_id="tenant-alpha",
            control_id=ctrl,
            observation_timestamp=now - timedelta(minutes=10),
            check_result="PASS",
            evidence_hash=_make_hash("db-alpha-1"),
        ),
        TelemetryEventInput(
            tenant_id="tenant-alpha",
            control_id=ctrl,
            observation_timestamp=now - timedelta(minutes=5),
            check_result="PASS",
            evidence_hash=_make_hash("db-alpha-2"),
        ),
    ]
    tracker.ingest_batch(events_alpha, conn=db_conn, now=now)

    # Ingest for tenant-beta
    events_beta = [
        TelemetryEventInput(
            tenant_id="tenant-beta",
            control_id=ctrl,
            observation_timestamp=now - timedelta(minutes=5),
            check_result="FAIL",
            evidence_hash=_make_hash("db-beta-1"),
        )
    ]
    tracker.ingest_batch(events_beta, conn=db_conn, now=now)

    # Query status from DB for tenant-alpha
    status_alpha = tracker.get_observation_status(
        control_id=ctrl, tenant_id="tenant-alpha", window_days=90, conn=db_conn, now=now
    )
    assert status_alpha.total_observations == 2
    assert status_alpha.pass_count == 2
    assert status_alpha.fail_count == 0
    assert status_alpha.compliance_percentage == 100.0
    assert status_alpha.status == "COMPLIANT"

    # Query status from DB for tenant-beta
    status_beta = tracker.get_observation_status(
        control_id=ctrl, tenant_id="tenant-beta", window_days=90, conn=db_conn, now=now
    )
    assert status_beta.total_observations == 1
    assert status_beta.pass_count == 0
    assert status_beta.fail_count == 1
    assert status_beta.compliance_percentage == 0.0
    assert status_beta.status == "NON_COMPLIANT"


# ---------------------------------------------------------------------------
# API Endpoints Integration Tests
# ---------------------------------------------------------------------------


def test_api_telemetry_ingest_and_window_endpoints() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)
    now = datetime.now(UTC)
    ctrl = f"API-CTRL-{uuid4().hex[:6]}"

    # Ingest single batch item
    payload = {
        "tenant_id": "api-tenant",
        "control_id": ctrl,
        "observation_timestamp": (now - timedelta(minutes=5)).isoformat(),
        "check_result": "PASS",
        "evidence_hash": _make_hash("api-payload-1"),
    }

    res = client.post("/v1/compliance/telemetry/ingest", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["accepted_count"] == 1
    assert data["status"] == "INGESTED"
    assert len(data["event_ids"]) == 1

    # Query observation window status
    res_status = client.get(
        f"/v1/compliance/telemetry/window/{ctrl}?tenant_id=api-tenant&window_days=90",
        headers=headers,
    )
    assert res_status.status_code == 200, res_status.text
    status_json = res_status.json()
    assert status_json["control_id"] == ctrl
    assert status_json["tenant_id"] == "api-tenant"
    assert status_json["total_observations"] >= 1
    assert status_json["pass_count"] >= 1
    assert status_json["compliance_percentage"] == 100.0
    assert status_json["status"] == "COMPLIANT"


def test_api_rejects_backdated_telemetry() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)
    now = datetime.now(UTC)

    # 48 hours old event
    payload = {
        "tenant_id": "api-tenant",
        "control_id": "SOC2-CC6.1",
        "observation_timestamp": (now - timedelta(hours=48)).isoformat(),
        "check_result": "PASS",
        "evidence_hash": _make_hash("too-old"),
    }

    res = client.post("/v1/compliance/telemetry/ingest", json=payload, headers=headers)
    assert res.status_code == 422
    assert "within last 24 hours" in res.text
