"""Unit and integration tests for Standard-Linked Formula Annotator (FEAT-025).

Verifies:
- Standards registry catalogs all 53 international and national standards
- Domain, governing body, and full-text filtering
- Resilient alias and fuzzy statutory reference resolution
- 100% of 24 canonical taxonomy formulas successfully link to standards
- Banking statutory ratios (CRAR, LCR, Leverage Ratio, NSFR) link to Basel III / RBI
- Linking latency overhead <= 0.5ms per formula
- REST API endpoints: GET /v1/compliance/standards, GET /v1/compliance/standards/{id},
  GET /v1/compliance/formulas/{id}/standards, POST /v1/compliance/annotate-formula
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.formula_engine import get_default_formula_engine
from app.compliance.standards_registry import (
    StandardsRegistry,
    get_default_standards_registry,
)
from app.ingest.formula_extractor import ExtractedFormula
from app.ingest.standard_linker import (
    AnnotatedFormula,
    StandardFormulaAnnotator,
    get_default_standard_annotator,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def registry() -> StandardsRegistry:
    return get_default_standards_registry()


@pytest.fixture
def annotator() -> StandardFormulaAnnotator:
    return get_default_standard_annotator()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


# ---------------------------------------------------------------------------
# Standards Registry Unit Tests
# ---------------------------------------------------------------------------


def test_standards_registry_catalogs_all_53_standards(registry: StandardsRegistry) -> None:
    """Verify registry catalogs all 53 international standards plus banking frameworks."""
    count = registry.count()
    assert count >= 53, f"Expected at least 53 standards, found {count}"

    # Critical international safety and sustainability standards
    assert registry.get_standard("DO-178C") is not None
    assert registry.get_standard("ISO/IEC 21031:2024") is not None
    assert registry.get_standard("ISO 26262") is not None
    assert registry.get_standard("NIST SP 800-53") is not None
    assert registry.get_standard("OWASP Top 10 for LLM Applications 2025") is not None
    assert registry.get_standard("WCAG 2.2") is not None
    assert registry.get_standard("Regulation (EU) 2022/2554 (DORA)") is not None

    # Banking & Statutory frameworks
    assert registry.get_standard("BASEL_III") is not None
    assert registry.get_standard("RBI_BASEL_III_CAPITAL") is not None
    assert registry.get_standard("RBI_LIQUIDITY_RISK") is not None


def test_standards_registry_domain_and_governing_body_filtering(
    registry: StandardsRegistry,
) -> None:
    """Filter standards by domain and governing body."""
    safety_stds = registry.list_standards(domain="embedded-safety-critical")
    assert len(safety_stds) >= 8
    assert all(s.domain == "embedded-safety-critical" for s in safety_stds)

    nist_stds = registry.list_standards(governing_body="NIST")
    assert len(nist_stds) >= 5
    assert all("NIST" in s.governing_body for s in nist_stds)

    rbi_stds = registry.list_standards(governing_body="RBI")
    assert len(rbi_stds) >= 3


def test_standards_registry_search_queries(registry: StandardsRegistry) -> None:
    """Search standards catalog across keywords."""
    carbon_matches = registry.search_standards("carbon")
    assert any("21031" in m.id for m in carbon_matches)

    basel_matches = registry.search_standards("basel")
    assert any("BASEL" in m.id for m in basel_matches)

    quantum_matches = registry.search_standards("quantum")
    assert len(quantum_matches) >= 3  # FIPS 203, 204, 205


def test_standards_registry_alias_and_fuzzy_resolution(registry: StandardsRegistry) -> None:
    """Resolve variations, lowercase aliases, and reference strings."""
    # DO-178C variations
    assert registry.resolve_standard("do178c") is not None
    assert registry.resolve_standard("do-178c") is not None
    assert registry.resolve_standard("ed-12c") is not None
    assert registry.resolve_standard("DO-178C Table A-7") is not None

    # SCI variations
    sci_res = registry.resolve_standard("ISO 21031")
    assert sci_res is not None
    assert sci_res.id == "ISO/IEC 21031:2024"

    # Basel III variations
    basel_res = registry.resolve_standard("basel iii")
    assert basel_res is not None
    assert "BASEL" in basel_res.id


# ---------------------------------------------------------------------------
# Formula Standard Linker Tests (FEAT-025 Objective)
# ---------------------------------------------------------------------------


def test_all_24_canonical_taxonomy_formulas_link_to_standards(
    annotator: StandardFormulaAnnotator,
) -> None:
    """Verify 100% of the 24 taxonomy formulas in term-taxonomy.json link to their governing standards."""
    engine = get_default_formula_engine()
    all_formulas = engine.list_formulas()
    assert len(all_formulas) >= 24

    unlinked: list[str] = []
    for f in all_formulas:
        annotated: AnnotatedFormula = annotator.annotate_formula(f)
        if annotated.status != "LINKED" or not annotated.standard_id:
            unlinked.append(f.id)

    assert not unlinked, f"The following formulas failed to link to standards: {unlinked}"


def test_specific_formula_standard_associations(
    annotator: StandardFormulaAnnotator,
) -> None:
    """Verify specific formula-to-standard lineages."""
    # 1. Software Carbon Intensity -> ISO/IEC 21031:2024
    sci = annotator.annotate_formula("sci")
    assert sci.standard_id == "ISO/IEC 21031:2024"
    assert sci.governing_body == "ISO/IEC"
    assert "Software Carbon Intensity" in sci.standard_name  # type: ignore

    # 2. MC/DC Test Count -> DO-178C
    mcdc = annotator.annotate_formula("mcdc")
    assert mcdc.standard_id == "DO-178C"
    assert mcdc.governing_body == "RTCA/EUROCAE"

    # 3. Capital to Risk-Weighted Assets -> RBI Basel III Capital Regulations
    crar = annotator.annotate_formula("crar")
    assert crar.standard_id in ("RBI_BASEL_III_CAPITAL", "BASEL_III")
    assert crar.governing_body in ("RBI", "BCBS")

    # 4. Liquidity Coverage Ratio -> RBI Liquidity Risk Framework
    lcr = annotator.annotate_formula("lcr")
    assert lcr.standard_id in ("RBI_LIQUIDITY_RISK", "BASEL_III")

    # 5. Attack Success Rate -> OWASP Top 10 for LLM Applications 2025
    asr = annotator.annotate_formula("asr")
    assert asr.standard_id == "OWASP Top 10 for LLM Applications 2025"
    assert asr.governing_body == "OWASP"

    # 6. Disparate Impact -> NIST SP 1270
    di = annotator.annotate_formula("disparate-impact")
    assert di.standard_id == "NIST SP 1270"
    assert di.governing_body == "NIST"

    # 7. Error budget burn rate -> SRE Reliability Framework
    burn = annotator.annotate_formula("burn-rate")
    assert burn.standard_id == "SRE_RELIABILITY_FRAMEWORK"


def test_extracted_formula_linkage(annotator: StandardFormulaAnnotator) -> None:
    """Verify linking ExtractedFormula objects from circular ingestion."""
    extracted = ExtractedFormula(
        doc_id="doc-rbi-272",
        formula_name="Capital Adequacy Ratio",
        raw_expression="CRAR = Capital / RWA",
        parsed_ast={},
        variables={"Capital": "Total capital", "RWA": "Risk-weighted assets"},
        span=(100, 150),
        confidence=0.95,
        standard="RBI Master Direction - Basel III Capital Regulations",
    )

    annotated = annotator.annotate_formula(extracted)
    assert annotated.status == "LINKED"
    assert annotated.standard_id == "RBI_BASEL_III_CAPITAL"
    assert annotated.governing_body == "RBI"


def test_unmatched_standard_fallback_behavior(annotator: StandardFormulaAnnotator) -> None:
    """Unmatched standard logs diagnostic info and returns standard_id=None without raising."""
    custom_formula = {
        "id": "synthetic_equation",
        "name": "Custom Proprietary Metric",
        "expression": "x + y * 2",
        "standard": "NONEXISTENT_STANDARD_XYZ_999",
    }

    annotated = annotator.annotate_formula(custom_formula)
    assert annotated.status == "UNLINKED"
    assert annotated.standard_id is None
    assert annotated.standard_name is None
    assert annotated.confidence == 0.0


def test_linking_latency_under_half_millisecond(
    annotator: StandardFormulaAnnotator,
) -> None:
    """Verify linking overhead <= 0.5ms per formula (p95 limit in specification)."""
    formulas = [
        "sci",
        "crar",
        "lcr",
        "mcdc",
        "asr",
        "cve-triage",
        "error-budget",
        "burn-rate",
    ]

    # Warmup
    for f in formulas:
        annotator.annotate_formula(f)

    latencies: list[float] = []
    for _ in range(500):
        for f in formulas:
            t0 = time.perf_counter()
            annotator.annotate_formula(f)
            latencies.append((time.perf_counter() - t0) * 1000.0)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    # Requirement: <= 0.5ms
    assert p95 <= 0.50, f"p95 latency {p95:.4f}ms exceeded 0.50ms threshold"


# ---------------------------------------------------------------------------
# REST API Endpoints Tests
# ---------------------------------------------------------------------------


def test_api_standards_list_endpoint(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify GET /v1/compliance/standards endpoint returns standard catalog."""
    # Auth required
    unauth_resp = client.get("/v1/compliance/standards")
    assert unauth_resp.status_code == 401

    resp = client.get("/v1/compliance/standards", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 53
    assert len(data["standards"]) >= 53

    # Query filter by domain
    dom_resp = client.get(
        "/v1/compliance/standards?domain=embedded-safety-critical",
        headers=auth_headers,
    )
    assert dom_resp.status_code == 200
    dom_data = dom_resp.json()
    assert dom_data["total"] >= 5
    assert all(s["domain"] == "embedded-safety-critical" for s in dom_data["standards"])

    # Query filter by text search
    q_resp = client.get("/v1/compliance/standards?query=ISO+21031", headers=auth_headers)
    assert q_resp.status_code == 200
    q_data = q_resp.json()
    assert q_data["total"] >= 1
    assert any("21031" in s["id"] for s in q_data["standards"])


def test_api_standard_detail_endpoint(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify GET /v1/compliance/standards/{standard_id} endpoint."""
    resp = client.get("/v1/compliance/standards/DO-178C", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "DO-178C"
    assert data["governing_body"] == "RTCA/EUROCAE"
    assert "MC/DC" in data["note"]

    # 404 for unknown standard
    not_found = client.get("/v1/compliance/standards/UNKNOWN_999", headers=auth_headers)
    assert not_found.status_code == 404


def test_api_formula_standards_endpoint(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify GET /v1/compliance/formulas/{formula_id}/standards endpoint."""
    resp = client.get("/v1/compliance/formulas/crar/standards", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["formula_id"] == "crar"
    assert data["status"] == "LINKED"
    assert "RBI" in data["governing_body"] or "BCBS" in data["governing_body"]
    assert "BASEL" in data["standard_id"]

    # 404 for nonexistent formula
    nf_resp = client.get("/v1/compliance/formulas/unknown_xyz/standards", headers=auth_headers)
    assert nf_resp.status_code == 404


def test_api_annotate_formula_endpoint(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify POST /v1/compliance/annotate-formula endpoint."""
    payload = {
        "formula_name": "Software Carbon Intensity",
        "expression": "(E * I + M) / R",
        "standard_hint": "ISO/IEC 21031:2024",
    }
    resp = client.post("/v1/compliance/annotate-formula", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["standard_id"] == "ISO/IEC 21031:2024"
    assert data["governing_body"] == "ISO/IEC"
    assert data["status"] == "LINKED"


def test_migration_0016_sql_syntax() -> None:
    """Verify migration 0016 SQL files exist and have valid table definitions."""
    up_path = Path("migrations/0016_standards_registry.up.sql")
    down_path = Path("migrations/0016_standards_registry.down.sql")

    assert up_path.is_file()
    assert down_path.is_file()

    up_sql = up_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS standards_registry" in up_sql
    assert "ALTER TABLE document_formulas" in up_sql
    assert "REFERENCES standards_registry(id)" in up_sql

    down_sql = down_path.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS standards_registry" in down_sql
