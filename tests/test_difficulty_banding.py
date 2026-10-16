"""Unit tests for Audience & Difficulty Banding Filter (FEAT-015)."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from app.api.models import Confidence, Passage, Provenance, SearchRequest, SearchResponse, Timings
from app.retrieval.difficulty import (
    DifficultyConfig,
    adapt_snippet,
    classify_difficulty,
    get_term_difficulty,
)


def test_difficulty_config_defaults_and_overrides() -> None:
    """Verifies DifficultyConfig initialization and token limits per band."""
    cfg = DifficultyConfig()
    assert cfg.default_level == "intermediate"
    assert cfg.max_foundational_tokens == 150
    assert cfg.max_intermediate_tokens == 250
    assert cfg.max_advanced_tokens == 400
    assert cfg.max_expert_tokens == 512

    # Token resolution
    assert cfg.get_max_tokens("foundational") == 150
    assert cfg.get_max_tokens("intermediate") == 250
    assert cfg.get_max_tokens("advanced") == 400
    assert cfg.get_max_tokens("expert") == 512
    assert cfg.get_max_tokens(None) == 512

    # Custom override
    custom = DifficultyConfig(
        default_level="advanced",
        max_foundational_tokens=100,
        max_expert_tokens=600,
    )
    assert custom.default_level == "advanced"
    assert custom.max_foundational_tokens == 100
    assert custom.max_expert_tokens == 600


def test_adapt_snippet_bounds_and_omission() -> None:
    """Verifies that adapt_snippet enforces token bounds per band and leaves None unchanged."""
    long_passage = " ".join([f"clause_{i}" for i in range(600)])

    # Omission returns standard full chunk window
    assert adapt_snippet(long_passage, None) == long_passage
    assert adapt_snippet(long_passage, "") == long_passage

    # Foundational <= 150 tokens
    foundational = adapt_snippet(long_passage, "foundational")
    assert len(foundational.split()) == 150

    # Intermediate <= 250 tokens
    intermediate = adapt_snippet(long_passage, "intermediate")
    assert len(intermediate.split()) == 250

    # Advanced <= 400 tokens
    advanced = adapt_snippet(long_passage, "advanced")
    assert len(advanced.split()) == 400

    # Expert <= 512 tokens
    expert = adapt_snippet(long_passage, "expert")
    assert len(expert.split()) == 512

    # Short passage not expanded or corrupted
    short_text = "RBI Master Direction on IT Governance Section 4.2."
    assert adapt_snippet(short_text, "foundational") == short_text
    assert adapt_snippet(short_text, "expert") == short_text


def test_passage_constructor_snippet_adaptation_feat_015() -> None:
    """Verifies snippet truncation logic directly inside Passage constructor."""
    long_text = " ".join([f"word_{i}" for i in range(300)])

    p_foundational = Passage(
        rank=1,
        chunk_id="chk-abc-001",
        document_id="doc-rbi-2024",
        source="RBI",
        canonical_url="https://rbi.org.in/circular/123",
        score=0.95,
        arm_ranks={"dense": 1, "bm25": 2},
        char_start=120,
        char_end=1500,
        text=long_text,
        difficulty_level="foundational",
    )
    assert p_foundational.difficulty_level == "foundational"
    assert len(p_foundational.text.split()) == 150
    # Zero loss of cited provenance spans or chunk UUID references
    assert p_foundational.chunk_id == "chk-abc-001"
    assert p_foundational.document_id == "doc-rbi-2024"
    assert p_foundational.char_start == 120
    assert p_foundational.char_end == 1500
    assert p_foundational.canonical_url == "https://rbi.org.in/circular/123"

    p_expert = Passage(
        rank=1,
        chunk_id="chk-abc-002",
        document_id="doc-rbi-2024",
        source="RBI",
        canonical_url=None,
        score=0.92,
        arm_ranks={"dense": 2},
        char_start=0,
        char_end=2000,
        text=long_text,
        difficulty_level="expert",
    )
    assert p_expert.difficulty_level == "expert"
    assert len(p_expert.text.split()) == 300  # 300 <= 512

    # Omission leaves text intact
    p_omitted = Passage(
        rank=1,
        chunk_id="chk-abc-003",
        document_id="doc-rbi-2024",
        source="RBI",
        canonical_url=None,
        score=0.88,
        arm_ranks={},
        char_start=0,
        char_end=1000,
        text=long_text,
        difficulty_level=None,
    )
    assert p_omitted.difficulty_level is None
    assert p_omitted.text == long_text


def test_search_request_validation_feat_015() -> None:
    """Verifies SearchRequest difficulty_band validation (valid literals vs 422 errors)."""
    for valid_band in ("foundational", "intermediate", "advanced", "expert", None):
        req = SearchRequest(query="capital adequacy ratio", difficulty_band=valid_band)
        assert req.difficulty_band == valid_band

    with pytest.raises(ValidationError):
        SearchRequest(query="capital adequacy ratio", difficulty_band="kindergarten")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        SearchRequest(query="capital adequacy ratio", difficulty_band="super_advanced")  # type: ignore[arg-type]


def test_term_difficulty_and_classifier() -> None:
    """Verifies taxonomy term lookups and text classification against lexicon levels."""
    assert get_term_difficulty("Unit Testing") == "foundational"
    assert get_term_difficulty("Acceptance Testing") == "foundational"
    assert get_term_difficulty("Formal Verification") == "expert"
    assert get_term_difficulty("ACID Transactions") == "advanced"

    # classify_difficulty
    expert_text = "The bank mandated Formal Verification and SAT Solving across payment pipelines."
    assert classify_difficulty(expert_text) == "expert"

    foundational_text = "Every sprint requires Unit Testing and Acceptance Testing before merge."
    assert classify_difficulty(foundational_text) == "foundational"

    neutral_text = "The committee convened to review general quarterly administrative minutes."
    assert classify_difficulty(neutral_text) == "intermediate"


def test_evaluation_dataset_40_queries_feat_015() -> None:
    """Evaluates 40 queries across all 4 difficulty levels (10 per band).

    Verifies 100% adherence to token window bounds.
    """
    sample_queries = {
        "foundational": [
            "what is unit testing in banking software",
            "explain api gateway basics",
            "system testing overview for newcomers",
            "what is acceptance testing",
            "intro to load testing",
            "continuous integration overview",
            "database transaction basics",
            "authentication introduction",
            "data encryption primer",
            "microservices 101 architecture",
        ],
        "intermediate": [
            "canary testing rollback policy",
            "api rate limiting configurations",
            "circuit breaker pattern implementation",
            "eventual consistency in distributed ledger",
            "zero downtime postgres migration steps",
            "database connection pool sizing",
            "oauth2 token refresh best practices",
            "kafka consumer lag monitoring",
            "distributed tracing with opentelemetry",
            "log retention compliance policy",
        ],
        "advanced": [
            "acid transaction isolation levels under high concurrency",
            "ai supply chain risk governance framework",
            "event sourcing projection rebuild strategy",
            "formal methods in smart contract audit",
            "pki certificate authority disaster recovery",
            "multi region active active replication conflicts",
            "byzantine fault tolerance in consensus networks",
            "chaos engineering blast radius containment",
            "differential privacy in credit scoring",
            "post quantum cryptography migration timeline",
        ],
        "expert": [
            "temporal logic verification of payment consensus",
            "model checking bounded invariants in core banking",
            "aead ciphersuite side channel mitigation",
            "attribute based access control formal semantics",
            "sat solving for regulatory rule conflict resolution",
            "formal specification of basel iii liquidity ratios",
            "zero knowledge proofs for transaction privacy",
            "tla+ specification of distributed transaction manager",
            "hardware security module cryptographic attestation",
            "provable security bounds on settlement finality",
        ],
    }

    synthetic_passage = " ".join([f"regulatory_clause_{i}" for i in range(600)])
    cfg = DifficultyConfig()

    for band, queries in sample_queries.items():
        assert len(queries) == 10
        expected_max = cfg.get_max_tokens(band)
        for q in queries:
            req = SearchRequest(query=q, difficulty_band=band)  # type: ignore[arg-type]
            adapted = adapt_snippet(synthetic_passage, req.difficulty_band)
            token_count = len(adapted.split())
            assert token_count <= expected_max, (
                f"Query '{q}' exceeded max {expected_max} tokens: {token_count}"
            )


def test_formatting_latency_overhead_feat_015() -> None:
    """Verifies that snippet formatting overhead is <= 0.1 ms per passage."""
    text = " ".join(["statutory regulatory framework circular mandate provision clause"] * 50)
    iterations = 1000

    start = time.perf_counter()
    for _ in range(iterations):
        _ = adapt_snippet(text, "foundational")
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    avg_latency_ms = elapsed_ms / iterations

    # Budget limit is 0.1 ms
    assert avg_latency_ms < 0.1, (
        f"Snippet formatting overhead {avg_latency_ms:.4f} ms exceeded 0.1 ms limit"
    )


def test_search_response_roundtrip_with_difficulty() -> None:
    """Verifies end-to-end SearchResponse construction and serialization with difficulty fields."""
    long_statutory = " ".join([f"rbi_directive_sec_{i}" for i in range(250)])
    p = Passage(
        rank=1,
        chunk_id="chk-001",
        document_id="doc-rbi",
        source="RBI",
        canonical_url="https://rbi.org.in/master-dir",
        score=0.91,
        arm_ranks={"hybrid": 1},
        char_start=0,
        char_end=500,
        text=long_statutory,
        difficulty_level="foundational",
    )
    assert p.difficulty_level == "foundational"
    assert len(p.text.split()) == 150

    resp = SearchResponse(
        query="what is capital adequacy ratio",
        mode="hybrid",
        k=1,
        passages=[p],
        confidence=Confidence(
            evidence_coverage=0.98,
            missing_terms=[],
            low_evidence=False,
            passages_considered=1,
        ),
        provenance=Provenance(
            embedding_model="test",
            embedding_dim=384,
            chunk_size=500,
            chunk_overlap=50,
            corpus_manifest_digest="sha256:abc",
            corpus_chunks=100,
            retrieval={"difficulty_band": "foundational"},
        ),
        timings=Timings(total_ms=5.0, retrieval_ms=5.0, cache_hit=False),
    )

    data = resp.model_dump()
    assert data["passages"][0]["difficulty_level"] == "foundational"
    assert len(data["passages"][0]["text"].split()) == 150
