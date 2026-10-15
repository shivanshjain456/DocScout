"""Tests for Arm-Anchored Fusion with Provenance Guarantees (FEAT-074, ADR-0065).

Validates:
1. Exact circular number retention when lexical arm is confident and dense arm is noisy.
2. Dense semantic leader retention when lexical arm dominates.
3. Graph arm leader retention in tri-arm / graph-hybrid settings.
4. Provenance flag propagation (is_arm_anchor, anchored_arm) on Retrieved and Candidate.
5. Post-reranking leader retention and score preservation.
6. Prometheus counter increment (docscout_arm_leaders_anchored_total).
7. Pure Python list surgery execution latency overhead <= 0.05 ms.
8. RetrievalConfig sync between anchor_arm_top1 and anchor_arm_leaders.
9. Input validation and error fallback.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.api.metrics import ARM_LEADERS_ANCHORED_TOTAL
from app.retrieval import SERVING_CONFIG, RetrievalConfig, anchor_arm_leaders
from app.retrieval.rerank import Candidate
from app.retrieval.search import _anchor_arm_leaders
from app.retrieval.types import Retrieved


def test_candidate_validation_rules() -> None:
    """Input validation enforces k >= 1 and non-empty candidate list."""
    cand = Candidate(chunk_id="c1", text="some text")
    with pytest.raises(ValueError, match="k must be >= 1"):
        anchor_arm_leaders([cand], {"lexical": cand}, k=0)

    with pytest.raises(ValueError, match="candidates must not be empty"):
        anchor_arm_leaders([], {"lexical": cand}, k=5)


def test_candidate_anchoring_preserves_missing_arm_leader() -> None:
    """When an arm leader is missing from top-k, it is anchored with provenance flags."""
    cands = [
        Candidate(chunk_id=f"dense_{i}", text=f"text {i}", score=1.0 - (i * 0.1)) for i in range(10)
    ]
    lexical_leader = Candidate(
        chunk_id="circular_DOR_2023_24",
        text="RBI Circular DOR.CRE.REC.No. 60/08.12.001/2023-24",
        score=0.05,
        arm_ranks={"lexical": 1},
    )

    before_count = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="lexical")._value.get()
    anchored = anchor_arm_leaders(cands, {"lexical": lexical_leader}, k=5)
    after_count = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="lexical")._value.get()

    assert len(anchored) == 5
    assert after_count == before_count + 1

    # Missing arm leader is anchored at the tail, displacing candidate 4
    ids = [c.chunk_id for c in anchored]
    assert "circular_DOR_2023_24" in ids
    assert ids == ["dense_0", "dense_1", "dense_2", "dense_3", "circular_DOR_2023_24"]

    rescued = next(c for c in anchored if c.chunk_id == "circular_DOR_2023_24")
    assert rescued.is_arm_anchor is True
    assert rescued.anchored_arm == "lexical"

    # Other items remain unanchored
    for c in anchored[:-1]:
        assert c.is_arm_anchor is False
        assert c.anchored_arm is None


def test_candidate_anchoring_noop_when_leader_already_in_top_k() -> None:
    """When an arm leader is naturally in top-k, it is preserved without re-anchoring."""
    cands = [
        Candidate(chunk_id=f"c_{i}", text=f"text {i}", score=1.0 - (i * 0.1)) for i in range(10)
    ]
    before_count = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="dense")._value.get()

    # dense leader is c_0, which is already rank 1
    anchored = anchor_arm_leaders(cands, {"dense": cands[0]}, k=5)
    after_count = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="dense")._value.get()

    assert len(anchored) == 5
    assert after_count == before_count
    assert [c.chunk_id for c in anchored] == [f"c_{i}" for i in range(5)]
    assert anchored[0].is_arm_anchor is False


def test_search_pipeline_tuple_anchoring() -> None:
    """Search pipeline tuple surgery preserves missing lexical and dense leaders."""
    top = [
        ("c1", 0.030, {"dense": 2, "lexical": 3}),
        ("c2", 0.028, {"dense": 3, "lexical": 2}),
        ("c3", 0.025, {"dense": 4, "lexical": 4}),
    ]
    fused = [
        ("c1", 0.030, {"dense": 2, "lexical": 3}),
        ("c2", 0.028, {"dense": 3, "lexical": 2}),
        ("c3", 0.025, {"dense": 4, "lexical": 4}),
        ("dense_top1", 0.020, {"dense": 1}),
        ("lexical_top1", 0.018, {"lexical": 1}),
    ]
    arms = {
        "dense": ["dense_top1", "c1", "c2"],
        "lexical": ["lexical_top1", "c2", "c1"],
    }
    anchored_out: dict[str, str] = {}
    before_dense = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="dense")._value.get()
    before_lex = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="lexical")._value.get()

    result = _anchor_arm_leaders(top, arms, fused, k_final=3, anchored_out=anchored_out)

    after_dense = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="dense")._value.get()
    after_lex = ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name="lexical")._value.get()

    assert len(result) == 3
    assert after_dense == before_dense + 1
    assert after_lex == before_lex + 1
    assert anchored_out == {"dense_top1": "dense", "lexical_top1": "lexical"}

    # Head is preserved, tail was evicted to seat both arm leaders
    result_ids = [cid for cid, _, _ in result]
    assert result_ids == ["c1", "dense_top1", "lexical_top1"]


def test_tri_arm_graph_hybrid_anchoring() -> None:
    """When graph-hybrid retrieval has a distinct graph leader, it is also anchored."""
    top = [("c1", 0.05, {}), ("c2", 0.04, {}), ("c3", 0.03, {})]
    fused = [
        ("c1", 0.05, {}),
        ("c2", 0.04, {}),
        ("c3", 0.03, {}),
        ("graph_leader", 0.02, {"graph": 1}),
    ]
    arms = {
        "dense": ["c1"],
        "lexical": ["c2"],
        "graph": ["graph_leader"],
    }
    anchored_out: dict[str, str] = {}
    result = _anchor_arm_leaders(top, arms, fused, k_final=3, anchored_out=anchored_out)

    assert len(result) == 3
    assert [cid for cid, _, _ in result] == ["c1", "c2", "graph_leader"]
    assert anchored_out == {"graph_leader": "graph"}


def test_duplicate_leaders_across_arms_do_not_duplicate_seat() -> None:
    """If dense and lexical arms agree on top-1, only one seat is reserved."""
    top = [("c2", 0.04, {}), ("c3", 0.03, {})]
    fused = [("c2", 0.04, {}), ("c3", 0.03, {}), ("unanimous_leader", 0.01, {})]
    arms = {
        "dense": ["unanimous_leader"],
        "lexical": ["unanimous_leader"],
    }
    result = _anchor_arm_leaders(top, arms, fused, k_final=2)
    assert len(result) == 2
    assert [cid for cid, _, _ in result] == ["c2", "unanimous_leader"]


def test_post_rerank_retention_with_cross_encoder_scores() -> None:
    """Reranked candidate scoring preserves arm leader with its genuine cross-encoder logit."""
    cands = [
        Candidate(chunk_id=f"c_{i}", text=f"text {i}", score=5.0 - (i * 0.5)) for i in range(10)
    ]
    lexical_leader = Candidate(
        chunk_id="statutory_circular_60",
        text="Exact statutory circular 60/08.12.001 text",
        score=-1.25,  # Low cross-encoder logit
        arm_ranks={"lexical": 1},
    )
    anchored = anchor_arm_leaders(cands, {"lexical": lexical_leader}, k=5)

    assert len(anchored) == 5
    rescued = anchored[-1]
    assert rescued.chunk_id == "statutory_circular_60"
    assert rescued.score == -1.25
    assert rescued.is_arm_anchor is True
    assert rescued.anchored_arm == "lexical"


def test_retrieval_config_sync_between_aliases() -> None:
    """RetrievalConfig synchronizes anchor_arm_top1 and anchor_arm_leaders."""
    cfg1 = RetrievalConfig(name="test1", mode="hybrid", anchor_arm_leaders=True)
    assert cfg1.anchor_arm_leaders is True
    assert cfg1.anchor_arm_top1 is True
    assert cfg1.as_dict()["anchor_arm_leaders"] is True
    assert cfg1.as_dict()["anchor_arm_top1"] is True

    cfg2 = RetrievalConfig(name="test2", mode="hybrid", anchor_arm_top1=True)
    assert cfg2.anchor_arm_leaders is True
    assert cfg2.anchor_arm_top1 is True

    cfg3 = RetrievalConfig(
        name="test3", mode="hybrid", anchor_arm_top1=False, anchor_arm_leaders=False
    )
    assert cfg3.anchor_arm_leaders is False
    assert cfg3.anchor_arm_top1 is False

    # SERVING_CONFIG default
    assert SERVING_CONFIG.anchor_arm_leaders is True
    assert SERVING_CONFIG.anchor_arm_top1 is True


def test_provenance_flag_retention_on_retrieved_model() -> None:
    """Retrieved dataclass cleanly exposes is_arm_anchor and anchored_arm."""
    r1 = Retrieved(
        chunk_id="c1",
        rank=1,
        score=0.9,
        document_id="d1",
        source="RBI",
        text="content",
        is_arm_anchor=True,
        anchored_arm="lexical",
    )
    assert r1.is_arm_anchor is True
    assert r1.anchored_arm == "lexical"

    r2 = Retrieved(
        chunk_id="c2",
        rank=2,
        score=0.8,
        document_id="d1",
        source="RBI",
        text="content",
    )
    assert r2.is_arm_anchor is False
    assert r2.anchored_arm is None


def test_latency_overhead_budget() -> None:
    """Execution overhead of anchor_arm_leaders must be <= 0.05 ms (50 microseconds)."""
    cands = [
        Candidate(chunk_id=f"c_{i}", text=f"text {i}", score=1.0 - (i * 0.05)) for i in range(20)
    ]
    leaders = {
        "dense": Candidate(chunk_id="dense_leader", text="dense text", score=0.2),
        "lexical": Candidate(chunk_id="lexical_leader", text="lex text", score=0.1),
    }

    # Warmup
    for _ in range(50):
        anchor_arm_leaders(cands, leaders, k=10)

    iterations = 1000
    start = time.perf_counter()
    for _ in range(iterations):
        anchor_arm_leaders(cands, leaders, k=10)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    mean_latency_ms = elapsed_ms / iterations

    assert mean_latency_ms <= 0.05, f"Overhead {mean_latency_ms:.5f} ms exceeds 0.05 ms limit"


def test_fallback_on_corrupt_state() -> None:
    """Unexpected exception in anchoring falls back safely to returning top-k unanchored."""
    corrupted_top: list[Any] = [("valid", 0.5, {})]
    # arms having invalid type that would break attribute lookup
    res = _anchor_arm_leaders(corrupted_top, arms=12345, fused=corrupted_top, k_final=1)
    assert res == corrupted_top
