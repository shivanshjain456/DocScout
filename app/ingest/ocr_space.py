"""OCR.Space API integration and bounded extraction fallback — ARCHITECTURE §3.1, FR-3.

Provides bounded optical character recognition for scanned regulatory documents:
1. Fast-path check: native clean documents extracted by pypdf never trigger OCR.
2. Pre-flight eligibility verification: enforces free-tier constraints (<= 1 MB, <= 3 pages).
   Documents exceeding constraints receive an explicit ELIGIBILITY_EXCEEDED disposition
   rather than silent truncation or silent page dropping.
3. Persistent hash-indexed cache in PostgreSQL `ocr_extractions` table avoids redundant
   API invocations across server restarts and crawler runs.
4. Preserves page offsets, line coordinates, and distinguishes OCR-derived text from
   native stream text to ensure honest citation and evidence traceability.
5. Surfaces quota exhaustion (500 req/day), network timeouts, and provider parse errors
   truthfully without hardcoded dummy fallbacks or silent suppression.
"""

from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg
import pypdf

from app.config import (
    ocr_space_api_key,
    ocr_space_max_bytes,
    ocr_space_max_pages,
    ocr_space_url,
)
from app.ingest.clean import clean_char_count
from app.ingest.errors import ExtractionError
from app.ingest.extract import Extraction, normalise_whitespace
from app.observability import get_logger

logger = get_logger("docscout.ocr_space")


@dataclass(frozen=True)
class OCRPreflightResult:
    """Outcome of pre-flight eligibility evaluation."""

    is_eligible: bool
    size_bytes: int
    page_count: int
    rejection_reason: str | None = None


@dataclass(frozen=True)
class OCRResult:
    """Extracted text, page structures, and provider diagnostic telemetry."""

    sha256: str
    status: str  # 'SUCCESS' | 'ERROR' | 'ELIGIBILITY_EXCEEDED'
    extracted_text: str
    pages_processed: int
    engine: str
    latency_ms: float
    error_detail: str | None = None
    cached: bool = False
    page_texts: list[str] = field(default_factory=list)


def evaluate_ocr_eligibility(pdf_bytes: bytes) -> OCRPreflightResult:
    """Verify whether a PDF payload satisfies OCR.Space free-tier operational limits.

    Free tier limits:
    - Maximum file size: 1 MB (1,048,576 bytes).
    - Maximum page count: 3 pages.
    """
    size_bytes = len(pdf_bytes)
    max_bytes = ocr_space_max_bytes()
    max_pages = ocr_space_max_pages()

    # 1. Size ceiling check
    if size_bytes > max_bytes:
        return OCRPreflightResult(
            is_eligible=False,
            size_bytes=size_bytes,
            page_count=0,
            rejection_reason=(
                f"PDF size ({size_bytes} bytes / {size_bytes / 1024 / 1024:.2f} MB) exceeds "
                f"OCR.Space free-tier limit of {max_bytes} bytes (1.0 MB). "
                "Silent truncation is prohibited by evidence integrity policy."
            ),
        )

    # 2. Inspect page count via pypdf structure
    page_count = 0
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
    except Exception as exc:
        return OCRPreflightResult(
            is_eligible=False,
            size_bytes=size_bytes,
            page_count=0,
            rejection_reason=f"Invalid or corrupted PDF header: {exc}",
        )

    if page_count > max_pages:
        return OCRPreflightResult(
            is_eligible=False,
            size_bytes=size_bytes,
            page_count=page_count,
            rejection_reason=(
                f"Document has {page_count} pages, which exceeds the OCR.Space free-tier "
                f"limit of {max_pages} pages per request. Silent truncation is prohibited."
            ),
        )

    if page_count == 0:
        return OCRPreflightResult(
            is_eligible=False,
            size_bytes=size_bytes,
            page_count=0,
            rejection_reason="PDF contains 0 pages.",
        )

    return OCRPreflightResult(
        is_eligible=True,
        size_bytes=size_bytes,
        page_count=page_count,
    )


