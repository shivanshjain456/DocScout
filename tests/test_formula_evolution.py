"""Tests for Historical Formula Evolution & Versioning (FEAT-030).

Verifies chronological version tracking, point-in-time statutory formula resolution,
semantic and mathematical version comparisons, and API endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.formula_evolution import (
    ChangeClassification,
    FormulaVersion,
    get_default_formula_evolution_manager,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_canonical_evolution_histories() -> None:
    """Verify that canonical statutory metrics have populated version timelines."""
    manager = get_default_formula_evolution_manager()
    tracked = manager.list_tracked_formulas()
    fids = {t["formula_id"] for t in tracked}
    assert {"crar", "lcr", "pcr", "sci"}.issubset(fids)

    # CRAR timeline verification
    crar_hist = manager.get_history("crar")
    assert len(crar_hist) == 4
    labels = [v.version_label for v in crar_hist]
    assert any("Basel I" in lbl for lbl in labels)
    assert any("Basel II" in lbl for lbl in labels)
    assert any("Basel III Fully Phased In" in lbl for lbl in labels)

    # Chronological sort check
    for i in range(len(crar_hist) - 1):
        assert crar_hist[i].effective_from <= crar_hist[i + 1].effective_from


def test_point_in_time_resolution() -> None:
    """Verify resolution of the legally binding formula for various historical audit dates."""
    manager = get_default_formula_evolution_manager()

    # 1. 1995 (Basel I era)
    ver_1995 = manager.resolve_version("crar", "1995-06-15")
    assert ver_1995.id == "crar_basel1"
    assert "credit_rwa" in ver_1995.variables

    # 2. 2008 (Basel II era)
    ver_2008 = manager.resolve_version("crar", "2008-01-01")
    assert ver_2008.id == "crar_basel2"
    assert "operational_rwa" in ver_2008.variables

    # 3. 2016 (Basel III interim era)
    ver_2016 = manager.resolve_version("crar", "2016-11-08")
    assert ver_2016.id == "crar_basel3_interim"
    assert "cet1_capital" in ver_2016.variables

    # 4. Present day (Basel III full era)
    ver_current = manager.resolve_version("crar", "2024-10-12")
    assert ver_current.id == "crar_basel3_current"
    assert ver_current.is_currently_active is True
    assert ver_current.thresholds["total_capital_with_ccb"] == 11.50


def test_lcr_phase_in_schedule_resolution() -> None:
    """Verify statutory LCR phase-in thresholds across annual compliance dates."""
    manager = get_default_formula_evolution_manager()

    # 2015: 60%
    lcr_2015 = manager.resolve_version("lcr", "2015-05-01")
    assert lcr_2015.thresholds["minimum_lcr"] == 60.0

    # 2017: 80%
    lcr_2017 = manager.resolve_version("lcr", "2017-08-15")
    assert lcr_2017.thresholds["minimum_lcr"] == 80.0

    # 2019+: 100%
    lcr_now = manager.resolve_version("lcr", "2023-01-01")
    assert lcr_now.thresholds["minimum_lcr"] == 100.0


def test_compare_versions_breaking_change() -> None:
    """Verify diff computation between Basel II and Basel III showing breaking structural changes."""
    manager = get_default_formula_evolution_manager()
    diff = manager.compare_versions("crar_basel2", "crar_basel3_current")

    assert diff.formula_id == "crar"
    assert diff.change_type == ChangeClassification.BREAKING
    assert diff.expression_changed is True

    # Added inputs in Basel III
    assert "cet1_capital" in diff.variables_added
    assert "at1_capital" in diff.variables_added
    assert "total_rwa" in diff.variables_added

    # Phased out inputs
    assert "credit_rwa" in diff.variables_removed
    assert "market_rwa" in diff.variables_removed
    assert "operational_rwa" in diff.variables_removed

    # Threshold adjustments
    assert "cet1_minimum" in diff.threshold_changes


def test_compare_versions_phase_in_change() -> None:
    """Verify diff computation between LCR 2015 and LCR 2019 showing threshold phase-in."""
    manager = get_default_formula_evolution_manager()
    diff = manager.compare_versions("lcr_2015", "lcr_current")

    assert diff.formula_id == "lcr"
    assert diff.change_type == ChangeClassification.PHASE_IN
    assert diff.expression_changed is False
    assert diff.variables_added == []
    assert diff.variables_removed == []
    assert diff.threshold_changes["minimum_lcr"] == {"old": 60.0, "new": 100.0}


def test_custom_version_registration() -> None:
    """Verify dynamic registration of custom formula versions."""
    manager = get_default_formula_evolution_manager()
    custom_ver = FormulaVersion(
        id="leverage_ratio_2019",
        formula_id="leverage_ratio",
        version_label="RBI Basel III Leverage Ratio",
        regulatory_framework="RBI",
        effective_from="2019-10-01",
        effective_to=None,
        expression="tier1_capital / total_exposure * 100",
        eval_expression="tier1_capital / total_exposure * 100",
        variables=["tier1_capital", "total_exposure"],
        thresholds={"minimum": 4.0},
        change_summary="Mandatory leverage backstop.",
    )
    manager.register_version(custom_ver)

    retrieved = manager.get_version("leverage_ratio_2019")
    assert retrieved is not None
    assert retrieved.thresholds["minimum"] == 4.0

    resolved = manager.resolve_version("leverage_ratio", "2022-01-01")
    assert resolved.id == "leverage_ratio_2019"


def test_api_list_tracked_histories(client: TestClient) -> None:
    """Verify GET /v1/compliance/formulas/history/tracked."""
    response = client.get(
        "/v1/compliance/formulas/history/tracked",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 4
    fids = [item["formula_id"] for item in data]
    assert "crar" in fids
    assert "lcr" in fids


def test_api_get_formula_history(client: TestClient) -> None:
    """Verify GET /v1/compliance/formulas/{formula_id}/history."""
    response = client.get(
        "/v1/compliance/formulas/crar/history",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["formula_id"] == "crar"
    assert data["total_versions"] >= 4
    assert len(data["history"]) >= 4

    # 404 for unknown formula
    res_404 = client.get(
        "/v1/compliance/formulas/unknown_xyz/history",
        headers=auth(),
    )
    assert res_404.status_code == 404


def test_api_resolve_formula_version(client: TestClient) -> None:
    """Verify POST /v1/compliance/formulas/{formula_id}/resolve-version."""
    payload = {"as_of_date": "2017-06-15"}
    response = client.post(
        "/v1/compliance/formulas/lcr/resolve-version",
        headers=auth(),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["formula_id"] == "lcr"
    assert data["thresholds"]["minimum_lcr"] == 80.0
    assert "2017" in data["version_label"]

    # Invalid date format returns 422
    res_bad = client.post(
        "/v1/compliance/formulas/lcr/resolve-version",
        headers=auth(),
        json={"as_of_date": "invalid-date"},
    )
    assert res_bad.status_code == 422


def test_api_compare_formula_versions(client: TestClient) -> None:
    """Verify POST /v1/compliance/formulas/compare-versions."""
    payload = {
        "version_a_id": "sci_draft_v1",
        "version_b_id": "sci_iso_21031",
    }
    response = client.post(
        "/v1/compliance/formulas/compare-versions",
        headers=auth(),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["formula_id"] == "sci"
    assert data["change_type"] == "breaking"
    assert data["expression_changed"] is True
    assert "time_share" in data["variables_added"]
    assert "res_share" in data["variables_added"]

    # 404 for nonexistent version
    res_404 = client.post(
        "/v1/compliance/formulas/compare-versions",
        headers=auth(),
        json={"version_a_id": "nonexistent_a", "version_b_id": "sci_iso_21031"},
    )
    assert res_404.status_code == 404
