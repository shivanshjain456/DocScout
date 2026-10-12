"""Statutory Formula Computational Engine (FEAT-021).

In-engine AST parser and safe mathematical evaluator executing statutory
and systems engineering formulas (e.g. Software Carbon Intensity, Error Budget Burn Rate,
MC/DC Bounds, Little's Law, Capital Adequacy / CRAR, Liquidity Coverage Ratio / LCR).
Zero reliance on untrusted eval() or exec(); strict AST node whitelisting.
"""

from __future__ import annotations

import ast
import math
import operator
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import structlog

from app.api.models import FormulaCalcResult, FormulaDefinition

logger = structlog.get_logger("docscout.compliance.formula_engine")


class FormulaEngineError(Exception):
    """Base exception for statutory formula computation errors."""


class UnknownFormulaError(FormulaEngineError):
    """Raised when an unrecognized formula identifier is requested."""


class MissingVariableError(FormulaEngineError):
    """Raised when one or more required input variables are missing."""

    def __init__(self, formula_id: str, missing_vars: list[str]) -> None:
        self.formula_id = formula_id
        self.missing_vars = missing_vars
        super().__init__(
            f"Missing required variable(s) for formula '{formula_id}': {', '.join(missing_vars)}"
        )


class MathDomainError(FormulaEngineError):
    """Raised on division by zero, negative logarithms, or out-of-domain calculations."""


class SecurityViolationError(FormulaEngineError):
    """Raised when an expression contains non-whitelisted AST nodes or unsafe calls."""


# Whitelisted binary and unary operators
_OPERATORS: dict[type[ast.AST], Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Whitelisted safe mathematical functions
_SAFE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "sum": sum,
}


class SafeMathEvaluator:
    """Evaluates mathematical expressions safely using Python AST inspection.

    Guarantees no arbitrary code execution: AST nodes outside the safe mathematical
    subset are rejected before evaluation.
    """

    def __init__(self) -> None:
        self._operators = _OPERATORS
        self._functions = _SAFE_FUNCTIONS

    def evaluate(self, expression: str, variables: dict[str, float]) -> float:
        """Parse and safely evaluate a mathematical expression against a variable dict."""
        if not expression or not expression.strip():
            raise MathDomainError("Expression cannot be empty.")

        # Clean string: replace common typography characters with valid math operators
        clean_expr = (
            expression.replace("×", "*")
            .replace("÷", "/")
            .replace("–", "-")
            .replace("—", "-")
            .replace("^", "**")
        )
        clean_expr = re.sub(r"(?<=\d|\))\s*[xX]\s*(?=\d|\()", " * ", clean_expr)

        try:
            parsed = ast.parse(clean_expr, mode="eval")
        except SyntaxError as exc:
            raise MathDomainError(
                f"Malformed mathematical expression '{expression}': {exc}"
            ) from exc

        return float(self._eval_node(parsed.body, variables))

    def _eval_node(self, node: ast.AST, variables: dict[str, float]) -> Any:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise SecurityViolationError(f"Non-numeric literal '{node.value!r}' is forbidden.")
            if isinstance(node.value, int):
                return int(node.value)
            val = float(node.value)
            if not math.isfinite(val):
                raise MathDomainError("Non-finite numeric constant encountered.")
            return val

        if isinstance(node, ast.Name):
            # Check exact match first, then case-insensitive match
            if node.id in variables:
                val = float(variables[node.id])
            else:
                lower_lookup = {k.lower(): v for k, v in variables.items()}
                if node.id.lower() in lower_lookup:
                    val = float(lower_lookup[node.id.lower()])
                else:
                    raise MissingVariableError("custom_expr", [node.id])

            if not math.isfinite(val):
                raise MathDomainError(f"Variable '{node.id}' has non-finite value '{val}'.")
            return val

        if isinstance(node, ast.UnaryOp):
            uop_type = type(node.op)
            if uop_type not in self._operators:
                raise SecurityViolationError(
                    f"Unary operator '{uop_type.__name__}' is not permitted."
                )
            operand = self._eval_node(node.operand, variables)
            res = self._operators[uop_type](operand)
            if not math.isfinite(res):
                raise MathDomainError("Unary calculation yielded non-finite result.")
            return res

        if isinstance(node, ast.BinOp):
            bop_type = type(node.op)
            if bop_type not in self._operators:
                raise SecurityViolationError(
                    f"Binary operator '{bop_type.__name__}' is not permitted."
                )
            left = self._eval_node(node.left, variables)
            right = self._eval_node(node.right, variables)

            # Division by zero guard
            if bop_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0.0:
                raise MathDomainError("Math domain error: division by zero.")

            try:
                res = self._operators[bop_type](left, right)
            except ZeroDivisionError as exc:
                raise MathDomainError("Math domain error: division by zero.") from exc
            except OverflowError as exc:
                raise MathDomainError("Math domain error: arithmetic overflow.") from exc

            if not math.isfinite(res):
                raise MathDomainError("Calculation yielded non-finite result.")
            return res

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise SecurityViolationError("Dynamic function dispatch is prohibited.")
            func_name = node.func.id
            if func_name not in self._functions:
                raise SecurityViolationError(
                    f"Function call '{func_name}' is not in safe function whitelist."
                )

            args = [self._eval_node(arg, variables) for arg in node.args]
            try:
                res = self._functions[func_name](*args)
            except (ValueError, ZeroDivisionError) as exc:
                raise MathDomainError(
                    f"Math domain error in function '{func_name}': {exc}"
                ) from exc

            if not math.isfinite(res):
                raise MathDomainError(f"Function '{func_name}' yielded non-finite result.")
            return res

        raise SecurityViolationError(
            f"AST node type '{type(node).__name__}' is strictly forbidden."
        )


