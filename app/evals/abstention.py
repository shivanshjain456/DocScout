"""Scoring whether the system knows when the corpus cannot answer.

The gold set has 153 items, of which 22 (14.4%) are unanswerable. Until now every one of
them was excluded from every metric: `runner.py` filtered them out because the retrieval
scorers measure citation coverage and an unanswerable item has no citations to cover. The
consequence was that a seventh of the hand-built gold set did no work.

These items are the expensive ones. Each was written so the corpus *nearly* answers it --
the unanswerable_reason fields say so explicitly, e.g. "the nine-month figure retrieves
strongly" and "the deadline text retrieves strongly, which is what makes the question
dangerous". A question whose topic is absent is easy to refuse; a question whose topic is
present and whose *answer* is absent is the one that produces a confident wrong citation.

Metrics follow the abstention literature rather than being invented here: refusal rate,
false rejection rate, and selective accuracy, plus the precision of the refusals
themselves, which is what tells you whether a flag is worth showing a user.

Nothing here calls a model. Coverage is computed from the same Postgres lexemes the BM25
arm indexes, so this runs in the same seconds-long loop as the rest of the harness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AbstentionScore:
    """Outcome of applying one coverage threshold to the whole gold set."""

    threshold: float
    answerable: int
    unanswerable: int
    #: Unanswerable questions correctly flagged. True positives.
    correct_refusals: int
    #: Answerable questions wrongly flagged. False positives -- the cost side.
    false_refusals: int

    @property
    def refusal_rate(self) -> float:
        """Share of all questions flagged. Compared against the 14.4% that should be."""
        total = self.answerable + self.unanswerable
        return (self.correct_refusals + self.false_refusals) / total if total else 0.0

    @property
    def abstention_recall(self) -> float:
        """Share of unanswerable questions caught."""
        return self.correct_refusals / self.unanswerable if self.unanswerable else 0.0

    @property
    def false_rejection_rate(self) -> float:
        """Share of answerable questions wrongly flagged. The over-refusal failure mode."""
        return self.false_refusals / self.answerable if self.answerable else 0.0

    @property
    def refusal_precision(self) -> float:
        """Of the questions flagged, how many deserved it.

        The number that decides whether a flag is worth surfacing: a flag that is wrong
        more often than right trains users to ignore it.
        """
        flagged = self.correct_refusals + self.false_refusals
        return self.correct_refusals / flagged if flagged else 0.0

    @property
    def selective_accuracy(self) -> float:
        """Share of questions handled correctly: answered when answerable, flagged when not."""
        total = self.answerable + self.unanswerable
        correct = self.correct_refusals + (self.answerable - self.false_refusals)
        return correct / total if total else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "threshold": self.threshold,
            "answerable": self.answerable,
            "unanswerable": self.unanswerable,
            "correct_refusals": self.correct_refusals,
            "false_refusals": self.false_refusals,
            "refusal_rate": round(self.refusal_rate, 4),
            "abstention_recall": round(self.abstention_recall, 4),
            "false_rejection_rate": round(self.false_rejection_rate, 4),
            "refusal_precision": round(self.refusal_precision, 4),
            "selective_accuracy": round(self.selective_accuracy, 4),
        }


def score_at_threshold(
    answerable_coverage: Sequence[float],
    unanswerable_coverage: Sequence[float],
    threshold: float,
) -> AbstentionScore:
    """Apply one threshold: a question is flagged when its coverage falls below it."""
    return AbstentionScore(
        threshold=threshold,
        answerable=len(answerable_coverage),
        unanswerable=len(unanswerable_coverage),
        correct_refusals=sum(1 for c in unanswerable_coverage if c < threshold),
        false_refusals=sum(1 for c in answerable_coverage if c < threshold),
    )


def separation_auc(
    answerable_coverage: Sequence[float], unanswerable_coverage: Sequence[float]
) -> float:
    """Probability that a random answerable question scores above a random unanswerable one.

    Threshold-free, which is the point: it says whether the signal carries information at
    all before anyone argues about where to put the cut. 0.5 is chance. Ties count half,
    so a constant signal -- which is what the RRF score turned out to be -- scores exactly
    0.5 rather than appearing to work.
    """
    if not answerable_coverage or not unanswerable_coverage:
        return 0.0
    wins = ties = 0
    for a in answerable_coverage:
        for u in unanswerable_coverage:
            if a > u:
                wins += 1
            elif a == u:
                ties += 1
    return (wins + 0.5 * ties) / (len(answerable_coverage) * len(unanswerable_coverage))


def sweep(
    answerable_coverage: Sequence[float],
    unanswerable_coverage: Sequence[float],
    thresholds: Sequence[float],
) -> list[AbstentionScore]:
    """Score every threshold, so the operating point is chosen from a curve, not asserted."""
    return [
        score_at_threshold(answerable_coverage, unanswerable_coverage, t)
        for t in sorted(thresholds)
    ]
