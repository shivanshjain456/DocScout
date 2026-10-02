"""Tests for evidence coverage and abstention scoring.

The arithmetic is tested against hand-computed values, because these numbers decide
whether a user is warned that the corpus may not answer their question. The signal itself
is weak by measurement — AUC 0.730 — and the tests pin that honestly rather than asserting
it works better than it does.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from app.evals import abstention
from app.retrieval import SERVING_CONFIG, Retriever
from app.retrieval.confidence import LOW_EVIDENCE_THRESHOLD, assess


# --- coverage -----------------------------------------------------------------------------
def test_full_coverage_is_not_flagged() -> None:
    result = assess(["penalti", "deadlin"], [{"penalti", "deadlin", "other"}])
    assert result.evidence_coverage == 1.0
    assert result.missing_terms == []
    assert result.low_evidence is False


def test_a_missing_term_lowers_coverage_and_is_named() -> None:
    """Naming the term is the point: it is usually the word that makes the question
    unanswerable, and a bare score tells the user nothing actionable."""
    result = assess(["penalti", "deadlin", "oper"], [{"deadlin", "oper"}])
    assert result.evidence_coverage == pytest.approx(2 / 3)
    assert result.missing_terms == ["penalti"]


def test_coverage_unions_across_passages_up_to_the_depth() -> None:
    passages = [{"a"}, {"b"}, {"c"}, {"d"}, {"e"}, {"f"}]
    assert assess(["a", "f"], passages, depth=5).evidence_coverage == 0.5  # f is 6th
    assert assess(["a", "f"], passages, depth=6).evidence_coverage == 1.0


def test_duplicate_query_terms_are_counted_once() -> None:
    """Otherwise a repeated word inflates or deflates coverage depending on where it lands."""
    assert assess(["a", "a", "b"], [{"a"}]).evidence_coverage == 0.5


def test_a_query_with_no_analyzable_terms_is_flagged() -> None:
    """Only stopwords or punctuation: nothing was matched, so nothing supports the result."""
    result = assess([], [{"anything"}])
    assert result.evidence_coverage == 0.0
    assert result.low_evidence is True


def test_threshold_boundary_is_exclusive() -> None:
    """Coverage exactly at the threshold is not flagged; below it is."""
    assert assess(["a", "b", "c", "d"], [{"a", "b", "c"}]).evidence_coverage == 0.75
    assert assess(["a", "b", "c", "d"], [{"a", "b", "c"}], threshold=0.75).low_evidence is False
    assert assess(["a", "b", "c", "d"], [{"a", "b", "c"}], threshold=0.76).low_evidence is True


def test_passages_considered_is_reported() -> None:
    """The coverage number is uninterpretable without knowing how much text it saw."""
    assert assess(["a"], [{"a"}, {"b"}], depth=5).passages_considered == 2


# --- abstention metrics -------------------------------------------------------------------
def test_metrics_are_hand_computable() -> None:
    answerable = [0.9, 0.9, 0.9, 0.5]  # one wrongly flagged at t=0.65
    unanswerable = [0.1, 0.1, 0.9]  # two caught, one missed
    score = abstention.score_at_threshold(answerable, unanswerable, 0.65)
    assert score.correct_refusals == 2
    assert score.false_refusals == 1
    assert score.abstention_recall == pytest.approx(2 / 3)
    assert score.false_rejection_rate == pytest.approx(1 / 4)
    assert score.refusal_precision == pytest.approx(2 / 3)
    # 2 correct refusals + 3 correctly answered, out of 7.
    assert score.selective_accuracy == pytest.approx(5 / 7)
    assert score.refusal_rate == pytest.approx(3 / 7)


def test_metrics_do_not_divide_by_zero_on_empty_input() -> None:
    score = abstention.score_at_threshold([], [], 0.5)
    for value in (
        score.refusal_rate,
        score.abstention_recall,
        score.false_rejection_rate,
        score.refusal_precision,
        score.selective_accuracy,
    ):
        assert value == 0.0


def test_refusal_precision_is_zero_when_nothing_is_flagged() -> None:
    """Not 1.0: flagging nothing is not perfect precision, it is no decision at all."""
    assert abstention.score_at_threshold([0.9], [0.9], 0.5).refusal_precision == 0.0


# --- AUC ------------------------------------------------------------------------------------
def test_auc_of_a_perfect_separator_is_one() -> None:
    assert abstention.separation_auc([0.9, 0.8], [0.2, 0.1]) == 1.0


def test_auc_of_a_constant_signal_is_exactly_chance() -> None:
    """The RRF score behaved this way. Ties must count half, or a useless signal looks
    perfect or worthless depending on comparison order."""
    assert abstention.separation_auc([0.5, 0.5], [0.5, 0.5]) == 0.5


def test_auc_detects_a_signal_pointing_the_wrong_way() -> None:
    """dense_margin measured below 0.5; the harness must show that, not take absolute value."""
    assert abstention.separation_auc([0.1, 0.2], [0.8, 0.9]) == 0.0


def test_sweep_is_ordered_and_covers_every_threshold() -> None:
    scores = abstention.sweep([0.9], [0.1], [0.8, 0.2, 0.5])
    assert [s.threshold for s in scores] == [0.2, 0.5, 0.8]


# --- against the real corpus ------------------------------------------------------------
@pytest.fixture(scope="module")
def retriever(app_conn: psycopg.Connection[Any]) -> Retriever:
    row = app_conn.execute("SELECT count(*) FROM chunks").fetchone()
    if not row or int(row[0]) == 0:  # pragma: no cover - environment guard
        pytest.skip("corpus not ingested; run `make ingest`")
    return Retriever(app_conn)


@pytest.mark.slow
def test_an_answerable_question_is_well_covered(retriever: Retriever) -> None:
    question = "What are the KYC requirements for foreign portfolio investors?"
    hits = retriever.retrieve(question, SERVING_CONFIG)
    result = retriever.assess_confidence(question, hits)
    assert result.evidence_coverage >= LOW_EVIDENCE_THRESHOLD
    assert result.low_evidence is False


@pytest.mark.slow
def test_a_question_the_corpus_cannot_answer_is_flagged(retriever: Retriever) -> None:
    """g-131 from the gold set: the circular says a threshold will be set, never what it is.

    The topic retrieves perfectly — this is the hard case the gold set was built around,
    not a question about an absent subject.
    """
    question = "What is the minimum acceptable ITRI score an MII must maintain?"
    hits = retriever.retrieve(question, SERVING_CONFIG)
    result = retriever.assess_confidence(question, hits)
    assert result.low_evidence is True
    assert result.missing_terms, "a flagged question should say which terms were absent"


@pytest.mark.slow
def test_coverage_uses_the_database_analyzer(retriever: Retriever) -> None:
    """Stemming must match the BM25 index, or coverage counts terms the index never had."""
    question = "What are the registration requirements?"
    hits = retriever.retrieve(question, SERVING_CONFIG)
    result = retriever.assess_confidence(question, hits)
    assert 0.0 <= result.evidence_coverage <= 1.0
    # "the", "are" and "what" are stopwords; they must not appear as missing terms.
    assert not {"the", "are", "what"} & set(result.missing_terms)
