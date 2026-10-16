"""Unit and integration tests for sub-sentence evidence highlighting and span pinpointing (FEAT-078)."""

from __future__ import annotations

import time
import uuid

import pytest

from app.api.metrics import SPANS_HIGHLIGHTED_TOTAL
from app.api.models import HighlightSpan, Passage
from app.retrieval.span_pinpoint import (
    HighlightConfig,
    SpanPinpointer,
    compute_span_iou,
    decorate_retrieved_highlights,
    get_query_features,
    pinpoint_highlights,
    split_sentences_with_spans,
)
from app.retrieval.types import Retrieved


# --- 1. Sentence boundary splitting & offset accuracy --------------------------------------
def test_sentence_boundary_splitting_offsets() -> None:
    """Character offsets must index directly into text: text[start:end] == span_text."""
    text = (
        "Non-bank Payment Aggregators (PAs) shall have a minimum net worth of Rs. 15 crore at "
        "application. Subsequently, net worth must be increased to Rs. 25 crore within three "
        "financial years; non-compliance may attract penal action under Sec. 46 of the PSS Act. "
        "All PAs must submit an annual audited net worth certificate to RBI."
    )

    sentences = split_sentences_with_spans(text)
    assert len(sentences) >= 2

    for start, end, span_text in sentences:
        assert 0 <= start < end <= len(text)
        assert text[start:end] == span_text
        assert not span_text.startswith(" ")
        assert not span_text.endswith(" ")

    # Verify that 'Rs. 15 crore' and 'Sec. 46' did NOT trigger a false sentence split
    first_sent = sentences[0][2]
    assert "Rs. 15 crore" in first_sent


def test_empty_and_whitespace_splitting() -> None:
    """Empty or blank text must return an empty list without raising."""
    assert split_sentences_with_spans("") == []
    assert split_sentences_with_spans("   \n\t  ") == []


# --- 2. Sub-sentence highlight ranking and operative clause pinpointing -------------------
def test_operative_sentence_pinpointing() -> None:
    """Pinpointer must identify the exact operative statutory sentence among background clauses."""
    passage = (
        "The Reserve Bank of India reviews the regulatory framework for regulated entities from "
        "time to time to ensure financial stability. Banks shall report cyber security incidents "
        "to the Reserve Bank of India within 2 to 6 hours of detection. Failure to report cyber "
        "incidents in time attracts regulatory supervisory penalties. Regulated entities should "
        "maintain complete incident response logs for forensic review."
    )
    query = "What is the deadline for banks to report cyber security incidents to RBI?"

    highlights = pinpoint_highlights(query, passage)
    assert len(highlights) >= 1
    top_highlight = highlights[0]

    assert "within 2 to 6 hours of detection" in top_highlight.text
    assert top_highlight.score >= 0.60
    assert passage[top_highlight.start : top_highlight.end] == top_highlight.text


