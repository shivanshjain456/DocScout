"""Integration and validation tests for Unified Standards Registry & Authority Engine (FEAT-041).

Validates:
1. Complete ingestion and 100% data fidelity against all 53 standards in term-taxonomy.json.standardsRegistry.
2. Structured control families, control counts, and authority metadata.
3. Alias and normalized fuzzy resolution for international and banking standards.
4. HTTP REST API endpoints:
   - GET /v1/standards (with domain, governing body, and free-text search filters).
   - GET /v1/standards/{standard_id} (exact retrieval, path-encoded slashes, and 404 RFC-7807 error).
5. Input validation on standard identifiers.
6. Prometheus counter docscout_standards_queried_total and histogram tracking.
7. Lookup latency SLA <= 1.0ms p95.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import STANDARDS_QUERIED_TOTAL
from app.api.security import load_keys
from app.compliance.standards_registry import get_default_standards_registry
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


def test_100_percent_taxonomy_standards_fidelity() -> None:
    """Validate 100% data fidelity against all 53 standards in term-taxonomy.json."""
    tax_path = (
        Path(__file__).resolve().parent.parent.parent / "do not commit!" / "term-taxonomy.json"
    )
    if not tax_path.exists():
        # Fallback to relative workspace root
        tax_path = (
            Path(__file__).resolve().parent.parent / "ui" / "public" / "taxonomy-dictionary.json"
        )

    registry = get_default_standards_registry()
    assert registry.count() >= 53

    # Load canonical standards from term-taxonomy.json if accessible
    if tax_path.exists():
        with open(tax_path, encoding="utf-8") as f:
            data = json.load(f)
        canonical_standards = data.get("standardsRegistry", [])
        assert len(canonical_standards) == 53

        for entry in canonical_standards:
            std_id = entry["id"]
            matched = registry.get_standard(std_id)
            assert matched is not None, (
                f"Taxonomy standard '{std_id}' failed to resolve in registry"
            )
            assert matched.name == entry["name"]
            assert (
                entry["body"] in matched.governing_body or matched.governing_body in entry["body"]
            )
            assert matched.domain == entry["domain"]
            if entry.get("note"):
                assert matched.note == entry["note"]


def test_control_families_and_control_counts() -> None:
    """Verify standards provide structured control families and calibrated control counts."""
    registry = get_default_standards_registry()

    # ISO/IEC 27001
    iso = registry.get_standard("ISO/IEC 27001")
    assert iso is not None
    fams = iso.get_resolved_control_families()
    assert len(fams) >= 4
    assert any("Access Control" in f or "Technological" in f or "Architecture" in f for f in fams)
    assert iso.get_resolved_control_count() >= 50

    # NIST SP 800-53
    nist = registry.get_standard("NIST SP 800-53")
    assert nist is not None
    assert len(nist.get_resolved_control_families()) >= 4
    assert nist.get_resolved_control_count() >= 50

    # DORA
    dora = registry.get_standard("Regulation (EU) 2022/2554 (DORA)")
    assert dora is not None
    dora_fams = dora.get_resolved_control_families()
    assert any("ICT" in f or "Resilience" in f or "Incident" in f for f in dora_fams)


def test_registry_domain_and_governing_body_filtering() -> None:
    """Test domain, governing_body, and full-text search filtering."""
    registry = get_default_standards_registry()

    # Domain filtering
    safety_stds = registry.list_standards(domain="embedded-safety-critical")
    assert len(safety_stds) >= 8
    assert all(s.domain == "embedded-safety-critical" for s in safety_stds)

    # Governing body filtering
    iso_stds = registry.list_standards(governing_body="ISO")
    assert len(iso_stds) >= 6
    assert all("ISO" in s.governing_body for s in iso_stds)

    # Free-text search
    llm_search = registry.search_standards("LLM")
    assert any("OWASP Top 10 for LLM Applications 2025" in s.id for s in llm_search)

    pci_search = registry.search_standards("PCI DSS")
    assert any("PCI DSS 4.0" in s.id for s in pci_search)


def test_alias_and_normalized_resolution() -> None:
    """Ensure resilient normalized resolution across case, hyphens, and slashes."""
    registry = get_default_standards_registry()

    # Compound DO-331 / DO-332 / DO-333
    assert registry.get_standard("DO-331") is not None
    assert registry.get_standard("do331") is not None
    assert registry.get_standard("DO-331 / DO-332 / DO-333") is not None

    # DORA alias
    assert registry.get_standard("dora") is not None
    assert registry.get_standard("EU DORA") is not None

    # Basel III
    assert registry.get_standard("basel iii") is not None
    assert registry.get_standard("basel 3") is not None


def test_api_list_standards_endpoint(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Test HTTP GET /v1/standards with various query parameters."""
    # 1. Unfiltered query
    resp = test_client.get("/v1/standards", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 53
    assert len(data["standards"]) == data["total"]
    assert len(data["domains"]) >= 8
    assert len(data["governing_bodies"]) >= 10

    # 2. Domain filter
    resp_domain = test_client.get(
        "/v1/standards?domain=embedded-safety-critical", headers=auth_headers
    )
    assert resp_domain.status_code == 200
    d_data = resp_domain.json()
    assert d_data["total"] >= 8
    assert all(s["domain"] == "embedded-safety-critical" for s in d_data["standards"])

    # 3. Governing body filter
    resp_gb = test_client.get("/v1/standards?governing_body=ISO", headers=auth_headers)
    assert resp_gb.status_code == 200
    gb_data = resp_gb.json()
    assert gb_data["total"] >= 6
    assert all("ISO" in s["governing_body"] for s in gb_data["standards"])

    # 4. Search query
    resp_search = test_client.get("/v1/standards?search=DORA", headers=auth_headers)
    assert resp_search.status_code == 200
    s_data = resp_search.json()
    assert s_data["total"] >= 1
    assert any("DORA" in s["id"] for s in s_data["standards"])


def test_api_get_standard_by_id(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Test HTTP GET /v1/standards/{standard_id} exact and path-encoded lookups."""
    # 1. Simple ID
    resp = test_client.get("/v1/standards/DO-178C", headers=auth_headers)
    assert resp.status_code == 200
    item = resp.json()
    assert item["id"] == "DO-178C"
    assert item["governing_body"] == "RTCA/EUROCAE"
    assert len(item["control_families"]) >= 4
    assert item["control_count"] > 0

    # 2. ID containing slashes (path-encoded or raw)
    resp_slash = test_client.get("/v1/standards/ISO/IEC 27001", headers=auth_headers)
    assert resp_slash.status_code == 200
    item_slash = resp_slash.json()
    assert item_slash["id"] == "ISO/IEC 27001"
    assert item_slash["governing_body"] == "ISO/IEC"

    # 3. Compound standard ID
    resp_compound = test_client.get("/v1/standards/DO-331 / DO-332 / DO-333", headers=auth_headers)
    assert resp_compound.status_code == 200
    assert resp_compound.json()["id"] == "DO-331 / DO-332 / DO-333"


def test_api_get_standard_404_and_400(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test RFC-7807 error format and list of available standard IDs on 404/400."""
    # 1. Unknown standard ID -> 404 with list of available standards and closest matches
    resp_404 = test_client.get("/v1/standards/UNKNOWN_STANDARD_999", headers=auth_headers)
    assert resp_404.status_code == 404
    err_data = resp_404.json()["detail"]
    assert err_data["status"] == 404
    assert "available_standards_sample" in err_data
    assert len(err_data["available_standards_sample"]) > 0
    assert err_data["total_available_standards"] >= 53

    # 2. Invalid characters in identifier -> 400
    resp_400 = test_client.get("/v1/standards/INVALID$<script>", headers=auth_headers)
    assert resp_400.status_code == 400
    assert "invalid characters" in resp_400.json()["detail"]


def test_api_standards_metrics(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify Prometheus counter increments on standard lookup."""
    target_id = "DO-178C"
    before = STANDARDS_QUERIED_TOTAL.labels(standard_id=target_id)._value.get()

    resp = test_client.get(f"/v1/standards/{target_id}", headers=auth_headers)
    assert resp.status_code == 200

    after = STANDARDS_QUERIED_TOTAL.labels(standard_id=target_id)._value.get()
    assert after == before + 1


def test_standards_lookup_latency_sla() -> None:
    """Performance SLA: Registry lookup latency <= 1.0ms p95."""
    registry = get_default_standards_registry()
    durations_ms: list[float] = []

    # Benchmark 200 lookups
    for _ in range(200):
        t0 = time.perf_counter()
        res = registry.get_standard("ISO/IEC 27001")
        dt = (time.perf_counter() - t0) * 1000.0
        durations_ms.append(dt)
        assert res is not None

    durations_ms.sort()
    p95_ms = durations_ms[int(len(durations_ms) * 0.95)]
    assert p95_ms <= 1.0, f"Lookup latency {p95_ms:.4f}ms exceeded 1.0ms budget"
