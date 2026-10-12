"""Compliance 'What-If' Sensitivity Simulator (FEAT-024).

Interactive calculation engine allowing risk officers and compliance engineers
to simulate how operational and balance-sheet variations impact statutory ratios
in real time. Computes partial derivatives, elasticities, sensitivity curves,
break-even breach points, and regulatory stress testing presets.
"""

from __future__ import annotations

import math
import time
from typing import Any, Literal

import structlog

from app.api.models import (
    ScenarioPoint,
    SensitivityResult,
    SimulationRequest,
    SimulationResponse,
    StressScenarioResult,
)
from app.compliance.boundary_validator import (
    StatutoryBoundaryValidator,
    get_default_boundary_validator,
)
from app.compliance.formula_engine import (
    FormulaEngine,
    MathDomainError,
    MissingVariableError,
    UnknownFormulaError,
    get_default_formula_engine,
)

logger = structlog.get_logger("docscout.compliance.simulator")


class SimulationError(Exception):
    """Base exception for sensitivity simulation errors."""


# ---------------------------------------------------------------------------
# Regulatory Stress Testing Presets
# ---------------------------------------------------------------------------

_STRESS_PRESETS: dict[str, list[dict[str, Any]]] = {
    "crar": [
        {
            "name": "RBI Moderate Asset Quality Stress",
            "description": "5% Tier 1 erosion and 10% risk-weighted assets growth",
            "delta_multipliers": {
                "tier1_capital": 0.95,
                "tier2_capital": 0.98,
                "risk_weighted_assets": 1.10,
            },
        },
        {
            "name": "RBI Severe Macroeconomic Downturn",
            "description": "15% Tier 1 impairment and 25% RWA escalation from credit rating downgrades",
            "delta_multipliers": {
                "tier1_capital": 0.85,
                "tier2_capital": 0.90,
                "risk_weighted_assets": 1.25,
            },
        },
    ],
    "lcr": [
        {
            "name": "Idiosyncratic 30-Day Liquidity Run",
            "description": "10% HQLA haircut and 25% acceleration in deposit run-offs",
            "delta_multipliers": {
                "hqla": 0.90,
                "net_cash_outflows": 1.25,
            },
        },
        {
            "name": "Systemic Interbank Liquidity Freeze",
            "description": "25% HQLA market valuation collapse and 40% net cash outflow spike",
            "delta_multipliers": {
                "hqla": 0.75,
                "net_cash_outflows": 1.40,
            },
        },
    ],
    "leverage-ratio": [
        {
            "name": "Off-Balance Sheet Credit Derivative Drawdown",
            "description": "20% surge in total leverage exposure from contingent commitments",
            "delta_multipliers": {
                "tier1_capital": 1.0,
                "total_exposure": 1.20,
            },
        },
        {
            "name": "Combined Gearing Stress",
            "description": "10% Tier 1 decline and 25% expansion in total exposure",
            "delta_multipliers": {
                "tier1_capital": 0.90,
                "total_exposure": 1.25,
            },
        },
    ],
    "nsfr": [
        {
            "name": "Wholesale Funding Roll-Over Freeze",
            "description": "10% loss of available stable funding and 10% extension of required stable assets",
            "delta_multipliers": {
                "asf": 0.90,
                "rsf": 1.10,
            },
        },
    ],
    "sci": [
        {
            "name": "Peak Traffic Brownout Surge",
            "description": "30% energy surge and 20% carbon intensity spike due to fossil peaker plants",
            "delta_multipliers": {
                "E": 1.30,
                "I": 1.20,
                "M": 1.0,
                "R": 1.0,
            },
        },
        {
            "name": "Hardware Amortization Shortfall",
            "description": "50% higher embodied emissions per functional transaction unit",
            "delta_multipliers": {
                "E": 1.0,
                "I": 1.0,
                "M": 1.50,
                "R": 1.0,
            },
        },
    ],
    "error-budget": [
        {
            "name": "Fast Burn Incident Multiplier",
            "description": "Triple error rate consumption over rolling observation window",
            "delta_multipliers": {
                "observed_error_rate": 3.0,
                "slo_target": 1.0,
            },
        },
    ],
}