# --- 3. Acceptance criteria: >= 90% IoU with gold standard evidence quotes -----------------
def test_iou_overlap_against_gold_evidence_quotes() -> None:
    """Sub-sentence highlights must achieve >= 90% IoU overlap with gold standard evidence quote spans."""
    benchmark_cases = [
        {
            "query": "Under the Differential Rate of Interest scheme, what is the maximum loan amount and what rate of interest applies?",
            "passage": (
                "The Differential Rate of Interest (DRI) Scheme was formulated to cater to the weaker sections. "
                "Under the scheme, banks provide finance up to ₹15,000/- at a concessional rate of interest of 4 per cent per annum. "
                "Eligibility is determined based on annual family income ceilings."
            ),
            "gold_quote": "Under the scheme, banks provide finance up to ₹15,000/- at a concessional rate of interest of 4 per cent per annum.",
        },
        {
            "query": "What is the deadline for banks to report cyber security incidents to RBI?",
            "passage": (
                "Information security guidelines require rigorous continuous monitoring. "
                "Banks shall report cyber security incidents to the Reserve Bank of India within 2 to 6 hours of detection. "
                "A root cause analysis report must be filed within 21 days."
            ),
            "gold_quote": "Banks shall report cyber security incidents to the Reserve Bank of India within 2 to 6 hours of detection.",
        },
        {
            "query": "What are the four regulatory layers under NBFC scale based regulation framework?",
            "passage": (
                "The regulatory architecture for non-banking financial companies has been reorganized. "
                "The Scale Based Regulation framework for NBFCs comprises four regulatory layers: Base Layer, Middle Layer, Upper Layer, and Top Layer. "
                "Capital requirements vary depending on the regulatory tier."
            ),
            "gold_quote": "The Scale Based Regulation framework for NBFCs comprises four regulatory layers: Base Layer, Middle Layer, Upper Layer, and Top Layer.",
        },
        {
            "query": "What is the minimum net worth requirement for non-bank payment aggregators?",
            "passage": (
                "Payment settlement systems require robust financial buffers. "
                "Non-bank Payment Aggregators (PAs) shall have a minimum net worth requirement of Rs 15 crore at the time of application and Rs 25 crore within three financial years. "
                "Net worth must be certified by statutory auditors."
            ),
            "gold_quote": "Non-bank Payment Aggregators (PAs) shall have a minimum net worth requirement of Rs 15 crore at the time of application and Rs 25 crore within three financial years.",
        },
    ]

    ious: list[float] = []
    for item in benchmark_cases:
        passage = item["passage"]
        gold_quote = item["gold_quote"]
        query = item["query"]

        gold_start = passage.index(gold_quote)
        gold_end = gold_start + len(gold_quote)
        gold_span = (gold_start, gold_end)

        highlights = pinpoint_highlights(query, passage)
        assert len(highlights) >= 1, f"No highlights returned for query: {query}"

        # Calculate max IoU among returned highlight spans
        best_case_iou = max(compute_span_iou((h.start, h.end), gold_span) for h in highlights)
        ious.append(best_case_iou)
        assert best_case_iou >= 0.90, (
            f"IoU {best_case_iou:.4f} < 0.90 for gold quote: '{gold_quote}'"
        )

    avg_iou = sum(ious) / len(ious)
    assert avg_iou >= 0.90, f"Average benchmark IoU was {avg_iou:.4f} (target >= 0.90)"


# --- 4. Configuration and threshold boundaries --------------------------------------------
def test_configuration_validation() -> None:
    """Invalid HighlightConfig values must be rejected."""
    with pytest.raises(ValueError, match="max_highlight_spans must be >= 1"):
        HighlightConfig(max_highlight_spans=0)

    with pytest.raises(ValueError, match="min_sentence_score must be in"):
        HighlightConfig(min_sentence_score=1.5)

    with pytest.raises(ValueError, match="min_sentence_score must be in"):
        HighlightConfig(min_sentence_score=-0.1)


def test_max_highlight_spans_ceiling() -> None:
    """Pinpointer must respect max_highlight_spans ceiling."""
    text = (
        "Banks must maintain CRAR of 9 percent. "
        "NBFCs must maintain CRAR of 15 percent. "
        "Payment banks must maintain CRAR of 15 percent. "
        "Small finance banks must maintain CRAR of 15 percent."
    )
    query = "What CRAR percentage must financial entities maintain?"

    config_1 = HighlightConfig(max_highlight_spans=1, min_sentence_score=0.40)
    spans_1 = pinpoint_highlights(query, text, config=config_1)
    assert len(spans_1) == 1

    config_2 = HighlightConfig(max_highlight_spans=2, min_sentence_score=0.40)
    spans_2 = pinpoint_highlights(query, text, config=config_2)
    assert len(spans_2) == 2


# --- 5. Fail-safe error handling and zero out-of-bounds guarantee --------------------------
def test_fail_safe_empty_and_irrelevant() -> None:
    """Irrelevant passages or empty queries return empty highlights without exception."""
    assert pinpoint_highlights("", "Some statutory text") == []
    assert pinpoint_highlights("What is net worth?", "") == []

    irrelevant = (
        "The quick brown fox jumps over the lazy dog. "
        "A wizard with a golden wand walked through the forest."
    )
    assert (
        pinpoint_highlights(
            "What is the capital adequacy ratio under RBI directions?",
            irrelevant,
            config=HighlightConfig(min_sentence_score=0.70),
        )
        == []
    )


