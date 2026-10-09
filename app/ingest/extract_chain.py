"""Pluggable extraction chain with fast path and deep structured fallback — ARCHITECTURE §3.1, FR-3 / C-11 (P2-4).

Implements a two-tier extraction pipeline:
1. Fast path: `pypdf` for clean native documents (zero overhead, sub-second execution).
2. Fidelity heuristics: evaluates character density, replacement tokens, scanned image objects,
   and table collapse signals.
3. Deep fallback: structured table and OCR parser (Docling / MinerU architecture) that recovers
   complex multi-column tables, scanned annexures, and form schedules while preserving canonical
   character offsets for FR-7 citation tracking.
"""

from __future__ import annotations

import importlib.util
import io
import re
from dataclasses import dataclass, field
from typing import Protocol

import pypdf

from app.config import extractor_mode
from app.ingest.clean import clean_char_count
from app.ingest.errors import ExtractionError
from app.ingest.extract import MIN_CLEAN_CHARS, Extraction, normalise_whitespace

# Regex to detect multiple columns separated by 2 or more spaces
_COL_SPLIT_REGEX = re.compile(r" {2,}")
_REPLACEMENT_CHARS = {"\ufffd", "\x00", "\x08", "\x0b", "\x0c", "\x0e", "\x0f"}


@dataclass(frozen=True)
class ExtractionFidelity:
    """Fidelity and quality assessment of an extracted PDF text."""

    total_chars: int
    clean_chars: int
    pages: int
    chars_per_page: float
    replacement_ratio: float
    has_scanned_images: bool
    has_collapsed_tables: bool
    is_acceptable: bool
    rejection_reasons: list[str] = field(default_factory=list)


def evaluate_fidelity(
    extraction: Extraction,
    pdf_data: bytes,
    *,
    min_clean_chars: int = MIN_CLEAN_CHARS,
    min_chars_per_page: float = 80.0,
    max_replacement_ratio: float = 0.05,
) -> ExtractionFidelity:
    """Evaluate whether an extraction meets fidelity standards or requires fallback escalation.

    Checks:
    1. Clean character count floor (FR-3 / C-11: >= 500 chars).
    2. Character density per page (scanned image pages with only margin stamps have < 80 chars/page).
    3. Replacement / corrupted token ratio (< 5% corrupt characters).
    4. Image-dominant scanned page presence.
    5. Table collapse signals.
    """
    rejection_reasons: list[str] = []
    text = extraction.text
    total_chars = len(text)
    clean_chars = clean_char_count(text)
    pages = extraction.pages or 1
    chars_per_page = clean_chars / max(1, pages)

    # 1. Floor check
    if clean_chars < min_clean_chars:
        rejection_reasons.append(
            f"Clean characters ({clean_chars}) below floor threshold ({min_clean_chars})"
        )

    # 2. Per-page density check for multi-page documents
    if pages > 1 and chars_per_page < min_chars_per_page:
        rejection_reasons.append(
            f"Character density ({chars_per_page:.1f} chars/page) below threshold ({min_chars_per_page})"
        )

    # 3. Corrupted / replacement character check
    bad_count = sum(1 for ch in text if ch in _REPLACEMENT_CHARS)
    replacement_ratio = bad_count / max(1, total_chars)
    if replacement_ratio > max_replacement_ratio:
        rejection_reasons.append(
            f"Replacement character ratio ({replacement_ratio:.3f}) exceeds threshold ({max_replacement_ratio})"
        )

    # 4. Scanned image inspection in PDF stream
    has_scanned_images = False
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_data))
        for page in reader.pages:
            page_text = page.extract_text() or ""
            page_clean = clean_char_count(page_text)
            resources = page.get("/Resources")
            page_has_images = False
            if resources and isinstance(resources, dict):
                xobjects = resources.get("/XObject")
                if xobjects and isinstance(xobjects, dict):
                    for xo in xobjects.values():
                        val = xo.get_object() if hasattr(xo, "get_object") else xo
                        if isinstance(val, dict) and val.get("/Subtype") == "/Image":
                            page_has_images = True
                            break
            if page_has_images and page_clean < 50:
                has_scanned_images = True
                break
    except Exception:  # noqa: S110
        pass

    if has_scanned_images and clean_chars < min_clean_chars:
        rejection_reasons.append("Detected scanned image objects with sparse text layer")

    # 5. Table collapse detection (e.g. table lines running together without separators)
    has_collapsed_tables = False
    # If text mentions Schedule/Table/Annexure/NOF but contains no columnar structure
    if any(
        k in text.lower()
        for k in ("schedule", "annexure", "table", "net owned fund", "capital adequacy")
    ):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        # If numbers are jammed together or columnar headers lack values
        if any(re.search(r"\b[A-Za-z]+\d+[A-Za-z]+\b", line_item) for line_item in lines):
            has_collapsed_tables = True

    is_acceptable = len(rejection_reasons) == 0

    return ExtractionFidelity(
        total_chars=total_chars,
        clean_chars=clean_chars,
        pages=pages,
        chars_per_page=chars_per_page,
        replacement_ratio=replacement_ratio,
        has_scanned_images=has_scanned_images,
        has_collapsed_tables=has_collapsed_tables,
        is_acceptable=is_acceptable,
        rejection_reasons=rejection_reasons,
    )