@dataclass(frozen=True)
class FormulaEngineConfig:
    """Configuration parameters for statutory formula computation."""

    max_calc_duration_ms: int = 50
    precision_decimal_places: int = 4


@dataclass(frozen=True)
class RegisteredFormula:
    """Internal definition of a verifiable compliance formula."""

    id: str
    name: str
    domain: str
    expression: str
    eval_expression: str
    required_variables: list[str]
    variable_descriptions: dict[str, str]
    unit: str
    standard: str | list[str] | None = None
    note: str | None = None
    statutory_threshold: str | None = None


# Registry of 24 canonical taxonomy formulas + 4 banking statutory compliance ratios
_REGISTERED_FORMULAS: list[RegisteredFormula] = [
    RegisteredFormula(
        id="sci",
        name="Software Carbon Intensity",
        domain="green-software-sustainability",
        expression="SCI = (E * I + M) / R",
        eval_expression="(E * I + M) / R",
        required_variables=["E", "I", "M", "R"],
        variable_descriptions={
            "E": "Energy consumed in kWh",
            "I": "Carbon intensity of electricity (gCO2eq/kWh)",
            "M": "Embodied emissions allocated to software (gCO2eq)",
            "R": "Functional unit (per user, transaction, API call)",
        },
        unit="gCO2eq / functional unit",
        standard="ISO/IEC 21031:2024",
        note="A rate, not a total. Totals cannot tell you whether software became more efficient.",
    ),
    RegisteredFormula(
        id="error-budget",
        name="Error budget",
        domain="reliability-resilience-chaos",
        expression="ErrorBudget = 1 - SLO",
        eval_expression="1 - SLO",
        required_variables=["SLO"],
        variable_descriptions={
            "SLO": "Service level objective as a fraction (e.g. 0.999 for 99.9%)",
        },
        unit="fraction",
        note="A 99.95% monthly availability SLO permits about 21.6 minutes of downtime in a 30-day window.",
    ),
    RegisteredFormula(
        id="burn-rate",
        name="Error budget burn rate",
        domain="reliability-resilience-chaos",
        expression="BurnRate = ErrorsObserved / Budget",
        eval_expression="ErrorsObserved / Budget",
        required_variables=["ErrorsObserved", "Budget"],
        variable_descriptions={
            "ErrorsObserved": "Errors observed in the measurement window",
            "Budget": "Allowed error budget for the period",
        },
        unit="burn rate multiplier",
        note="Burn rate of 1.0 consumes 100% of error budget over the period. >14.4 triggers page alerts.",
    ),
    RegisteredFormula(
        id="mcdc",
        name="MC/DC test count bound",
        domain="coverage-adequacy-code-health",
        expression="Tests = N + 1",
        eval_expression="N + 1",
        required_variables=["N"],
        variable_descriptions={
            "N": "Number of independent decision conditions",
        },
        unit="test cases",
        standard=["DO-178C", "ISO 26262 Part 6 Table 9", "IEC 61508 Part 3"],
        note="MC/DC reduces full condition coverage from 2^N to roughly N+1 cases while preserving fault-detection power.",
    ),
    RegisteredFormula(
        id="mutation-score",
        name="Mutation score",
        domain="coverage-adequacy-code-health",
        expression="MutationScore = KilledMutants / (TotalMutants - EquivalentMutants)",
        eval_expression="KilledMutants / (TotalMutants - EquivalentMutants)",
        required_variables=["KilledMutants", "TotalMutants", "EquivalentMutants"],
        variable_descriptions={
            "KilledMutants": "Mutants killed by test suite",
            "TotalMutants": "Total mutants generated",
            "EquivalentMutants": "Semantically equivalent undetected mutants",
        },
        unit="ratio",
        note="The equivalent-mutant problem is why 100% is not attainable; interpret rather than target.",
    ),
    RegisteredFormula(
        id="dre",
        name="Defect Removal Efficiency",
        domain="coverage-adequacy-code-health",
        expression="DRE = DefectsFoundInPhase / (DefectsFoundInPhase + DefectsEscapedFromPhase)",
        eval_expression="DefectsFoundInPhase / (DefectsFoundInPhase + DefectsEscapedFromPhase)",
        required_variables=["DefectsFoundInPhase", "DefectsEscapedFromPhase"],
        variable_descriptions={
            "DefectsFoundInPhase": "Defects identified during phase",
            "DefectsEscapedFromPhase": "Defects found in subsequent phases",
        },
        unit="ratio",
        note="Measures each gate's yield so effort can be reallocated to the weakest gate.",
    ),
    RegisteredFormula(
        id="littles-law",
        name="Little's Law",
        domain="performance-capacity-engineering",
        expression="L = arrival_rate * W",
        eval_expression="arrival_rate * W",
        required_variables=["arrival_rate", "W"],
        variable_descriptions={
            "arrival_rate": "Average arrival rate (requests per second / lambda)",
            "W": "Average wait / residency time in seconds",
        },
        unit="concurrent items",
        note="The sanity check that catches impossible capacity models and reveals hidden queueing.",
    ),
    RegisteredFormula(
        id="usl",
        name="Universal Scalability Law",
        domain="performance-capacity-engineering",
        expression="C(N) = N / (1 + a * (N - 1) + b * N * (N - 1))",
        eval_expression="N / (1 + a * (N - 1) + b * N * (N - 1))",
        required_variables=["N", "a", "b"],
        variable_descriptions={
            "N": "Concurrency level or worker count",
            "a": "Contention coefficient",
            "b": "Coherency coefficient",
        },
        unit="relative capacity",
        note="Predicts the throughput knee. With b > 0 the model peaks and then declines, explaining why adding capacity can reduce throughput.",
    ),
    RegisteredFormula(
        id="amdahl",
        name="Amdahl's Law",
        domain="performance-capacity-engineering",
        expression="Speedup = 1 / ((1 - p) + p / s)",
        eval_expression="1 / ((1 - p) + p / s)",
        required_variables=["p", "s"],
        variable_descriptions={
            "p": "Parallelizable fraction of workload (0 to 1)",
            "s": "Speedup factor of parallelized portion",
        },
        unit="speedup factor",
        note="Bounds the end-to-end gain from parallelisation; prevents funding work that cannot pay off.",
    ),
    RegisteredFormula(
        id="apdex",
        name="Throughput saturation / knee",
        domain="performance-capacity-engineering",
        expression="DeliveryRatio = Throughput / Load",
        eval_expression="Throughput / Load",
        required_variables=["Throughput", "Load"],
        variable_descriptions={
            "Throughput": "Completed work per unit time",
            "Load": "Offered demand",
        },
        unit="delivery ratio",
        note="Beyond the knee, added demand degrades latency without increasing throughput.",
    ),
    RegisteredFormula(
        id="disparate-impact",
        name="Disparate impact ratio (4/5ths rule)",
        domain="ai-ml-llm-assurance",
        expression="DIR = SelectionRate_protected / SelectionRate_reference",
        eval_expression="SelectionRate_protected / SelectionRate_reference",
        required_variables=["SelectionRate_protected", "SelectionRate_reference"],
        variable_descriptions={
            "SelectionRate_protected": "Favourable-outcome rate for protected demographic",
            "SelectionRate_reference": "Favourable-outcome rate for reference group",
        },
        unit="ratio",
        standard=["US EEOC Uniform Guidelines", "NIST SP 1270"],
        statutory_threshold=">= 0.80",
        note="A common US baseline: below 0.8 indicates adverse impact. Necessary but not sufficient.",
    ),
    RegisteredFormula(
        id="ece",
        name="Expected Calibration Error",
        domain="ai-ml-llm-assurance",
        expression="ECE = (n_b / N) * abs(acc_b - conf_b)",
        eval_expression="(n_b / N) * abs(acc_b - conf_b)",
        required_variables=["n_b", "N", "acc_b", "conf_b"],
        variable_descriptions={
            "n_b": "Samples in bin b",
            "N": "Total dataset samples",
            "acc_b": "Observed empirical accuracy in bin",
            "conf_b": "Mean predicted confidence in bin",
        },
        unit="calibration error",
        note="An uncalibrated model silently misleads operators setting decision thresholds.",
    ),
    RegisteredFormula(
        id="faithfulness",
        name="Faithfulness / supported-claim ratio",
        domain="ai-ml-llm-assurance",
        expression="Faithfulness = supported_claims / total_claims",
        eval_expression="supported_claims / total_claims",
        required_variables=["supported_claims", "total_claims"],
        variable_descriptions={
            "supported_claims": "Atomic factual claims entailed by context",
            "total_claims": "Total factual claims asserted in generation",
        },
        unit="ratio",
        statutory_threshold=">= 0.95",
        note="Claim-level decomposition is what distinguishes one fabricated citation from total fabrication.",
    ),
    RegisteredFormula(
        id="hallucination-rate",
        name="Hallucination rate",
        domain="ai-ml-llm-assurance",
        expression="HallucinationRate = unsupported_answers / total_answers",
        eval_expression="unsupported_answers / total_answers",
        required_variables=["unsupported_answers", "total_answers"],
        variable_descriptions={
            "unsupported_answers": "Answers containing 1 or more unsupported claims",
            "total_answers": "Total evaluated answers",
        },
        unit="fraction",
        statutory_threshold="<= 0.05",
        note="Report alongside a confidence interval on a domain-specific eval set.",
    ),
    RegisteredFormula(
        id="asr",
        name="Attack success rate",
        domain="ai-ml-llm-assurance",
        expression="ASR = successful_attacks / total_attempts",
        eval_expression="successful_attacks / total_attempts",
        required_variables=["successful_attacks", "total_attempts"],
        variable_descriptions={
            "successful_attacks": "Attacks breaching defensive constraints",
            "total_attempts": "Total adversarial attempts probed",
        },
        unit="ratio",
        standard=["OWASP Top 10 for LLM Applications 2025", "MITRE ATLAS"],
        statutory_threshold="<= 0.02",
        note="Report per category and weight by impact; a tone change and data exfiltration are not comparable.",
    ),
    RegisteredFormula(
        id="srm",
        name="Sample ratio mismatch",
        domain="experimentation-measurement",
        expression="ChiSquare = ((observed - expected) ** 2) / expected",
        eval_expression="((observed - expected) ** 2) / expected",
        required_variables=["observed", "expected"],
        variable_descriptions={
            "observed": "Observed sample count in variant",
            "expected": "Expected sample count under nominal assignment",
        },
        unit="chi-square statistic",
        note="The highest-signal indicator that an experiment's randomisation or logging is broken.",
    ),
    RegisteredFormula(
        id="cuped",
        name="CUPED variance reduction",
        domain="experimentation-measurement",
        expression="Y_cuped = Y - theta * (X - mean_X)",
        eval_expression="Y - theta * (X - mean_X)",
        required_variables=["Y", "theta", "X", "mean_X"],
        variable_descriptions={
            "Y": "Observed outcome metric",
            "theta": "Covariance/variance regression coefficient",
            "X": "Pre-experiment covariate value",
            "mean_X": "Mean pre-experiment covariate",
        },
        unit="adjusted metric value",
        note="Routinely reduces required sample size by tens of percent at essentially no cost.",
    ),
    RegisteredFormula(
        id="power",
        name="Sample size for a two-sample test",
        domain="experimentation-measurement",
        expression="n = 2 * ((z_alpha_2 + z_beta) ** 2) * (sigma ** 2) / (delta ** 2)",
        eval_expression="2 * ((z_alpha_2 + z_beta) ** 2) * (sigma ** 2) / (delta ** 2)",
        required_variables=["z_alpha_2", "z_beta", "sigma", "delta"],
        variable_descriptions={
            "z_alpha_2": "Critical value for significance level alpha/2 (e.g. 1.96 for 0.05)",
            "z_beta": "Critical value for statistical power 1-beta (e.g. 0.84 for 80% power)",
            "sigma": "Standard deviation of metric",
            "delta": "Minimum detectable effect (MDE)",
        },
        unit="sample size per variant",
        note="Underpowered experiments produce false negatives and inflated effect estimates.",
    ),
    RegisteredFormula(
        id="coordinated-omission",
        name="Coordinated omission correction",
        domain="performance-capacity-engineering",
        expression="TrueLatency = actual_latency + stall_duration",
        eval_expression="actual_latency + stall_duration",
        required_variables=["actual_latency", "stall_duration"],
        variable_descriptions={
            "actual_latency": "Measured service response latency",
            "stall_duration": "Queuing delay prior to actual request transmission",
        },
        unit="ms",
        note="A generator measuring from actual send time understates tail latency by orders of magnitude.",
    ),
    RegisteredFormula(
        id="t-way",
        name="Combinatorial coverage reduction",
        domain="test-design-oracles-generative",
        expression="TestCases = k ** t",
        eval_expression="k ** t",
        required_variables=["k", "t"],
        variable_descriptions={
            "k": "Parameter domain cardinality (values per factor)",
            "t": "Interaction strength (usually 2 for pairwise)",
        },
        unit="test configurations",
        note="Pairwise coverage captures the large majority of interaction defects at a tiny fraction of the case count.",
    ),
    RegisteredFormula(
        id="coverage-gap",
        name="Structural coverage obligation gap",
        domain="embedded-safety-critical",
        expression="CoverageGap = required_coverage - achieved_coverage",
        eval_expression="required_coverage - achieved_coverage",
        required_variables=["required_coverage", "achieved_coverage"],
        variable_descriptions={
            "required_coverage": "Mandated structural coverage percentage (e.g. 1.0 for Level A MC/DC)",
            "achieved_coverage": "Actual verified coverage percentage achieved",
        },
        unit="coverage percentage gap",
        standard=[
            "DO-178C Table A-7",
            "ISO 26262 Part 6 Table 9",
            "IEC 61508 Part 3 Table B-2",
            "IEC 62304",
        ],
        statutory_threshold="<= 0.00",
        note="DO-178C Level A requires MC/DC; ISO 26262 rates MC/DC highly recommended at ASIL D.",
    ),
    RegisteredFormula(
        id="cve-triage",
        name="Exploit-probability-weighted triage",
        domain="security-appsec-testing",
        expression="Priority = cvss * epss * kev_factor",
        eval_expression="cvss * epss * kev_factor",
        required_variables=["cvss", "epss", "kev_factor"],
        variable_descriptions={
            "cvss": "CVSS base score (0.0 - 10.0)",
            "epss": "EPSS exploit prediction probability (0.0 - 1.0)",
            "kev_factor": "Known Exploited Vulnerabilities weight multiplier (e.g. 1.5 - 2.0)",
        },
        unit="risk priority score",
        standard=["CVSS", "EPSS", "CISA KEV"],
        note="Severity alone is the wrong sort order. KEV membership and EPSS probability are far better predictors.",
    ),
    RegisteredFormula(
        id="capacity-headroom",
        name="Failure-tolerant capacity",
        domain="performance-capacity-engineering",
        expression="RequiredCapacity = (PeakLoad / (1 - RedundancyLoss)) * SafetyFactor",
        eval_expression="(PeakLoad / (1 - RedundancyLoss)) * SafetyFactor",
        required_variables=["PeakLoad", "RedundancyLoss", "SafetyFactor"],
        variable_descriptions={
            "PeakLoad": "Peak observed system load (RPS or concurrency)",
            "RedundancyLoss": "Fraction of capacity lost during failover (0.0 to 1.0)",
            "SafetyFactor": "Buffer safety factor multiplier (e.g. 1.2 for 20% head room)",
        },
        unit="required capacity units",
        note="Running at the saturation knee means any single failure becomes an outage; failover capacity must absorb surviving region load.",
    ),
    RegisteredFormula(
        id="toil-ratio",
        name="Toil ratio",
        domain="reliability-resilience-chaos",
        expression="ToilRatio = toil_hours / total_engineering_hours",
        eval_expression="toil_hours / total_engineering_hours",
        required_variables=["toil_hours", "total_engineering_hours"],
        variable_descriptions={
            "toil_hours": "Hours spent on repetitive manual operational tasks",
            "total_engineering_hours": "Total engineering hours logged",
        },
        unit="ratio",
        statutory_threshold="<= 0.50",
        note="SRE guidance treats sustained toil above roughly half of operational time as a project-level problem, not an individual one.",
    ),
    # Banking Statutory Prudential Compliance Ratios (Pillar 3 Highlights)
    RegisteredFormula(
        id="crar",
        name="Capital to Risk-Weighted Assets Ratio",
        domain="banking-prudential-capital",
        expression="CRAR = (tier1_capital + tier2_capital) / risk_weighted_assets",
        eval_expression="(tier1_capital + tier2_capital) / risk_weighted_assets",
        required_variables=["tier1_capital", "tier2_capital", "risk_weighted_assets"],
        variable_descriptions={
            "tier1_capital": "Core equity Tier 1 capital in Cr",
            "tier2_capital": "Supplementary Tier 2 capital in Cr",
            "risk_weighted_assets": "Total risk-weighted assets (RWA) in Cr",
        },
        unit="ratio",
        standard="RBI Master Direction - Basel III Capital Regulations",
        statutory_threshold=">= 0.15",
        note="Mandatory statutory prudential solvency ratio under RBI Master Directions (minimum 15% for NBFC-SI / 9% for commercial banks).",
    ),
    RegisteredFormula(
        id="lcr",
        name="Liquidity Coverage Ratio",
        domain="banking-liquidity-risk",
        expression="LCR = hqla / net_cash_outflows",
        eval_expression="hqla / net_cash_outflows",
        required_variables=["hqla", "net_cash_outflows"],
        variable_descriptions={
            "hqla": "Stock of high-quality liquid assets",
            "net_cash_outflows": "Total net cash outflows over 30 days stress period",
        },
        unit="ratio",
        standard="RBI Liquidity Risk Management Framework",
        statutory_threshold=">= 1.00",
        note="Ensures financial institutions hold sufficient HQLA to survive a 30-day acute liquidity stress scenario.",
    ),
    RegisteredFormula(
        id="leverage-ratio",
        name="Basel III Leverage Ratio",
        domain="banking-prudential-capital",
        expression="LeverageRatio = tier1_capital / total_exposure",
        eval_expression="tier1_capital / total_exposure",
        required_variables=["tier1_capital", "total_exposure"],
        variable_descriptions={
            "tier1_capital": "Tier 1 capital",
            "total_exposure": "Total on- and off-balance sheet leverage exposure",
        },
        unit="ratio",
        standard="RBI Basel III Capital Regulations",
        statutory_threshold=">= 0.04",
        note="Non-risk-based backstop to prevent excessive balance sheet gearing (minimum 4% for banks).",
    ),
    RegisteredFormula(
        id="nsfr",
        name="Net Stable Funding Ratio",
        domain="banking-liquidity-risk",
        expression="NSFR = asf / rsf",
        eval_expression="asf / rsf",
        required_variables=["asf", "rsf"],
        variable_descriptions={
            "asf": "Available stable funding",
            "rsf": "Required stable funding",
        },
        unit="ratio",
        standard="RBI Master Direction - Basel III NSFR",
        statutory_threshold=">= 1.00",
        note="Requires banks to maintain a stable funding profile in relation to their assets over a 1-year horizon.",
    ),
]


