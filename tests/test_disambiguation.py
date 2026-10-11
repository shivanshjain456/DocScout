"""Unit and integration tests for Context-Aware Token Disambiguation Engine (FEAT-011).

Verifies:
1. 100% correct resolution of all 8 canonical disambiguation rules from term-taxonomy.json.
2. Statutory disambiguation rules (RE, PA) for RBI regulatory intelligence.
3. Zero false positives on queries lacking ambiguous terms.
4. Safe pass-through fallback when confidence < 0.70 or when disabled.
5. Latency <= 0.8 ms p95 performance limit.
6. Domain hint steering and metric observation.
"""

from __future__ import annotations

import time

import pytest

from app.api.models import SearchRequest
from app.retrieval.disambiguation import (
    CANONICAL_RULES,
    DisambiguationConfig,
    TokenDisambiguator,
    get_token_disambiguator,
)
from app.retrieval.types import RetrievalConfig


def test_disambiguator_singleton_and_defaults() -> None:
    disambiguator = get_token_disambiguator()
    assert disambiguator is not None
    assert len(disambiguator.rules) == len(CANONICAL_RULES)
    assert disambiguator.config.enabled is True
    assert disambiguator.config.min_confidence == 0.70


def test_canonical_coverage_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Structural coverage
    q_struct = "branch coverage analysis for python unit test suite"
    mod_struct, res_struct = disambiguator.disambiguate_query(q_struct)
    assert len(res_struct) == 1
    assert res_struct[0].token == "coverage"
    assert res_struct[0].resolved_sense == "Structural coverage"
    assert res_struct[0].canonical_term == "Branch / Decision Coverage"
    assert res_struct[0].confidence >= 0.70
    assert "structural code coverage" in mod_struct

    # 2. Functional coverage
    q_func = "functional coverage model verification in systemverilog uvm"
    mod_func, res_func = disambiguator.disambiguate_query(q_func)
    assert len(res_func) == 1
    assert res_func[0].token == "coverage"
    assert res_func[0].resolved_sense == "Functional coverage"
    assert res_func[0].canonical_term == "Functional Coverage / Coverage-Driven Verification"
    assert res_func[0].confidence >= 0.70
    assert "functional verification coverage" in mod_func


def test_canonical_canary_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Canary release
    q_deploy = "canary deployment rollout with argo and istio traffic routing"
    mod_deploy, res_deploy = disambiguator.disambiguate_query(q_deploy)
    assert len(res_deploy) == 1
    assert res_deploy[0].token == "canary"
    assert res_deploy[0].resolved_sense == "Canary release"
    assert res_deploy[0].canonical_term == "Canary Release"
    assert res_deploy[0].confidence >= 0.70
    assert "canary release" in mod_deploy

    # 2. Canary token
    q_token = "canary token planted in prompt to detect secret exfiltration leak"
    mod_token, res_token = disambiguator.disambiguate_query(q_token)
    assert len(res_token) == 1
    assert res_token[0].token == "canary"
    assert res_token[0].resolved_sense == "Canary token"
    assert res_token[0].canonical_term == "Canary Token Assertions"
    assert res_token[0].confidence >= 0.70
    assert "canary token leak detection" in mod_token


def test_canonical_dora_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. DORA delivery metrics
    q_metrics = "dora delivery metrics lead time for changes and deployment frequency"
    mod_metrics, res_metrics = disambiguator.disambiguate_query(q_metrics)
    assert len(res_metrics) == 1
    assert res_metrics[0].token == "DORA"
    assert res_metrics[0].resolved_sense == "DORA delivery metrics"
    assert res_metrics[0].canonical_term == "DORA Metrics (five keys)"
    assert res_metrics[0].confidence >= 0.70
    assert "DORA delivery metrics" in mod_metrics

    # 2. EU DORA regulation
    q_reg = "eu dora digital operational resilience act for financial entities compliance"
    mod_reg, res_reg = disambiguator.disambiguate_query(q_reg)
    assert len(res_reg) == 1
    assert res_reg[0].token == "DORA"
    assert res_reg[0].resolved_sense == "EU DORA regulation"
    assert res_reg[0].canonical_term == "EU DORA (Digital Operational Resilience Act)"
    assert res_reg[0].confidence >= 0.70
    assert "DORA regulation" in mod_reg


