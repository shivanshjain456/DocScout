"""Tests for Statutory Threshold & Boundary Validator (FEAT-023).

Verifies boundary rules across RBI Master Directions, Basel III, ISO/IEC 21031,
and SRE standards. Tests 70+ boundary scenarios (boundary - 1, boundary, boundary + 1),
entity-type alias resolution, batch evaluations, tolerance buffers, and FastAPI endpoints.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from starlette.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.boundary_validator import (
    StatutoryBoundaryValidator,
    UnknownRatioError,
    get_default_boundary_validator,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def validator() -> StatutoryBoundaryValidator:
    """Fixture providing default boundary validator instance."""
    return get_default_boundary_validator()


# ---------------------------------------------------------------------------
# Catalog & Rule Registration Tests
# ---------------------------------------------------------------------------


def test_catalog_contains_at_least_35_statutory_rules(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify that catalog meets or exceeds the required 35 statutory rules."""
    assert validator.total_rules >= 35
    rules = validator.list_boundaries()
    assert len(rules) >= 35

    regulators = {r.regulator for r in rules}
    assert "RBI" in regulators
    assert "GSF" in regulators

    categories = {r.category for r in rules}
    assert "capital_adequacy" in categories
    assert "liquidity" in categories
    assert "asset_quality" in categories
    assert "leverage" in categories
    assert "priority_sector" in categories


