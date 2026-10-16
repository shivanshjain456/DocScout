"""Algorithmic & AI Impact Assessment Framework (FEAT-050).

Operationalizes the taxonomy's Algorithmic Impact Assessment and statutory
checklists under SEBI Algorithmic Trading Framework (Circular 2018/62),
SEBI AI/ML Reporting Framework, RBI Model Governance Guidelines, and
ISO/IEC 42001 (Artificial Intelligence Management System).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

ModelType = Literal[
    "algorithmic_trading",
    "credit_scoring",
    "llm_agent",
    "fraud_detection",
    "general_ai",
]


@dataclass(frozen=True)
class FailedControl:
    """Represents a failed statutory algorithmic control."""

    control_id: str
    title: str
    regulation_ref: str
    remedy: str


@dataclass(frozen=True)
class StatutoryControlRule:
    """Definition of a statutory control check for algorithmic/AI systems."""

    control_id: str
    title: str
    category: str
    weight: float
    regulation_ref: str
    mandatory_for: list[str]
    positive_patterns: list[re.Pattern[str]]
    negative_patterns: list[re.Pattern[str]]
    remedy: str


@dataclass
class AlgoImpactConfig:
    """Configuration for algorithmic impact evaluation."""

    strict_kill_switch_required: bool = True
    pass_threshold: float = 75.0


@dataclass
class AlgoAssessmentResult:
    """Result of an algorithmic impact assessment."""

    system_name: str
    model_type: str
    conformity_score: float
    status: Literal["CONFORMANT", "CONDITIONAL", "NON_CONFORMANT"]
    passed_controls: list[str]
    failed_controls: list[FailedControl]
    negative_flags: list[str]
    audit_certificate_id: str
    evaluated_at: datetime
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_name": self.system_name,
            "model_type": self.model_type,
            "conformity_score": self.conformity_score,
            "status": self.status,
            "passed_controls": self.passed_controls,
            "failed_controls": [
                {
                    "control_id": fc.control_id,
                    "title": fc.title,
                    "regulation_ref": fc.regulation_ref,
                    "remedy": fc.remedy,
                }
                for fc in self.failed_controls
            ],
            "negative_flags": self.negative_flags,
            "audit_certificate_id": self.audit_certificate_id,
            "evaluated_at": self.evaluated_at.isoformat(),
            "summary": self.summary,
        }


# Catalog of 8 statutory algorithmic and AI governance controls
STATUTORY_CONTROLS: list[StatutoryControlRule] = [
    StatutoryControlRule(
        control_id="ALGO-CTRL-01",
        title="Automated Kill Switch Mechanism",
        category="Operational Resilience & Circuit Breakers",
        weight=20.0,
        regulation_ref="SEBI Circular CIR/MRD/DP/24/2013 & SEBI/HO/MRD/DP/CIR/P/2018/62 Clause 3.2",
        mandatory_for=["algorithmic_trading", "llm_agent", "fraud_detection", "general_ai"],
        positive_patterns=[
            re.compile(r"\bkill[\s\-_]*switch(?:es)?\b", re.IGNORECASE),
            re.compile(
                r"\bemergency\s+(?:stop|halt|shutdown|cutoff|isolation)(?:s)?\b", re.IGNORECASE
            ),
            re.compile(r"\bcircuit[\s\-_]*breaker(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bhalt(?:ing|s)?\s+order\s+generation\b", re.IGNORECASE),
            re.compile(
                r"\binstant(?:aneous)?\s+(?:cancellation|order\s+flush|trading\s+halt)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bmanual\s+(?:override|disable)\s+switch(?:es)?\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(r"\bno\s+kill[\s\-_]*switch\b", re.IGNORECASE),
            re.compile(
                r"\bkill[\s\-_]*switch\s+(?:is\s+)?(?:not\s+(?:supported|implemented|configured)|disabled)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bunable\s+to\s+halt\s+(?:trading|execution|orders)\b", re.IGNORECASE),
        ],
        remedy="Implement an autonomous hardware or software kill switch capable of halting order routing and canceling pending orders within < 50ms upon risk threshold breach.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-02",
        title="Out-of-Sample Stress Testing & Backtesting Validation",
        category="Model Governance & Quantitative Risk",
        weight=15.0,
        regulation_ref="SEBI AI/ML Reporting Framework & Market Intermediaries System Audit Manual",
        mandatory_for=["algorithmic_trading", "credit_scoring", "fraud_detection", "general_ai"],
        positive_patterns=[
            re.compile(r"\bout[\s\-_]*of[\s\-_]*sample\b", re.IGNORECASE),
            re.compile(r"\bbacktest(?:ing|s|ed)?\b", re.IGNORECASE),
            re.compile(r"\bwalk[\s\-_]*forward\s+(?:analysis|validation|testing)\b", re.IGNORECASE),
            re.compile(r"\bstress\s+(?:testing|scenario|simulation)(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bflash\s+crash\s+simulation(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bhistorical\s+tick[\s\-_]*data\b", re.IGNORECASE),
            re.compile(r"\bcross[\s\-_]*validation\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(r"\bno\s+backtest(?:ing)?\b", re.IGNORECASE),
            re.compile(
                r"\bbacktest(?:ing)?\s+(?:not\s+(?:conducted|performed)|omitted)\b", re.IGNORECASE
            ),
            re.compile(r"\btested\s+only\s+in\s+live\s+production\b", re.IGNORECASE),
        ],
        remedy="Document rigorous out-of-sample stress testing across historical volatility events (e.g. Flash Crash) and conduct walk-forward cross-validation before release.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-03",
        title="Feature Importance & Decision Explainability (XAI)",
        category="Transparency & Model Interpretability",
        weight=10.0,
        regulation_ref="RBI Master Direction on Credit Underwriting & ISO/IEC 42001 Clause 8.4",
        mandatory_for=["credit_scoring", "llm_agent", "fraud_detection", "general_ai"],
        positive_patterns=[
            re.compile(r"\b(?:shap|shapley|lime)\b", re.IGNORECASE),
            re.compile(r"\bfeature\s+importance\b", re.IGNORECASE),
            re.compile(r"\bexplainab(?:ility|le)\b", re.IGNORECASE),
            re.compile(r"\bmodel\s+interpretability\b", re.IGNORECASE),
            re.compile(r"\binterpretability\b", re.IGNORECASE),
            re.compile(r"\bsurrogate\s+model(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bdecision\s+(?:attribution|rationale)(?:s)?\b", re.IGNORECASE),
            re.compile(r"\btransparent\s+(?:scoring|inference)\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(
                r"\bblack[\s\-_]*box\b.*?\b(?:without|no)\s+explainability\b", re.IGNORECASE
            ),
            re.compile(r"\b(?:without|no)\s+(?:model\s+)?explainability\b", re.IGNORECASE),
            re.compile(r"\b(?:without|no)\s+feature\s+importance\b", re.IGNORECASE),
            re.compile(r"\bunexplainable\s+decision(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bno\s+feature\s+attribution\b", re.IGNORECASE),
        ],
        remedy="Integrate explainability tooling (such as SHAP values or surrogate decision models) to provide feature attributions for every automated decision or adverse outcome.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-04",
        title="Algorithmic Bias, Fairness & Disparate Impact Auditing",
        category="Fairness & Ethical AI",
        weight=10.0,
        regulation_ref="SEBI Advisory on AI/ML Ethics & RBI Fair Lending Principles",
        mandatory_for=["credit_scoring", "llm_agent", "general_ai"],
        positive_patterns=[
            re.compile(r"\b(?:algorithmic|demographic)\s+(?:bias|fairness)\b", re.IGNORECASE),
            re.compile(r"\bdisparate\s+impact\b", re.IGNORECASE),
            re.compile(r"\bdemographic\s+parity\b", re.IGNORECASE),
            re.compile(r"\bequal(?:ized)?\s+odds\b", re.IGNORECASE),
            re.compile(
                r"\bfairness\s+(?:audit|metric|testing|evaluation|review)s?\b", re.IGNORECASE
            ),
            re.compile(r"\bprotected\s+(?:attribute|group|classification)s?\b", re.IGNORECASE),
            re.compile(r"\bnon[\s\-_]*discriminat(?:ory|ion)\b", re.IGNORECASE),
            re.compile(r"\bunbiased\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(
                r"\bbias\s+(?:audit(?:ing)?\s+)?(?:is\s+)?(?:not\s+(?:evaluated|checked|performed)|omitted)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bdemographic\s+parity\s+(?:is\s+)?(?:omitted|not\s+(?:evaluated|tracked|measured))\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bno\s+fairness\s+testing\b", re.IGNORECASE),
        ],
        remedy="Conduct formal algorithmic fairness reviews measuring demographic parity, disparate impact ratio (80% rule), and equalized odds across protected classifications.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-05",
        title="Deterministic Audit Trail & 7-Year Parameter Logging",
        category="Regulatory Audit & Provenance",
        weight=15.0,
        regulation_ref="SEBI Algorithm Testing Norms Clause 4.1 & Rule 6 of SEBI (Stock Brokers) Regulations",
        mandatory_for=[
            "algorithmic_trading",
            "credit_scoring",
            "llm_agent",
            "fraud_detection",
            "general_ai",
        ],
        positive_patterns=[
            re.compile(
                r"\b(?:7|seven)[\s\-_]*year\s+(?:retention|audit|log(?:ging)?|storage|records?)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\b7[\s\-_]*year\b", re.IGNORECASE),
            re.compile(r"\bimmutable\s+audit\s+trail\b", re.IGNORECASE),
            re.compile(r"\border\s+(?:and\s+trade\s+)?logging\b", re.IGNORECASE),
            re.compile(r"\bparameter\s+(?:snapshot|state)\s+logging\b", re.IGNORECASE),
            re.compile(r"\bworm\s+storage\b", re.IGNORECASE),
            re.compile(r"\bmicrosecond[\s\-_]*level\s+timestamp(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bdeterministic\s+logging\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(r"\bno\s+(?:audit\s+trail|order\s+logging)\b", re.IGNORECASE),
            re.compile(
                r"\blogs?\s+(?:discarded|deleted)\s+(?:immediately|after\s+(?:[1-6]\s*(?:day|month|week|year)))\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bunlogged\s+parameters\b", re.IGNORECASE),
        ],
        remedy="Configure tamper-evident, append-only audit logging recording all input signals, model parameters, and output decisions, retained for at least 7 years.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-06",
        title="Continuous Population Stability & Concept Drift Monitoring",
        category="Post-Deployment Telemetry",
        weight=10.0,
        regulation_ref="NIST AI RMF 1.0 (Measure 2.6) & ISO/IEC 42001 Clause 9.1",
        mandatory_for=[
            "algorithmic_trading",
            "credit_scoring",
            "llm_agent",
            "fraud_detection",
            "general_ai",
        ],
        positive_patterns=[
            re.compile(r"\bconcept\s+drift\b", re.IGNORECASE),
            re.compile(r"\bpopulation\s+stability\s+index\b|\bpsi\b", re.IGNORECASE),
            re.compile(r"\bdata\s+drift\s+(?:detection|monitoring)\b", re.IGNORECASE),
            re.compile(r"\bmodel\s+performance\s+decay\b", re.IGNORECASE),
            re.compile(r"\bcovariate\s+shift\b", re.IGNORECASE),
            re.compile(r"\btelemetry\s+drift\b", re.IGNORECASE),
            re.compile(r"\bdistribution(?:al)?\s+shift(?:s)?\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(r"\bno\s+drift\s+(?:monitoring|detection)\b", re.IGNORECASE),
            re.compile(
                r"\bdrift\s+monitoring\s+(?:not\s+(?:configured|enabled)|disabled)\b", re.IGNORECASE
            ),
            re.compile(r"\bstatic\s+model\s+without\s+monitoring\b", re.IGNORECASE),
        ],
        remedy="Establish automated telemetry tracking Population Stability Index (PSI) and feature drift against baseline training distributions with alerting triggers.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-07",
        title="Order-to-Trade Ratio (OTR) Limits & Pre-Trade Price Bands",
        category="Market Integrity & Throttle Controls",
        weight=15.0,
        regulation_ref="SEBI Master Circular on Algorithmic Trading Order-to-Trade Ratio Limits",
        mandatory_for=["algorithmic_trading", "fraud_detection", "general_ai"],
        positive_patterns=[
            re.compile(r"\border[\s\-_]*to[\s\-_]*trade\s+ratio\b|\botr\b", re.IGNORECASE),
            re.compile(r"\bprice\s+band(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bfat[\s\-_]*finger\s+(?:check|control|filter)(?:s)?\b", re.IGNORECASE),
            re.compile(
                r"\bpre[\s\-_]*trade\s+risk\s+(?:control|limit|filter)(?:s)?\b", re.IGNORECASE
            ),
            re.compile(r"\border\s+rate\s+limit(?:er|ing|s)?\b", re.IGNORECASE),
            re.compile(r"\bmaximum\s+order\s+quantity\b", re.IGNORECASE),
            re.compile(r"\bthrottl(?:ing|ed)\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(r"\bunthrottled\s+order(?:ing)?\b", re.IGNORECASE),
            re.compile(r"\bno\s+(?:rate\s+limit|price\s+band|otr\s+control)\b", re.IGNORECASE),
            re.compile(r"\bbypass(?:ed)?\s+pre[\s\-_]*trade\s+limits\b", re.IGNORECASE),
        ],
        remedy="Deploy pre-trade risk limiters enforcing maximum daily order-to-trade ratios (OTR), dynamic price collar validation, and fat-finger quantum guards.",
    ),
    StatutoryControlRule(
        control_id="ALGO-CTRL-08",
        title="Annual Independent System & Algorithm Conformance Audit",
        category="Statutory Assurance",
        weight=5.0,
        regulation_ref="SEBI System Audit Framework for Algorithmic Trading Members (Annual CERT-In Audit)",
        mandatory_for=["algorithmic_trading", "credit_scoring", "general_ai"],
        positive_patterns=[
            re.compile(r"\bannual\s+(?:system\s+)?audit\b", re.IGNORECASE),
            re.compile(r"\bcert[\s\-_]*in\s+empanelled\b", re.IGNORECASE),
            re.compile(r"\bindependent\s+(?:system\s+)?auditor\b", re.IGNORECASE),
            re.compile(r"\bcisa\s+auditor\b", re.IGNORECASE),
            re.compile(r"\bthird[\s\-_]*party\s+algorithm\s+audit\b", re.IGNORECASE),
            re.compile(r"\bexternal\s+conformance\s+review\b", re.IGNORECASE),
        ],
        negative_patterns=[
            re.compile(r"\bno\s+(?:independent|external)\s+audit\b", re.IGNORECASE),
            re.compile(r"\baudit\s+exempted\b", re.IGNORECASE),
        ],
        remedy="Commission and retain documentation of an annual comprehensive algorithmic system audit conducted by an independent CERT-In empanelled or CISA-certified auditor.",
    ),
]


class AlgorithmicImpactEngine:
    """Evaluates algorithmic and AI systems for statutory compliance."""

    def __init__(self, rules: list[StatutoryControlRule] | None = None) -> None:
        self.rules = rules or STATUTORY_CONTROLS

    def evaluate(
        self,
        system_name: str,
        model_type: ModelType | str,
        system_spec_text: str,
        config: AlgoImpactConfig | None = None,
    ) -> AlgoAssessmentResult:
        """Evaluate an algorithmic specification against statutory control rules."""
        if not system_name or not system_name.strip():
            raise ValueError("system_name must be non-empty")
        if not (100 <= len(system_spec_text) <= 50000):
            raise ValueError(
                f"system_spec_text length must be between 100 and 50,000 characters (got {len(system_spec_text)})"
            )

        active_config = config or AlgoImpactConfig()
        norm_model_type = model_type.lower().strip()

        passed_controls: list[str] = []
        failed_controls: list[FailedControl] = []
        negative_flags: list[str] = []

        total_applicable_weight = 0.0
        earned_weight = 0.0
        kill_switch_passed = False

        for rule in self.rules:
            # Check applicability based on target model classification
            if norm_model_type in [
                "algorithmic_trading",
                "credit_scoring",
                "llm_agent",
                "fraud_detection",
            ]:
                is_applicable = norm_model_type in rule.mandatory_for or "all" in rule.mandatory_for
            else:
                is_applicable = (
                    "general_ai" in rule.mandatory_for
                    or "all" in rule.mandatory_for
                    or len(rule.mandatory_for) == 0
                )

            if not is_applicable:
                continue

            total_applicable_weight += rule.weight

            # Check for explicit negative indicators
            has_negative = any(pat.search(system_spec_text) for pat in rule.negative_patterns)
            if has_negative:
                negative_flags.append(
                    f"{rule.control_id}: Explicit non-compliance or bypass detected"
                )

            # Check positive matches
            has_positive = any(pat.search(system_spec_text) for pat in rule.positive_patterns)

            if has_positive and not has_negative:
                passed_controls.append(rule.control_id)
                earned_weight += rule.weight
                if rule.control_id == "ALGO-CTRL-01":
                    kill_switch_passed = True
            else:
                failed_controls.append(
                    FailedControl(
                        control_id=rule.control_id,
                        title=rule.title,
                        regulation_ref=rule.regulation_ref,
                        remedy=rule.remedy,
                    )
                )

        # Baseline score calculation
        if total_applicable_weight > 0:
            raw_score = (earned_weight / total_applicable_weight) * 100.0
        else:
            raw_score = 100.0

        # Penalize for negative flags
        if negative_flags:
            raw_score = max(0.0, raw_score - (len(negative_flags) * 15.0))

        # Strict kill switch enforcement for algorithmic trading
        if (
            active_config.strict_kill_switch_required
            and norm_model_type == "algorithmic_trading"
            and not kill_switch_passed
        ):
            raw_score = min(raw_score, 45.0)

        conformity_score = round(max(0.0, min(100.0, raw_score)), 1)

        # Status determination
        if conformity_score >= active_config.pass_threshold:
            status: Literal["CONFORMANT", "CONDITIONAL", "NON_CONFORMANT"] = "CONFORMANT"
        elif conformity_score >= 50.0:
            status = "CONDITIONAL"
        else:
            status = "NON_CONFORMANT"

        # Generate deterministic certificate ID
        hasher = hashlib.sha256()
        hasher.update(
            f"{system_name}:{norm_model_type}:{conformity_score}:{system_spec_text[:200]}".encode()
        )
        cert_id = f"CERT-ALGO-{hasher.hexdigest()[:12].upper()}"

        evaluated_at = datetime.now(UTC)
        summary = (
            f"Evaluated {system_name} ({norm_model_type}) against {len(passed_controls) + len(failed_controls)} "
            f"statutory controls: {len(passed_controls)} passed, {len(failed_controls)} failed. "
            f"Conformity score {conformity_score}/100 ({status})."
        )

        return AlgoAssessmentResult(
            system_name=system_name,
            model_type=norm_model_type,
            conformity_score=conformity_score,
            status=status,
            passed_controls=passed_controls,
            failed_controls=failed_controls,
            negative_flags=negative_flags,
            audit_certificate_id=cert_id,
            evaluated_at=evaluated_at,
            summary=summary,
        )


_DEFAULT_ALGO_IMPACT_ENGINE: AlgorithmicImpactEngine | None = None


def get_default_algorithmic_impact_engine() -> AlgorithmicImpactEngine:
    """Return the singleton instance of AlgorithmicImpactEngine."""
    global _DEFAULT_ALGO_IMPACT_ENGINE
    if _DEFAULT_ALGO_IMPACT_ENGINE is None:
        _DEFAULT_ALGO_IMPACT_ENGINE = AlgorithmicImpactEngine()
    return _DEFAULT_ALGO_IMPACT_ENGINE