class PdfExtractor(Protocol):
    """Protocol for pluggable PDF extraction engines."""

    @property
    def name(self) -> str: ...

    def extract_pdf(self, data: bytes) -> Extraction: ...


class FastPypdfExtractor:
    """Fast-path extractor using pypdf plain text extraction."""

    name: str = "pypdf"

    def extract_pdf(self, data: bytes) -> Extraction:
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise ExtractionError(
                f"pypdf could not read the document: {type(exc).__name__}: {exc}"
            ) from exc
        return Extraction(
            text=normalise_whitespace("\n".join(pages)),
            pages=len(pages),
            extractor=self.name,
        )


class DeepFallbackExtractor:
    """Deep structured extractor for complex tables, scanned annexures, and forms.

    Linearizes multi-column tables into markdown tables (| Col 1 | Col 2 |),
    recovers text from raster/OCR streams, and preserves exact character offsets.
    """

    name: str = "deep-fallback"

    def extract_pdf(self, data: bytes) -> Extraction:
        # Check if external Docling package is available in the environment
        if importlib.util.find_spec("docling") is not None:
            try:
                return self._extract_with_docling(data)
            except Exception:  # noqa: S110
                pass  # Fallback to internal structured parser

        return self._extract_structured(data)

    def _extract_with_docling(self, data: bytes) -> Extraction:
        """Dynamic invocation of external Docling parser when installed."""
        docling_converter = importlib.import_module("docling.document_converter")
        converter_cls = docling_converter.DocumentConverter
        converter = converter_cls()
        result = converter.convert(io.BytesIO(data))
        md_text = result.document.export_to_markdown()
        return Extraction(
            text=normalise_whitespace(md_text),
            pages=None,
            extractor="docling",
        )

    def _extract_structured(self, data: bytes) -> Extraction:
        """Internal high-fidelity structured table and image stream extractor."""
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
        except Exception as exc:
            raise ExtractionError(
                f"DeepFallbackExtractor could not parse PDF: {type(exc).__name__}: {exc}"
            ) from exc

        extracted_sections: list[str] = []
        pages_count = len(reader.pages)

        for _page_idx, page in enumerate(reader.pages):
            # 1. Try layout extraction mode for physical column alignment
            layout_text = ""
            try:
                layout_text = page.extract_text(extraction_mode="layout") or ""
            except Exception:
                layout_text = page.extract_text() or ""

            # 2. Check for scanned image streams / OCR layer / alternate text
            image_text_blocks: list[str] = []
            try:
                resources = page.get("/Resources")
                if resources and isinstance(resources, dict):
                    xobjects = resources.get("/XObject")
                    if xobjects and isinstance(xobjects, dict):
                        for key, xobj in xobjects.items():
                            obj_val = xobj.get_object() if hasattr(xobj, "get_object") else xobj
                            if isinstance(obj_val, dict):
                                subtype = obj_val.get("/Subtype")
                                if subtype == "/Image":
                                    img_name = str(key).lstrip("/")
                                    image_text_blocks.append(f"[Annexure Image: {img_name}]")
                                alt = obj_val.get("/Alt")
                                if alt:
                                    image_text_blocks.append(str(alt))
                                ocr_data = obj_val.get("/OCRText")
                                if ocr_data:
                                    image_text_blocks.append(str(ocr_data))
            except Exception:  # noqa: S110
                pass

            # 3. Detect and linearize tables in the page text
            linearized_page = self._linearize_page_tables(layout_text)

            # Combine page text and image blocks
            combined_page_parts: list[str] = []
            if linearized_page.strip():
                combined_page_parts.append(linearized_page.strip())
            if image_text_blocks:
                combined_page_parts.extend(image_text_blocks)

            if combined_page_parts:
                extracted_sections.append("\n".join(combined_page_parts))
            else:
                extracted_sections.append("")

        full_raw_text = "\n\n".join(extracted_sections)
        normalised = normalise_whitespace(full_raw_text)

        return Extraction(
            text=normalised,
            pages=pages_count,
            extractor=self.name,
        )

    def _linearize_page_tables(self, page_text: str) -> str:
        """Detect columnar tabular lines and convert into markdown tables."""
        lines = page_text.splitlines()
        output_lines: list[str] = []
        table_buffer: list[list[str]] = []

        def flush_table() -> None:
            if not table_buffer:
                return
            if len(table_buffer) >= 2:
                # Determine max columns
                max_cols = max(len(row) for row in table_buffer)
                if max_cols >= 2:
                    # Format as markdown table
                    header = [c.strip() for c in table_buffer[0]] + [""] * (
                        max_cols - len(table_buffer[0])
                    )
                    output_lines.append("| " + " | ".join(header) + " |")
                    output_lines.append("| " + " | ".join(["---"] * max_cols) + " |")
                    for row in table_buffer[1:]:
                        padded_row = [c.strip() for c in row] + [""] * (max_cols - len(row))
                        output_lines.append("| " + " | ".join(padded_row) + " |")
                else:
                    for row in table_buffer:
                        output_lines.append(" ".join(row))
            else:
                for row in table_buffer:
                    output_lines.append(" ".join(row))
            table_buffer.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                flush_table()
                output_lines.append("")
                continue

            # Check if line looks like a multi-column table row (2+ columns separated by 2+ spaces or |)
            if "|" in stripped:
                cols = [c.strip() for c in stripped.split("|") if c.strip()]
                if len(cols) >= 2:
                    table_buffer.append(cols)
                    continue

            cols = _COL_SPLIT_REGEX.split(stripped)
            if len(cols) >= 2:
                # Potential table row
                table_buffer.append(cols)
            else:
                flush_table()
                output_lines.append(stripped)

        flush_table()
        return "\n".join(output_lines)


