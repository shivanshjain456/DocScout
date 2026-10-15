"""Unit and benchmark tests for FEAT-082: Deterministic Citation Provenance Grounding Validator.

Validates:
1. CitationValidatorConfig defaults and singleton accessor.
2. Grounded answers with valid [ID:N] and [chunk_id] markers.
3. Out-of-bounds citation indices (e.g. [ID:5] with 2 passages).
4. Unknown chunk ID citations not matching any retrieved passage.
5. Missing citations on factual propositions.
6. Non-overlapping passage text (citation mismatch).
7. Abstention and refusal statement handling.
8. Sanitization stripping ungrounded sentences in strict mode.
9. Sub-millisecond latency budget (<= 0.40ms).
10. Prometheus metrics registration and emission.
"""

from __future__ import annotations

import time

from app.api import metrics
from app.api.models import Passage
from app.evals.citation_validator import (
    CitationValidator,
    CitationValidatorConfig,
    get_default_citation_validator,
)


def _make_passage(rank: int, chunk_id: str, text: str) -> Passage:
    return Passage(
        rank=rank,
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source="RBI",
        canonical_url=None,
        score=0.95,
        arm_ranks={"dense": rank},
        char_start=0,
        char_end=len(text),
        text=text,
    )


def test_citation_validator_config_defaults() -> None:
    """Validate default configuration values for FEAT-082."""
    cfg = CitationValidatorConfig()
    assert cfg.strict_mode is True
    assert cfg.min_overlap_threshold == 0.35

    validator = get_default_citation_validator()
    assert isinstance(validator, CitationValidator)
    assert get_default_citation_validator() is validator


def test_citation_validation_fully_grounded() -> None:
    """Verify answer where every claim has valid [ID:N] citations covering the text."""
    validator = CitationValidator()

    p1 = _make_passage(
        1,
        "chunk-crar-15",
        "Every non-banking financial company shall maintain a minimum capital ratio of 15 percent.",
    )
    p2 = _make_passage(
        2,
        "chunk-tier-10",
        "Tier I capital shall not be less than 10 percent of aggregate risk weighted assets.",
    )

    answer = (
        "Non-banking financial companies must maintain a minimum capital ratio of 15 percent [ID:1]. "
        "Tier I capital shall not be less than 10 percent [ID:2]."
    )

    result = validator.validate(answer, [p1, p2])
    assert result.is_grounded is True
    assert result.valid_citations_count == 2
    assert len(result.invalid_citations) == 0
    assert len(result.ungrounded_sentences) == 0
    assert result.total_sentences == 2
    assert result.grounded_sentences_count == 2
    assert "15 percent" in result.sanitized_answer
    assert "Tier I capital" in result.sanitized_answer


def test_citation_validation_chunk_id_markers() -> None:
    """Verify citations using direct chunk IDs like [chunk-cyber-6h]."""
    validator = CitationValidator()

    p1 = _make_passage(
        1,
        "chunk-cyber-6h",
        "Payment Aggregators shall report all cyber security incidents to RBI within 6 hours of detection.",
    )

    answer = (
        "Payment Aggregators must report cyber incidents to RBI within 6 hours [chunk-cyber-6h]."
    )

    result = validator.validate(answer, [p1])
    assert result.is_grounded is True
    assert result.valid_citations_count == 1
    assert len(result.invalid_citations) == 0
    assert len(result.ungrounded_sentences) == 0


def test_citation_validation_out_of_bounds_citation() -> None:
    """Verify citation index exceeding the number of returned passages is flagged."""
    validator = CitationValidator()

    p1 = _make_passage(
        1, "chunk-1", "Scheduled commercial banks must classify assets as NPA after 90 days."
    )

    # Citing [ID:5] when only 1 passage exists
    answer = "Scheduled commercial banks must classify assets as NPA after 90 days [ID:5]."

    result = validator.validate(answer, [p1])
    assert result.is_grounded is False
    assert any("out_of_bounds:[ID:5]" in inv for inv in result.invalid_citations)
    assert len(result.ungrounded_sentences) == 1
    assert result.sanitized_answer == ""


