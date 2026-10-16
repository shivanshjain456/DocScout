"""Tests for Statutory Deprecation & Supersession Engine (FEAT-031).

Verifies detection of superseded circulars, repealed guidelines, and engineering antipatterns,
multi-step supersession chain resolution, sunset date checks, grandfathering provisions,
and compliance API endpoints.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.deprecation_engine import (
    DeprecationStatus,
    RegulatorCode,
    StatutoryDeprecation,
    StatutoryDeprecationEngine,
    SubjectType,
    get_default_deprecation_engine,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_canonical_deprecations_catalog() -> None:
    """Verify that statutory and technical deprecations are pre-populated in engine."""
    engine = get_default_deprecation_engine()
    deprecations = engine.list_deprecations()
    assert len(deprecations) >= 15

    regulators = {d.regulator.value for d in deprecations}
    assert {"RBI", "SEBI", "PMLA", "BASEL", "INDUSTRY_STANDARD"}.issubset(regulators)

    # Check key statutory circulars
    rbi_kyc = engine.get_deprecation("rbi-kyc-circular-2002")
    assert rbi_kyc is not None
    assert rbi_kyc.status == DeprecationStatus.SUPERSEDED
    assert rbi_kyc.superseded_by == "rbi-kyc-master-circular-2013"
    assert len(rbi_kyc.replacement) > 0


def test_superseded_circular_corpus_flag_rate() -> None:
    """Verify 100% flag rate on known superseded circular test corpus."""
    engine = get_default_deprecation_engine()

    test_corpus = [
        (
            "We follow RBI KYC Guidelines 2002 for customer identity verification.",
            "rbi-kyc-circular-2002",
        ),
        (
            "Outsourcing policy adheres to DBOD.No.BP.40/21.04.158/2006-07 guidelines.",
            "rbi-outsourcing-2006",
        ),
        (
            "Lending contracts reference DBOD.Leg.BC.104/09.07.007/2002-03 code.",
            "rbi-fair-practices-2003",
        ),
        (
            "Merchant retains Card-on-File plain text storage for fast checkout.",
            "rbi-card-storage-legacy",
        ),
        (
            "Security baseline follows DBS.CO/CSITE/BC.11/33.01.001/2015-16 circular.",
            "rbi-cyber-framework-2016",
        ),
        ("Company governance complies with Clause 49 corporate governance.", "sebi-clause-49"),
        (
            "Broking arm adheres to CIR/MIRSD/1/2015 Cybersecurity Framework.",
            "sebi-cyber-framework-2015",
        ),
        (
            "AML checks apply 25% beneficial ownership threshold for corporate entities.",
            "pmla-bo-threshold-25pct",
        ),
        (
            "Credit risk calculated under Basel II Standardised Approach for Credit Risk.",
            "basel2-standardized-credit",
        ),
    ]

    for text, expected_id in test_corpus:
        findings = engine.scan_text(text)
        flagged_ids = [f.deprecation_id for f in findings]
        assert expected_id in flagged_ids, (
            f"Failed to flag expected deprecation '{expected_id}' in: {text}"
        )


def test_technical_antipattern_flag_rate() -> None:
    """Verify detection of software and compliance antipatterns from term-taxonomy."""
    engine = get_default_deprecation_engine()

    tech_corpus = [
        ("We use DREAD threat modeling for architecture risk scoring.", "dep-dread"),
        ("Microservice circuit breaker uses Netflix Hystrix core.", "dep-hystrix"),
        ("KPI dashboard reports MTTR as a stability metric.", "dep-mttr-stability"),
        (
            "Release gate enforces 90% line coverage as a quality target.",
            "dep-line-coverage-quality",
        ),
        ("CI pipeline implements blind test retries to address flakes.", "dep-blind-retries"),
        (
            "Accessibility compliance relies on checkbox accessibility scanning.",
            "dep-checkbox-accessibility",
        ),
        ("Annual point-in-time penetration testing scheduled for Q4.", "dep-annual-pentest"),
        ("Microservices use JSON-over-the-wire without contract testing.", "dep-json-no-contract"),
    ]

    for text, expected_id in tech_corpus:
        findings = engine.scan_text(text)
        flagged_ids = [f.deprecation_id for f in findings]
        assert expected_id in flagged_ids, (
            f"Failed to flag technical antipattern '{expected_id}' in: {text}"
        )


def test_supersession_chain_resolution() -> None:
    """Verify multi-step recursive supersession chain resolution to active master direction."""
    engine = get_default_deprecation_engine()

    chain = engine.get_supersession_chain("rbi-kyc-circular-2002")
    assert chain.root_instrument == "rbi-kyc-circular-2002"
    assert chain.depth == 3
    assert not chain.has_cycle

    # Step 1: 2002 circular (superseded)
    assert chain.chain[0].instrument_id == "rbi-kyc-circular-2002"
    assert not chain.chain[0].is_currently_active

    # Step 2: 2013 master circular (superseded)
    assert chain.chain[1].instrument_id == "rbi-kyc-master-circular-2013"
    assert not chain.chain[1].is_currently_active

    # Step 3: 2016 master direction (active authority)
    assert chain.chain[2].instrument_id == "rbi-kyc-master-direction-2016"
    assert chain.chain[2].is_currently_active
    assert "RBI Master Direction - Know Your Customer" in chain.active_authority


def test_supersession_cycle_prevention() -> None:
    """Verify that artificial cyclic supersessions terminate safely without infinite recursion."""
    test_engine = StatutoryDeprecationEngine()

    # Create artificial circular references: A -> B -> C -> A
    dep_a = StatutoryDeprecation(
        id="test-circular-a",
        subject="Circular A",
        subject_type=SubjectType.CIRCULAR,
        regulator=RegulatorCode.RBI,
        status=DeprecationStatus.SUPERSEDED,
        reason="Testing",
        effective_date="2020-01-01",
        superseded_by="test-circular-b",
        guidance="None",
    )
    dep_b = StatutoryDeprecation(
        id="test-circular-b",
        subject="Circular B",
        subject_type=SubjectType.CIRCULAR,
        regulator=RegulatorCode.RBI,
        status=DeprecationStatus.SUPERSEDED,
        reason="Testing",
        effective_date="2021-01-01",
        superseded_by="test-circular-c",
        guidance="None",
    )
    dep_c = StatutoryDeprecation(
        id="test-circular-c",
        subject="Circular C",
        subject_type=SubjectType.CIRCULAR,
        regulator=RegulatorCode.RBI,
        status=DeprecationStatus.SUPERSEDED,
        reason="Testing",
        effective_date="2022-01-01",
        superseded_by="test-circular-a",
        guidance="None",
    )

    test_engine.register_deprecation(dep_a)
    test_engine.register_deprecation(dep_b)
    test_engine.register_deprecation(dep_c)

    chain = test_engine.get_supersession_chain("test-circular-a")
    assert chain.has_cycle is True
    assert chain.depth == 3


def test_sunset_date_and_grandfathering_evaluation() -> None:
    """Verify point-in-time sunset expiration and grandfathering clause extraction."""
    engine = get_default_deprecation_engine()

    card_storage = engine.get_deprecation("rbi-card-storage-legacy")
    assert card_storage is not None
    assert card_storage.sunset_date == "2022-09-30"

    # Before sunset date
    assert not card_storage.is_sunset_passed("2022-06-01")

    # After sunset date
    assert card_storage.is_sunset_passed("2023-01-01")

    # Grandfathering check on RBI Fair Practices
    fp = engine.get_deprecation("rbi-fair-practices-2003")
    assert fp is not None
    assert fp.grandfathering_clause is not None
    assert "Existing bilateral loans" in fp.grandfathering_clause


def test_scan_latency_performance() -> None:
    """Verify that multi-paragraph policy text scanning executes with p95 <= 0.5ms."""
    engine = get_default_deprecation_engine()
    sample_policy = (
        "The bank currently complies with RBI KYC Guidelines 2002 and DBOD.AML.BC.18/14.01.001/2002-03. "
        "Vendor contracting references DBOD.No.BP.40/21.04.158/2006-07 outsourcing directives. "
        "Quality assurance continues to enforce 90% line coverage as a quality target across services. "
        "Card data is managed under Card-on-File plain text storage mechanisms."
    )

    # Warmup
    _ = engine.scan_text(sample_policy)

    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        findings = engine.scan_text(sample_policy)
        times.append(time.perf_counter() - t0)

    p95_ms = sorted(times)[int(len(times) * 0.95)] * 1000.0
    assert len(findings) >= 3
    assert p95_ms <= 2.5, f"Expected fast scan, got {p95_ms}ms"


def test_api_list_deprecations(client: TestClient) -> None:
    """Verify GET /v1/compliance/deprecations catalog endpoint."""
    res = client.get("/v1/compliance/deprecations", headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] >= 15
    assert "RBI" in data["regulators"]
    assert "SEBI" in data["regulators"]

    # Filter by regulator
    res_rbi = client.get("/v1/compliance/deprecations?regulator=RBI", headers=auth(PRIMARY_KEY))
    assert res_rbi.status_code == 200
    data_rbi = res_rbi.json()
    assert all(d["regulator"] == "RBI" for d in data_rbi["deprecations"])


def test_api_check_supersession(client: TestClient) -> None:
    """Verify POST /v1/compliance/check-supersession endpoint."""
    payload = {
        "text": "Customer onboarding is conducted pursuant to DBOD.AML.BC.18/14.01.001/2002-03 and Clause 49.",
        "as_of_date": "2024-06-01",
    }
    res = client.post("/v1/compliance/check-supersession", json=payload, headers=auth(PRIMARY_KEY))
    assert res.status_code == 200
    data = res.json()
    assert not data["is_compliant"]
    assert data["total_flagged"] >= 2
    assert len(data["recommended_actions"]) >= 2
    assert data["latency_ms"] < 50.0

    subjects = [d["subject"] for d in data["detections"]]
    assert any("2002-03" in s for s in subjects)
    assert any("Clause 49" in s for s in subjects)


def test_api_supersession_chain(client: TestClient) -> None:
    """Verify GET /v1/compliance/supersession-chain/{instrument_id} endpoint."""
    res = client.get(
        "/v1/compliance/supersession-chain/rbi-kyc-circular-2002",
        headers=auth(PRIMARY_KEY),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["root_instrument"] == "rbi-kyc-circular-2002"
    assert data["depth"] == 3
    assert not data["has_cycle"]
    assert len(data["chain"]) == 3
    assert data["chain"][-1]["is_currently_active"] is True