# ---------------------------------------------------------------------------
# Boundary Condition Test Vectors (boundary - 1, boundary, boundary + 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (13.5, "BREACH"),
        (14.9, "BREACH"),
        (14.9999, "BREACH"),
        (15.0, "WARNING"),  # Exact threshold: inside warning buffer [15.0, 15.75)
        (15.5, "WARNING"),  # Inside 5% buffer
        (15.749, "WARNING"),
        (15.75, "COMPLIANT"),  # At or above 5% buffer
        (16.0, "COMPLIANT"),
        (20.0, "COMPLIANT"),
    ],
)
def test_crar_nbfc_si_boundary_conditions(
    validator: StatutoryBoundaryValidator,
    value: float,
    expected_status: str,
) -> None:
    """Verify NBFC-SI CRAR >= 15% boundary transitions."""
    finding = validator.validate_ratio("CRAR_NBFC_SI", value, tolerance_percentage=0.05)
    assert finding.status == expected_status
    assert finding.threshold_value == 15.0
    assert finding.operator == ">="
    assert "RBI Master Direction" in finding.circular_citation


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (7.5, "BREACH"),
        (8.9, "BREACH"),
        (9.0, "WARNING"),  # Threshold 9.0%, warning buffer [9.0, 9.45)
        (9.2, "WARNING"),
        (9.449, "WARNING"),
        (9.45, "COMPLIANT"),
        (10.5, "COMPLIANT"),
        (14.0, "COMPLIANT"),
    ],
)
def test_crar_commercial_bank_boundary_conditions(
    validator: StatutoryBoundaryValidator,
    value: float,
    expected_status: str,
) -> None:
    """Verify Commercial Bank CRAR >= 9% boundary transitions."""
    finding = validator.validate_ratio("CRAR_COMMERCIAL_BANK", value, tolerance_percentage=0.05)
    assert finding.status == expected_status
    assert finding.threshold_value == 9.0
    assert "Basel III Capital Regulations" in finding.circular_citation


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (90.0, "BREACH"),
        (99.9, "BREACH"),
        (100.0, "WARNING"),  # Threshold 100.0%, warning buffer [100.0, 105.0)
        (102.5, "WARNING"),
        (104.99, "WARNING"),
        (105.0, "COMPLIANT"),
        (115.0, "COMPLIANT"),
    ],
)
def test_lcr_boundary_conditions(
    validator: StatutoryBoundaryValidator,
    value: float,
    expected_status: str,
) -> None:
    """Verify Liquidity Coverage Ratio (LCR) >= 100% boundary transitions."""
    finding = validator.validate_ratio("LCR_COMMERCIAL_BANK", value, tolerance_percentage=0.05)
    assert finding.status == expected_status
    assert finding.threshold_value == 100.0
    assert finding.unit == "percent"
    assert "Liquidity Coverage Ratio" in finding.circular_citation


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (8.0, "BREACH"),  # Ceiling 6.0%: greater than 6.0 is BREACH
        (6.5, "BREACH"),
        (6.01, "BREACH"),
        (6.00, "WARNING"),  # At ceiling: warning range (5.70, 6.00]
        (5.85, "WARNING"),  # Within 5% buffer below ceiling
        (5.701, "WARNING"),
        (5.70, "COMPLIANT"),  # Safely below ceiling and buffer
        (4.5, "COMPLIANT"),
        (2.0, "COMPLIANT"),
    ],
)
def test_net_npa_pca_ceiling_boundary_conditions(
    validator: StatutoryBoundaryValidator,
    value: float,
    expected_status: str,
) -> None:
    """Verify Net NPA PCA Risk Threshold 1 <= 6.0% ceiling transitions."""
    finding = validator.validate_ratio("NET_NPA_PCA_THRESHOLD_1", value, tolerance_percentage=0.05)
    assert finding.status == expected_status
    assert finding.threshold_value == 6.0
    assert finding.operator == "<="
    assert "Prompt Corrective Action" in finding.circular_citation


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (20.0, "BREACH"),  # Ceiling 14.4: greater than 14.4 is BREACH
        (14.5, "BREACH"),
        (14.4, "WARNING"),  # At ceiling: inside warning range
        (14.0, "WARNING"),  # Within 5% below ceiling
        (13.68, "COMPLIANT"),  # Safely below 5% of 14.4 (13.68)
        (5.0, "COMPLIANT"),
        (1.0, "COMPLIANT"),
    ],
)
def test_sre_fast_burn_rate_ceiling(
    validator: StatutoryBoundaryValidator,
    value: float,
    expected_status: str,
) -> None:
    """Verify SRE 1-hour fast burn rate <= 14.4 ceiling transitions."""
    finding = validator.validate_ratio(
        "ERROR_BUDGET_BURN_RATE_1H", value, tolerance_percentage=0.05
    )
    assert finding.status == expected_status
    assert finding.threshold_value == 14.4
    assert finding.operator == "<="


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (60.0, "BREACH"),  # Ceiling 50.0: greater than 50.0 is BREACH
        (51.0, "BREACH"),
        (50.0, "WARNING"),
        (48.5, "WARNING"),  # Within 5% below 50.0 (47.5 to 50.0)
        (47.4, "COMPLIANT"),
        (25.0, "COMPLIANT"),
    ],
)
def test_sci_software_carbon_intensity_ceiling(
    validator: StatutoryBoundaryValidator,
    value: float,
    expected_status: str,
) -> None:
    """Verify Software Carbon Intensity (SCI) <= 50.0 ceiling transitions."""
    finding = validator.validate_ratio(
        "SOFTWARE_CARBON_INTENSITY", value, tolerance_percentage=0.05
    )
    assert finding.status == expected_status
    assert finding.threshold_value == 50.0
    assert "ISO/IEC 21031" in finding.circular_citation


# ---------------------------------------------------------------------------
# Entity-Type Sensitive Alias Resolution
# ---------------------------------------------------------------------------


