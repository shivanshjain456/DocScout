"""Uncertainty for eval differences.

Why this module exists: the first baseline run put bm25-only 0.0039 recall@5 above
hybrid-rrf. On 131 items that is 0.5 items. Reported bare, it reads as "BM25 beats
hybrid" and would have justified deleting the dense arm. It is noise, and the harness
should be able to say so without a human remembering to divide by n every time.

The CI gate in EVAL_PROTOCOL fails a run that regresses more than 1pp against the mean of
the last three baselines. 1pp on this gold set is 1.3 items, so the gate is operating at
roughly the resolution of a single item. That is a property of a 131-item gold set, not
of the metric, and it is recorded here rather than discovered later.

Paired, not unpaired: both configurations answer the same questions, so the per-item
difference removes question difficulty from the comparison. An unpaired test on these
numbers would be both wrong and much less sensitive.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PairedDifference:
    """Difference between two configurations on the same items, with a bootstrap CI."""

    n: int
    mean_a: float
    mean_b: float
    difference: float
    ci_low: float
    ci_high: float
    # True when the interval excludes zero -- i.e. the sign of the difference survives
    # resampling. Deliberately not called "significant": this is a bootstrap interval on
    # one gold set, not a hypothesis test with a controlled family-wise error rate.
    excludes_zero: bool
    items_equivalent: float

    def as_dict(self) -> dict[str, float | int | bool]:
        return {
            "n": self.n,
            "mean_a": round(self.mean_a, 4),
            "mean_b": round(self.mean_b, 4),
            "difference": round(self.difference, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "excludes_zero": self.excludes_zero,
            "difference_in_items": round(self.items_equivalent, 2),
        }


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    iterations: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> PairedDifference:
    """Percentile bootstrap CI for mean(a) - mean(b) over paired observations.

    The seed is fixed and the iteration count is explicit so that two runs of the same
    report produce the same interval. A confidence interval that moves when you re-run it
    is not evidence of anything.
    """
    if len(a) != len(b):
        raise ValueError(f"paired inputs must be the same length, got {len(a)} and {len(b)}")
    n = len(a)
    if n == 0:
        return PairedDifference(0, 0.0, 0.0, 0.0, 0.0, 0.0, False, 0.0)

    deltas = [x - y for x, y in zip(a, b, strict=True)]
    observed = sum(deltas) / n

    # S311: flagged as unsuitable for cryptography, which is exactly right and not the use
    # here. A bootstrap must be reproducible, so a seeded Mersenne Twister is the correct
    # choice and a CSPRNG would make the published interval unverifiable.
    rng = random.Random(seed)  # noqa: S311
    samples: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += deltas[rng.randrange(n)]
        samples.append(total / n)
    samples.sort()

    tail = (1.0 - confidence) / 2.0
    low = samples[int(tail * iterations)]
    high = samples[min(iterations - 1, int((1.0 - tail) * iterations))]
    return PairedDifference(
        n=n,
        mean_a=sum(a) / n,
        mean_b=sum(b) / n,
        difference=observed,
        ci_low=low,
        ci_high=high,
        excludes_zero=(low > 0.0) or (high < 0.0),
        items_equivalent=observed * n,
    )


def mcnemar_counts(a_hits: Sequence[bool], b_hits: Sequence[bool]) -> tuple[int, int]:
    """Discordant pair counts: (a won and b lost, b won and a lost).

    Reported alongside the bootstrap because for a binary outcome the discordant pairs are
    the entire evidence, and "3 vs 1" communicates the sample size of the comparison far
    more honestly than a mean to three decimal places.
    """
    a_only = sum(1 for x, y in zip(a_hits, b_hits, strict=True) if x and not y)
    b_only = sum(1 for x, y in zip(a_hits, b_hits, strict=True) if y and not x)
    return a_only, b_only