def test_canonical_sil_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Software-in-the-Loop simulation
    q_sim = "automotive plant simulation with sil in the loop on host"
    mod_sim, res_sim = disambiguator.disambiguate_query(q_sim)
    assert len(res_sim) == 1
    assert res_sim[0].token == "SIL"
    assert res_sim[0].resolved_sense == "Software-in-the-Loop"
    assert res_sim[0].canonical_term == "Software-in-the-Loop (SIL)"
    assert res_sim[0].confidence >= 0.70
    assert "Software-in-the-Loop simulation" in mod_sim

    # 2. Safety Integrity Level
    q_safety = "iec 61508 safety integrity level sil 3 hazard risk classification"
    mod_safety, res_safety = disambiguator.disambiguate_query(q_safety)
    assert len(res_safety) == 1
    assert res_safety[0].token == "SIL"
    assert res_safety[0].resolved_sense == "Safety Integrity Level"
    assert res_safety[0].canonical_term == "Safety Integrity Level (SIL 1-4)"
    assert res_safety[0].confidence >= 0.70
    assert "Safety Integrity Level classification" in mod_safety


def test_canonical_mttr_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Mean Time To Repair/Recover
    q_rec = "service outage recovery mttr downtime incident restoration sre"
    mod_rec, res_rec = disambiguator.disambiguate_query(q_rec)
    assert len(res_rec) == 1
    assert res_rec[0].token == "MTTR"
    assert res_rec[0].resolved_sense == "Mean Time To Repair/Recover"
    assert res_rec[0].canonical_term == "MTBF / MTTF / MTTR / MTTD / MTTA"
    assert res_rec[0].confidence >= 0.70
    assert "Mean Time To Recover" in mod_rec

    # 2. Mean Time To Remediate (vulnerability)
    q_vuln = "security mttr cve vulnerability patch fix sla audit"
    mod_vuln, res_vuln = disambiguator.disambiguate_query(q_vuln)
    assert len(res_vuln) == 1
    assert res_vuln[0].token == "MTTR"
    assert res_vuln[0].resolved_sense == "Mean Time To Remediate (vulnerability)"
    assert res_vuln[0].canonical_term == "Mean Time to Remediate (MTTR-vuln)"
    assert res_vuln[0].confidence >= 0.70
    assert "Mean Time To Remediate" in mod_vuln


def test_canonical_stress_testing_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Tester's capacity sense
    q_cap = "system load capacity stress testing breaking point benchmark"
    mod_cap, res_cap = disambiguator.disambiguate_query(q_cap)
    assert len(res_cap) == 1
    assert res_cap[0].token == "stress testing"
    assert res_cap[0].resolved_sense == "Tester's sense"
    assert res_cap[0].canonical_term == "Stress Testing"
    assert res_cap[0].confidence >= 0.70
    assert "capacity stress testing" in mod_cap

    # 2. Resilience fault injection sense
    q_fault = "chaos engineering fault injection stress testing kill pod perturbation"
    mod_fault, res_fault = disambiguator.disambiguate_query(q_fault)
    assert len(res_fault) == 1
    assert res_fault[0].token == "stress testing"
    assert res_fault[0].resolved_sense == "Resilience sense"
    assert res_fault[0].canonical_term == "Fault Injection"
    assert res_fault[0].confidence >= 0.70
    assert "resilience fault injection stress testing" in mod_fault


def test_canonical_integration_testing_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Software sense
    q_soft = "microservice api endpoint integration testing rest contracts"
    mod_soft, res_soft = disambiguator.disambiguate_query(q_soft)
    assert len(res_soft) == 1
    assert res_soft[0].token == "integration testing"
    assert res_soft[0].resolved_sense == "Software sense"
    assert res_soft[0].canonical_term == "Integration Testing"
    assert res_soft[0].confidence >= 0.70
    assert "software service integration testing" in mod_soft

    # 2. Hardware/embedded sense
    q_hw = "sensor actuator ecu hardware integration testing hil target"
    mod_hw, res_hw = disambiguator.disambiguate_query(q_hw)
    assert len(res_hw) == 1
    assert res_hw[0].token == "integration testing"
    assert res_hw[0].resolved_sense == "Hardware/embedded sense"
    assert res_hw[0].canonical_term == "Hardware-in-the-Loop (HIL)"
    assert res_hw[0].confidence >= 0.70
    assert "hardware-in-the-loop integration testing" in mod_hw


def test_canonical_shift_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # 1. Shift-left
    q_left = "shift-left testing in early developer ide pre-commit"
    mod_left, res_left = disambiguator.disambiguate_query(q_left)
    assert len(res_left) == 1
    assert res_left[0].token == "shift"
    assert res_left[0].resolved_sense == "Shift-left"
    assert res_left[0].canonical_term == "Shift-Left Testing"
    assert res_left[0].confidence >= 0.70
    assert "shift-left" in mod_left

    # 2. Shift-right
    q_right = "shift-right telemetry monitoring in production live traffic"
    mod_right, res_right = disambiguator.disambiguate_query(q_right)
    assert len(res_right) == 1
    assert res_right[0].token == "shift"
    assert res_right[0].resolved_sense == "Shift-right"
    assert res_right[0].canonical_term == "Shift-Right Testing"
    assert res_right[0].confidence >= 0.70
    assert "shift-right" in mod_right


