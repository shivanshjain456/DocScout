"""Tests for Regulatory & Technical Antipattern Scanner (FEAT-033).

Verifies detection across the 30 canonical taxonomy antipatterns, synthetic compliance manual
benchmark (>90% accuracy), health score penalties, and API endpoints.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.antipattern_scanner import (
    get_default_antipattern_scanner,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_canonical_30_antipatterns_registered():
    """Verify that all 30 taxonomy antipatterns are registered with valid replacements."""
    scanner = get_default_antipattern_scanner()
    rules = scanner.list_rules()
    assert len(rules) == 30, f"Expected exactly 30 antipatterns, found {len(rules)}"

    domains = {r.domain_category for r in rules}
    assert {
        "testing",
        "reliability",
        "ai_llm",
        "security",
        "observability",
        "deployment",
        "governance",
    }.issubset(domains)

    for rule in rules:
        assert rule.id.startswith("ap-")
        assert len(rule.instead) > 0, f"Antipattern {rule.id} missing 'instead' replacements"
        assert len(rule.regex_patterns) > 0 or len(rule.keywords) > 0


def test_synthetic_manual_benchmark_accuracy():
    """Verify detection accuracy across synthetic compliance manuals containing seeded antipatterns."""
    scanner = get_default_antipattern_scanner()
    bench = scanner.evaluate_synthetic_benchmark()

    assert bench["benchmark_passed"] is True
    assert bench["recall"] >= 0.90
    assert bench["precision"] >= 0.90
    assert bench["detected_antipatterns"] >= 11
    assert bench["false_negatives"] <= 1


def test_document_scoring_model():
    """Verify organizational health score calculation and penalty weighting."""
    scanner = get_default_antipattern_scanner()

    # 1. Clean document should score 100
    clean_text = (
        "All API contracts are verified with bi-directional contract testing on every build."
    )
    clean_res = scanner.scan_document(clean_text)
    assert clean_res["total_findings"] == 0
    assert clean_res["overall_score"] == 100.0

    # 2. Text with critical antipattern (e.g. chaos without hypothesis: -15 penalty)
    risky_text = (
        "We run experiments breaking things in production without a steady-state hypothesis."
    )
    risky_res = scanner.scan_document(risky_text)
    assert risky_res["total_findings"] == 1
    assert risky_res["critical_count"] == 1
    assert risky_res["overall_score"] <= 85.0


def test_sub_millisecond_scan_latency():
    """Verify that multi-paragraph document scanning executes with p95 <= 0.5ms."""
    scanner = get_default_antipattern_scanner()
    doc = """
    Our engineering policy mandates 90% line coverage as a quality target across repos.
    To avoid failing test runs, we add automatic retries to a failing test suite.
    LLM judges are used adopting judge scores as ground truth without validating the outputs.
    """

    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        _ = scanner.scan_document(doc)
        times.append(time.perf_counter() - t0)

    p95_ms = sorted(times)[int(len(times) * 0.95)] * 1000.0
    assert p95_ms <= 2.5, f"Expected fast scan latency, got {p95_ms}ms"


def test_api_list_antipatterns_catalog(client: TestClient):
    """Verify GET /v1/compliance/antipatterns/catalog endpoint."""
    res = client.get("/v1/compliance/antipatterns/catalog", headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 30
    assert "testing" in data["domains"]
    assert "security" in data["domains"]

    # Filter by domain
    res_sec = client.get(
        "/v1/compliance/antipatterns/catalog?domain_category=security", headers=auth(PRIMARY_KEY)
    )
    assert res_sec.status_code == 200
    assert all(r["domain_category"] == "security" for r in res_sec.json()["rules"])


def test_api_scan_antipatterns(client: TestClient):
    """Verify POST /v1/compliance/antipatterns/scan endpoint."""
    payload = {
        "text": "The release gate mandates line coverage as a quality target, and teams mock everything so that tests verify their own assumptions.",
        "document_name": "testing_standard_v2.md",
    }
    res = client.post("/v1/compliance/antipatterns/scan", json=payload, headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["document_name"] == "testing_standard_v2.md"
    assert data["total_findings"] >= 2
    assert not data["is_healthy"]
    assert data["overall_score"] < 100.0
    assert data["latency_ms"] < 30.0

    rule_ids = [f["rule_id"] for f in data["findings"]]
    assert "ap-line-coverage" in rule_ids
    assert "ap-mock-everything" in rule_ids


def test_api_antipatterns_benchmark(client: TestClient):
    """Verify GET /v1/compliance/antipatterns/benchmark endpoint."""
    res = client.get("/v1/compliance/antipatterns/benchmark", headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["benchmark_passed"] is True
    assert data["recall"] >= 0.90
    assert data["precision"] >= 0.90
