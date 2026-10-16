"""Tests for Numerical Regulatory Evidence Extractor (FEAT-026).

Verifies extraction, unit normalization, operator classification, and API endpoints
for quantitative statutory parameters in RBI and SEBI circulars.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.ingest.numeric_extractor import (
    CRORE_MULTIPLIER,
    LAKH_MULTIPLIER,
    NumericalRegulatoryEvidenceExtractor,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


def test_monetary_penalty_extraction() -> None:
    """Verify extraction of statutory penalties and fines with Indian currency scaling."""
    extractor = NumericalRegulatoryEvidenceExtractor()
    sample = (
        "Section 11. Failure to comply with directions shall attract a penalty of Rs. 10 lakh "
        "per occurrence, up to a maximum penalty not exceeding Rs 1 crore."
    )
    params = extractor.extract_from_text(sample, document_id="rbi-penalty-01")

    penalties = [p for p in params if p.parameter_type == "penalty"]
    assert len(penalties) == 2

    # First penalty: Rs. 10 lakh -> 1,000,000 INR
    p1 = penalties[0]
    assert p1.numeric_value == 10.0
    assert p1.unit == "lakh"
    assert p1.normalized_value == 10.0 * LAKH_MULTIPLIER
    assert p1.normalized_unit == "INR"
    assert p1.section_reference == "Section 11"

    # Second penalty: Rs 1 crore -> 10,000,000 INR, lte
    p2 = penalties[1]
    assert p2.numeric_value == 1.0
    assert p2.unit == "crore"
    assert p2.normalized_value == 1.0 * CRORE_MULTIPLIER
    assert p2.comparison_operator == "lte"


def test_net_worth_threshold_extraction() -> None:
    """Verify extraction of net worth, turnover, and capital thresholds."""
    extractor = NumericalRegulatoryEvidenceExtractor()
    sample = (
        "Clause 5(b). Regulated entities must maintain a minimum net worth of not less than "
        "Rs. 100 crore before commencing digital lending activities."
    )
    params = extractor.extract_from_text(sample, document_id="rbi-dl-01")

    net_worth = [p for p in params if p.parameter_type == "net_worth_threshold"]
    assert len(net_worth) == 1
    nw = net_worth[0]
    assert nw.numeric_value == 100.0
    assert nw.normalized_value == 100.0 * CRORE_MULTIPLIER
    assert nw.normalized_unit == "INR"
    assert nw.comparison_operator == "gte"
    assert nw.section_reference == "Clause 5(b)"


def test_time_window_and_cooling_off_extraction() -> None:
    """Verify statutory filing windows, cooling-off periods, and hour-to-day conversion."""
    extractor = NumericalRegulatoryEvidenceExtractor()
    sample = (
        "Regulation 30. Material events shall be disclosed to stock exchanges within 24 hours. "
        "Borrowers shall be provided a cooling-off period of not less than 3 days. "
        "Quarterly compliance certificates must be filed within 15 days of quarter end."
    )
    params = extractor.extract_from_text(sample, document_id="sebi-lodr-01")

    time_params = [
        p
        for p in params
        if p.parameter_type in ("filing_window", "cooling_off_period", "time_window")
    ]
    assert len(time_params) >= 3

    # 24 hours -> 1.0 day
    hours_param = next(p for p in time_params if p.unit == "hours")
    assert hours_param.numeric_value == 24.0
    assert abs(hours_param.normalized_value - 1.0) < 1e-4
    assert hours_param.normalized_unit == "days"
    assert hours_param.parameter_type == "filing_window"

    # Cooling off: 3 days, gte
    cooling_param = next(p for p in time_params if p.parameter_type == "cooling_off_period")
    assert cooling_param.numeric_value == 3.0
    assert cooling_param.normalized_value == 3.0
    assert cooling_param.comparison_operator == "gte"

    # 15 days filing window
    filing_param = next(p for p in time_params if p.numeric_value == 15.0)
    assert filing_param.unit == "days"
    assert filing_param.normalized_value == 15.0


def test_ratio_and_haircut_extraction() -> None:
    """Verify capital adequacy ratios, regulatory haircuts, and basis point conversion."""
    extractor = NumericalRegulatoryEvidenceExtractor()
    sample = (
        "Paragraph 2.1. Banks shall maintain a minimum CRAR of 9.0% on a continuous basis. "
        "Commercial corporate bonds shall carry a haircut of 15%. "
        "Interest rate spread shall not exceed 250 bps over benchmark."
    )
    params = extractor.extract_from_text(sample, document_id="basel-ratios-01")

    # CRAR: 9.0% -> 0.09 ratio, gte
    crar_list = [p for p in params if p.parameter_type == "capital_adequacy"]
    assert len(crar_list) == 1
    crar = crar_list[0]
    assert crar.numeric_value == 9.0
    assert abs(crar.normalized_value - 0.09) < 1e-5
    assert crar.normalized_unit == "ratio"
    assert crar.comparison_operator == "gte"

    # Haircut: 15% -> 0.15 ratio
    haircut_list = [p for p in params if p.parameter_type == "haircut"]
    assert len(haircut_list) == 1
    hc = haircut_list[0]
    assert hc.numeric_value == 15.0
    assert abs(hc.normalized_value - 0.15) < 1e-5

    # 250 bps -> 0.025 ratio
    bps_list = [p for p in params if p.unit == "bps"]
    assert len(bps_list) == 1
    bps = bps_list[0]
    assert bps.numeric_value == 250.0
    assert abs(bps.normalized_value - 0.025) < 1e-5


def test_extraction_throughput_performance() -> None:
    """Benchmark parameter extraction throughput ensuring <0.5ms per page overhead."""
    extractor = NumericalRegulatoryEvidenceExtractor()
    page_text = (
        "Section 4.1. Borrowers shall be provided a cooling-off period of not less than 3 days.\n"
        "Clause 6.3. Any Regulated Entity shall attract a penalty of Rs. 10 lakh per occurrence, "
        "up to a maximum of Rs 1 crore.\n"
        "Section 8.2. REs must have a minimum net worth of Rs 100 crore.\n"
        "Annexure B. CRAR must be maintained at not less than 9% with a spread of 150 bps."
    )

    # Warm-up run
    for _ in range(10):
        _ = extractor.extract_from_text(page_text, document_id="warmup")

    t0 = time.perf_counter()
    n_runs = 200
    total_params = 0
    for i in range(n_runs):
        res = extractor.extract_from_text(page_text, document_id=f"doc-{i}")
        total_params += len(res)
    duration = time.perf_counter() - t0

    avg_ms = (duration / n_runs) * 1000.0
    assert avg_ms < 5.0, f"Extraction throughput too slow: {avg_ms:.3f} ms/run"
    assert total_params >= n_runs * 5


def test_api_extract_parameters_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify POST /v1/compliance/extract-parameters endpoint behavior and models."""
    payload = {
        "text": "Clause 4. Minimum net worth of Rs. 50 crore and penalty not exceeding Rs 5 lakh.",
        "document_id": "doc-test-api",
    }
    resp = client.post(
        "/v1/compliance/extract-parameters",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == "doc-test-api"
    assert data["total_count"] == 2
    assert "penalty" in data["parameter_types"]
    assert "net_worth_threshold" in data["parameter_types"]
    assert data["latency_ms"] >= 0.0


def test_api_extract_parameters_unauthorized(client: TestClient) -> None:
    """Verify 401 rejection for unauthenticated requests."""
    resp = client.post(
        "/v1/compliance/extract-parameters",
        json={"text": "penalty of Rs 10 lakh"},
    )
    assert resp.status_code == 401


def test_api_get_document_parameters(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify GET /v1/compliance/documents/{id}/parameters endpoint."""
    resp = client.get(
        "/v1/compliance/documents/doc-sample-123/parameters",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == "doc-sample-123"
    assert isinstance(data["parameters"], list)


def test_migration_0017_sql_syntax() -> None:
    """Verify migration 0017 SQL files exist and have valid table definitions."""
    up_path = Path("migrations/0017_statutory_parameters.up.sql")
    down_path = Path("migrations/0017_statutory_parameters.down.sql")

    assert up_path.is_file()
    assert down_path.is_file()

    up_sql = up_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS statutory_parameters" in up_sql
    assert "idx_statutory_parameters_doc" in up_sql
    assert "idx_statutory_parameters_type" in up_sql

    down_sql = down_path.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS statutory_parameters" in down_sql
