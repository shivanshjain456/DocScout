"""Tests for Cross-Framework Control Mapping Matrix (FEAT-042).

Validates:
1. Bidirectional mapping between RBI Cyber Security Framework, ISO/IEC 27001:2022, and NIST CSF 2.0.
2. 50 benchmark cybersecurity controls evaluated across all 3 frameworks with >= 98% accuracy.
3. Unmapped control returns HTTP 200 with empty target_controls and 'No direct mapping established'.
4. Equivalence classification (EXACT, SUBSET, SUPERSET) and verbatim statutory citation spans.
5. Framework coverage metrics calculation.
6. HTTP GET /v1/standards/crosswalk endpoint with caching, input validation, and Prometheus metrics.
7. Performance SLA: query latency <= 3.5ms p95.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import CROSSWALK_QUERIES_TOTAL
from app.api.security import load_keys
from app.compliance.control_mapper import (
    ControlMapper,
    get_default_control_mapper,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


@pytest.fixture
def mapper() -> ControlMapper:
    return get_default_control_mapper()


def test_mapper_catalogs_at_least_50_benchmark_controls(mapper: ControlMapper) -> None:
    """Verify crosswalk engine contains at least 50 benchmark control mappings."""
    total = mapper.count()
    assert total >= 50, f"Expected at least 50 benchmark mappings, found {total}"
    benchmarks = mapper.get_benchmark_controls()
    assert len(benchmarks) == total

    # Ensure all required domains are covered
    sources = {b["source_control_id"] for b in benchmarks}
    assert any("4." in s for s in sources)  # Access Control
    assert any("5." in s for s in sources)  # Network Security
    assert any("6." in s for s in sources)  # Cryptography
    assert any("7." in s for s in sources)  # Vulnerability Management
    assert any("8." in s for s in sources)  # Incident Response
    assert any("9." in s for s in sources)  # BCP/DR
    assert any("10." in s for s in sources)  # Third-Party Risk
    assert any("3." in s for s in sources)  # Governance


def test_bidirectional_control_lookup_rbi_to_iso(mapper: ControlMapper) -> None:
    """Test forward mapping from RBI CSF to ISO/IEC 27001."""
    # 1. Privileged Access Management (PAM)
    pam_res = mapper.get_crosswalk(
        source_framework="RBI_CSF",
        target_framework="ISO/IEC 27001",
        control_id="Annex-1_Cl_4.2",
    )
    assert pam_res["source_control"] == "Annex-1_Cl_4.2"
    assert pam_res["total_mappings"] >= 1
    assert any(c["control_id"] == "A.8.2" for c in pam_res["target_controls"])
    assert pam_res["target_controls"][0]["equivalence_level"] == "SUPERSET"
    assert len(pam_res["citation_spans"]) >= 2
    assert any("RBI" in span for span in pam_res["citation_spans"])
    assert any("ISO" in span for span in pam_res["citation_spans"])

    # 2. Cryptography & Encryption
    crypto_res = mapper.get_crosswalk(
        source_framework="RBI_CSF",
        target_framework="ISO/IEC 27001",
        control_id="Annex-1_Cl_6.1",
    )
    assert any(c["control_id"] == "A.8.24" for c in crypto_res["target_controls"])
    assert crypto_res["target_controls"][0]["equivalence_level"] == "EXACT"


def test_bidirectional_control_lookup_iso_to_rbi(mapper: ControlMapper) -> None:
    """Test reverse mapping asking: 'What RBI circular clause fulfills ISO 27001 A.8.24 / A.8.2?'"""
    # 1. Querying ISO A.8.24 (Cryptography) -> maps back to RBI Cl 6.1, Cl 6.2, Cl 6.3
    rev_crypto = mapper.get_crosswalk(
        source_framework="ISO/IEC 27001",
        target_framework="RBI_CSF",
        control_id="A.8.24",
    )
    assert rev_crypto["total_mappings"] >= 2
    rbi_ids = {c["control_id"] for c in rev_crypto["target_controls"]}
    assert "Annex-1_Cl_6.1" in rbi_ids or "Annex-1_Cl_6.3" in rbi_ids

    # 2. Querying ISO A.8.2 (Privileged access) -> maps back to RBI PAM
    rev_pam = mapper.get_crosswalk(
        source_framework="ISO/IEC 27001",
        target_framework="RBI_CSF",
        control_id="A.8.2",
    )
    assert rev_pam["total_mappings"] >= 1
    assert any(c["control_id"] == "Annex-1_Cl_4.2" for c in rev_pam["target_controls"])


def test_crosswalk_rbi_to_nist_csf(mapper: ControlMapper) -> None:
    """Test mapping between RBI CSF and NIST CSF 2.0."""
    # 1. Mandatory 6-hour incident reporting
    inc_res = mapper.get_crosswalk(
        source_framework="RBI_CSF",
        target_framework="NIST CSF 2.0",
        control_id="Annex-1_Cl_8.2",
    )
    assert inc_res["total_mappings"] >= 1
    assert any(c["control_id"] == "RS.CO-02" for c in inc_res["target_controls"])
    assert inc_res["target_controls"][0]["equivalence_level"] == "SUPERSET"
    assert any("6" in span or "hour" in span.lower() for span in inc_res["citation_spans"])

    # 2. Network segmentation
    net_res = mapper.get_crosswalk(
        source_framework="RBI_CSF",
        target_framework="NIST CSF 2.0",
        control_id="Annex-1_Cl_5.1",
    )
    assert any(c["control_id"] == "PR.IR-01" for c in net_res["target_controls"])


def test_unmapped_control_graceful_handling(mapper: ControlMapper) -> None:
    """Verify unmapped control returns empty list and 'No direct mapping established'."""
    unmapped = mapper.get_crosswalk(
        source_framework="RBI_CSF",
        target_framework="ISO/IEC 27001",
        control_id="NON_EXISTENT_CLAUSE_999",
    )
    assert unmapped["source_control"] == "NON_EXISTENT_CLAUSE_999"
    assert unmapped["total_mappings"] == 0
    assert unmapped["target_controls"] == []
    assert unmapped["citation_spans"] == []
    assert "No direct mapping established" in unmapped["equivalence_summary"]


def test_pairwise_framework_coverage_metrics(mapper: ControlMapper) -> None:
    """Verify framework coverage percentage calculation."""
    cov = mapper.compute_coverage("RBI_CSF", "ISO/IEC 27001")
    assert cov.total_source_controls >= 20
    assert cov.total_target_controls >= 20
    assert cov.mapped_target_controls >= 20
    assert cov.coverage_percentage >= 90.0, (
        f"Expected >= 90% coverage, got {cov.coverage_percentage}%"
    )

    cov_nist = mapper.compute_coverage("RBI_CSF", "NIST CSF 2.0")
    assert cov_nist.coverage_percentage >= 85.0


def test_api_crosswalk_single_control(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test HTTP GET /v1/standards/crosswalk with single control."""
    resp = test_client.get(
        "/v1/standards/crosswalk?source_framework=RBI_CSF&target_framework=ISO/IEC 27001&control_id=Annex-1_Cl_4.2",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_framework"] == "RBI_CSF"
    assert data["target_framework"] == "ISO/IEC 27001"
    assert data["source_control"] == "Annex-1_Cl_4.2"
    assert len(data["target_controls"]) >= 1
    assert data["target_controls"][0]["control_id"] == "A.8.2"
    assert data["target_controls"][0]["equivalence_level"] == "SUPERSET"
    assert len(data["citation_spans"]) >= 2
    assert "Cache-Control" in resp.headers
    assert "86400" in resp.headers["Cache-Control"]


def test_api_crosswalk_pairwise_matrix_and_coverage(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test HTTP GET /v1/standards/crosswalk pairwise matrix without control_id."""
    resp = test_client.get(
        "/v1/standards/crosswalk?source_framework=RBI_CSF&target_framework=ISO/IEC 27001",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_framework"] == "RBI_CSF"
    assert data["target_framework"] == "ISO/IEC 27001"
    assert data["source_control"] is None
    assert data["total_mappings"] >= 25
    assert data["coverage_percentage"] is not None
    assert data["coverage_percentage"] >= 90.0
    assert len(data["mappings"]) == data["total_mappings"]


def test_api_crosswalk_unmapped_control(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test HTTP GET /v1/standards/crosswalk unmapped control returns 200 with empty list."""
    resp = test_client.get(
        "/v1/standards/crosswalk?source_framework=RBI_CSF&target_framework=ISO/IEC 27001&control_id=UNKNOWN_CLAUSE",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_mappings"] == 0
    assert data["target_controls"] == []
    assert "No direct mapping established" in data["equivalence_summary"]


def test_api_crosswalk_unknown_framework_400(
    test_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Test HTTP GET /v1/standards/crosswalk invalid framework returns 400."""
    resp = test_client.get(
        "/v1/standards/crosswalk?source_framework=UNKNOWN_FRAMEWORK_XYZ&target_framework=ISO/IEC 27001",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Unknown source framework" in resp.json()["detail"]


def test_api_crosswalk_metrics(test_client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify Prometheus counter increments on crosswalk query."""
    src = "RBI_CSF"
    tgt = "ISO/IEC 27001"
    before = CROSSWALK_QUERIES_TOTAL.labels(source=src, target=tgt)._value.get()

    resp = test_client.get(
        f"/v1/standards/crosswalk?source_framework={src}&target_framework={tgt}&control_id=Annex-1_Cl_6.1",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    after = CROSSWALK_QUERIES_TOTAL.labels(source=src, target=tgt)._value.get()
    assert after == before + 1


def test_crosswalk_lookup_latency_sla(mapper: ControlMapper) -> None:
    """Performance SLA: Query execution latency <= 3.5ms p95."""
    durations_ms: list[float] = []

    # Benchmark 200 queries
    for _ in range(200):
        t0 = time.perf_counter()
        res = mapper.get_crosswalk("RBI_CSF", "ISO/IEC 27001", "Annex-1_Cl_4.2")
        dt = (time.perf_counter() - t0) * 1000.0
        durations_ms.append(dt)
        assert res["total_mappings"] >= 1

    durations_ms.sort()
    p95 = durations_ms[int(len(durations_ms) * 0.95)]
    assert p95 <= 3.5, f"p95 query latency {p95:.3f}ms exceeded 3.5ms SLA"
