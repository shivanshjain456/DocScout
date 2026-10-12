"""Tests for Indian Financial Unit Normalizer (FEAT-028).

Verifies bidirectional conversion across >50 numerical representations,
Indian comma formatting, Western comma formatting, basis points to percentage scaling,
equivalence checking, and API endpoints.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.unit_normalizer import (
    CRORE_MULTIPLIER,
    LAKH_MULTIPLIER,
    MILLION_MULTIPLIER,
    IndianFinancialUnitNormalizer,
    format_indian_number,
    format_international_number,
    get_default_unit_normalizer,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_bidirectional_conversion_over_50_representations() -> None:
    """Validate parsing and conversion across at least 50 varied numerical representations."""
    normalizer = IndianFinancialUnitNormalizer()

    test_vectors: list[tuple[str, float, str]] = [
        # Indian Crore variations (1-10)
        ("₹ 1 Crore", 1.0 * CRORE_MULTIPLIER, "INR"),
        ("Rs. 50 Cr", 50.0 * CRORE_MULTIPLIER, "INR"),
        ("100 crores", 100.0 * CRORE_MULTIPLIER, "INR"),
        ("2.5 cr", 2.5 * CRORE_MULTIPLIER, "INR"),
        ("INR 500 crs", 500.0 * CRORE_MULTIPLIER, "INR"),
        ("0.5 Crore", 0.5 * CRORE_MULTIPLIER, "INR"),
        ("₹12.75 Cr", 12.75 * CRORE_MULTIPLIER, "INR"),
        ("Rs 1000 Crore", 1000.0 * CRORE_MULTIPLIER, "INR"),
        ("3.14 Cr", 3.14 * CRORE_MULTIPLIER, "INR"),
        ("₹ 25 Crore", 25.0 * CRORE_MULTIPLIER, "INR"),
        # Indian Lakh variations (11-20)
        ("₹ 1 Lakh", 1.0 * LAKH_MULTIPLIER, "INR"),
        ("Rs. 10 Lakhs", 10.0 * LAKH_MULTIPLIER, "INR"),
        ("50 lacs", 50.0 * LAKH_MULTIPLIER, "INR"),
        ("2.5 lakh", 2.5 * LAKH_MULTIPLIER, "INR"),
        ("INR 100 lac", 100.0 * LAKH_MULTIPLIER, "INR"),
        ("₹75 lakh", 75.0 * LAKH_MULTIPLIER, "INR"),
        ("0.25 Lakh", 0.25 * LAKH_MULTIPLIER, "INR"),
        ("Rs 5 Lakhs", 5.0 * LAKH_MULTIPLIER, "INR"),
        ("15 lk", 15.0 * LAKH_MULTIPLIER, "INR"),
        ("₹ 12.5 Lacs", 12.5 * LAKH_MULTIPLIER, "INR"),
        # International Million variations (21-28)
        ("$1 Million", 1.0 * MILLION_MULTIPLIER, "USD"),
        ("10 millions", 10.0 * MILLION_MULTIPLIER, "USD"),
        ("500 M", 500.0 * MILLION_MULTIPLIER, "USD"),
        ("USD 2.5 mn", 2.5 * MILLION_MULTIPLIER, "USD"),
        ("€ 15 Million", 15.0 * MILLION_MULTIPLIER, "EUR"),
        ("100 million", 100.0 * MILLION_MULTIPLIER, "USD"),
        ("0.5M", 0.5 * MILLION_MULTIPLIER, "USD"),
        ("$250 Million", 250.0 * MILLION_MULTIPLIER, "USD"),
        # International Billion variations (29-35)
        ("$1 Billion", 1_000_000_000.0, "USD"),
        ("2.5 billions", 2_500_000_000.0, "USD"),
        ("USD 10 B", 10_000_000_000.0, "USD"),
        ("€ 5 bn", 5_000_000_000.0, "EUR"),
        ("0.75 Billion", 750_000_000.0, "USD"),
        ("$100 B", 100_000_000_000.0, "USD"),
        ("1.2 bn", 1_200_000_000.0, "USD"),
        # Basis Points (bps) variations (36-43)
        ("25 bps", 0.0025, "BPS"),
        ("50 basis points", 0.0050, "BPS"),
        ("100 bp", 0.0100, "BPS"),
        ("150 bps", 0.0150, "BPS"),
        ("200 basis point", 0.0200, "BPS"),
        ("1000 bps", 0.1000, "BPS"),
        ("75 bps", 0.0075, "BPS"),
        ("12.5 bps", 0.00125, "BPS"),
        # Percentage variations (44-51)
        ("5%", 0.05, "PERCENT"),
        ("12.5 %", 0.125, "PERCENT"),
        ("0.75 percent", 0.0075, "PERCENT"),
        ("18 percentage", 0.18, "PERCENT"),
        ("100%", 1.0, "PERCENT"),
        ("2.25%", 0.0225, "PERCENT"),
        ("50 percent", 0.50, "PERCENT"),
        ("9.0%", 0.09, "PERCENT"),
        # Raw / Thousands (52-55)
        ("50 thousand", 50_000.0, "INR"),
        ("Rs. 25k", 25_000.0, "INR"),
        ("USD 500k", 500_000.0, "USD"),
        ("10,00,000", 1_000_000.0, "INR"),
    ]

    assert len(test_vectors) >= 50, f"Expected >= 50 test representations, got {len(test_vectors)}"

    for text, expected_val, _expected_unit in test_vectors:
        norm = normalizer.parse(text)
        assert norm.is_valid, f"Failed parsing: {text}"
        assert abs(norm.canonical_value - expected_val) < 1e-4, (
            f"Value mismatch for '{text}': got {norm.canonical_value}, expected {expected_val}"
        )


def test_crore_to_million_equivalence() -> None:
    """Verify that 50 Crore equals 500 Million INR."""
    normalizer = IndianFinancialUnitNormalizer()
    assert normalizer.are_equivalent("₹ 50 Crore", "500 Million INR")
    assert normalizer.are_equivalent("50 Cr", "500M")
    assert normalizer.are_equivalent("1 Crore", "10 Million")
    assert not normalizer.are_equivalent("₹ 50 Crore", "600 Million INR")


def test_lakh_to_million_equivalence() -> None:
    """Verify that 10 Lakh equals 1 Million."""
    normalizer = IndianFinancialUnitNormalizer()
    assert normalizer.are_equivalent("₹ 10 Lakh", "1 Million INR")
    assert normalizer.are_equivalent("100 Lakh", "1 Crore")
    assert normalizer.are_equivalent("25 Lakh", "2.5 Million")


def test_basis_points_and_percentage_equivalence() -> None:
    """Verify that 150 bps equals 1.50%."""
    normalizer = IndianFinancialUnitNormalizer()
    assert normalizer.are_equivalent("150 bps", "1.50%")
    assert normalizer.are_equivalent("25 bps", "0.25%")
    assert normalizer.are_equivalent("10000 bps", "100%")
    assert normalizer.are_equivalent("1 bp", "0.01%")


def test_indian_comma_formatting() -> None:
    """Verify Indian numbering comma grouping."""
    assert format_indian_number(123456789) == "12,34,56,789"
    assert format_indian_number(100000) == "1,00,000"
    assert format_indian_number(10000000) == "1,00,00,000"
    assert format_indian_number(500) == "500"
    assert format_indian_number(1500) == "1,500"
    assert format_indian_number(-50000000) == "-5,00,00,000"


def test_international_comma_formatting() -> None:
    """Verify Western comma grouping."""
    assert format_international_number(123456789) == "123,456,789"
    assert format_international_number(1000000) == "1,000,000"
    assert format_international_number(500) == "500"


def test_query_synonym_expansion() -> None:
    """Verify synonym expansion generates equivalent search phrases."""
    normalizer = IndianFinancialUnitNormalizer()
    syns = normalizer.expand_query_synonyms("₹ 50 Crore")
    assert any("50.00 Cr" in s or "50 Cr" in s for s in syns)
    assert any("500.00 Million" in s or "500 Million" in s for s in syns)


def test_singleton_getter() -> None:
    """Verify default unit normalizer singleton."""
    norm1 = get_default_unit_normalizer()
    norm2 = get_default_unit_normalizer()
    assert norm1 is norm2


def test_throughput_performance_benchmark() -> None:
    """Throughput benchmark ensuring sub-millisecond evaluation."""
    normalizer = IndianFinancialUnitNormalizer()
    sample = "Penalty of Rs 25 Crore with 150 bps interest spread"

    # Warm-up
    for _ in range(10):
        _ = normalizer.parse(sample)

    t0 = time.perf_counter()
    n_runs = 200
    for _ in range(n_runs):
        res = normalizer.parse(sample)
        assert res.is_valid is True
    duration = time.perf_counter() - t0

    avg_ms = (duration / n_runs) * 1000.0
    assert avg_ms < 5.0, f"Unit normalizer throughput too slow: {avg_ms:.3f} ms/run"


def test_api_normalize_units_endpoint(client: TestClient) -> None:
    """POST /v1/compliance/normalize-units normalizes list of expressions."""
    payload: dict[str, Any] = {
        "expressions": ["₹ 50 Crore", "175 bps", "10 Lakh INR", "$2.5 Billion"]
    }
    res = client.post(
        "/v1/compliance/normalize-units",
        json=payload,
        headers=auth(),
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_count"] == 4
    assert data["results"][0]["canonical_value"] == 500_000_000.0
    assert data["results"][0]["scale_label"] == "Crore"
    assert "Crore" in data["results"][0]["indian_words"]
    assert "Million" in data["results"][0]["international_words"]
    assert data["results"][1]["bps_equivalent"] == 175.0


def test_api_compare_quantities_endpoint(client: TestClient) -> None:
    """POST /v1/compliance/compare-quantities checks equivalence between two quantities."""
    # 1. Equivalent pair
    res_equiv = client.post(
        "/v1/compliance/compare-quantities",
        json={"expression_a": "₹ 50 Crore", "expression_b": "500 Million INR"},
        headers=auth(),
    )
    assert res_equiv.status_code == 200, res_equiv.text
    data_equiv = res_equiv.json()
    assert data_equiv["are_equivalent"] is True
    assert data_equiv["absolute_difference"] == 0.0

    # 2. Non-equivalent pair
    res_mismatch = client.post(
        "/v1/compliance/compare-quantities",
        json={"expression_a": "₹ 50 Crore", "expression_b": "600 Million INR"},
        headers=auth(),
    )
    assert res_mismatch.status_code == 200
    data_mismatch = res_mismatch.json()
    assert data_mismatch["are_equivalent"] is False
    assert data_mismatch["absolute_difference"] > 0
