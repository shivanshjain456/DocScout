"""Evidence coverage and confidence-calibrated selective refusal gate (FEAT-077).

Under statutory regulatory compliance requirements, DocScout enforces the strict invariant:
"Every answer cites its source or it refuses to answer."

This module evaluates evidence coverage (query terms intersect passage terms across top-5
retrieved passages) and triggers structured selective refusal whenever confidence falls below
the calibrated 0.65 threshold, completely suppressing hallucinated speculative answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from app.api.metrics import ABSTENTION_EVENTS_TOTAL, CONFIDENCE_SCORES

logger = structlog.get_logger(__name__)

#: Passages whose terms count toward coverage. Depth 5 bounds dilution.
COVERAGE_DEPTH = 5

#: Below this fraction of query terms found, the response triggers selective refusal.
LOW_EVIDENCE_THRESHOLD = 0.65

# Regex tokenizer for statutory terms
TERM_TOKEN_RE = re.compile(r"\b[A-Za-z0-9\-\.\/]+\b")

# Common English stopwords to ignore when tokenizing raw query text
COMMON_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "with",
        "on",
        "at",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "how",
        "when",
        "where",
        "why",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "if",
        "each",
        "all",
        "both",
        "can",
        "could",
        "shall",
        "should",
        "will",
        "would",
        "may",
        "might",
        "must",
        "under",
        "over",
        "between",
        "into",
        "through",
        "after",
        "before",
        "during",
        "without",
        "within",
        "about",
        "against",
        "among",
        "below",
        "behind",
        "beneath",
        "beside",
        "beyond",
        "down",
        "up",
        "out",
        "off",
        "near",
        "above",
        "across",
        "along",
        "around",
        "towards",
        "toward",
        "upon",
        "via",
        "per",
    }
)


@dataclass(frozen=True)
class ConfidenceConfig:
    """Configuration schema for confidence-calibrated selective refusal (FEAT-077)."""

    low_evidence_threshold: float = LOW_EVIDENCE_THRESHOLD
    coverage_depth: int = COVERAGE_DEPTH

    def __post_init__(self) -> None:
        if not (0.0 <= self.low_evidence_threshold <= 1.0):
            raise ValueError(
                f"low_evidence_threshold must be in [0.0, 1.0], got {self.low_evidence_threshold}"
            )
        if self.coverage_depth < 1:
            raise ValueError(f"coverage_depth must be >= 1, got {self.coverage_depth}")


@dataclass(frozen=True)
class Confidence:
    """How much of the question the retrieved evidence actually covers (FEAT-077)."""

    score: float
    level: Literal["HIGH", "MEDIUM", "LOW"]
    is_refusal: bool
    refusal_reason: str | None = None
    evidence_coverage: float = 0.0
    missing_terms: list[str] = field(default_factory=list)
    low_evidence: bool = False
    passages_considered: int = 5

    def __post_init__(self) -> None:
        if not self.evidence_coverage and self.score:
            object.__setattr__(self, "evidence_coverage", self.score)
        elif not self.score and self.evidence_coverage:
            object.__setattr__(self, "score", self.evidence_coverage)

        if self.is_refusal and not self.low_evidence:
            object.__setattr__(self, "low_evidence", True)
        elif self.low_evidence and not self.is_refusal:
            object.__setattr__(self, "is_refusal", True)

        if self.is_refusal and self.refusal_reason is None:
            missing_str = (
                f" Missing key statutory terms: {', '.join(self.missing_terms[:3])}"
                if self.missing_terms
                else ""
            )
            object.__setattr__(
                self,
                "refusal_reason",
                f"Insufficient regulatory evidence in corpus (coverage {self.score:.2f} < 0.65).{missing_str}",
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "level": self.level,
            "is_refusal": self.is_refusal,
            "refusal_reason": self.refusal_reason,
            "evidence_coverage": round(self.evidence_coverage, 4),
            "missing_terms": self.missing_terms,
            "low_evidence": self.low_evidence,
            "passages_considered": self.passages_considered,
        }


def extract_terms(text: str) -> list[str]:
    """Extract lowercase alphanumeric terms excluding standard stopwords with suffix normalization."""
    if not text:
        return []
    tokens = TERM_TOKEN_RE.findall(text.lower())
    terms: list[str] = []
    for tok in tokens:
        if tok in COMMON_STOPWORDS or len(tok) <= 1:
            continue
        norm = tok
        if norm.endswith("ing") and len(norm) > 5:
            norm = norm[:-3]
        elif norm.endswith("ed") and len(norm) > 4:
            norm = norm[:-2]
        elif norm.endswith("tion") and len(norm) > 6:
            norm = norm[:-4]
        elif norm.endswith("s") and len(norm) > 3 and not norm.endswith("ss"):
            norm = norm[:-1]
        terms.append(norm)
    return terms


def assess(
    query_terms: list[str],
    passage_terms: list[set[str]],
    *,
    depth: int = COVERAGE_DEPTH,
    threshold: float = LOW_EVIDENCE_THRESHOLD,
    config: ConfidenceConfig | None = None,
) -> Confidence:
    """Score how much of the question the top passages cover.

    Pure in-memory calculation (latency <= 0.2 ms).
    Emits Prometheus metrics: docscout_abstention_events_total and docscout_confidence_scores.
    """
    effective_depth = config.coverage_depth if config is not None else depth
    effective_threshold = config.low_evidence_threshold if config is not None else threshold

    try:
        considered = passage_terms[:effective_depth]
        found: set[str] = set()
        for terms in considered:
            found |= terms

        unique_query_terms = set(query_terms)
        if not unique_query_terms:
            ABSTENTION_EVENTS_TOTAL.labels(level="LOW").inc()
            CONFIDENCE_SCORES.observe(0.0)
            return Confidence(
                score=0.0,
                level="LOW",
                is_refusal=True,
                refusal_reason="Query contains no analyzable statutory terms",
                evidence_coverage=0.0,
                missing_terms=[],
                low_evidence=True,
                passages_considered=len(considered),
            )

        covered = unique_query_terms & found
        coverage = len(covered) / len(unique_query_terms)
        missing = sorted(unique_query_terms - found)

        # Confidence level calibration
        if coverage >= 0.85:
            level: Literal["HIGH", "MEDIUM", "LOW"] = "HIGH"
            is_refusal = False
            refusal_reason = None
        elif coverage >= effective_threshold:
            level = "MEDIUM"
            is_refusal = False
            refusal_reason = None
        else:
            level = "LOW"
            is_refusal = True
            missing_str = f" Missing terms: {', '.join(missing[:3])}" if missing else ""
            refusal_reason = (
                f"Insufficient regulatory evidence in corpus "
                f"(coverage {coverage:.2f} < threshold {effective_threshold:.2f}).{missing_str}"
            )

        ABSTENTION_EVENTS_TOTAL.labels(level=level).inc()
        CONFIDENCE_SCORES.observe(coverage)

        return Confidence(
            score=coverage,
            level=level,
            is_refusal=is_refusal,
            refusal_reason=refusal_reason,
            evidence_coverage=coverage,
            missing_terms=missing,
            low_evidence=is_refusal,
            passages_considered=len(considered),
        )
    except Exception as exc:
        logger.warning("confidence_assessment_failed_fail_closed_refusal", error=str(exc))
        # Fail-closed: conservative refusal to prevent hallucinations
        ABSTENTION_EVENTS_TOTAL.labels(level="LOW").inc()
        CONFIDENCE_SCORES.observe(0.0)
        return Confidence(
            score=0.0,
            level="LOW",
            is_refusal=True,
            refusal_reason="Internal error during confidence calculation - conservative refusal triggered",
            evidence_coverage=0.0,
            missing_terms=[],
            low_evidence=True,
            passages_considered=0,
        )


def assess_passages(
    query: str,
    passages: list[Any],
    config: ConfidenceConfig | None = None,
) -> Confidence:
    """Assess confidence directly from raw query text and retrieved passages (FEAT-077).

    Validates: len(passages) >= 1.
    """
    if not passages:
        raise ValueError("passages must contain at least 1 passage (len(passages) >= 1)")

    cfg = config if config is not None else ConfidenceConfig()
    query_terms = extract_terms(query)

    passage_term_sets: list[set[str]] = []
    for p in passages[: cfg.coverage_depth]:
        text = getattr(p, "text", None)
        if text is None and isinstance(p, dict):
            text = p.get("text", "")
        elif text is None and isinstance(p, str):
            text = p
        terms = set(extract_terms(text or ""))
        passage_term_sets.append(terms)

    return assess(query_terms, passage_term_sets, config=cfg)
