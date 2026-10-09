"""Tests for Pluggable Extraction Chain with Deep Fallback (P2-4).

Enforces:
1. Fast-path pypdf preservation: clean native PDFs extract identically with zero regression.
2. Fidelity heuristics: correctly identify stubs, low density, scanned image pages, and corrupted text.
3. Scanned annexure recovery: scanned PDF fixture fails fast path but deep fallback successfully
   recovers structured table data, regulatory requirements, and statutory citations.
4. Extractor mode overrides: DOCSCOUT_EXTRACTOR configuration ('auto', 'fast', 'deep').
5. Offset preservation: canonical normalization ensures character spans remain stable (FR-7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.clean import clean_char_count, clean_preserving_offsets
from app.ingest.extract import Extraction, extract_pdf
from app.ingest.extract_chain import (
    ExtractionChain,
    FastPypdfExtractor,
    evaluate_fidelity,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sebi_scanned_annexure.pdf"
CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus" / "raw"


def test_clean_document_fast_path_zero_regression() -> None:
    """Clean corpus documents use the pypdf fast path with exact byte-for-byte character fidelity."""
    corpus_pdfs = list(CORPUS_DIR.glob("*.pdf")) + list(CORPUS_DIR.glob("*.PDF"))
    if not corpus_pdfs:
        pytest.skip("No corpus PDFs found in corpus/raw")

    sample_pdf = corpus_pdfs[0]
    pdf_bytes = sample_pdf.read_bytes()

    fast = FastPypdfExtractor()
    fast_result = fast.extract_pdf(pdf_bytes)

    chain = ExtractionChain(mode="auto")
    chain_result = chain.extract_pdf(pdf_bytes)

    assert chain_result.extractor == "pypdf"
    assert chain_result.pages == fast_result.pages
    assert chain_result.text == fast_result.text
    assert len(chain_result.text) == len(fast_result.text)


def test_fidelity_heuristics_evaluation() -> None:
    """Fidelity heuristics correctly detect stubs, low density, and character corruption."""
    pdf_bytes = FIXTURE_PATH.read_bytes()

    # 1. High fidelity synthetic extraction
    good_text = "This is a clean regulatory document. " * 30  # ~1100 chars
    good_ext = Extraction(text=good_text, pages=1, extractor="pypdf")
    good_fid = evaluate_fidelity(good_ext, pdf_bytes)
    assert good_fid.is_acceptable is True
    assert len(good_fid.rejection_reasons) == 0

    # 2. Short extraction (< 500 clean chars)
    short_text = "Short stub notice with minimal content."
    short_ext = Extraction(text=short_text, pages=1, extractor="pypdf")
    short_fid = evaluate_fidelity(short_ext, pdf_bytes)
    assert short_fid.is_acceptable is False
    assert any("below floor threshold" in r for r in short_fid.rejection_reasons)

    # 3. Low density per page
    sparse_text = (
        "Sparse text spread across many pages. " * 5
    )  # ~190 chars on 5 pages = 38 chars/page
    sparse_ext = Extraction(text=sparse_text, pages=5, extractor="pypdf")
    sparse_fid = evaluate_fidelity(sparse_ext, pdf_bytes, min_chars_per_page=80.0)
    assert sparse_fid.is_acceptable is False
    assert any("Character density" in r for r in sparse_fid.rejection_reasons)

    # 4. Corrupted character flood (> 5% replacement characters)
    corrupted_text = "Legitimate text " * 10 + "\ufffd\x00\x08" * 20
    corrupted_ext = Extraction(text=corrupted_text, pages=1, extractor="pypdf")
    corrupt_fid = evaluate_fidelity(corrupted_ext, pdf_bytes)
    assert corrupt_fid.is_acceptable is False
    assert any("Replacement character ratio" in r for r in corrupt_fid.rejection_reasons)


def test_scanned_fixture_fast_path_fails_fidelity() -> None:
    """Naive pypdf on scanned annexure fails fidelity check due to sparse extracted text."""
    pdf_bytes = FIXTURE_PATH.read_bytes()

    fast = FastPypdfExtractor()
    fast_result = fast.extract_pdf(pdf_bytes)

    fidelity = evaluate_fidelity(fast_result, pdf_bytes)
    assert fidelity.is_acceptable is False
    assert fidelity.clean_chars < 500  # Fails FR-3 minimum floor
    assert fidelity.has_scanned_images is True

    # Naive pypdf misses all regulatory provisions in the scanned annexure
    assert "Rs 50 Crore" not in fast_result.text
    assert "Category I Merchant Banker" not in fast_result.text
    assert "Section 45-IA" not in fast_result.text


def test_scanned_fixture_chain_escalates_to_deep_fallback() -> None:
    """ExtractionChain automatically detects low fidelity and recovers full tabular annexure."""
    pdf_bytes = FIXTURE_PATH.read_bytes()

    chain = ExtractionChain(mode="auto")
    result = chain.extract_pdf(pdf_bytes)

    # Proves automatic escalation
    assert result.extractor == "deep-fallback"
    assert clean_char_count(result.text) >= 500  # Clears FR-3 floor

    # Key provisions and tables are recovered
    assert "Category I Merchant Banker" in result.text
    assert "Rs 50 Crore" in result.text
    assert "15.0 Percent Capital Adequacy" in result.text
    assert "Portfolio Manager PMS" in result.text
    assert "Rs 10 Crore" in result.text
    assert "Investment Advisor IA" in result.text
    assert "Rs 5 Crore" in result.text
    assert "Section 45-IA of the Reserve Bank of India Act, 1934" in result.text
    assert "Securities and Exchange Board of India Act, 1992" in result.text

    # Verify integration with main extract_pdf entrypoint
    delegated_result = extract_pdf(pdf_bytes)
    assert delegated_result.extractor == "deep-fallback"
    assert "Rs 50 Crore" in delegated_result.text


def test_extractor_mode_overrides() -> None:
    """Explicit configuration modes force fast or deep extractors."""
    pdf_bytes = FIXTURE_PATH.read_bytes()

    # Forced fast mode: returns pypdf even if fidelity is low
    chain_fast = ExtractionChain(mode="fast")
    res_fast = chain_fast.extract_pdf(pdf_bytes)
    assert res_fast.extractor == "pypdf"
    assert clean_char_count(res_fast.text) < 500

    # Forced deep mode: returns deep-fallback
    chain_deep = ExtractionChain(mode="deep")
    res_deep = chain_deep.extract_pdf(pdf_bytes)
    assert res_deep.extractor == "deep-fallback"
    assert clean_char_count(res_deep.text) >= 500


def test_character_offset_preservation_and_clean_invariants() -> None:
    """Extraction output preserves 1:1 character offset indexing under clean_preserving_offsets (FR-7)."""
    pdf_bytes = FIXTURE_PATH.read_bytes()
    chain = ExtractionChain(mode="auto")
    result = chain.extract_pdf(pdf_bytes)

    # Canonical text must be non-empty and stripped
    assert result.text == result.text.strip()
    assert "  " not in result.text  # Normalized single-space whitespace

    # Offsets must match 1:1 after clean_preserving_offsets
    cleaned = clean_preserving_offsets(result.text)
    assert len(cleaned) == len(result.text)

    # Specific phrase index check
    target_phrase = "Rs 50 Crore"
    idx = result.text.find(target_phrase)
    assert idx != -1
    span = result.text[idx : idx + len(target_phrase)]
    assert span == target_phrase
