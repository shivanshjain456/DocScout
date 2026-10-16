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
from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True)
class AbstentionGateConfig:
    """Configuration schema for refusal precision and selective accuracy gate (FEAT-086)."""

    min_selective_accuracy: float = 0.95
    min_refusal_precision: float = 0.98
    max_false_rejection_rate: float = 0.03

    def __post_init__(self) -> None:
        if not (0.0 <= self.min_selective_accuracy <= 1.0):
            raise ValueError(
                f"min_selective_accuracy must be in [0.0, 1.0], got {self.min_selective_accuracy}"
            )
        if not (0.0 <= self.min_refusal_precision <= 1.0):
            raise ValueError(
                f"min_refusal_precision must be in [0.0, 1.0], got {self.min_refusal_precision}"
            )
        if not (0.0 <= self.max_false_rejection_rate <= 1.0):
            raise ValueError(
                f"max_false_rejection_rate must be in [0.0, 1.0], got {self.max_false_rejection_rate}"
            )


@dataclass(frozen=True)
class AbstentionGateResult:
    """Evaluation output schema for selective accuracy and refusal precision (FEAT-086)."""

    selective_accuracy: float
    refusal_precision: float
    false_rejection_rate: float
    gate_passed: bool
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "selective_accuracy": round(self.selective_accuracy, 4),
            "refusal_precision": round(self.refusal_precision, 4),
            "false_rejection_rate": round(self.false_rejection_rate, 4),
            "gate_passed": self.gate_passed,
            "details": dict(self.details),
        }


def evaluate_query_subset_abstention(
    items: Sequence[dict[str, Any]],
    config: AbstentionGateConfig | None = None,
) -> AbstentionGateResult:
    """Evaluate refusal precision and selective accuracy over query outcome items.

    Each item must contain:
    - 'is_unanswerable' (bool) or 'answerable' (bool)
    - 'is_refused' (bool)
    - 'is_correct' (bool) for answered items
    """
    cfg = config or AbstentionGateConfig()
    total_unanswerable = 0
    total_answerable = 0
    correct_refusals = 0
    false_refusals = 0
    correct_answered = 0

    for item in items:
        unanswerable = bool(item.get("is_unanswerable", not item.get("answerable", True)))
        refused = bool(item.get("is_refused", False))
        correct = bool(item.get("is_correct", False))

        if unanswerable:
            total_unanswerable += 1
            if refused:
                correct_refusals += 1
        else:
            total_answerable += 1
            if refused:
                false_refusals += 1
            else:
                if correct:
                    correct_answered += 1

    total_refused = correct_refusals + false_refusals
    total_answered = total_answerable - false_refusals

    refusal_precision = correct_refusals / total_refused if total_refused > 0 else 1.0
    selective_accuracy = correct_answered / total_answered if total_answered > 0 else 1.0
    false_rejection_rate = false_refusals / total_answerable if total_answerable > 0 else 0.0

    passed = (
        selective_accuracy >= cfg.min_selective_accuracy
        and refusal_precision >= cfg.min_refusal_precision
        and false_rejection_rate <= cfg.max_false_rejection_rate
    )

    details = {
        "total_items": len(items),
        "total_answerable": total_answerable,
        "total_unanswerable": total_unanswerable,
        "correct_refusals": correct_refusals,
        "false_refusals": false_refusals,
        "correct_answered": correct_answered,
        "total_answered": total_answered,
        "total_refused": total_refused,
    }

    return AbstentionGateResult(
        selective_accuracy=selective_accuracy,
        refusal_precision=refusal_precision,
        false_rejection_rate=false_rejection_rate,
        gate_passed=passed,
        details=details,
    )


def evaluate_abstention_gate(
    abstention_data: dict[str, Any] | AbstentionScore,
    config: AbstentionGateConfig | None = None,
) -> AbstentionGateResult:
    """Evaluate CI abstention gate over benchmark results JSON or AbstentionScore."""
    cfg = config or AbstentionGateConfig()

    if isinstance(abstention_data, AbstentionScore):
        sel_acc = abstention_data.selective_accuracy
        ref_prec = abstention_data.refusal_precision
        frr = abstention_data.false_rejection_rate
        passed = (
            sel_acc >= cfg.min_selective_accuracy
            and ref_prec >= cfg.min_refusal_precision
            and frr <= cfg.max_false_rejection_rate
        )
        return AbstentionGateResult(
            selective_accuracy=sel_acc,
            refusal_precision=ref_prec,
            false_rejection_rate=frr,
            gate_passed=passed,
            details=abstention_data.as_dict(),
        )

    # If full items list is present
    items = abstention_data.get("items")
    if items and isinstance(items, list) and len(items) > 0 and "is_refused" in items[0]:
        return evaluate_query_subset_abstention(items, cfg)

    shipped = abstention_data.get("at_shipped_threshold", abstention_data)
    sel_acc = float(shipped.get("selective_accuracy", 0.0))
    ref_prec = float(shipped.get("refusal_precision", 0.0))
    frr = float(shipped.get("false_rejection_rate", 0.0))

    passed = (
        sel_acc >= cfg.min_selective_accuracy
        and ref_prec >= cfg.min_refusal_precision
        and frr <= cfg.max_false_rejection_rate
    )

    details = dict(shipped)
    if not passed and "items" not in abstention_data:
        details["legacy_baseline"] = True

    return AbstentionGateResult(
        selective_accuracy=sel_acc,
        refusal_precision=ref_prec,
        false_rejection_rate=frr,
        gate_passed=passed,
        details=details,
    )
