"""Unit and benchmark evaluation test suite for Algorithmic & AI Impact Assessment Framework (FEAT-050)."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.algo_impact import (
    AlgoImpactConfig,
    AlgorithmicImpactEngine,
    get_default_algorithmic_impact_engine,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


# Benchmark Evaluation Dataset: 10 Algorithmic & AI System Specifications

BENCHMARK_SPEC_01_COMPLIANT_HFT = """
System Architecture & Risk Controls Specification: AlphaPulse HFT Market Maker
AlphaPulse is a high-frequency market making algorithm for equity derivatives.
1. Operational Resilience: Features an automated software kill switch and physical emergency stop button.
Upon market disconnect or latency spike (>10ms), the kill switch instantaneously cancels all outstanding orders
and halts new order generation across all exchange routing channels.
2. Model Validation: Comprehensive backtesting conducted across 5 years of historical tick-data.
Rigorous walk-forward validation and out-of-sample stress testing simulated Flash Crash events with -12% drops.
3. Feature Explainability: TreeSHAP pipeline generates feature importance vectors for bid-ask spread rationales.
4. Bias & Fairness: Demographic fairness audits confirm unbiased order placement.
5. Deterministic Audit Trail: WORM storage maintains an immutable audit trail with microsecond-level timestamps,
guaranteeing a 7-year retention period per SEBI norms.
6. Post-Deployment Telemetry: Real-time population stability index (PSI) and concept drift monitors evaluate distribution shifts.
7. Market Integrity: Pre-trade risk controls enforce strict order-to-trade ratio (OTR) limiters and fat-finger price bands.
8. External Assurance: Annual system audit executed by CERT-In empanelled independent system auditor.
"""

BENCHMARK_SPEC_02_NO_KILL_SWITCH = """
System Architecture & Strategy Specification: SwiftMomentum Algo
SwiftMomentum is an automated momentum scalping strategy.
1. Model Validation: Extensive backtesting and walk-forward analysis against historical tick-data with stress scenario tests.
2. Feature Explainability: Implements TreeSHAP explainability models for feature attribution.
3. Deterministic Audit Trail: Maintains immutable audit trail logging with 7-year retention period.
4. Telemetry: Continuous monitoring of concept drift and population stability index (PSI).
5. Market Integrity: Pre-trade price bands and order-to-trade ratio limiters enabled.
6. Operational Controls: Currently, no kill switch is implemented in the execution gateway.
Engineers rely on manual server termination if abnormal trading occurs.
7. External Assurance: Annual system audit scheduled with independent auditor.
"""

BENCHMARK_SPEC_03_COMPLIANT_CREDIT_AI = """
Credit Risk Model Governance Documentation: SmartLend AI
SmartLend is an automated credit risk and underwriting engine for personal retail lending.
1. Feature Attribution: Implements TreeSHAP and LIME surrogate models providing explainability and feature importance
for every credit denial and underwriting decision.
2. Fairness & Bias Auditing: Annual algorithmic bias evaluation measures disparate impact ratio, demographic parity,
and equalized odds across protected attributes to guarantee non-discriminatory lending.
3. Model Validation: Out-of-sample stress testing on distressed default loan cohorts alongside 5-fold cross-validation.
4. Continuous Drift: Population Stability Index (PSI) monitored continuously; alerts trigger when PSI exceeds 0.25.
5. Audit Logging: Full deterministic audit logging of applicant feature snapshots and decision scores with 7-year storage.
6. Circuit Breaker: Manual override switch and operational emergency stop halts automated loan approvals upon anomaly.
"""

BENCHMARK_SPEC_04_BIASED_BLACK_BOX_CREDIT = """
Credit Scoring Model Specification: BlackBox Credit
This automated neural network approves or rejects consumer credit applications.
1. Validation: Evaluated only using train accuracy without out-of-sample validation or stress testing.
2. Architecture: Deep black-box neural network without explainability or feature importance output.
3. Fairness: Bias auditing is not evaluated or checked, and demographic parity is omitted.
4. Logging: Decision logs are discarded after 30 days due to database storage constraints.
5. Drift: No drift monitoring or telemetry is configured for this deployment.
"""

BENCHMARK_SPEC_05_COMPLIANT_LLM_AGENT = """
Wealth Advisory Autonomous LLM Agent: FinAdvisor AI
1. Operational Guardrails: Integrated circuit breaker and emergency cutoff switch halting generation if hallucination occurs.
2. Decision Attribution: Feature importance and citation provenance provide explainability for financial recommendations.
3. Bias Mitigation: Regular demographic fairness audits evaluate parity of financial advisory outcomes.
4. Audit Logging: Microsecond timestamps log all prompts, completions, and retrieved contexts into immutable audit trail for 7 years.
5. Telemetry: Continuous monitoring tracks concept drift and distribution shifts in query embeddings.
"""

BENCHMARK_SPEC_06_UNMONITORED_LLM_AGENT = """
Experimental Customer Support Financial LLM
1. Model Setup: Deployed LLM agent answering user tax and investment queries.
2. Monitoring: Static model without monitoring or concept drift tracking.
3. Logging: Logs deleted immediately after session closure to protect user privacy.
4. Emergency Controls: Circuit breaker and kill switch not supported; session disconnects are handled by frontend.
5. Explainability: Decision rationale is unexplainable given high-dimensional embedding spaces.
"""

BENCHMARK_SPEC_07_COMPLIANT_FRAUD_ENGINE = """
Sentinel Real-Time Payment Fraud Engine Architecture
1. Operational Controls: Hardware circuit breaker halts automated block actions if false-positive anomaly rate exceeds 5%.
2. Model Validation: Backtesting over 100M historical UPI payment events with out-of-sample stress testing under surge traffic.
3. Explainability: Local SHAP values accompany every blocked payment event providing clear feature importance.
4. Telemetry: Real-time concept drift monitoring alerts operators on new merchant category anomalies.
5. Audit Records: Immutable logging of fraud scores with 7-year retention.
6. Market Integrity: Order rate limiters and pre-trade risk filters throttle transaction evaluation rates.
"""

BENCHMARK_SPEC_08_ROGUE_UNTHROTTLED_ALGO = """
Aggressive Liquidity Sweeper Algorithmic Strategy
1. Execution Logic: Sweeps depth of book across multiple venues.
2. Risk Bypass: Unthrottled ordering configured to maximize capture speed; no rate limit, price band, or OTR control applied.
3. Kill Switch: Emergency kill switch is present to shut down routing if connectivity fails.
4. Backtesting: Backtesting performed on historical tick-data.
5. Logging: Order and trade logging stored for 7 years.
"""

BENCHMARK_SPEC_09_GENERAL_ENTERPRISE_AI = """
Enterprise Decision Support AI Model Card
1. Operational Resilience: Emergency stop and manual override switch configured in the administration console.
2. Model Governance: Cross-validation and backtesting across historical business records.
3. Interpretability: Decision attribution and feature importance explanations generated for each automated inference.
4. Provenance: 7-year retention of model parameter weights and inference audit logs in WORM storage.
5. Monitoring: Continuous telemetry for data drift and population stability index (PSI) tracking.
6. Fairness: Regular demographic parity and fairness audits evaluate decision parity across protected groups.
7. Assurance: Independent annual system review conducted by CISA auditor.
"""

BENCHMARK_SPEC_10_UNTESTED_LIVE_ALGO = """
Dynamic Trading Engine v0.9 Beta
1. Operational Controls: Hardware kill switch installed and connected to broker API.
2. Validation: No backtesting was conducted; algorithm was tested only in live production markets.
3. Logging: Parameter state logging enabled with 7-year retention.
4. Telemetry: Basic latency anomaly logging in place.
"""


# --- Unit Tests ---


def test_engine_singleton() -> None:
    engine1 = get_default_algorithmic_impact_engine()
    engine2 = get_default_algorithmic_impact_engine()
    assert engine1 is engine2
    assert isinstance(engine1, AlgorithmicImpactEngine)
    assert len(engine1.rules) >= 8


def test_validation_empty_system_name() -> None:
    engine = get_default_algorithmic_impact_engine()
    with pytest.raises(ValueError, match="system_name must be non-empty"):
        engine.evaluate(
            system_name="",
            model_type="algorithmic_trading",
            system_spec_text=BENCHMARK_SPEC_01_COMPLIANT_HFT,
        )


def test_validation_spec_too_short() -> None:
    engine = get_default_algorithmic_impact_engine()
    with pytest.raises(ValueError, match="length must be between 100 and 50,000"):
        engine.evaluate(
            system_name="TestAlgo",
            model_type="algorithmic_trading",
            system_spec_text="Too short",
        )


def test_spec_01_compliant_hft_assessment() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="AlphaPulse HFT",
        model_type="algorithmic_trading",
        system_spec_text=BENCHMARK_SPEC_01_COMPLIANT_HFT,
    )
    assert result.status == "CONFORMANT"
    assert result.conformity_score >= 90.0
    assert "ALGO-CTRL-01" in result.passed_controls
    assert "ALGO-CTRL-02" in result.passed_controls
    assert "ALGO-CTRL-05" in result.passed_controls
    assert "ALGO-CTRL-06" in result.passed_controls
    assert "ALGO-CTRL-07" in result.passed_controls
    assert "ALGO-CTRL-08" in result.passed_controls
    assert len(result.failed_controls) == 0
    assert result.audit_certificate_id.startswith("CERT-ALGO-")
    assert len(result.negative_flags) == 0


def test_spec_02_strict_kill_switch_capping() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="SwiftMomentum Algo",
        model_type="algorithmic_trading",
        system_spec_text=BENCHMARK_SPEC_02_NO_KILL_SWITCH,
        config=AlgoImpactConfig(strict_kill_switch_required=True),
    )
    # Missing kill switch on trading model with strict gating must cap score at <= 45.0
    assert result.conformity_score <= 45.0
    assert result.status == "NON_CONFORMANT"
    failed_ids = [fc.control_id for fc in result.failed_controls]
    assert "ALGO-CTRL-01" in failed_ids
    assert any("ALGO-CTRL-01" in flag for flag in result.negative_flags)


def test_spec_03_compliant_credit_ai() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="SmartLend AI",
        model_type="credit_scoring",
        system_spec_text=BENCHMARK_SPEC_03_COMPLIANT_CREDIT_AI,
    )
    assert result.status == "CONFORMANT"
    assert result.conformity_score >= 85.0
    assert "ALGO-CTRL-03" in result.passed_controls
    assert "ALGO-CTRL-04" in result.passed_controls
    assert "ALGO-CTRL-05" in result.passed_controls
    assert "ALGO-CTRL-06" in result.passed_controls


def test_spec_04_biased_black_box_credit() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="BlackBox Credit",
        model_type="credit_scoring",
        system_spec_text=BENCHMARK_SPEC_04_BIASED_BLACK_BOX_CREDIT,
    )
    assert result.status == "NON_CONFORMANT"
    assert result.conformity_score <= 40.0
    failed_ids = [fc.control_id for fc in result.failed_controls]
    assert "ALGO-CTRL-03" in failed_ids
    assert "ALGO-CTRL-04" in failed_ids
    assert "ALGO-CTRL-05" in failed_ids
    assert "ALGO-CTRL-06" in failed_ids


def test_spec_05_compliant_llm_agent() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="FinAdvisor AI",
        model_type="llm_agent",
        system_spec_text=BENCHMARK_SPEC_05_COMPLIANT_LLM_AGENT,
    )
    assert result.status == "CONFORMANT"
    assert result.conformity_score >= 85.0
    assert "ALGO-CTRL-01" in result.passed_controls
    assert "ALGO-CTRL-03" in result.passed_controls
    assert "ALGO-CTRL-05" in result.passed_controls


def test_spec_06_unmonitored_llm_agent() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="Support LLM",
        model_type="llm_agent",
        system_spec_text=BENCHMARK_SPEC_06_UNMONITORED_LLM_AGENT,
    )
    assert result.status == "NON_CONFORMANT"
    failed_ids = [fc.control_id for fc in result.failed_controls]
    assert "ALGO-CTRL-01" in failed_ids
    assert "ALGO-CTRL-05" in failed_ids
    assert "ALGO-CTRL-06" in failed_ids


def test_spec_07_compliant_fraud_engine() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="Sentinel Fraud",
        model_type="fraud_detection",
        system_spec_text=BENCHMARK_SPEC_07_COMPLIANT_FRAUD_ENGINE,
    )
    assert result.status == "CONFORMANT"
    assert result.conformity_score >= 85.0


def test_spec_08_rogue_unthrottled_algo() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="Aggressive Sweeper",
        model_type="algorithmic_trading",
        system_spec_text=BENCHMARK_SPEC_08_ROGUE_UNTHROTTLED_ALGO,
    )
    failed_ids = [fc.control_id for fc in result.failed_controls]
    assert "ALGO-CTRL-07" in failed_ids
    assert any("ALGO-CTRL-07" in flag for flag in result.negative_flags)


def test_spec_09_general_enterprise_ai() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="Enterprise AI",
        model_type="general_ai",
        system_spec_text=BENCHMARK_SPEC_09_GENERAL_ENTERPRISE_AI,
    )
    assert result.status == "CONFORMANT"
    assert result.conformity_score >= 75.0


def test_spec_10_untested_live_algo() -> None:
    engine = get_default_algorithmic_impact_engine()
    result = engine.evaluate(
        system_name="Beta Trader",
        model_type="algorithmic_trading",
        system_spec_text=BENCHMARK_SPEC_10_UNTESTED_LIVE_ALGO,
    )
    failed_ids = [fc.control_id for fc in result.failed_controls]
    assert "ALGO-CTRL-02" in failed_ids
    assert any("ALGO-CTRL-02" in flag for flag in result.negative_flags)


def test_deterministic_audit_certificate_id() -> None:
    engine = get_default_algorithmic_impact_engine()
    res1 = engine.evaluate(
        system_name="AlphaPulse",
        model_type="algorithmic_trading",
        system_spec_text=BENCHMARK_SPEC_01_COMPLIANT_HFT,
    )
    res2 = engine.evaluate(
        system_name="AlphaPulse",
        model_type="algorithmic_trading",
        system_spec_text=BENCHMARK_SPEC_01_COMPLIANT_HFT,
    )
    assert res1.audit_certificate_id == res2.audit_certificate_id
    assert res1.audit_certificate_id.startswith("CERT-ALGO-")
    assert len(res1.audit_certificate_id) == 22


def test_evaluation_performance_sla() -> None:
    engine = get_default_algorithmic_impact_engine()
    t0 = time.perf_counter()
    iterations = 100
    for _ in range(iterations):
        engine.evaluate(
            system_name="PerfTest",
            model_type="algorithmic_trading",
            system_spec_text=BENCHMARK_SPEC_01_COMPLIANT_HFT,
        )
    total_time = time.perf_counter() - t0
    avg_latency_ms = (total_time / iterations) * 1000.0
    # Must comfortably satisfy SLA of <= 25ms p95 (typically < 2ms)
    assert avg_latency_ms < 10.0, f"Average latency was {avg_latency_ms:.2f}ms"


# --- REST API Tests ---


def test_api_algo_assessment_success(client: TestClient, api_headers: dict[str, str]) -> None:
    payload = {
        "system_name": "API Test HFT",
        "model_type": "algorithmic_trading",
        "system_spec_text": BENCHMARK_SPEC_01_COMPLIANT_HFT,
        "strict_kill_switch_required": True,
    }
    response = client.post("/v1/compliance/algo-assessment", json=payload, headers=api_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["system_name"] == "API Test HFT"
    assert data["model_type"] == "algorithmic_trading"
    assert data["conformity_score"] >= 90.0
    assert data["status"] == "CONFORMANT"
    assert len(data["passed_controls"]) >= 6
    assert data["audit_certificate_id"].startswith("CERT-ALGO-")


def test_api_algo_assessment_validation_failure(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    payload = {
        "system_name": "Short",
        "model_type": "algorithmic_trading",
        "system_spec_text": "Spec too short",
    }
    response = client.post("/v1/compliance/algo-assessment", json=payload, headers=api_headers)
    assert response.status_code == 422
