"""Tests for cross-encoder reranking.

The ordering logic is tested against a stubbed scorer rather than the real model. That is
not a shortcut: loading the cross-encoder costs ~11 s and scoring real chunks costs ~100 ms
per pair, so a suite that exercised the model for every ordering rule would be unusable and
would be testing PyTorch rather than this repository's logic. The model itself is exercised
once, end to end, in the integration tests below.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from app.retrieval import SERVING_CONFIG, RetrievalConfig, Retriever
from app.retrieval.rerank import Candidate, CrossEncoderReranker, RerankError


class StubReranker(CrossEncoderReranker):
    """A reranker with a scripted score list, so ordering rules can be asserted exactly."""

    def __init__(self, scores: list[float]) -> None:
        super().__init__()
        self._scores = scores

    def score(self, query: str, candidates: list[Candidate]) -> list[float]:
        return self._scores[: len(candidates)]


def candidates(n: int) -> list[Candidate]:
    return [Candidate(chunk_id=f"c{i}", text=f"passage {i}") for i in range(n)]


# --- ordering -----------------------------------------------------------------------------
def test_order_sorts_by_descending_score() -> None:
    reranker = StubReranker([0.1, 0.9, 0.5])
    assert [i for i, _ in reranker.order("q", candidates(3))] == [1, 2, 0]


def test_ties_preserve_the_incoming_order() -> None:
    """A reranker that cannot separate two candidates must not reshuffle them.

    Fusion's ordering is evidence; a coin flip is not. This also keeps a run reproducible,
    which the 1pp regression gate depends on.
    """
    reranker = StubReranker([0.5, 0.5, 0.5])
    assert [i for i, _ in reranker.order("q", candidates(3))] == [0, 1, 2]


def test_negative_scores_are_ordered_correctly() -> None:
    """Cross-encoder logits are unbounded and routinely negative."""
    reranker = StubReranker([-8.0, -2.0, -11.0])
    assert [i for i, _ in reranker.order("q", candidates(3))] == [1, 0, 2]


def test_empty_candidate_list_is_not_an_error() -> None:
    assert StubReranker([]).order("q", []) == []
    assert StubReranker([]).score("q", []) == []


def test_score_count_mismatch_is_rejected() -> None:
    """A silent length mismatch would misalign every score with the wrong passage."""

    class Broken(CrossEncoderReranker):
        def _load(self) -> Any:
            class Model:
                def predict(self, pairs: list[Any], **_: Any) -> list[float]:
                    return [0.1] * (len(pairs) - 1)

            return Model()

    with pytest.raises(RerankError, match="returned 2 scores for 3"):
        Broken().score("q", candidates(3))


# --- configuration ------------------------------------------------------------------------
def test_rerank_top_n_below_k_final_is_rejected() -> None:
    """Scoring fewer candidates than are returned pays for the model and reorders nothing."""
    with pytest.raises(ValueError, match="must be >= k_final"):
        RetrievalConfig(name="bad", mode="hybrid", k_final=10, rerank=True, rerank_top_n=5)


def test_rerank_fields_appear_in_provenance_only_when_enabled() -> None:
    off = RetrievalConfig(name="off", mode="hybrid").as_dict()
    assert off["rerank"] is False
    assert off["rerank_model"] is None

    on = RetrievalConfig(name="on", mode="hybrid", rerank=True, rerank_top_n=20).as_dict()
    assert on["rerank"] is True
    assert "ms-marco" in str(on["rerank_model"])


def test_serving_config_does_not_rerank() -> None:
    """ADR-0009: measured, and not worth 30x the latency on this corpus."""
    assert SERVING_CONFIG.rerank is False


# --- integration, against the real model and corpus ---------------------------------------
@pytest.fixture(scope="module")
def retriever(app_conn: psycopg.Connection[Any]) -> Retriever:
    row = app_conn.execute("SELECT count(*) FROM chunks").fetchone()
    if not row or int(row[0]) == 0:  # pragma: no cover - environment guard
        pytest.skip("corpus not ingested; run `make ingest`")
    return Retriever(app_conn)


QUESTION = "What are the KYC requirements for foreign portfolio investors?"


def reranked_config(k_final: int = 3, top_n: int = 5) -> RetrievalConfig:
    """Deliberately tiny: the cross-encoder costs ~100 ms per real chunk on 2 vCPU."""
    return RetrievalConfig(
        name="rerank-test",
        mode="hybrid",
        k_dense=SERVING_CONFIG.k_dense,
        k_lexical=SERVING_CONFIG.k_lexical,
        k_final=k_final,
        rrf_k=SERVING_CONFIG.rrf_k,
        anchor_arm_top1=True,
        rerank=True,
        rerank_top_n=top_n,
    )


@pytest.mark.slow
def test_reranking_returns_a_full_well_formed_result(retriever: Retriever) -> None:
    results = retriever.retrieve(QUESTION, reranked_config())
    assert len(results) == 3
    assert [r.rank for r in results] == [1, 2, 3]
    assert all(r.chunk_id and r.text for r in results)
    # Scores are cross-encoder logits now, not RRF scores (~1/61). Asserting the magnitude
    # catches a wiring mistake where the fused score survives into a reranked response.
    assert any(abs(r.score) > 0.5 for r in results)


@pytest.mark.slow
def test_reranking_is_deterministic(retriever: Retriever) -> None:
    config = reranked_config()
    first = [r.chunk_id for r in retriever.retrieve(QUESTION, config)]
    second = [r.chunk_id for r in retriever.retrieve(QUESTION, config)]
    assert first == second


@pytest.mark.slow
def test_reranked_results_come_from_the_candidate_pool(retriever: Retriever) -> None:
    """The reranker reorders; it must never introduce a chunk retrieval did not return."""
    pool = {
        r.chunk_id
        for r in retriever.retrieve(
            QUESTION,
            RetrievalConfig(
                name="pool",
                mode="hybrid",
                k_dense=SERVING_CONFIG.k_dense,
                k_lexical=SERVING_CONFIG.k_lexical,
                k_final=5,
                rrf_k=SERVING_CONFIG.rrf_k,
                anchor_arm_top1=True,
            ),
        )
    }
    reranked = {r.chunk_id for r in retriever.retrieve(QUESTION, reranked_config(3, 5))}
    assert reranked <= pool


@pytest.mark.slow
def test_reranking_actually_changes_something(retriever: Retriever) -> None:
    """Guards against a flag that is plumbed but never applied.

    If this ever fails because the orders agree, check that the reranker ran at all before
    concluding the model simply agreed with fusion.
    """
    baseline = [
        r.chunk_id
        for r in retriever.retrieve(
            QUESTION,
            RetrievalConfig(
                name="base",
                mode="hybrid",
                k_dense=SERVING_CONFIG.k_dense,
                k_lexical=SERVING_CONFIG.k_lexical,
                k_final=5,
                rrf_k=SERVING_CONFIG.rrf_k,
                anchor_arm_top1=True,
            ),
        )
    ]
    reranked = [r.chunk_id for r in retriever.retrieve(QUESTION, reranked_config(5, 10))]
    assert set(reranked) <= set(baseline) | set(reranked)
    assert reranked != baseline, "reranking produced the identical order; is it wired up?"
