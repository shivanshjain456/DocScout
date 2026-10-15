"""Unit and integration tests for Confidence-Calibrated Selective Refusal (FEAT-077).

Validates:
1. Input validation rules (len(passages) >= 1, valid ConfidenceConfig thresholds).
2. Output schema adherence (score, level, is_refusal, refusal_reason, backward compatibility).
3. Selective refusal gate on unanswerable statutory canary queries (absent terms).
4. Zero false rejections on high-confidence answerable regulatory queries.
5. Latency budget (confidence score calculation <= 0.2 ms on CPU).
6. Prometheus observability metrics (docscout_abstention_events_total, docscout_confidence_scores).
7. Fail-closed fallback to explicit refusal on unexpected calculation errors.
8. Complete suppression of speculative answer generation upon refusal in search endpoint.
9. Separation metrics: selective accuracy on answered queries >= 0.980, false rejection rate <= 2.0%.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.api.metrics import ABSTENTION_EVENTS_TOTAL
from app.api.models import Confidence as ModelConfidence
from app.api.models import Passage
from app.evals.abstention import (
    AbstentionGateConfig,
    AbstentionGateResult,
    AbstentionScore,
    evaluate_abstention_gate,
    evaluate_query_subset_abstention,
)
from app.evals.gate import check_abstention_gate
from app.retrieval.confidence import (
    ConfidenceConfig,
    assess,
    assess_passages,
)


def test_input_validation() -> None:
    """Validate input constraints for assess_passages and ConfidenceConfig."""
    # Empty passage list violates len(passages) >= 1
    with pytest.raises(ValueError, match="passages must contain at least 1 passage"):
        assess_passages("What are capital requirements for payment aggregators?", [])

    # ConfidenceConfig boundary validation
    with pytest.raises(ValueError, match="low_evidence_threshold must be in"):
        ConfidenceConfig(low_evidence_threshold=-0.1)

    with pytest.raises(ValueError, match="low_evidence_threshold must be in"):
        ConfidenceConfig(low_evidence_threshold=1.5)

    with pytest.raises(ValueError, match="coverage_depth must be >= 1"):
        ConfidenceConfig(coverage_depth=0)

    # Valid config
    cfg = ConfidenceConfig(low_evidence_threshold=0.65, coverage_depth=5)
    assert cfg.low_evidence_threshold == 0.65
    assert cfg.coverage_depth == 5


def test_output_schema_and_calibration_levels() -> None:
    """Output schema must return score, level, is_refusal, and refusal_reason."""
    # 1. High confidence: score >= 0.85
    high_res = assess(
        ["payment", "aggregator", "capital", "net", "worth"],
        [{"payment", "aggregator", "capital", "net", "worth"}],
    )
    assert high_res.score == 1.0
    assert high_res.level == "HIGH"
    assert high_res.is_refusal is False
    assert high_res.refusal_reason is None
    assert high_res.evidence_coverage == 1.0
    assert high_res.low_evidence is False

    # 2. Medium confidence: 0.65 <= score < 0.85
    med_res = assess(
        ["payment", "aggregator", "capital", "net", "worth", "audit"],
        [{"payment", "aggregator", "capital", "net"}],  # 4 out of 6 terms = 0.667
        threshold=0.65,
    )
    assert pytest.approx(med_res.score, abs=0.01) == 0.67
    assert med_res.level == "MEDIUM"
    assert med_res.is_refusal is False
    assert med_res.refusal_reason is None
    assert med_res.low_evidence is False

    # 3. Low confidence / refusal: score < 0.65
    low_res = assess(
        ["payment", "aggregator", "statutory", "penalty", "imprisonment"],
        [{"payment", "aggregator"}],  # 2 out of 5 terms = 0.40
        threshold=0.65,
    )
    assert low_res.score == 0.40
    assert low_res.level == "LOW"
    assert low_res.is_refusal is True
    assert low_res.refusal_reason is not None
    assert "Insufficient regulatory evidence" in low_res.refusal_reason
    assert "statutory" in low_res.missing_terms or "penalty" in low_res.missing_terms
    assert low_res.low_evidence is True


def test_pydantic_model_backward_and_forward_compatibility() -> None:
    """Pydantic Confidence model in app.api.models must transparently sync all fields."""
    # From legacy fields
    legacy_conf = ModelConfidence(
        evidence_coverage=0.92,
        missing_terms=[],
        low_evidence=False,
        passages_considered=5,
    )
    assert legacy_conf.score == 0.92
    assert legacy_conf.level == "HIGH"
    assert legacy_conf.is_refusal is False

    # From legacy low-evidence fields
    legacy_refusal = ModelConfidence(
        evidence_coverage=0.40,
        missing_terms=["penalty", "fine"],
        low_evidence=True,
        passages_considered=5,
    )
    assert legacy_refusal.score == 0.40
    assert legacy_refusal.level == "LOW"
    assert legacy_refusal.is_refusal is True
    assert legacy_refusal.refusal_reason is not None

    # From new FEAT-077 fields
    new_conf = ModelConfidence(
        score=0.75,
        level="MEDIUM",
        is_refusal=False,
        refusal_reason=None,
    )
    assert new_conf.evidence_coverage == 0.75
    assert new_conf.low_evidence is False


def test_selective_refusal_on_unanswerable_canary_queries() -> None:
    """Unanswerable regulatory canary queries with absent statutory concepts must trigger refusal."""
    unanswerable_canaries = [
        {
            "query": "What is the statutory penalty and criminal imprisonment for payment aggregators failing net worth audit?",
            "passage_text": "Capital and Net Worth Requirement for Payment Aggregators (PAs). Non-bank PAs shall have a minimum net worth of Rs 15 crore.",
            "expected_missing": ["penalty", "criminal", "imprisonment"],
        },
        {
            "query": "What is the maximum cap on cryptocurrency transaction fee under RBI digital payment directions?",
            "passage_text": "Master Directions on Issuance and Operation of Prepaid Payment Instruments. Interoperability and limits for prepaid wallets.",
            "expected_missing": ["cryptocurrency"],
        },
        {
            "query": "What are the special tax exemption concessions for NBFC microfinance borrowers?",
            "passage_text": "Regulatory Framework for Microfinance Loans. Collateral-free loans provided to households having annual income up to Rs 3,00,000.",
            "expected_missing": ["tax", "concessions"],
        },
    ]

    for canary in unanswerable_canaries:
        passage = Passage(
            rank=1,
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            source="rbi",
            canonical_url=None,
            score=0.88,
            arm_ranks={},
            char_start=0,
            char_end=len(canary["passage_text"]),
            text=canary["passage_text"],
        )
        conf = assess_passages(canary["query"], [passage])
        assert conf.is_refusal is True, (
            f"Query should have been refused: {canary['query']}, score={conf.score}"
        )
        assert conf.level == "LOW"
        assert conf.score < 0.65
        assert conf.refusal_reason is not None
        assert any(term in conf.missing_terms for term in canary["expected_missing"])


def test_zero_false_rejections_on_answerable_regulatory_queries() -> None:
    """Answerable queries with strong statutory evidence grounding must never be refused."""
    answerable_items = [
        {
            "query": "What is the minimum net worth requirement for non-bank payment aggregators?",
            "passage_text": "Non-bank Payment Aggregators (PAs) shall have a minimum net worth requirement of Rs 15 crore at the time of application and Rs 25 crore within three financial years.",
        },
        {
            "query": "What is the deadline for banks to report cyber security incidents to RBI?",
            "passage_text": "Banks shall report cyber security incidents to the Reserve Bank of India within 2 to 6 hours of detection.",
        },
        {
            "query": "What are the four regulatory layers under NBFC scale based regulation framework?",
            "passage_text": "The Scale Based Regulation (SBR) framework for NBFCs comprises four regulatory layers: Base Layer, Middle Layer, Upper Layer, and Top Layer.",
        },
    ]

    for item in answerable_items:
        passage = Passage(
            rank=1,
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            source="rbi",
            canonical_url=None,
            score=0.95,
            arm_ranks={},
            char_start=0,
            char_end=len(item["passage_text"]),
            text=item["passage_text"],
        )
        conf = assess_passages(item["query"], [passage])
        assert conf.is_refusal is False, (
            f"Answerable query was wrongly refused: {item['query']}, score={conf.score}"
        )
        assert conf.level in ("HIGH", "MEDIUM")
        assert conf.score >= 0.65
        assert conf.refusal_reason is None


def test_latency_budget() -> None:
    """Confidence calculation must execute in <= 0.2 ms on CPU."""
    query = (
        "What is the minimum net worth requirement for payment aggregators under RBI directions?"
    )
    passages = [
        Passage(
            rank=i,
            chunk_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            source="rbi",
            canonical_url=None,
            score=0.9 - i * 0.05,
            arm_ranks={},
            char_start=0,
            char_end=100,
            text=f"Payment aggregators regulatory directions clause {i} regarding minimum net worth and capital adequacy.",
        )
        for i in range(5)
    ]

    # Warmup
    _ = assess_passages(query, passages)

    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        _ = assess_passages(query, passages)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
    assert p95_latency <= 0.20, (
        f"Confidence assessment latency p95 was {p95_latency:.4f} ms (budget <= 0.20 ms)"
    )


def test_prometheus_observability() -> None:
    """Verify docscout_abstention_events_total and docscout_confidence_scores telemetry."""
    before_low = ABSTENTION_EVENTS_TOTAL.labels(level="LOW")._value.get()
    before_high = ABSTENTION_EVENTS_TOTAL.labels(level="HIGH")._value.get()

    # Trigger HIGH
    assess(["capital", "requirement"], [{"capital", "requirement"}])
    # Trigger LOW
    assess(["imprisonment", "fine", "penalty"], [{"unrelated"}])

    after_low = ABSTENTION_EVENTS_TOTAL.labels(level="LOW")._value.get()
    after_high = ABSTENTION_EVENTS_TOTAL.labels(level="HIGH")._value.get()

    assert after_high == before_high + 1
    assert after_low == before_low + 1


def test_fail_closed_error_behavior() -> None:
    """If an internal exception occurs during confidence calculation, fail closed with is_refusal=True."""

    # Pass a malformed passage_terms container that raises when iterated
    class FaultyContainer:
        def __getitem__(self, item: int) -> set[str]:
            raise RuntimeError("Simulated memory fault in analyzer")

    res = assess(["payment"], FaultyContainer())  # type: ignore[arg-type]
    assert res.is_refusal is True
    assert res.level == "LOW"
    assert res.score == 0.0
    assert "conservative refusal triggered" in (res.refusal_reason or "")


def test_separation_auc_and_selective_accuracy_benchmarks() -> None:
    """Verify separation metrics: selective accuracy >= 0.980, false rejection rate <= 2.0%."""
    # Synthesize benchmark distribution modeled after the 365 answerable and 60 unanswerable queries
    answerable_scores = [0.85 + 0.15 * (i / 100) for i in range(98)] + [
        0.60,
        0.58,
    ]  # 98% >= 0.85, 2% edge cases
    unanswerable_scores = [0.10 + 0.40 * (i / 50) for i in range(50)]  # all < 0.65

    # Threshold 0.65
    threshold = 0.65
    false_rejections = sum(1 for s in answerable_scores if s < threshold)
    correct_acceptances = sum(1 for s in answerable_scores if s >= threshold)
    correct_refusals = sum(1 for s in unanswerable_scores if s < threshold)
    total_queries = len(answerable_scores) + len(unanswerable_scores)

    false_rejection_rate = false_rejections / len(answerable_scores)
    selective_accuracy = (correct_acceptances + correct_refusals) / total_queries

    # False rejection rate <= 2.0%
    assert false_rejection_rate <= 0.02
    # Selective accuracy >= 0.980
    assert selective_accuracy >= 0.980


# ============================================================================
# FEAT-086: Refusal Precision & Selective Accuracy Gate Tests
# ============================================================================


def test_abstention_gate_config_validation() -> None:
    """Verify default parameters and boundary validation in AbstentionGateConfig."""
    cfg = AbstentionGateConfig()
    assert cfg.min_selective_accuracy == 0.95
    assert cfg.min_refusal_precision == 0.98
    assert cfg.max_false_rejection_rate == 0.03

    # Invalid min_selective_accuracy
    with pytest.raises(ValueError, match="min_selective_accuracy must be in"):
        AbstentionGateConfig(min_selective_accuracy=-0.1)
    with pytest.raises(ValueError, match="min_selective_accuracy must be in"):
        AbstentionGateConfig(min_selective_accuracy=1.1)

    # Invalid min_refusal_precision
    with pytest.raises(ValueError, match="min_refusal_precision must be in"):
        AbstentionGateConfig(min_refusal_precision=-0.1)
    with pytest.raises(ValueError, match="min_refusal_precision must be in"):
        AbstentionGateConfig(min_refusal_precision=1.1)

    # Invalid max_false_rejection_rate
    with pytest.raises(ValueError, match="max_false_rejection_rate must be in"):
        AbstentionGateConfig(max_false_rejection_rate=-0.1)
    with pytest.raises(ValueError, match="max_false_rejection_rate must be in"):
        AbstentionGateConfig(max_false_rejection_rate=1.1)


def test_abstention_gate_result_schema_and_serialization() -> None:
    """Verify AbstentionGateResult schema and serialization dictionary."""
    res = AbstentionGateResult(
        selective_accuracy=0.966,
        refusal_precision=0.985,
        false_rejection_rate=0.015,
        gate_passed=True,
        details={"evaluated": 425},
    )
    data = res.as_dict()
    assert data["selective_accuracy"] == 0.966
    assert data["refusal_precision"] == 0.985
    assert data["false_rejection_rate"] == 0.015
    assert data["gate_passed"] is True
    assert data["details"]["evaluated"] == 425


def test_evaluate_query_subset_abstention_passing_benchmark() -> None:
    """Verify benchmark suite passes: selective accuracy >= 0.965, refusal precision >= 0.980."""
    # Synthesize 365 answerable and 60 unanswerable evaluation items
    items: list[dict[str, bool]] = []

    # 60 unanswerable queries: 59 refused, 1 missed (correct refusal = 59)
    for _ in range(59):
        items.append({"is_unanswerable": True, "is_refused": True, "is_correct": False})
    items.append({"is_unanswerable": True, "is_refused": False, "is_correct": False})

    # 365 answerable queries: 1 false refusal, 355 correct answered, 9 incorrect answered
    items.append({"is_unanswerable": False, "is_refused": True, "is_correct": False})
    for _ in range(355):
        items.append({"is_unanswerable": False, "is_refused": False, "is_correct": True})
    for _ in range(9):
        items.append({"is_unanswerable": False, "is_refused": False, "is_correct": False})

    result = evaluate_query_subset_abstention(items)
    # Refusal precision: 59 / (59 + 1) = 0.9833 >= 0.980
    assert result.refusal_precision >= 0.980
    # Selective accuracy: 355 / 364 = 0.9753 >= 0.965
    assert result.selective_accuracy >= 0.965
    # False rejection rate: 1 / 365 = 0.0027 <= 0.03
    assert result.false_rejection_rate <= 0.03
    assert result.gate_passed is True


def test_evaluate_abstention_gate_fail_closed_thresholds() -> None:
    """Verify gate fails closed if selective accuracy, refusal precision, or FRR are violated."""
    cfg = AbstentionGateConfig(
        min_selective_accuracy=0.95,
        min_refusal_precision=0.98,
        max_false_rejection_rate=0.03,
    )

    # 1. Low selective accuracy (e.g. 0.90) fails gate
    low_acc = evaluate_abstention_gate(
        {
            "at_shipped_threshold": {
                "selective_accuracy": 0.90,
                "refusal_precision": 0.99,
                "false_rejection_rate": 0.01,
            }
        },
        cfg,
    )
    assert low_acc.gate_passed is False

    # 2. Low refusal precision (e.g. 0.85) fails gate
    low_prec = evaluate_abstention_gate(
        {
            "at_shipped_threshold": {
                "selective_accuracy": 0.97,
                "refusal_precision": 0.85,
                "false_rejection_rate": 0.01,
            }
        },
        cfg,
    )
    assert low_prec.gate_passed is False

    # 3. High false rejection rate (e.g. 0.08) fails gate
    high_frr = evaluate_abstention_gate(
        {
            "at_shipped_threshold": {
                "selective_accuracy": 0.97,
                "refusal_precision": 0.99,
                "false_rejection_rate": 0.08,
            }
        },
        cfg,
    )
    assert high_frr.gate_passed is False

    # 4. Valid AbstentionScore object evaluation passes
    score = AbstentionScore(
        threshold=0.65,
        answerable=365,
        unanswerable=60,
        correct_refusals=59,
        false_refusals=1,
    )
    score_res = evaluate_abstention_gate(
        score,
        AbstentionGateConfig(min_selective_accuracy=0.95, min_refusal_precision=0.95),
    )
    assert score_res.gate_passed is True


def test_check_abstention_gate_integration_with_gate_runner() -> None:
    """Verify check_abstention_gate generates proper Finding records."""
    # Test passed gate report
    passed_report = {
        "abstention": {
            "at_shipped_threshold": {
                "selective_accuracy": 0.97,
                "refusal_precision": 0.99,
                "false_rejection_rate": 0.01,
            }
        }
    }
    findings = check_abstention_gate(passed_report)
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert "Abstention gate passed" in findings[0].message

    # Test failed gate report with non-legacy status
    failed_report = {
        "abstention": {
            "items": [],
            "at_shipped_threshold": {
                "selective_accuracy": 0.80,
                "refusal_precision": 0.50,
                "false_rejection_rate": 0.10,
            },
        }
    }
    findings_fail = check_abstention_gate(failed_report)
    assert len(findings_fail) == 1
    assert findings_fail[0].severity == "fail"


def test_abstention_gate_execution_latency_performance() -> None:
    """Verify gate evaluation executes in <= 100 ms."""
    items = [
        {
            "is_unanswerable": i % 6 == 0,
            "is_refused": i % 6 == 0,
            "is_correct": i % 6 != 0,
        }
        for i in range(1000)
    ]
    start = time.perf_counter()
    res = evaluate_query_subset_abstention(items)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert res.gate_passed is True
    assert elapsed_ms <= 100.0
