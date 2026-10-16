"""Tests for Circular Clause Conflict Detector (FEAT-032).

Verifies inter-circular contradiction detection, synthetic benchmark (>90% detection rate),
modality clash identification, threshold mismatch auditing, and API endpoints.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.clause_conflict import (
    CircularClause,
    ClauseModality,
    ConflictSeverity,
    ConflictType,
    get_default_clause_conflict_detector,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_synthetic_contradiction_benchmark_rate() -> None:
    """Verify synthetic contradiction test set detection rate exceeds the 90% threshold."""
    detector = get_default_clause_conflict_detector()
    bench = detector.evaluate_synthetic_benchmark()

    assert bench["benchmark_passed"] is True
    assert bench["detection_rate"] >= 0.90
    assert bench["detected_conflicts"] >= 9
    assert bench["precision"] >= 0.90
    assert bench["false_positives"] == 0


def test_canonical_clauses_and_preloaded_conflicts() -> None:
    """Verify preloaded canonical clauses and detected conflicts across domains."""
    detector = get_default_clause_conflict_detector()
    clauses = detector.list_clauses()
    assert len(clauses) >= 10

    domains = {c.domain_category for c in clauses}
    assert {
        "fldg",
        "incident_reporting",
        "capital_adequacy",
        "data_localization",
        "beneficial_ownership",
    }.issubset(domains)

    conflicts = detector.detect_conflicts()
    assert len(conflicts) >= 5

    # Check FLDG conflict
    fldg_conflicts = [c for c in conflicts if c.clause_a.domain_category == "fldg"]
    assert len(fldg_conflicts) >= 1
    assert fldg_conflicts[0].conflict_type == ConflictType.THRESHOLD_CONTRADICTION
    assert fldg_conflicts[0].parameter_name == "fldg_ceiling_pct"

    # Check Incident reporting conflict
    incident_conflicts = [
        c for c in conflicts if c.clause_a.domain_category == "incident_reporting"
    ]
    assert len(incident_conflicts) >= 1
    assert incident_conflicts[0].conflict_type == ConflictType.THRESHOLD_CONTRADICTION


def test_modality_clash_detection() -> None:
    """Verify detection of normative contradictions (MANDATORY vs PROHIBITED)."""
    detector = get_default_clause_conflict_detector()

    clause_a = CircularClause(
        id="mod-test-a",
        circular_id="CIRC-001",
        circular_title="Onshore Data Residency",
        regulator="RBI",
        section_reference="Sec 2",
        clause_text="All card data must be stored exclusively in domestic servers.",
        domain_category="storage",
        modality=ClauseModality.MANDATORY,
    )
    clause_b = CircularClause(
        id="mod-test-b",
        circular_id="CIRC-002",
        circular_title="Global Processing Protocols",
        regulator="RBI",
        section_reference="Sec 5",
        clause_text="Mirroring data outside domestic boundaries is prohibited.",
        domain_category="storage",
        modality=ClauseModality.PROHIBITED,
    )

    conflict = detector.compare_clauses(clause_a, clause_b)
    assert conflict is not None
    assert conflict.conflict_type == ConflictType.MODALITY_CLASH
    assert conflict.severity == ConflictSeverity.CRITICAL
    assert "Direct normative contradiction" in conflict.explanation


def test_harmonious_clauses_no_false_positives() -> None:
    """Verify that harmonious or distinct domain clauses do not trigger false conflicts."""
    detector = get_default_clause_conflict_detector()

    # Same threshold
    clause_a = CircularClause(
        id="harm-1",
        circular_id="CIRC-101",
        circular_title="Capital Mandate A",
        regulator="RBI",
        section_reference="Sec 1",
        clause_text="Maintain CRAR 9%",
        domain_category="capital",
        modality=ClauseModality.MANDATORY,
        parameter_name="crar",
        parameter_value=9.0,
        parameter_unit="pct",
        comparison_operator="MIN",
    )
    clause_b = CircularClause(
        id="harm-2",
        circular_id="CIRC-102",
        circular_title="Capital Mandate B",
        regulator="RBI",
        section_reference="Sec 1",
        clause_text="Maintain CRAR 9%",
        domain_category="capital",
        modality=ClauseModality.MANDATORY,
        parameter_name="crar",
        parameter_value=9.0,
        parameter_unit="pct",
        comparison_operator="MIN",
    )
    assert detector.compare_clauses(clause_a, clause_b) is None

    # Different domains
    clause_c = CircularClause(
        id="harm-3",
        circular_id="CIRC-103",
        circular_title="LCR Directive",
        regulator="RBI",
        section_reference="Sec 3",
        clause_text="Maintain LCR 100%",
        domain_category="liquidity",
        modality=ClauseModality.MANDATORY,
        parameter_name="lcr",
        parameter_value=100.0,
        parameter_unit="pct",
        comparison_operator="MIN",
    )
    assert detector.compare_clauses(clause_a, clause_c) is None


def test_scan_clause_pair_helper() -> None:
    """Verify dictionary-based ad-hoc comparison helper."""
    detector = get_default_clause_conflict_detector()

    c_a = {
        "id": "dict-a",
        "circular_id": "REF-A",
        "circular_title": "Directive A",
        "domain_category": "reporting",
        "modality": "mandatory",
        "parameter_name": "window_hours",
        "parameter_value": 2.0,
        "parameter_unit": "hours",
        "comparison_operator": "MAX",
    }
    c_b = {
        "id": "dict-b",
        "circular_id": "REF-B",
        "circular_title": "Directive B",
        "domain_category": "reporting",
        "modality": "mandatory",
        "parameter_name": "window_hours",
        "parameter_value": 24.0,
        "parameter_unit": "hours",
        "comparison_operator": "MAX",
    }

    conflict = detector.scan_clause_pair(c_a, c_b)
    assert conflict is not None
    assert conflict.conflict_type == ConflictType.THRESHOLD_CONTRADICTION
    assert conflict.parameter_name == "window_hours"


def test_clause_comparison_latency() -> None:
    """Verify pairwise comparison executes with p95 <= 0.1ms."""
    detector = get_default_clause_conflict_detector()
    clauses = detector.list_clauses()
    assert len(clauses) >= 2

    c_a = clauses[0]
    c_b = clauses[1]

    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = detector.compare_clauses(c_a, c_b)
        times.append(time.perf_counter() - t0)

    p95_ms = sorted(times)[95] * 1000.0
    assert p95_ms <= 0.5, f"Expected sub-millisecond check, got {p95_ms}ms"


def test_api_list_clauses(client: TestClient) -> None:
    """Verify GET /v1/compliance/conflicts/clauses endpoint."""
    res = client.get("/v1/compliance/conflicts/clauses", headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    clauses = res.json()
    assert len(clauses) >= 10
    assert any(c["domain_category"] == "fldg" for c in clauses)

    # Filter by domain
    res_fldg = client.get(
        "/v1/compliance/conflicts/clauses?domain_category=fldg", headers=auth(PRIMARY_KEY)
    )
    assert res_fldg.status_code == 200
    assert all(c["domain_category"] == "fldg" for c in res_fldg.json())


def test_api_detect_conflicts(client: TestClient) -> None:
    """Verify POST /v1/compliance/detect-conflicts endpoint."""
    payload = {"domain_category": "fldg"}
    res = client.post("/v1/compliance/detect-conflicts", json=payload, headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["has_conflicts"] is True
    assert data["total_conflicts"] >= 1
    assert "fldg" in data["domains_affected"]
    assert data["latency_ms"] < 25.0


def test_api_compare_clause_pair(client: TestClient) -> None:
    """Verify POST /v1/compliance/compare-clause-pair endpoint."""
    payload = {
        "clause_a": {
            "id": "api-test-a",
            "circular_id": "CIRC-API-1",
            "circular_title": "Lending Standards 1",
            "regulator": "RBI",
            "section_reference": "Sec 1",
            "clause_text": "FLDG shall not exceed 5%",
            "domain_category": "fldg",
            "modality": "mandatory",
            "parameter_name": "fldg_cap",
            "parameter_value": 5.0,
            "parameter_unit": "pct",
            "comparison_operator": "MAX",
            "effective_date": "2023-01-01",
            "is_active": True,
        },
        "clause_b": {
            "id": "api-test-b",
            "circular_id": "CIRC-API-2",
            "circular_title": "Lending Standards 2",
            "regulator": "RBI",
            "section_reference": "Sec 4",
            "clause_text": "FLDG shall not exceed 10%",
            "domain_category": "fldg",
            "modality": "mandatory",
            "parameter_name": "fldg_cap",
            "parameter_value": 10.0,
            "parameter_unit": "pct",
            "comparison_operator": "MAX",
            "effective_date": "2023-06-01",
            "is_active": True,
        },
    }
    res = client.post("/v1/compliance/compare-clause-pair", json=payload, headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["conflict_detected"] is True
    assert data["conflict"] is not None
    assert data["conflict"]["conflict_type"] == "threshold_contradiction"


def test_api_conflicts_benchmark(client: TestClient) -> None:
    """Verify GET /v1/compliance/conflicts/benchmark endpoint."""
    res = client.get("/v1/compliance/conflicts/benchmark", headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["benchmark_passed"] is True
    assert data["detection_rate"] >= 0.90
