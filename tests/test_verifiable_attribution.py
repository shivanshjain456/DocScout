"""Tests for O6: Answers carry verifiable attribution, or are refused.

Verifies:
1. Every citation must resolve to content actually retrieved for that request; fabricated citations trigger refusal.
2. Every quoted span must be present verbatim in the cited source; quote mismatches trigger refusal.
3. Generations that stopped early (finish_reason != 'stop') are refused with an error, never returned.
4. Groundedness and abstention are computed from the evidence rather than hardcoded constants.
5. All generator implementations satisfy the exact same attribution and verification contract.
"""

from __future__ import annotations

import pytest

from app.api.models import Passage
from app.generate.attribution import AttributionError, AttributionVerifier
from app.generate.generator import DeterministicLocalGenerator
from app.generate.models import CitationSpan, GeneratedAnswer


def _make_passage(
    chunk_id: str = "chunk-100",
    text: str = "Payment aggregators must settle funds to merchants within T+1 working days.",
) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        document_id="doc-100",
        source="RBI/2024/05",
        canonical_url="https://rbi.org.in/pa/05",
        score=0.92,
        arm_ranks={"dense": 1, "bm25": 1},
        rank=1,
        char_start=0,
        char_end=len(text),
        text=text,
    )


def test_fabricated_citation_triggers_refusal() -> None:
    """An answer citing a chunk_id that was not in retrieved passages is refused with an error."""
    passage = _make_passage(chunk_id="chunk-retrieved-1")

    # Answer citing a fabricated chunk not in retrieved passages
    answer = GeneratedAnswer(
        text="Settlement must happen in T+1 [chunk-fabricated-999].",
        citations=["chunk-fabricated-999"],
        citation_spans=[
            CitationSpan(
                chunk_id="chunk-fabricated-999",
                source="RBI/2024/05",
                quote="Settlement must happen in T+1",
            )
        ],
        model_id="test-model",
        finish_reason="stop",
    )

    with pytest.raises(AttributionError) as exc_info:
        AttributionVerifier.verify(answer, [passage])
    assert (
        "Fabricated citation" in str(exc_info.value) or "unretrieved" in str(exc_info.value).lower()
    )


def test_quote_mismatch_triggers_refusal() -> None:
    """An answer whose quote does not appear verbatim in cited chunk is refused."""
    passage = _make_passage(
        chunk_id="chunk-retrieved-1",
        text="Payment aggregators must settle funds to merchants within T+1 working days.",
    )

    # Hallucinated / altered quote
    answer = GeneratedAnswer(
        text="Settlement occurs in T+0 instantaneous days [chunk-retrieved-1].",
        citations=["chunk-retrieved-1"],
        citation_spans=[
            CitationSpan(
                chunk_id="chunk-retrieved-1",
                source="RBI/2024/05",
                quote="Settlement occurs in T+0 instantaneous days.",
            )
        ],
        model_id="test-model",
        finish_reason="stop",
    )

    with pytest.raises(AttributionError) as exc_info:
        AttributionVerifier.verify(answer, [passage])
    assert "Quote mismatch" in str(exc_info.value) or "verbatim" in str(exc_info.value).lower()


def test_truncated_generation_stopped_early_triggers_refusal() -> None:
    """A generation cut short (finish_reason='length') is refused with an error."""
    passage = _make_passage(chunk_id="chunk-retrieved-1")

    # Partial answer that ran out of tokens
    answer = GeneratedAnswer(
        text="Payment aggregators must settle funds to merchants within",
        citations=["chunk-retrieved-1"],
        model_id="test-model",
        finish_reason="length",  # Stopped early!
    )

    with pytest.raises(AttributionError) as exc_info:
        AttributionVerifier.verify(answer, [passage])
    assert (
        "truncated" in str(exc_info.value).lower() or "stopped early" in str(exc_info.value).lower()
    )


def test_valid_answer_attribution_passes_and_computes_groundedness() -> None:
    """A fully grounded answer with verbatim quotes passes verification."""
    passage = _make_passage(
        chunk_id="chunk-retrieved-1",
        text="Payment aggregators must settle funds to merchants within T+1 working days.",
    )

    quote = "Payment aggregators must settle funds to merchants within T+1 working days."
    answer = GeneratedAnswer(
        text=f"{quote} [chunk-retrieved-1]",
        citations=["chunk-retrieved-1"],
        citation_spans=[
            CitationSpan(
                chunk_id="chunk-retrieved-1",
                source="RBI/2024/05",
                quote=quote,
                char_start=0,
                char_end=len(quote),
            )
        ],
        grounded=False,  # Should be computed dynamically
        model_id="test-model",
        finish_reason="stop",
    )

    verified = AttributionVerifier.verify(answer, [passage])
    assert verified.grounded is True
    assert verified.citations == ["chunk-retrieved-1"]


def test_deterministic_local_generator_satisfies_attribution_contract() -> None:
    """The local deterministic generator produces verifiable citations and spans."""
    passage = _make_passage(
        chunk_id="chunk-100",
        text="Payment aggregators must settle funds to merchants within T+1 working days.",
    )

    generator = DeterministicLocalGenerator()
    answer = generator.generate(
        query="What is the settlement timeline for payment aggregators?",
        passages=[passage],
    )

    assert not answer.abstained
    assert answer.finish_reason == "stop"
    assert answer.citations == ["chunk-100"]
    assert len(answer.citation_spans) > 0

    # Verification must pass without error
    verified = AttributionVerifier.verify(answer, [passage])
    assert verified.grounded is True
