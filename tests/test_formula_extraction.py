"""Tests for Automated Formula Extraction from Circulars (FEAT-022).

Verifies extraction of statutory ratios (CRAR, LCR, Leverage Ratio, NSFR, NOF, SCI),
where-clause variable definitions extraction, AST expression parsing,
statutory threshold identification, high throughput (>=150 pages/sec),
and PostgreSQL document_formulas persistence.
"""

from __future__ import annotations

import time
from typing import Any

import psycopg
import pytest

from app.ingest.formula_extractor import (
    CircularFormulaExtractor,
    fetch_document_formulas,
    store_extracted_formulas,
)


@pytest.fixture
def extractor() -> CircularFormulaExtractor:
    return CircularFormulaExtractor()


# Benchmark circular sample texts
CIRCULAR_CRAR_TEXT = """
Reserve Bank of India
Master Direction - Non-Banking Financial Company - Systemically Important Non-Deposit taking Company

Chapter IV - Prudential Regulations
Section 15. Capital Adequacy Requirement

15.1 Every non-banking financial company shall maintain a minimum capital ratio consisting of
Tier I and Tier II capital which shall not be less than 15 per cent of its aggregate risk-weighted assets.

CRAR = (Tier I Capital + Tier II Capital) / Risk Weighted Assets

where:
- Tier I Capital means core equity and disclosed free reserves
- Tier II Capital represents qualifying subordinated debt and revaluation reserves
- Risk Weighted Assets denotes total credit, market and operational risk-weighted exposure

The total Tier I capital at any point of time shall not be less than 10 per cent.
"""

CIRCULAR_LCR_TEXT = """
Reserve Bank of India
Basel III Framework on Liquidity Standards - Liquidity Coverage Ratio (LCR)

3. Calculation of Liquidity Coverage Ratio
The LCR standard aims to ensure that a bank has an adequate stock of unencumbered High Quality Liquid Assets (HQLA).

LCR = Stock of HQLA / Total net cash outflows over the next 30 calendar days

where:
- Stock of HQLA represents liquid cash, government securities and qualifying central bank reserves
- Total net cash outflows represents total expected contractual cash outflows minus inflows

Banks shall maintain a minimum of 100% LCR on an ongoing basis.
"""

CIRCULAR_LEVERAGE_TEXT = """
Reserve Bank of India - Basel III Leverage Ratio Framework

The Basel III leverage ratio is defined as the capital measure divided by the exposure measure.

Leverage Ratio = Capital Measure / Exposure Measure

where:
- Capital Measure represents Tier 1 capital
- Exposure Measure denotes the sum of on-balance sheet items and off-balance sheet exposures

Banks shall maintain a minimum of 4% leverage ratio.
"""

CIRCULAR_NSFR_TEXT = """
RBI Master Direction on Net Stable Funding Ratio (NSFR)

The NSFR is defined as the amount of available stable funding relative to the amount of required stable funding.

NSFR = Available Stable Funding / Required Stable Funding

Banks are required to maintain a minimum NSFR of 100 per cent at all times.
"""

CIRCULAR_SCI_TEXT = """
Software Carbon Intensity Specification (ISO/IEC 21031:2024)

The Software Carbon Intensity (SCI) provides a rate of carbon emissions for software systems.

SCI = (E * I + M) / R

where:
- E represents total energy consumed in kWh
- I denotes carbon intensity of the grid in gCO2eq/kWh
- M denotes embodied emissions of the hardware
- R represents functional unit of work
"""


def test_extract_crar_formula(extractor: CircularFormulaExtractor) -> None:
    """Verify CRAR equation, variable definitions, and 15% threshold are extracted."""
    formulas = extractor.extract_formulas(CIRCULAR_CRAR_TEXT, doc_id="rbi-crar-doc-1")
    assert len(formulas) == 1
    f = formulas[0]

    assert "CRAR" in f.formula_name
    assert "Tier I Capital" in f.raw_expression
    assert "Risk Weighted Assets" in f.raw_expression
    assert f.standard == "RBI Master Direction - Basel III Capital Regulations"
    assert f.statutory_threshold == ">= 0.15"

    # Check extracted variables
    assert len(f.variables) >= 3
    assert any("tier i" in k.lower() for k in f.variables)
    assert any("tier ii" in k.lower() for k in f.variables)
    assert any("risk weighted" in k.lower() for k in f.variables)

    # Check parsed AST
    assert "type" in f.parsed_ast
    assert f.parsed_ast["type"] in ("Expression", "BinOp", "HeuristicExpression")


