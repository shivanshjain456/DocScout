"""Tests for Compliance 'What-If' Sensitivity Simulator (FEAT-024).

Verifies parameterized formula simulations, partial derivatives, elasticities,
curve sweeps, break-even boundary searches, regulatory stress test presets,
analytical mathematical precision, latency budgets, and FastAPI HTTP endpoints.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from starlette.testclient import TestClient

from app.api import metrics
from app.api.app import app
from app.api.models import SimulationRequest
from app.api.security import load_keys
from app.compliance.formula_engine import (
    MathDomainError,
    MissingVariableError,
    UnknownFormulaError,
)
from app.compliance.simulator import (
    ComplianceSimulator,
    get_default_compliance_simulator,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def simulator() -> ComplianceSimulator:
    """Fixture providing default compliance simulator instance."""
    return get_default_compliance_simulator()


# ---------------------------------------------------------------------------
# 1. Baseline Computation & Mathematical Precision Tests
# ---------------------------------------------------------------------------


def test_crar_baseline_and_analytical_derivatives(
    simulator: ComplianceSimulator,
) -> None:
    """Verify numerical partial derivatives against analytical calculus for CRAR.

    CRAR = (T1 + T2) / RWA
    d(CRAR)/d(T1) = 1 / RWA
    d(CRAR)/d(T2) = 1 / RWA
    d(CRAR)/d(RWA) = -(T1 + T2) / (RWA^2)
    Elasticity(RWA) = -1.0
    """
    t1 = 160.0
    t2 = 40.0
    rwa = 1000.0

    req = SimulationRequest(
        formula_id="crar",
        base_inputs={
            "tier1_capital": t1,
            "tier2_capital": t2,
            "risk_weighted_assets": rwa,
        },
        sweep_steps=5,
    )
    res = simulator.simulate(req)

    # 1. Baseline verification: (160 + 40) / 1000 = 0.20 (20.0%)
    assert res.baseline_value == 0.20
    assert res.baseline_status == "COMPLIANT"

    # 2. Analytical partial derivative comparison
    analytical_dt1 = 1.0 / rwa  # 0.001
    analytical_drwa = -(t1 + t2) / (rwa**2)  # -0.0002

    deriv_t1 = res.sensitivity_gradients["tier1_capital"]
    deriv_rwa = res.sensitivity_gradients["risk_weighted_assets"]

    assert abs(deriv_t1 - analytical_dt1) < 1e-5
    assert abs(deriv_rwa - analytical_drwa) < 1e-5

    # 3. Elasticity: RWA elasticity must equal -1.0
    elasticity_rwa = res.elasticities["risk_weighted_assets"]
    assert abs(elasticity_rwa - (-1.0)) < 1e-3

    # 4. Impact ranking: RWA (elasticity -1.0) and Tier 1 (0.8) are top ranked
    ranks = {s.variable: s.impact_rank for s in res.sensitivities}
    assert ranks["risk_weighted_assets"] == 1 or ranks["tier1_capital"] == 1


def test_lcr_baseline_and_analytical_derivatives(
    simulator: ComplianceSimulator,
) -> None:
    """Verify numerical partial derivatives against analytical calculus for LCR.

    LCR = HQLA / NetOutflows
    d(LCR)/d(HQLA) = 1 / NetOutflows
    d(LCR)/d(NetOutflows) = -HQLA / (NetOutflows^2)
    """
    hqla = 600.0
    outflows = 500.0

    req = SimulationRequest(
        formula_id="lcr",
        base_inputs={
            "hqla": hqla,
            "net_cash_outflows": outflows,
        },
    )
    res = simulator.simulate(req)

    # Baseline: 600 / 500 = 1.20 (120%)
    assert res.baseline_value == 1.20
    assert res.baseline_status == "COMPLIANT"

    analytical_dhqla = 1.0 / outflows  # 0.002
    analytical_dout = -hqla / (outflows**2)  # -0.0024

    assert abs(res.sensitivity_gradients["hqla"] - analytical_dhqla) < 1e-5
    assert abs(res.sensitivity_gradients["net_cash_outflows"] - analytical_dout) < 1e-5
    assert abs(res.elasticities["net_cash_outflows"] - (-1.0)) < 1e-3
    assert abs(res.elasticities["hqla"] - 1.0) < 1e-3


def test_sci_software_carbon_intensity_simulation(
    simulator: ComplianceSimulator,
) -> None:
    """Verify Software Carbon Intensity sensitivity simulation."""
    req = SimulationRequest(
        formula_id="sci",
        base_inputs={
            "E": 10.0,
            "I": 400.0,
            "M": 500.0,
            "R": 100.0,
        },
    )
    res = simulator.simulate(req)

    # Baseline: (10 * 400 + 500) / 100 = 4500 / 100 = 45.0
    assert res.baseline_value == 45.0
    assert res.baseline_status == "COMPLIANT"  # <= 50.0 is compliant

    # Positive derivatives for E, I, M; Negative for R
    assert res.sensitivity_gradients["E"] > 0
    assert res.sensitivity_gradients["I"] > 0
    assert res.sensitivity_gradients["M"] > 0
    assert res.sensitivity_gradients["R"] < 0


# ---------------------------------------------------------------------------
# 2. Parameter Sweep Curves & Boundary Transitions
# ---------------------------------------------------------------------------


def test_sweep_curves_capture_boundary_transitions(
    simulator: ComplianceSimulator,
) -> None:
    """Verify parameter sweep generates scenario curves that transition across boundary states."""
    # Near statutory boundary: 155 Cr capital, 1000 Cr RWA = 15.5% CRAR (WARNING zone [15.0, 15.75))
    req = SimulationRequest(
        formula_id="crar",
        base_inputs={
            "tier1_capital": 120.0,
            "tier2_capital": 35.0,
            "risk_weighted_assets": 1000.0,
        },
        sweep_percentage_range=0.30,  # +/- 30% sweep
        sweep_steps=11,
        entity_type="nbfc_si",
    )
    res = simulator.simulate(req)

    rwa_curve = res.scenario_curves["risk_weighted_assets"]
    assert len(rwa_curve) == 11

    statuses = [p.status for p in rwa_curve]
    # At -30% RWA (700 Cr), CRAR is 155/700 = 22.1% -> COMPLIANT
    assert statuses[0] == "COMPLIANT"
    # At +30% RWA (1300 Cr), CRAR is 155/1300 = 11.9% -> BREACH
    assert statuses[-1] == "BREACH"


def test_explicit_custom_deltas(simulator: ComplianceSimulator) -> None:
    """Verify user-provided delta percentages override automated sweep."""
    req = SimulationRequest(
        formula_id="lcr",
        base_inputs={
            "hqla": 500.0,
            "net_cash_outflows": 500.0,
        },
        deltas={
            "hqla": [-0.20, -0.10, 0.0, 0.10, 0.20],
        },
    )
    res = simulator.simulate(req)

    hqla_curve = res.scenario_curves["hqla"]
    assert len(hqla_curve) == 5
    assert hqla_curve[0].input_value == 400.0  # -20%
    assert hqla_curve[2].input_value == 500.0  # 0%
    assert hqla_curve[4].input_value == 600.0  # +20%


# ---------------------------------------------------------------------------
# 3. Regulatory Stress Testing Presets
# ---------------------------------------------------------------------------


def test_regulatory_stress_presets(simulator: ComplianceSimulator) -> None:
    """Verify built-in banking stress presets generate adverse scenario reports."""
    req = SimulationRequest(
        formula_id="crar",
        base_inputs={
            "tier1_capital": 160.0,
            "tier2_capital": 40.0,
            "risk_weighted_assets": 1200.0,
        },
    )
    res = simulator.simulate(req)

    assert len(res.stress_tests) >= 2
    mod_stress = next(s for s in res.stress_tests if "Moderate Asset Quality" in s.name)
    sev_stress = next(s for s in res.stress_tests if "Severe Macroeconomic" in s.name)

    # Moderate: T1 152, T2 39.2, RWA 1320 -> (152 + 39.2) / 1320 = 191.2 / 1320 = 14.48% (BREACH of 15% NBFC / Warning Bank)
    assert mod_stress.delta_percentage_from_baseline < 0
    # Severe must be strictly worse than moderate
    assert sev_stress.computed_value < mod_stress.computed_value


# ---------------------------------------------------------------------------
# 4. Error Handling & Guardrails
# ---------------------------------------------------------------------------


def test_unknown_formula_raises_error(simulator: ComplianceSimulator) -> None:
    """Verify unknown formula IDs raise UnknownFormulaError."""
    req = SimulationRequest(
        formula_id="invalid_formula_abc",
        base_inputs={"x": 1.0},
    )
    with pytest.raises(UnknownFormulaError):
        simulator.simulate(req)


def test_missing_variable_raises_error(simulator: ComplianceSimulator) -> None:
    """Verify missing required variables raise MissingVariableError."""
    req = SimulationRequest(
        formula_id="crar",
        base_inputs={"tier1_capital": 100.0},  # missing tier2 and rwa
    )
    with pytest.raises(MissingVariableError):
        simulator.simulate(req)


def test_non_finite_variable_raises_error(simulator: ComplianceSimulator) -> None:
    """Verify NaN or infinity values raise MathDomainError."""
    req = SimulationRequest(
        formula_id="lcr",
        base_inputs={"hqla": float("nan"), "net_cash_outflows": 100.0},
    )
    with pytest.raises(MathDomainError):
        simulator.simulate(req)


# ---------------------------------------------------------------------------
# 5. Performance & Latency SLA (p95 <= 4.0ms)
# ---------------------------------------------------------------------------


def test_simulation_latency_under_4ms(simulator: ComplianceSimulator) -> None:
    """Verify 50 simulation runs complete within the required <= 4.0ms budget."""
    req = SimulationRequest(
        formula_id="crar",
        base_inputs={
            "tier1_capital": 150.0,
            "tier2_capital": 50.0,
            "risk_weighted_assets": 1000.0,
        },
        sweep_steps=11,
    )

    # Warmup
    for _ in range(5):
        simulator.simulate(req)

    durations: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter()
        simulator.simulate(req)
        durations.append((time.perf_counter() - t0) * 1000.0)

    durations.sort()
    p95_ms = durations[int(len(durations) * 0.95)]
    assert p95_ms < 4.0, f"Expected p95 < 4.0ms, got {p95_ms:.3f}ms"


# ---------------------------------------------------------------------------
# 6. FastAPI HTTP Endpoint Tests
# ---------------------------------------------------------------------------


def test_api_simulate_endpoint_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /v1/compliance/simulate returns simulation payload and increments metrics."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    before_count = metrics.SIMULATION_REQUESTS_TOTAL.labels(formula_id="crar")._value.get()

    payload = {
        "formula_id": "crar",
        "base_inputs": {
            "tier1_capital": 160.0,
            "tier2_capital": 40.0,
            "risk_weighted_assets": 1000.0,
        },
        "sweep_steps": 5,
    }

    resp = client.post("/v1/compliance/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data: dict[str, Any] = resp.json()

    assert data["formula_id"] == "crar"
    assert data["baseline_value"] == 0.20
    assert "sensitivity_gradients" in data
    assert "elasticities" in data
    assert "scenario_curves" in data
    assert len(data["scenario_curves"]["tier1_capital"]) == 5
    assert len(data["stress_tests"]) >= 2
    assert data["latency_ms"] > 0

    after_count = metrics.SIMULATION_REQUESTS_TOTAL.labels(formula_id="crar")._value.get()
    assert after_count == before_count + 1


def test_api_simulate_unauthorized_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unauthenticated simulation requests return 401."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)

    resp = client.post(
        "/v1/compliance/simulate",
        json={"formula_id": "crar", "base_inputs": {}},
    )
    assert resp.status_code == 401


def test_api_simulate_missing_variables_returns_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify missing required variables return HTTP 422 with validation detail."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    resp = client.post(
        "/v1/compliance/simulate",
        json={"formula_id": "crar", "base_inputs": {"tier1_capital": 100.0}},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "Missing required variable" in resp.json()["detail"]
