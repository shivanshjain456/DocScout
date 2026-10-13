"""Integration and validation tests for Multi-Jurisdiction Compliance Harmonizer (FEAT-043).

Validates:
1. Benchmark comparative topics across RBI, EU GDPR, EU DORA, US FedRAMP, and US NIST.
2. Accurate identification of RBI's strict 6-hour incident reporting window vs. GDPR's 72-hour window.
3. Deterministic delta classification (STRICTER_A, EQUIVALENT, STRICTER_B) and bidirectional symmetry.
4. Absolute domestic payment data localization under DPSS.CO.OD No. 2785/06.08.005/2017-18.
5. HTTP REST API endpoint POST /v1/compliance/harmonize with input validation and RFC-7807/422 handling.
6. Prometheus counter docscout_harmonizations_performed_total incrementing.
7. Latency SLA <= 20.0ms p95.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import HARMONIZATIONS_PERFORMED_TOTAL
from app.api.security import load_keys
from app.compliance.harmonizer import (
    ComplianceHarmonizer,
    get_default_compliance_harmonizer,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


@pytest.fixture
def harmonizer() -> ComplianceHarmonizer:
    return get_default_compliance_harmonizer()


def test_harmonizer_catalogs_10_major_benchmark_topics(harmonizer: ComplianceHarmonizer) -> None:
    """Verify engine catalogs 10 distinct multi-jurisdiction benchmark compliance topics."""
    assert harmonizer.count() >= 10
    j_catalog = harmonizer.list_supported_jurisdictions()
    assert "IN_RBI" in j_catalog
    assert "EU_GDPR" in j_catalog
    assert "EU_DORA" in j_catalog
    assert "US_NIST" in j_catalog
    assert "US_FEDRAMP" in j_catalog
    assert "GLOBAL_ISO" in j_catalog


def test_rbi_incident_reporting_stricter_than_gdpr(harmonizer: ComplianceHarmonizer) -> None:
    """Acceptance criterion: Accurately highlights RBI's strict 6-hour reporting window vs GDPR's 72 hours."""
    res = harmonizer.harmonize(
        topic="cyber_incident_reporting",
        jurisdiction_a="IN_RBI",
        jurisdiction_b="EU_GDPR",
    )
    assert res["delta_classification"] == "STRICTER_A"
    assert "6" in res["comparative_analysis"] and "72" in res["comparative_analysis"]
    assert any("6-hour" in m or "6 hour" in m for m in res["localized_mandates"])
    assert any("RBI" in c for c in res["statutory_citations"])
    assert any("GDPR" in c or "2016/679" in c for c in res["statutory_citations"])
    assert res["confidence_score"] >= 0.95


def test_reverse_jurisdiction_inversion(harmonizer: ComplianceHarmonizer) -> None:
    """Verify bidirectional symmetry when jurisdictions are inverted (STRICTER_A -> STRICTER_B)."""
    res_inv = harmonizer.harmonize(
        topic="cyber_incident_reporting",
        jurisdiction_a="EU_GDPR",
        jurisdiction_b="IN_RBI",
    )
    assert res_inv["delta_classification"] == "STRICTER_B"
    assert "6" in res_inv["comparative_analysis"] and "72" in res_inv["comparative_analysis"]


def test_payment_data_localization_stricter_than_gdpr(harmonizer: ComplianceHarmonizer) -> None:
    """Verify RBI payment data localization imposes strict territorial confinement over GDPR transfer rules."""
    res = harmonizer.harmonize(
        topic="data_localization_payments",
        jurisdiction_a="IN_RBI",
        jurisdiction_b="EU_GDPR",
    )
    assert res["delta_classification"] == "STRICTER_A"
    assert any("India" in m or "domestic" in m.lower() for m in res["localized_mandates"])
    assert any("2785" in c for c in res["statutory_citations"])


def test_encryption_algorithm_equivalent(harmonizer: ComplianceHarmonizer) -> None:
    """Verify cryptographic standard across RBI and US NIST classifies as EQUIVALENT."""
    res = harmonizer.harmonize(
        topic="encryption_algorithm_standard",
        jurisdiction_a="IN_RBI",
        jurisdiction_b="US_NIST",
    )
    assert res["delta_classification"] == "EQUIVALENT"
    assert any("AES-256" in m for m in res["localized_mandates"])


def test_software_bill_of_materials_fedramp_stricter(harmonizer: ComplianceHarmonizer) -> None:
    """Verify US FedRAMP / EO 14028 imposes stricter machine-readable SBOM requirements than RBI guidelines."""
    res = harmonizer.harmonize(
        topic="software_bill_of_materials",
        jurisdiction_a="IN_RBI",
        jurisdiction_b="US_FEDRAMP",
    )
    assert res["delta_classification"] == "STRICTER_B"
    assert any("SBOM" in m or "FedRAMP" in m for m in res["localized_mandates"])


def test_disaster_recovery_rto_rpo_stricter_than_iso(harmonizer: ComplianceHarmonizer) -> None:
    """Verify RBI quantitative RTO <= 2h and RPO <= 15m is stricter than ISO 27001 / ISO 22301 guidance."""
    res = harmonizer.harmonize(
        topic="disaster_recovery_rto_rpo",
        jurisdiction_a="IN_RBI",
        jurisdiction_b="GLOBAL_ISO",
    )
    assert res["delta_classification"] == "STRICTER_A"
    assert any("2 Hours" in m or "2h" in m.lower() for m in res["localized_mandates"])
    assert any("15 Minutes" in m or "15m" in m.lower() for m in res["localized_mandates"])


def test_api_harmonize_endpoint_success(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify HTTP POST /v1/compliance/harmonize executes successfully."""
    payload = {
        "topic": "cyber_incident_reporting",
        "jurisdiction_a": "IN_RBI",
        "jurisdiction_b": "EU_GDPR",
    }
    resp = test_client.post("/v1/compliance/harmonize", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic"] == "cyber_incident_reporting"
    assert data["jurisdiction_a"] == "IN_RBI"
    assert data["jurisdiction_b"] == "EU_GDPR"
    assert data["delta_classification"] == "STRICTER_A"
    assert len(data["localized_mandates"]) >= 2
    assert len(data["statutory_citations"]) >= 2
    assert data["confidence_score"] >= 0.95
    assert data["latency_ms"] >= 0.0


def test_api_harmonize_endpoint_unknown_jurisdiction_422(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify HTTP POST /v1/compliance/harmonize rejects unsupported jurisdictions with 422."""
    payload = {
        "topic": "cyber_incident_reporting",
        "jurisdiction_a": "UNKNOWN_JURISDICTION_XYZ",
        "jurisdiction_b": "EU_GDPR",
    }
    resp = test_client.post("/v1/compliance/harmonize", json=payload, headers=auth_headers)
    assert resp.status_code == 422
    assert "Supported jurisdictions" in resp.json()["detail"]


def test_api_harmonize_metrics(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify Prometheus counter increments on harmonization call."""
    payload = {
        "topic": "privileged_access_monitoring",
        "jurisdiction_a": "IN_RBI",
        "jurisdiction_b": "US_NIST",
    }
    delta = "STRICTER_A"
    topic = "privileged_access_monitoring"
    before = HARMONIZATIONS_PERFORMED_TOTAL.labels(
        delta_classification=delta, topic=topic
    )._value.get()

    resp = test_client.post("/v1/compliance/harmonize", json=payload, headers=auth_headers)
    assert resp.status_code == 200

    after = HARMONIZATIONS_PERFORMED_TOTAL.labels(
        delta_classification=delta, topic=topic
    )._value.get()
    assert after == before + 1


def test_harmonizer_latency_sla(harmonizer: ComplianceHarmonizer) -> None:
    """Performance SLA: Comparative analysis latency <= 20.0ms p95."""
    durations_ms: list[float] = []

    # Benchmark 200 calls
    for _ in range(200):
        t0 = time.perf_counter()
        res = harmonizer.harmonize(
            topic="cyber_incident_reporting",
            jurisdiction_a="IN_RBI",
            jurisdiction_b="EU_GDPR",
        )
        dt = (time.perf_counter() - t0) * 1000.0
        durations_ms.append(dt)
        assert res["delta_classification"] == "STRICTER_A"

    durations_ms.sort()
    p95 = durations_ms[int(len(durations_ms) * 0.95)]
    assert p95 <= 20.0, f"p95 latency {p95:.3f}ms exceeded 20.0ms SLA"