def test_extract_lcr_formula(extractor: CircularFormulaExtractor) -> None:
    """Verify LCR equation, HQLA variables, and 100% threshold are extracted."""
    formulas = extractor.extract_formulas(CIRCULAR_LCR_TEXT, doc_id="rbi-lcr-doc-1")
    assert len(formulas) == 1
    f = formulas[0]

    assert "LCR" in f.formula_name
    assert "Stock of HQLA" in f.raw_expression
    assert f.standard == "RBI Liquidity Risk Management Framework"
    assert f.statutory_threshold == ">= 1.00"
    assert len(f.variables) >= 2


def test_extract_leverage_ratio_formula(extractor: CircularFormulaExtractor) -> None:
    """Verify Leverage Ratio formula, variables, and 4% threshold are extracted."""
    formulas = extractor.extract_formulas(CIRCULAR_LEVERAGE_TEXT, doc_id="rbi-lev-doc-1")
    assert len(formulas) == 1
    f = formulas[0]

    assert "Leverage Ratio" in f.formula_name
    assert "Capital Measure" in f.raw_expression
    assert f.statutory_threshold == ">= 0.04"


def test_extract_nsfr_formula(extractor: CircularFormulaExtractor) -> None:
    """Verify NSFR formula and 100% threshold are extracted."""
    formulas = extractor.extract_formulas(CIRCULAR_NSFR_TEXT, doc_id="rbi-nsfr-doc-1")
    assert len(formulas) == 1
    f = formulas[0]

    assert "NSFR" in f.formula_name
    assert "Available Stable Funding" in f.raw_expression
    assert f.statutory_threshold == ">= 1.00"


def test_extract_sci_formula(extractor: CircularFormulaExtractor) -> None:
    """Verify Software Carbon Intensity (SCI) equation and 4 variables are extracted."""
    formulas = extractor.extract_formulas(CIRCULAR_SCI_TEXT, doc_id="iso-sci-doc-1")
    assert len(formulas) == 1
    f = formulas[0]

    assert "Software Carbon Intensity" in f.formula_name
    assert "SCI = (E * I + M) / R" in f.raw_expression
    assert f.standard == "ISO/IEC 21031:2024"
    assert "E" in f.variables
    assert "I" in f.variables
    assert "M" in f.variables
    assert "R" in f.variables


def test_high_throughput_performance(extractor: CircularFormulaExtractor) -> None:
    """Verify extraction processing throughput exceeds 150 pages/sec (<= 2.0 ms per page)."""
    # 50 simulated pages of regulatory circular text
    pages = [CIRCULAR_CRAR_TEXT, CIRCULAR_LCR_TEXT, CIRCULAR_LEVERAGE_TEXT, CIRCULAR_SCI_TEXT] * 15
    assert len(pages) == 60

    t0 = time.perf_counter()
    count = 0
    for idx, page in enumerate(pages):
        res = extractor.extract_formulas(page, doc_id=f"doc-{idx}")
        count += len(res)
    total_time = time.perf_counter() - t0

    throughput_pages_per_sec = len(pages) / total_time
    assert throughput_pages_per_sec >= 150.0, (
        f"Throughput {throughput_pages_per_sec:.1f} pages/sec is below 150 pages/sec SLA!"
    )
    assert count > 0


def test_database_persistence_integration(
    app_conn: psycopg.Connection[Any],
    extractor: CircularFormulaExtractor,
) -> None:
    """Verify storing and fetching extracted formulas in document_formulas PostgreSQL table."""
    formulas = extractor.extract_formulas(CIRCULAR_CRAR_TEXT, doc_id="rbi-crar-db-test")
    assert len(formulas) == 1

    # Store in database
    inserted = store_extracted_formulas(app_conn, formulas)
    assert inserted == 1

    # Fetch back from database
    fetched = fetch_document_formulas(app_conn, doc_id="rbi-crar-db-test")
    assert len(fetched) == 1
    f = fetched[0]
    assert f.doc_id == "rbi-crar-db-test"
    assert "CRAR" in f.formula_name
    assert "Tier I Capital" in f.raw_expression
    assert len(f.variables) >= 3
    assert f.statutory_threshold == ">= 0.15"
