"""Tests for Prescriptive Remediation Engine (FEAT-034).

Verifies mapping of detected antipatterns and deprecations to sanctioned
alternative practices ("Instead-Of"), actionable checklist steps, latency constraints,
and API endpoints.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.antipattern_scanner import AntipatternFinding
from app.compliance.remediation_engine import (
    get_default_remediation_engine,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_catalog_completeness():
    """Verify that all 30 antipatterns and 8 deprecations (38 total plans) are loaded."""
    engine = get_default_remediation_engine()
    stats = engine.get_stats()

    assert stats["total_antipattern_remediations"] == 30
    assert stats["total_deprecation_remediations"] == 8
    assert stats["total_remediation_plans"] == 38
    assert stats["total_recommended_practice_mappings"] == 116

    catalog = engine.list_catalog()
    assert len(catalog) == 38

    for plan in catalog:
        assert plan.flaw_id
        assert plan.flaw_type in {"antipattern", "deprecation"}
        assert plan.identified_flaw
        assert plan.consequence_or_reason
        assert len(plan.recommended_practices) >= 1
        for rec in plan.recommended_practices:
            assert rec.name
            assert rec.term_id
            assert rec.definition
            assert rec.value_justification
            assert rec.tier in {1, 2, 3}
            assert len(rec.implementation_steps) >= 1


def test_lookup_by_antipattern_id_and_practice():
    """Verify looking up remediation plans by rule ID and practice title."""
    engine = get_default_remediation_engine()

    # Lookup by ID
    t0 = time.perf_counter()
    plan_by_id = engine.get_remediation_for_antipattern("ap-line-coverage")
    dur_ms = (time.perf_counter() - t0) * 1000.0

    assert plan_by_id is not None
    assert plan_by_id.flaw_id == "ap-line-coverage"
    assert dur_ms < 0.5  # Must meet <= 0.5ms SLA
    rec_names = [r.name for r in plan_by_id.recommended_practices]
    assert "Diff / Patch Coverage" in rec_names
    assert "Mutation Score / Mutation Adequacy" in rec_names
    assert "Coverage Ratcheting" in rec_names

    # Lookup by practice name (case-insensitive)
    plan_by_name = engine.get_remediation_for_antipattern("Statement Coverage")
    assert plan_by_name is not None
    assert plan_by_name.flaw_id == "ap-line-coverage"


def test_lookup_by_deprecation_id_and_subject():
    """Verify looking up deprecation replacements by subject and ID."""
    engine = get_default_remediation_engine()

    plan_by_subject = engine.get_remediation_for_deprecation("DREAD")
    assert plan_by_subject is not None
    assert plan_by_subject.flaw_type == "deprecation"
    rec_names = [r.name for r in plan_by_subject.recommended_practices]
    assert "Threat Modeling (STRIDE)" in rec_names
    assert "Attack Tree Analysis" in rec_names
    assert "CVSS (Common Vulnerability Scoring System)" in rec_names

    plan_by_id = engine.get_remediation_by_flaw_id("dep-dread")
    assert plan_by_id is not None
    assert plan_by_id.flaw_id == "dep-dread"


def test_implementation_steps_toggle():
    """Verify include_steps toggle generates or omits implementation checklist."""
    engine = get_default_remediation_engine()

    plan_with_steps = engine.get_remediation_for_antipattern(
        "ap-mock-everything", include_steps=True
    )
    assert plan_with_steps is not None
    assert all(len(r.implementation_steps) > 0 for r in plan_with_steps.recommended_practices)

    plan_without_steps = engine.get_remediation_for_antipattern(
        "ap-mock-everything", include_steps=False
    )
    assert plan_without_steps is not None
    assert all(len(r.implementation_steps) == 0 for r in plan_without_steps.recommended_practices)


def test_finding_conversion_and_fallback():
    """Verify converting an AntipatternFinding object into a full remediation plan with fallback."""
    engine = get_default_remediation_engine()

    finding = AntipatternFinding(
        rule_id="ap-chaos-no-hypothesis",
        practice="Chaos Engineering",
        antipattern="Breaking things in production without a steady-state hypothesis.",
        consequence="Outages with no learning.",
        instead=["Steady-State Hypothesis", "Automated Rollback Verification"],
        severity="CRITICAL",
        domain_category="reliability",
        matched_snippet="Breaking things in production without a steady-state hypothesis.",
    )

    plan = engine.generate_remediation_for_finding(finding)
    assert plan.flaw_id == "ap-chaos-no-hypothesis"
    assert len(plan.recommended_practices) >= 2

    # Unmapped flaw fallback
    unmapped_finding = {
        "rule_id": "ap-custom-unmapped",
        "practice": "Custom Practice",
        "instead": ["Alternative Practice One"],
        "severity": "HIGH",
    }
    fallback_plan = engine.generate_remediation_for_finding(unmapped_finding)
    assert fallback_plan.flaw_id == "ap-custom-unmapped"
    assert len(fallback_plan.recommended_practices) == 1
    assert fallback_plan.recommended_practices[0].name == "Alternative Practice One"


def test_remediation_report_batch():
    """Verify batch remediation report formulation across multiple findings."""
    engine = get_default_remediation_engine()

    findings = [
        {"rule_id": "ap-line-coverage"},
        {"rule_id": "ap-prompt-injection-direct-only"},
        {"rule_id": "dep-dread"},
        {"rule_id": "ap-error-budget-ignored"},
    ]

    report = engine.generate_remediation_report(findings)
    assert report.total_findings == 4
    assert report.remediated_findings == 4
    assert len(report.plans) == 4
    assert len(report.unique_recommended_practices) >= 8


def test_catalog_filtering():
    """Verify filtering the remediation catalog by flaw type and tier."""
    engine = get_default_remediation_engine()

    ap_plans = engine.list_catalog(flaw_type="antipattern")
    assert len(ap_plans) == 30

    dep_plans = engine.list_catalog(flaw_type="deprecation")
    assert len(dep_plans) == 8

    tier1_plans = engine.list_catalog(tier=1)
    assert len(tier1_plans) > 0
    for p in tier1_plans:
        assert all(r.tier == 1 for r in p.recommended_practices)


def test_api_remediation_plan_endpoint(client: TestClient):
    """Verify POST /v1/compliance/remediation/plan endpoint."""
    payload = {
        "flaw_id": "ap-mock-everything",
        "include_implementation_steps": True,
    }
    res = client.post("/v1/compliance/remediation/plan", json=payload, headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["flaw_id"] == "ap-mock-everything"
    assert len(data["recommended_practices"]) >= 1
    assert data["lookup_latency_ms"] < 20.0

    # By practice name
    payload2 = {"practice_or_subject": "DREAD"}
    res2 = client.post("/v1/compliance/remediation/plan", json=payload2, headers=auth(PRIMARY_KEY))
    assert res2.status_code == 200
    assert res2.json()["flaw_type"] == "deprecation"


def test_api_remediation_batch_endpoint(client: TestClient):
    """Verify POST /v1/compliance/remediation/batch endpoint."""
    payload = {
        "flaw_ids": ["ap-line-coverage", "dep-dread", "ap-error-budget-ignored"],
        "include_implementation_steps": True,
    }
    res = client.post("/v1/compliance/remediation/batch", json=payload, headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["total_findings"] == 3
    assert data["remediated_findings"] == 3
    assert len(data["plans"]) == 3
    assert len(data["unique_recommended_practices"]) >= 6


def test_api_remediation_catalog_endpoint(client: TestClient):
    """Verify GET /v1/compliance/remediation/catalog endpoint."""
    res = client.get("/v1/compliance/remediation/catalog", headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["total_plans"] == 38
    assert data["total_practices_mapped"] == 116
    assert len(data["plans"]) == 38

    # Filtered by deprecation
    res_dep = client.get(
        "/v1/compliance/remediation/catalog?flaw_type=deprecation",
        headers=auth(PRIMARY_KEY),
    )
    assert res_dep.status_code == 200
    assert res_dep.json()["total_plans"] == 8
