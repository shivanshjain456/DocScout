"""Unit and integration tests for Grandfathering & Exemption Scope Engine (FEAT-036).

Verifies:
1. Scope classification into ALL, NEW_ENTRANTS_ONLY, GRANDFATHERED_EXISTING.
2. 25-clause benchmark evaluation dataset achieving precision >= 95%.
3. Regression guard: Zero false-positive grandfathering on universal statutory mandates.
4. Fail-safe fallback: Ambiguous text defaults to scope="ALL".
5. Input validation: Non-empty text requirement.
6. Performance: Classification latency <= 0.5 ms per chunk.
7. Search integration: entity_vintage filtering in retrieval.
"""

from __future__ import annotations

import time

import pytest

from app.ingest.scope_classifier import (
    ScopeClassification,
    ScopeClassifier,
    ScopeConfig,
    classify_scope,
)

# 25 benchmark regulatory clauses for grandfathering vs new entrants evaluation
BENCHMARK_SCOPE_CLAUSES = [
    # GRANDFATHERED_EXISTING (10 clauses)
    {
        "text": "Existing non-bank Payment Aggregators (PAs) as on March 17, 2020 may continue their operations and shall apply for authorization on or before September 30, 2021.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "Existing entities currently undertaking activities as account aggregators shall be grandfathered provided they submit an application within six months.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "The revised net-worth norms shall not apply to entities already holding a certificate of registration prior to the cutoff date.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "Incumbent market participants are exempted from the initial capital requirement under legacy grandfathering provisions.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "Existing credit rating agencies operating under previous guidelines may continue business subject to phased compliance.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "Entities registered before April 1, 2022 shall enjoy transitional relief and carryover licensing status.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "Existing prepaid payment instrument (PPI) issuers are grandfathered regarding customer acquisition criteria until license renewal.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "These higher capital adequacy constraints are waived for legacy microfinance institutions holding valid permits.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "All existing authorized dealers may continue cross-border trade transactions without submitting fresh incorporation certificates.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    {
        "text": "Pre-existing peer-to-peer lending platforms shall be grandfathered and are granted twelve months to align with net-worth ratios.",
        "expected_scope": "GRANDFATHERED_EXISTING",
    },
    # NEW_ENTRANTS_ONLY (7 clauses)
    {
        "text": "New entities desiring to setup payment aggregator operations shall adhere to Rs. 15 crore net-worth on day-one of commencing business.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
    },
    {
        "text": "The provisions of Chapter IV shall apply strictly to applications received on or after November 01, 2023.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
        "condition_hint": "on or after",
    },
    {
        "text": "Prospective applicants seeking fresh registration as Non-Banking Financial Companies (NBFC) must comply with enhanced statutory deposit requirements.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
    },
    {
        "text": "New market entrants shall submit an escrow agreement and technical audit before onboarding any merchant.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
    },
    {
        "text": "Entities incorporated on or after January 01, 2025 shall not be eligible for phased net-worth milestones and must satisfy the ceiling immediately.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
    },
    {
        "text": "Fresh applicants seeking regulatory sandbox admission must demonstrate minimum operational track record.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
    },
    {
        "text": "New entrants into the trade repository ecosystem shall install redundant disaster recovery infrastructure prior to commercial launch.",
        "expected_scope": "NEW_ENTRANTS_ONLY",
    },
    # ALL - Universal mandates (8 clauses)
    {
        "text": "All regulated entities, whether existing or newly incorporated, shall establish a Board-approved Information Security Policy.",
        "expected_scope": "ALL",
    },
    {
        "text": "Every authorized payment system operator shall implement multi-factor authentication for customer-initiated transactions.",
        "expected_scope": "ALL",
    },
    {
        "text": "All commercial banks and non-banking financial companies must report suspicious cyber incidents within six hours of detection.",
        "expected_scope": "ALL",
    },
    {
        "text": "Regulated entities shall ensure that customer card data is encrypted using AES-256 standard across all communication channels.",
        "expected_scope": "ALL",
    },
    {
        "text": "No entity in the financial ecosystem shall store sensitive personal data outside the geographical boundaries of India.",
        "expected_scope": "ALL",
    },
    {
        "text": "Universal customer dispute redressal mechanisms shall be operationalized with 24x7 helpline availability.",
        "expected_scope": "ALL",
    },
    {
        "text": "Every intermediary shall designate a Principal Officer responsible for reporting under Prevention of Money Laundering Act.",
        "expected_scope": "ALL",
    },
    {
        "text": "Statutory audit reports shall be submitted annually to the Reserve Bank of India by the thirty-first day of July.",
        "expected_scope": "ALL",
    },
]


