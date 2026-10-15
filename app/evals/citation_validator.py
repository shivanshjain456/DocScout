"""Deterministic Citation Provenance Grounding Validator (FEAT-082, ADR-0073).

Validates that every factual proposition contains an explicit [ID:N] or chunk ID marker
mapping to a retrieved chunk ID that exists and explicitly covers the proposition.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import structlog

from app.api import metrics

logger = structlog.get_logger("docscout.evals.citation_validator")

# Regex pattern for citations: [ID:1], [ID: 1], [id:1], [1], (1), [chunk-uuid]
CITATION_MARKER_RE = re.compile(
    r"\[(?:ID:?\s*)?([a-zA-Z0-9_\-\.:]+)\]|\(([0-9]+)\)",
    re.IGNORECASE,
)

# Sentence splitter preserving punctuation
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])|(?<=\n)\s*")

WORD_TOKEN_RE = re.compile(r"\b[a-zA-Z0-9-]+\b")

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

ABSTENTION_MARKERS = [
    "insufficient evidence",
    "cannot be answered",
    "not provided in the",
    "does not contain sufficient",
    "no relevant passages",
]


@dataclass
class CitationValidatorConfig:
    """Configuration schema for Deterministic Citation Provenance Grounding Validator."""

    strict_mode: bool = True
    min_overlap_threshold: float = 0.35


@dataclass
class CitationValidationResult:
    """Evaluation result for citation grounding and provenance verification."""

    is_grounded: bool
    valid_citations_count: int
    invalid_citations: list[str]
    ungrounded_sentences: list[str]
    sanitized_answer: str = ""
    total_sentences: int = 0
    grounded_sentences_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CitationValidator:
    """Validates citation provenance, marker validity, and sentence-level evidence grounding."""

    def __init__(self, config: CitationValidatorConfig | None = None) -> None:
        self.config = config or CitationValidatorConfig()

    def _extract_tokens(self, text: str) -> set[str]:
        words = WORD_TOKEN_RE.findall(text.lower())
        return {w for w in words if w not in STOPWORDS and len(w) > 1}

    def _is_abstention_or_filler(self, sentence: str) -> bool:
        s_lower = sentence.lower().strip()
        if len(s_lower) < 15:
            return True
        return any(marker in s_lower for marker in ABSTENTION_MARKERS)

    def validate(
        self,
        answer: str,
        passages: Sequence[Any],
    ) -> CitationValidationResult:
        """Validate citation markers, database provenance, and lexical grounding."""
        if not answer or not answer.strip():
            return CitationValidationResult(
                is_grounded=True,
                valid_citations_count=0,
                invalid_citations=[],
                ungrounded_sentences=[],
                sanitized_answer="",
                total_sentences=0,
                grounded_sentences_count=0,
            )

        if not passages:
            # If answer is an explicit refusal/abstention, it is valid without citations
            if self._is_abstention_or_filler(answer):
                return CitationValidationResult(
                    is_grounded=True,
                    valid_citations_count=0,
                    invalid_citations=[],
                    ungrounded_sentences=[],
                    sanitized_answer=answer,
                    total_sentences=1,
                    grounded_sentences_count=1,
                )
            # Otherwise an answer served with zero passages is ungrounded
            return CitationValidationResult(
                is_grounded=False,
                valid_citations_count=0,
                invalid_citations=["NO_PASSAGES_PROVIDED"],
                ungrounded_sentences=[answer.strip()],
                sanitized_answer="",
                total_sentences=1,
                grounded_sentences_count=0,
            )

        # Build passage lookups by 1-based index and chunk_id
        passage_by_index: dict[int, str] = {}
        passage_by_id: dict[str, str] = {}

        for idx, p in enumerate(passages, start=1):
            text = (
                getattr(p, "text", "")
                if hasattr(p, "text")
                else (p.get("text", "") if isinstance(p, dict) else str(p))
            )
            chunk_id = (
                getattr(p, "chunk_id", None)
                if hasattr(p, "chunk_id")
                else (p.get("chunk_id") if isinstance(p, dict) else None)
            )

            passage_by_index[idx] = text
            if chunk_id:
                passage_by_id[str(chunk_id).lower()] = text

        raw_sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(answer) if s.strip()]
        total_sentences = len(raw_sentences)

        valid_citations_count = 0
        invalid_citations: list[str] = []
        ungrounded_sentences: list[str] = []
        grounded_sentences: list[str] = []

        for raw_sent in raw_sentences:
            # Check if sentence is an unanswerable / insufficient evidence declaration
            if self._is_abstention_or_filler(raw_sent):
                grounded_sentences.append(raw_sent)
                continue

            matches = list(CITATION_MARKER_RE.finditer(raw_sent))
            if not matches:
                # Proposition has no citation marker!
                ungrounded_sentences.append(raw_sent)
                continue

            sent_has_invalid = False
            cited_passage_texts: list[str] = []

            for m in matches:
                ref = m.group(1) or m.group(2)
                if not ref:
                    continue

                if ref.isdigit():
                    num = int(ref)
                    if num in passage_by_index:
                        valid_citations_count += 1
                        cited_passage_texts.append(passage_by_index[num])
                    else:
                        sent_has_invalid = True
                        invalid_citations.append(f"out_of_bounds:[ID:{num}]")
                else:
                    ref_lower = ref.lower()
                    if ref_lower in passage_by_id:
                        valid_citations_count += 1
                        cited_passage_texts.append(passage_by_id[ref_lower])
                    else:
                        sent_has_invalid = True
                        invalid_citations.append(f"unknown_chunk_id:[{ref}]")

            if sent_has_invalid:
                ungrounded_sentences.append(raw_sent)
                continue

            # Strip citation tags from sentence to evaluate proposition text
            clean_sent = CITATION_MARKER_RE.sub("", raw_sent).strip()
            sent_tokens = self._extract_tokens(clean_sent)

            if not sent_tokens:
                # Preamble or formula string
                grounded_sentences.append(raw_sent)
                continue

            # Check evidence overlap against cited passages
            combined_cited_text = " ".join(cited_passage_texts)
            passage_tokens = self._extract_tokens(combined_cited_text)

            overlap_count = len(sent_tokens.intersection(passage_tokens))
            overlap_ratio = overlap_count / len(sent_tokens)

            if overlap_ratio >= self.config.min_overlap_threshold:
                grounded_sentences.append(raw_sent)
            else:
                ungrounded_sentences.append(raw_sent)

        grounded_count = len(grounded_sentences)
        is_grounded = len(ungrounded_sentences) == 0 and len(invalid_citations) == 0

        # Sanitization logic
        sanitized_answer: str
        if self.config.strict_mode:
            if grounded_sentences:
                sanitized_answer = " ".join(grounded_sentences)
            else:
                sanitized_answer = ""
        else:
            sanitized_answer = answer

        # Observability metrics updates
        if valid_citations_count > 0:
            metrics.CITATIONS_VALIDATED_TOTAL.labels(status="valid").inc(valid_citations_count)
        if invalid_citations:
            metrics.CITATIONS_VALIDATED_TOTAL.labels(status="invalid").inc(len(invalid_citations))
        if ungrounded_sentences:
            metrics.CITATIONS_VALIDATED_TOTAL.labels(status="ungrounded").inc(
                len(ungrounded_sentences)
            )
        if sanitized_answer != answer:
            metrics.CITATIONS_VALIDATED_TOTAL.labels(status="sanitized").inc()

        return CitationValidationResult(
            is_grounded=is_grounded,
            valid_citations_count=valid_citations_count,
            invalid_citations=invalid_citations,
            ungrounded_sentences=ungrounded_sentences,
            sanitized_answer=sanitized_answer,
            total_sentences=total_sentences,
            grounded_sentences_count=grounded_count,
        )


_DEFAULT_VALIDATOR: CitationValidator | None = None


def get_default_citation_validator() -> CitationValidator:
    """Return singleton instance of CitationValidator."""
    global _DEFAULT_VALIDATOR
    if _DEFAULT_VALIDATOR is None:
        _DEFAULT_VALIDATOR = CitationValidator()
    return _DEFAULT_VALIDATOR
