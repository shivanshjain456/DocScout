"""Unit tests for Token-Budget Dynamic Context Packing (FEAT-073)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.api.metrics import (
    CONTEXT_PACKS_COMPLETED_TOTAL,
    CONTEXT_TOKEN_UTILIZATION_RATIO,
)
from app.api.models import Passage
from app.generate.prompt import format_evidence_context
from app.retrieval.context_packer import ContextPacker, pack_context
from app.retrieval.types import ContextPackerConfig, Retrieved


def make_passage(chunk_id: str, score: float, rank: int, text: str) -> Passage:
    return Passage(
        chunk_id=chunk_id,
        rank=rank,
        score=score,
        document_id=f"doc-{chunk_id}",
        source="RBI",
        canonical_url=f"https://rbi.org.in/{chunk_id}",
        arm_ranks={"dense": rank},
        char_start=0,
        char_end=len(text),
        text=text,
    )


def make_retrieved(chunk_id: str, score: float, rank: int, text: str) -> Retrieved:
    return Retrieved(
        chunk_id=chunk_id,
        rank=rank,
        score=score,
        document_id=f"doc-{chunk_id}",
        source="SEBI",
        text=text,
        arm_ranks={"bm25": rank},
    )


# --- Edge cases and basic packing ---


def test_empty_passages_returns_empty_packed_context() -> None:
    res = pack_context([])
    assert res.packed_passages == []
    assert res.total_tokens == 0
    assert res.utilization_ratio == 0.0
    assert not res.truncated_boundary_chunk


def test_single_passage_fitting_budget() -> None:
    text = "The Reserve Bank of India mandates strict liquidity ratios for all scheduled banks."
    p = make_passage("c1", 0.95, 1, text)
    packer = ContextPacker()
    res = packer.pack([p], config=ContextPackerConfig(max_tokens=1024))
    assert len(res.packed_passages) == 1
    assert res.packed_passages[0].chunk_id == "c1"
    assert res.total_tokens > 0
    assert not res.truncated_boundary_chunk
    assert res.utilization_ratio == res.total_tokens / 1024


def test_token_ceiling_enforcement() -> None:
    sentences = [
        "Under Section 12 of SEBI LODR regulations, all listed entities must file financial reports. "
        * 3,
        "The board shall review all quarterly filings prior to submission to the stock exchanges. "
        * 3,
        "Non-compliance shall invite penal actions including monetary fines and trading suspension. "
        * 3,
        "Statutory auditors must provide an independent assessment of internal financial controls. "
        * 3,
        "All disclosures must be submitted in machine-readable XBRL format without delay. " * 3,
    ]
    passages = [make_passage(f"c{i}", 0.90 - i * 0.05, i + 1, s) for i, s in enumerate(sentences)]
    cfg = ContextPackerConfig(max_tokens=300, target_utilization=0.95)
    ceiling = int(300 * 0.95)

    packer = ContextPacker()
    res = packer.pack(passages, config=cfg)

    assert res.total_tokens <= ceiling
    assert len(res.packed_passages) <= len(passages)


# --- Sentence boundary trimming ---


def test_sentence_boundary_trimming_preserves_complete_sentences() -> None:
    p1_sentences = [
        f"Statutory section {i} mandates strict compliance with capital maintenance guidelines."
        for i in range(1, 30)
    ]
    p1_text = " ".join(p1_sentences)
    p2_text = (
        "Fifth provision requiring monthly compliance reporting for corporate banks. "
        "Sixth provision detailing penalties for late filings by primary dealers. "
        "Seventh provision specifying appellate tribunal procedures for disputes."
    )
    p1 = make_passage("c1", 0.95, 1, p1_text)
    p2 = make_passage("c2", 0.90, 2, p2_text)

    packer = ContextPacker()
    p1_tokens = packer.count_tokens(p1.text)
    # p1_tokens is ~280 tokens. Budget of p1_tokens + 25 will only fit 1 or 2 sentences of p2
    cfg = ContextPackerConfig(
        max_tokens=p1_tokens + 25,
        target_utilization=1.0,
        sentence_boundary_trim=True,
    )

    res = packer.pack([p1, p2], config=cfg)
    assert len(res.packed_passages) == 2
    assert res.packed_passages[0].chunk_id == "c1"
    assert res.packed_passages[0].text == p1.text
    assert res.packed_passages[1].chunk_id == "c2"

    trimmed_text = res.packed_passages[1].text
    # Must not contain the full text of p2
    assert trimmed_text != p2.text
    # Must end with a valid sentence punctuation mark
    assert trimmed_text.endswith((".", "!", "?", ";"))
    assert res.truncated_boundary_chunk
    assert res.total_tokens <= cfg.max_tokens


def test_sentence_boundary_trimming_with_semicolons() -> None:
    text = (
        "Provided that all scheduled commercial banks maintain statutory reserve; "
        "provided further that cooperative credit societies may apply for staggered compliance; "
        "and provided finally that willful default results in license revocation."
    )
    packer = ContextPacker()
    full_tok = packer.count_tokens(text)
    trimmed, tok_count, did_trim = packer.trim_to_sentence_boundary(text, max_tokens=full_tok // 2)

    assert did_trim
    assert tok_count <= full_tok // 2
    assert trimmed.endswith(";")
    assert "willful default" not in trimmed


def test_boundary_chunk_discarded_if_no_sentence_fits() -> None:
    p1_sentences = [
        f"Statutory section {i} mandates strict compliance with capital maintenance guidelines."
        for i in range(1, 25)
    ]
    p1_text = " ".join(p1_sentences)
    p2_text = "This is an extremely long single sentence that cannot possibly fit into a tiny two token remaining allowance."
    p1 = make_passage("c1", 0.95, 1, p1_text)
    p2 = make_passage("c2", 0.85, 2, p2_text)

    packer = ContextPacker()
    p1_tok = packer.count_tokens(p1.text)

    # Budget has only 2 tokens left after p1, and total max_tokens >= 256
    cfg = ContextPackerConfig(
        max_tokens=p1_tok + 2, target_utilization=1.0, sentence_boundary_trim=True
    )
    res = packer.pack([p1, p2], config=cfg)

    # p2 should be discarded because even its first sentence cannot fit in 2 tokens
    assert len(res.packed_passages) == 1
    assert res.packed_passages[0].chunk_id == "c1"
    assert not res.truncated_boundary_chunk
    assert res.total_tokens == p1_tok


def test_sentence_trimming_disabled_drops_overflow_chunk() -> None:
    p1_sentences = [
        f"Standard capital adequacy rules for banking institutions in category {i}."
        for i in range(1, 20)
    ]
    p2_sentences = [
        f"Secondary reserve requirements for authorized foreign exchange dealers in tier {i}."
        for i in range(1, 15)
    ]
    p1 = make_passage("c1", 0.95, 1, " ".join(p1_sentences))
    p2 = make_passage("c2", 0.85, 2, " ".join(p2_sentences))

    packer = ContextPacker()
    p1_tok = packer.count_tokens(p1.text)
    p2_tok = packer.count_tokens(p2.text)

    cfg = ContextPackerConfig(
        max_tokens=p1_tok + (p2_tok // 2),
        target_utilization=1.0,
        sentence_boundary_trim=False,
    )
    res = packer.pack([p1, p2], config=cfg)

    # Overflow chunk p2 must be discarded entirely
    assert len(res.packed_passages) == 1
    assert res.packed_passages[0].chunk_id == "c1"
    assert not res.truncated_boundary_chunk


# --- Target utilization scaling across budgets ---


@pytest.mark.parametrize("budget", [1024, 2048, 4096])
def test_target_utilization_achieved_across_budgets(budget: int) -> None:
    # Build 80 regulatory paragraphs with abundant sentences
    paragraphs = [
        f"Paragraph {i}: The competent authority under Section {i} of the banking regulation act "
        f"stipulates that every financial intermediary must maintain an adequate capital conservation buffer. "
        f"Quarterly review reports must be submitted to the supervisory committee within 15 days of quarter end. "
        f"Failure to adhere to these reporting guidelines triggers supervisory action under prompt corrective action framework."
        for i in range(1, 81)
    ]
    passages = [make_passage(f"c{i}", 1.0 - (i * 0.01), i, p) for i, p in enumerate(paragraphs)]

    packer = ContextPacker()
    cfg = ContextPackerConfig(max_tokens=budget, target_utilization=0.95)
    ceiling = int(budget * 0.95)

    res = packer.pack(passages, config=cfg)

    # Total tokens must strictly obey ceiling
    assert res.total_tokens <= ceiling
    # Utilization must be >= 90% when sufficient content is supplied
    assert res.utilization_ratio >= 0.90
    assert res.total_tokens >= int(budget * 0.90)


# --- Input validations ---


def test_config_validations() -> None:
    with pytest.raises(ValueError, match="max_tokens must be >= 256"):
        ContextPackerConfig(max_tokens=255)

    with pytest.raises(ValueError, match="target_utilization must be in"):
        ContextPackerConfig(target_utilization=0.49)

    with pytest.raises(ValueError, match="target_utilization must be in"):
        ContextPackerConfig(target_utilization=1.05)


# --- Polymorphic type support: Retrieved, Passage, and dict ---


def test_packing_retrieved_dataclass() -> None:
    r1 = make_retrieved(
        "r1",
        0.9,
        1,
        "RBI regulatory framework on credit cards. Annual report disclosure requirements.",
    )
    r2 = make_retrieved(
        "r2", 0.8, 2, "SEBI framework for REITs and InvITs. Valuation guidelines for assets."
    )

    packer = ContextPacker()
    res = packer.pack([r1, r2], config=ContextPackerConfig(max_tokens=1024))
    assert len(res.packed_passages) == 2
    assert isinstance(res.packed_passages[0], Retrieved)
    assert res.packed_passages[0].chunk_id == "r1"


def test_packing_dict_items() -> None:
    d1: dict[str, Any] = {
        "chunk_id": "d1",
        "score": 0.88,
        "text": "Guidance note on accounting for corporate CSR expenses. Disclosures in financial statements.",
    }
    d2: dict[str, Any] = {
        "chunk_id": "d2",
        "score": 0.75,
        "text": "Internal audit checklist for listed commercial banks. Review of credit appraisal standards.",
    }

    packer = ContextPacker()
    res = packer.pack([d1, d2], config=ContextPackerConfig(max_tokens=1024))
    assert len(res.packed_passages) == 2
    assert isinstance(res.packed_passages[0], dict)
    assert res.packed_passages[0]["chunk_id"] == "d1"


# --- Relevance order sorting ---


def test_relevance_sorting_descending() -> None:
    p_low = make_passage("low", 0.40, 3, "Low relevance regulatory advisory on stationery.")
    p_high = make_passage("high", 0.98, 1, "High relevance primary circular on interest rate risk.")
    p_mid = make_passage("mid", 0.75, 2, "Medium relevance clarification on hedging instruments.")

    packer = ContextPacker()
    # Pass them scrambled
    res = packer.pack([p_low, p_high, p_mid], config=ContextPackerConfig(max_tokens=1024))

    assert [p.chunk_id for p in res.packed_passages] == ["high", "mid", "low"]


# --- Execution latency budget <= 0.8 ms p95 ---


def test_execution_latency_under_p95_budget() -> None:
    import gc

    passages = [
        make_passage(
            f"c{i}",
            0.95 - (i * 0.05),
            i + 1,
            f"Regulatory circular section {i}. All entities must submit compliance forms by day {i * 5}. "
            "Supervisory action follows failure to submit.",
        )
        for i in range(3)
    ]
    packer = ContextPacker()
    cfg = ContextPackerConfig(max_tokens=500, target_utilization=0.95)

    # Warmup
    for _ in range(10):
        packer.pack(passages, config=cfg)

    gc.collect()
    latencies: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        packer.pack(passages, config=cfg)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    # Latency budget: <= 0.8 ms p95
    assert p95 <= 0.8, f"p95 latency was {p95:.3f} ms, expected <= 0.8 ms"


# --- Metrics emission ---


def test_prometheus_metrics_emitted() -> None:
    p = make_passage("c1", 0.95, 1, "Standard passage for testing metrics counter and gauge.")
    packer = ContextPacker()
    res = packer.pack([p], config=ContextPackerConfig(max_tokens=1024))

    gauge_val = CONTEXT_TOKEN_UTILIZATION_RATIO._value.get()
    assert gauge_val == pytest.approx(res.utilization_ratio, rel=1e-3)
    counter_val = CONTEXT_PACKS_COMPLETED_TOTAL.labels(status="success")._value.get()
    assert counter_val >= 1.0


# --- Fallback behavior on unexpected error ---


def test_fallback_on_unexpected_error() -> None:
    def failing_counter(text: str) -> int:
        raise RuntimeError("Simulated tokenization hardware failure")

    p1 = make_passage("c1", 0.95, 1, "Passage one text.")
    p2 = make_passage("c2", 0.85, 2, "Passage two text.")
    p3 = make_passage("c3", 0.75, 3, "Passage three text.")
    p4 = make_passage("c4", 0.65, 4, "Passage four text.")

    packer = ContextPacker(count_tokens_fn=failing_counter)
    # Pack should not crash, must return top-3 untrimmed passages
    res = packer.pack([p1, p2, p3, p4], config=ContextPackerConfig(max_tokens=1024))

    assert len(res.packed_passages) == 3
    assert [p.chunk_id for p in res.packed_passages] == ["c1", "c2", "c3"]
    assert not res.truncated_boundary_chunk


# --- Integration with format_evidence_context ---


def test_format_evidence_context_with_pack_flag() -> None:
    p1 = make_passage("c1", 0.95, 1, "Circular provision on asset reconstruction companies.")
    p2 = make_passage("c2", 0.85, 2, "Circular provision on resolution of stressed assets.")

    xml = format_evidence_context(
        [p1, p2], pack=True, packer_config=ContextPackerConfig(max_tokens=1024)
    )
    assert "<retrieved_evidence>" in xml
    assert 'chunk_id="c1"' in xml
    assert 'chunk_id="c2"' in xml
    assert "</retrieved_evidence>" in xml