class FormulaEngine:
    """Computational execution engine for statutory and systems compliance formulas."""

    _instance: ClassVar[FormulaEngine | None] = None

    def __init__(self, config: FormulaEngineConfig | None = None) -> None:
        self.config = config or FormulaEngineConfig()
        self.evaluator = SafeMathEvaluator()
        self._formulas: dict[str, RegisteredFormula] = {f.id: f for f in _REGISTERED_FORMULAS}

    def list_formulas(self) -> list[FormulaDefinition]:
        """List all available verifiable compliance formulas."""
        return [
            FormulaDefinition(
                id=f.id,
                name=f.name,
                domain=f.domain,
                expression=f.expression,
                required_variables=f.required_variables,
                variable_descriptions=f.variable_descriptions,
                unit=f.unit,
                standard=f.standard,
                note=f.note,
                statutory_threshold=f.statutory_threshold,
            )
            for f in self._formulas.values()
        ]

    def get_formula(self, formula_id: str) -> FormulaDefinition | None:
        """Lookup metadata for a specific formula ID."""
        f = self._formulas.get(formula_id)
        if f is None:
            return None
        return FormulaDefinition(
            id=f.id,
            name=f.name,
            domain=f.domain,
            expression=f.expression,
            required_variables=f.required_variables,
            variable_descriptions=f.variable_descriptions,
            unit=f.unit,
            standard=f.standard,
            note=f.note,
            statutory_threshold=f.statutory_threshold,
        )

    def get_registered_formula(self, formula_id: str) -> RegisteredFormula | None:
        """Lookup internal RegisteredFormula containing eval_expression for high-performance simulation."""
        return self._formulas.get(formula_id)

    def calculate(
        self,
        formula_id: str,
        inputs: dict[str, float],
        custom_expression: str | None = None,
        precision_decimal_places: int | None = None,
    ) -> FormulaCalcResult:
        """Compute the result of a statutory formula with arbitrary precision and audit trail."""
        t0 = time.perf_counter()
        places = (
            precision_decimal_places
            if precision_decimal_places is not None
            else self.config.precision_decimal_places
        )

        # Handle custom ad-hoc expression if supplied
        if formula_id == "custom":
            if not custom_expression:
                raise MathDomainError("custom_expression must be supplied for 'custom' formula_id.")
            raw_val = self.evaluator.evaluate(custom_expression, inputs)
            computed_val = round(raw_val, places)
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            return FormulaCalcResult(
                formula_id="custom",
                name="Custom Mathematical Expression",
                expression=custom_expression,
                computed_value=computed_val,
                unit="custom unit",
                steps=[
                    f"Inputs: {inputs}",
                    f"Expression: {custom_expression}",
                    f"Computed value: {computed_val}",
                ],
                duration_ms=duration_ms,
            )

        reg_formula = self._formulas.get(formula_id)
        if reg_formula is None:
            raise UnknownFormulaError(f"Unknown formula ID '{formula_id}'.")

        # Map aliases in inputs (e.g. 'lambda' -> 'arrival_rate' for Little's Law)
        normalized_inputs = dict(inputs)
        if formula_id == "littles-law":
            if "lambda" in normalized_inputs and "arrival_rate" not in normalized_inputs:
                normalized_inputs["arrival_rate"] = normalized_inputs["lambda"]

        # Check required variables
        missing = [
            var
            for var in reg_formula.required_variables
            if var not in normalized_inputs
            and var.lower() not in {k.lower(): v for k, v in normalized_inputs.items()}
        ]
        if missing:
            raise MissingVariableError(formula_id, missing)

        # Evaluate the mathematical expression
        raw_val = self.evaluator.evaluate(reg_formula.eval_expression, normalized_inputs)
        computed_val = round(raw_val, places)

        # Check statutory threshold compliance if defined
        is_compliant: bool | None = None
        threshold_step = "No statutory threshold defined."
        if reg_formula.statutory_threshold:
            thresh_expr = reg_formula.statutory_threshold.strip()
            match = re.match(r"^([><]=?|==)\s*(-?\d+(?:\.\d+)?)$", thresh_expr)
            if match:
                op, limit_str = match.groups()
                limit_val = float(limit_str)
                if op == ">=":
                    is_compliant = computed_val >= limit_val
                elif op == ">":
                    is_compliant = computed_val > limit_val
                elif op == "<=":
                    is_compliant = computed_val <= limit_val
                elif op == "<":
                    is_compliant = computed_val < limit_val
                elif op == "==":
                    is_compliant = computed_val == limit_val
                status_str = "COMPLIANT" if is_compliant else "NON-COMPLIANT"
                threshold_step = (
                    f"Statutory Threshold: {computed_val} {op} {limit_val} -> {status_str}"
                )

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        steps = [
            f"Formula: {reg_formula.name} ({reg_formula.expression})",
            f"Input Variables: {inputs}",
            f"Evaluated Expression: {reg_formula.eval_expression}",
            f"Computed Value: {computed_val} {reg_formula.unit}",
            threshold_step,
        ]

        logger.info(
            "formula_calculated",
            formula_id=formula_id,
            computed_value=computed_val,
            is_compliant=is_compliant,
            duration_ms=duration_ms,
        )

        return FormulaCalcResult(
            formula_id=reg_formula.id,
            name=reg_formula.name,
            expression=reg_formula.expression,
            computed_value=computed_val,
            unit=reg_formula.unit,
            standard=reg_formula.standard,
            note=reg_formula.note,
            statutory_threshold=reg_formula.statutory_threshold,
            is_compliant=is_compliant,
            steps=steps,
            duration_ms=duration_ms,
        )

    @classmethod
    def get_default(cls) -> FormulaEngine:
        """Process-wide singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_default_formula_engine() -> FormulaEngine:
    """Convenience accessor for default FormulaEngine."""
    return FormulaEngine.get_default()
