"""Unit and benchmark tests for FEAT-081: Supported-Claim Faithfulness Evaluator.

Validates:
1. FaithfulnessConfig defaults and exact mathematical formula (Faithfulness = Supported / Total).
2. Atomic claim decomposition and preamble / citation bracket stripping.
3. Natural language entailment detection across numerical, entity, and negation polarities.
4. Fail-closed rejection of unfaithful answers with Prometheus telemetry updates.
5. 100-answer evaluation benchmark achieving >= 98% hallucination detection accuracy.
6. Execution latency <= 35.0ms on multi-core CPU.
"""

from __future__ import annotations

import time

import pytest

from app.api import metrics
from app.api.models import Passage
from app.evals.faithfulness import (
    ClaimDecomposer,
    ClaimEntailmentEvaluator,
    FaithfulnessConfig,
    FaithfulnessEvaluator,
    get_default_faithfulness_evaluator,
)
from app.evals.scorers import faithfulness_score


def test_faithfulness_config_defaults() -> None:
    """Validate default configuration values for FEAT-081."""
    cfg = FaithfulnessConfig()
    assert cfg.min_score_threshold == 0.98
    assert cfg.nli_model == "deberta-v3-small-nli"
    assert cfg.enable_nli is True
    assert cfg.entailment_threshold == 0.65

    # Verify singleton helper and standalone entailment evaluator
    evaluator = get_default_faithfulness_evaluator()
    assert isinstance(evaluator, FaithfulnessEvaluator)
    assert get_default_faithfulness_evaluator() is evaluator

    entailer = ClaimEntailmentEvaluator()
    score, reason = entailer.evaluate_claim_against_passage("test claim", "test claim")
    assert score == 1.0


def test_faithfulness_score_formula() -> None:
    """Verify exact formula Faithfulness = Supported Claims / Total Claims."""
    assert faithfulness_score(5, 5) == 1.0
    assert faithfulness_score(4, 5) == 0.8
    assert faithfulness_score(1, 4) == 0.25
    assert faithfulness_score(0, 5) == 0.0
    assert faithfulness_score(0, 0) == 1.0  # Safe identity when no claims are asserted
    assert faithfulness_score(-1, 5) == 0.0


def test_claim_decomposition() -> None:
    """Verify answer prose is decomposed into atomic claims without preambles or citations."""
    decomposer = ClaimDecomposer()

    raw_answer = (
        "According to the Master Direction, all Non-Banking Financial Companies must maintain "
        "a minimum CRAR of 15% [ID:1]. Furthermore, Tier 1 capital shall not be less than 10% [ID:2]. "
        "Here is the summary: Net Owned Funds must be at least Rs 2 crore."
    )

    claims = decomposer.decompose(raw_answer)
    assert len(claims) >= 2
    # Verify citations like [ID:1] are stripped
    for c in claims:
        assert "[ID:" not in c
        assert "**" not in c
    # Check key claim presence
    assert any("CRAR of 15%" in c for c in claims)
    assert any("Tier 1 capital" in c for c in claims)


def test_claim_entailment_grounded_answer() -> None:
    """Verify fully supported answer scores 1.0 and is marked faithful."""
    evaluator = FaithfulnessEvaluator(FaithfulnessConfig(min_score_threshold=0.98))

    passage = Passage(
        rank=1,
        chunk_id="chunk-crar-15",
        document_id="doc-rbi-nbfc",
        source="RBI",
        canonical_url=None,
        score=0.95,
        arm_ranks={"dense": 1, "bm25": 1},
        char_start=0,
        char_end=200,
        text=(
            "Every non-banking financial company shall maintain a minimum capital ratio "
            "consisting of Tier I and Tier II capital which shall not be less than 15 percent "
            "of its aggregate risk weighted assets. Tier I capital shall not be less than 10 percent."
        ),
    )

    answer = (
        "Non-banking financial companies must maintain a minimum capital ratio of 15 percent "
        "of aggregate risk weighted assets [ID:1]. Tier I capital shall not be less than 10 percent [ID:1]."
    )

    result = evaluator.evaluate(answer, [passage])
    assert result.is_faithful is True
    assert result.score == 1.0
    assert result.total_claims == 2
    assert result.supported_claims == 2
    assert len(result.unsupported_claims) == 0


