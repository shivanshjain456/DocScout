"""Tests for Interactive Search Query Suggestions (FEAT-019).

Verifies prefix autocomplete, acronym resolution, statutory circular suggestions,
graph edge exploration for related queries, typo-tolerant normalizer integration,
and strictly enforces the latency budget (<15ms p95).
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.retrieval.suggester import SearchSuggester, get_default_suggester
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def suggester() -> SearchSuggester:
    return get_default_suggester()


def test_prefix_autocomplete_term_names(suggester: SearchSuggester) -> None:
    """Test standard prefix typing matches term names correctly."""
    res = suggester.suggest("pay", limit=10)
    assert res.total > 0
    texts = [s.text.lower() for s in res.suggestions]
    assert any("payment aggregator" in t or "payment gateway" in t for t in texts)

    res_lcr = suggester.suggest("liquidity cov", limit=5)
    assert res_lcr.total > 0
    assert any("liquidity coverage ratio" in s.text.lower() for s in res_lcr.suggestions)


def test_acronym_suggestions(suggester: SearchSuggester) -> None:
    """Test acronym searches provide expanded regulatory definitions."""
    res_pa = suggester.suggest("PA", limit=5)
    assert res_pa.total > 0
    assert any("payment aggregator" in s.text.lower() for s in res_pa.suggestions)
    pa_match = next(s for s in res_pa.suggestions if "payment aggregator" in s.text.lower())
    assert pa_match.category in ("acronym", "term")

    res_lcr = suggester.suggest("LCR", limit=5)
    assert any("liquidity coverage ratio" in s.text.lower() for s in res_lcr.suggestions)

    res_nbfc = suggester.suggest("NBFC", limit=5)
    assert any("non-banking financial company" in s.text.lower() for s in res_nbfc.suggestions)

    res_fldg = suggester.suggest("FLDG", limit=5)
    assert any("default loss guarantee" in s.text.lower() for s in res_fldg.suggestions)


def test_statutory_circular_and_section_suggestions(suggester: SearchSuggester) -> None:
    """Test statutory circular prefixes and section numbers autocomplete."""
    res_rbi = suggester.suggest("RBI/2022", limit=5)
    assert res_rbi.total > 0
    stat_match = next(s for s in res_rbi.suggestions if "RBI/2022-23/111" in s.text)
    assert stat_match.category == "statutory"
    assert "Digital Lending" in stat_match.text

    res_sec = suggester.suggest("Section 45", limit=5)
    assert res_sec.total >= 2
    sec_texts = [s.text for s in res_sec.suggestions]
    assert any("Section 45-IA" in t for t in sec_texts)
    assert any("Section 45-JA" in t for t in sec_texts)

    res_rule = suggester.suggest("Rule 144", limit=5)
    assert any("Rule 144(xi)" in s.text for s in res_rule.suggestions)


def test_word_token_prefix_matching(suggester: SearchSuggester) -> None:
    """Test typing secondary word tokens matches containing terms."""
    res_agg = suggester.suggest("aggreg", limit=10)
    assert res_agg.total > 0
    texts = [s.text.lower() for s in res_agg.suggestions]
    assert any("payment aggregator" in t for t in texts)

    res_rec = suggester.suggest("reconstruct", limit=5)
    assert any("asset reconstruction company" in s.text.lower() for s in res_rec.suggestions)


def test_typo_tolerant_suggestions(suggester: SearchSuggester) -> None:
    """Test misspellings are corrected by RegulatoryNormalizer into valid suggestions."""
    res = suggester.suggest("paymnet ag", limit=5, enable_normalization=True)
    assert res.normalized_query == "payment ag"
    assert res.total > 0
    assert any("payment aggregator" in s.text.lower() for s in res.suggestions)

    res_dig = suggester.suggest("digtal lend", limit=5, enable_normalization=True)
    assert any("digital lending" in s.text.lower() for s in res_dig.suggestions)


def test_related_queries_from_graph_edges(suggester: SearchSuggester) -> None:
    """Test graph edge traversal produces related inquiry suggestions."""
    res = suggester.suggest("Payment Aggregator", limit=5, include_related=True)
    pa_item = next(s for s in res.suggestions if s.id == "payment-aggregator")
    assert len(pa_item.related_queries) > 0
    # Graph edges include payment-gateway, escrow-account, merchant-onboarding
    assert any("Payment Gateway" in q or "Escrow Account" in q for q in pa_item.related_queries)

    # When include_related is disabled
    res_no_rel = suggester.suggest("Payment Aggregator", limit=5, include_related=False)
    # Suggestions should not contain category='related'
    assert not any(s.category == "related" for s in res_no_rel.suggestions)


def test_latency_benchmark_under_15ms(suggester: SearchSuggester) -> None:
    """Verify p95 autocomplete response latency is strictly under 15ms."""
    queries = [
        "pay",
        "payment ag",
        "lcr",
        "rbi/2022",
        "section 45",
        "aggreg",
        "digtal lend",
        "nbfc",
        "kyc",
        "escrow",
    ]

    latencies_ms: list[float] = []
    # 100 queries benchmark
    for _ in range(10):
        for q in queries:
            t0 = time.perf_counter()
            res = suggester.suggest(q, limit=10)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)
            assert res.latency_ms >= 0.0

    latencies_ms.sort()
    p50 = latencies_ms[int(len(latencies_ms) * 0.50)]
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    p99 = latencies_ms[int(len(latencies_ms) * 0.99)]

    # The spec requirement is < 15ms. In practice it is sub-millisecond.
    assert p95 < 15.0, f"p95 latency {p95:.2f}ms exceeded 15ms SLA target!"
    assert p50 < 5.0, f"p50 latency {p50:.2f}ms too high!"
    assert p99 < 15.0, f"p99 latency {p99:.2f}ms exceeded 15ms SLA target!"


def test_api_search_suggestions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the HTTP API endpoint GET /v1/search/suggestions."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)

    # Missing API key -> 401 Unauthorized
    resp_unauth = client.get("/v1/search/suggestions?q=pay")
    assert resp_unauth.status_code == 401

    # Valid API key
    headers = auth(PRIMARY_KEY)
    resp = client.get("/v1/search/suggestions?q=pay&limit=5", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["query"] == "pay"
    assert data["total"] > 0
    assert len(data["suggestions"]) <= 5
    first_suggestion = data["suggestions"][0]
    assert "id" in first_suggestion
    assert "text" in first_suggestion
    assert "category" in first_suggestion
    assert "score" in first_suggestion
    assert "highlight" in first_suggestion
    assert "latency_ms" in data
    assert data["latency_ms"] < 15.0

    # Test validation: empty query
    resp_empty = client.get("/v1/search/suggestions?q=", headers=headers)
    assert resp_empty.status_code == 422
