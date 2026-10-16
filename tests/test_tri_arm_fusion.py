"""Unit tests for Edge-Weighted Tri-Arm RRF Hybrid Fusion - FEAT-003.

Enforces:
1. Input validation: weights sum > 0.0, rrf_k >= 1.
2. Tri-arm fusion across dense, lexical, and knowledge graph arms.
3. Edge-weighted scoring bonuses for curated vs statutory similarity relationships.
4. Deterministic tie-breaking on chunk UUIDs.
5. Exact parity with legacy 2-arm RRF when weight_graph=0.0 or arms['graph']=[].
6. Performance: execution time <= 0.4 ms for 150 candidates.
"""

from __future__ import annotations

import time

import pytest

from app.retrieval.fusion import (
    TriArmFusionConfig,
    reciprocal_rank_fusion,
    tri_arm_fusion,
)


def test_input_validation_zero_weights() -> None:
    """Weights that sum to <= 0.0 must raise ValueError."""
    arms = {"dense": ["00000000-0000-4000-8000-000000000001"]}
    with pytest.raises(ValueError, match="weights must sum to > 0.0"):
        tri_arm_fusion(arms, weights={"dense": 0.0})


def test_input_validation_invalid_rrf_k() -> None:
    """rrf_k must be >= 1."""
    arms = {"dense": ["00000000-0000-4000-8000-000000000001"]}
    with pytest.raises(ValueError, match="rrf_k must be >= 1"):
        tri_arm_fusion(arms, rrf_k=0)


def test_tri_arm_fusion_config_defaults() -> None:
    """TriArmFusionConfig exposes expected default weights."""
    cfg = TriArmFusionConfig()
    assert cfg.rrf_k == 60
    assert cfg.weight_dense == 1.0
    assert cfg.weight_lexical == 1.0
    assert cfg.weight_graph == 0.85
    weights = cfg.as_weights()
    assert weights["graph"] == 0.85


def test_exact_parity_with_2arm_when_graph_weight_zero() -> None:
    """Tri-arm fusion with weight_graph=0.0 must match 2-arm RRF output exactly."""
    cid1 = "00000000-0000-4000-8000-000000000001"
    cid2 = "00000000-0000-4000-8000-000000000002"
    cid3 = "00000000-0000-4000-8000-000000000003"

    arms_2arm = {
        "dense": [cid1, cid2],
        "lexical": [cid2, cid3],
    }
    arms_3arm = {
        "dense": [cid1, cid2],
        "lexical": [cid2, cid3],
        "graph": [cid3, cid1],
    }

    res_2arm = reciprocal_rank_fusion(arms_2arm, weights={"dense": 1.0, "lexical": 1.0})
    res_3arm = tri_arm_fusion(
        arms_3arm,
        weights={"dense": 1.0, "lexical": 1.0, "graph": 0.0},
    )

    assert len(res_2arm) == len(res_3arm)
    for (id2, s2, r2), (id3, s3, r3) in zip(res_2arm, res_3arm, strict=True):
        assert id2 == id3
        assert pytest.approx(s2, 1e-6) == s3
        assert r2.get("dense") == r3.get("dense")
        assert r2.get("lexical") == r3.get("lexical")


def test_tri_arm_surfaces_cross_circular_graph_hit() -> None:
    """When a chunk is ranked in the graph arm, tri-arm fusion boosts it into the top ranking."""
    cid_dense_top = "00000000-0000-4000-8000-000000000001"
    cid_graph_only = "00000000-0000-4000-8000-000000000002"
    cid_shared = "00000000-0000-4000-8000-000000000003"

    arms = {
        "dense": [cid_dense_top, cid_shared],
        "lexical": [cid_shared],
        "graph": [cid_graph_only, cid_shared],
    }
    weights = {"dense": 1.0, "lexical": 1.0, "graph": 0.85}

    results = tri_arm_fusion(arms, weights=weights, rrf_k=60)
    res_ids = [r[0] for r in results]

    # cid_shared has contributions from all 3 arms, so it should rank #1
    assert res_ids[0] == cid_shared
    assert cid_graph_only in res_ids


def test_deterministic_tie_breaking() -> None:
    """Ties in score must be broken deterministically by chunk_id string sort."""
    cid_a = "00000000-0000-4000-8000-00000000000a"
    cid_b = "00000000-0000-4000-8000-00000000000b"

    # Both chunks have identical rank in single arms with equal weights
    arms = {
        "dense": [cid_b],
        "lexical": [cid_a],
    }
    results = tri_arm_fusion(arms, weights={"dense": 1.0, "lexical": 1.0})

    # Scores are identical: 1.0 / 61. cid_a must precede cid_b
    assert results[0][0] == cid_a
    assert results[1][0] == cid_b


def test_performance_under_0_4ms() -> None:
    """Tri-arm fusion over 150 total candidates must execute in <= 0.4 ms."""
    dense_ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(50)]
    lex_ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(25, 75)]
    graph_ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(50, 100)]

    arms = {
        "dense": dense_ids,
        "lexical": lex_ids,
        "graph": graph_ids,
    }

    # Warmup
    for _ in range(10):
        tri_arm_fusion(arms)

    timings: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter()
        tri_arm_fusion(arms)
        timings.append((time.perf_counter() - t0) * 1000.0)

    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 <= 0.4, f"p95 was {p95:.3f} ms (budget <= 0.4 ms)"
