"""Deterministic retrieval scorers.

These run before any LLM judge, and nothing here calls a model. That ordering is a
requirement, not a preference: a judge is itself a measuring instrument with unknown
error, and calibrating one against a system whose retrieval quality is unmeasured leaves
two unknowns and one equation. Every number in this module is a pure function of
(ranked chunk ids, gold citation groups) and is reproducible without a network.

The relevance model, stated once and used everywhere
----------------------------------------------------
Each answerable gold item carries one GROUP of acceptable chunk ids per evidence quote
(see goldset.resolve_groups). Within a group the ids are alternatives -- ADR-0003's 150
character overlap means a boundary-adjacent quote genuinely lives in two adjacent chunks,
and citing either is correct. Across groups they are obligations -- a multi-hop item
quoting two documents is not answered by finding one of them.

So: disjunction within a group, conjunction across groups. Recall@k is the fraction of
GROUPS covered by the top k, never the fraction of ids. Scoring ids directly would charge
a retriever 0.5 for returning the one perfectly correct chunk, which is not a measurement
of anything.

Unanswerable items have no groups and are excluded from every retrieval metric here, with
the count reported. They measure abstention, which is a generation property; silently
averaging them in as zeros -- or as ones -- would move the headline number by the share of
unanswerable items (14.4% of this gold set) for reasons unrelated to retrieval.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ItemScore:
    """Per-item metrics. Kept per item so the report can show what failed, not just a mean."""

    item_id: str
    n_groups: int
    groups_covered: int
    recall: float
    hit: bool
    mrr: float
    ndcg: float
    first_relevant_rank: int | None
    missed_groups: list[list[str]] = field(default_factory=list)


def _relevant_ids(groups: Sequence[Sequence[str]]) -> set[str]:
    return {cid for group in groups for cid in group}


def recall_at_k(groups: Sequence[Sequence[str]], ranked: Sequence[str], k: int) -> float:
    """Fraction of quote groups with at least one member in the top k."""
    if not groups:
        return 0.0
    top = set(ranked[:k])
    covered = sum(1 for group in groups if top.intersection(group))
    return covered / len(groups)


def hit_at_k(groups: Sequence[Sequence[str]], ranked: Sequence[str], k: int) -> bool:
    """True when the top k covers at least one group. The weakest useful signal."""
    if not groups:
        return False
    top = set(ranked[:k])
    return any(top.intersection(group) for group in groups)


def reciprocal_rank(groups: Sequence[Sequence[str]], ranked: Sequence[str]) -> float:
    """1 / rank of the first relevant chunk, 0 if none is retrieved."""
    relevant = _relevant_ids(groups)
    for index, chunk_id in enumerate(ranked):
        if chunk_id in relevant:
            return 1.0 / (index + 1)
    return 0.0


def ndcg_at_k(groups: Sequence[Sequence[str]], ranked: Sequence[str], k: int) -> float:
    """Binary-gain nDCG@k under the group model.

    A retrieved chunk earns gain 1 the first time its GROUP is seen and 0 afterwards.
    Counting both members of an overlapping pair would let a retriever inflate nDCG by
    returning two copies of the same evidence, which is the opposite of what the metric
    should reward. The ideal ranking therefore places min(len(groups), k) relevant chunks
    in the first positions.
    """
    if not groups:
        return 0.0
    seen: set[int] = set()
    dcg = 0.0
    for index, chunk_id in enumerate(ranked[:k]):
        for g_index, group in enumerate(groups):
            if g_index not in seen and chunk_id in group:
                seen.add(g_index)
                dcg += 1.0 / math.log2(index + 2)
                break
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(groups), k)))
    return dcg / ideal if ideal > 0 else 0.0


def score_item(
    item_id: str,
    groups: Sequence[Sequence[str]],
    ranked: Sequence[str],
    k: int,
) -> ItemScore:
    """All retrieval metrics for one answerable item at cutoff k."""
    top = set(ranked[:k])
    missed = [list(group) for group in groups if not top.intersection(group)]
    relevant = _relevant_ids(groups)
    first = next((i + 1 for i, c in enumerate(ranked) if c in relevant), None)
    return ItemScore(
        item_id=item_id,
        n_groups=len(groups),
        groups_covered=len(groups) - len(missed),
        recall=recall_at_k(groups, ranked, k),
        hit=hit_at_k(groups, ranked, k),
        mrr=reciprocal_rank(groups, ranked),
        ndcg=ndcg_at_k(groups, ranked, k),
        first_relevant_rank=first,
        missed_groups=missed,
    )


@dataclass(frozen=True)
class Aggregate:
    """Corpus-level means. `n` is always reported beside them."""

    n: int
    recall: float
    hit_rate: float
    mrr: float
    ndcg: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "recall": round(self.recall, 4),
            "hit_rate": round(self.hit_rate, 4),
            "mrr": round(self.mrr, 4),
            "ndcg": round(self.ndcg, 4),
        }


def aggregate(scores: Sequence[ItemScore]) -> Aggregate:
    """Macro-average over items.

    Macro, not micro: micro-averaging over groups would weight a 3-quote multi-hop item
    three times as heavily as a single-quote extractive one, so the headline number would
    drift whenever the gold set's composition changed rather than when the system did.
    """
    n = len(scores)
    if n == 0:
        return Aggregate(0, 0.0, 0.0, 0.0, 0.0)
    return Aggregate(
        n=n,
        recall=sum(s.recall for s in scores) / n,
        hit_rate=sum(1 for s in scores if s.hit) / n,
        mrr=sum(s.mrr for s in scores) / n,
        ndcg=sum(s.ndcg for s in scores) / n,
    )
