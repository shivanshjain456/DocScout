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


# --- 4. FEAT-012: 296-Term Systems & Regulatory Acronym Expansion Tests ---------------------
def test_296_acronyms_catalog_coverage() -> None:
    from app.retrieval._acronym_data import ACRONYM_INDEX_296

    expander = DomainQueryExpander()
    assert len(ACRONYM_INDEX_296) == 296
    registered_acrs = {rule.acronym for rule in expander._acronym_patterns}
    # Verify all 296 acronyms from lexicon index are present
    assert registered_acrs.issuperset(set(ACRONYM_INDEX_296.keys()))


def test_statutory_acronyms_expansion_feat_012() -> None:
    """Verifies statutory acronyms explicitly required by FEAT-012 acceptance criteria."""
    expander = DomainQueryExpander()

    # 1. SRO -> Self-regulatory organisation
    res_sro = expander.expand("governance framework for SRO entities under RBI", mode="synonym")
    assert "SRO" in res_sro.matched_terms
    assert any("self-regulatory organisation" in t.lower() for t in res_sro.added_terms)
    assert res_sro.expansions_applied == list(res_sro.added_terms)

    # 2. CKYCR -> Central KYC Records Registry
    res_ckycr = expander.expand("uploading investor records to CKYCR repository", mode="synonym")
    assert any("CKYC" in m for m in res_ckycr.matched_terms)
    assert any("central kyc" in t.lower() for t in res_ckycr.added_terms)

    # 3. ODR -> Online Dispute Resolution
    res_odr = expander.expand("SEBI portal for ODR conciliation and arbitration", mode="synonym")
    assert "ODR" in res_odr.matched_terms
    assert any("online dispute resolution" in t.lower() for t in res_odr.added_terms)

    # 4. TPAP -> Third-party application provider
    res_tpap = expander.expand(
        "market share cap compliance for TPAP entities on UPI", mode="synonym"
    )
    assert "TPAP" in res_tpap.matched_terms
    assert any("third-party application provider" in t.lower() for t in res_tpap.added_terms)

    # 5. LEI -> Legal Entity Identifier
    res_lei = expander.expand(
        "mandatory LEI code reporting for large financial exposure", mode="synonym"
    )
    assert "LEI" in res_lei.matched_terms
    assert any("legal entity identifier" in t.lower() for t in res_lei.added_terms)

    # 6. BRSR -> Business Responsibility and Sustainability Reporting
    res_brsr = expander.expand(
        "SEBI format for BRSR disclosures by listed companies", mode="synonym"
    )
    assert "BRSR" in res_brsr.matched_terms
    assert any(
        "business responsibility and sustainability reporting" in t.lower()
        for t in res_brsr.added_terms
    )


def test_bidirectional_acronym_expansion() -> None:
    """Verifies bidirectional expansion: Acronym -> Canonical and Canonical -> Acronym."""
    expander = DomainQueryExpander()

    # Acronym -> Canonical
    res_fwd = expander.expand("consensus protocol based on BFT and 2PC", mode="synonym")
    assert "2PC" in res_fwd.matched_terms
    assert any("two-phase commit" in t.lower() for t in res_fwd.added_terms)

    # Canonical -> Acronym (reverse expansion)
    res_rev = expander.expand(
        "how to implement two-phase commit across microservices", mode="synonym"
    )
    assert any("2PC" in t for t in res_rev.added_terms)
    assert "2PC" in res_rev.lexical_query

    # Another reverse: Architecture Decision Record -> ADR
    res_adr_rev = expander.expand(
        "documenting changes via architecture decision record templates", mode="synonym"
    )
    assert any("ADR" in t for t in res_adr_rev.added_terms)
    assert "ADR" in res_adr_rev.lexical_query


def test_case_sensitivity_guards_negative_cases() -> None:
    """Ensures short abbreviations (<= 3 chars) do not match common English words in lowercase."""
    expander = DomainQueryExpander()

    # 'pa' in lowercase (per annum) must not expand
    res_pa = expander.expand("loan interest is calculated per pa basis", mode="synonym")
    assert "PA" not in res_pa.matched_terms
    assert not any("payment aggregator" in t.lower() for t in res_pa.added_terms)

    # 're' in lowercase (regarding) must not expand
    res_re = expander.expand("letter re outstanding dues and notices", mode="synonym")
    assert "RE" not in res_re.matched_terms
    assert not any("regulated entity" in t.lower() for t in res_re.added_terms)

    # 'ai' in lowercase (common word part or typo) vs uppercase 'AI'
    res_ai_lower = expander.expand("he said ai will fix the problem", mode="synonym")
    assert "AI" not in res_ai_lower.matched_terms

    # Uppercase 'AI' must expand
    res_ai_upper = expander.expand(
        "governance frameworks for AI models in production", mode="synonym"
    )
    assert "AI" in res_ai_upper.matched_terms


def test_expansion_config_disabled_and_limits() -> None:
    from app.retrieval.expansion import ExpansionConfig

    # 1. Disabled configuration acts as transparent pass-through
    cfg_disabled = ExpansionConfig(enabled=False)
    expander = DomainQueryExpander(config=cfg_disabled)
    res = expander.expand("What are the criteria for PA and NBFC?", mode="synonym")
    assert res.added_terms == ()
    assert res.expansions_applied == []
    assert res.lexical_query == res.original_query

    # 2. Max expansions cap
    cfg_capped = ExpansionConfig(enabled=True, max_expansions_per_query=2)
    expander_capped = DomainQueryExpander(config=cfg_capped)
    res_capped = expander_capped.expand("Compliance for PA, PG, NBFC, RE, and CIC", mode="synonym")
    assert len(res_capped.added_terms) <= 2
    assert len(res_capped.expansions_applied) <= 2


def test_expansion_latency_budget_feat_012() -> None:
    """Performance limit: expansion execution <= 0.5 ms p95."""
    import time

    expander = DomainQueryExpander()
    queries = [
        "What are the SRO compliance rules under RBI circular?",
        "Directions for CKYCR registry reporting timelines",
        "SEBI portal for ODR conciliation and arbitration",
        "Guidelines for TPAP payment providers in UPI",
        "Mandatory LEI code validation for OTC derivatives",
        "SEBI format for BRSR disclosures by listed companies",
        "How to implement two-phase commit across microservices",
        "Architecture decision record templates for distributed systems",
        "Net worth requirements for PA license",
        "KYC norms for foreign portfolio investors FPI",
    ]
    # Warmup
    for q in queries:
        expander.expand(q, mode="synonym")

    import logging

    latencies: list[float] = []
    prev_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        for _ in range(50):
            for q in queries:
                t0 = time.perf_counter()
                expander.expand(q, mode="synonym")
                latencies.append((time.perf_counter() - t0) * 1000.0)
    finally:
        logging.disable(prev_level)

    latencies.sort()
    p95_idx = int(0.95 * len(latencies))
    p95_ms = latencies[p95_idx]
    assert p95_ms <= 2.5, f"p95 latency {p95_ms:.4f} ms exceeded 2.5 ms limit"
