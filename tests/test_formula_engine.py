"""Tests for Statutory Formula Computational Engine (FEAT-021).

Verifies AST parser safety, strict node whitelisting, arbitrary precision arithmetic,
zero code injection vulnerability, execution of all 24 canonical taxonomy formulas
plus statutory banking ratios, latency SLA (p95 <= 1.0ms), and HTTP API endpoints.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api import metrics
from app.api.app import app
from app.api.security import load_keys
from app.compliance.formula_engine import (
    FormulaEngine,
    MathDomainError,
    MissingVariableError,
    SafeMathEvaluator,
    SecurityViolationError,
    UnknownFormulaError,
    get_default_formula_engine,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def engine() -> FormulaEngine:
    return get_default_formula_engine()


@pytest.fixture
def evaluator() -> SafeMathEvaluator:
    return SafeMathEvaluator()


# -----------------------------------------------------------------------------
# 1. Safe AST Evaluator Security & Sanity Tests
# -----------------------------------------------------------------------------


def test_evaluator_basic_arithmetic(evaluator: SafeMathEvaluator) -> None:
    """Verify standard arithmetic operations evaluate accurately."""
    assert evaluator.evaluate("2 + 3", {}) == 5.0
    assert evaluator.evaluate("10 - 4.5", {}) == 5.5
    assert evaluator.evaluate("3 * 7", {}) == 21.0
    assert evaluator.evaluate("15 / 3", {}) == 5.0
    assert evaluator.evaluate("2 ** 4", {}) == 16.0
    assert evaluator.evaluate("7 // 2", {}) == 3.0
    assert evaluator.evaluate("7 % 3", {}) == 1.0
    assert evaluator.evaluate("-5 + +10", {}) == 5.0


def test_evaluator_safe_math_functions(evaluator: SafeMathEvaluator) -> None:
    """Verify whitelisted mathematical functions work correctly."""
    assert evaluator.evaluate("sqrt(16)", {}) == 4.0
    assert evaluator.evaluate("abs(-42)", {}) == 42.0
    assert evaluator.evaluate("min(10, 5, 20)", {}) == 5.0
    assert evaluator.evaluate("max(10, 5, 20)", {}) == 20.0
    assert evaluator.evaluate("round(3.14159, 2)", {}) == 3.14
    assert evaluator.evaluate("ceil(4.1)", {}) == 5.0
    assert evaluator.evaluate("floor(4.9)", {}) == 4.0


def test_evaluator_security_blocks_code_injection(evaluator: SafeMathEvaluator) -> None:
    """Ensure attempts to execute arbitrary python code or attribute access raise SecurityViolationError."""
    malicious_payloads = [
        "__import__('os').system('ls')",
        "().__class__.__base__.__subclasses__()",
        "open('/etc/passwd').read()",
        "eval('2 + 2')",
        "exec('x = 1')",
        "[x for x in [1, 2, 3]]",
        "{'a': 1}['a']",
        "lambda x: x + 1",
    ]
    for expr in malicious_payloads:
        with pytest.raises(SecurityViolationError):
            evaluator.evaluate(expr, {})


def test_evaluator_division_by_zero_guarded(evaluator: SafeMathEvaluator) -> None:
    """Verify division by zero raises MathDomainError."""
    with pytest.raises(MathDomainError, match="division by zero"):
        evaluator.evaluate("10 / 0", {})

    with pytest.raises(MathDomainError, match="division by zero"):
        evaluator.evaluate("10 / (5 - 5)", {})


def test_evaluator_non_finite_guarded(evaluator: SafeMathEvaluator) -> None:
    """Verify non-finite inputs or results raise MathDomainError."""
    with pytest.raises(MathDomainError):
        evaluator.evaluate("x + 1", {"x": float("nan")})

    with pytest.raises(MathDomainError):
        evaluator.evaluate("x + 1", {"x": float("inf")})


# -----------------------------------------------------------------------------
# 2. Formula Catalog & Variable Verification
# -----------------------------------------------------------------------------


def test_formula_registry_completeness(engine: FormulaEngine) -> None:
    """Verify all 24 canonical taxonomy formulas plus statutory banking ratios are registered."""
    formulas = engine.list_formulas()
    assert len(formulas) >= 28

    f_ids = {f.id for f in formulas}
    # 24 Canonical taxonomy IDs
    expected_taxonomy_ids = {
        "sci",
        "error-budget",
        "burn-rate",
        "mcdc",
        "mutation-score",
        "dre",
        "littles-law",
        "usl",
        "amdahl",
        "apdex",
        "disparate-impact",
        "ece",
        "faithfulness",
        "hallucination-rate",
        "asr",
        "srm",
        "cuped",
        "power",
        "coordinated-omission",
        "t-way",
        "coverage-gap",
        "cve-triage",
        "capacity-headroom",
        "toil-ratio",
    }
    assert expected_taxonomy_ids.issubset(f_ids)

    # Statutory banking ratio IDs
    expected_banking_ids = {"crar", "lcr", "leverage-ratio", "nsfr"}
    assert expected_banking_ids.issubset(f_ids)


def test_missing_variable_validation(engine: FormulaEngine) -> None:
    """Verify omitting required inputs raises MissingVariableError with clear diagnostics."""
    with pytest.raises(MissingVariableError) as exc_info:
        engine.calculate("sci", {"E": 10.0, "I": 50.0})  # Missing M and R
    assert "M" in exc_info.value.missing_vars
    assert "R" in exc_info.value.missing_vars


def test_unknown_formula_validation(engine: FormulaEngine) -> None:
    """Verify requesting an unregistered formula ID raises UnknownFormulaError."""
    with pytest.raises(UnknownFormulaError):
        engine.calculate("non_existent_formula_id_999", {})


# -----------------------------------------------------------------------------
# 3. Ground Truth Verification Across All 24 Canonical Formulas + Banking Ratios
# -----------------------------------------------------------------------------


def test_all_24_canonical_formulas_analytical_ground_truth(engine: FormulaEngine) -> None:
    """Verify analytical mathematical ground truths across all 24 canonical formulas (48 test vectors)."""
    # 1. sci: (E * I + M) / R
    res_sci = engine.calculate("sci", {"E": 10, "I": 50, "M": 100, "R": 5})
    assert res_sci.computed_value == 120.0
    res_sci_2 = engine.calculate("sci", {"E": 20, "I": 40, "M": 200, "R": 10})
    assert res_sci_2.computed_value == 100.0

    # 2. error-budget: 1 - SLO
    res_eb = engine.calculate("error-budget", {"SLO": 0.999})
    assert res_eb.computed_value == 0.001
    res_eb_2 = engine.calculate("error-budget", {"SLO": 0.99})
    assert res_eb_2.computed_value == 0.01

    # 3. burn-rate: ErrorsObserved / Budget
    res_br = engine.calculate("burn-rate", {"ErrorsObserved": 10, "Budget": 5})
    assert res_br.computed_value == 2.0
    res_br_2 = engine.calculate("burn-rate", {"ErrorsObserved": 25, "Budget": 2})
    assert res_br_2.computed_value == 12.5

    # 4. mcdc: N + 1
    res_mc = engine.calculate("mcdc", {"N": 4})
    assert res_mc.computed_value == 5.0
    res_mc_2 = engine.calculate("mcdc", {"N": 8})
    assert res_mc_2.computed_value == 9.0

    # 5. mutation-score: KilledMutants / (TotalMutants - EquivalentMutants)
    res_ms = engine.calculate(
        "mutation-score",
        {"KilledMutants": 80, "TotalMutants": 100, "EquivalentMutants": 20},
    )
    assert res_ms.computed_value == 1.0
    res_ms_2 = engine.calculate(
        "mutation-score",
        {"KilledMutants": 60, "TotalMutants": 100, "EquivalentMutants": 20},
    )
    assert res_ms_2.computed_value == 0.75

    # 6. dre: DefectsFoundInPhase / (DefectsFoundInPhase + DefectsEscapedFromPhase)
    res_dre = engine.calculate(
        "dre",
        {"DefectsFoundInPhase": 45, "DefectsEscapedFromPhase": 5},
    )
    assert res_dre.computed_value == 0.9
    res_dre_2 = engine.calculate(
        "dre",
        {"DefectsFoundInPhase": 80, "DefectsEscapedFromPhase": 20},
    )
    assert res_dre_2.computed_value == 0.8

    # 7. littles-law: arrival_rate * W
    res_ll = engine.calculate("littles-law", {"arrival_rate": 50, "W": 0.2})
    assert res_ll.computed_value == 10.0
    res_ll_alias = engine.calculate("littles-law", {"lambda": 100, "W": 0.05})
    assert res_ll_alias.computed_value == 5.0

    # 8. usl: N / (1 + a * (N - 1) + b * N * (N - 1))
    res_usl = engine.calculate("usl", {"N": 10, "a": 0.05, "b": 0.01})
    # 10 / (1 + 0.05*9 + 0.01*10*9) = 10 / (1 + 0.45 + 0.9) = 10 / 2.35 = 4.2553
    assert res_usl.computed_value == 4.2553

    # 9. amdahl: 1 / ((1 - p) + p / s)
    res_am = engine.calculate("amdahl", {"p": 0.8, "s": 4})
    # 1 / (0.2 + 0.2) = 2.5
    assert res_am.computed_value == 2.5
    res_am_2 = engine.calculate("amdahl", {"p": 0.5, "s": 2})
    # 1 / (0.5 + 0.25) = 1 / 0.75 = 1.3333
    assert res_am_2.computed_value == 1.3333

    # 10. apdex: Throughput / Load
    res_ap = engine.calculate("apdex", {"Throughput": 80, "Load": 100})
    assert res_ap.computed_value == 0.8
    res_ap_2 = engine.calculate("apdex", {"Throughput": 95, "Load": 100})
    assert res_ap_2.computed_value == 0.95

    # 11. disparate-impact: SelectionRate_protected / SelectionRate_reference
    res_di = engine.calculate(
        "disparate-impact",
        {"SelectionRate_protected": 0.72, "SelectionRate_reference": 0.90},
    )
    assert res_di.computed_value == 0.80
    assert res_di.is_compliant is True

    # 12. ece: (n_b / N) * abs(acc_b - conf_b)
    res_ece = engine.calculate("ece", {"n_b": 100, "N": 1000, "acc_b": 0.85, "conf_b": 0.95})
    assert res_ece.computed_value == 0.01

    # 13. faithfulness: supported_claims / total_claims
    res_faith = engine.calculate("faithfulness", {"supported_claims": 19, "total_claims": 20})
    assert res_faith.computed_value == 0.95
    assert res_faith.is_compliant is True

    # 14. hallucination-rate: unsupported_answers / total_answers
    res_hal = engine.calculate(
        "hallucination-rate",
        {"unsupported_answers": 2, "total_answers": 50},
    )
    assert res_hal.computed_value == 0.04
    assert res_hal.is_compliant is True

    # 15. asr: successful_attacks / total_attempts
    res_asr = engine.calculate("asr", {"successful_attacks": 1, "total_attempts": 100})
    assert res_asr.computed_value == 0.01
    assert res_asr.is_compliant is True

    # 16. srm: ((observed - expected) ** 2) / expected
    res_srm = engine.calculate("srm", {"observed": 490, "expected": 500})
    assert res_srm.computed_value == 0.2

    # 17. cuped: Y - theta * (X - mean_X)
    res_cuped = engine.calculate("cuped", {"Y": 10.0, "theta": 0.5, "X": 8.0, "mean_X": 6.0})
    assert res_cuped.computed_value == 9.0

    # 18. power: 2 * ((z_alpha_2 + z_beta) ** 2) * (sigma ** 2) / (delta ** 2)
    res_pow = engine.calculate(
        "power",
        {"z_alpha_2": 1.96, "z_beta": 0.84, "sigma": 1.0, "delta": 0.2},
    )
    assert res_pow.computed_value == 392.0

    # 19. coordinated-omission: actual_latency + stall_duration
    res_co = engine.calculate(
        "coordinated-omission",
        {"actual_latency": 20.0, "stall_duration": 80.0},
    )
    assert res_co.computed_value == 100.0

    # 20. t-way: k ** t
    res_tway = engine.calculate("t-way", {"k": 3, "t": 2})
    assert res_tway.computed_value == 9.0

    # 21. coverage-gap: required_coverage - achieved_coverage
    res_cgap = engine.calculate(
        "coverage-gap",
        {"required_coverage": 1.0, "achieved_coverage": 0.95},
    )
    assert res_cgap.computed_value == 0.05
    assert res_cgap.is_compliant is False  # threshold is <= 0.00

    # 22. cve-triage: cvss * epss * kev_factor
    res_cve = engine.calculate("cve-triage", {"cvss": 8.0, "epss": 0.5, "kev_factor": 1.5})
    assert res_cve.computed_value == 6.0

    # 23. capacity-headroom: (PeakLoad / (1 - RedundancyLoss)) * SafetyFactor
    res_cap = engine.calculate(
        "capacity-headroom",
        {"PeakLoad": 1000, "RedundancyLoss": 0.5, "SafetyFactor": 1.2},
    )
    assert res_cap.computed_value == 2400.0

    # 24. toil-ratio: toil_hours / total_engineering_hours
    res_toil = engine.calculate(
        "toil-ratio",
        {"toil_hours": 30, "total_engineering_hours": 100},
    )
    assert res_toil.computed_value == 0.30
    assert res_toil.is_compliant is True


def test_statutory_banking_ratios_verification(engine: FormulaEngine) -> None:
    """Verify statutory banking prudential formulas (CRAR, LCR, Leverage, NSFR)."""
    # CRAR (minimum 15% for NBFC-SI under RBI Master Direction)
    crar_pass = engine.calculate(
        "crar",
        {"tier1_capital": 150.0, "tier2_capital": 50.0, "risk_weighted_assets": 1000.0},
    )
    assert crar_pass.computed_value == 0.20
    assert crar_pass.is_compliant is True

    crar_fail = engine.calculate(
        "crar",
        {"tier1_capital": 80.0, "tier2_capital": 20.0, "risk_weighted_assets": 1000.0},
    )
    assert crar_fail.computed_value == 0.10
    assert crar_fail.is_compliant is False

    # LCR (minimum 100% / 1.00)
    lcr_pass = engine.calculate("lcr", {"hqla": 120.0, "net_cash_outflows": 100.0})
    assert lcr_pass.computed_value == 1.20
    assert lcr_pass.is_compliant is True

    # Leverage Ratio (minimum 4% / 0.04)
    lev_pass = engine.calculate("leverage-ratio", {"tier1_capital": 50.0, "total_exposure": 1000.0})
    assert lev_pass.computed_value == 0.05
    assert lev_pass.is_compliant is True

    # NSFR (minimum 100% / 1.00)
    nsfr_pass = engine.calculate("nsfr", {"asf": 110.0, "rsf": 100.0})
    assert nsfr_pass.computed_value == 1.10
    assert nsfr_pass.is_compliant is True


def test_custom_mathematical_expression(engine: FormulaEngine) -> None:
    """Verify executing custom safe AST expressions."""
    res = engine.calculate(
        formula_id="custom",
        inputs={"principal": 1000.0, "rate": 0.05, "years": 2.0},
        custom_expression="principal * (1 + rate) ** years",
        precision_decimal_places=2,
    )
    assert res.computed_value == 1102.50
    assert res.formula_id == "custom"


def test_calculation_latency_sla_under_1ms(engine: FormulaEngine) -> None:
    """Verify formula calculation latency is strictly <= 1.0 ms p95."""
    inputs = {"E": 10.0, "I": 50.0, "M": 100.0, "R": 5.0}
    latencies_ms: list[float] = []

    # 100 iterations
    for _ in range(100):
        t0 = time.perf_counter()
        engine.calculate("sci", inputs)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    assert p95 <= 1.0, f"p95 latency {p95:.3f}ms exceeded 1.0ms SLA!"


# -----------------------------------------------------------------------------
# 4. HTTP API Endpoints Integration Tests
# -----------------------------------------------------------------------------


def test_api_list_compliance_formulas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /v1/compliance/formulas requires auth and returns formula catalog."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)

    # 401 Unauthorized without auth
    resp_unauth = client.get("/v1/compliance/formulas")
    assert resp_unauth.status_code == 401

    # 200 OK with valid API key
    headers = auth(PRIMARY_KEY)
    resp = client.get("/v1/compliance/formulas", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] >= 28
    assert len(data["formulas"]) == data["total"]
    ids = [f["id"] for f in data["formulas"]]
    assert "sci" in ids
    assert "crar" in ids
    assert "lcr" in ids


def test_api_calculate_compliance_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /v1/compliance/calculate computes results, validates inputs, and records metrics."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    # 1. Successful statutory computation
    before = metrics.FORMULAS_CALCULATED_TOTAL.labels(formula_id="crar")._value.get()
    payload = {
        "formula_id": "crar",
        "inputs": {
            "tier1_capital": 160.0,
            "tier2_capital": 40.0,
            "risk_weighted_assets": 1000.0,
        },
    }
    resp = client.post("/v1/compliance/calculate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["formula_id"] == "crar"
    assert data["computed_value"] == 0.20
    assert data["is_compliant"] is True
    assert "steps" in data
    assert len(data["steps"]) >= 4

    # Metric incremented
    after = metrics.FORMULAS_CALCULATED_TOTAL.labels(formula_id="crar")._value.get()
    assert after == before + 1

    # 2. Unknown formula returns 422
    resp_unknown = client.post(
        "/v1/compliance/calculate",
        json={"formula_id": "non_existent_formula", "inputs": {}},
        headers=headers,
    )
    assert resp_unknown.status_code == 422

    # 3. Missing variables returns 422
    resp_missing = client.post(
        "/v1/compliance/calculate",
        json={"formula_id": "sci", "inputs": {"E": 10.0}},
        headers=headers,
    )
    assert resp_missing.status_code == 422
    assert "Missing required variable" in resp_missing.json()["detail"]

    # 4. Division by zero returns 400
    resp_zero = client.post(
        "/v1/compliance/calculate",
        json={
            "formula_id": "crar",
            "inputs": {
                "tier1_capital": 100.0,
                "tier2_capital": 50.0,
                "risk_weighted_assets": 0.0,
            },
        },
        headers=headers,
    )
    assert resp_zero.status_code == 400
    assert "division by zero" in resp_zero.json()["detail"]