# --- 6. Retrieved and Passage integration --------------------------------------------------
def test_decorate_retrieved_highlights() -> None:
    """Retrieved list items are decorated with exact highlight spans."""
    items = [
        Retrieved(
            chunk_id=str(uuid.uuid4()),
            rank=1,
            score=0.92,
            document_id=str(uuid.uuid4()),
            source="rbi",
            text="Banks shall report cyber security incidents to RBI within 2 to 6 hours of detection.",
        ),
        Retrieved(
            chunk_id=str(uuid.uuid4()),
            rank=2,
            score=0.88,
            document_id=str(uuid.uuid4()),
            source="rbi",
            text="The audit committee shall review cyber security posture at quarterly intervals.",
        ),
    ]
    query = "What is the cyber incident reporting deadline to RBI?"

    decorated = decorate_retrieved_highlights(query, items)
    assert len(decorated) == 2
    assert len(decorated[0].highlights) >= 1
    assert "within 2 to 6 hours" in decorated[0].highlights[0].text


def test_passage_model_serialization_with_highlights() -> None:
    """Passage Pydantic model validates and serializes highlights cleanly."""
    span = HighlightSpan(
        start=10,
        end=35,
        text="minimum net worth of Rs 15 crore",
        score=0.85,
    )
    passage = Passage(
        rank=1,
        chunk_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        source="rbi",
        canonical_url=None,
        score=0.95,
        arm_ranks={"bm25": 1, "dense": 1},
        char_start=0,
        char_end=100,
        text="A company must maintain a minimum net worth of Rs 15 crore at registration.",
        highlights=[span],
    )

    data = passage.model_dump()
    assert "highlights" in data
    assert len(data["highlights"]) == 1
    assert data["highlights"][0]["start"] == 10
    assert data["highlights"][0]["score"] == 0.85

    # Roundtrip validation
    reconstructed = Passage.model_validate(data)
    assert reconstructed.highlights[0].text == span.text


# --- 7. Performance latency budget: <= 2.0 ms for 5 passages on CPU -----------------------
def test_latency_budget_5_passages() -> None:
    """Span pinpointing across 5 retrieved passages must execute in <= 2.0 ms on CPU."""
    passages = [
        (
            f"Regulatory circular paragraph {i}. The Reserve Bank of India mandates that all non-bank "
            f"payment aggregators maintain minimum capital reserves. Non-bank Payment Aggregators (PAs) "
            f"shall have a minimum net worth requirement of Rs 15 crore at application. Compliance must "
            f"be verified by statutory auditors within sixty days of financial year end."
        )
        for i in range(5)
    ]
    query = "What is the minimum net worth requirement for non-bank payment aggregators?"

    pinpointer = SpanPinpointer()
    feat = get_query_features(query)

    # Warmup
    for _ in range(5):
        for p in passages:
            _ = pinpointer.pinpoint(query, p, features=feat)

    latencies: list[float] = []
    for _ in range(40):
        t0 = time.perf_counter()
        for p in passages:
            _ = pinpointer.pinpoint(query, p, features=feat)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
    assert p95_latency <= 2.0, (
        f"Pinpointing 5 passages latency p95 was {p95_latency:.4f} ms (budget <= 2.0 ms)"
    )


# --- 8. Prometheus metric emission --------------------------------------------------------
def test_prometheus_metric_emission() -> None:
    """docscout_spans_highlighted_total counter increments when spans are highlighted."""
    query = "What is the deadline for banks to report cyber security incidents to RBI?"
    text = "Banks shall report cyber security incidents to the Reserve Bank of India within 2 to 6 hours."

    before = SPANS_HIGHLIGHTED_TOTAL.labels(source="rbi")._value.get()
    _ = pinpoint_highlights(query, text, source="rbi")
    after = SPANS_HIGHLIGHTED_TOTAL.labels(source="rbi")._value.get()

    assert after > before
