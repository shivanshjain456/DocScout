"""DocScout Prescriptive Remediation Engine (FEAT-034).

Maps compliance antipatterns and deprecated practices to sanctioned, compliant
alternative practices and actionable prescriptive implementation steps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("docscout.compliance.remediation_engine")


@dataclass
class PracticeRecommendation:
    """Actionable prescriptive replacement practice anchored in taxonomy."""

    name: str
    term_id: str
    definition: str
    value_justification: str
    tier: int
    domain: str
    gate_criteria: str | None = None
    implementation_steps: list[str] = field(default_factory=list)
    standard_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "term_id": self.term_id,
            "definition": self.definition,
            "value_justification": self.value_justification,
            "tier": self.tier,
            "domain": self.domain,
            "gate_criteria": self.gate_criteria,
            "implementation_steps": self.implementation_steps,
            "standard_reference": self.standard_reference,
        }


@dataclass
class RemediationPlan:
    """Complete prescriptive remediation plan addressing a detected flaw."""

    flaw_id: str
    flaw_type: str
    identified_flaw: str
    consequence_or_reason: str
    severity: str
    recommended_practices: list[PracticeRecommendation]
    guidance: str | None = None
    lookup_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "flaw_id": self.flaw_id,
            "flaw_type": self.flaw_type,
            "identified_flaw": self.identified_flaw,
            "consequence_or_reason": self.consequence_or_reason,
            "severity": self.severity,
            "recommended_practices": [r.to_dict() for r in self.recommended_practices],
            "guidance": self.guidance,
            "lookup_latency_ms": round(self.lookup_latency_ms, 3),
        }


@dataclass
class RemediationReport:
    """Aggregate remediation report across multiple audit findings."""

    total_findings: int
    remediated_findings: int
    plans: list[RemediationPlan]
    unique_recommended_practices: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_findings": self.total_findings,
            "remediated_findings": self.remediated_findings,
            "plans": [p.to_dict() for p in self.plans],
            "unique_recommended_practices": self.unique_recommended_practices,
        }


def _build_default_implementation_steps(term_name: str, gate: str | None) -> list[str]:
    """Generate prescriptive, actionable implementation steps for a replacement practice."""
    steps = [
        f"Adopt and integrate {term_name} across architecture guidelines and team documentation.",
    ]
    if gate and gate.strip():
        steps.append(f"Configure automated quality gate: {gate.strip()}")
    else:
        steps.append(f"Establish telemetry, metrics, and automated validation for {term_name}.")
    steps.append(
        f"Audit {term_name} continuous operational effectiveness during observation windows."
    )
    return steps


class PrescriptiveRemediationEngine:
    """Engine mapping detected antipatterns and deprecations to sanctioned practices."""

    def __init__(self) -> None:
        self._antipattern_plans: dict[str, RemediationPlan] = {}
        self._practice_to_plan: dict[str, RemediationPlan] = {}
        self._deprecation_plans: dict[str, RemediationPlan] = {}
        self._subject_to_plan: dict[str, RemediationPlan] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        """Preload all 30 canonical antipatterns and 8 deprecations."""
        raw_antipatterns: list[dict[str, Any]] = [
            {
                "flaw_id": "ap-line-coverage",
                "flaw_type": "antipattern",
                "practice": "Statement Coverage",
                "antipattern": "Using line coverage as a quality target or a release gate.",
                "consequence": "Teams write assertion-free tests that execute code without verifying anything, and the metric rises while defect detection does not.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Diff / Patch Coverage",
                        "term_id": "diff-patch-coverage",
                        "definition": "Coverage restricted to the lines changed in a specific change set.",
                        "value": "Far more actionable than global coverage and immune to the legacy-code dilution problem.",
                        "tier": 1,
                        "gate": "Merge blocked below an agreed percentage on changed lines (typical starting point 80%).",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                    {
                        "term_name": "Mutation Score / Mutation Adequacy",
                        "term_id": "mutation-score-mutation-adequacy",
                        "definition": "Percentage of injected artificial faults (mutants) that the test suite detects.",
                        "value": "The best available proxy for a suite's real fault-detection power, far stronger than line coverage.",
                        "tier": 1,
                        "gate": "Incremental mutation run on changed files only; threshold enforced per package, not globally.",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                    {
                        "term_name": "Coverage Ratcheting",
                        "term_id": "coverage-ratcheting",
                        "definition": "Prevent the coverage percentage from decreasing on any change rather than demanding an absolute target.",
                        "value": "Achieves incremental improvement without a demoralising big-bang coverage initiative.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                ],
            },
            {
                "flaw_id": "ap-mutation-all",
                "flaw_type": "antipattern",
                "practice": "Mutation Testing",
                "antipattern": "Running mutation testing across the whole repository on every commit and demanding 100%.",
                "consequence": "Builds become unusably slow, the equivalent-mutant problem makes 100% unattainable, and the practice is abandoned entirely.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "Diff / Patch Coverage",
                        "term_id": "diff-patch-coverage",
                        "definition": "Coverage restricted to the lines changed in a specific change set.",
                        "value": "Far more actionable than global coverage and immune to the legacy-code dilution problem.",
                        "tier": 1,
                        "gate": "Merge blocked below an agreed percentage on changed lines (typical starting point 80%).",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                    {
                        "term_name": "Regression Test Selection",
                        "term_id": "regression-test-selection",
                        "definition": "Run only the subset of tests provably affected by a given change.",
                        "value": "The main lever for keeping CI fast as suites grow without sacrificing safety.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Test Design, Oracles & Generative Testing",
                    },
                    {
                        "term_name": "Test Suite Runtime Budget",
                        "term_id": "test-suite-runtime-budget",
                        "definition": "An explicit ceiling on how long the full suite may take, enforced like a performance budget.",
                        "value": "Unbudgeted suites grow monotonically until feedback loops stop working.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                ],
            },
            {
                "flaw_id": "ap-mock-everything",
                "flaw_type": "antipattern",
                "practice": "Test Doubles Taxonomy",
                "antipattern": "Mocking everything so that tests verify the test's own assumptions rather than real behaviour.",
                "consequence": "Tests pass while integration fails, because the mock encoded the same misunderstanding as the code under test.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Testcontainers-Based Integration Testing",
                        "term_id": "testcontainers-based-integration-testing",
                        "definition": "Provision real dependency instances (databases, brokers, caches) in ephemeral containers per test run.",
                        "value": "Real dependencies at unit-test convenience, eliminating mock-versus-reality divergence.",
                        "tier": 1,
                        "gate": "Integration suites use real dependency containers, not mocks, for anything with a wire protocol.",
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Consumer-Driven Contract Testing",
                        "term_id": "consumer-driven-contract-testing",
                        "definition": "The consumer defines the minimal interactions it depends on; the provider later verifies it still satisfies them.",
                        "value": "Enables independent deployment of services without a full integration environment.",
                        "tier": 1,
                        "gate": "Consumer pacts published per build; provider verifies; `can-i-deploy` gates every production deployment.",
                        "domain": "Architecture & Contract Testing",
                    },
                    {
                        "term_name": "Testing Honeycomb",
                        "term_id": "testing-honeycomb",
                        "definition": "Prioritises integration tests for complex systems over both unit and end-to-end tests.",
                        "value": "Appropriate for distributed and data-heavy systems where behaviour lives at integration boundaries.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Quality Engineering Operating Model",
                    },
                ],
            },
            {
                "flaw_id": "ap-chaos-no-hypothesis",
                "flaw_type": "antipattern",
                "practice": "Chaos Engineering",
                "antipattern": "Breaking things in production without a steady-state hypothesis, abort conditions or blast-radius limits.",
                "consequence": "An informative experiment becomes an outage, and the practice is banned organisationally.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Steady-State Hypothesis",
                        "term_id": "steady-state-hypothesis",
                        "definition": "A measurable definition of normal behaviour (SLO-level metrics) that an experiment attempts to falsify.",
                        "value": "Without it an experiment produces anecdotes; with it, a falsifiable result.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                    {
                        "term_name": "Abort Conditions",
                        "term_id": "abort-conditions",
                        "definition": "Pre-agreed thresholds and automatic stop conditions that terminate an experiment immediately.",
                        "value": "Prevents an informative experiment from becoming an incident.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                    {
                        "term_name": "Blast Radius Containment",
                        "term_id": "blast-radius-containment",
                        "definition": "Bound the population, infrastructure and duration an experiment or failure can affect.",
                        "value": "The control that makes production experimentation ethically and commercially defensible.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                    {
                        "term_name": "game days",
                        "term_id": "game-days",
                        "definition": "Planned, rehearsed failure exercises in which a team injects faults and practises its detection, response and recovery.",
                        "value": "",
                        "tier": None,
                        "gate": None,
                        "domain": "Preserved Original",
                    },
                ],
            },
            {
                "flaw_id": "ap-feature-flags-stale",
                "flaw_type": "antipattern",
                "practice": "Feature Flags",
                "antipattern": "Accumulating unowned, never-expiring toggles.",
                "consequence": "2^n code paths, an unknowable test matrix, and flags that silently change behaviour years after their purpose ended.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Flag Debt Management",
                        "term_id": "flag-debt-management",
                        "definition": "Classify, own, expire and automatically retire toggles to bound combinatorial test surface.",
                        "value": "Unmanaged flags create 2^n code paths and make the test matrix unknowable.",
                        "tier": 1,
                        "gate": "CI fails when a flag exceeds its expiry or lacks an owner or removal ticket.",
                        "domain": "Delivery, Deployment & Progressive Rollout",
                    },
                    {
                        "term_name": "Kill Switch Validation",
                        "term_id": "kill-switch-validation",
                        "definition": "Periodically exercise the emergency disable path for each high-risk capability.",
                        "value": "An untested kill switch is discoverable as broken during the incident it was meant to contain.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Delivery, Deployment & Progressive Rollout",
                    },
                ],
            },
            {
                "flaw_id": "ap-canary-dashboard-eye",
                "flaw_type": "antipattern",
                "practice": "Canary Release",
                "antipattern": "Routing 5% of traffic to a canary and watching a dashboard by eye.",
                "consequence": "The decision is made by attention and time of day rather than statistics, and small regressions are missed.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Automated Canary Analysis (ACA)",
                        "term_id": "automated-canary-analysis-aca",
                        "definition": "Statistically compare canary against baseline on defined metrics and promote or abort automatically.",
                        "value": "Removes human judgement and its latency from the most common release decision.",
                        "tier": 1,
                        "gate": "Promote or abort decided by metric analysis over the canary window, not by human judgement at 4pm on a Friday.",
                        "domain": "Delivery, Deployment & Progressive Rollout",
                    },
                    {
                        "term_name": "Multi-Window Multi-Burn-Rate Alerting",
                        "term_id": "multi-window-multi-burn-rate-alerting",
                        "definition": "Alert on error-budget consumption rate across several time windows to balance sensitivity against noise.",
                        "value": "The standard method for making SLO alerts both fast and actionable.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Performance Regression Detection",
                        "term_id": "performance-regression-detection",
                        "definition": "Statistically compare benchmark distributions against a baseline and gate the change.",
                        "value": "Catches the death-by-a-thousand-cuts degradation that no single change appears to cause.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Performance & Capacity Engineering",
                    },
                ],
            },
            {
                "flaw_id": "ap-ab-early-stopping",
                "flaw_type": "antipattern",
                "practice": "A/B Testing",
                "antipattern": "Stopping the test as soon as the result crosses significance.",
                "consequence": "False-positive rate explodes far above the nominal alpha because of the peeking problem.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Sequential Testing / Always-Valid Inference",
                        "term_id": "sequential-testing-always-valid-inference",
                        "definition": "Statistical procedures that permit continuous monitoring without inflating false positives.",
                        "value": "Eliminates the peeking problem that invalidates naive fixed-horizon tests.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Experimentation & Measurement",
                    },
                    {
                        "term_name": "Power Analysis and Minimum Detectable Effect",
                        "term_id": "power-analysis-and-minimum-detectable-effect",
                        "definition": "Compute the sample size needed to detect an effect of a given size at a given confidence.",
                        "value": "Underpowered experiments produce false negatives and inflated effect estimates.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Experimentation & Measurement",
                    },
                    {
                        "term_name": "Overall Evaluation Criterion (OEC)",
                        "term_id": "overall-evaluation-criterion-oec",
                        "definition": "The single pre-registered primary metric an experiment is designed to move.",
                        "value": "Prevents post-hoc metric shopping, the most common way experiments mislead.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Experimentation & Measurement",
                    },
                ],
            },
            {
                "flaw_id": "ap-judge-unvalidated",
                "flaw_type": "antipattern",
                "practice": "LLM-as-a-Judge",
                "antipattern": "Adopting judge scores as ground truth without validating the judge.",
                "consequence": "Metrics measure the judge's biases, and a judge model upgrade silently invalidates every historical comparison.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Judge Reliability and Evaluator Drift",
                        "term_id": "judge-reliability-and-evaluator-drift",
                        "definition": "Measure the judge's self-consistency and re-validate it whenever the judge model or prompt changes.",
                        "value": "A silently drifting judge invalidates every metric built on it.",
                        "tier": 2,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Human-Metric Alignment",
                        "term_id": "human-metric-alignment",
                        "definition": "Statistically align automated scores with human annotations so the metric means what you think.",
                        "value": "Without alignment, you optimise a proxy that may not correlate with quality at all.",
                        "tier": 2,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Golden Eval Set",
                        "term_id": "golden-eval-set",
                        "definition": "A curated, version-controlled set of cases with expected properties representing must-not-regress behaviour.",
                        "value": "The regression suite for AI systems, and the gate for prompt, model and retrieval changes.",
                        "tier": 1,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                ],
            },
            {
                "flaw_id": "ap-prompt-injection-direct-only",
                "flaw_type": "antipattern",
                "practice": "Prompt Injection Testing",
                "antipattern": "Testing only direct user-supplied injections in a RAG or agent system.",
                "consequence": "The higher-severity indirect route  -  instructions embedded in retrieved documents, web pages or tool outputs  -  goes entirely untested.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Direct and Indirect Prompt Injection Testing",
                        "term_id": "direct-and-indirect-prompt-injection-testing",
                        "definition": "User input that overrides instructions versus malicious instructions embedded in retrieved documents, tool outputs or web content.",
                        "value": "Indirect injection is the higher-severity case for RAG and agents because the attacker need not be the user.",
                        "tier": 1,
                        "gate": "Growing adversarial corpus rerun on every release; canary tokens assert no prompt or tool-argument leakage.",
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Adversarial Prompt Corpus",
                        "term_id": "adversarial-prompt-corpus",
                        "definition": "A growing library of attack prompts and malicious intents, rerun every release.",
                        "value": "AI security is an arms race measured by attack success rate per category, not by a pass/fail.",
                        "tier": 1,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Canary Token Assertions",
                        "term_id": "canary-token-assertions",
                        "definition": "Plant a unique secret in the system prompt or context and assert it never appears in output or tool arguments.",
                        "value": "An objective, automatable oracle for leakage and injection success.",
                        "tier": 1,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                ],
            },
            {
                "flaw_id": "ap-fairness-single-attribute",
                "flaw_type": "antipattern",
                "practice": "Model Fairness Auditing",
                "antipattern": "Checking one protected attribute at a time and reporting a single aggregate accuracy figure.",
                "consequence": "Harm concentrates at intersections and in minority slices that global metrics average away.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Intersectional Bias Testing",
                        "term_id": "intersectional-bias-testing",
                        "definition": "Evaluate fairness across combinations of protected attributes rather than one attribute at a time.",
                        "value": "Harm concentrates at intersections; single-attribute audits systematically miss it.",
                        "tier": 2,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Slice-Based Evaluation",
                        "term_id": "slice-based-evaluation",
                        "definition": "Systematically measure performance across defined data slices (segments, cohorts, edge populations) rather than global averages.",
                        "value": "Global metrics are dominated by the majority slice and hide catastrophic subgroup failure.",
                        "tier": 1,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Worst-Group Performance Analysis",
                        "term_id": "worst-group-performance-analysis",
                        "definition": "Report the minimum performance across groups as a headline metric.",
                        "value": "More actionable than the mean and aligned with safety and fairness requirements.",
                        "tier": 2,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                ],
            },
            {
                "flaw_id": "ap-data-quality-nulls-only",
                "flaw_type": "antipattern",
                "practice": "Data Quality Dimensions",
                "antipattern": "Monitoring only nulls and duplicates because those checks are easy to write.",
                "consequence": "Values stay well-formed while becoming wrong; accuracy and consistency failures reach decision-makers unflagged.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "Data Observability",
                        "term_id": "data-observability",
                        "definition": "Monitor freshness, volume, schema, distribution and lineage to detect the anomalies you never wrote rules for.",
                        "value": "Validation catches known violations; observability catches the unknown.",
                        "tier": 1,
                        "gate": "Freshness, volume, schema and distribution monitors per critical table with alerting into the same on-call rotation as services.",
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                    {
                        "term_name": "Column and Dimension Anomaly Detection",
                        "term_id": "column-and-dimension-anomaly-detection",
                        "definition": "Detect distribution, null-rate and cardinality shifts within individual columns and dimension values.",
                        "value": "Catches semantic corruption that row counts and schema checks pass straight through.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                    {
                        "term_name": "Data Reconciliation and Checksum Validation",
                        "term_id": "data-reconciliation-and-checksum-validation",
                        "definition": "Compare source and target by counts, aggregates and per-partition checksums.",
                        "value": "Row counts alone conceal compensating errors; checksums do not.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                ],
            },
            {
                "flaw_id": "ap-testcontainers-per-unit",
                "flaw_type": "antipattern",
                "practice": "Testcontainers-Based Integration Testing",
                "antipattern": "Spinning up the full production topology for every unit test.",
                "consequence": "Suite runtime explodes and developers route around the tests entirely.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "Test Impact Analysis (TIA)",
                        "term_id": "test-impact-analysis-tia",
                        "definition": "Use dependency and coverage mappings to select only the tests affected by a change.",
                        "value": "The main technique for keeping large suites fast without dropping safety.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Test Sharding and Parallelisation",
                        "term_id": "test-sharding-and-parallelisation",
                        "definition": "Partition test suites across executors with balanced duration and strict isolation.",
                        "value": "Linear speedup for suites whose runtime has outgrown the acceptable feedback window.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Test Suite Runtime Budget",
                        "term_id": "test-suite-runtime-budget",
                        "definition": "An explicit ceiling on how long the full suite may take, enforced like a performance budget.",
                        "value": "Unbudgeted suites grow monotonically until feedback loops stop working.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Test Trophy",
                        "term_id": "test-trophy",
                        "definition": "Emphasises integration tests as the highest-value layer, with unit and E2E tests as supporting tiers.",
                        "value": "A correction for codebases where unit tests mock so heavily they verify nothing real.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Quality Engineering Operating Model",
                    },
                ],
            },
            {
                "flaw_id": "ap-rts-filename-heuristics",
                "flaw_type": "antipattern",
                "practice": "Regression Test Selection",
                "antipattern": "Selecting tests by filename or directory heuristics rather than real dependency analysis.",
                "consequence": "Affected tests are skipped, and the safety property the technique was adopted for is silently lost.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Test Impact Analysis (TIA)",
                        "term_id": "test-impact-analysis-tia",
                        "definition": "Use dependency and coverage mappings to select only the tests affected by a change.",
                        "value": "The main technique for keeping large suites fast without dropping safety.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Predictive Test Selection",
                        "term_id": "predictive-test-selection",
                        "definition": "Use ML models over historical failures and code changes to rank which tests are most likely to fail.",
                        "value": "Prioritises scarce CI capacity toward the tests most likely to find the current defect.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Diff / Patch Coverage",
                        "term_id": "diff-patch-coverage",
                        "definition": "Coverage restricted to the lines changed in a specific change set.",
                        "value": "Far more actionable than global coverage and immune to the legacy-code dilution problem.",
                        "tier": 1,
                        "gate": "Merge blocked below an agreed percentage on changed lines (typical starting point 80%).",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                ],
            },
            {
                "flaw_id": "ap-blind-test-retries",
                "flaw_type": "antipattern",
                "practice": "Retry Semantics and Masking Risk",
                "antipattern": "Adding automatic retries to a failing test suite to make CI green.",
                "consequence": "Genuine concurrency and state defects become intermittent production incidents with no owner.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Flaky Test Detection and Quarantine",
                        "term_id": "flaky-test-detection-and-quarantine",
                        "definition": "Automatically detect non-deterministic tests, move them out of the critical path and track their repair.",
                        "value": "Quarantine preserves signal quality while keeping the debt visible instead of merely tolerated.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Nondeterminism Auditing",
                        "term_id": "nondeterminism-auditing",
                        "definition": "Systematically inventory uncontrolled sources of variation: time, randomness, network, parallel order, locale, shared state.",
                        "value": "You cannot fix flakiness without first enumerating its causes.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Seeded Randomness",
                        "term_id": "seeded-randomness",
                        "definition": "Control all randomness through explicit seeds so the same run can be reproduced.",
                        "value": "Converts non-deterministic failures into deterministic ones.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                ],
            },
            {
                "flaw_id": "ap-synthetic-data-unconstrained",
                "flaw_type": "antipattern",
                "practice": "Synthetic Data Generation",
                "antipattern": "Generating statistically plausible data that violates real-world relationships and constraints.",
                "consequence": "Tests pass against impossible combinations; referential and business-rule defects are never exercised.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Referentially Consistent Subsetting",
                        "term_id": "referentially-consistent-subsetting",
                        "definition": "Produce a smaller dataset that preserves all relationships and constraints of the original.",
                        "value": "Naive sampling breaks joins and invalidates realistic integration testing.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                    {
                        "term_name": "Golden Dataset Curation",
                        "term_id": "golden-dataset-curation",
                        "definition": "Maintain a versioned, reviewed dataset that represents expected behaviour and edge cases.",
                        "value": "The reference artefact against which pipelines and models are regression-tested.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                    {
                        "term_name": "Data Quality Dimensions",
                        "term_id": "data-quality-dimensions",
                        "definition": "Validity, completeness, uniqueness, consistency, timeliness and accuracy as separately testable properties.",
                        "value": "Accuracy needs a system of record to compare against; the other dimensions can be enforced automatically.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                ],
            },
            {
                "flaw_id": "ap-stride-system-whole",
                "flaw_type": "antipattern",
                "practice": "Threat Modeling (STRIDE)",
                "antipattern": "Applying the six categories to 'the system' as a whole rather than per element and trust boundary.",
                "consequence": "Six generic bullets are produced for a system that should have generated hundreds of specific threats.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Attack Tree Analysis",
                        "term_id": "attack-tree-analysis",
                        "definition": "Decompose an attacker goal into alternative and required sub-goals to reveal multi-step chains.",
                        "value": "Captures chained exploits that per-element threat enumeration structurally misses.",
                        "tier": 3,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "Abuse Case / Misuse Case Testing",
                        "term_id": "abuse-case-misuse-case-testing",
                        "definition": "Express attacker goals as first-class cases and derive testable security requirements and verification evidence from them.",
                        "value": "Turns threat-model output into tests, closing the loop from design risk to evidence.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "PASTA (Process for Attack Simulation and Threat Analysis)",
                        "term_id": "pasta-process-for-attack-simulation-and-threat-analysis",
                        "definition": "A seven-stage, risk- and business-centric threat modeling method aligned to attacker simulation.",
                        "value": "Suits high-stakes, compliance-heavy systems where business impact drives prioritisation.",
                        "tier": 3,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                ],
            },
            {
                "flaw_id": "ap-sbom-shelfware",
                "flaw_type": "antipattern",
                "practice": "SBOM (Software Bill of Materials)",
                "antipattern": "Generating an SBOM once for compliance and never consuming it operationally.",
                "consequence": "The next Log4j-class event still takes weeks to assess because the inventory is stale and unqueryable.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "VEX (Vulnerability Exploitability eXchange)",
                        "term_id": "vex-vulnerability-exploitability-exchange",
                        "definition": "A machine-readable statement of whether a vulnerability in a component actually affects a given product.",
                        "value": "Kills false-positive CVE noise, which is what makes SBOMs operationally unusable without it.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Supply Chain & Build Integrity",
                    },
                    {
                        "term_name": "SCA (Software Composition Analysis)",
                        "term_id": "sca-software-composition-analysis",
                        "definition": "Inventory open-source and third-party components and map them to known vulnerabilities and licences.",
                        "value": "70-90% of a modern codebase is third-party; SCA is also the substrate of your SBOM.",
                        "tier": 1,
                        "gate": "Build fails on new critical/known-exploited dependency findings; SBOM regenerated and attached to every artefact.",
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "Mean Time to Remediate (MTTR-vuln)",
                        "term_id": "mean-time-to-remediate-mttr-vuln",
                        "definition": "Average time from vulnerability identification to verified fix in production.",
                        "value": "The metric auditors and regulators actually ask for on vulnerability management SLAs.",
                        "tier": 3,
                        "gate": None,
                        "domain": "Supply Chain & Build Integrity",
                    },
                ],
            },
            {
                "flaw_id": "ap-annual-pentest-evidence",
                "flaw_type": "antipattern",
                "practice": "Penetration Testing",
                "antipattern": "Running an annual penetration test as the primary evidence that controls work.",
                "consequence": "Frameworks requiring continuous evidence  -  PCI DSS 4.0, SOC 2 Type II, FedRAMP  -  find provable gaps across the observation window.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Continuous Compliance",
                        "term_id": "continuous-compliance",
                        "definition": "Continuously generate timestamped control evidence rather than assembling it before an audit.",
                        "value": "Audit windows are 3-12 months; point-in-time scans leave provable gaps.",
                        "tier": 1,
                        "gate": "Control evidence generated automatically with timestamps spanning the full audit observation window.",
                        "domain": "Compliance, Governance & Audit",
                    },
                    {
                        "term_name": "Purple Teaming",
                        "term_id": "purple-teaming",
                        "definition": "Red and blue teams collaborate iteratively so every attack technique ends in a detection or a documented gap.",
                        "value": "Converts offensive findings into defensive capability instead of a report that decays.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "Adversary Emulation",
                        "term_id": "adversary-emulation",
                        "definition": "Replay realistic, multi-stage adversary behaviour mapped to a specific threat actor or technique set.",
                        "value": "Tests the whole detection-and-response chain, not just prevention controls.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                ],
            },
            {
                "flaw_id": "ap-perf-empty-db-average",
                "flaw_type": "antipattern",
                "practice": "Performance Testing",
                "antipattern": "Reporting average response time and running a closed-model load test against an empty database.",
                "consequence": "Average latency hides the tail, and coordinated omission understates p99 by orders of magnitude.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Tail Latency Analysis (p99 / p999)",
                        "term_id": "tail-latency-analysis-p99-p999",
                        "definition": "Quantify the slowest requests rather than the average.",
                        "value": "At scale, the tail is the user experience, and averages hide exactly the failures users notice.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Performance & Capacity Engineering",
                    },
                    {
                        "term_name": "Coordinated Omission Avoidance",
                        "term_id": "coordinated-omission-avoidance",
                        "definition": "Correct for the measurement bias where a slow system reduces the number of samples it reports.",
                        "value": "The reason many load-test results are optimistically wrong by an order of magnitude at the tail.",
                        "tier": 1,
                        "gate": "Load test harness must use open-model arrival or corrected latency accounting before any capacity number is published.",
                        "domain": "Performance & Capacity Engineering",
                    },
                    {
                        "term_name": "Open vs Closed Workload Models",
                        "term_id": "open-vs-closed-workload-models",
                        "definition": "Closed models hold a fixed number of users; open models drive arrival rate independent of response time.",
                        "value": "Closed-model load tests systematically understate the damage of slow responses.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Performance & Capacity Engineering",
                    },
                    {
                        "term_name": "Production Traffic Replay",
                        "term_id": "production-traffic-replay",
                        "definition": "Capture real request streams and replay them against a candidate build.",
                        "value": "The highest-fidelity load test available without exposing users.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Performance & Capacity Engineering",
                    },
                ],
            },
            {
                "flaw_id": "ap-high-cardinality-metric-labels",
                "flaw_type": "antipattern",
                "practice": "Observability & Telemetry Engineering",
                "antipattern": "Attaching user IDs, request IDs and raw URL paths as metric labels.",
                "consequence": "Cardinality explosion makes observability cost more than compute and slows every query to unusable.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Cardinality Management",
                        "term_id": "cardinality-management",
                        "definition": "Bound the number of distinct attribute-value combinations allowed on metrics.",
                        "value": "Undisciplined labels are the primary cause of runaway observability cost and slow queries.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Head vs Tail Sampling",
                        "term_id": "head-vs-tail-sampling",
                        "definition": "Decide whether to sample before execution (cheap, blind to errors) or after (expensive, can keep all errors and slow traces).",
                        "value": "Tail sampling preserves exactly the traces you need while cutting cost dramatically.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Wide Events / High-Dimensional Event Analysis",
                        "term_id": "wide-events-high-dimensional-event-analysis",
                        "definition": "Emit one rich event per operation with hundreds of attributes and aggregate at query time.",
                        "value": "Lets you ask unanticipated questions after the fact instead of pre-deciding which metrics matter.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Exemplars",
                        "term_id": "exemplars",
                        "definition": "Attach a sampled trace reference to a metric data point so an aggregate can be drilled into a concrete request.",
                        "value": "Connects dashboards to individual failures without high-cardinality metrics.",
                        "tier": 3,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                ],
            },
            {
                "flaw_id": "ap-tracing-entry-only",
                "flaw_type": "antipattern",
                "practice": "Distributed Tracing / Span Model",
                "antipattern": "Instrumenting only the entry service and assuming traces will join up.",
                "consequence": "Partial traces point confidently at the wrong service, which is worse than having no trace at all.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "Trace Context Propagation",
                        "term_id": "trace-context-propagation",
                        "definition": "Carry trace and span identifiers across process, protocol and async boundaries per the W3C Trace Context standard.",
                        "value": "Broken propagation silently produces partial traces and destroys root-cause analysis.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Instrumentation Assertion Testing",
                        "term_id": "instrumentation-assertion-testing",
                        "definition": "Assert that the code actually emits the spans, metrics and attributes it is specified to emit.",
                        "value": "Telemetry is a contract with operators and must be tested like any other interface.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Semantic Conventions",
                        "term_id": "semantic-conventions",
                        "definition": "Standardised attribute and metric names, units and kinds for common operations.",
                        "value": "Without them, telemetry from different services cannot be joined, compared or alerted on consistently.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                ],
            },
            {
                "flaw_id": "ap-sr117-onetime-signoff",
                "flaw_type": "antipattern",
                "practice": "Independent Model Validation (SR 11-7 style)",
                "antipattern": "Treating validation as a one-time pre-launch sign-off.",
                "consequence": "Data, model and concept drift degrade the validated system with no re-validation trigger, and documented validity silently expires.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Data Drift Detection",
                        "term_id": "data-drift-detection",
                        "definition": "Detect changes in the distribution of incoming features relative to the training baseline.",
                        "value": "Inputs move before accuracy does, making drift an early warning signal.",
                        "tier": 1,
                        "gate": "Automated monitor comparing live feature distributions with the training baseline, with retraining or alerting thresholds.",
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                    {
                        "term_name": "Concept Drift Detection",
                        "term_id": "concept-drift-detection",
                        "definition": "Detect change in the input-to-output relationship itself, measured against realised outcomes.",
                        "value": "Requires labels or proxies, but it is the only detector for genuine model obsolescence.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Data, Analytics & Pipeline Testing",
                    },
                    {
                        "term_name": "Prediction Drift Monitoring",
                        "term_id": "prediction-drift-monitoring",
                        "definition": "Track the distribution of model outputs over time independent of ground truth.",
                        "value": "An early, label-free signal that inputs or behaviour have changed.",
                        "tier": 2,
                        "gate": None,
                        "domain": "AI, ML & LLM Assurance",
                    },
                    {
                        "term_name": "Model Promotion Gates",
                        "term_id": "model-promotion-gates",
                        "definition": "Require evaluation thresholds, fairness checks, robustness results and sign-off before a model reaches production.",
                        "value": "Prevents models from shipping on the strength of a single favourable metric.",
                        "tier": 2,
                        "gate": "Model registry requires evaluation thresholds, fairness and robustness evidence before promotion to production.",
                        "domain": "AI, ML & LLM Assurance",
                    },
                ],
            },
            {
                "flaw_id": "ap-accessibility-scanner-only",
                "flaw_type": "antipattern",
                "practice": "Accessibility Testing",
                "antipattern": "Reporting an automated scan pass as evidence of accessibility compliance.",
                "consequence": "Roughly two-thirds of WCAG failures remain, concentrated in exactly the areas that determine real usability.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Screen Reader Compatibility Testing",
                        "term_id": "screen-reader-compatibility-testing",
                        "definition": "Verify semantic structure, names, roles, states and live-region announcements with NVDA, JAWS, VoiceOver or TalkBack.",
                        "value": "Automated scanners catch roughly a third of accessibility defects; this is where the rest live.",
                        "tier": 1,
                        "gate": "Manual assistive-technology pass on critical flows each release, with automated scanning as a continuous floor.",
                        "domain": "Client, Mobile & Web Testing",
                    },
                    {
                        "term_name": "Keyboard-Only Navigation Testing",
                        "term_id": "keyboard-only-navigation-testing",
                        "definition": "Operate the entire product without a pointing device, verifying reachability and operability.",
                        "value": "A WCAG Level A requirement and a strong predictor of general interaction quality.",
                        "tier": 1,
                        "gate": "Automated keyboard reachability and focus-order assertions on every interactive component.",
                        "domain": "Client, Mobile & Web Testing",
                    },
                    {
                        "term_name": "Focus Management and Focus Trap Testing",
                        "term_id": "focus-management-and-focus-trap-testing",
                        "definition": "Verify logical focus order, visible focus indication and correct trapping/release in modals.",
                        "value": "Focus defects make interfaces unusable for assistive-technology users.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Client, Mobile & Web Testing",
                    },
                ],
            },
            {
                "flaw_id": "ap-contract-pact-no-provider",
                "flaw_type": "antipattern",
                "practice": "Contract Testing",
                "antipattern": "Publishing consumer pacts without ever running provider verification.",
                "consequence": "A false sense of safety: contracts exist, are never checked, and providers break consumers undetected.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Pact Broker and can-i-deploy",
                        "term_id": "pact-broker-and-can-i-deploy",
                        "definition": "Central registry of contracts with verification results that gates deployment on cross-service compatibility.",
                        "value": "Turns contract testing into an automated, enforceable release control.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Architecture & Contract Testing",
                    },
                    {
                        "term_name": "Schema-Based Contract Testing",
                        "term_id": "schema-based-contract-testing",
                        "definition": "Validate live consumer and provider behaviour directly against an OpenAPI, AsyncAPI or GraphQL specification.",
                        "value": "Catches specification lies and undocumented behaviour without hand-written contract code.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Architecture & Contract Testing",
                    },
                    {
                        "term_name": "Breaking Change Detection",
                        "term_id": "breaking-change-detection",
                        "definition": "Automatically classify schema changes as breaking, dangerous or compatible (oasdiff, Buf, GraphQL Inspector, AsyncAPI diff).",
                        "value": "Prevents provider-side changes from silently breaking unknown consumers.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Architecture & Contract Testing",
                    },
                ],
            },
            {
                "flaw_id": "ap-blue-green-no-session-drain",
                "flaw_type": "antipattern",
                "practice": "Blue-Green Deployment",
                "antipattern": "Switching traffic without accounting for in-flight requests, schema compatibility and session state.",
                "consequence": "A technically instant cutover produces user-visible errors and data corruption across the boundary.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Graceful Shutdown and Connection Draining Testing",
                        "term_id": "graceful-shutdown-and-connection-draining-testing",
                        "definition": "Verify in-flight requests complete and load balancers stop routing before process exit.",
                        "value": "The most common cause of user-visible errors during an otherwise correct deployment.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                    {
                        "term_name": "N-1 / N+1 Compatibility Testing",
                        "term_id": "n-1-n-1-compatibility-testing",
                        "definition": "Test that the previous and next application versions both work against the current schema and protocol.",
                        "value": "The constraint that makes independent, order-free deployment possible.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Delivery, Deployment & Progressive Rollout",
                    },
                    {
                        "term_name": "Zero-Downtime Deploy Validation",
                        "term_id": "zero-downtime-deploy-validation",
                        "definition": "Verify that deployments cause no user-visible errors, including during connection draining and migration windows.",
                        "value": "Deployability is a property to be proven continuously, not assumed.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Delivery, Deployment & Progressive Rollout",
                    },
                ],
            },
            {
                "flaw_id": "ap-dora-leaderboards",
                "flaw_type": "antipattern",
                "practice": "DORA Metrics (five keys)",
                "antipattern": "Publishing per-team deployment frequency leaderboards.",
                "consequence": "Goodhart's Law: teams split deployments artificially, and the metric rises while throughput does not.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "Metric Anti-Gaming Controls",
                        "term_id": "metric-anti-gaming-controls",
                        "definition": "Pair every productivity metric with counter-metrics and outcome measures to resist Goodhart's Law.",
                        "value": "Any single optimised metric will be corrupted within a quarter if unguarded.",
                        "tier": 2,
                        "gate": None,
                        "domain": "CI/CD, Tooling & Developer Productivity",
                    },
                    {
                        "term_name": "SPACE Framework",
                        "term_id": "space-framework",
                        "definition": "Satisfaction, performance, activity, communication and efficiency/flow as five dimensions of developer productivity.",
                        "value": "Prevents the single-metric thinking that makes productivity measurement actively harmful.",
                        "tier": 2,
                        "gate": None,
                        "domain": "CI/CD, Tooling & Developer Productivity",
                    },
                    {
                        "term_name": "DevEx Framework",
                        "term_id": "devex-framework",
                        "definition": "Feedback loops, cognitive load and flow state as the three actionable dimensions of developer experience.",
                        "value": "Maps every finding directly onto a change a leader can make.",
                        "tier": 1,
                        "gate": None,
                        "domain": "CI/CD, Tooling & Developer Productivity",
                    },
                    {
                        "term_name": "DX Core 4",
                        "term_id": "dx-core-4",
                        "definition": "Speed, effectiveness, quality and impact as a balanced, executive-legible productivity model.",
                        "value": "Reconciles DORA, SPACE and DevEx into one framework usable outside engineering.",
                        "tier": 2,
                        "gate": None,
                        "domain": "CI/CD, Tooling & Developer Productivity",
                    },
                ],
            },
            {
                "flaw_id": "ap-error-budget-ignored",
                "flaw_type": "antipattern",
                "practice": "Error Budget Policy Enforcement",
                "antipattern": "Defining an SLO and error budget but never acting when the budget is exhausted.",
                "consequence": "The mechanism becomes a dashboard instead of a governance rule, and reliability work never gets scheduled.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Error-Budget-Gated Release",
                        "term_id": "error-budget-gated-release",
                        "definition": "Automatically link change velocity to remaining reliability budget.",
                        "value": "Institutionalises the trade-off between speed and stability so it is not renegotiated every release.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Delivery, Deployment & Progressive Rollout",
                    },
                    {
                        "term_name": "Multi-Window Multi-Burn-Rate Alerting",
                        "term_id": "multi-window-multi-burn-rate-alerting",
                        "definition": "Alert on error-budget consumption rate across several time windows to balance sensitivity against noise.",
                        "value": "The standard method for making SLO alerts both fast and actionable.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Toil Audit",
                        "term_id": "toil-audit",
                        "definition": "Measure the volume, distribution and cost of manual, repetitive, automatable operational work.",
                        "value": "Toil is invisible in delivery metrics and grows until it consumes engineering capacity.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                ],
            },
            {
                "flaw_id": "ap-property-trivial",
                "flaw_type": "antipattern",
                "practice": "Property-Based Testing",
                "antipattern": "Writing trivial properties that restate the implementation.",
                "consequence": "The suite generates thousands of cases that verify nothing, at real compute cost.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "Differential Testing",
                        "term_id": "differential-testing",
                        "definition": "Run the same inputs against two or more independent implementations of a specification and flag any behavioural disagreement.",
                        "value": "Turns an unavailable oracle into a comparison; how compilers, parsers and databases are validated in practice.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Test Design, Oracles & Generative Testing",
                    },
                    {
                        "term_name": "Metamorphic Testing",
                        "term_id": "metamorphic-testing",
                        "definition": "Replace the missing test oracle with metamorphic relations between related inputs and outputs of multiple executions.",
                        "value": "The standard remedy for the oracle problem in ML, compilers, search, simulation and other non-deterministic systems.",
                        "tier": 1,
                        "gate": "Explicit metamorphic-relation catalogue for every oracle-free component (ML, search, compilers, simulation).",
                        "domain": "Test Design, Oracles & Generative Testing",
                    },
                    {
                        "term_name": "Mutation Score / Mutation Adequacy",
                        "term_id": "mutation-score-mutation-adequacy",
                        "definition": "Percentage of injected artificial faults (mutants) that the test suite detects.",
                        "value": "The best available proxy for a suite's real fault-detection power, far stronger than line coverage.",
                        "tier": 1,
                        "gate": "Incremental mutation run on changed files only; threshold enforced per package, not globally.",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                ],
            },
            {
                "flaw_id": "ap-semantic-conventions-bespoke",
                "flaw_type": "antipattern",
                "practice": "Semantic Conventions",
                "antipattern": "Inventing bespoke span names and metric names per team.",
                "consequence": "Telemetry cannot be joined or alerted on consistently across services, defeating the purpose of tracing.",
                "severity": "MEDIUM",
                "recommendations": [
                    {
                        "term_name": "OpenTelemetry / OTLP",
                        "term_id": "opentelemetry-otlp",
                        "definition": "The vendor-neutral standard and wire protocol for traces, metrics, logs and profiles.",
                        "value": "Removes instrumentation lock-in and makes telemetry itself testable and portable.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Instrumentation Assertion Testing",
                        "term_id": "instrumentation-assertion-testing",
                        "definition": "Assert that the code actually emits the spans, metrics and attributes it is specified to emit.",
                        "value": "Telemetry is a contract with operators and must be tested like any other interface.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                    {
                        "term_name": "Cardinality Management",
                        "term_id": "cardinality-management",
                        "definition": "Bound the number of distinct attribute-value combinations allowed on metrics.",
                        "value": "Undisciplined labels are the primary cause of runaway observability cost and slow queries.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Observability & Telemetry Engineering",
                    },
                ],
            },
            {
                "flaw_id": "ap-audit-screenshot-evidence",
                "flaw_type": "antipattern",
                "practice": "Compliance, Governance & Audit",
                "antipattern": "Collecting evidence by screenshot shortly before the audit window closes.",
                "consequence": "Evidence cannot cover the observation period, remediation workflows are undocumented, and findings accumulate.",
                "severity": "CRITICAL",
                "recommendations": [
                    {
                        "term_name": "Continuous Compliance",
                        "term_id": "continuous-compliance",
                        "definition": "Continuously generate timestamped control evidence rather than assembling it before an audit.",
                        "value": "Audit windows are 3-12 months; point-in-time scans leave provable gaps.",
                        "tier": 1,
                        "gate": "Control evidence generated automatically with timestamps spanning the full audit observation window.",
                        "domain": "Compliance, Governance & Audit",
                    },
                    {
                        "term_name": "Immutable Audit Trail",
                        "term_id": "immutable-audit-trail",
                        "definition": "Tamper-evident, append-only, time-stamped records of privileged and security-relevant activity.",
                        "value": "Evidence that can be altered is not evidence.",
                        "tier": 1,
                        "gate": "Append-only, time-stamped, tamper-evident logs for all privileged and security-relevant activity.",
                        "domain": "Compliance, Governance & Audit",
                    },
                    {
                        "term_name": "Cross-Framework Control Mapping",
                        "term_id": "cross-framework-control-mapping",
                        "definition": "Maintain a single control set mapped to every applicable framework to avoid duplicated evidence effort.",
                        "value": "Reduces assessment cost dramatically by making one artefact serve many frameworks.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Compliance, Governance & Audit",
                    },
                ],
            },
        ]

        raw_deprecations: list[dict[str, Any]] = [
            {
                "flaw_id": "dep-dread",
                "flaw_type": "deprecation",
                "subject": "DREAD",
                "status": "informally-deprecated",
                "reason": "Scores are subjective, dimensions overlap, inter-reviewer variance is high, and it produces no enumeration behind the numbers.",
                "guidance": "Use STRIDE for enumeration, attack trees for multi-step realism, CVSS for known-CVE scoring and FAIR for dollar-denominated risk. DREAD may still work as a small-team shared rubric but should not be adopted fresh.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Threat Modeling (STRIDE)",
                        "term_id": "threat-modeling-stride",
                        "definition": "Apply six threat categories (spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege) to each element and trust boundary.",
                        "value": "Per-element application gives provable coverage; applying it to 'the system' gives six useless bullets.",
                        "tier": 1,
                        "gate": "Threat model per component and trust boundary, refreshed on architecture change, with each threat traced to a testable requirement and a test.",
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "Attack Tree Analysis",
                        "term_id": "attack-tree-analysis",
                        "definition": "Decompose an attacker goal into alternative and required sub-goals to reveal multi-step chains.",
                        "value": "Captures chained exploits that per-element threat enumeration structurally misses.",
                        "tier": 3,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "CVSS (Common Vulnerability Scoring System)",
                        "term_id": "cvss-common-vulnerability-scoring-system",
                        "definition": "A standard severity score for a specific known vulnerability.",
                        "value": "Triage input, not a design metric; score the vulnerability, not the threat to your system.",
                        "tier": 3,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                ],
            },
            {
                "flaw_id": "dep-hystrix",
                "flaw_type": "deprecation",
                "subject": "Hystrix",
                "status": "maintenance-mode",
                "reason": "Netflix stopped active development; the library is maintained but not recommended for new projects.",
                "guidance": "Use Resilience4j (JVM) or Polly (.NET) for circuit breaking, bulkheads and bulkhead-style concurrency limits.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Bulkhead Isolation Verification",
                        "term_id": "bulkhead-isolation-verification",
                        "definition": "Prove that resource partitioning per dependency or tenant actually contains saturation.",
                        "value": "Without verification, bulkheads become decoration that fails at exactly the wrong moment.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                    {
                        "term_name": "Backpressure Verification",
                        "term_id": "backpressure-verification",
                        "definition": "Confirm that downstream saturation propagates flow control upstream instead of unbounded buffering.",
                        "value": "Unbounded queues convert a slowdown into a memory-exhaustion outage.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Reliability, Resilience & Chaos Engineering",
                    },
                ],
            },
            {
                "flaw_id": "dep-mttr-as-a-stability-metric",
                "flaw_type": "deprecation",
                "subject": "MTTR as a stability metric",
                "status": "renamed-and-reclassified",
                "reason": "In 2023 DORA renamed it 'failed deployment recovery time' and in 2024 moved it from stability to throughput, reflecting that fast recovery enables faster deployment rather than merely preventing damage.",
                "guidance": "Report 'failed deployment recovery time' and include 'deployment rework rate' as the fifth metric. Most published lists still say four metrics.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "DORA Metrics (five keys)",
                        "term_id": "dora-metrics-five-keys",
                        "definition": "Deployment frequency, change lead time, failed deployment recovery time, change fail rate and deployment rework rate.",
                        "value": "The industry baseline for delivery performance; note that MTTR was renamed in 2023 and rework rate added in 2024.",
                        "tier": 1,
                        "gate": "Automated extraction from CI/CD and incident tooling, reported per team as trends rather than as targets.",
                        "domain": "CI/CD, Tooling & Developer Productivity",
                    }
                ],
            },
            {
                "flaw_id": "dep-line-coverage-as-a-quality-tar",
                "flaw_type": "deprecation",
                "subject": "Line coverage as a quality target",
                "status": "misapplied-in-practice",
                "reason": "Statement coverage is the weakest structural criterion and is trivially gamed by assertion-free tests.",
                "guidance": "Use coverage to find untested code, not to certify tested code. Gate on diff coverage; measure adequacy with mutation score.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Diff / Patch Coverage",
                        "term_id": "diff-patch-coverage",
                        "definition": "Coverage restricted to the lines changed in a specific change set.",
                        "value": "Far more actionable than global coverage and immune to the legacy-code dilution problem.",
                        "tier": 1,
                        "gate": "Merge blocked below an agreed percentage on changed lines (typical starting point 80%).",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                    {
                        "term_name": "Mutation Score / Mutation Adequacy",
                        "term_id": "mutation-score-mutation-adequacy",
                        "definition": "Percentage of injected artificial faults (mutants) that the test suite detects.",
                        "value": "The best available proxy for a suite's real fault-detection power, far stronger than line coverage.",
                        "tier": 1,
                        "gate": "Incremental mutation run on changed files only; threshold enforced per package, not globally.",
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                    {
                        "term_name": "Coverage Ratcheting",
                        "term_id": "coverage-ratcheting",
                        "definition": "Prevent the coverage percentage from decreasing on any change rather than demanding an absolute target.",
                        "value": "Achieves incremental improvement without a demoralising big-bang coverage initiative.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Coverage, Adequacy & Code Health Metrics",
                    },
                ],
            },
            {
                "flaw_id": "dep-blind-test-retries-as-a-flake-",
                "flaw_type": "deprecation",
                "subject": "Blind test retries as a flake remedy",
                "status": "anti-pattern",
                "reason": "Retries convert genuine defects into intermittent production incidents with no owner and hide nondeterminism that indicates real concurrency or state bugs.",
                "guidance": "Retry only for infrastructure faults, with telemetry. Quarantine and repair flaky tests rather than papering over them.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Flaky Test Detection and Quarantine",
                        "term_id": "flaky-test-detection-and-quarantine",
                        "definition": "Automatically detect non-deterministic tests, move them out of the critical path and track their repair.",
                        "value": "Quarantine preserves signal quality while keeping the debt visible instead of merely tolerated.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Retry Semantics and Masking Risk",
                        "term_id": "retry-semantics-and-masking-risk",
                        "definition": "Distinguish legitimate infrastructure retries from retries that hide genuine defects.",
                        "value": "Blind retries convert real bugs into intermittent production incidents with no owners.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                    {
                        "term_name": "Nondeterminism Auditing",
                        "term_id": "nondeterminism-auditing",
                        "definition": "Systematically inventory uncontrolled sources of variation: time, randomness, network, parallel order, locale, shared state.",
                        "value": "You cannot fix flakiness without first enumerating its causes.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Environments, Test Data & Determinism",
                    },
                ],
            },
            {
                "flaw_id": "dep-checkbox-accessibility-scannin",
                "flaw_type": "deprecation",
                "subject": "Checkbox accessibility scanning",
                "status": "insufficient",
                "reason": "Automated scanners detect roughly 30-40% of WCAG issues and are blind to judgment calls such as meaningful alt text and logical focus order.",
                "guidance": "Automated scanning is the floor, not the standard. Critical flows require manual assistive-technology passes.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Screen Reader Compatibility Testing",
                        "term_id": "screen-reader-compatibility-testing",
                        "definition": "Verify semantic structure, names, roles, states and live-region announcements with NVDA, JAWS, VoiceOver or TalkBack.",
                        "value": "Automated scanners catch roughly a third of accessibility defects; this is where the rest live.",
                        "tier": 1,
                        "gate": "Manual assistive-technology pass on critical flows each release, with automated scanning as a continuous floor.",
                        "domain": "Client, Mobile & Web Testing",
                    },
                    {
                        "term_name": "Keyboard-Only Navigation Testing",
                        "term_id": "keyboard-only-navigation-testing",
                        "definition": "Operate the entire product without a pointing device, verifying reachability and operability.",
                        "value": "A WCAG Level A requirement and a strong predictor of general interaction quality.",
                        "tier": 1,
                        "gate": "Automated keyboard reachability and focus-order assertions on every interactive component.",
                        "domain": "Client, Mobile & Web Testing",
                    },
                    {
                        "term_name": "Focus Management and Focus Trap Testing",
                        "term_id": "focus-management-and-focus-trap-testing",
                        "definition": "Verify logical focus order, visible focus indication and correct trapping/release in modals.",
                        "value": "Focus defects make interfaces unusable for assistive-technology users.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Client, Mobile & Web Testing",
                    },
                ],
            },
            {
                "flaw_id": "dep-annual-point-in-time-penetrati",
                "flaw_type": "deprecation",
                "subject": "Annual point-in-time penetration testing",
                "status": "insufficient-for-modern-frameworks",
                "reason": "PCI DSS 4.0, SOC 2 Type II and FedRAMP require evidence of controls operating across an observation window; point-in-time scans leave provable gaps.",
                "guidance": "Run continuous or quarterly testing that accumulates timestamped evidence across the audit period.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Continuous Compliance",
                        "term_id": "continuous-compliance",
                        "definition": "Continuously generate timestamped control evidence rather than assembling it before an audit.",
                        "value": "Audit windows are 3-12 months; point-in-time scans leave provable gaps.",
                        "tier": 1,
                        "gate": "Control evidence generated automatically with timestamps spanning the full audit observation window.",
                        "domain": "Compliance, Governance & Audit",
                    },
                    {
                        "term_name": "Purple Teaming",
                        "term_id": "purple-teaming",
                        "definition": "Red and blue teams collaborate iteratively so every attack technique ends in a detection or a documented gap.",
                        "value": "Converts offensive findings into defensive capability instead of a report that decays.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                    {
                        "term_name": "Adversary Emulation",
                        "term_id": "adversary-emulation",
                        "definition": "Replay realistic, multi-stage adversary behaviour mapped to a specific threat actor or technique set.",
                        "value": "Tests the whole detection-and-response chain, not just prevention controls.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Security & Application Security Testing",
                    },
                ],
            },
            {
                "flaw_id": "dep-json-over-the-wire-without-con",
                "flaw_type": "deprecation",
                "subject": "JSON-over-the-wire without contract testing",
                "status": "risk",
                "reason": "JSON has no built-in compatibility rules, so a removed or renamed field silently breaks consumers.",
                "guidance": "Protobuf gives partial natural protection; JSON gives none. Enforce via contracts or schema diffing.",
                "severity": "HIGH",
                "recommendations": [
                    {
                        "term_name": "Consumer-Driven Contract Testing",
                        "term_id": "consumer-driven-contract-testing",
                        "definition": "The consumer defines the minimal interactions it depends on; the provider later verifies it still satisfies them.",
                        "value": "Enables independent deployment of services without a full integration environment.",
                        "tier": 1,
                        "gate": "Consumer pacts published per build; provider verifies; `can-i-deploy` gates every production deployment.",
                        "domain": "Architecture & Contract Testing",
                    },
                    {
                        "term_name": "Breaking Change Detection",
                        "term_id": "breaking-change-detection",
                        "definition": "Automatically classify schema changes as breaking, dangerous or compatible (oasdiff, Buf, GraphQL Inspector, AsyncAPI diff).",
                        "value": "Prevents provider-side changes from silently breaking unknown consumers.",
                        "tier": 1,
                        "gate": None,
                        "domain": "Architecture & Contract Testing",
                    },
                    {
                        "term_name": "Serialization Backward Compatibility Testing",
                        "term_id": "serialization-backward-compatibility-testing",
                        "definition": "Verify that new code can read payloads written by old code and vice versa.",
                        "value": "The practical constraint that governs whether a rollout or rollback is actually safe.",
                        "tier": 2,
                        "gate": None,
                        "domain": "Architecture & Contract Testing",
                    },
                ],
            },
        ]

        for ap in raw_antipatterns:
            recs = []
            recs_list: list[dict[str, Any]] = ap.get("recommendations", [])
            for r in recs_list:
                steps = _build_default_implementation_steps(str(r["term_name"]), r.get("gate"))
                val = (
                    str(r["value"])
                    if r.get("value")
                    else f"Adopts established reliability and testing standards for {r['term_name']}."
                )
                tier_val = r.get("tier")
                tier = int(tier_val) if tier_val is not None else 1
                recs.append(
                    PracticeRecommendation(
                        name=str(r["term_name"]),
                        term_id=str(r["term_id"]),
                        definition=str(r["definition"]),
                        value_justification=val,
                        tier=tier,
                        domain=str(r["domain"]),
                        gate_criteria=str(r["gate"]) if r.get("gate") else None,
                        implementation_steps=steps,
                        standard_reference=str(r["domain"]),
                    )
                )

            plan = RemediationPlan(
                flaw_id=str(ap["flaw_id"]),
                flaw_type="antipattern",
                identified_flaw=str(ap["antipattern"]),
                consequence_or_reason=str(ap["consequence"]),
                severity=str(ap["severity"]),
                recommended_practices=recs,
                guidance=f"Replace '{ap['practice']}' antipattern with sanctioned taxonomy alternatives.",
            )
            self._antipattern_plans[str(ap["flaw_id"])] = plan
            self._practice_to_plan[str(ap["practice"]).lower()] = plan

        for dep in raw_deprecations:
            recs = []
            dep_recs_list: list[dict[str, Any]] = dep.get("recommendations", [])
            for r in dep_recs_list:
                steps = _build_default_implementation_steps(str(r["term_name"]), r.get("gate"))
                val = (
                    str(r["value"])
                    if r.get("value")
                    else f"Adopts established reliability and testing standards for {r['term_name']}."
                )
                tier_val = r.get("tier")
                tier = int(tier_val) if tier_val is not None else 1
                recs.append(
                    PracticeRecommendation(
                        name=str(r["term_name"]),
                        term_id=str(r["term_id"]),
                        definition=str(r["definition"]),
                        value_justification=val,
                        tier=tier,
                        domain=str(r["domain"]),
                        gate_criteria=str(r["gate"]) if r.get("gate") else None,
                        implementation_steps=steps,
                        standard_reference=str(r["domain"]),
                    )
                )

            plan = RemediationPlan(
                flaw_id=str(dep["flaw_id"]),
                flaw_type="deprecation",
                identified_flaw=f"Deprecated practice: {dep['subject']} ({dep['status']})",
                consequence_or_reason=str(dep["reason"]),
                severity=str(dep["severity"]),
                recommended_practices=recs,
                guidance=str(dep["guidance"]) if dep.get("guidance") else None,
            )
            self._deprecation_plans[str(dep["flaw_id"])] = plan
            self._subject_to_plan[str(dep["subject"]).lower()] = plan

    def get_remediation_for_antipattern(
        self,
        identifier: str,
        include_steps: bool = True,
    ) -> RemediationPlan | None:
        """Lookup remediation plan for antipattern ID or practice title."""
        t0 = time.perf_counter()
        plan = self._antipattern_plans.get(identifier) or self._practice_to_plan.get(
            identifier.lower()
        )
        if not plan:
            return None

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return self._format_plan(plan, include_steps, latency_ms)

    def get_remediation_for_deprecation(
        self,
        identifier: str,
        include_steps: bool = True,
    ) -> RemediationPlan | None:
        """Lookup remediation plan for deprecation ID or subject title."""
        t0 = time.perf_counter()
        plan = self._deprecation_plans.get(identifier) or self._subject_to_plan.get(
            identifier.lower()
        )
        if not plan:
            return None

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return self._format_plan(plan, include_steps, latency_ms)

    def get_remediation_by_flaw_id(
        self,
        flaw_id: str,
        include_steps: bool = True,
    ) -> RemediationPlan | None:
        """Universal lookup by flaw ID (antipattern or deprecation)."""
        return self.get_remediation_for_antipattern(
            flaw_id, include_steps
        ) or self.get_remediation_for_deprecation(flaw_id, include_steps)

    def generate_remediation_for_finding(
        self,
        finding: dict[str, Any] | Any,
        include_steps: bool = True,
    ) -> RemediationPlan:
        """Generate a complete RemediationPlan for a scan finding or fallback gracefully."""
        t0 = time.perf_counter()
        rule_id = (
            getattr(finding, "rule_id", None)
            or (finding.get("rule_id") if isinstance(finding, dict) else None)
            or ""
        )
        practice = (
            getattr(finding, "practice", None)
            or (finding.get("practice") if isinstance(finding, dict) else None)
            or ""
        )
        antipattern = (
            getattr(finding, "antipattern", None)
            or (finding.get("antipattern") if isinstance(finding, dict) else None)
            or ""
        )
        consequence = (
            getattr(finding, "consequence", None)
            or (finding.get("consequence") if isinstance(finding, dict) else None)
            or ""
        )
        severity = (
            getattr(finding, "severity", None)
            or (finding.get("severity") if isinstance(finding, dict) else None)
            or "HIGH"
        )

        plan = (
            self.get_remediation_by_flaw_id(rule_id, include_steps)
            or self.get_remediation_for_antipattern(practice, include_steps)
            or self.get_remediation_for_deprecation(practice, include_steps)
        )
        if plan:
            return plan

        # Fallback when flaw is unmapped: synthesize from finding attributes
        latency_ms = (time.perf_counter() - t0) * 1000.0
        instead_list = (
            getattr(finding, "instead", None)
            or (finding.get("instead") if isinstance(finding, dict) else [])
            or []
        )
        fallback_recs = []
        for inst in instead_list:
            fallback_recs.append(
                PracticeRecommendation(
                    name=inst,
                    term_id=inst.lower().replace(" ", "-"),
                    definition=f"Sanctioned alternative practice for {practice}.",
                    value_justification="Adopts industry best practice and satisfies regulatory requirements.",
                    tier=1,
                    domain="governance",
                    gate_criteria="Enforce peer review and compliance sign-off.",
                    implementation_steps=_build_default_implementation_steps(inst, None)
                    if include_steps
                    else [],
                )
            )

        return RemediationPlan(
            flaw_id=rule_id or "unmapped-flaw",
            flaw_type="antipattern",
            identified_flaw=antipattern or practice or "Identified non-compliant practice",
            consequence_or_reason=consequence or "Increases regulatory and technical defect risk.",
            severity=severity,
            recommended_practices=fallback_recs,
            guidance="Follow sanctioned compliance taxonomy standards.",
            lookup_latency_ms=latency_ms,
        )

    def generate_remediation_report(
        self,
        findings: list[dict[str, Any] | Any],
        include_steps: bool = True,
    ) -> RemediationReport:
        """Generate batch remediation report across multiple audit findings."""
        plans: list[RemediationPlan] = []
        unique_practices: set[str] = set()

        for f in findings:
            plan = self.generate_remediation_for_finding(f, include_steps=include_steps)
            plans.append(plan)
            for rec in plan.recommended_practices:
                unique_practices.add(rec.name)

        remediated_count = sum(1 for p in plans if len(p.recommended_practices) > 0)

        return RemediationReport(
            total_findings=len(findings),
            remediated_findings=remediated_count,
            plans=plans,
            unique_recommended_practices=sorted(list(unique_practices)),
        )

    def list_catalog(
        self,
        flaw_type: str | None = None,
        tier: int | None = None,
    ) -> list[RemediationPlan]:
        """List all 38 available prescriptive remediation plans."""
        results: list[RemediationPlan] = []
        if flaw_type is None or flaw_type.lower() == "antipattern":
            results.extend(self._antipattern_plans.values())
        if flaw_type is None or flaw_type.lower() == "deprecation":
            results.extend(self._deprecation_plans.values())

        if tier is not None:
            filtered = []
            for p in results:
                matching_recs = [r for r in p.recommended_practices if r.tier == tier]
                if matching_recs:
                    filtered.append(
                        RemediationPlan(
                            flaw_id=p.flaw_id,
                            flaw_type=p.flaw_type,
                            identified_flaw=p.identified_flaw,
                            consequence_or_reason=p.consequence_or_reason,
                            severity=p.severity,
                            recommended_practices=matching_recs,
                            guidance=p.guidance,
                            lookup_latency_ms=p.lookup_latency_ms,
                        )
                    )
            results = filtered

        return sorted(results, key=lambda p: (p.flaw_type, p.flaw_id))

    def get_stats(self) -> dict[str, Any]:
        """Return catalog metadata counts."""
        total_ap = len(self._antipattern_plans)
        total_dep = len(self._deprecation_plans)
        total_recs = sum(
            len(p.recommended_practices) for p in self._antipattern_plans.values()
        ) + sum(len(p.recommended_practices) for p in self._deprecation_plans.values())
        return {
            "total_antipattern_remediations": total_ap,
            "total_deprecation_remediations": total_dep,
            "total_remediation_plans": total_ap + total_dep,
            "total_recommended_practice_mappings": total_recs,
        }

    def _format_plan(
        self,
        plan: RemediationPlan,
        include_steps: bool,
        latency_ms: float,
    ) -> RemediationPlan:
        """Format plan according to requested config."""
        recs = []
        for r in plan.recommended_practices:
            recs.append(
                PracticeRecommendation(
                    name=r.name,
                    term_id=r.term_id,
                    definition=r.definition,
                    value_justification=r.value_justification,
                    tier=r.tier,
                    domain=r.domain,
                    gate_criteria=r.gate_criteria,
                    implementation_steps=r.implementation_steps if include_steps else [],
                    standard_reference=r.standard_reference,
                )
            )
        return RemediationPlan(
            flaw_id=plan.flaw_id,
            flaw_type=plan.flaw_type,
            identified_flaw=plan.identified_flaw,
            consequence_or_reason=plan.consequence_or_reason,
            severity=plan.severity,
            recommended_practices=recs,
            guidance=plan.guidance,
            lookup_latency_ms=latency_ms,
        )


# Singleton accessor
_DEFAULT_REMEDIATION_ENGINE: PrescriptiveRemediationEngine | None = None


def get_default_remediation_engine() -> PrescriptiveRemediationEngine:
    """Retrieve or initialize singleton PrescriptiveRemediationEngine."""
    global _DEFAULT_REMEDIATION_ENGINE
    if _DEFAULT_REMEDIATION_ENGINE is None:
        _DEFAULT_REMEDIATION_ENGINE = PrescriptiveRemediationEngine()
    return _DEFAULT_REMEDIATION_ENGINE
