"""Unit tests for Lost-in-the-Middle Context Reordering (FEAT-072)."""

from __future__ import annotations

import time
from typing import Any

from app.api.models import Passage
from app.generate.prompt import format_evidence_context
from app.retrieval import RetrievalConfig
from app.retrieval.context_reorder import reorder_context
from app.retrieval.types import Retrieved


def make_passage(chunk_id: str, score: float, rank: int, text: str = "sample text") -> Passage:
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


def make_retrieved(chunk_id: str, score: float, rank: int) -> Retrieved:
    return Retrieved(
        chunk_id=chunk_id,
        rank=rank,
        score=score,
        document_id=f"doc-{chunk_id}",
        source="SEBI",
        text=f"Text content for {chunk_id}",
        arm_ranks={"bm25": rank},
    )


# --- Edge cases ---


def test_empty_passages_returns_empty_list() -> None:
    assert reorder_context([]) == []


def test_single_passage_returns_identical_with_presentation_rank() -> None:
    p = make_passage("c1", 0.95, 1)
    reordered = reorder_context([p])
    assert len(reordered) == 1
    assert reordered[0].chunk_id == "c1"
    assert reordered[0].presentation_rank == 1
    assert reordered[0].score == 0.95
    assert reordered[0].rank == 1


def test_two_passages_returns_sorted_with_presentation_ranks() -> None:
    p1 = make_passage("c1", 0.70, 2)
    p2 = make_passage("c2", 0.95, 1)
    reordered = reorder_context([p1, p2])
    assert len(reordered) == 2
    assert reordered[0].chunk_id == "c2"
    assert reordered[0].presentation_rank == 1
    assert reordered[1].chunk_id == "c1"
    assert reordered[1].presentation_rank == 2


# --- Alternating boundary distribution (U-shape) ---


def test_three_passages_reordering() -> None:
    # 3 passages: Rank 1 -> pos 0, Rank 2 -> pos 2, Rank 3 -> pos 1
    p1 = make_passage("c1", 0.90, 1)
    p2 = make_passage("c2", 0.80, 2)
    p3 = make_passage("c3", 0.70, 3)

    reordered = reorder_context([p1, p2, p3])
    assert [p.chunk_id for p in reordered] == ["c1", "c3", "c2"]
    assert [p.presentation_rank for p in reordered] == [1, 2, 3]
    # Rank 1 at index 0, Rank 2 at index 2 (last), Rank 3 at index 1 (middle)
    assert reordered[0].rank == 1
    assert reordered[1].rank == 3
    assert reordered[2].rank == 2


def test_five_passages_u_shaped_distribution() -> None:
    passages = [
        make_passage("c1", 0.90, 1),
        make_passage("c2", 0.80, 2),
        make_passage("c3", 0.70, 3),
        make_passage("c4", 0.60, 4),
        make_passage("c5", 0.50, 5),
    ]

    reordered = reorder_context(passages)
    assert len(reordered) == 5
    # Alternating boundary:
    # index 0: Rank 1 (c1, score 0.90)
    # index 1: Rank 3 (c3, score 0.70)
    # index 2: Rank 5 (c5, score 0.50) [lowest relevance in middle]
    # index 3: Rank 4 (c4, score 0.60)
    # index 4: Rank 2 (c2, score 0.80) [high relevance at end]
    assert [p.chunk_id for p in reordered] == ["c1", "c3", "c5", "c4", "c2"]
    assert [p.presentation_rank for p in reordered] == [1, 2, 3, 4, 5]
    assert [p.rank for p in reordered] == [1, 3, 5, 4, 2]

    # Boundary verification: highest-scoring passages are at boundaries
    assert reordered[0].score == 0.90
    assert reordered[-1].score == 0.80
    # Center has minimum score
    assert reordered[2].score == 0.50


def test_ten_passages_alternating_boundary() -> None:
    passages = [make_passage(f"c{i + 1}", 1.0 - (i * 0.05), i + 1) for i in range(10)]
    reordered = reorder_context(passages)

    assert len(reordered) == 10
    # Boundary placements:
    # Rank 1 at position 0
    assert reordered[0].chunk_id == "c1"
    assert reordered[0].presentation_rank == 1
    # Rank 2 at position 9 (last)
    assert reordered[9].chunk_id == "c2"
    assert reordered[9].presentation_rank == 10
    # Rank 3 at position 1
    assert reordered[1].chunk_id == "c3"
    assert reordered[1].presentation_rank == 2
    # Rank 4 at position 8
    assert reordered[8].chunk_id == "c4"
    assert reordered[8].presentation_rank == 9
    # Middle contains least relevant (Rank 9 and Rank 10)
    assert {reordered[4].chunk_id, reordered[5].chunk_id} == {"c9", "c10"}


