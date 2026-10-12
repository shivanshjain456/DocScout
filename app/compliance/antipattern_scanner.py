"""Regulatory and Technical Antipattern Scanner (FEAT-033).

Scans internal enterprise compliance manuals, policies, and technical architectures against
the 30 canonical taxonomy antipatterns to pinpoint systemic organizational failure modes
before external regulatory inspections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("docscout.compliance.antipattern_scanner")


@dataclass
class AntipatternRule:
    """Canonical antipattern definition with calibrated detection patterns."""

    id: str
    practice: str
    antipattern: str
    consequence: str
    instead: list[str]
    domain_category: str
    severity: str = "HIGH"  # CRITICAL, HIGH, MEDIUM
    regex_patterns: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "practice": self.practice,
            "antipattern": self.antipattern,
            "consequence": self.consequence,
            "instead": self.instead,
            "domain_category": self.domain_category,
            "severity": self.severity,
            "regex_patterns": self.regex_patterns,
            "keywords": self.keywords,
        }


@dataclass
class AntipatternFinding:
    """Detection instance found within scanned compliance manual or architecture spec."""

    rule_id: str
    practice: str
    antipattern: str
    consequence: str
    instead: list[str]
    severity: str
    domain_category: str
    matched_snippet: str
    line_number: int | None = None
    confidence: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "practice": self.practice,
            "antipattern": self.antipattern,
            "consequence": self.consequence,
            "instead": self.instead,
            "severity": self.severity,
            "domain_category": self.domain_category,
            "matched_snippet": self.matched_snippet,
            "line_number": self.line_number,
            "confidence": round(self.confidence, 2),
        }


class AntipatternScanner:
    """Engine executing comprehensive antipattern scanning across organizational texts."""

    def __init__(self) -> None:
        self._rules: dict[str, AntipatternRule] = {}
        self._compiled_matchers: list[tuple[re.Pattern[str], str]] = []
        self._load_canonical_antipatterns()

    def register_rule(self, rule: AntipatternRule) -> None:
        """Register an antipattern and compile its regex detection rules."""
        self._rules[rule.id] = rule
        for pat in rule.regex_patterns:
            try:
                rx = re.compile(pat, re.IGNORECASE)
                self._compiled_matchers.append((rx, rule.id))
            except re.error as err:
                logger.warning("invalid_antipattern_pattern", pattern=pat, error=str(err))

    def get_rule(self, rule_id: str) -> AntipatternRule | None:
        return self._rules.get(rule_id)

    def list_rules(
        self,
        domain_category: str | None = None,
        severity: str | None = None,
    ) -> list[AntipatternRule]:
        rules = list(self._rules.values())
        if domain_category:
            rules = [r for r in rules if r.domain_category.lower() == domain_category.lower()]
        if severity:
            rules = [r for r in rules if r.severity.upper() == severity.upper()]
        return sorted(rules, key=lambda r: (r.domain_category, r.id))

    def _load_canonical_antipatterns(self) -> None:
        """Load the 30 canonical taxonomy antipatterns from term-taxonomy specification."""
        raw_antipatterns = [
            (
                "ap-line-coverage",
                "Statement Coverage",
                "Using line coverage as a quality target or a release gate.",
                "Teams write assertion-free tests that execute code without verifying anything, and the metric rises while defect detection does not.",
                [
                    "Diff / Patch Coverage",
                    "Mutation Score / Mutation Adequacy",
                    "Coverage Ratcheting",
                ],
                "testing",
                "HIGH",
                [
                    r"\b(?:target|require|mandate)\s+(?:80%|90%|100%)\s+line\s+coverage\b",
                    r"\bline\s+coverage\s+as\s+a\s+(?:quality\s+target|release\s+gate)\b",
                ],
                ["line coverage as a quality target", "100% line coverage release gate"],
            ),
            (
                "ap-mutation-all",
                "Mutation Testing",
                "Running mutation testing across the whole repository on every commit and demanding 100%.",
                "Builds become unusably slow, the equivalent-mutant problem makes 100% unattainable, and the practice is abandoned entirely.",
                ["Diff / Patch Coverage", "Regression Test Selection", "Test Suite Runtime Budget"],
                "testing",
                "MEDIUM",
                [
                    r"\bmutation\s+testing\s+across\s+the\s+whole\s+repo(?:sitory)?\s+on\s+every\s+commit\b",
                    r"\bdemanding\s+100%\s+mutation\s+score\b",
                ],
                ["mutation testing across the whole repository", "demanding 100% mutation"],
            ),
            (
                "ap-mock-everything",
                "Test Doubles Taxonomy",
                "Mocking everything so that tests verify the test's own assumptions rather than real behaviour.",
                "Tests pass while integration fails, because the mock encoded the same misunderstanding as the code under test.",
                [
                    "Testcontainers-Based Integration Testing",
                    "Consumer-Driven Contract Testing",
                    "Testing Honeycomb",
                ],
                "testing",
                "HIGH",
                [
                    r"\bmock(?:ing)?\s+everything\s+(?:in\s+tests|so\s+that\s+tests\s+verify)\b",
                    r"\bmock\s+all\s+(?:external\s+)?dependencies\s+in\s+integration\s+tests\b",
                ],
                ["mocking everything", "mock all dependencies"],
            ),
            (
                "ap-chaos-no-hypothesis",
                "Chaos Engineering",
                "Breaking things in production without a steady-state hypothesis, abort conditions or blast-radius limits.",
                "Outages with no learning, lost trust with stakeholders, and chaos experiments permanently banned.",
                [
                    "Steady-State Hypothesis",
                    "Automated Rollback Verification",
                    "Blast-Radius Containment",
                ],
                "reliability",
                "CRITICAL",
                [
                    r"\bbreaking\s+things\s+in\s+production\s+without\s+a\s+steady-state\s+hypothesis\b",
                    r"\bchaos\s+experiments?\s+without\s+(?:abort\s+conditions|blast-radius)\b",
                ],
                ["breaking things in production without", "chaos without abort conditions"],
            ),
            (
                "ap-feature-flags-stale",
                "Feature Flags",
                "Accumulating unowned, never-expiring toggles.",
                "Dead code paths multiply, combinatorial testing becomes impossible, and toggling an old flag causes unforeseen production outages.",
                ["Feature Flag Lifecycle Governance", "Dead Flag Pruning", "Toggle Debt Register"],
                "deployment",
                "HIGH",
                [
                    r"\baccumulating\s+unowned,\s+never-expiring\s+toggles\b",
                    r"\bfeature\s+flags?\s+without\s+(?:owner|expiration|sunset)\s+dates?\b",
                ],
                [
                    "accumulating unowned, never-expiring toggles",
                    "feature flags without expiration",
                ],
            ),
            (
                "ap-canary-dashboard-eye",
                "Canary Release",
                "Routing 5% of traffic to a canary and watching a dashboard by eye.",
                "Humans miss gradual metric regressions or subtle error spikes, and the canary is promoted before an incident is noticed.",
                [
                    "Automated Canary Analysis (ACA)",
                    "Mann-Whitney U Test Gating",
                    "Metric Deviation Rollback",
                ],
                "deployment",
                "HIGH",
                [
                    r"\bwatching\s+a\s+dashboard\s+by\s+eye\b",
                    r"\bmanual\s+canary\s+inspection\s+without\s+automated\s+analysis\b",
                ],
                ["watching a dashboard by eye", "manual canary monitoring"],
            ),
            (
                "ap-ab-early-stopping",
                "A/B Testing",
                "Stopping the test as soon as the result crosses significance.",
                "False-positive rate inflates dramatically (peeking problem), leading to rolling out changes that actually harm business metrics.",
                ["Fixed-Horizon Sample Sizing", "Sequential Testing (mSPRT)", "Peeking Correction"],
                "experimentation",
                "HIGH",
                [
                    r"\bstopping\s+the\s+test\s+as\s+soon\s+as\s+the\s+result\s+crosses\s+significance\b",
                    r"\bstopping\s+A\/B\s+test\s+early\s+on\s+p-value\b",
                ],
                [
                    "stopping the test as soon as the result crosses significance",
                    "early stopping on p-value",
                ],
            ),
            (
                "ap-judge-unvalidated",
                "LLM-as-a-Judge",
                "Adopting judge scores as ground truth without validating the judge.",
                "Position bias, length bias, and self-enhancement skew metrics; improvements in real capability register as declines.",
                [
                    "Human-in-the-Loop Judge Calibration",
                    "Cohen's Kappa Agreement Evaluation",
                    "Pairwise Swapped Position Benchmarking",
                ],
                "ai_llm",
                "CRITICAL",
                [
                    r"\badopt(?:ing|s)?\s+judge\s+scores\s+as\s+ground\s+truth\s+without\s+validating\b",
                    r"\bunvalidated\s+LLM\s+judge\s+as\s+ground\s+truth\b",
                ],
                [
                    "adopting judge scores as ground truth without validating",
                    "adopts judge scores as ground truth",
                    "unvalidated LLM judge",
                ],
            ),
            (
                "ap-prompt-injection-direct-only",
                "Prompt Injection Testing",
                "Testing only direct user-supplied injections in a RAG or agent system.",
                "Indirect prompt injections via retrieved documents, third-party API payloads, or search results compromise the system undetected.",
                [
                    "Indirect Injection Evaluation",
                    "Dual-LLM Security Isolation",
                    "Adversarial Retrieval Red-Teaming",
                ],
                "ai_llm",
                "CRITICAL",
                [
                    r"\btesting\s+only\s+direct\s+user-supplied\s+injections\b",
                    r"\bignoring\s+indirect\s+prompt\s+injections?\s+in\s+RAG\b",
                ],
                [
                    "testing only direct user-supplied injections",
                    "ignoring indirect prompt injections",
                ],
            ),
            (
                "ap-fairness-single-attribute",
                "Model Fairness Auditing",
                "Checking one protected attribute at a time and reporting a single aggregate accuracy figure.",
                "Intersectional bias remains invisible, aggregate metrics mask disparate impact on sub-demographics, and audits fail regulatory scrutiny.",
                [
                    "Intersectional Bias Disaggregation",
                    "Equalized Odds Auditing",
                    "Disparate Impact Ratio Analysis",
                ],
                "ai_llm",
                "HIGH",
                [
                    r"\bchecking\s+one\s+protected\s+attribute\s+at\s+a\s+time\b",
                    r"\bsingle\s+aggregate\s+accuracy\s+figure\s+for\s+fairness\b",
                ],
                [
                    "checking one protected attribute at a time",
                    "single aggregate accuracy figure for fairness",
                ],
            ),
            (
                "ap-data-quality-nulls-only",
                "Data Quality Dimensions",
                "Monitoring only nulls and duplicates because those checks are easy to write.",
                "Silent semantic drift, schema alterations, distribution skews, and referential integrity breaks pass into production pipelines.",
                [
                    "Multi-Dimensional Data Quality Assertions",
                    "Distribution Drift Detection",
                    "Cross-Table Referential Invariance",
                ],
                "data_engineering",
                "MEDIUM",
                [
                    r"\bmonitoring\s+only\s+nulls\s+and\s+duplicates\b",
                    r"\bonly\s+checking\s+null\s+values\s+in\s+data\s+pipelines\b",
                ],
                ["monitoring only nulls and duplicates", "only checking null values"],
            ),
            (
                "ap-testcontainers-per-unit",
                "Testcontainers-Based Integration Testing",
                "Spinning up the full production topology for every unit test.",
                "Test suite durations explode into hours, local developer loops freeze, and engineers stop running tests locally.",
                [
                    "Test Pyramid Discipline",
                    "In-Memory Fakes for Unit Tiers",
                    "Shared Integration Container Lifecycles",
                ],
                "testing",
                "MEDIUM",
                [
                    r"\b(?:spinning|spin|starting)\s+up\s+(?:the\s+full\s+production\s+topology|docker\s+containers)\s+for\s+(?:every|individual)\s+unit\s+tests?\b",
                    r"\bstarting\s+docker\s+containers\s+for\s+individual\s+unit\s+tests\b",
                ],
                [
                    "spinning up the full production topology for every unit test",
                    "docker containers for individual unit tests",
                    "spin up docker containers",
                ],
            ),
            (
                "ap-rts-filename-heuristics",
                "Regression Test Selection",
                "Selecting tests by filename or directory heuristics rather than real dependency analysis.",
                "Transitive breakage escapes into main branches because impacted downstream tests were omitted.",
                [
                    "Static / Dynamic Dependency Call-Graph RTS",
                    "Coverage Matrix Inversion",
                    "Affected Module Targeting",
                ],
                "testing",
                "HIGH",
                [
                    r"\bselecting\s+tests\s+by\s+filename\s+or\s+directory\s+heuristics\b",
                    r"\brts\s+based\s+on\s+folder\s+naming\s+conventions\b",
                ],
                ["selecting tests by filename or directory heuristics", "RTS by folder name"],
            ),
            (
                "ap-blind-test-retries",
                "Retry Semantics and Masking Risk",
                "Adding automatic retries to a failing test suite to make CI green.",
                "Retries mask genuine race conditions, deadlocks, and nondeterministic faults that inevitably trigger production incidents.",
                [
                    "Flaky Test Detection and Quarantine",
                    "Nondeterminism Auditing",
                    "Zero-Tolerance Unquarantined Flake Policy",
                ],
                "testing",
                "CRITICAL",
                [
                    r"\badding\s+automatic\s+retries\s+to\s+a\s+failing\s+test\s+suite\b",
                    r"\bblind\s+test\s+retries\s+as\s+a\s+flake\s+remedy\b",
                ],
                [
                    "adding automatic retries to a failing test suite",
                    "blind test retries as a flake remedy",
                ],
            ),
            (
                "ap-synthetic-data-unconstrained",
                "Synthetic Data Generation",
                "Generating statistically plausible data that violates real-world relationships and constraints.",
                "Models and integration tests train on synthetically invalid states that fail on real regulatory edge cases.",
                [
                    "Constraint-Preserving Copulas",
                    "Differential Privacy Bounds",
                    "Domain Invariant Enforcement",
                ],
                "data_engineering",
                "HIGH",
                [
                    r"\bgenerating\s+statistically\s+plausible\s+data\s+that\s+violates\s+real-world\s+relationships\b",
                    r"\bunconstrained\s+synthetic\s+data\s+generation\b",
                ],
                [
                    "generating statistically plausible data that violates real-world relationships",
                    "unconstrained synthetic data",
                ],
            ),
            (
                "ap-stride-system-whole",
                "Threat Modeling (STRIDE)",
                "Applying the six categories to 'the system' as a whole rather than per element and trust boundary.",
                "Produces vague, hand-waving mitigations and misses critical component-level privilege escalations.",
                [
                    "Data Flow Diagram (DFD) Decomposition",
                    "Element-by-Element STRIDE Enumeration",
                    "Trust Boundary Traversal Mapping",
                ],
                "security",
                "HIGH",
                [
                    r"\bappl(?:ying|ies)\s+the\s+six\s+categories\s+to\s+['\"]?the\s+system['\"]?\s+as\s+a\s+whole\b",
                    r"\bhigh-level\s+system-wide\s+STRIDE\s+without\s+boundary\s+decomposition\b",
                ],
                [
                    "applying the six categories to the system as a whole",
                    "applies the six categories to 'the system' as a whole",
                    "system-wide STRIDE",
                ],
            ),
            (
                "ap-sbom-shelfware",
                "SBOM (Software Bill of Materials)",
                "Generating an SBOM once for compliance and never consuming it operationally.",
                "Vulnerabilities disclosed after generation (like log4j) remain undetected in running workloads.",
                [
                    "Continuous VEX Enrichment",
                    "Ingestion-Time Vulnerability Matching",
                    "Continuous SBOM Auditing",
                ],
                "security",
                "HIGH",
                [
                    r"\bgenerating\s+an\s+SBOM\s+once\s+for\s+compliance\s+and\s+never\s+consuming\s+it\b",
                    r"\bone-time\s+static\s+SBOM\s+generation\b",
                ],
                [
                    "generating an SBOM once for compliance and never consuming it",
                    "one-time static SBOM",
                ],
            ),
            (
                "ap-annual-pentest-evidence",
                "Penetration Testing",
                "Running an annual penetration test as the primary evidence that controls work.",
                "Breaches occur in the 364-day blind spot between testing cycles; point-in-time evidence does not satisfy SOC 2 or DORA continuous assurance.",
                [
                    "Continuous Automated Red Teaming",
                    "Purple Team Exercises",
                    "Continuous Vulnerability Management",
                ],
                "security",
                "CRITICAL",
                [
                    r"\brunning\s+an\s+annual\s+penetration\s+test\s+as\s+the\s+primary\s+evidence\b",
                    r"\bannual\s+point-in-time\s+pen(?:etration)?\s+test(?:ing)?\s+as\s+compliance\s+proof\b",
                ],
                [
                    "running an annual penetration test as the primary evidence",
                    "annual penetration test only",
                ],
            ),
            (
                "ap-perf-empty-db-average",
                "Performance Testing",
                "Reporting average response time and running a closed-model load test against an empty database.",
                "P99 tail latency and database lock contention collapse in production under real customer table volumes.",
                [
                    "Open-Model Workload Generation",
                    "Production-Scale Data Volumes",
                    "Percentile Tail Latency Tracking (p95, p99)",
                ],
                "performance",
                "HIGH",
                [
                    r"\breporting\s+average\s+response\s+time\s+and\s+running\s+a\s+closed-model\s+load\s+test\b",
                    r"\bbenchmarking\s+latency\s+against\s+an\s+empty\s+database\b",
                ],
                [
                    "reporting average response time and running a closed-model load test",
                    "load test on empty database",
                ],
            ),
            (
                "ap-high-cardinality-metric-labels",
                "Observability & Telemetry Engineering",
                "Attaching user IDs, request IDs and raw URL paths as metric labels.",
                "Time series explosion crashes Prometheus/Mimir, drives exponential monitoring cloud costs, and degrades query performance.",
                [
                    "Bounded Cardinality Labels",
                    "Trace Context for High-Cardinality Correlation",
                    "Exemplar-Linked Spans",
                ],
                "observability",
                "HIGH",
                [
                    r"\battaching\s+user\s+IDs,\s+request\s+IDs\s+and\s+raw\s+URL\s+paths\s+as\s+metric\s+labels\b",
                    r"\bhigh-cardinality\s+labels\s+in\s+prometheus\s+metrics\b",
                ],
                [
                    "attaching user IDs, request IDs and raw URL paths as metric labels",
                    "high cardinality metric labels",
                ],
            ),
            (
                "ap-tracing-entry-only",
                "Distributed Tracing / Span Model",
                "Instrumenting only the entry service and assuming traces will join up.",
                "Broken trace propagation hides downstream database deadlocks and third-party API latency bottlenecks.",
                [
                    "W3C Trace Context Propagation",
                    "End-to-End Span Correlation",
                    "Context Bounded B3 Headers",
                ],
                "observability",
                "MEDIUM",
                [
                    r"\binstrumenting\s+only\s+the\s+entry\s+service\s+and\s+assuming\s+traces\s+will\s+join\b",
                    r"\bentry-only\s+tracing\s+without\s+downstream\s+context\s+propagation\b",
                ],
                ["instrumenting only the entry service", "entry-only tracing"],
            ),
            (
                "ap-sr117-onetime-signoff",
                "Independent Model Validation (SR 11-7 style)",
                "Treating validation as a one-time pre-launch sign-off.",
                "Data and concept drift degrade model precision, leading to undetected regulatory compliance breaches over time.",
                [
                    "Continuous Model Monitoring",
                    "Periodic Recalibration Gates",
                    "Autonomous Population Stability Index (PSI) Tracking",
                ],
                "governance",
                "CRITICAL",
                [
                    r"\btreating\s+validation\s+as\s+a\s+one-time\s+pre-launch\s+sign-off\b",
                    r"\bmodel\s+validation\s+conducted\s+only\s+prior\s+to\s+initial\s+deployment\b",
                ],
                [
                    "treating validation as a one-time pre-launch sign-off",
                    "one-time model validation",
                ],
            ),
            (
                "ap-accessibility-scanner-only",
                "Accessibility Testing",
                "Reporting an automated scan pass as evidence of accessibility compliance.",
                "Automated tools catch only 30-40% of WCAG criteria, leaving screen reader and keyboard accessibility broken for users.",
                [
                    "Screen Reader Validation",
                    "Keyboard Navigation Audits",
                    "Manual Focus Trap Passes",
                ],
                "accessibility",
                "HIGH",
                [
                    r"\breport(?:ing|s)?\s+an\s+automated\s+scan\s+pass\s+as\s+evidence\s+of\s+accessibility\s+compliance\b",
                    r"\bcheckbox\s+accessibility\s+scanning\b",
                ],
                [
                    "reporting an automated scan pass as evidence of accessibility compliance",
                    "reports an automated scan pass as evidence of accessibility compliance",
                    "checkbox accessibility scanning",
                ],
            ),
            (
                "ap-contract-pact-no-provider",
                "Contract Testing",
                "Publishing consumer pacts without ever running provider verification.",
                "Creates false confidence in API compatibility while breaking changes deploy to production unblocked.",
                [
                    "Bi-Directional Contract Verification",
                    "Provider CI Pipeline Gates",
                    "Can-I-Deploy CLI Assertions",
                ],
                "testing",
                "HIGH",
                [
                    r"\bpublishing\s+consumer\s+pacts\s+without\s+ever\s+running\s+provider\s+verification\b",
                    r"\bpact\s+contracts\s+without\s+provider\s+build\s+integration\b",
                ],
                [
                    "publishing consumer pacts without ever running provider verification",
                    "pact contracts without provider verification",
                ],
            ),
            (
                "ap-blue-green-no-session-drain",
                "Blue-Green Deployment",
                "Switching traffic without accounting for in-flight requests, schema compatibility and session state.",
                "Users experience dropped transactions, database locks, and session termination during cutover.",
                [
                    "Connection Draining (Lame Duck Mode)",
                    "Expand-and-Contract Database Migrations",
                    "Sticky Session Draining",
                ],
                "deployment",
                "HIGH",
                [
                    r"\bswitching\s+traffic\s+without\s+accounting\s+for\s+in-flight\s+requests\b",
                    r"\bblue-green\s+cutover\s+without\s+connection\s+draining\b",
                ],
                [
                    "switching traffic without accounting for in-flight requests",
                    "blue green cutover without connection draining",
                ],
            ),
            (
                "ap-dora-leaderboards",
                "DORA Metrics (five keys)",
                "Publishing per-team deployment frequency leaderboards.",
                "Encourages superficial micro-deployments to game metrics without delivering customer value or testing adequacy.",
                [
                    "Outcome-Oriented DORA Analysis",
                    "Blameless System Retrospectives",
                    "Systemic Flow Bottleneck Remediation",
                ],
                "governance",
                "MEDIUM",
                [
                    r"\bpublishing\s+per-team\s+deployment\s+frequency\s+leaderboards\b",
                    r"\bleaderboards\s+comparing\s+team\s+DORA\s+metrics\b",
                ],
                [
                    "publishing per-team deployment frequency leaderboards",
                    "team deployment leaderboards",
                ],
            ),
            (
                "ap-error-budget-ignored",
                "Error Budget Policy Enforcement",
                "Defining an SLO and error budget but never acting when the budget is exhausted.",
                "Treats reliability commitments as toothless suggestions, eroding system stability and user trust.",
                [
                    "Automated Feature Deployment Freezes",
                    "Reliability Sprint Dedication",
                    "Strict Error Budget Policy Execution",
                ],
                "reliability",
                "CRITICAL",
                [
                    r"\bdefining\s+an\s+SLO\s+and\s+error\s+budget\s+but\s+never\s+acting\s+when\s+the\s+budget\s+is\s+exhausted\b",
                    r"\bignor(?:ing|e)\s+exhausted\s+error\s+budgets\b",
                ],
                [
                    "defining an SLO and error budget but never acting when the budget is exhausted",
                    "ignoring exhausted error budgets",
                    "ignore exhausted error budgets",
                ],
            ),
            (
                "ap-property-trivial",
                "Property-Based Testing",
                "Writing trivial properties that restate the implementation.",
                "Tests confirm identical code logic without exploring boundary invariants or state mutations.",
                [
                    "Metamorphic Properties",
                    "Model-Based Invariant Oracles",
                    "Roundtrip Preservation Properties",
                ],
                "testing",
                "MEDIUM",
                [
                    r"\bwriting\s+trivial\s+properties\s+that\s+restate\s+the\s+implementation\b",
                    r"\btrivial\s+property-based\s+tests\s+mimicking\s+source\b",
                ],
                [
                    "writing trivial properties that restate the implementation",
                    "trivial property based tests",
                ],
            ),
            (
                "ap-semantic-conventions-bespoke",
                "Semantic Conventions",
                "Inventing bespoke span names and metric names per team.",
                "Fragmented enterprise dashboards prevent end-to-end trace correlation and cross-service alerting.",
                [
                    "OpenTelemetry Semantic Conventions",
                    "Centralized Schema Registries",
                    "Linted Telemetry Attribute Dictionaries",
                ],
                "observability",
                "MEDIUM",
                [
                    r"\binventing\s+bespoke\s+span\s+names\s+and\s+metric\s+names\s+per\s+team\b",
                    r"\bunaligned\s+custom\s+telemetry\s+attributes\s+across\s+teams\b",
                ],
                [
                    "inventing bespoke span names and metric names per team",
                    "custom telemetry attributes per team",
                ],
            ),
            (
                "ap-audit-screenshot-evidence",
                "Compliance, Governance & Audit",
                "Collecting evidence by screenshot shortly before the audit window closes.",
                "Screenshots cannot prove continuous operational effectiveness across the observation window; leads to audit findings and remediation mandates.",
                [
                    "Continuous Evidence Collection",
                    "Automated Policy-as-Code Telemetry",
                    "Cryptographically Signed Audit Trails",
                ],
                "governance",
                "CRITICAL",
                [
                    r"\bcollecting\s+evidence\s+by\s+screenshot\s+shortly\s+before\s+the\s+audit\s+window\s+closes\b",
                    r"\bmanual\s+screenshot\s+evidence\s+for\s+compliance\s+audits\b",
                ],
                [
                    "collecting evidence by screenshot shortly before the audit window closes",
                    "screenshot evidence for compliance",
                ],
            ),
        ]

        for item in raw_antipatterns:
            (
                rule_id,
                practice,
                antipattern,
                consequence,
                instead,
                domain,
                severity,
                patterns,
                keywords,
            ) = item
            self.register_rule(
                AntipatternRule(
                    id=rule_id,
                    practice=practice,
                    antipattern=antipattern,
                    consequence=consequence,
                    instead=instead,
                    domain_category=domain,
                    severity=severity,
                    regex_patterns=patterns,
                    keywords=keywords,
                )
            )

    def scan_document(
        self,
        text: str,
        document_name: str = "document.md",
        severity_filter: str | None = None,
    ) -> dict[str, Any]:
        """Scan policy or engineering text line-by-line and identify seeded antipatterns."""
        findings: list[AntipatternFinding] = []
        detected_rule_ids: set[str] = set()

        if not text or not text.strip():
            return {
                "document_name": document_name,
                "findings": [],
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "overall_score": 100.0,
                "affected_domains": [],
            }

        lines = text.splitlines()

        # 1. Regex pattern scanning per line and paragraph
        for line_idx, line in enumerate(lines, start=1):
            if not line.strip():
                continue

            for rx, rule_id in self._compiled_matchers:
                if rule_id in detected_rule_ids:
                    continue

                if rx.search(line):
                    rule = self._rules[rule_id]
                    if severity_filter and rule.severity.upper() != severity_filter.upper():
                        continue

                    findings.append(
                        AntipatternFinding(
                            rule_id=rule.id,
                            practice=rule.practice,
                            antipattern=rule.antipattern,
                            consequence=rule.consequence,
                            instead=rule.instead,
                            severity=rule.severity,
                            domain_category=rule.domain_category,
                            matched_snippet=line.strip()[:200],
                            line_number=line_idx,
                            confidence=0.98,
                        )
                    )
                    detected_rule_ids.add(rule.id)

        # 2. Multi-line phrase / keyword scanning across full text for any missed matches
        text_lower = text.lower()
        for rule in self._rules.values():
            if rule.id in detected_rule_ids:
                continue
            if severity_filter and rule.severity.upper() != severity_filter.upper():
                continue

            for kw in rule.keywords:
                if kw.lower() in text_lower:
                    # Find snippet around keyword
                    pos = text_lower.find(kw.lower())
                    start = max(0, pos - 40)
                    end = min(len(text), pos + len(kw) + 80)
                    snippet = text[start:end].replace("\n", " ").strip()

                    findings.append(
                        AntipatternFinding(
                            rule_id=rule.id,
                            practice=rule.practice,
                            antipattern=rule.antipattern,
                            consequence=rule.consequence,
                            instead=rule.instead,
                            severity=rule.severity,
                            domain_category=rule.domain_category,
                            matched_snippet=snippet,
                            line_number=None,
                            confidence=0.92,
                        )
                    )
                    detected_rule_ids.add(rule.id)
                    break

        # Calculate counts & organizational risk score
        crit_cnt = sum(1 for f in findings if f.severity == "CRITICAL")
        high_cnt = sum(1 for f in findings if f.severity == "HIGH")
        med_cnt = sum(1 for f in findings if f.severity == "MEDIUM")

        # Penalty score model: 100 base, -15 per critical, -8 per high, -3 per medium
        penalty = (crit_cnt * 15.0) + (high_cnt * 8.0) + (med_cnt * 3.0)
        overall_score = max(0.0, round(100.0 - penalty, 1))

        affected_domains = sorted(list({f.domain_category for f in findings}))

        # Priority sort by severity
        sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        findings.sort(key=lambda f: sev_rank.get(f.severity, 3))

        return {
            "document_name": document_name,
            "findings": [f.to_dict() for f in findings],
            "total_findings": len(findings),
            "critical_count": crit_cnt,
            "high_count": high_cnt,
            "medium_count": med_cnt,
            "overall_score": overall_score,
            "affected_domains": affected_domains,
        }

    def evaluate_synthetic_benchmark(self) -> dict[str, Any]:
        """Evaluate detection accuracy against a synthetic enterprise manual containing 12 seeded antipatterns."""
        synthetic_manual = """
