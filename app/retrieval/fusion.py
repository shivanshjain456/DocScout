"""Reciprocal Rank Fusion and Edge-Weighted Tri-Arm Fusion (FEAT-003).

Fuses ranked id lists across Dense, Lexical, and Knowledge Graph arms into one
unified ranking. Ties are broken deterministically by chunk_id string sort to
ensure byte-identical outputs across runs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import structlog

from app.api.metrics import TRI_ARM_FUSIONS

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TriArmFusionConfig:
    """Configuration for Edge-Weighted Tri-Arm Reciprocal Rank Fusion."""

    rrf_k: int = 60
    weight_dense: float = 1.0
    weight_lexical: float = 1.0
    weight_graph: float = 0.85

    def as_weights(self) -> dict[str, float]:
        return {
            "dense": self.weight_dense,
            "lexical": self.weight_lexical,
            "graph": self.weight_graph,
        }


def tri_arm_fusion(
    arms: Mapping[str, Sequence[str | tuple[str, float]]],
    *,
    weights: Mapping[str, float] | None = None,
    rrf_k: int = 60,
) -> list[tuple[str, float, dict[str, int]]]:
    """Fuse candidates across Dense, Lexical, and Graph arms with edge-weighted scoring.

    Input validation:
    - rrf_k must be >= 1
    - weights must sum to > 0.0 if specified
    """
    if rrf_k < 1:
        raise ValueError(f"rrf_k must be >= 1, got {rrf_k}")

    if weights is not None:
        total_weight = sum(weights.values())
        if total_weight <= 0.0:
            raise ValueError(f"weights must sum to > 0.0, got {total_weight}")

    TRI_ARM_FUSIONS.inc()
    weights_map = weights or {}
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}

    for arm, items in arms.items():
        weight = weights_map.get(arm, 1.0)
        if weight <= 0.0:
            continue

        for index, item in enumerate(items):
            rank = index + 1
            chunk_id = item[0] if isinstance(item, (tuple, list)) else item
            edge_bonus = 1.0
            if (
                isinstance(item, (tuple, list))
                and len(item) > 1
                and isinstance(item[1], (int, float))
            ):
                # If explicit proximity score is present in the arm tuple
                edge_bonus = 1.0 + (float(item[1]) * 0.1)

            scores[chunk_id] = scores.get(chunk_id, 0.0) + (weight * edge_bonus) / (rrf_k + rank)
            ranks.setdefault(chunk_id, {})[arm] = rank

    # Deterministic tie-breaking on chunk_id string
    fused = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(cid, score, ranks[cid]) for cid, score in fused]


def reciprocal_rank_fusion(
    arms: Mapping[str, Sequence[str | tuple[str, float]]],
    *,
    weights: Mapping[str, float] | None = None,
    rrf_k: int = 60,
) -> list[tuple[str, float, dict[str, int]]]:
    """Backwards-compatible alias for reciprocal rank fusion."""
    weights_map = weights or {}
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}

    for arm, items in arms.items():
        weight = weights_map.get(arm, 1.0)
        if weight <= 0.0:
            continue

        for index, item in enumerate(items):
            rank = index + 1
            chunk_id = item[0] if isinstance(item, (tuple, list)) else item
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (rrf_k + rank)
            ranks.setdefault(chunk_id, {})[arm] = rank

    fused = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(cid, score, ranks[cid]) for cid, score in fused]