def test_alias_resolution_respects_entity_type(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify that generic aliases like 'crar' resolve to entity-specific statutory rules."""
    finding_nbfc = validator.validate_ratio("crar", 14.5, entity_type="nbfc_si")
    assert finding_nbfc.ratio_name == "Capital to Risk-Weighted Assets Ratio (NBFC-SI)"
    assert finding_nbfc.threshold_value == 15.0
    assert finding_nbfc.status == "BREACH"

    finding_bank = validator.validate_ratio("crar", 14.5, entity_type="commercial_bank")
    assert finding_bank.ratio_name == "Minimum Total Capital (CRAR) - Commercial Banks"
    assert finding_bank.threshold_value == 9.0
    assert finding_bank.status == "COMPLIANT"

    finding_sfb = validator.validate_ratio("crar", 14.5, entity_type="small_finance_bank")
    assert finding_sfb.threshold_value == 15.0
    assert finding_sfb.status == "BREACH"

    # Tier 1 alias check
    t1_nbfc = validator.validate_ratio("tier1", 9.5, entity_type="nbfc_si")
    assert t1_nbfc.threshold_value == 10.0
    assert t1_nbfc.status == "BREACH"

    t1_bank = validator.validate_ratio("tier1", 9.5, entity_type="commercial_bank")
    assert t1_bank.threshold_value == 7.0
    assert t1_bank.status == "COMPLIANT"


# ---------------------------------------------------------------------------
# Batch Validation & Overall Status Computation
# ---------------------------------------------------------------------------


def test_batch_validation_compliant_scenario(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify batch report when all ratios are safely compliant."""
    ratios = {
        "crar": 12.0,  # 9.0% threshold (bank) -> Compliant
        "lcr": 115.0,  # 100% threshold -> Compliant
        "leverage_ratio": 5.0,  # 3.5% threshold -> Compliant
        "net_npa": 2.5,  # 6.0% ceiling -> Compliant
        "psl": 45.0,  # 40% threshold -> Compliant
    }
    report = validator.validate_ratios(
        ratios=ratios, entity_type="commercial_bank", tolerance_percentage=0.05
    )

    assert report.overall_status == "COMPLIANT"
    assert report.summary["total"] == 5
    assert report.summary["compliant"] == 5
    assert report.summary["warning"] == 0
    assert report.summary["breach"] == 0
    assert len(report.findings) == 5
    assert report.latency_ms > 0.0


def test_batch_validation_warning_scenario(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify batch report when at least one ratio is in AMBER warning and none breached."""
    ratios = {
        "crar": 9.2,  # 9.0% threshold -> WARNING (within 5% buffer)
        "lcr": 120.0,  # 100% threshold -> Compliant
        "net_npa": 3.0,  # 6.0% ceiling -> Compliant
    }
    report = validator.validate_ratios(
        ratios=ratios, entity_type="commercial_bank", tolerance_percentage=0.05
    )

    assert report.overall_status == "WARNING"
    assert report.summary["total"] == 3
    assert report.summary["compliant"] == 2
    assert report.summary["warning"] == 1
    assert report.summary["breach"] == 0


def test_batch_validation_breach_scenario(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify batch report when at least one ratio is in BREACH."""
    ratios = {
        "crar": 8.5,  # 9.0% threshold -> BREACH
        "lcr": 102.0,  # 100% threshold -> WARNING
        "net_npa": 7.2,  # 6.0% ceiling -> BREACH
        "psl": 41.0,  # 40% threshold -> WARNING (within 5% buffer [40, 42))
    }
    report = validator.validate_ratios(
        ratios=ratios, entity_type="commercial_bank", tolerance_percentage=0.05
    )

    assert report.overall_status == "BREACH"
    assert report.summary["total"] == 4
    assert report.summary["compliant"] == 0
    assert report.summary["warning"] == 2
    assert report.summary["breach"] == 2


def test_zero_tolerance_exact_boundary_is_compliant(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify that with tolerance=0.0, exact boundary is classified as COMPLIANT."""
    finding = validator.validate_ratio("CRAR_NBFC_SI", 15.0, tolerance_percentage=0.0)
    assert finding.status == "COMPLIANT"

    finding_below = validator.validate_ratio("CRAR_NBFC_SI", 14.999, tolerance_percentage=0.0)
    assert finding_below.status == "BREACH"


def test_unknown_ratio_raises_exception_with_catalog_context(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify that invalid ratio names trigger UnknownRatioError with helpful suggestions."""
    with pytest.raises(UnknownRatioError) as exc_info:
        validator.validate_ratio("NON_EXISTENT_METRIC_XYZ", 10.0)

    err_msg = str(exc_info.value)
    assert "NON_EXISTENT_METRIC_XYZ" in err_msg
    assert "Available ratios include" in err_msg


# ---------------------------------------------------------------------------
# Performance & High Throughput Microbenchmark
# ---------------------------------------------------------------------------


def test_validation_execution_speed_under_1_2ms(
    validator: StatutoryBoundaryValidator,
) -> None:
    """Verify NFR requirements: p95 execution latency <= 1.2ms for multi-ratio evaluations."""
    batch_ratios = {
        "crar": 16.5,
        "tier1": 11.0,
        "lcr": 110.0,
        "nsfr": 108.0,
        "crr": 4.8,
        "slr": 19.5,
        "leverage_ratio": 4.2,
        "net_npa": 2.1,
        "pcr": 75.0,
        "psl": 42.5,
    }

    # Warmup
    for _ in range(5):
        validator.validate_ratios(batch_ratios, entity_type="commercial_bank")

    # Measure 50 iterations
    durations: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter()
        validator.validate_ratios(batch_ratios, entity_type="commercial_bank")
        durations.append((time.perf_counter() - t0) * 1000.0)

    durations.sort()
    p95_ms = durations[int(len(durations) * 0.95)]
    assert p95_ms < 1.2, f"Expected p95 < 1.2ms, got {p95_ms:.3f}ms"


# ---------------------------------------------------------------------------
# FastAPI Endpoints Tests
# ---------------------------------------------------------------------------


def test_api_list_boundaries_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /v1/compliance/boundaries endpoint."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    response = client.get("/v1/compliance/boundaries", headers=headers)
    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    assert data["total"] >= 35
    assert len(data["boundaries"]) >= 35

    # Test filtering by regulator
    rbi_resp = client.get("/v1/compliance/boundaries?regulator=RBI", headers=headers)
    assert rbi_resp.status_code == 200
    assert all(b["regulator"] == "RBI" for b in rbi_resp.json()["boundaries"])

    # Test filtering by category
    liq_resp = client.get("/v1/compliance/boundaries?category=liquidity", headers=headers)
    assert liq_resp.status_code == 200
    assert all(b["category"] == "liquidity" for b in liq_resp.json()["boundaries"])


def test_api_validate_ratios_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /v1/compliance/validate-ratios endpoint."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    payload = {
        "entity_type": "nbfc_si",
        "tolerance_percentage": 0.05,
        "ratios": {
            "crar": 14.8,  # 15.0% threshold -> BREACH
            "tier1": 10.2,  # 10.0% threshold -> WARNING
            "lcr": 115.0,  # 100% threshold -> COMPLIANT
            "leverage_ratio": 5.0,  # <= 7.0 ceiling -> COMPLIANT
        },
    }

    response = client.post("/v1/compliance/validate-ratios", json=payload, headers=headers)
    assert response.status_code == 200
    data: dict[str, Any] = response.json()

    assert data["overall_status"] == "BREACH"
    assert data["entity_type"] == "nbfc_si"
    assert data["summary"]["breach"] == 1
    assert data["summary"]["warning"] == 1
    assert data["summary"]["compliant"] == 2
    assert len(data["findings"]) == 4

    # Check finding details
    crar_finding = next(
        f for f in data["findings"] if "Capital to Risk-Weighted Assets" in f["ratio_name"]
    )
    assert crar_finding["status"] == "BREACH"
    assert crar_finding["reported_value"] == 14.8
    assert crar_finding["threshold_value"] == 15.0
    assert "RBI Master Direction" in crar_finding["circular_citation"]


def test_api_validate_ratios_unknown_ratio_returns_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that unknown ratio names return 422 with validation detail."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    payload = {
        "entity_type": "commercial_bank",
        "ratios": {
            "completely_fabricated_metric_abc": 99.9,
        },
    }

    response = client.post("/v1/compliance/validate-ratios", json=payload, headers=headers)
    assert response.status_code == 422
    assert "Unrecognized regulatory ratio" in response.json()["detail"]


def test_api_validate_ratios_unauthorized_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that requests without valid credentials return 401."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)

    response = client.post("/v1/compliance/validate-ratios", json={"ratios": {"crar": 15.0}})
    assert response.status_code == 401
