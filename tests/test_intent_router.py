"""Unit tests for Intent-Driven Query Classification & Routing (FEAT-013)."""

from __future__ import annotations

import time

from app.api.models import Confidence, Passage, Provenance, SearchResponse, Timings
from app.retrieval._intent_data import INTENT_DEFINITIONS
from app.retrieval.intent_router import IntentRouterConfig, get_default_intent_router


def test_intent_catalog_coverage() -> None:
    """Verifies all 21 diagnostic intents plus statutory incident readiness are registered."""
    router = get_default_intent_router()
    registered_ids = {ci.definition.id for ci in router._intents}

    assert len(INTENT_DEFINITIONS) == 22
    assert len(registered_ids) == 22

    expected_ids = {
        "intent.flaky-ci",
        "intent.slow-ci",
        "intent.ship-safely",
        "intent.distributed-bug",
        "intent.hard-to-reproduce",
        "intent.security-hardening",
        "intent.supply-chain",
        "intent.ai-redteam",
        "intent.llm-regression",
        "intent.ai-governance",
        "intent.data-quality",
        "intent.zero-downtime-migration",
        "intent.observability",
        "intent.performance",
        "intent.accessibility",
        "intent.compliance-evidence",
        "intent.sustainability",
        "intent.crypto-migration",
        "intent.test-automation-strategy",
        "intent.legacy-safety-net",
        "intent.contract-testing",
        "intent.incident-readiness",
    }
    assert registered_ids == expected_ids


def test_canonical_intents_classification_feat_013() -> None:
    """Verifies statutory and engineering diagnostic intents cited in FEAT-013 acceptance criteria."""
    router = get_default_intent_router()

    cases = [
        ("our CI is flaky", "intent.flaky-ci"),
        ("tests pass locally fail in CI", "intent.flaky-ci"),
        ("how to report cyber incident", "intent.incident-readiness"),
        ("cert-in incident reporting timeline", "intent.incident-readiness"),
        ("where do we start with AppSec", "intent.security-hardening"),
        ("customer asking for SBOM", "intent.supply-chain"),
        ("prompt injection attacks on our LLM", "intent.ai-redteam"),
        ("EU AI Act compliance requirements", "intent.ai-governance"),
        ("schema change without downtime", "intent.zero-downtime-migration"),
        ("consumer driven contracts", "intent.contract-testing"),
        ("latency spikes in production", "intent.performance"),
        ("accessibility compliance under WCAG", "intent.accessibility"),
    ]

    for query, expected_intent_id in cases:
        res = router.classify(query)
        assert res is not None, f"Failed to classify intent for query: '{query}'"
        assert res.intent_id == expected_intent_id, (
            f"Query '{query}' classified as '{res.intent_id}', expected '{expected_intent_id}'"
        )
        assert res.confidence >= 0.65
        assert len(res.first_move) > 10
        assert len(res.recommended_terms) > 0
        assert len(res.primary_domain) > 0


def test_105_synthetic_utterances_accuracy_feat_013() -> None:
    """Acceptance criteria: accurately classifies >= 90% of test utterances."""
    router = get_default_intent_router()
    test_utterances: list[tuple[str, str]] = []

    for defn in INTENT_DEFINITIONS:
        for u in defn.utterances:
            test_utterances.append((u, defn.id))

    assert len(test_utterances) >= 100, f"Expected >= 100 utterances, got {len(test_utterances)}"

    correct = 0
    for utterance, expected_id in test_utterances:
        res = router.classify(utterance)
        if res is not None and res.intent_id == expected_id and res.confidence >= 0.65:
            correct += 1

    accuracy = correct / len(test_utterances)
    assert accuracy >= 0.90, f"Intent classification accuracy {accuracy:.2%} is below 90% target"


