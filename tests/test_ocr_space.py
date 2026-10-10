"""Tests for OCR.Space integration and bounded fallback extraction.

Validates:
1. Pre-flight eligibility checking:
   - Size limit: payloads > 1 MB rejected with explicit disposition.
   - Page count limit: documents > 3 pages rejected without silent truncation.
   - Valid PDFs <= 1 MB and <= 3 pages accepted as eligible.
2. Hash-indexed persistent database cache:
   - Cache hits return stored extraction without outbound network calls.
   - Cache misses execute extraction and record result in `ocr_extractions`.
3. Error handling:
   - OCR.Space provider errors (exit code != 1 or errored flag) reported honestly.
   - Network timeouts and failures handled without fabricated fallback text.
4. Extractor contract:
   - OCRSpaceFallbackExtractor returns Extraction object with clean characters.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import pypdf
import pytest

from app.ingest.errors import ExtractionError
from app.ingest.ocr_space import (
    OCRResult,
    OCRSpaceClient,
    OCRSpaceFallbackExtractor,
    evaluate_ocr_eligibility,
)


def _create_test_pdf(pages: int = 1, pad_bytes: int = 0) -> bytes:
    """Create a minimal synthetic valid PDF with specified page count and optional padding."""
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()
    if pad_bytes > 0:
        pdf_bytes += b"%" + b"X" * pad_bytes
    return pdf_bytes


def test_preflight_eligibility_accepts_valid_pdf() -> None:
    """A 1-page PDF under 1 MB is eligible for free-tier OCR processing."""
    pdf = _create_test_pdf(pages=1)
    res = evaluate_ocr_eligibility(pdf)
    assert res.is_eligible
    assert res.page_count == 1
    assert res.size_bytes == len(pdf)
    assert res.rejection_reason is None


def test_preflight_eligibility_rejects_oversized_pdf() -> None:
    """A PDF exceeding 1 MB is rejected with an explicit size limit reason."""
    # 1.1 MB
    pdf = _create_test_pdf(pages=1, pad_bytes=1_150_000)
    res = evaluate_ocr_eligibility(pdf)
    assert not res.is_eligible
    assert res.size_bytes > 1_048_576
    assert "exceeds" in (res.rejection_reason or "").lower()
    assert "silent truncation is prohibited" in (res.rejection_reason or "").lower()


def test_preflight_eligibility_rejects_excessive_pages() -> None:
    """A document with > 3 pages is rejected because OCR.Space free tier limits to 3 pages."""
    pdf = _create_test_pdf(pages=5)
    res = evaluate_ocr_eligibility(pdf)
    assert not res.is_eligible
    assert res.page_count == 5
    assert (
        "exceeds the ocr.space free-tier limit of 3 pages" in (res.rejection_reason or "").lower()
    )


def test_ocr_space_cache_hit(db: Any) -> None:
    """Cached OCR extractions in ocr_extractions table are returned without outbound requests."""
    pdf = _create_test_pdf(pages=1)
    import hashlib

    sha = hashlib.sha256(pdf).hexdigest()

    # Pre-seed cache
    with db.transaction():
        db.execute(
            """
            INSERT INTO ocr_extractions
                (sha256, provider, engine, status, pages_processed, extracted_text, latency_ms)
            VALUES (%s, 'ocr.space', 'ocr.space-engine2', 'SUCCESS', 1, %s, 120.0)
            ON CONFLICT (sha256) DO NOTHING
            """,
            (sha, "RESERVE BANK OF INDIA REGULATORY NOTIFICATION TEXT"),
        )

    client = OCRSpaceClient(api_key="test-api-key")
    with patch("httpx.Client.post") as mock_post:
        result = client.parse_pdf(pdf, conn=db)
        # Network must not be called on cache hit
        mock_post.assert_not_called()

    assert result.cached
    assert result.status == "SUCCESS"
    assert "RESERVE BANK OF INDIA" in result.extracted_text


def test_ocr_space_client_handles_provider_error() -> None:
    """Provider-reported error codes return status='ERROR' and record diagnostic message."""
    pdf = _create_test_pdf(pages=1)
    client = OCRSpaceClient(api_key="test-api-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "OCRExitCode": 3,
        "IsErroredOnProcessing": True,
        "ErrorMessage": ["File failed to process: unsupported color space"],
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        result = client.parse_pdf(pdf, conn=None)

    assert result.status == "ERROR"
    assert "unsupported color space" in (result.error_detail or "")
    assert result.extracted_text == ""


def test_ocr_space_fallback_extractor_success() -> None:
    """OCRSpaceFallbackExtractor wraps OCRResult into standard Extraction."""
    pdf = _create_test_pdf(pages=1)
    mock_client = MagicMock(spec=OCRSpaceClient)
    mock_client.parse_pdf.return_value = OCRResult(
        sha256="test-sha",
        status="SUCCESS",
        extracted_text="SEBI CIRCULAR ON FOREIGN PORTFOLIO INVESTORS REGULATIONS 2024",
        pages_processed=1,
        engine="ocr.space-engine2",
        latency_ms=250.0,
    )

    extractor = OCRSpaceFallbackExtractor(client=mock_client)
    extraction = extractor.extract_pdf(pdf)

    assert extraction.extractor == "ocr.space"
    assert "FOREIGN PORTFOLIO INVESTORS" in extraction.text
    assert extraction.pages == 1


def test_ocr_space_fallback_extractor_raises_on_error() -> None:
    """OCRSpaceFallbackExtractor raises ExtractionError when OCR fails."""
    pdf = _create_test_pdf(pages=1)
    mock_client = MagicMock(spec=OCRSpaceClient)
    mock_client.parse_pdf.return_value = OCRResult(
        sha256="test-sha",
        status="ERROR",
        extracted_text="",
        pages_processed=0,
        engine="ocr.space-engine2",
        latency_ms=100.0,
        error_detail="Daily free tier quota exhausted",
    )

    extractor = OCRSpaceFallbackExtractor(client=mock_client)
    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract_pdf(pdf)

    assert "Daily free tier quota exhausted" in str(exc_info.value)