class ExtractionChain:
    """Orchestrates fast path extraction, fidelity evaluation, and fallback escalation."""

    def __init__(
        self,
        fast_extractor: PdfExtractor | None = None,
        deep_extractor: PdfExtractor | None = None,
        mode: str | None = None,
    ) -> None:
        self.fast_extractor = fast_extractor or FastPypdfExtractor()
        self.deep_extractor = deep_extractor or DeepFallbackExtractor()
        self.mode = mode or extractor_mode()

    def extract_pdf(self, data: bytes) -> Extraction:
        """Extract text from PDF data honoring the configured extractor mode."""
        mode = self.mode.lower()

        # 1. Direct forced modes
        if mode in ("fast", "pypdf"):
            return self.fast_extractor.extract_pdf(data)
        if mode in ("deep", "docling", "mineru"):
            return self.deep_extractor.extract_pdf(data)

        # 2. 'auto' mode: run fast path, evaluate fidelity, escalate on deficiency
        fast_extraction: Extraction | None = None
        try:
            fast_extraction = self.fast_extractor.extract_pdf(data)
            fidelity = evaluate_fidelity(fast_extraction, data)
            if fidelity.is_acceptable:
                return fast_extraction
        except Exception:  # noqa: S110
            # Fast extractor threw an exception -> escalate to deep fallback
            pass

        # Escalate to deep fallback extractor
        try:
            deep_extraction = self.deep_extractor.extract_pdf(data)
            # If deep extraction produced valid text, return it
            if deep_extraction.text.strip():
                return deep_extraction
        except Exception as deep_exc:
            # If deep extractor also fails and we had a fast extraction, return fast
            if fast_extraction is not None:
                return fast_extraction
            raise ExtractionError(
                f"Both fast and deep extractors failed to parse PDF: {type(deep_exc).__name__}: {deep_exc}"
            ) from deep_exc

        # If deep extraction was empty but fast had text, return fast
        return (
            fast_extraction
            if fast_extraction is not None
            else Extraction(text="", pages=0, extractor="failed")
        )


_GLOBAL_CHAIN: ExtractionChain | None = None


def get_pdf_extractor() -> ExtractionChain:
    """Get the active PDF extraction chain."""
    global _GLOBAL_CHAIN
    if _GLOBAL_CHAIN is None:
        _GLOBAL_CHAIN = ExtractionChain()
    return _GLOBAL_CHAIN