def test_citation_validation_unknown_chunk_id() -> None:
    """Verify citation referencing a non-existent chunk ID is flagged as invalid."""
    validator = CitationValidator()

    p1 = _make_passage(
        1, "chunk-valid-1", "Housing Finance Companies must maintain Net Owned Fund of Rs 25 crore."
    )

    answer = "Housing Finance Companies must maintain Net Owned Fund of Rs 25 crore [chunk-nonexistent-999]."

    result = validator.validate(answer, [p1])
    assert result.is_grounded is False
    assert any(
        "unknown_chunk_id:[chunk-nonexistent-999]" in inv for inv in result.invalid_citations
    )
    assert len(result.ungrounded_sentences) == 1


def test_citation_validation_missing_citation() -> None:
    """Verify factual proposition lacking citation markers is flagged as ungrounded."""
    validator = CitationValidator()

    p1 = _make_passage(
        1,
        "chunk-crar-15",
        "Every non-banking financial company shall maintain a minimum capital ratio of 15 percent.",
    )

    # First sentence has citation; second sentence does not
    answer = (
        "Non-banking financial companies must maintain a minimum capital ratio of 15 percent [ID:1]. "
        "All board directors must attend quarterly compliance briefings in person."
    )

    result = validator.validate(answer, [p1])
    assert result.is_grounded is False
    assert len(result.ungrounded_sentences) == 1
    assert "quarterly compliance briefings" in result.ungrounded_sentences[0]
    # Sanitized answer should preserve only the grounded sentence
    assert "15 percent [ID:1]" in result.sanitized_answer
    assert "quarterly compliance briefings" not in result.sanitized_answer


def test_citation_validation_non_overlapping_passage() -> None:
    """Verify citation pointing to irrelevant passage with zero overlap is flagged."""
    validator = CitationValidator(CitationValidatorConfig(min_overlap_threshold=0.35))

    p1 = _make_passage(
        1,
        "chunk-crar-15",
        "Every non-banking financial company shall maintain a minimum capital ratio of 15 percent.",
    )

    # Claim discusses cyber incident reporting, but cites passage 1 which discusses capital ratios
    answer = "Entities must report cyber incidents to the Indian Computer Emergency Response Team within 6 hours [ID:1]."

    result = validator.validate(answer, [p1])
    assert result.is_grounded is False
    assert len(result.ungrounded_sentences) == 1
    assert "cyber incidents" in result.ungrounded_sentences[0]


def test_citation_validation_abstention_declarations() -> None:
    """Verify standard refusal declarations are accepted as grounded with zero citations."""
    validator = CitationValidator()
    p1 = _make_passage(1, "chunk-1", "Some context text.")

    answer = "Insufficient evidence: the provided regulatory documents do not contain sufficient evidence to answer this question."

    result = validator.validate(answer, [p1])
    assert result.is_grounded is True
    assert len(result.invalid_citations) == 0
    assert len(result.ungrounded_sentences) == 0
    assert result.sanitized_answer == answer


def test_citation_validation_latency_budget() -> None:
    """Verify validation execution latency <= 0.40ms on multi-core CPU."""
    validator = CitationValidator()

    p1 = _make_passage(
        1,
        "chunk-crar-15",
        "Every non-banking financial company shall maintain a minimum capital ratio of 15 percent.",
    )
    p2 = _make_passage(
        2,
        "chunk-tier-10",
        "Tier I capital shall not be less than 10 percent of aggregate risk weighted assets.",
    )

    answer = (
        "Non-banking financial companies must maintain a minimum capital ratio of 15 percent [ID:1]. "
        "Tier I capital shall not be less than 10 percent [ID:2]."
    )

    # Warm-up pass
    validator.validate(answer, [p1, p2])

    t0 = time.perf_counter()
    res = validator.validate(answer, [p1, p2])
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.is_grounded is True
    # Spec threshold: <= 0.40ms
    assert latency_ms <= 0.40, f"Expected latency <= 0.40ms, got {latency_ms:.3f}ms"


def test_citation_validation_prometheus_metrics() -> None:
    """Verify Prometheus metrics are emitted for citation validation."""
    validator = CitationValidator()
    p1 = _make_passage(
        1, "chunk-1", "Scheduled commercial banks must classify assets as NPA after 90 days."
    )

    # Valid validation
    validator.validate("Banks must classify assets as NPA after 90 days [ID:1].", [p1])

    # Invalid validation
    validator.validate("Banks must report frauds [ID:99].", [p1])

    body, _ = metrics.render()
    assert b"docscout_citations_validated_total" in body
