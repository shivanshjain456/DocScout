"""Tests for Formula Dependency Graph Builder (FEAT-029).

Verifies topological calculation ordering, cycle detection, execution stages,
prerequisite readiness checking, cascade evaluations, and API endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.dependency_graph import (
    CircularDependencyError,
    DependencyGraphBuilder,
    NodeType,
    extract_variables_from_expression,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_extract_variables_from_expression() -> None:
    """Verify AST extraction of free variable identifiers from mathematical formulas."""
    expr = "(common_shares + retained_earnings + statutory_reserves - deductions) / total_rwa * 100"
    vars_found = extract_variables_from_expression(expr)
    assert vars_found == [
        "common_shares",
        "deductions",
        "retained_earnings",
        "statutory_reserves",
        "total_rwa",
    ]

    # Expression with unicode multiplication and minus
    expr2 = "gross_npa × 100 ÷ gross_advances – provision_deductions"
    vars_found2 = extract_variables_from_expression(expr2)
    assert "gross_npa" in vars_found2
    assert "gross_advances" in vars_found2
    assert "provision_deductions" in vars_found2


def test_build_custom_graph_topological_sort() -> None:
    """Verify that DependencyGraphBuilder creates correct topological ordering and tiers."""
    formulas = [
        {
            "id": "tier1",
            "expression": "cet1 + at1",
        },
        {
            "id": "total_capital",
            "expression": "tier1 + tier2",
        },
        {
            "id": "crar",
            "expression": "(total_capital / rwa) * 100",
        },
    ]

    graph = DependencyGraphBuilder.build_from_formulas(
        formulas=formulas,
        graph_id="custom_capital",
        name="Custom Capital Adequacy",
        target_variables=["crar"],
    )

    # Inputs should be automatically discovered: cet1, at1, tier2, rwa
    for inp in ("cet1", "at1", "tier2", "rwa"):
        assert inp in graph.nodes
        assert graph.nodes[inp].node_type == NodeType.INPUT

    assert graph.nodes["crar"].node_type == NodeType.OUTPUT
    assert graph.nodes["tier1"].node_type == NodeType.INTERMEDIATE

    # Topological order must compute inputs before tier1, tier1 before total_capital, etc.
    order = graph.topological_order
    assert order.index("cet1") < order.index("tier1")
    assert order.index("at1") < order.index("tier1")
    assert order.index("tier1") < order.index("total_capital")
    assert order.index("tier2") < order.index("total_capital")
    assert order.index("total_capital") < order.index("crar")
    assert order.index("rwa") < order.index("crar")

    # Execution tiers
    assert len(graph.execution_tiers) >= 4
    assert graph.nodes["cet1"].tier == 0
    assert graph.nodes["tier1"].tier == 1
    assert graph.nodes["total_capital"].tier == 2
    assert graph.nodes["crar"].tier == 3


def test_circular_dependency_detection() -> None:
    """Verify that circular dependencies are caught with CircularDependencyError."""
    cyclic_formulas = [
        {"id": "a", "expression": "b + 10"},
        {"id": "b", "expression": "c * 2"},
        {"id": "c", "expression": "a - 5"},
    ]

    with pytest.raises(CircularDependencyError) as exc_info:
        DependencyGraphBuilder.build_from_formulas(
            formulas=cyclic_formulas,
            graph_id="cyclic_test",
            name="Cyclic Graph",
        )

    assert "Circular dependency detected" in str(exc_info.value)
    assert len(exc_info.value.cycle_path) >= 3


def test_canonical_templates() -> None:
    """Verify built-in regulatory templates: Basel III, LCR, IRAC, and SCI."""
    templates = DependencyGraphBuilder.list_templates()
    assert len(templates) >= 4
    template_ids = {t["template_id"] for t in templates}
    assert "basel3_crar" in template_ids
    assert "lcr_framework" in template_ids
    assert "asset_quality_irac" in template_ids
    assert "software_carbon_intensity" in template_ids

    # Load Basel III template
    b3 = DependencyGraphBuilder.get_template("basel3_crar")
    assert "crar" in b3.target_variables
    assert "cet1_ratio" in b3.target_variables
    assert "total_rwa" in b3.nodes
    assert len(b3.topological_order) > 0


def test_basel3_cascade_evaluation() -> None:
    """Verify exact cascade numeric evaluation on Basel III CRAR template."""
    b3 = DependencyGraphBuilder.get_template("basel3_crar")
    inputs = {
        "common_shares": 5000.0,
        "retained_earnings": 3000.0,
        "statutory_reserves": 2000.0,
        "regulatory_deductions": 500.0,
        "additional_tier1": 1500.0,
        "subordinated_debt": 1200.0,
        "general_provisions": 300.0,
        "credit_rwa": 60000.0,
        "market_rwa": 10000.0,
        "operational_rwa": 10000.0,
    }

    result = b3.evaluate_cascade(inputs)
    assert result["is_complete"] is True
    # cet1 = 5000 + 3000 + 2000 - 500 = 9500
    # tier1 = 9500 + 1500 = 11000
    # tier2 = 1200 + 300 = 1500
    # total_capital = 11000 + 1500 = 12500
    # total_rwa = 60000 + 10000 + 10000 = 80000
    # crar = (12500 / 80000) * 100 = 15.625
    # tier1_ratio = (11000 / 80000) * 100 = 13.75
    # cet1_ratio = (9500 / 80000) * 100 = 11.875
    outputs = result["target_outputs"]
    assert pytest.approx(outputs["crar"], 0.001) == 15.625
    assert pytest.approx(outputs["tier1_ratio"], 0.001) == 13.75
    assert pytest.approx(outputs["cet1_ratio"], 0.001) == 11.875


def test_lcr_framework_evaluation() -> None:
    """Verify Liquidity Coverage Ratio cascade evaluation."""
    lcr_graph = DependencyGraphBuilder.get_template("lcr_framework")
    inputs = {
        "level1_cash_reserves": 3000.0,
        "level1_gov_bonds": 7000.0,
        "level2a_corporate_bonds": 2000.0,
        "stressed_30d_cash_outflows": 10000.0,
        "stressed_30d_cash_inflows": 2000.0,
    }

    result = lcr_graph.evaluate_cascade(inputs)
    assert result["is_complete"] is True
    # level1_hqla = 3000 + 7000 = 10000
    # level2a_hqla = 2000 * 0.85 = 1700
    # total_hqla = 10000 + 1700 = 11700
    # net_cash_outflows = 10000 - 2000 = 8000
    # lcr = (11700 / 8000) * 100 = 146.25%
    outputs = result["target_outputs"]
    assert pytest.approx(outputs["lcr"], 0.01) == 146.25


def test_prerequisite_readiness_checker() -> None:
    """Verify missing inputs identification and completion percentage calculation."""
    irac = DependencyGraphBuilder.get_template("asset_quality_irac")
    # Provide only partial inputs
    inputs = {
        "substandard_assets": 1000.0,
        "doubtful_assets": 500.0,
    }

    check = irac.check_prerequisites(target_variables=["pcr"], provided_inputs=inputs)
    assert check["is_ready"] is False
    assert "loss_assets" in check["missing_inputs"]
    assert "cumulative_provisions" in check["missing_inputs"]
    assert check["completion_percentage"] < 100.0

    # Provide all inputs for PCR
    full_inputs = {
        "substandard_assets": 1000.0,
        "doubtful_assets": 500.0,
        "loss_assets": 200.0,
        "cumulative_provisions": 1360.0,
    }
    check_full = irac.check_prerequisites(target_variables=["pcr"], provided_inputs=full_inputs)
    assert check_full["is_ready"] is True
    assert len(check_full["missing_inputs"]) == 0
    assert check_full["completion_percentage"] == 100.0
    assert "gross_npa" in check_full["resolvable_intermediates"]


def test_missing_input_blocked_trace() -> None:
    """Verify that missing inputs mark dependent nodes as BLOCKED without crashing."""
    b3 = DependencyGraphBuilder.get_template("basel3_crar")
    # Pass empty inputs
    result = b3.evaluate_cascade({})
    assert result["is_complete"] is False
    assert len(result["missing_variables"]) > 0

    blocked_steps = [s for s in result["trace"] if s["status"] == "BLOCKED"]
    assert len(blocked_steps) > 0


def test_api_list_templates(client: TestClient) -> None:
    """Verify GET /v1/compliance/dependency-graphs/templates."""
    response = client.get(
        "/v1/compliance/dependency-graphs/templates",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 4
    template_ids = [t["template_id"] for t in data]
    assert "basel3_crar" in template_ids


def test_api_get_graph(client: TestClient) -> None:
    """Verify GET /v1/compliance/dependency-graphs/{graph_id}."""
    response = client.get(
        "/v1/compliance/dependency-graphs/basel3_crar",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["graph_id"] == "basel3_crar"
    assert "nodes" in data
    assert "edges" in data
    assert "topological_order" in data
    assert "execution_tiers" in data

    # 404 for unknown graph
    res_404 = client.get(
        "/v1/compliance/dependency-graphs/unknown_graph_99",
        headers=auth(),
    )
    assert res_404.status_code == 404


def test_api_build_graph(client: TestClient) -> None:
    """Verify POST /v1/compliance/dependency-graphs/build."""
    payload = {
        "graph_id": "test_api_graph",
        "name": "API Test Graph",
        "domain": "test",
        "formulas": [
            {"id": "sum_ab", "expression": "a + b"},
            {"id": "ratio_c", "expression": "sum_ab / total * 100"},
        ],
        "target_variables": ["ratio_c"],
    }
    response = client.post(
        "/v1/compliance/dependency-graphs/build",
        headers=auth(),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["graph_id"] == "test_api_graph"
    assert "sum_ab" in data["nodes"]
    assert "ratio_c" in data["nodes"]
    assert "a" in data["nodes"]

    # Test circular dependency error returns 400
    bad_payload = {
        "graph_id": "bad_cyclic",
        "name": "Bad Cyclic",
        "formulas": [
            {"id": "x", "expression": "y + 1"},
            {"id": "y", "expression": "x * 2"},
        ],
    }
    res_bad = client.post(
        "/v1/compliance/dependency-graphs/build",
        headers=auth(),
        json=bad_payload,
    )
    assert res_bad.status_code == 400
    assert "Circular dependency" in res_bad.json()["detail"]


def test_api_evaluate_graph(client: TestClient) -> None:
    """Verify POST /v1/compliance/dependency-graphs/evaluate."""
    payload = {
        "template_id": "software_carbon_intensity",
        "provided_inputs": {
            "energy_consumption_kwh": 20000.0,
            "grid_carbon_intensity": 0.5,
            "embodied_carbon": 1000.0,
            "functional_unit_r": 1000000.0,
        },
    }
    response = client.post(
        "/v1/compliance/dependency-graphs/evaluate",
        headers=auth(),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_complete"] is True
    # operational = 20000 * 0.5 = 10000
    # total = 10000 + 1000 = 11000
    # sci = 11000 / 1000000 = 0.011
    assert pytest.approx(data["target_outputs"]["sci"], 0.0001) == 0.011
    assert len(data["trace"]) > 0


def test_api_check_prerequisites(client: TestClient) -> None:
    """Verify POST /v1/compliance/dependency-graphs/prerequisites."""
    payload = {
        "template_id": "lcr_framework",
        "provided_inputs": {
            "level1_cash_reserves": 5000.0,
        },
    }
    response = client.post(
        "/v1/compliance/dependency-graphs/prerequisites",
        headers=auth(),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_ready"] is False
    assert len(data["missing_inputs"]) > 0
    assert "level1_gov_bonds" in data["missing_inputs"]
