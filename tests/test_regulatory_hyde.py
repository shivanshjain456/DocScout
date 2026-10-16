"""Unit tests for Regulatory HyDE (Hypothetical Document Embeddings) (FEAT-014)."""

from __future__ import annotations

import time

from app.api.metrics import HYDE_INVOCATIONS_TOTAL
from app.retrieval.hyde import (
    HyDEConfig,
    get_default_hyde_generator,
)


def test_regulatory_hyde_rbi_authority_generation() -> None:
    """Verifies synthesis of official RBI statutory circular clauses."""
    gen = get_default_hyde_generator()
    query = "What are the capital adequacy requirements for scheduled commercial banks?"

    hypothesis = gen.generate_hypothesis(query)

    assert "RESERVE BANK OF INDIA" in hypothesis
    assert "DEPARTMENT OF REGULATION" in hypothesis
    assert "Master Direction" in hypothesis
    assert query in hypothesis
    assert "minimum regulatory capital adequacy requirements" in hypothesis
    assert "Regulated Entities" in hypothesis


def test_regulatory_hyde_sebi_authority_generation() -> None:
    """Verifies synthesis of official SEBI statutory circular clauses."""
    gen = get_default_hyde_generator()
    query = "SEBI format for BRSR disclosures and ESG reporting by listed companies"

    hypothesis = gen.generate_hypothesis(query)

    assert "SECURITIES AND EXCHANGE BOARD OF INDIA" in hypothesis
    assert "DEPARTMENT OF REGULATION / MARKET INTERMEDIARIES" in hypothesis
    assert "Master Direction" in hypothesis
    assert "Market Intermediaries" in hypothesis


def test_domain_specific_statutory_hints() -> None:
    """Verifies statutory hints across cybersecurity, payments, and KYC."""
    gen = get_default_hyde_generator()

    # 1. Cyber security
    h_cyber = gen.generate_hypothesis(
        "Mandatory incident reporting timeline for ransomware attacks"
    )
    assert "cyber security frameworks" in h_cyber
    assert "incident reporting within 6 hours" in h_cyber

    # 2. Payments
    h_pay = gen.generate_hypothesis("Escrow account settlement rules for payment aggregators")
    assert "payment system operator governance" in h_pay
    assert "escrow accounts" in h_pay

    # 3. KYC / AML
    h_kyc = gen.generate_hypothesis("Customer due diligence requirements under PMLA norms")
    assert "customer identification procedures" in h_kyc
    assert "beneficial ownership verification" in h_kyc


def test_input_validation_rules_feat_014() -> None:
    """Validation rule: length between 10 and 256 characters."""
    gen = get_default_hyde_generator()

    # Under 10 characters -> returns original query unchanged
    short_query = "KYC rule"
    assert gen.generate_hypothesis(short_query) == short_query

    # Empty / whitespace -> returns original query unchanged
    assert gen.generate_hypothesis("") == ""
    assert gen.generate_hypothesis("   ") == "   "

    # Over 256 characters -> returns original query unchanged
    long_query = "What are the rules regarding " + "banking regulations " * 20
    assert len(long_query) > 256
    assert gen.generate_hypothesis(long_query) == long_query


def test_token_and_character_budget_capped_at_120_tokens() -> None:
    """Resource limits: token generation budget capped at 120 tokens (~480 chars)."""
    gen = get_default_hyde_generator()
    query = "Guidelines for capital charge on operational risk for non-banking financial companies"

    hypothesis = gen.generate_hypothesis(query)
    assert len(hypothesis) <= 480

    # Custom tighter token limit
    tight_cfg = HyDEConfig(enabled=True, max_tokens=30)
    tight_hypothesis = gen.generate_hypothesis(query, config=tight_cfg)
    assert len(tight_hypothesis) <= 125
    assert tight_hypothesis.endswith("...")


def test_hyde_performance_latency_budget_feat_014() -> None:
    """Performance limit: template-based HyDE <= 1.0 ms."""
    gen = get_default_hyde_generator()
    queries = [
        "What are the capital adequacy requirements for scheduled commercial banks?",
        "SEBI format for BRSR disclosures and ESG reporting by listed companies",
        "Mandatory incident reporting timeline for ransomware attacks under CERT-In",
        "Escrow account settlement rules for payment aggregators and gateways",
        "Customer due diligence requirements under PMLA master direction",
        "Prudential norms on outsourcing of financial services to cloud providers",
        "Integrated ombudsman scheme turnaround timelines for customer grievances",
        "Scale-based regulatory framework for upper layer NBFCs",
    ]

    # Warmup
    for q in queries:
        gen.generate_hypothesis(q)

    latencies: list[float] = []
    for _ in range(50):
        for q in queries:
            t0 = time.perf_counter()
            gen.generate_hypothesis(q)
            latencies.append((time.perf_counter() - t0) * 1000.0)

    latencies.sort()
    p95_idx = int(0.95 * len(latencies))
    p95_ms = latencies[p95_idx]
    assert p95_ms <= 1.0, f"p95 latency {p95_ms:.4f} ms exceeded 1.0 ms limit"


def test_hyde_metric_invocations_incremented() -> None:
    """Observability requirements: counter docscout_hyde_invocations_total."""
    before = HYDE_INVOCATIONS_TOTAL._value.get()
    gen = get_default_hyde_generator()
    gen.generate_hypothesis("Valid regulatory query with sufficient character length")
    after = HYDE_INVOCATIONS_TOTAL._value.get()
    assert after > before
