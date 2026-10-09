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
from typing import Any


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


@dataclass(frozen=True)
class KappaResult:
    """Inter-rater agreement with Cohen's kappa and rare-class breakdown.

    Implements EVAL_PROTOCOL.md E-11: 'Agreement alone lies... kappa MUST be reported
    alongside agreement, together with per-class agreement on the rare class.'
    """

    n: int
    observed_agreement: float
    expected_agreement: float
    kappa: float
    std_error: float
    ci_low: float
    ci_high: float
    confusion_matrix: dict[str, int]
    rare_class_precision: float
    rare_class_recall: float
    rare_class_f1: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "observed_agreement": round(self.observed_agreement, 4),
            "expected_agreement": round(self.expected_agreement, 4),
            "kappa": round(self.kappa, 4),
            "std_error": round(self.std_error, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "confusion_matrix": self.confusion_matrix,
            "rare_class_precision": round(self.rare_class_precision, 4),
            "rare_class_recall": round(self.rare_class_recall, 4),
            "rare_class_f1": round(self.rare_class_f1, 4),
        }


def cohens_kappa(
    rater_a: Sequence[bool | int],
    rater_b: Sequence[bool | int],
) -> KappaResult:
    """Calculate Cohen's kappa and agreement statistics between two raters on binary labels."""
    import math

    if len(rater_a) != len(rater_b):
        raise ValueError(f"rater lengths differ: {len(rater_a)} vs {len(rater_b)}")
    n = len(rater_a)
    if n == 0:
        raise ValueError("cannot compute kappa on empty sequences")

    # Binarize
    a_bin = [bool(x) for x in rater_a]
    b_bin = [bool(x) for x in rater_b]

    # Confusion counts where 1 is positive and 0 is negative
    tp = sum(1 for a, b in zip(a_bin, b_bin, strict=True) if a and b)
    fp = sum(1 for a, b in zip(a_bin, b_bin, strict=True) if a and not b)
    fn = sum(1 for a, b in zip(a_bin, b_bin, strict=True) if not a and b)
    tn = sum(1 for a, b in zip(a_bin, b_bin, strict=True) if not a and not b)

    p_o = (tp + tn) / n
    p_a1 = (tp + fp) / n
    p_a0 = (fn + tn) / n
    p_b1 = (tp + fn) / n
    p_b0 = (fp + tn) / n
    p_e = (p_a1 * p_b1) + (p_a0 * p_b0)

    if math.isclose(p_e, 1.0, abs_tol=1e-9):
        kappa = 1.0 if math.isclose(p_o, 1.0, abs_tol=1e-9) else 0.0
        se = 0.0
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)
        denom = n * ((1.0 - p_e) ** 2)
        se = math.sqrt(p_o * (1.0 - p_o) / denom) if denom > 0 else 0.0

    ci_low = max(-1.0, kappa - 1.96 * se)
    ci_high = min(1.0, kappa + 1.96 * se)

    # Rare class is usually class 0 (unfaithful / invalid) in high-quality systems
    # For class 0: True Positives = tn, False Positives = fn, False Negatives = fp
    rare_prec = tn / (tn + fn) if (tn + fn) > 0 else 0.0
    rare_rec = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    rare_f1 = (
        (2 * rare_prec * rare_rec) / (rare_prec + rare_rec) if (rare_prec + rare_rec) > 0 else 0.0
    )

    return KappaResult(
        n=n,
        observed_agreement=p_o,
        expected_agreement=p_e,
        kappa=kappa,
        std_error=se,
        ci_low=ci_low,
        ci_high=ci_high,
        confusion_matrix={"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        rare_class_precision=rare_prec,
        rare_class_recall=rare_rec,
        rare_class_f1=rare_f1,
    )
