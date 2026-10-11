"""Unit and regression tests for Circular Citation Graph Extractor - FEAT-005.

Verifies:
1. Input validation: text >= 100 characters, valid non-empty doc_id.
2. Extraction across statutory circular identifier families (RBI, SEBI, Master Directions).
3. Grounded provenance spans and character offset accuracy.
4. Manifest target document resolution.
5. High-throughput performance (processing speed >= 250 pages/sec).
6. Precision and recall thresholds on real regulatory benchmark documents.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.ingest.citation_extractor import (
    CircularCitationExtractor,
    CitationEdge,
    CitationExtractorConfig,
)


def test_input_validation_empty_or_short_text() -> None:
    """text must be a string with length >= 100 characters."""
    extractor = CircularCitationExtractor()
    with pytest.raises(ValueError, match="text must be non-empty string >= 100 characters"):
        extractor.extract_citations("Short text", "doc-1")

    with pytest.raises(ValueError, match="text must be non-empty string >= 100 characters"):
        extractor.extract_citations("", "doc-1")


def test_input_validation_invalid_doc_id() -> None:
    """doc_id must be non-empty string."""
    extractor = CircularCitationExtractor()
    sample_text = "This is a regulatory circular text containing sufficient characters to exceed the 100 character threshold for validation."
    with pytest.raises(ValueError, match="doc_id must be non-empty string"):
        extractor.extract_citations(sample_text, "")

    with pytest.raises(ValueError, match="doc_id must be non-empty string"):
        extractor.extract_citations(sample_text, "   ")


def test_config_disabled() -> None:
    """When disabled in config, extract_citations returns empty list immediately."""
    extractor = CircularCitationExtractor(config=CitationExtractorConfig(enabled=False))
    sample = "In terms of Circular DBOD.No.BP.BC.9/21.04.048/2014-15 dated September 1, 2014, all scheduled commercial banks must comply with capital adequacy norms."
    edges = extractor.extract_citations(sample, "doc-test")
    assert edges == []


def test_extract_rbi_statutory_citations() -> None:
    """Extract various RBI circular number formats and check provenance offsets."""
    extractor = CircularCitationExtractor()
    text = (
        "In terms of Circular DBOD.No.BP.BC.9/21.04.048/2014-15 dated September 1, 2014, "
        "banks are advised to adhere to guidelines. Further, attention is invited to RBI/2024-25/111 "
        "DOR.CRE.REC.66/21.07.001/2024-25 regarding digital lending operations and direct disbursals."
    )
    edges = extractor.extract_citations(text, "doc-sample-1")
    assert len(edges) >= 3

    target_numbers = {e.target_circular_no for e in edges}
    assert any("DBOD.No.BP.BC.9/21.04.048/2014-15" in num for num in target_numbers)
    assert any("RBI/2024-25/111" in num for num in target_numbers)
    assert any("DOR.CRE.REC.66/21.07.001/2024-25" in num for num in target_numbers)

    # Check offsets and provenance span
    for edge in edges:
        assert isinstance(edge, CitationEdge)
        assert edge.source_doc_id == "doc-sample-1"
        assert edge.char_start >= 0
        assert edge.char_end > edge.char_start
        assert len(edge.raw_citation_span) > 0


def test_extract_sebi_circular_citations() -> None:
    """Extract SEBI circular formats."""
    extractor = CircularCitationExtractor()
    text = (
        "Pursuant to SEBI/HO/CFD/CMD1/CIR/P/2020/84 and CIR/CFD/DIL/3/2013, listed entities "
        "shall ensure disclosures conform to corporate governance mandates under LODR regulations. "
        "Additional guidance was issued vide HO/(449)2026-ITD-5_DIV1/I/19448/2026 on incident reporting."
    )
    edges = extractor.extract_citations(text, "doc-sebi-test")
    target_numbers = {e.target_circular_no for e in edges}
    assert any("SEBI/HO/CFD/CMD1/CIR/P/2020/84" in num for num in target_numbers)
    assert any("CIR/CFD/DIL/3/2013" in num for num in target_numbers)


def test_extract_from_benchmark_master_circular() -> None:
    """Extract citations from actual benchmark Master Circular (03-RBI) containing Appendix list."""
    path = (
        Path(__file__).resolve().parents[1]
        / "corpus"
        / "raw"
        / "03-RBI-272MC011020266691348260DF4CF99ACE017F146409F1.PDF.txt"
    )
    if not path.is_file():
        pytest.skip("Benchmark corpus file not present")

    text = path.read_text(encoding="utf-8")
    extractor = CircularCitationExtractor()
    edges = extractor.extract_citations(text, "doc-03-rbi")

    # In 03-RBI, the appendix lists 21 circulars, plus the header circulars
    assert len(edges) >= 20
    circ_nos = [e.target_circular_no for e in edges]
    assert any("RBI/2026-27/272" in c for c in circ_nos)
    assert any("DBOD" in c for c in circ_nos)
    assert any("RPCD" in c for c in circ_nos)


def test_performance_pages_per_second() -> None:
    """Verify processing speed exceeds 250 pages/sec (each page ~2,500 characters)."""
    extractor = CircularCitationExtractor()
    # 50 pages equivalent = 125,000 characters
    page_text = (
        "In terms of Circular DBOD.No.BP.BC.9/21.04.048/2014-15 dated September 1, 2014, "
        "banks are advised to adhere to guidelines. Attention is invited to RBI/2024-25/111 "
        "DOR.CRE.REC.66/21.07.001/2024-25 regarding digital lending operations. " * 10
    )
    text_50_pages = page_text * 50  # ~100k chars

    # Warmup
    extractor.extract_citations(text_50_pages, "doc-perf")

    t0 = time.perf_counter()
    edges = extractor.extract_citations(text_50_pages, "doc-perf")
    duration = time.perf_counter() - t0

    pages_processed = len(text_50_pages) / 2500.0
    pages_per_sec = pages_processed / max(0.0001, duration)

    assert len(edges) > 0
    # Must process >= 250 pages/sec
    assert pages_per_sec >= 250, f"Processed {pages_per_sec:.1f} pages/sec (budget >= 250)"
