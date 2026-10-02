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


# --- gaps found by mutation testing -----------------------------------------------------
# Line coverage on this module was 99% and its mutation score was 83.7%: the suite executed
# almost every line while still failing to notice 25 deliberate behaviour changes. Each test
# below kills a specific surviving mutant, named in its docstring.
def test_empty_aggregate_reports_zero_for_every_metric() -> None:
    """Kills aggregate mutants 5-8, which returned None for each metric in turn.

    The previous test asserted only `.n == 0`, so replacing any of the four metric values
    with None went unnoticed. An eval report would then carry `"recall": null` for an
    empty slice and the gate would compare against it.
    """
    empty = scorers.aggregate([])
    assert empty.n == 0
    assert empty.recall == 0.0
    assert empty.hit_rate == 0.0
    assert empty.mrr == 0.0
    assert empty.ndcg == 0.0
    assert empty.as_dict() == {"n": 0, "recall": 0.0, "hit_rate": 0.0, "mrr": 0.0, "ndcg": 0.0}


def test_score_item_carries_its_identifier() -> None:
    """Kills score_item mutant 17 (`item_id=None`).

    The runner keys every per-item row in results.json by this field, so losing it would
    silently detach every score from the question that produced it.
    """
    assert scorers.score_item("g-042", [["a"]], ["a"], 5).item_id == "g-042"


def test_score_item_reports_the_hit_flag() -> None:
    """Kills score_item mutant 21 (`hit=None`), which no assertion previously covered."""
    assert scorers.score_item("g-1", [["a"]], ["a"], 5).hit is True
    assert scorers.score_item("g-2", [["a"]], ["z"], 5).hit is False


def test_score_item_applies_the_cutoff_to_recall() -> None:
    """Kills score_item mutant 38, which passed k=None into recall_at_k.

    `ranked[:None]` is the whole list, so the cutoff silently stopped applying. Every
    earlier test happened to use a k large enough that truncation made no difference,
    which is exactly the blind spot a mutation surfaces and line coverage cannot.
    """
    groups, ranked = [["a"]], ["x", "y", "z", "a"]
    assert scorers.score_item("g-1", groups, ranked, 3).recall == 0.0
    assert scorers.score_item("g-1", groups, ranked, 4).recall == 1.0


def test_mcnemar_rejects_unpaired_inputs() -> None:
    """Kills mcnemar mutants 6 and 9, which dropped `strict=True` from zip().

    Without it, zip silently truncates to the shorter sequence: two configurations scored
    over different numbers of items would be compared pairwise anyway, under-reporting the
    discordant pairs rather than failing.
    """
    with pytest.raises(ValueError):
        stats.mcnemar_counts([True, False, True], [True, False])


def test_bootstrap_confidence_level_widens_the_interval() -> None:
    """Kills the mutants that altered the tail calculation.

    No earlier test varied `confidence`, so changes to how the percentile bounds are
    derived produced an identical default-argument result and went undetected.
    """
    a = [1.0, 0.0] * 30
    b = [0.0, 0.0] * 30
    narrow = stats.paired_bootstrap(a, b, confidence=0.50)
    wide = stats.paired_bootstrap(a, b, confidence=0.99)
    assert (wide.ci_high - wide.ci_low) > (narrow.ci_high - narrow.ci_low)


def test_bootstrap_seed_changes_the_interval_but_not_the_observation() -> None:
    """Kills mutants that ignored or altered the seed.

    The observed difference is a property of the data and must not move; the interval is a
    property of the resampling and must.
    """
    a = [1.0, 0.0, 0.5] * 20
    b = [0.0, 0.5, 0.5] * 20
    first = stats.paired_bootstrap(a, b, seed=1)
    second = stats.paired_bootstrap(a, b, seed=2)
    assert first.difference == second.difference
    assert (first.ci_low, first.ci_high) != (second.ci_low, second.ci_high)


def test_bootstrap_iteration_count_is_honoured() -> None:
    """Kills mutants that changed the resample count.

    Fewer resamples give a coarser interval, so the bound lands on a different value. If
    nothing asserts this, `iterations` can be ignored entirely without any test noticing.
    """
    a = [1.0, 0.0, 1.0, 0.0, 1.0] * 8
    b = [0.0, 0.0, 1.0, 1.0, 0.0] * 8
    coarse = stats.paired_bootstrap(a, b, iterations=50)
    fine = stats.paired_bootstrap(a, b, iterations=5000)
    assert coarse.n == fine.n == len(a)
    assert (coarse.ci_low, coarse.ci_high) != (fine.ci_low, fine.ci_high)


def test_bootstrap_reports_both_means() -> None:
    """Kills the mutants that set mean_a/mean_b to None or swapped them."""
    a = [1.0] * 10
    b = [0.25] * 10
    result = stats.paired_bootstrap(a, b)
    assert result.mean_a == pytest.approx(1.0)
    assert result.mean_b == pytest.approx(0.25)
    assert result.items_equivalent == pytest.approx(7.5)