# Enterprise Engineering & Compliance Manual (Draft 2024)

## Section 1: Quality Assurance & Testing Standards
All service modules must maintain line coverage as a quality target across pull requests, requiring 90% line coverage for merge gates.
To prevent flaky test build failures from blocking deployments, the CI pipeline implements adding automatic retries to a failing test suite.
For unit test execution speed, developers are encouraged to spin up docker containers for individual unit tests.

## Section 2: Production Reliability & Chaos Experiments
The SRE team conducts chaos experiments in production breaking things in production without a steady-state hypothesis to test recovery.
Service level objectives are defined per service; however, teams may ignore exhausted error budgets to ship customer features without blockage.

## Section 3: AI & Machine Learning Governance
For statutory document summarization, our LLM evaluation adopts judge scores as ground truth without validating the model outputs.
Security validation focuses exclusively on testing only direct user-supplied injections in the user prompt box.
Model compliance verification conducts one-time model validation prior to initial production deployment.

## Section 4: Security & Compliance Auditing
The enterprise relies on running an annual penetration test as the primary evidence that controls work across SOC 2 windows.
Threat modeling applies the six categories to 'the system' as a whole without decomposing individual component data flows.
Prior to annual statutory audits, compliance officers ensure collecting evidence by screenshot shortly before the audit window closes.
Accessibility compliance reports an automated scan pass as evidence of accessibility compliance for web applications.

