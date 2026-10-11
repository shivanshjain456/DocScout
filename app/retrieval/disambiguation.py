"""Context-Aware Token Disambiguation Engine (FEAT-011).

Detects and disambiguates polysemous tokens (e.g., "coverage", "canary", "shift",
"DORA", "SIL", "MTTR", "RE", "PA") using formal disambiguation rules from
term-taxonomy.json to prevent cross-domain retrieval bleed.

Guarantees:
1. Sub-millisecond execution latency (p95 <= 0.8 ms).
2. Memory allocation <= 4 MB.
3. 100% correct resolution of canonical polysemous test cases.
4. Zero false-positive modifications on queries lacking ambiguous terms.
5. If confidence < 0.70, passes query through unmodified without raising.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import structlog
from pydantic import BaseModel

from app.api.metrics import DISAMBIGUATION_LATENCY, TOKENS_DISAMBIGUATED_TOTAL

logger = structlog.get_logger(__name__)


class DisambiguationConfig(BaseModel):
    """Configuration schema for token disambiguation engine."""

    enabled: bool = True
    min_confidence: float = 0.70
    context_window_tokens: int = 5


@dataclass(frozen=True)
class DisambiguationResult:
    """Outcome of disambiguating an ambiguous token in a query."""

    token: str
    resolved_sense: str
    canonical_term: str
    confidence: float
    modified_query: str
    domain: str


@dataclass(frozen=True)
class MeaningSense:
    """A specific semantic sense of an ambiguous token."""

    sense: str
    domain: str
    canonical_term: str
    replacement_term: str
    context_clues: frozenset[str]
    negative_clues: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DisambiguationRule:
    """A disambiguation rule for a specific polysemous token."""

    token: str
    pattern: re.Pattern[str]
    senses: tuple[MeaningSense, ...]
    guidance: str = ""


# Default canonical disambiguation rules based on term-taxonomy.json
CANONICAL_RULES: tuple[DisambiguationRule, ...] = (
    DisambiguationRule(
        token="DORA",
        pattern=re.compile(r"\b(?:dora)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="DORA delivery metrics",
                domain="ci-cd-developer-productivity",
                canonical_term="DORA Metrics (five keys)",
                replacement_term="DORA delivery metrics",
                context_clues=frozenset(
                    {
                        "metric",
                        "metrics",
                        "delivery",
                        "deployment",
                        "lead",
                        "time",
                        "change",
                        "failure",
                        "rate",
                        "devops",
                        "team",
                        "keys",
                        "four",
                        "five",
                        "productivity",
                        "velocity",
                        "frequency",
                    }
                ),
                negative_clues=frozenset({"act", "eu", "regulation", "financial", "ict"}),
            ),
            MeaningSense(
                sense="EU DORA regulation",
                domain="compliance-governance-audit",
                canonical_term="EU DORA (Digital Operational Resilience Act)",
                replacement_term="EU DORA regulation",
                context_clues=frozenset(
                    {
                        "regulation",
                        "act",
                        "compliance",
                        "ict",
                        "resilience",
                        "incident",
                        "reporting",
                        "third-party",
                        "oversight",
                        "financial",
                        "eu",
                        "audit",
                        "regulatory",
                        "governance",
                        "operational",
                    }
                ),
                negative_clues=frozenset({"lead", "metrics", "deployment"}),
            ),
        ),
        guidance="Distinguish DORA DevOps delivery metrics from EU DORA financial resilience regulation.",
    ),
    DisambiguationRule(
        token="coverage",
        pattern=re.compile(r"\b(?:coverage)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Structural coverage",
                domain="coverage-adequacy-code-health",
                canonical_term="Branch / Decision Coverage",
                replacement_term="structural code coverage",
                context_clues=frozenset(
                    {
                        "branch",
                        "code",
                        "statement",
                        "line",
                        "decision",
                        "mcdc",
                        "mc/dc",
                        "source",
                        "unit",
                        "test",
                        "suite",
                        "istanbul",
                        "cobertura",
                        "jacoco",
                        "lines",
                    }
                ),
            ),
            MeaningSense(
                sense="Functional coverage",
                domain="embedded-safety-critical",
                canonical_term="Functional Coverage / Coverage-Driven Verification",
                replacement_term="functional verification coverage",
                context_clues=frozenset(
                    {
                        "functional",
                        "model",
                        "verification",
                        "covergroup",
                        "coverpoint",
                        "cross",
                        "intent",
                        "hardware",
                        "systemverilog",
                        "uvm",
                        "simulation",
                        "chip",
                    }
                ),
            ),
        ),
        guidance="Distinguish code line/branch structural coverage from hardware functional coverage models.",
    ),
    DisambiguationRule(
        token="canary",
        pattern=re.compile(r"\b(?:canary)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Canary release",
                domain="delivery-deployment-progressive-rollout",
                canonical_term="Canary Release",
                replacement_term="canary release",
                context_clues=frozenset(
                    {
                        "release",
                        "deployment",
                        "traffic",
                        "percentage",
                        "rollout",
                        "version",
                        "cluster",
                        "ingress",
                        "pod",
                        "routing",
                        "weight",
                        "istio",
                        "argo",
                        "flagger",
                        "blue-green",
                    }
                ),
            ),
            MeaningSense(
                sense="Canary token",
                domain="ai-ml-llm-assurance",
                canonical_term="Canary Token Assertions",
                replacement_term="canary token leak detection",
                context_clues=frozenset(
                    {
                        "token",
                        "tokens",
                        "secret",
                        "leak",
                        "leakage",
                        "injection",
                        "assertion",
                        "planted",
                        "jailbreak",
                        "prompt",
                        "honeypot",
                        "exfiltration",
                        "data",
                        "llm",
                    }
                ),
            ),
        ),
        guidance="Distinguish deployment canaries (traffic routing) from canary tokens (secret leak detection).",
    ),
    DisambiguationRule(
        token="shift",
        pattern=re.compile(r"\b(?:shift)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Shift-left",
                domain="quality-engineering-operating-model",
                canonical_term="Shift-Left Testing",
                replacement_term="shift-left testing",
                context_clues=frozenset(
                    {
                        "left",
                        "early",
                        "developer",
                        "ide",
                        "commit",
                        "pre-commit",
                        "local",
                        "lint",
                        "design",
                        "requirements",
                        "ci",
                        "unit",
                    }
                ),
            ),
            MeaningSense(
                sense="Shift-right",
                domain="quality-engineering-operating-model",
                canonical_term="Shift-Right Testing",
                replacement_term="shift-right testing",
                context_clues=frozenset(
                    {
                        "right",
                        "production",
                        "telemetry",
                        "monitoring",
                        "observability",
                        "live",
                        "real",
                        "traffic",
                        "synthetic",
                        "chaos",
                        "prod",
                        "post-release",
                    }
                ),
            ),
        ),
        guidance="Distinguish shift-left (early testing) from shift-right (testing in production).",
    ),
    DisambiguationRule(
        token="SIL",
        pattern=re.compile(r"\b(?:sil)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Software-in-the-Loop",
                domain="embedded-safety-critical",
                canonical_term="Software-in-the-Loop (SIL)",
                replacement_term="Software-in-the-Loop simulation",
                context_clues=frozenset(
                    {
                        "software",
                        "simulation",
                        "simulated",
                        "loop",
                        "plant",
                        "host",
                        "hil",
                        "pil",
                        "virtual",
                        "automotive",
                        "model",
                    }
                ),
            ),
            MeaningSense(
                sense="Safety Integrity Level",
                domain="embedded-safety-critical",
                canonical_term="Safety Integrity Level (SIL 1-4)",
                replacement_term="Safety Integrity Level classification",
                context_clues=frozenset(
                    {
                        "safety",
                        "integrity",
                        "level",
                        "iec",
                        "61508",
                        "iso",
                        "26262",
                        "criticality",
                        "hazard",
                        "risk",
                        "1",
                        "2",
                        "3",
                        "4",
                        "sil1",
                        "sil2",
                        "sil3",
                        "sil4",
                    }
                ),
            ),
        ),
        guidance="Distinguish Software-in-the-Loop (SIL) simulation from Safety Integrity Level (SIL 1-4).",
    ),
    DisambiguationRule(
        token="MTTR",
        pattern=re.compile(r"\b(?:mttr)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Mean Time To Repair/Recover",
                domain="reliability-resilience-chaos",
                canonical_term="MTBF / MTTF / MTTR / MTTD / MTTA",
                replacement_term="Mean Time To Recover (service restoration)",
                context_clues=frozenset(
                    {
                        "repair",
                        "recovery",
                        "recover",
                        "restore",
                        "downtime",
                        "incident",
                        "service",
                        "outage",
                        "sre",
                        "reliability",
                        "failover",
                        "availability",
                    }
                ),
            ),
            MeaningSense(
                sense="Mean Time To Remediate (vulnerability)",
                domain="supply-chain-build-integrity",
                canonical_term="Mean Time to Remediate (MTTR-vuln)",
                replacement_term="Mean Time To Remediate (vulnerability fix)",
                context_clues=frozenset(
                    {
                        "vulnerability",
                        "vulnerabilities",
                        "remediate",
                        "remediation",
                        "cve",
                        "patch",
                        "patching",
                        "security",
                        "sla",
                        "auditor",
                        "exploit",
                        "scan",
                    }
                ),
            ),
        ),
        guidance="Distinguish MTTR recovery from MTTR vulnerability remediation.",
    ),
    DisambiguationRule(
        token="stress testing",
        pattern=re.compile(r"\b(?:stress\s+testing)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Tester's sense",
                domain="preserved-original",
                canonical_term="Stress Testing",
                replacement_term="capacity stress testing",
                context_clues=frozenset(
                    {
                        "capacity",
                        "load",
                        "breaking",
                        "point",
                        "performance",
                        "concurrency",
                        "rps",
                        "benchmark",
                        "soak",
                        "volume",
                        "traffic",
                    }
                ),
            ),
            MeaningSense(
                sense="Resilience sense",
                domain="reliability-resilience-chaos",
                canonical_term="Fault Injection",
                replacement_term="resilience fault injection stress testing",
                context_clues=frozenset(
                    {
                        "chaos",
                        "resilience",
                        "perturbation",
                        "failure",
                        "injection",
                        "fault",
                        "adversarial",
                        "kill",
                        "turbulent",
                        "latency",
                    }
                ),
            ),
        ),
        guidance="Distinguish load/capacity stress testing from resilience fault injection.",
    ),
    DisambiguationRule(
        token="integration testing",
        pattern=re.compile(r"\b(?:integration\s+testing)\b", re.IGNORECASE),
        senses=(
            MeaningSense(
                sense="Software sense",
                domain="preserved-original",
                canonical_term="Integration Testing",
                replacement_term="software service integration testing",
                context_clues=frozenset(
                    {
                        "software",
                        "service",
                        "services",
                        "api",
                        "endpoint",
                        "endpoints",
                        "microservices",
                        "database",
                        "http",
                        "contract",
                        "contracts",
                        "module",
                    }
                ),
            ),
            MeaningSense(
                sense="Hardware/embedded sense",
                domain="embedded-safety-critical",
                canonical_term="Hardware-in-the-Loop (HIL)",
                replacement_term="hardware-in-the-loop integration testing",
                context_clues=frozenset(
                    {
                        "hardware",
                        "embedded",
                        "hil",
                        "pil",
                        "target",
                        "actuator",
                        "sensor",
                        "ecu",
                        "board",
                        "plant",
                        "real-time",
                    }
                ),
            ),
        ),
        guidance="Distinguish software service integration from hardware-in-the-loop integration testing.",
    ),
    DisambiguationRule(
        token="RE",
        pattern=re.compile(r"\b(?:RE)\b"),  # Case-sensitive for statutory acronym
        senses=(
            MeaningSense(
                sense="Regulated Entity",
                domain="physical-and-regulated",
                canonical_term="Regulated Entity (RE)",
                replacement_term="Regulated Entity (RE)",
                context_clues=frozenset(
                    {
                        "rbi",
                        "bank",
                        "banks",
                        "nbfc",
                        "lending",
                        "circular",
                        "compliance",
                        "directions",
                        "master",
                        "audit",
                        "statutory",
                        "norm",
                        "norms",
                    }
                ),
            ),
            MeaningSense(
                sense="Reliability Engineering",
                domain="reliability-resilience-chaos",
                canonical_term="Site Reliability Engineering",
                replacement_term="Reliability Engineering",
                context_clues=frozenset(
                    {"sre", "reliability", "chaos", "pipeline", "slo", "sli", "infrastructure"}
                ),
            ),
        ),
        guidance="In RBI statutory context RE means Regulated Entity.",
    ),
    DisambiguationRule(
        token="PA",
        pattern=re.compile(r"\b(?:PA)\b"),  # Case-sensitive for statutory acronym
        senses=(
            MeaningSense(
                sense="Payment Aggregator",
                domain="physical-and-regulated",
                canonical_term="Payment Aggregator (PA)",
                replacement_term="Payment Aggregator (PA)",
                context_clues=frozenset(
                    {
                        "rbi",
                        "payment",
                        "payments",
                        "aggregator",
                        "escrow",
                        "merchant",
                        "merchants",
                        "settlement",
                        "nodal",
                        "pg",
                        "gateway",
                    }
                ),
            ),
        ),
        guidance="In RBI statutory context PA means Payment Aggregator.",
    ),
)


def _clean_substitute(prefix: str, replacement: str, suffix: str) -> str:
    """Substitute replacement into query between prefix and suffix, avoiding repeated words and hyphens."""
    clean_suffix = suffix
    if clean_suffix.startswith(("-left", "-right")) and (
        "left" in replacement.lower() or "right" in replacement.lower()
    ):
        clean_suffix = clean_suffix[clean_suffix.find(" ") :] if " " in clean_suffix else ""

    p_parts = prefix.rstrip().split()
    r_parts = replacement.split()
    s_parts = clean_suffix.lstrip().split()

    # Deduplicate overlapping boundary words
    while p_parts and r_parts and p_parts[-1].lower() == r_parts[0].lower():
        r_parts.pop(0)
    while s_parts and r_parts and s_parts[0].lower() == r_parts[-1].lower():
        r_parts.pop(-1)

    parts: list[str] = []
    if p_parts:
        parts.append(" ".join(p_parts))
    if r_parts:
        parts.append(" ".join(r_parts))
    if s_parts:
        parts.append(" ".join(s_parts))
    return " ".join(parts)


class TokenDisambiguator:
    """Pre-retrieval token disambiguation engine."""

    def __init__(self, config: DisambiguationConfig | None = None) -> None:
        self.config = config or DisambiguationConfig()
        self.rules: tuple[DisambiguationRule, ...] = CANONICAL_RULES

    def disambiguate_query(
        self, query: str, domain_hint: str | None = None
    ) -> tuple[str, list[DisambiguationResult]]:
        """Scan query for polysemous tokens, resolve their intended sense, and return modified query."""
        if not self.config.enabled or not query or len(query.strip()) < 3:
            return query, []

        started = time.perf_counter()
        modified_query = query
        results: list[DisambiguationResult] = []

        # Extract all words from query
        all_words = set(re.findall(r"[a-zA-Z0-9]+", query.lower()))

        for rule in self.rules:
            match = rule.pattern.search(modified_query)
            if not match:
                continue

            # Extract surrounding context tokens
            matched_span = match.span()
            matched_text = match.group(0)

            # Analyze context clues
            best_sense: MeaningSense | None = None
            highest_score = -1.0
            second_highest_score = -1.0

            # Gather all other words in the query as context
            matched_words = set(re.findall(r"[a-zA-Z0-9]+", matched_text.lower()))
            context_words = all_words - matched_words

            for sense in rule.senses:
                score = 0.0
                matched_clues = 0

                for word in context_words:
                    if word in sense.context_clues:
                        score += 2.0
                        matched_clues += 1
                    if word in sense.negative_clues:
                        score -= 3.0

                # Check clues directly present in matched_text (e.g., 'left' in 'shift-left')
                for word in matched_words:
                    if word in sense.context_clues:
                        score += 3.0
                        matched_clues += 1

                # Domain hint bonus
                if domain_hint and domain_hint.lower() in sense.domain.lower():
                    score += 3.0

                if score > highest_score:
                    second_highest_score = highest_score
                    highest_score = score
                    best_sense = sense
                elif score > second_highest_score:
                    second_highest_score = score

            if best_sense is not None and highest_score > 0.0:
                # Calculate confidence
                if second_highest_score < 0:
                    confidence = 0.95
                else:
                    confidence = round(
                        highest_score / (highest_score + second_highest_score + 0.1), 3
                    )

                if confidence >= self.config.min_confidence:
                    # Apply substitution
                    start, end = matched_span
                    prefix = modified_query[:start]
                    suffix = modified_query[end:]
                    modified_query = _clean_substitute(prefix, best_sense.replacement_term, suffix)

                    res = DisambiguationResult(
                        token=rule.token,
                        resolved_sense=best_sense.sense,
                        canonical_term=best_sense.canonical_term,
                        confidence=confidence,
                        modified_query=modified_query,
                        domain=best_sense.domain,
                    )
                    results.append(res)
                    try:
                        TOKENS_DISAMBIGUATED_TOTAL.labels(
                            token=rule.token, resolved_sense=best_sense.sense
                        ).inc()
                    except Exception:
                        logger.debug("tokens_disambiguated_metric_failed", exc_info=True)
                else:
                    logger.debug(
                        "disambiguation_low_confidence",
                        token=rule.token,
                        confidence=confidence,
                        query=query,
                    )

        elapsed_seconds = time.perf_counter() - started
        try:
            DISAMBIGUATION_LATENCY.observe(elapsed_seconds)
        except Exception:
            logger.debug("disambiguation_latency_metric_failed", exc_info=True)

        return modified_query, results


_GLOBAL_DISAMBIGUATOR: TokenDisambiguator | None = None


def get_token_disambiguator(config: DisambiguationConfig | None = None) -> TokenDisambiguator:
    """Return the global token disambiguator instance."""
    global _GLOBAL_DISAMBIGUATOR
    if _GLOBAL_DISAMBIGUATOR is None:
        _GLOBAL_DISAMBIGUATOR = TokenDisambiguator(config)
    return _GLOBAL_DISAMBIGUATOR
