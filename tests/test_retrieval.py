"""Tests for the retrieval arms and their fusion.

Fusion is tested without a database because it is pure arithmetic over rank lists. The
arms are tested against the real corpus, because a BM25 implementation that agrees with
its own unit test but disagrees with Postgres's analyzer is the exact failure this design
exists to prevent.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from app.retrieval import SERVING_CONFIG, RetrievalConfig, Retriever
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.lexical import BM25Index
from app.rowtypes import as_int


# --- fusion: pure, no database -----------------------------------------------------------
def test_rrf_rewards_agreement_between_arms() -> None:
    """A document both arms rank second beats one that a single arm ranks first."""
    fused = reciprocal_rank_fusion({"dense": ["x", "both"], "lexical": ["y", "both"]}, rrf_k=60)
    assert fused[0][0] == "both"


def test_rrf_score_is_the_documented_formula() -> None:
    fused = reciprocal_rank_fusion({"dense": ["a"], "lexical": ["a"]}, rrf_k=60)
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 61)


def test_rrf_records_each_arm_rank_for_explainability() -> None:
    fused = reciprocal_rank_fusion({"dense": ["a", "b"], "lexical": ["b"]}, rrf_k=60)
    ranks = {cid: arms for cid, _, arms in fused}
    assert ranks["b"] == {"dense": 2, "lexical": 1}
    assert ranks["a"] == {"dense": 1}


def test_rrf_weights_shift_the_balance() -> None:
    arms = {"dense": ["d"], "lexical": ["l"]}
    assert reciprocal_rank_fusion(arms, weights={"dense": 10.0, "lexical": 1.0})[0][0] == "d"
    assert reciprocal_rank_fusion(arms, weights={"dense": 1.0, "lexical": 10.0})[0][0] == "l"


def test_rrf_is_deterministic_under_ties() -> None:
    """Ties break on chunk_id so two runs of one config are byte-identical.

    A report that reshuffles between runs cannot support a 1pp regression gate.
    """
    arms = {"dense": ["b", "a"], "lexical": ["a", "b"]}
    first = [cid for cid, _, _ in reciprocal_rank_fusion(arms)]
    second = [cid for cid, _, _ in reciprocal_rank_fusion(dict(reversed(list(arms.items()))))]
    assert first == second == ["a", "b"]


def test_rrf_of_nothing_is_empty() -> None:
    assert reciprocal_rank_fusion({}) == []


# --- arms: against the real corpus -------------------------------------------------------
@pytest.fixture(scope="module")
def retriever(app_conn: psycopg.Connection[Any]) -> Retriever:
    count = app_conn.execute("SELECT count(*) FROM chunks").fetchone()
    if not count or as_int(count[0]) == 0:
        pytest.skip("corpus not ingested; run `make ingest`")
    return Retriever(app_conn)


def test_bm25_uses_the_same_analyzer_as_the_index(app_conn: psycopg.Connection[Any]) -> None:
    """Query terms must come from Postgres, not a second Python tokenizer.

    'Registered' must stem to the same lexeme as 'registration' would under the english
    configuration; if the scorer ever tokenizes independently, this is where it shows.
    """
    index = BM25Index(app_conn)
    terms = index.query_terms(app_conn, "the registered intermediaries were registering")
    assert "regist" in " ".join(terms)
    assert "the" not in terms  # stopword, removed by the analyzer


def test_bm25_index_statistics_are_sane(app_conn: psycopg.Connection[Any]) -> None:
    index = BM25Index(app_conn)
    assert index.n_documents > 0
    assert index.average_length > 0


def test_bm25_finds_an_exact_regulatory_token(
    retriever: Retriever, app_conn: psycopg.Connection[Any]
) -> None:
    hits = retriever.bm25.search(app_conn, "foreign portfolio investor KYC review", 5)
    assert hits, "BM25 returned nothing for a corpus term"
    assert all(score > 0 for _, score in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_every_mode_returns_k_final_ranked_results(retriever: Retriever, mode: str) -> None:
    config = RetrievalConfig(name=f"t-{mode}", mode=mode, k_final=5)  # type: ignore[arg-type]
    results = retriever.retrieve(
        "What are the KYC requirements for foreign portfolio investors?", config
    )
    assert len(results) == 5
    assert [r.rank for r in results] == [1, 2, 3, 4, 5]
    assert all(r.chunk_id and r.text for r in results)


def test_hybrid_credits_both_arms(retriever: Retriever) -> None:
    config = RetrievalConfig(name="t-hybrid", mode="hybrid", k_final=10)
    results = retriever.retrieve("settlement cycle for listed securities", config)
    arms_seen = {arm for r in results for arm in r.arm_ranks}
    assert arms_seen == {"dense", "lexical"}


def test_single_arm_runs_do_not_report_a_fused_score(retriever: Retriever) -> None:
    """A dense-only run must report cosine similarity, not an RRF score.

    Reporting a fused score for a configuration that never fused anything would be a
    fabricated number, and RRF scores are ~1/61 while cosine is ~0.7 -- easy to tell apart.
    """
    results = retriever.retrieve("KYC", RetrievalConfig(name="t", mode="dense", k_final=3))
    assert results[0].score > 0.1
    assert set(results[0].arm_ranks) == {"dense"}


def test_retrieval_is_deterministic(retriever: Retriever) -> None:
    config = RetrievalConfig(name="t", mode="hybrid", k_final=10)
    question = "What is the timeline for grievance redressal?"
    assert [r.chunk_id for r in retriever.retrieve(question, config)] == [
        r.chunk_id for r in retriever.retrieve(question, config)
    ]


# --- regression: g-038, a confident arm buried by rank-only fusion ----------------------
# Gold item g-038 asks which withdrawn circular covered CCTV coverage of currency chests.
# BM25 ranks the correct chunk FIRST with a decisive margin; the dense arm ranks it 41st;
# RRF at k=60 fused those to rank 14, outside the serving depth of 10, so the item scored
# zero recall at every cutoff while one arm had the answer at position one.
#
# The cause is structural, not a tuning accident: RRF scores by 1/(k + rank), so at k=60
# rank 1 is worth only 1.66x rank 41, and consensus beats conviction. SERVING_CONFIG
# reserves a seat for each arm's own top hit. These tests fail against plain RRF.
G038_QUESTION = (
    "Which withdrawn circular dealt with CCTV coverage of cash handling operations in "
    "currency chests, and on what date was it issued?"
)
G038_GOLD_CHUNK = "32457830-3217-579d-bb5f-0abe24a87676"


def test_g038_confident_lexical_hit_survives_fusion(retriever: Retriever) -> None:
    """The serving configuration must return the chunk BM25 ranked first."""
    results = retriever.retrieve(G038_QUESTION, SERVING_CONFIG)
    assert G038_GOLD_CHUNK in [r.chunk_id for r in results], (
        "g-038's evidence fell out of the served results; the arm-anchor guarantee is gone"
    )


def test_g038_is_still_buried_without_the_anchor(retriever: Retriever) -> None:
    """Pins the defect itself, so the regression test cannot quietly stop testing anything.

    If a future change makes plain RRF surface this chunk on its own, this test fails and
    the anchor guarantee -- and its ADR -- should be revisited rather than left in place as
    cargo cult.
    """
    plain = RetrievalConfig(
        name="plain-rrf", mode="hybrid", k_dense=50, k_lexical=50, k_final=10, rrf_k=60
    )
    assert G038_GOLD_CHUNK not in [r.chunk_id for r in retriever.retrieve(G038_QUESTION, plain)]


def test_anchored_chunk_keeps_its_real_fused_score(retriever: Retriever) -> None:
    """An anchored result must not be given a fabricated score to justify its position."""
    results = retriever.retrieve(G038_QUESTION, SERVING_CONFIG)
    anchored = next(r for r in results if r.chunk_id == G038_GOLD_CHUNK)
    assert anchored.score > 0.0
    assert anchored.arm_ranks.get("lexical") == 1


def test_anchor_adds_at_most_one_chunk_per_arm(retriever: Retriever) -> None:
    """The guarantee is bounded: it reserves seats, it does not reshape the result set."""
    plain = RetrievalConfig(
        name="plain-rrf", mode="hybrid", k_dense=50, k_lexical=50, k_final=10, rrf_k=60
    )
    before = {r.chunk_id for r in retriever.retrieve(G038_QUESTION, plain)}
    after = {r.chunk_id for r in retriever.retrieve(G038_QUESTION, SERVING_CONFIG)}
    assert len(after) == len(before) == 10
    assert len(after - before) <= 2  # one arm leader per arm, at most