def test_claim_entailment_numerical_hallucination() -> None:
    """Verify numerical alteration (15% -> 12%) is caught as unsupported claim."""
    evaluator = FaithfulnessEvaluator(FaithfulnessConfig(min_score_threshold=0.98))

    passage = Passage(
        rank=1,
        chunk_id="chunk-crar-15",
        document_id="doc-rbi-nbfc",
        source="RBI",
        canonical_url=None,
        score=0.95,
        arm_ranks={"dense": 1},
        char_start=0,
        char_end=200,
        text="Every non-banking financial company shall maintain a minimum capital ratio of 15 percent.",
    )

    # Hallucinated number 12 percent
    answer = "Non-banking financial companies must maintain a minimum capital ratio of 12 percent."

    result = evaluator.evaluate(answer, [passage])
    assert result.is_faithful is False
    assert result.score < 0.98
    assert result.supported_claims == 0
    assert len(result.unsupported_claims) == 1
    assert "12 percent" in result.unsupported_claims[0]


def test_claim_entailment_entity_substitution() -> None:
    """Verify entity substitution (Payment Aggregator -> Commercial Bank) is flagged as unfaithful."""
    evaluator = FaithfulnessEvaluator(FaithfulnessConfig(min_score_threshold=0.98))

    passage = Passage(
        rank=1,
        chunk_id="chunk-pa-6h",
        document_id="doc-rbi-pa",
        source="RBI",
        canonical_url=None,
        score=0.92,
        arm_ranks={"dense": 1},
        char_start=0,
        char_end=150,
        text="A Payment Aggregator shall report all cyber security incidents to RBI within 6 hours of detection.",
    )

    # Substituted entity Commercial Bank
    answer = "A Commercial Bank shall report all cyber security incidents to RBI within 6 hours of detection."

    result = evaluator.evaluate(answer, [passage])
    assert result.is_faithful is False
    assert result.score < 0.98
    assert len(result.unsupported_claims) == 1


def test_claim_entailment_polarity_inversion() -> None:
    """Verify fact inversion (required -> not required) is caught as a contradiction."""
    evaluator = FaithfulnessEvaluator(FaithfulnessConfig(min_score_threshold=0.98))

    passage = Passage(
        rank=1,
        chunk_id="chunk-approval-req",
        document_id="doc-rbi-approval",
        source="RBI",
        canonical_url=None,
        score=0.90,
        arm_ranks={"bm25": 1},
        char_start=0,
        char_end=100,
        text="Prior approval of the Reserve Bank is mandatory before appointing a foreign director.",
    )

    # Inverted polarity: "not required"
    answer = (
        "Prior approval of the Reserve Bank is not required before appointing a foreign director."
    )

    result = evaluator.evaluate(answer, [passage])
    assert result.is_faithful is False
    assert result.score < 0.98
    assert len(result.unsupported_claims) == 1


def test_input_validation() -> None:
    """Verify evaluator validates non-empty inputs."""
    evaluator = FaithfulnessEvaluator()
    with pytest.raises(ValueError, match="answer must be non-empty"):
        evaluator.evaluate("", ["some passage"])

    with pytest.raises(ValueError, match="at least 1 citation must be provided"):
        evaluator.evaluate("Valid answer text.", [])


def test_abstention_declarations_are_faithful() -> None:
    """Answers declaring insufficient evidence have zero unsupported claims and are marked faithful."""
    evaluator = FaithfulnessEvaluator()
    passage = "Some regulatory context."

    answer = "Insufficient evidence: the provided regulatory documents do not contain sufficient evidence."
    result = evaluator.evaluate(answer, [passage])
    assert result.is_faithful is True
    assert result.score == 1.0
    assert result.total_claims == 0


