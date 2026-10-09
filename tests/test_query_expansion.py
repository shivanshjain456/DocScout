"""Tests for regulatory domain query understanding and expansion (P1-3).

Validates:
1. Pure domain dictionary matching: acronym-to-expansion and term-to-acronym.
2. Word boundary and case-sensitivity guards preventing false positives on common words.
3. HyDE hypothetical regulatory passage synthesis.
4. Dense and lexical query separation.
5. End-to-end retrieval with expansion against the corpus.
6. HTTP API parameter parsing and cache partitioning.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from starlette.testclient import TestClient

from app.retrieval import RetrievalConfig, Retriever
from app.retrieval.expansion import DomainQueryExpander, ExpandedQuery
from tests.conftest import auth


# --- 1. Pure unit tests for DomainQueryExpander -------------------------------------------
def test_expander_expands_acronym_to_canonical() -> None:
    expander = DomainQueryExpander()
    res = expander.expand("What are the net worth criteria for PA?", mode="synonym")
    assert isinstance(res, ExpandedQuery)
    assert "PA" in res.matched_terms
    assert any("payment aggregator" in t.lower() for t in res.added_terms)
    assert "payment aggregator" in res.lexical_query.lower()
    assert "(payment aggregator" in res.dense_query.lower()


def test_expander_expands_canonical_term_to_acronym() -> None:
    expander = DomainQueryExpander()
    res = expander.expand(
        "Directives issued to non-banking financial company entities", mode="synonym"
    )
    assert any("NBFC" in t for t in res.added_terms)
    assert "NBFC" in res.lexical_query


def test_case_sensitive_acronym_guards() -> None:
    """Short abbreviations ('PA', 'RE', 'DP') must NOT match lowercase common words."""
    expander = DomainQueryExpander()

    # 'pa' in lowercase should not trigger 'payment aggregator'
    res_pa = expander.expand("interest is paid 5% pa on this account", mode="synonym")
    assert "PA" not in res_pa.matched_terms
    assert "payment aggregator" not in res_pa.lexical_query.lower()

    # 're' in lowercase should not trigger 'regulated entity'
    res_re = expander.expand("please reply regarding this inquiry", mode="synonym")
    assert "RE" not in res_re.matched_terms
    assert "regulated entity" not in res_re.lexical_query.lower()

    # Uppercase 'RE' and 'PA' MUST trigger
    res_re_upper = expander.expand(
        "Mandatory directives applicable to all RE entities", mode="synonym"
    )
    assert "RE" in res_re_upper.matched_terms
    assert "regulated entity" in res_re_upper.lexical_query.lower()


def test_word_boundary_guards_prevent_substring_matches() -> None:
    """Substrings inside unrelated words must not match."""
    expander = DomainQueryExpander()
    res = expander.expand("company prepares transparent reports", mode="synonym")
    assert "PA" not in res.matched_terms
    assert "RE" not in res.matched_terms
    assert res.added_terms == ()


def test_case_insensitive_longer_acronyms() -> None:
    """Longer acronyms like KYC, NBFC, CKYC can be typed in lowercase by users."""
    expander = DomainQueryExpander()
    res = expander.expand("what are the kyc requirements for foreign clients?", mode="synonym")
    assert any("know your customer" in t.lower() for t in res.added_terms)
    assert "know your customer" in res.lexical_query.lower()


def test_hyde_passage_synthesis() -> None:
    expander = DomainQueryExpander()
    res = expander.expand("Net worth requirements for PA license", mode="hyde")
    assert res.hypothetical_passage is not None
    assert "Reserve Bank of India" in res.hypothetical_passage
    assert "payment aggregator" in res.hypothetical_passage
    assert res.dense_query == res.hypothetical_passage


def test_combined_mode() -> None:
    expander = DomainQueryExpander()
    res = expander.expand("CEGSSC guarantee limits for eligible beneficiaries", mode="combined")
    assert "CEGSSC" in res.matched_terms
    assert any("credit enhancement" in t.lower() for t in res.added_terms)
    assert res.hypothetical_passage is not None
    assert res.dense_query == res.hypothetical_passage
    assert "credit enhancement" in res.lexical_query.lower()


def test_mode_none_is_noop() -> None:
    expander = DomainQueryExpander()
    res = expander.expand("What are the criteria for PA?", mode="none")
    assert res.original_query == res.lexical_query == res.dense_query
    assert res.matched_terms == ()
    assert res.added_terms == ()


def test_empty_query_is_noop() -> None:
    expander = DomainQueryExpander()
    res = expander.expand("   ", mode="synonym")
    assert res.added_terms == ()


# --- 2. End-to-end retrieval with expansion -----------------------------------------------
@pytest.fixture(scope="module")
def retriever(app_conn: psycopg.Connection[Any]) -> Retriever:
    return Retriever(app_conn)


def test_retriever_executes_with_synonym_expansion(retriever: Retriever) -> None:
    config = RetrievalConfig(
        name="test-expanded",
        mode="hybrid",
        k_final=5,
        expand_query=True,
        expansion_mode="synonym",
    )
    results = retriever.retrieve("What are the KYC norms for foreign portfolio investors?", config)
    assert len(results) == 5
    assert all(r.chunk_id for r in results)
    assert all(r.score > 0.0 for r in results)


def test_retriever_executes_with_hyde_expansion(retriever: Retriever) -> None:
    config = RetrievalConfig(
        name="test-hyde",
        mode="hybrid",
        k_final=5,
        expand_query=True,
        expansion_mode="hyde",
    )
    results = retriever.retrieve("timeline for ODR grievance redressal", config)
    assert len(results) == 5
    assert all(r.chunk_id for r in results)


def test_retrieval_with_expansion_is_deterministic(retriever: Retriever) -> None:
    config = RetrievalConfig(
        name="test-det-expanded",
        mode="hybrid",
        k_final=5,
        expand_query=True,
        expansion_mode="synonym",
    )
    query = "What is the DRI scheme interest rate?"
    first = retriever.retrieve(query, config)
    second = retriever.retrieve(query, config)
    assert [r.chunk_id for r in first] == [r.chunk_id for r in second]
    assert [r.score for r in first] == [r.score for r in second]


# --- 3. HTTP API integration & cache isolation -------------------------------------------


def test_api_search_accepts_expansion_parameters(client: TestClient) -> None:
    payload = {
        "query": "What are the KYC rules for FPI?",
        "k": 5,
        "mode": "hybrid",
        "expand_query": True,
        "expansion_mode": "synonym",
        "use_cache": False,
    }
    response = client.post("/v1/search", json=payload, headers=auth())
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["passages"]) == 5
    assert data["provenance"]["retrieval"]["expand_query"] is True
    assert data["provenance"]["retrieval"]["expansion_mode"] == "synonym"


def test_api_cache_partitions_by_expansion_parameters(client: TestClient) -> None:
    query = "What is the maximum loan under DRI?"
    base_payload = {
        "query": query,
        "k": 5,
        "mode": "hybrid",
        "use_cache": True,
    }

    # Request 1: Without expansion
    r1 = client.post(
        "/v1/search",
        json={**base_payload, "expand_query": False, "expansion_mode": "none"},
        headers=auth(),
    )
    assert r1.status_code == 200
    assert r1.json()["timings"]["cache_hit"] is False

    # Repeat request 1: Should be a cache hit
    r1_hit = client.post(
        "/v1/search",
        json={**base_payload, "expand_query": False, "expansion_mode": "none"},
        headers=auth(),
    )
    assert r1_hit.status_code == 200
    assert r1_hit.json()["timings"]["cache_hit"] is True

    # Request 2: With expansion enabled. Must NOT hit the unexpanded cache entry!
    r2 = client.post(
        "/v1/search",
        json={**base_payload, "expand_query": True, "expansion_mode": "synonym"},
        headers=auth(),
    )
    assert r2.status_code == 200
    assert r2.json()["timings"]["cache_hit"] is False  # Must be a fresh computation

    # Repeat request 2: Should now hit its own partitioned cache entry
    r2_hit = client.post(
        "/v1/search",
        json={**base_payload, "expand_query": True, "expansion_mode": "synonym"},
        headers=auth(),
    )
    assert r2_hit.status_code == 200
    assert r2_hit.json()["timings"]["cache_hit"] is True