def test_intent_router_latency_budget_feat_013() -> None:
    """Performance limit: intent classification latency <= 2.5 ms p95."""
    router = get_default_intent_router()
    queries = [
        "our CI is flaky and tests fail randomly",
        "how to report cyber incident to cert-in and rbi",
        "prompt injection and jailbreak testing",
        "zero-downtime database schema migration",
        "consumer-driven contract testing between microservices",
        "what are the capital adequacy requirements for banks",
        "latency spikes and p99 flame graph profiling",
        "WCAG accessibility compliance testing for screen readers",
    ]

    # Warmup
    for q in queries:
        router.classify(q)

    latencies: list[float] = []
    for _ in range(50):
        for q in queries:
            t0 = time.perf_counter()
            router.classify(q)
            latencies.append((time.perf_counter() - t0) * 1000.0)

    latencies.sort()
    p95_idx = int(0.95 * len(latencies))
    p95_ms = latencies[p95_idx]
    assert p95_ms <= 2.5, f"p95 latency {p95_ms:.4f} ms exceeded 2.5 ms limit"


def test_non_intent_queries_abstention() -> None:
    """Error behavior: queries without diagnostic intent clear threshold return None."""
    router = get_default_intent_router()

    general_queries = [
        "What are the capital adequacy requirements for scheduled commercial banks?",
        "Net worth criteria for non-banking financial company registration",
        "Guidelines on core banking solution implementation",
        "Standard operating procedure for ATM cash replenishment",
    ]

    for q in general_queries:
        res = router.classify(q)
        assert res is None, f"Expected None for non-intent query '{q}', got {res}"


def test_input_validation_rules() -> None:
    """Input validation: length between 5 and 512 characters."""
    router = get_default_intent_router()

    assert router.classify("") is None
    assert router.classify("   ") is None
    assert router.classify("ci") is None  # < 5 chars
    assert router.classify("a" * 513) is None  # > 512 chars


def test_intent_router_config_toggle() -> None:
    """Verifies disabling router via config returns None."""
    router = get_default_intent_router()
    cfg_disabled = IntentRouterConfig(enabled=False)
    assert router.classify("our CI is flaky", config=cfg_disabled) is None

    cfg_high_threshold = IntentRouterConfig(enabled=True, min_confidence=0.99)
    # A generic overlap won't reach 0.99
    res = router.classify("we need some kind of testing strategy", config=cfg_high_threshold)
    assert res is None or res.confidence >= 0.99


def test_search_response_intent_field_serialization() -> None:
    """Verifies SearchResponse model serialization with and without intent."""
    router = get_default_intent_router()
    classified = router.classify("our CI is flaky")
    assert classified is not None

    resp_with_intent = SearchResponse(
        query="our CI is flaky",
        mode="hybrid",
        k=5,
        passages=[
            Passage(
                rank=1,
                chunk_id="chk-001",
                document_id="doc-001",
                source="test",
                canonical_url=None,
                score=0.9,
                arm_ranks={},
                char_start=0,
                char_end=100,
                text="Test text",
            )
        ],
        confidence=Confidence(
            evidence_coverage=0.95,
            missing_terms=[],
            low_evidence=False,
            passages_considered=1,
        ),
        provenance=Provenance(
            embedding_model="test",
            embedding_dim=384,
            chunk_size=500,
            chunk_overlap=50,
            corpus_manifest_digest="sha256:123",
            corpus_chunks=10,
            retrieval={},
        ),
        timings=Timings(total_ms=10.0, retrieval_ms=10.0, cache_hit=False),
        intent=classified,
    )

    data = resp_with_intent.model_dump()
    assert data["intent"] is not None
    assert data["intent"]["intent_id"] == "intent.flaky-ci"
    assert "Instrument flakiness rate" in data["intent"]["first_move"]

    # Serialization without intent
    resp_without_intent = resp_with_intent.model_copy(update={"intent": None})
    data_no_intent = resp_without_intent.model_dump()
    assert data_no_intent["intent"] is None
