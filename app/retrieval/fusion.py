"""Reciprocal Rank Fusion.

Why RRF rather than normalising and adding the arms' scores: BM25 scores are unbounded and
corpus-dependent while cosine similarity lives in [-1, 1]. Any score-level combination
needs a normalisation that is itself a tuned, corpus-specific choice, and min-max
normalisation in particular is dominated by whichever arm happens to produce the largest
spread on that query. RRF uses only ranks, so it needs no normalisation and cannot be
destabilised by one arm's score distribution shifting.

The cost of that, stated plainly: RRF throws away margin. An arm that is certain of its
top hit contributes exactly as much as one that barely preferred it. On this corpus that
loss is acceptable -- it is measured in the ADR-0006 ablation rather than assumed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def reciprocal_rank_fusion(
    arms: Mapping[str, Sequence[str]],
    *,
    weights: Mapping[str, float] | None = None,
    rrf_k: int = 60,
) -> list[tuple[str, float, dict[str, int]]]:
    """Fuse ranked id lists into one ranking.

    Returns (chunk_id, fused_score, {arm: rank}) ordered best first. Ranks are 1-based.
    Ties are broken by chunk_id so that two runs of the same configuration on the same
    data produce byte-identical output -- a report that reshuffles between runs cannot
    support a 1pp regression gate.
    """
    weights = weights or {}
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for arm, ids in arms.items():
        weight = weights.get(arm, 1.0)
        for index, chunk_id in enumerate(ids):
            rank = index + 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (rrf_k + rank)
            ranks.setdefault(chunk_id, {})[arm] = rank
    fused = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(cid, score, ranks[cid]) for cid, score in fused]
