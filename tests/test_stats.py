"""Tests for statistical methods: paired bootstrap, McNemar counts, and Cohen's kappa."""

from __future__ import annotations

import pytest

from app.evals.stats import cohens_kappa, mcnemar_counts, paired_bootstrap


def test_paired_bootstrap_detects_difference() -> None:
    a = [1.0, 1.0, 1.0, 1.0, 1.0]
    b = [0.0, 0.0, 0.0, 0.0, 0.0]
    diff = paired_bootstrap(a, b, iterations=1000, seed=42)
    assert diff.difference == 1.0
    assert diff.excludes_zero is True
    assert diff.ci_low > 0.0


def test_mcnemar_counts_counts_discordant_pairs() -> None:
    a = [True, True, False, False]
    b = [True, False, True, False]
    a_only, b_only = mcnemar_counts(a, b)
    assert a_only == 1  # item index 1
    assert b_only == 1  # item index 2


def test_cohens_kappa_perfect_agreement() -> None:
    a = [1, 1, 0, 0, 1, 0, 1, 1]
    b = [1, 1, 0, 0, 1, 0, 1, 1]
    res = cohens_kappa(a, b)
    assert res.observed_agreement == 1.0
    assert res.kappa == 1.0
    assert res.rare_class_precision == 1.0
    assert res.rare_class_recall == 1.0
    assert res.rare_class_f1 == 1.0


def test_cohens_kappa_hand_computed_matrix() -> None:
    # tp=4, fp=1, fn=1, tn=4, n=10 -> Po=0.8, Pe=0.5 -> kappa=0.6
    a = [1, 1, 1, 1, 0, 0, 0, 0, 1, 0]
    b = [1, 1, 1, 0, 0, 0, 0, 1, 1, 0]
    res = cohens_kappa(a, b)
    assert pytest.approx(res.observed_agreement, 0.01) == 0.8
    assert pytest.approx(res.expected_agreement, 0.01) == 0.5
    assert pytest.approx(res.kappa, 0.01) == 0.6
    assert res.confusion_matrix == {"tp": 4, "fp": 1, "fn": 1, "tn": 4}


def test_cohens_kappa_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="differ"):
        cohens_kappa([1, 0], [1])


def test_cohens_kappa_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        cohens_kappa([], [])