def test_statutory_re_and_pa_disambiguation() -> None:
    disambiguator = get_token_disambiguator()

    # RE: Regulated Entity in RBI circular
    q_re = "rbi master direction on digital lending compliance for RE banks"
    mod_re, res_re = disambiguator.disambiguate_query(q_re)
    assert len(res_re) == 1
    assert res_re[0].token == "RE"
    assert res_re[0].resolved_sense == "Regulated Entity"
    assert "Regulated Entity (RE)" in mod_re

    # PA: Payment Aggregator
    q_pa = "rbi guidelines for payment aggregator PA escrow accounts and settlement"
    mod_pa, res_pa = disambiguator.disambiguate_query(q_pa)
    assert len(res_pa) == 1
    assert res_pa[0].token == "PA"
    assert res_pa[0].resolved_sense == "Payment Aggregator"
    assert "Payment Aggregator (PA)" in mod_pa


def test_zero_false_positive_on_unambiguous_queries() -> None:
    disambiguator = get_token_disambiguator()

    unambiguous_queries = [
        "what are the RBI guidelines on digital lending",
        "SEBI master circular on mutual funds risk management",
        "cyber security incident reporting framework requirements",
        "statutory audit checklist for non banking financial companies",
        "customer grievance redressal mechanism timeline",
    ]
    for q in unambiguous_queries:
        mod_q, results = disambiguator.disambiguate_query(q)
        assert mod_q == q, f"Query '{q}' was unexpectedly modified to '{mod_q}'"
        assert len(results) == 0


def test_low_confidence_fallback_unmodified() -> None:
    disambiguator = get_token_disambiguator()

    # Query with ambiguous token but absolutely zero context clues to distinguish senses
    q_bare = "what is dora"
    mod_q, results = disambiguator.disambiguate_query(q_bare)
    # Must safely pass through without modification
    assert mod_q == q_bare
    assert len(results) == 0


def test_disabled_disambiguator() -> None:
    disabled_config = DisambiguationConfig(enabled=False)
    disambiguator = TokenDisambiguator(disabled_config)

    q = "branch coverage analysis for python unit test suite"
    mod_q, results = disambiguator.disambiguate_query(q)
    assert mod_q == q
    assert len(results) == 0


def test_domain_hint_steering() -> None:
    disambiguator = get_token_disambiguator()

    # Ambiguous token with neutral context, steered by domain_hint
    q = "dora requirements for institutions"
    mod_q, results = disambiguator.disambiguate_query(q, domain_hint="compliance-governance-audit")
    assert len(results) == 1
    assert results[0].resolved_sense == "EU DORA regulation"


def test_latency_performance_budget() -> None:
    disambiguator = get_token_disambiguator()
    sample_queries = [
        "branch coverage in python unit tests",
        "functional coverage model for verification",
        "canary rollout with traffic routing",
        "canary token secret leak assertion",
        "dora delivery metrics lead time",
        "eu dora regulation compliance for ict",
        "sil automotive plant simulation",
        "iec 61508 safety integrity level sil 3",
        "mttr service outage recovery",
        "security mttr vulnerability patch",
    ]
    latencies: list[float] = []
    # Warmup
    for q in sample_queries:
        disambiguator.disambiguate_query(q)

    # Measure 50 iterations
    for _ in range(50):
        for q in sample_queries:
            t0 = time.perf_counter()
            disambiguator.disambiguate_query(q)
            latencies.append((time.perf_counter() - t0) * 1000.0)

    latencies.sort()
    p95_idx = int(0.95 * len(latencies))
    p95_latency_ms = latencies[p95_idx]

    # Specification requires p95 latency <= 0.8 ms
    assert p95_latency_ms <= 0.8, f"p95 latency {p95_latency_ms:.4f} ms exceeded 0.8 ms"


def test_schema_and_config_contracts() -> None:
    # 1. SearchRequest schema validation
    req = SearchRequest(query="rbi digital lending guidelines", enable_disambiguation=True)
    assert req.enable_disambiguation is True

    req_disabled = SearchRequest(
        query="rbi digital lending guidelines", enable_disambiguation=False
    )
    assert req_disabled.enable_disambiguation is False

    # 2. RetrievalConfig schema validation
    cfg = RetrievalConfig(
        name="test", enable_disambiguation=True, disambiguation_min_confidence=0.75
    )
    assert cfg.enable_disambiguation is True
    assert cfg.disambiguation_min_confidence == 0.75
    assert cfg.as_dict()["enable_disambiguation"] is True
    assert cfg.as_dict()["disambiguation_min_confidence"] == 0.75

    with pytest.raises(ValueError, match="disambiguation_min_confidence"):
        RetrievalConfig(name="invalid", disambiguation_min_confidence=1.5)