def test_100_answers_benchmark_accuracy() -> None:
    """Benchmark: Evaluate 100 answers (50 grounded, 50 hallucinated) with >= 98% accuracy."""
    evaluator = FaithfulnessEvaluator(FaithfulnessConfig(min_score_threshold=0.98))

    base_passages = [
        "Housing Finance Companies must maintain Net Owned Fund of Rs 25 crore.",
        "Scheduled Commercial Banks must classify assets as NPA after 90 days of overdue interest.",
        "Primary Urban Co-operative Banks shall report fraud above Rs 1 lakh to Regional Office within 3 weeks.",
        "Small Finance Banks must extend 75 percent of Adjusted Net Bank Credit to Priority Sector.",
        "Prepaid Payment Instruments issuers shall maintain an escrow account with a Scheduled Commercial Bank.",
    ]

    # Generate 50 grounded answers
    grounded_cases = []
    for i in range(50):
        idx = i % len(base_passages)
        p = base_passages[idx]
        grounded_cases.append((p, p))

    # Generate 50 hallucinated answers (subtle number mutations, entity swaps, negations)
    hallucinated_cases = []
    for i in range(50):
        idx = i % len(base_passages)
        p = base_passages[idx]
        if idx == 0:
            ans = "Housing Finance Companies must maintain Net Owned Fund of Rs 10 crore."
        elif idx == 1:
            ans = "Scheduled Commercial Banks must classify assets as NPA after 60 days of overdue interest."
        elif idx == 2:
            ans = "Payments Banks shall report fraud above Rs 1 lakh to Regional Office within 3 weeks."
        elif idx == 3:
            ans = "Small Finance Banks are not required to extend credit to Priority Sector."
        else:
            ans = "Prepaid Payment Instruments issuers may maintain escrow accounts with foreign banks."
        hallucinated_cases.append((ans, p))

    correct_predictions = 0

    for ans, p in grounded_cases:
        res = evaluator.evaluate(ans, [p])
        if res.is_faithful is True:
            correct_predictions += 1

    for ans, p in hallucinated_cases:
        res = evaluator.evaluate(ans, [p])
        if res.is_faithful is False:
            correct_predictions += 1

    accuracy = correct_predictions / 100.0
    # Spec threshold: >= 98%
    assert accuracy >= 0.98, f"Expected benchmark accuracy >= 0.98, got {accuracy:.4f}"


def test_faithfulness_scoring_latency_budget() -> None:
    """Verify evaluation execution latency <= 35.0ms on multi-core CPU."""
    evaluator = FaithfulnessEvaluator()
    passage = (
        "Every non-banking financial company shall maintain a minimum capital ratio "
        "consisting of Tier I and Tier II capital which shall not be less than 15 percent "
        "of its aggregate risk weighted assets. Tier I capital shall not be less than 10 percent."
    )
    answer = (
        "Non-banking financial companies must maintain a minimum capital ratio of 15 percent [ID:1]. "
        "Tier I capital must not be less than 10 percent [ID:1]."
    )

    t0 = time.perf_counter()
    res = evaluator.evaluate(answer, [passage])
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.is_faithful is True
    # Spec threshold: <= 35.0ms
    assert latency_ms <= 35.0, f"Expected latency <= 35.0ms, got {latency_ms:.2f}ms"


def test_prometheus_metrics_registration() -> None:
    """Verify Prometheus faithfulness metrics are emitted and observable."""
    metrics.MEAN_ANSWER_FAITHFULNESS_SCORE.set(0.95)
    metrics.UNFAITHFUL_ANSWERS_REJECTED_TOTAL.inc()

    body, _ = metrics.render()
    assert b"docscout_mean_answer_faithfulness_score" in body
    assert b"docscout_unfaithful_answers_rejected_total" in body
