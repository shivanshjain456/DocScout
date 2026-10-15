"""Sub-sentence evidence highlighting and span pinpointing (FEAT-078).

In statutory regulatory compliance research, retrieved chunks span ~1,000 characters
comprising multiple procedural clauses and administrative preambles. Showing an entire
block of text forces compliance officers to manually scan for the operative rule.

This module segments retrieved passages into statutory sentence and subclause units,
computes semantic and lexical alignment scores against the user's query intent, and
pinpoints the exact 1-2 operative sentences with character-exact offsets [start, end].
In the console UI, these pinpointed spans are rendered with amber highlights.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

from app.api.metrics import SPANS_HIGHLIGHTED_TOTAL
from app.retrieval.confidence import COMMON_STOPWORDS, extract_terms

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class HighlightSpan(BaseModel):
    """Sub-sentence character span pinpointing key statutory evidence (FEAT-078)."""

    start: int = Field(..., ge=0, description="Start character offset in passage text")
    end: int = Field(..., ge=0, description="End character offset in passage text")
    text: str = Field(..., description="Exact substring corresponding to text[start:end]")
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score of sentence span")

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "score": round(self.score, 4),
        }


#: Default maximum number of sentence spans to highlight per passage
DEFAULT_MAX_HIGHLIGHT_SPANS: int = 2

#: Minimum calibrated relevance score for a sentence to qualify as a highlight
DEFAULT_MIN_SENTENCE_SCORE: float = 0.60

#: Regex for statutory abbreviations that should NOT trigger a sentence split
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "rs.",
        "inr.",
        "no.",
        "nos.",
        "sec.",
        "para.",
        "cl.",
        "art.",
        "e.g.",
        "i.e.",
        "viz.",
        "vs.",
        "v.",
        "dept.",
        "fig.",
        "approx.",
        "govt.",
        "ltd.",
        "pvt.",
        "co.",
        "dr.",
        "mr.",
        "mrs.",
        "ms.",
        "prof.",
        "rbi.",
        "sebi.",
        "cir.",
    }
)

#: Regex to identify numeric, statutory currency, and percentage tokens
NUMERIC_OR_STATUTORY_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?(?:%|th|rd|st|nd)?|₹\s*\d+(?:,\d+)*(?:\.\d+)?|rs\.?\s*\d+(?:,\d+)*(?:\.\d+)?)\b",
    re.IGNORECASE,
)

#: Pre-compiled regex for sentence boundary detection in statutory text
SENTENCE_BOUNDARY_RE = re.compile(
    r'(?:(?<=[.?!;])\s+(?=[A-Z0-9"\'\(\[\u0900-\u097F]))|(?:\n\s*\n+)'
)


@dataclass(frozen=True)
class HighlightConfig:
    """Configuration for sub-sentence evidence highlighting (FEAT-078)."""

    max_highlight_spans: int = DEFAULT_MAX_HIGHLIGHT_SPANS
    min_sentence_score: float = DEFAULT_MIN_SENTENCE_SCORE

    def __post_init__(self) -> None:
        if self.max_highlight_spans < 1:
            raise ValueError(f"max_highlight_spans must be >= 1, got {self.max_highlight_spans}")
        if not (0.0 <= self.min_sentence_score <= 1.0):
            raise ValueError(
                f"min_sentence_score must be in [0.0, 1.0], got {self.min_sentence_score}"
            )


def split_sentences_with_spans(text: str) -> list[tuple[int, int, str]]:
    """Split text into sentences while tracking exact character offsets [start, end].

    Guarantees:
    - 0 <= start < end <= len(text)
    - text[start:end] == span_text
    - Strips leading and trailing whitespace without offset drift
    - Preserves abbreviations (e.g. 'Rs. 15 crore', 'Sec. 46') without false boundary splits
    """
    if not text or not text.strip():
        return []

    raw_boundaries: list[tuple[int, int]] = []
    prev_pos = 0

    for match in SENTENCE_BOUNDARY_RE.finditer(text):
        split_pos = match.start()
        preceding = text[prev_pos:split_pos]
        tokens = preceding.rstrip().split()
        last_tok = tokens[-1].lower() if tokens else ""

        # Guard against known statutory abbreviations
        if last_tok in ABBREVIATIONS:
            continue
        # Guard against single-letter initial abbreviations (e.g., 'A. Smith')
        if len(last_tok) == 2 and last_tok.endswith(".") and last_tok[0].isalpha():
            continue

        raw_boundaries.append((prev_pos, split_pos + 1))
        prev_pos = match.end()

    if prev_pos < len(text):
        raw_boundaries.append((prev_pos, len(text)))

    sentences: list[tuple[int, int, str]] = []
    for s_start, s_end in raw_boundaries:
        raw_segment = text[s_start:s_end]
        l_trim = len(raw_segment) - len(raw_segment.lstrip())
        r_trim = len(raw_segment) - len(raw_segment.rstrip())
        actual_start = s_start + l_trim
        actual_end = s_end - r_trim

        if actual_start < actual_end:
            trimmed = text[actual_start:actual_end]
            sentences.append((actual_start, actual_end, trimmed))

    return sentences


def compute_span_iou(span_a: tuple[int, int], span_b: tuple[int, int]) -> float:
    """Compute Intersection-over-Union (IoU) overlap between two character spans."""
    a_start, a_end = span_a
    b_start, b_end = span_b

    inter_start = max(a_start, b_start)
    inter_end = min(a_end, b_end)
    intersection = max(0, inter_end - inter_start)

    union = (a_end - a_start) + (b_end - b_start) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


@dataclass(frozen=True)
class QueryFeatures:
    """Pre-computed parsed features of a query to optimize multi-passage scoring."""

    query: str
    query_terms: frozenset[str]
    query_numerics: frozenset[str]
    bigrams: tuple[str, ...]
    has_rate_intent: bool
    has_amount_intent: bool
    has_deadline_intent: bool
    has_layer_intent: bool

    @classmethod
    def from_query(cls, query: str) -> QueryFeatures:
        q_lower = query.lower()
        q_terms = frozenset(extract_terms(query))
        q_numerics = frozenset(NUMERIC_OR_STATUTORY_RE.findall(q_lower))
        q_words = [w for w in q_lower.split() if w not in COMMON_STOPWORDS and len(w) > 1]
        bigrams = tuple(f"{q_words[i]} {q_words[i + 1]}" for i in range(len(q_words) - 1))
        return cls(
            query=query,
            query_terms=q_terms,
            query_numerics=q_numerics,
            bigrams=bigrams,
            has_rate_intent=any(
                k in q_lower for k in ("rate", "interest", "percent", "percentage", "crar")
            ),
            has_amount_intent=any(
                k in q_lower for k in ("amount", "loan", "worth", "capital", "finance")
            ),
            has_deadline_intent=any(
                k in q_lower for k in ("deadline", "time", "hours", "days", "report")
            ),
            has_layer_intent=any(k in q_lower for k in ("layers", "four", "tier", "levels")),
        )


@functools.lru_cache(maxsize=256)
def get_query_features(query: str) -> QueryFeatures:
    """Cached query features provider to guarantee sub-millisecond multi-passage evaluation."""
    return QueryFeatures.from_query(query)


class SpanPinpointer:
    """Scores sentence spans against a query to pinpoint operative regulatory evidence."""

    def __init__(self, config: HighlightConfig | None = None) -> None:
        self.config = config if config is not None else HighlightConfig()

    def score_sentence(
        self,
        query: str,
        sentence_text: str,
        query_terms: set[str] | frozenset[str] | None = None,
        query_numerics: set[str] | frozenset[str] | None = None,
        features: QueryFeatures | None = None,
    ) -> float:
        """Calculate calibrated relevance score [0.0, 1.0] for a sentence span."""
        if not sentence_text or not sentence_text.strip():
            return 0.0

        sent_terms = set(extract_terms(sentence_text))
        if not sent_terms:
            return 0.0

        feat = features if features is not None else get_query_features(query)
        if not feat.query_terms:
            return 0.0

        # 1. Term coverage ratio
        matched_terms = feat.query_terms & sent_terms
        coverage = len(matched_terms) / len(feat.query_terms)

        # 2. Phrase and n-gram overlap bonus
        s_lower = sentence_text.lower()
        phrase_match = any(bg in s_lower for bg in feat.bigrams)

        # 3. WH-intent and statutory entity matching
        entity_bonus = 0.0
        if feat.has_rate_intent and any(
            k in s_lower for k in ("%", "percent", "rate of interest", "crar")
        ):
            entity_bonus += 0.20
        if feat.has_amount_intent and any(
            k in s_lower for k in ("₹", "rs", "crore", "lakh", "finance up to", "net worth")
        ):
            entity_bonus += 0.20
        if feat.has_deadline_intent and any(k in s_lower for k in ("within", "hours", "days")):
            entity_bonus += 0.20
        if feat.has_layer_intent and any(k in s_lower for k in ("layers", "four", "base layer")):
            entity_bonus += 0.20

        raw_score = (
            0.40 * coverage
            + (0.25 if phrase_match else 0.0)
            + min(0.35, entity_bonus)
            + 0.15 * min(1.0, len(matched_terms) / 2.0)
        )

        return min(1.0, max(0.0, raw_score))

    def pinpoint(
        self,
        query: str,
        text: str,
        source: str = "general",
        features: QueryFeatures | None = None,
    ) -> list[HighlightSpan]:
        """Extract and rank the top operative statutory sentence spans in text.

        Guarantees:
        - Latency <= 2.0 ms for 5 passages on CPU.
        - Offsets index directly into text: text[start:end] == span.text.
        - Graceful fail-safe fallback to [] on any internal exception.
        """
        if not text or not text.strip() or not query or not query.strip():
            return []

        try:
            sentences = split_sentences_with_spans(text)
            if not sentences:
                return []

            feat = features if features is not None else get_query_features(query)

            scored_spans: list[tuple[float, int, int, str]] = []
            for start, end, sent_text in sentences:
                score = self.score_sentence(
                    query,
                    sent_text,
                    features=feat,
                )
                if score >= self.config.min_sentence_score:
                    scored_spans.append((score, start, end, sent_text))

            if not scored_spans:
                return []

            # Rank by score descending, then by earlier start position
            scored_spans.sort(key=lambda s: (-s[0], s[1]))
            top_spans = scored_spans[: self.config.max_highlight_spans]

            # Present final highlights in sequential text order for intuitive UI rendering
            top_spans.sort(key=lambda s: s[1])

            highlights: list[HighlightSpan] = []
            for score, start, end, sent_text in top_spans:
                highlights.append(
                    HighlightSpan(
                        start=start,
                        end=end,
                        text=sent_text,
                        score=round(score, 4),
                    )
                )
                try:
                    SPANS_HIGHLIGHTED_TOTAL.labels(source=source).inc()
                except Exception:
                    logger.debug("spans_highlighted_metric_failed", exc_info=True)

            return highlights
        except Exception as exc:
            logger.warning("span_pinpoint_failed_fallback_unhighlighted", error=str(exc))
            return []


def pinpoint_highlights(
    query: str,
    text: str,
    config: HighlightConfig | None = None,
    source: str = "general",
    features: QueryFeatures | None = None,
) -> list[HighlightSpan]:
    """Functional interface for sub-sentence evidence highlighting (FEAT-078)."""
    pinpointer = SpanPinpointer(config)
    return pinpointer.pinpoint(query, text, source=source, features=features)


def decorate_retrieved_highlights(
    query: str,
    retrieved_list: list[Any],
    config: HighlightConfig | None = None,
) -> list[Any]:
    """Decorate a list of Retrieved objects with pinpointed sub-sentence highlights."""
    if not retrieved_list:
        return retrieved_list

    pinpointer = SpanPinpointer(config)
    features = QueryFeatures.from_query(query)
    decorated: list[Any] = []

    for item in retrieved_list:
        text = getattr(item, "text", "")
        source = getattr(item, "source", "general")
        spans = pinpointer.pinpoint(query, text, source=source, features=features)
        if hasattr(item, "highlights"):
            if dataclasses.is_dataclass(item):
                decorated.append(dataclasses.replace(item, highlights=spans))  # type: ignore[type-var]
            else:
                item.highlights = spans
                decorated.append(item)
        else:
            decorated.append(item)

    return decorated