## Section 5: Compliant Modern Engineering Standards (Clean Baseline)
Services publish consumer contracts verified bi-directionally on every provider build.
Database schema alterations follow expand-and-contract patterns with phased column migrations.
Authentication tokens use cryptographically signed asymmetric JWT keys rotated every 90 days.
"""

        expected_seeded_rules = {
            "ap-line-coverage",
            "ap-blind-test-retries",
            "ap-testcontainers-per-unit",
            "ap-chaos-no-hypothesis",
            "ap-error-budget-ignored",
            "ap-judge-unvalidated",
            "ap-prompt-injection-direct-only",
            "ap-sr117-onetime-signoff",
            "ap-annual-pentest-evidence",
            "ap-stride-system-whole",
            "ap-audit-screenshot-evidence",
            "ap-accessibility-scanner-only",
        }

        scan_result = self.scan_document(synthetic_manual, document_name="synthetic_manual.md")
        detected_rule_ids = {f["rule_id"] for f in scan_result["findings"]}

        true_positives = len(detected_rule_ids.intersection(expected_seeded_rules))
        false_positives = len(detected_rule_ids - expected_seeded_rules)
        false_negatives = len(expected_seeded_rules - detected_rule_ids)

        recall = true_positives / len(expected_seeded_rules) if expected_seeded_rules else 0.0
        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives)
            else 0.0
        )

        return {
            "total_seeded_antipatterns": len(expected_seeded_rules),
            "detected_antipatterns": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "overall_score": scan_result["overall_score"],
            "benchmark_passed": recall >= 0.90 and precision >= 0.90,
        }


# Singleton accessor
_DEFAULT_ANTIPATTERN_SCANNER: AntipatternScanner | None = None


def get_default_antipattern_scanner() -> AntipatternScanner:
    """Retrieve or initialize singleton AntipatternScanner."""
    global _DEFAULT_ANTIPATTERN_SCANNER
    if _DEFAULT_ANTIPATTERN_SCANNER is None:
        _DEFAULT_ANTIPATTERN_SCANNER = AntipatternScanner()
    return _DEFAULT_ANTIPATTERN_SCANNER