class ComplianceSimulator:
    """Execution engine for sensitivity simulations and stress curve generation."""

    def __init__(
        self,
        engine: FormulaEngine | None = None,
        validator: StatutoryBoundaryValidator | None = None,
    ) -> None:
        self._engine = engine or get_default_formula_engine()
        self._validator = validator or get_default_boundary_validator()

    def simulate(self, request: SimulationRequest) -> SimulationResponse:
        """Execute a parameterized sensitivity simulation.

        Computes:
        - Baseline output and compliance status
        - Central difference partial derivatives
        - Elasticity multipliers
        - Parameter sweep curves
        - Regulatory break-even breach values
        - Pre-configured stress scenario results
        """
        start_ts = time.perf_counter()

        formula = self._engine.get_registered_formula(request.formula_id)
        if formula is None:
            available = [f.id for f in self._engine.list_formulas()]
            raise UnknownFormulaError(
                f"Formula '{request.formula_id}' not found. Available: {', '.join(available[:10])}"
            )

        # Validate required variables
        missing = [v for v in formula.required_variables if v not in request.base_inputs]
        if missing:
            raise MissingVariableError(request.formula_id, missing)

        for k, v in request.base_inputs.items():
            if not math.isfinite(v):
                raise MathDomainError(f"Variable '{k}' has non-finite value '{v}'")

        # 1. Baseline evaluation using fast AST evaluator
        eval_expr = formula.eval_expression

        def _fast_eval(inp: dict[str, float]) -> float:
            return float(self._engine.evaluator.evaluate(eval_expr, inp))

        baseline_val = _fast_eval(request.base_inputs)
        # Pre-resolve boundary rule once for fast status evaluation
        boundary_rule = None
        statutory_display = formula.statutory_threshold
        try:
            boundary_rule = self._validator.resolve_rule(
                formula.id, entity_type=request.entity_type
            )
            statutory_display = (
                f"{boundary_rule.operator} {boundary_rule.threshold_value:.2f} {boundary_rule.unit}"
            )
        except Exception as exc:
            logger.debug(
                "simulator.boundary_rule_resolve_failed",
                formula_id=formula.id,
                error=str(exc),
            )

        def _fast_validate(
            val: float,
        ) -> tuple[Literal["COMPLIANT", "WARNING", "BREACH"] | None, float | None]:
            if boundary_rule is None:
                return None, None
            th = boundary_rule.threshold_value
            op = boundary_rule.operator
            ev = val
            if boundary_rule.unit == "percent" and formula.unit in ("ratio", "fraction"):
                ev = val * 100.0

            if op in (">=", ">"):
                mg = ev - th
                wc = round(th * (1.0 + 0.05), 6)
                if (op == ">=" and ev < th) or (op == ">" and ev <= th):
                    return "BREACH", round(mg, 4)
                if round(ev, 6) < wc:
                    return "WARNING", round(mg, 4)
                return "COMPLIANT", round(mg, 4)
            if op in ("<=", "<"):
                mg = th - ev
                wc = round(th * (1.0 - 0.05), 6)
                if (op == "<=" and ev > th) or (op == "<" and ev >= th):
                    return "BREACH", round(mg, 4)
                if round(ev, 6) > wc:
                    return "WARNING", round(mg, 4)
                return "COMPLIANT", round(mg, 4)
            return None, None

        # Baseline boundary status
        baseline_status, _ = _fast_validate(baseline_val)

        sensitivity_gradients: dict[str, float] = {}
        elasticities: dict[str, float] = {}
        sensitivities: list[SensitivityResult] = []
        scenario_curves: dict[str, list[ScenarioPoint]] = {}

        # 2. Variable-by-variable partial derivative & curve sweep
        for var in formula.required_variables:
            base_x = request.base_inputs[var]

            # Partial derivative via symmetric difference
            dx = max(0.0001, 0.005 * abs(base_x)) if base_x != 0.0 else 0.001

            inputs_plus = dict(request.base_inputs)
            inputs_plus[var] = base_x + dx

            inputs_minus = dict(request.base_inputs)
            inputs_minus[var] = base_x - dx

            try:
                val_plus = _fast_eval(inputs_plus)
                val_minus = _fast_eval(inputs_minus)
                deriv = (val_plus - val_minus) / (2.0 * dx)
            except Exception:
                deriv = 0.0

            if base_x != 0.0 and baseline_val != 0.0:
                elasticity = deriv * (base_x / baseline_val)
            else:
                elasticity = 0.0

            deriv_rounded = round(deriv, 6)
            elasticity_rounded = round(elasticity, 4)

            sensitivity_gradients[var] = deriv_rounded
            elasticities[var] = elasticity_rounded

            direction: Literal["positive", "negative", "neutral"] = "neutral"
            if deriv > 1e-6:
                direction = "positive"
            elif deriv < -1e-6:
                direction = "negative"

            # 3. Sweep curve generation
            points: list[ScenarioPoint] = []
            if var in request.deltas and request.deltas[var]:
                # User provided explicit deltas (multipliers or delta percentages)
                for step_idx, delta_pct in enumerate(request.deltas[var]):
                    sim_x = base_x * (1.0 + delta_pct)
                    sim_inputs = dict(request.base_inputs)
                    sim_inputs[var] = sim_x
                    try:
                        sim_val = _fast_eval(sim_inputs)
                        sim_status, sim_margin = _fast_validate(sim_val)

                        points.append(
                            ScenarioPoint(
                                step=step_idx + 1,
                                variable=var,
                                input_value=round(sim_x, 4),
                                delta_percentage=round(delta_pct * 100.0, 2),
                                computed_value=round(sim_val, 4),
                                status=sim_status,
                                margin=sim_margin,
                            )
                        )
                    except Exception as exc:
                        logger.debug(
                            "simulator.sweep_eval_failed",
                            variable=var,
                            error=str(exc),
                        )
                        continue
            elif request.sweep_variable is None or request.sweep_variable == var:
                # Automated evenly spaced sweep
                half_range = request.sweep_percentage_range
                steps = request.sweep_steps
                step_size = (2.0 * half_range) / (steps - 1) if steps > 1 else 0.0

                for i in range(steps):
                    pct = -half_range + (i * step_size)
                    sim_x = max(0.0, base_x * (1.0 + pct))
                    sim_inputs = dict(request.base_inputs)
                    sim_inputs[var] = sim_x

                    try:
                        sim_val = _fast_eval(sim_inputs)
                        sim_status, sim_margin = _fast_validate(sim_val)

                        points.append(
                            ScenarioPoint(
                                step=i + 1,
                                variable=var,
                                input_value=round(sim_x, 4),
                                delta_percentage=round(pct * 100.0, 2),
                                computed_value=round(sim_val, 4),
                                status=sim_status,
                                margin=sim_margin,
                            )
                        )
                    except Exception as exc:
                        logger.debug(
                            "simulator.sweep_eval_failed",
                            variable=var,
                            error=str(exc),
                        )
                        continue

            scenario_curves[var] = points

            # 4. Break-even breach search
            breach_point: float | None = None
            if points:
                # Look for status transition to BREACH in curve points
                for p in points:
                    if p.status == "BREACH":
                        breach_point = p.input_value
                        break

            sensitivities.append(
                SensitivityResult(
                    variable=var,
                    description=formula.variable_descriptions.get(var),
                    baseline_input=round(base_x, 4),
                    partial_derivative=deriv_rounded,
                    elasticity=elasticity_rounded,
                    direction=direction,
                    impact_rank=1,  # will rank below
                    breach_boundary_value=breach_point,
                )
            )

        # Sort and rank sensitivities by absolute elasticity
        sensitivities.sort(key=lambda s: abs(s.elasticity), reverse=True)
        ranked_sensitivities: list[SensitivityResult] = []
        for idx, s in enumerate(sensitivities):
            ranked_sensitivities.append(
                SensitivityResult(
                    variable=s.variable,
                    description=s.description,
                    baseline_input=s.baseline_input,
                    partial_derivative=s.partial_derivative,
                    elasticity=s.elasticity,
                    direction=s.direction,
                    impact_rank=idx + 1,
                    breach_boundary_value=s.breach_boundary_value,
                )
            )

        # 5. Regulatory Stress Presets Evaluation
        stress_tests: list[StressScenarioResult] = []
        preset_list = _STRESS_PRESETS.get(formula.id, [])
        for preset in preset_list:
            stress_inputs = dict(request.base_inputs)
            for var_k, mult in preset["delta_multipliers"].items():
                if var_k in stress_inputs:
                    stress_inputs[var_k] = round(stress_inputs[var_k] * mult, 4)

            try:
                stress_val = _fast_eval(stress_inputs)
                stress_delta = (
                    ((stress_val - baseline_val) / baseline_val) * 100.0
                    if baseline_val != 0.0
                    else 0.0
                )
                stress_status, _ = _fast_validate(stress_val)

                stress_tests.append(
                    StressScenarioResult(
                        name=preset["name"],
                        description=preset["description"],
                        inputs=stress_inputs,
                        computed_value=round(stress_val, 4),
                        delta_percentage_from_baseline=round(stress_delta, 2),
                        status=stress_status,
                    )
                )
            except Exception as exc:
                logger.debug(
                    "simulator.stress_eval_failed",
                    preset=preset.get("name"),
                    error=str(exc),
                )
                continue

        latency_ms = (time.perf_counter() - start_ts) * 1000.0

        return SimulationResponse(
            formula_id=formula.id,
            formula_name=formula.name,
            expression=formula.expression,
            unit=formula.unit,
            baseline_value=round(baseline_val, 4),
            baseline_status=baseline_status,
            statutory_threshold=statutory_display,
            sensitivity_gradients=sensitivity_gradients,
            elasticities=elasticities,
            sensitivities=ranked_sensitivities,
            scenario_curves=scenario_curves,
            stress_tests=stress_tests,
            latency_ms=round(latency_ms, 3),
        )


# Global singleton instance
_DEFAULT_COMPLIANCE_SIMULATOR: ComplianceSimulator | None = None


def get_default_compliance_simulator() -> ComplianceSimulator:
    """Return or lazily instantiate default compliance simulator."""
    global _DEFAULT_COMPLIANCE_SIMULATOR
    if _DEFAULT_COMPLIANCE_SIMULATOR is None:
        _DEFAULT_COMPLIANCE_SIMULATOR = ComplianceSimulator()
    return _DEFAULT_COMPLIANCE_SIMULATOR