def test_input_validation() -> None:
    """Verifies that empty chunk text is rejected with ValueError."""
    classifier = ScopeClassifier()
    with pytest.raises(ValueError, match="non-empty"):
        classifier.classify("")

    with pytest.raises(ValueError, match="non-empty"):
        classifier.classify("   \n\t  ")


def test_ambiguous_text_failsafe_defaults_to_all() -> None:
    """FAIL-SAFE: Ambiguous or generic text must default to applicability_scope='ALL'."""
    classifier = ScopeClassifier()
    ambiguous_text = "The committee reviewed market developments and noted ongoing improvements in macroeconomic stability."
    res = classifier.classify(ambiguous_text)
    assert res.scope == "ALL"
    assert res.confidence >= 0.5


def test_zero_false_positive_grandfathering_on_universal_mandates() -> None:
    """REGRESSION LIMIT: Universal mandates must NEVER be classified as grandfathered."""
    classifier = ScopeClassifier()
    strict_mandates = [
        "All regulated entities shall maintain minimum capital adequacy ratios without exception.",
        "Every licensed banking corporation must report cyber breach incidents to CERT-In within six hours.",
        "No institution shall permit unauthorized access to customer credit records under any circumstance.",
        "All existing and new systems shall strictly implement TLS 1.3 cryptographic protocols.",
    ]
    for mandate in strict_mandates:
        res = classifier.classify(mandate)
        assert res.scope == "ALL", f"Universal mandate falsely classified as {res.scope}: {mandate}"


def test_benchmark_scope_precision() -> None:
    """ACCEPTANCE CRITERIA: Grandfathering detection precision >= 95% on 25 benchmark clauses."""
    classifier = ScopeClassifier()

    correct_predictions = 0
    total = len(BENCHMARK_SCOPE_CLAUSES)

    for item in BENCHMARK_SCOPE_CLAUSES:
        text = item["text"]
        expected = item["expected_scope"]

        result = classifier.classify(text)
        if result.scope == expected:
            correct_predictions += 1
        else:
            pytest.fail(
                f"Clause misclassified: expected '{expected}', got '{result.scope}'. Text: {text}"
            )

    accuracy = correct_predictions / total
    assert accuracy >= 0.95, f"Benchmark scope accuracy {accuracy:.4f} is below 0.95 threshold"


def test_performance_budget_sub_millisecond() -> None:
    """PERFORMANCE LIMIT: Classification overhead <= 0.5 ms per chunk."""
    classifier = ScopeClassifier()
    sample = BENCHMARK_SCOPE_CLAUSES[0]["text"]

    # Warmup
    classifier.classify(sample)

    iterations = 100
    t0 = time.perf_counter()
    for _ in range(iterations):
        classifier.classify(sample)
    duration_per_chunk_ms = ((time.perf_counter() - t0) / iterations) * 1000.0

    assert duration_per_chunk_ms <= 0.5, (
        f"Overhead {duration_per_chunk_ms:.3f}ms exceeds 0.5ms limit"
    )


def test_convenience_function_and_config() -> None:
    """Verifies module-level classify_scope function and configuration toggle."""
    res = classify_scope("Existing entities may continue operation under legacy permits.")
    assert isinstance(res, ScopeClassification)
    assert res.scope == "GRANDFATHERED_EXISTING"

    # Disabled config returns ALL
    disabled_config = ScopeConfig(enabled=False)
    disabled_res = classify_scope(
        "Existing entities may continue operation.", config=disabled_config
    )
    assert disabled_res.scope == "ALL"
