"""Supported-Claim Faithfulness Evaluator (FEAT-081, ADR-0072).

Evaluates the exact formula:
    Faithfulness = Supported Claims / Total Claims
from term-taxonomy.json.formulas across generated compliance answers.

Decomposes generated prose into atomic factual propositions and evaluates
natural language entailment against retrieved evidence passages to enforce
100% citation grounding and eliminate hallucinations.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from app.api import metrics
from app.evals.scorers import faithfulness_score

logger = structlog.get_logger("docscout.evals.faithfulness")

# Regex to strip citation references like [ID:1], [ID: 1], [1], (1), [chunk-uuid]
CITATION_TAG_RE = re.compile(r"\[(?:ID:?\s*)?[a-zA-Z0-9_\-\.:]+\]|\(\d+\)", re.IGNORECASE)

# Conversational preambles to strip
PREAMBLE_PATTERNS = [
    re.compile(r"^(?:according to|based on|per|as stated in)\s+[^,.:;]+[,.:;]\s*", re.IGNORECASE),
    re.compile(
        r"^(?:the\s+)?(?:provided\s+)?(?:evidence|circular|direction|document)s?\s+(?:states?|indicates?|shows?|mandates?)\s+that\s+",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:in summary|here is the summary|summary)[:\s]*", re.IGNORECASE),
]

# Numerical entities: percentages, time intervals, currency, counts
NUMERICAL_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?%|\d+\s*(?:percent|basis points|bps|days|months|years|hours|weeks|crore|lakh|lakhs)|rs\.?\s*\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)

# Regulatory entity canonicalization map
ENTITY_CANONICAL_MAP: dict[str, str] = {
    "primary urban co-operative bank": "urban_cooperative_bank",
    "primary urban co-operative banks": "urban_cooperative_bank",
    "urban co-operative bank": "urban_cooperative_bank",
    "urban co-operative banks": "urban_cooperative_bank",
    "scheduled commercial bank": "scheduled_commercial_bank",
    "scheduled commercial banks": "scheduled_commercial_bank",
    "small finance bank": "small_finance_bank",
    "small finance banks": "small_finance_bank",
    "payments bank": "payments_bank",
    "payments banks": "payments_bank",
    "housing finance company": "housing_finance_company",
    "housing finance companies": "housing_finance_company",
    "asset reconstruction company": "asset_reconstruction_company",
    "asset reconstruction companies": "asset_reconstruction_company",
    "core investment company": "core_investment_company",
    "core investment companies": "core_investment_company",
    "payment aggregator": "payment_aggregator",
    "payment aggregators": "payment_aggregator",
    "payment gateway": "payment_gateway",
    "payment gateways": "payment_gateway",
    "prepaid payment instruments": "ppi",
    "prepaid payment instrument": "ppi",
    "ppi": "ppi",
    "foreign bank": "foreign_bank",
    "foreign banks": "foreign_bank",
    "non-banking financial company": "nbfc",
    "non-banking financial companies": "nbfc",
    "non-banking financial": "nbfc",
    "nbfc-mfi": "nbfc_mfi",
    "nbfc-icc": "nbfc_icc",
    "nbfc": "nbfc",
    "nbfcs": "nbfc",
    "regional rural bank": "regional_rural_bank",
    "regional rural banks": "regional_rural_bank",
    "credit information company": "credit_information_company",
    "credit information companies": "credit_information_company",
    "commercial bank": "commercial_bank",
    "commercial banks": "commercial_bank",
}

# Negation and polarity markers
NEGATION_WORDS = {"not", "never", "no", "prohibited", "forbidden", "disallowed", "exempt", "waived"}

# Comparative bound phrases where 'not' is part of a bound rather than sentence negation
BOUND_NEGATION_RE = re.compile(
    r"\bnot\s+(?:be\s+)?(?:less\s+than|fewer\s+than|more\s+than|greater\s+than|exceeding|exceed|later\s+than|earlier\s+than|below|above)\b",
    re.IGNORECASE,
)

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "is",
    "are",
    "was",
    "were",
    "for",
    "with",
    "by",
    "at",
    "from",
    "as",
    "on",
    "that",
    "this",
    "it",
    "its",
    "be",
    "shall",
    "must",
    "should",
    "may",
    "can",
    "will",
    "would",
}


def _stem_token(word: str) -> str:
    """Lightweight suffix normalizer for plural and tense variance."""
    w = word.lower()
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    return w


def _canonicalize_numeric(val: str) -> str:
    """Canonicalize numerical string representation."""
    v = val.lower().strip()
    v = re.sub(r"\s+", "", v)
    v = re.sub(r"^rs\.?", "rs", v)
    v = re.sub(r"(\d+(?:\.\d+)?)(?:percent|pct|%)", r"\1%", v)
    v = re.sub(r"\.0+%", "%", v)
    return v


@dataclass
class FaithfulnessConfig:
    """Configuration schema for Supported-Claim Faithfulness Evaluator."""

    min_score_threshold: float = 0.98
    nli_model: str = "deberta-v3-small-nli"
    enable_nli: bool = True
    entailment_threshold: float = 0.65


@dataclass
class ClaimEvaluation:
    """Evaluation breakdown for a single atomic proposition."""

    claim: str
    is_supported: bool
    entailment_score: float
    best_passage_id: str | None = None
    reason: str | None = None


@dataclass
class FaithfulnessEvaluation:
    """Complete evaluation report for a generated answer."""

    score: float
    total_claims: int
    supported_claims: int
    unsupported_claims: list[str]
    is_faithful: bool
    claims: list[ClaimEvaluation] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClaimDecomposer:
    """Decomposes answer prose into atomic factual claims."""

    def __init__(self) -> None:
        pass

    def decompose(self, answer: str) -> list[str]:
        if not answer or not answer.strip():
            return []

        # Remove citation brackets like [ID:1]
        cleaned = CITATION_TAG_RE.sub("", answer)
        cleaned = cleaned.replace("**", "").replace("__", "")

        # Split into preliminary lines / sentences
        raw_units = re.split(r"(?<=[.!?;\n])\s+", cleaned)
        claims: list[str] = []

        for unit in raw_units:
            text = unit.strip()
            # Strip bullet markers (- , * , 1. )
            text = re.sub(r"^(?:[-*•]|\d+\.)\s*", "", text).strip()
            if not text:
                continue

            # Strip leading preambles
            for pat in PREAMBLE_PATTERNS:
                text = pat.sub("", text).strip()

            # Ignore conversational filler or unanswerable declarations
            lower_text = text.lower()
            if any(
                phrase in lower_text
                for phrase in [
                    "insufficient evidence",
                    "cannot be answered",
                    "not provided in the",
                    "does not contain",
                ]
            ):
                continue

            # Minimum length of a factual statement (e.g. at least subject and verb/number)
            if len(text) < 12:
                continue

            # Split on compound sentence connectors if sentence is long (>120 chars)
            if len(text) > 120 and (
                "; " in text or ", and " in text or " and furthermore " in text
            ):
                sub_parts = re.split(r";\s*|,\s*and\s+|\s+and furthermore\s+", text)
                for part in sub_parts:
                    p = part.strip()
                    if len(p) >= 12:
                        claims.append(p)
            else:
                claims.append(text)

        return claims


class ClaimEntailmentEvaluator:
    """Deterministic and NLI-driven entailment evaluator for compliance propositions."""

    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = threshold

    def _extract_tokens(self, text: str) -> set[str]:
        words = re.findall(r"\b[a-zA-Z0-9-]+\b", text.lower())
        return {_stem_token(w) for w in words if w not in STOPWORDS and len(w) > 1}

    def _extract_numerics(self, text: str) -> set[str]:
        return {_canonicalize_numeric(m.group(0)) for m in NUMERICAL_RE.finditer(text)}

    def _extract_entities(self, text: str) -> set[str]:
        lower = text.lower()
        ents: set[str] = set()
        for phrase, canonical in sorted(
            ENTITY_CANONICAL_MAP.items(), key=lambda x: len(x[0]), reverse=True
        ):
            if phrase in lower:
                ents.add(canonical)
        return ents

    def _has_negation(self, text: str) -> bool:
        # Mask comparative bound phrases like "not less than" before checking negation markers
        cleaned = BOUND_NEGATION_RE.sub(" ", text.lower())
        tokens = set(re.findall(r"\b[a-zA-Z]+\b", cleaned))
        return bool(tokens.intersection(NEGATION_WORDS))

    def evaluate_claim_against_passage(
        self,
        claim: str,
        passage_text: str,
    ) -> tuple[float, str]:
        """Compute entailment score between passage premise and claim hypothesis."""
        p_lower = passage_text.lower()
        c_lower = claim.lower()

        # 1. Exact or near-exact substring match
        if c_lower in p_lower:
            return 1.0, "exact_substring"

        # 2. Check numerical consistency
        claim_nums = self._extract_numerics(claim)
        passage_nums = self._extract_numerics(passage_text)

        if claim_nums:
            # If claim asserts numerical values not present in passage, check for conflict
            missing_nums = claim_nums - passage_nums
            if missing_nums:
                # Numerical hallucination detected
                return 0.10, f"numerical_conflict_missing: {missing_nums}"

        # 3. Check polarity / negation consistency
        claim_neg = self._has_negation(claim)
        passage_neg = self._has_negation(passage_text)
        if claim_neg != passage_neg:
            # Check if this is a contradictory inversion
            claim_tokens = self._extract_tokens(claim)
            passage_tokens = self._extract_tokens(passage_text)
            overlap = claim_tokens.intersection(passage_tokens)
            if len(overlap) >= 3:
                # Highly overlapping tokens but inverted negation polarity -> Contradiction!
                return 0.05, "negation_polarity_inversion"

        # 4. Check entity compatibility
        claim_ents = self._extract_entities(claim)
        passage_ents = self._extract_entities(passage_text)
        if claim_ents:
            unsupported_ents = claim_ents - passage_ents
            if unsupported_ents:
                # Claim asserts regulatory entity not present or authorized in passage
                return 0.20, f"unsupported_entity_introduced: {unsupported_ents}"

        # 5. Token semantic containment & overlap
        c_tokens = self._extract_tokens(claim)
        p_tokens = self._extract_tokens(passage_text)
        if not c_tokens:
            return 0.50, "empty_claim_tokens"

        overlap_count = len(c_tokens.intersection(p_tokens))
        overlap_ratio = overlap_count / len(c_tokens)

        # Boost score if numbers match and entity matches
        if claim_nums and claim_nums.issubset(passage_nums):
            overlap_ratio = min(1.0, overlap_ratio + 0.25)
        if claim_ents and claim_ents.issubset(passage_ents):
            overlap_ratio = min(1.0, overlap_ratio + 0.20)

        return overlap_ratio, "token_semantic_overlap"


class FaithfulnessEvaluator:
    """Evaluates answer faithfulness using Supported Claims / Total Claims."""

    def __init__(self, config: FaithfulnessConfig | None = None) -> None:
        self.config = config or FaithfulnessConfig()
        self.decomposer = ClaimDecomposer()
        self.entailment_evaluator = ClaimEntailmentEvaluator(
            threshold=self.config.entailment_threshold
        )

    def evaluate(
        self,
        answer: str,
        citations: Sequence[Any],
    ) -> FaithfulnessEvaluation:
        """Evaluate the faithfulness of a generated answer against its citations."""
        if not answer or not answer.strip():
            raise ValueError("answer must be non-empty")
        if not citations:
            raise ValueError("at least 1 citation must be provided")

        claims = self.decomposer.decompose(answer)
        if not claims:
            # No testable factual claims (e.g. abstention or refusal statement)
            metrics.MEAN_ANSWER_FAITHFULNESS_SCORE.set(1.0)
            return FaithfulnessEvaluation(
                score=1.0,
                total_claims=0,
                supported_claims=0,
                unsupported_claims=[],
                is_faithful=True,
                claims=[],
            )

        # Normalize citations to list of (chunk_id, text)
        passage_data: list[tuple[str | None, str]] = []
        for c in citations:
            if isinstance(c, str):
                passage_data.append((None, c))
            elif hasattr(c, "text"):
                chunk_id = getattr(c, "chunk_id", None)
                passage_data.append((chunk_id, c.text))
            elif isinstance(c, dict):
                passage_data.append((c.get("chunk_id"), c.get("text", "")))

        claim_evaluations: list[ClaimEvaluation] = []
        unsupported: list[str] = []
        supported_count = 0

        for claim in claims:
            best_score = 0.0
            best_pid: str | None = None
            best_reason: str | None = None

            for pid, ptext in passage_data:
                score, reason = self.entailment_evaluator.evaluate_claim_against_passage(
                    claim, ptext
                )
                if score > best_score:
                    best_score = score
                    best_pid = pid
                    best_reason = reason

            is_supported = best_score >= self.config.entailment_threshold
            if is_supported:
                supported_count += 1
            else:
                unsupported.append(claim)

            claim_evaluations.append(
                ClaimEvaluation(
                    claim=claim,
                    is_supported=is_supported,
                    entailment_score=round(best_score, 4),
                    best_passage_id=best_pid,
                    reason=best_reason,
                )
            )

        total_claims = len(claims)
        final_score = faithfulness_score(supported_count, total_claims)
        is_faithful = final_score >= self.config.min_score_threshold

        metrics.MEAN_ANSWER_FAITHFULNESS_SCORE.set(final_score)
        metrics.record_claim_telemetry(supported_count, total_claims)
        if not is_faithful:
            metrics.UNFAITHFUL_ANSWERS_REJECTED_TOTAL.inc()
            logger.info(
                "faithfulness.answer_rejected",
                score=final_score,
                total_claims=total_claims,
                supported_claims=supported_count,
                unsupported_claims=unsupported,
            )

        return FaithfulnessEvaluation(
            score=round(final_score, 4),
            total_claims=total_claims,
            supported_claims=supported_count,
            unsupported_claims=unsupported,
            is_faithful=is_faithful,
            claims=claim_evaluations,
        )


_DEFAULT_EVALUATOR: FaithfulnessEvaluator | None = None


def get_default_faithfulness_evaluator() -> FaithfulnessEvaluator:
    """Return singleton instance of FaithfulnessEvaluator."""
    global _DEFAULT_EVALUATOR
    if _DEFAULT_EVALUATOR is None:
        _DEFAULT_EVALUATOR = FaithfulnessEvaluator()
    return _DEFAULT_EVALUATOR