# --- Performance latency requirement ---


def test_reordering_execution_latency_under_50_microseconds() -> None:
    """Spec requires latency <= 0.05 ms for 10 passages."""
    passages = [make_passage(f"c{i}", 1.0 - i * 0.08, i + 1) for i in range(10)]

    # Warm up
    for _ in range(50):
        reorder_context(passages)

    import gc

    gc.collect()
    iterations = 500
    trials: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        for _ in range(iterations):
            reorder_context(passages)
        elapsed_total_ms = (time.perf_counter() - t0) * 1000.0
        trials.append(elapsed_total_ms / iterations)

    best_latency_ms = min(trials)
    # Must be <= 0.05 ms (50 microseconds)
    assert best_latency_ms <= 0.05, f"Best latency {best_latency_ms:.4f} ms exceeded 0.05 ms budget"


# --- Immutability & Dataclass / Dict Support ---


def test_retrieved_dataclass_support_without_mutation() -> None:
    original = [
        make_retrieved("r1", 0.95, 1),
        make_retrieved("r2", 0.85, 2),
        make_retrieved("r3", 0.75, 3),
    ]

    # Original must have presentation_rank None
    assert all(r.presentation_rank is None for r in original)

    reordered = reorder_context(original)
    assert [r.chunk_id for r in reordered] == ["r1", "r3", "r2"]
    assert [r.presentation_rank for r in reordered] == [1, 2, 3]

    # Original list elements remain unmutated
    assert all(r.presentation_rank is None for r in original)


def test_dict_input_support() -> None:
    items: list[dict[str, Any]] = [
        {"chunk_id": "d1", "score": 0.9, "rank": 1},
        {"chunk_id": "d2", "score": 0.8, "rank": 2},
        {"chunk_id": "d3", "score": 0.7, "rank": 3},
    ]
    reordered = reorder_context(items)
    assert [d["chunk_id"] for d in reordered] == ["d1", "d3", "d2"]
    assert [d["presentation_rank"] for d in reordered] == [1, 2, 3]


def test_deterministic_tie_breaking() -> None:
    p1 = make_passage("chunk_b", 0.80, 1)
    p2 = make_passage("chunk_a", 0.80, 2)
    p3 = make_passage("chunk_c", 0.80, 3)

    # All identical scores break ties deterministically on original index
    first_run = [p.chunk_id for p in reorder_context([p1, p2, p3])]
    second_run = [p.chunk_id for p in reorder_context([p1, p2, p3])]
    assert first_run == second_run
    assert first_run == ["chunk_b", "chunk_c", "chunk_a"]


# --- Error resilience fallback ---


def test_fallback_on_broken_object() -> None:
    class FlakyPassage:
        @property
        def score(self) -> float:
            raise RuntimeError("Property access failed")

    broken_list = [FlakyPassage(), FlakyPassage()]
    # Should fall back cleanly to list(passages) without raising
    result = reorder_context(broken_list)
    assert len(result) == 2


# --- Generation Prompt Context Formatting ---


def test_format_evidence_context_includes_presentation_rank() -> None:
    passages = [
        make_passage("c1", 0.95, 1, "Evidence paragraph 1"),
        make_passage("c2", 0.85, 2, "Evidence paragraph 2"),
        make_passage("c3", 0.75, 3, "Evidence paragraph 3"),
    ]

    xml = format_evidence_context(passages, reorder=True)
    assert 'presentation_rank="1"' in xml
    assert 'presentation_rank="2"' in xml
    assert 'presentation_rank="3"' in xml
    # Order inside XML should have c1 first, c3 middle, c2 last
    pos_c1 = xml.find('chunk_id="c1"')
    pos_c2 = xml.find('chunk_id="c2"')
    pos_c3 = xml.find('chunk_id="c3"')
    assert pos_c1 < pos_c3 < pos_c2


# --- Configuration Serialization ---


def test_retrieval_config_has_lost_in_middle_flag() -> None:
    cfg_default = RetrievalConfig(name="default")
    assert cfg_default.enable_lost_in_middle_reordering is False
    assert "enable_lost_in_middle_reordering" in cfg_default.as_dict()
    assert cfg_default.as_dict()["enable_lost_in_middle_reordering"] is False

    cfg_enabled = RetrievalConfig(name="lim-on", enable_lost_in_middle_reordering=True)
    assert cfg_enabled.enable_lost_in_middle_reordering is True
    assert cfg_enabled.as_dict()["enable_lost_in_middle_reordering"] is True
