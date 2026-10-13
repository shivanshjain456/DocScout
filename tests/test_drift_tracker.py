"""Unit and benchmark tests for Semantic Terminology Drift Tracker (FEAT-037).

Validates:
1. Single-definition handling (semantic_distance = 0.0, fallback).
2. Reprint gazette invariance (zero false-positive drift on identical definitions).
3. Longitudinal drift detection over 10 benchmark revised statutory terms (>0.20 distance).
4. Key token difference extraction.
5. Performance SLAs (<= 5.0 ms across 5 historical versions).
6. API endpoint GET /v1/admin/ontology/drift/{term_id}.
"""

from __future__ import annotations

import os
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.drift_tracker import (
    DriftConfig,
    TermDriftReport,
    TerminologyDriftTracker,
    get_default_drift_tracker,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth

BENCHMARK_TERMS = [
    "critical-it-infrastructure",
    "significant-beneficial-owner",
    "digital-payment-system",
    "material-outsourcee",
    "small-value-digital-payment",
    "systemically-important-nbfc",
    "designated-non-financial-business",
    "beneficial-ownership-threshold",
    "senior-management-personnel",
    "financial-creditor",
]


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def tracker() -> TerminologyDriftTracker:
    return get_default_drift_tracker()


def test_single_definition_returns_zero_drift(tracker: TerminologyDriftTracker) -> None:
    custom_term = "statutory-liquidity-ratio"
    tracker.register_definition(
        term_id=custom_term,
        canonical_term="Statutory Liquidity Ratio",
        doc_id="RBI/2010/01",
        version_date=date(2010, 1, 1),
        definition_text="Share of net demand and time liabilities that banks maintain in safe and liquid assets.",
    )

    report = tracker.compute_drift(custom_term)
    assert isinstance(report, TermDriftReport)
    assert report.term_id == custom_term
    assert report.canonical_term == "Statutory Liquidity Ratio"
    assert len(report.historical_definitions) == 1
    assert report.semantic_distance_from_origin == 0.0
    assert report.key_diff_tokens == []
    assert not report.drift_alert


def test_identical_definitions_across_reprints_zero_drift(
    tracker: TerminologyDriftTracker,
) -> None:
    reprint_term = "cash-reserve-ratio"
    tracker.register_definition(
        term_id=reprint_term,
        canonical_term="Cash Reserve Ratio",
        doc_id="RBI/2015/01",
        version_date=date(2015, 1, 1),
        definition_text="Specified minimum percentage of total deposits that banks must hold as cash reserves with RBI.",
    )
    # Reprint Gazette with identical text
    tracker.register_definition(
        term_id=reprint_term,
        canonical_term="Cash Reserve Ratio",
        doc_id="RBI/2015/02-REPRINT",
        version_date=date(2015, 6, 1),
        definition_text="Specified minimum percentage of total deposits that banks must hold as cash reserves with RBI.",
    )

    report = tracker.compute_drift(reprint_term)
    assert len(report.historical_definitions) == 2
    assert report.semantic_distance_from_origin == 0.0
    assert report.key_diff_tokens == []
    assert not report.drift_alert


def test_benchmark_regulatory_terms_drift_detection(
    tracker: TerminologyDriftTracker,
) -> None:
    """Evaluate 10 statutory terms across revised circulars.

    Requirement: 100% detection of major definition revisions (> 0.20 distance).
    """
    for term_id in BENCHMARK_TERMS:
        report = tracker.compute_drift(term_id)
        assert len(report.historical_definitions) >= 2, f"Term {term_id} must have >=2 versions"
        assert report.semantic_distance_from_origin >= 0.20, (
            f"Term {term_id} expected semantic distance >= 0.20, got {report.semantic_distance_from_origin:.3f}"
        )
        assert len(report.key_diff_tokens) > 0, f"Term {term_id} must isolate key differing tokens"
        assert report.drift_alert is True, f"Term {term_id} should trigger drift alert"


def test_key_diff_tokens_excludes_stopwords(tracker: TerminologyDriftTracker) -> None:
    report = tracker.compute_drift("critical-it-infrastructure")
    stopwords = {"and", "the", "in", "of", "to", "for", "with", "whose", "or"}
    for tok in report.key_diff_tokens:
        assert tok not in stopwords, f"Stopword '{tok}' should not be in key_diff_tokens"
    # Essential new content tokens from 2023 Master Direction
    diff_tokens_set = set(report.key_diff_tokens)
    assert any(t in diff_tokens_set for t in ["cloud", "software", "supply", "chains", "stability"])


def test_drift_calculation_performance(tracker: TerminologyDriftTracker) -> None:
    """Latency budget: <= 5.0 ms across 5 historical versions."""
    multi_term = "evolving-cloud-standard"
    versions = [
        ("DOC-2010", date(2010, 1, 1), "Internal computer servers located in bank premises."),
        (
            "DOC-2013",
            date(2013, 1, 1),
            "Hosted servers and managed hosting within Indian territory.",
        ),
        (
            "DOC-2017",
            date(2017, 1, 1),
            "Private cloud infrastructure deployed in certified tier-4 datacenters.",
        ),
        (
            "DOC-2020",
            date(2020, 1, 1),
            "Hybrid cloud environments with multi-tenant data storage isolation.",
        ),
        (
            "DOC-2024",
            date(2024, 1, 1),
            "Multi-cloud architectures, edge compute nodes, and serverless containers.",
        ),
    ]
    for doc_id, vdate, text in versions:
        tracker.register_definition(
            term_id=multi_term,
            canonical_term="Cloud Standard",
            doc_id=doc_id,
            version_date=vdate,
            definition_text=text,
        )

    # Warmup
    tracker.compute_drift(multi_term)

    start = time.perf_counter()
    iterations = 20
    for _ in range(iterations):
        res = tracker.compute_drift(multi_term)
        assert res.semantic_distance_from_origin > 0.20
    elapsed_ms = ((time.perf_counter() - start) / iterations) * 1000.0

    assert elapsed_ms <= 5.0, f"Drift calculation {elapsed_ms:.3f}ms exceeds 5.0ms limit"


def test_custom_config_alert_threshold(tracker: TerminologyDriftTracker) -> None:
    high_threshold_config = DriftConfig(alert_threshold_distance=0.99)
    report = tracker.compute_drift("significant-beneficial-owner", config=high_threshold_config)
    # Distance is ~0.3-0.4, so 0.99 should not alert
    assert not report.drift_alert

    low_threshold_config = DriftConfig(alert_threshold_distance=0.05)
    report2 = tracker.compute_drift("significant-beneficial-owner", config=low_threshold_config)
    assert report2.drift_alert


def test_api_admin_ontology_drift_endpoint(test_client: TestClient) -> None:
    headers = auth(PRIMARY_KEY)

    # Unknown term -> 404
    resp_404 = test_client.get(
        "/v1/admin/ontology/drift/unknown-nonexistent-term",
        headers=headers,
    )
    assert resp_404.status_code == 404

    # Valid term -> 200
    resp_200 = test_client.get(
        "/v1/admin/ontology/drift/critical-it-infrastructure",
        headers=headers,
    )
    assert resp_200.status_code == 200
    data = resp_200.json()
    assert data["term_id"] == "critical-it-infrastructure"
    assert data["canonical_term"] == "Critical IT Infrastructure"
    assert len(data["historical_definitions"]) >= 2
    assert data["semantic_distance_from_origin"] >= 0.20
    assert len(data["key_diff_tokens"]) > 0
    assert "drift_alert" in data