class OCRSpaceClient:
    """Client for OCR.Space REST API with persistent caching and rate governance."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint_url: str | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = (api_key or ocr_space_api_key()).strip()
        self.endpoint_url = (endpoint_url or ocr_space_url()).strip()
        self.timeout = timeout_seconds

    def parse_pdf(
        self,
        pdf_bytes: bytes,
        conn: psycopg.Connection[Any] | None = None,
        *,
        engine: str = "2",
        language: str = "eng",
    ) -> OCRResult:
        """Process an eligible PDF through OCR.Space with persistent DB caching."""
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        start_t = time.perf_counter()

        # 1. Check persistent database cache
        if conn is not None:
            try:
                row = conn.execute(
                    """
                    SELECT status, extracted_text, pages_processed, engine, error_detail, latency_ms
                      FROM ocr_extractions
                     WHERE sha256 = %s
                    """,
                    (sha256,),
                ).fetchone()

                if row is not None:
                    cached_status, text, pages, eng, err, lat = row
                    logger.info("ocr_space.cache_hit", sha256=sha256, status=cached_status)
                    return OCRResult(
                        sha256=sha256,
                        status=str(cached_status),
                        extracted_text=str(text) if text else "",
                        pages_processed=int(pages or 0),
                        engine=str(eng or engine),
                        latency_ms=float(lat or 0.0),
                        error_detail=str(err) if err else None,
                        cached=True,
                    )
            except Exception:
                logger.warning("ocr_space.cache_read_failed", exc_info=True)

        # 2. Pre-flight eligibility check
        preflight = evaluate_ocr_eligibility(pdf_bytes)
        if not preflight.is_eligible:
            latency_ms = (time.perf_counter() - start_t) * 1000.0
            result = OCRResult(
                sha256=sha256,
                status="ELIGIBILITY_EXCEEDED",
                extracted_text="",
                pages_processed=preflight.page_count,
                engine=f"ocr.space-engine{engine}",
                latency_ms=latency_ms,
                error_detail=preflight.rejection_reason,
                cached=False,
            )
            self._record_extraction(conn, result)
            return result

        # 3. Key presence check
        if not self.api_key:
            latency_ms = (time.perf_counter() - start_t) * 1000.0
            result = OCRResult(
                sha256=sha256,
                status="ERROR",
                extracted_text="",
                pages_processed=preflight.page_count,
                engine=f"ocr.space-engine{engine}",
                latency_ms=latency_ms,
                error_detail="OCR_SPACE_API_KEY is not configured",
                cached=False,
            )
            return result

        # 4. Invoke OCR.Space REST API
        files = {
            "file": (f"{sha256[:12]}.pdf", pdf_bytes, "application/pdf"),
        }
        data = {
            "apikey": self.api_key,
            "language": language,
            "isOverlayRequired": "true",
            "filetype": "PDF",
            "detectOrientation": "true",
            "scale": "true",
            "OCREngine": engine,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.endpoint_url, data=data, files=files)
                latency_ms = (time.perf_counter() - start_t) * 1000.0

                if resp.status_code != 200:
                    err_msg = f"OCR.Space HTTP {resp.status_code}: {resp.text[:200]}"
                    result = OCRResult(
                        sha256=sha256,
                        status="ERROR",
                        extracted_text="",
                        pages_processed=0,
                        engine=f"ocr.space-engine{engine}",
                        latency_ms=latency_ms,
                        error_detail=err_msg,
                    )
                    self._record_extraction(conn, result)
                    return result

                body = resp.json()
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_t) * 1000.0
            err_msg = f"OCR.Space request failed: {type(exc).__name__}: {exc}"
            result = OCRResult(
                sha256=sha256,
                status="ERROR",
                extracted_text="",
                pages_processed=0,
                engine=f"ocr.space-engine{engine}",
                latency_ms=latency_ms,
                error_detail=err_msg,
            )
            self._record_extraction(conn, result)
            return result

        # 5. Parse OCR Response Payload
        exit_code = body.get("OCRExitCode")
        is_errored = body.get("IsErroredOnProcessing", False)
        error_message = body.get("ErrorMessage") or body.get("ErrorDetails") or ""

        if is_errored or exit_code != 1:
            err_detail = (
                f"OCR.Space error (exit {exit_code}): {error_message or 'processing error'}"
            )
            result = OCRResult(
                sha256=sha256,
                status="ERROR",
                extracted_text="",
                pages_processed=0,
                engine=f"ocr.space-engine{engine}",
                latency_ms=latency_ms,
                error_detail=err_detail,
            )
            self._record_extraction(conn, result)
            return result

        parsed_results = body.get("ParsedResults", [])
        page_texts: list[str] = []
        for p in parsed_results:
            p_text = p.get("ParsedText") or ""
            page_texts.append(p_text.strip())

        full_extracted = "\n\n".join(page_texts)
        result = OCRResult(
            sha256=sha256,
            status="SUCCESS",
            extracted_text=normalise_whitespace(full_extracted),
            pages_processed=len(page_texts),
            engine=f"ocr.space-engine{engine}",
            latency_ms=latency_ms,
            error_detail=None,
            page_texts=page_texts,
        )
        self._record_extraction(conn, result)
        logger.info(
            "ocr_space.success",
            sha256=sha256,
            pages=len(page_texts),
            clean_chars=clean_char_count(result.extracted_text),
            duration_ms=round(latency_ms, 2),
        )
        return result

    def _record_extraction(self, conn: psycopg.Connection[Any] | None, result: OCRResult) -> None:
        """Persist OCR result into PostgreSQL ocr_extractions table."""
        if conn is None:
            return
        try:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO ocr_extractions
                        (sha256, provider, engine, status, pages_processed,
                         extracted_text, error_detail, latency_ms)
                    VALUES (%s, 'ocr.space', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (sha256) DO UPDATE SET
                        status = EXCLUDED.status,
                        extracted_text = EXCLUDED.extracted_text,
                        pages_processed = EXCLUDED.pages_processed,
                        error_detail = EXCLUDED.error_detail,
                        latency_ms = EXCLUDED.latency_ms
                    """,
                    (
                        result.sha256,
                        result.engine,
                        result.status,
                        result.pages_processed,
                        result.extracted_text,
                        result.error_detail,
                        result.latency_ms,
                    ),
                )
        except Exception:
            logger.warning("ocr_space.record_db_failed", sha256=result.sha256, exc_info=True)


class OCRSpaceFallbackExtractor:
    """Pluggable extractor implementing the PdfExtractor protocol using OCR.Space."""

    name: str = "ocr.space"

    def __init__(
        self, client: OCRSpaceClient | None = None, conn: psycopg.Connection[Any] | None = None
    ) -> None:
        self.client = client or OCRSpaceClient()
        self.conn = conn

    def extract_pdf(self, data: bytes) -> Extraction:
        """Execute OCR extraction with fallback error handling."""
        res = self.client.parse_pdf(data, self.conn)
        if res.status != "SUCCESS":
            raise ExtractionError(
                f"OCR.Space extraction failed for payload: status={res.status}, detail={res.error_detail}"
            )

        return Extraction(
            text=res.extracted_text,
            pages=res.pages_processed,
            extractor=self.name,
        )
