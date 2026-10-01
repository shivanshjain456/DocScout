"""Tests for the deterministic retrieval scorers.

These are the measuring instrument. If they are wrong, every number in every report is
wrong in the same direction and nothing downstream will notice, so they are tested against
hand-computed values rather than against their own output.
"""

from __future__ import annotations

import math

import pytest

from app.evals import scorers, stats


# --- the group model: disjunction within, conjunction across -----------------------------
def test_overlapping_chunks_in_one_group_count_once() -> None:
    """ADR-0003's overlap puts a boundary quote in two chunks; either citation is correct.

    Scoring the flat id list would give 0.5 here for a perfect answer. That regression is
    the reason resolve_groups exists, so it is pinned.
    """
    groups = [["a", "b"]]  # one quote, two acceptable chunks
    assert scorers.recall_at_k(groups, ["a"], 5) == 1.0
    assert scorers.recall_at_k(groups, ["b"], 5) == 1.0
    # Returning both does not earn extra credit.
    assert scorers.recall_at_k(groups, ["a", "b"], 5) == 1.0


def test_separate_groups_are_obligations_not_alternatives() -> None:
    groups = [["a"], ["b"]]  # multi-hop: two quotes, two documents
    assert scorers.recall_at_k(groups, ["a"], 5) == 0.5
    assert scorers.recall_at_k(groups, ["a", "b"], 5) == 1.0
    assert scorers.hit_at_k(groups, ["a"], 5) is True  # hit is deliberately weaker


def test_cutoff_is_respected() -> None:
    groups = [["a"]]
    ranked = ["x", "y", "z", "a"]
    assert scorers.recall_at_k(groups, ranked, 3) == 0.0
    assert scorers.recall_at_k(groups, ranked, 4) == 1.0


# --- MRR ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("ranked", "expected"),
    [(["a"], 1.0), (["x", "a"], 0.5), (["x", "y", "a"], 1 / 3), (["x"], 0.0)],
)
def test_reciprocal_rank(ranked: list[str], expected: float) -> None:
    assert scorers.reciprocal_rank([["a"]], ranked) == pytest.approx(expected)


# --- nDCG --------------------------------------------------------------------------------
def test_ndcg_is_one_for_a_perfect_ranking() -> None:
    groups = [["a"], ["b"]]
    assert scorers.ndcg_at_k(groups, ["a", "b", "x"], 5) == pytest.approx(1.0)


def test_ndcg_hand_computed() -> None:
    """One group, retrieved at rank 2: DCG = 1/log2(3), ideal = 1/log2(2) = 1."""
    assert scorers.ndcg_at_k([["a"]], ["x", "a"], 5) == pytest.approx(1 / math.log2(3))


def test_ndcg_does_not_reward_duplicate_evidence() -> None:
    """Both members of an overlapping pair must not each earn gain.

    Without this, a retriever could inflate nDCG by returning two copies of the same
    evidence, which is the opposite of what the metric should reward.
    """
    one_group_twice = scorers.ndcg_at_k([["a", "b"]], ["a", "b"], 5)
    assert one_group_twice == pytest.approx(1.0)
    assert scorers.ndcg_at_k([["a", "b"]], ["a"], 5) == pytest.approx(one_group_twice)


# --- unanswerable items ------------------------------------------------------------------
def test_items_without_groups_score_zero_and_must_be_excluded_by_the_caller() -> None:
    """Unanswerable items have no groups; the scorers return 0 rather than guessing.

    The runner excludes them. This test documents that the exclusion is the caller's job
    and that a caller who forgets will see zeros, not silently inflated means.
    """
    assert scorers.recall_at_k([], ["a"], 5) == 0.0
    assert scorers.hit_at_k([], ["a"], 5) is False
    assert scorers.ndcg_at_k([], ["a"], 5) == 0.0


# --- aggregation -------------------------------------------------------------------------
def test_aggregate_is_macro_averaged_over_items() -> None:
    """A 3-group item must not outweigh a 1-group item three to one."""
    multi = scorers.score_item("m", [["a"], ["b"], ["c"]], ["a", "b", "c"], 10)  # recall 1.0
    single = scorers.score_item("s", [["z"]], ["q"], 10)  # recall 0.0
    assert scorers.aggregate([multi, single]).recall == pytest.approx(0.5)


def test_aggregate_of_nothing_is_zero_not_a_crash() -> None:
    assert scorers.aggregate([]).n == 0


def test_score_item_reports_what_was_missed() -> None:
    score = scorers.score_item("g-1", [["a"], ["b"]], ["a"], 5)
    assert score.missed_groups == [["b"]]
    assert score.groups_covered == 1
    assert score.first_relevant_rank == 1


# --- uncertainty -------------------------------------------------------------------------
def test_bootstrap_is_reproducible() -> None:
    """A confidence interval that moves when re-run is not evidence of anything."""
    a = [1.0, 0.0, 1.0, 1.0, 0.5] * 10
    b = [0.0, 0.0, 1.0, 0.5, 0.5] * 10
    first = stats.paired_bootstrap(a, b)
    second = stats.paired_bootstrap(a, b)
    assert first.as_dict() == second.as_dict()


def test_bootstrap_detects_no_difference_when_there_is_none() -> None:
    values = [1.0, 0.0, 0.5] * 20
    result = stats.paired_bootstrap(values, list(values))
    assert result.difference == 0.0
    assert result.excludes_zero is False


def test_bootstrap_flags_a_consistent_difference() -> None:
    a = [1.0] * 40
    b = [0.0] * 40
    result = stats.paired_bootstrap(a, b)
    assert result.difference == pytest.approx(1.0)
    assert result.excludes_zero is True


def test_bootstrap_rejects_unpaired_inputs() -> None:
    with pytest.raises(ValueError, match="same length"):
        stats.paired_bootstrap([1.0, 2.0], [1.0])


def test_mcnemar_counts_discordant_pairs_only() -> None:
    a = [True, True, False, False]
    b = [True, False, True, False]
    assert stats.mcnemar_counts(a, b) == (1, 1)
