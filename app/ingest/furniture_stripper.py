"""Intelligent Regulatory Furniture & Gazette Stamp Stripper (FEAT-065).

Strips repetitive official gazette stamps, authority publication banners, running page footers,
and government press colophons from regulatory documents without altering character offsets
of substantive statutory clauses.

Enforces strict length preservation: len(cleaned_text) == len(raw_text).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

from app.api.metrics import FURNITURE_TOKENS_STRIPPED_TOTAL

logger = structlog.get_logger(__name__)


@dataclass
class FurnitureConfig:
    """Configuration toggles for furniture stripping categories."""

    strip_gazette_stamps: bool = True
    strip_page_numbers: bool = True
    strip_watermarks: bool = True
    strip_printer_signatures: bool = True
    strip_authority_banners: bool = True


@dataclass
class StrippedFurnitureSummary:
    """Diagnostic outcome of furniture stripping operation."""

    total_characters_stripped: int = 0
    total_tokens_stripped: int = 0
    categories_matched: list[str] = field(default_factory=list)


# ==============================================================================
# Compiled High-Performance Furniture Patterns
# ==============================================================================

# 1. Gazette header stamps and statutory section indicators
GAZETTE_STAMP_PATTERNS = [
    re.compile(r"(?i)\bTHE\s+GAZETTE\s+OF\s+INDIA\s*[:\-]?\s*EXTRAORDINARY\b"),
    re.compile(r"(?i)\bPUBLISHED\s+BY\s+AUTHORITY\b"),
    re.compile(r"(?i)\bPART\s+[IVX\d]+[\-\s]+Section\s+\d+[\-\s]+Sub-section\s*\([ivx\d]+\)\b"),
    re.compile(
        r"(?i)\[\s*(?:भाग|Part)\s+[IVX\d]+[\-\s]+(?:खण्ड|Section|Sec\.?)\s*[\d\(\)a-z]+\s*\]"
    ),
    re.compile(r"(?i)\bEXTRAORDINARY\s+PART\s+[IVX\d]+[\-\s]+SECTION\s+\d+\b"),
]

# 2. Authority publication banners, dates, and registration numbers
AUTHORITY_BANNER_PATTERNS = [
    re.compile(r"(?i)\bREGD\.?\s*NO\.?\s*[A-Z\d\.\-/]+"),
    re.compile(
        r"(?i)\bNEW\s+DELHI\s*,\s*(?:[A-Z]+,\s*)?[A-Z]+\s+\d{1,2}\s*,\s*\d{4}(?:\s*/\s*[^,\n\r]+)?"
    ),
    re.compile(r"(?i)\b\d{1,5}\s+GI\s*/\s*\d{2,4}\b"),
    re.compile(r"(?i)\bMINISTRY\s+OF\s+FINANCE\s*\([A-Za-z\s]+\)\s*NOTIFICATION\b"),
]

# 3. Running page footers and page numbering
PAGE_NUMBER_PATTERNS = [
    re.compile(r"(?i)\bPage\s+\d+\s+of\s+\d+\b"),
    re.compile(r"(?i)\[\s*Page\s+\d+\s*\]"),
    re.compile(r"(?i)\bपृ.{0,3}ठ\s*सं\.?\s*\d+\b"),
    re.compile(
        r"(?i)(?<=\n)\s*\d+\s*(?=\n|$)"
    ),  # Standalone solitary page numbers on isolated lines
]

# 4. Government press printer signatures and colophons
PRINTER_SIGNATURE_PATTERNS = [
    re.compile(r"(?i)\bPRINTED\s+BY\s+THE\s+MANAGER\s*,\s*GOVERNMENT\s+OF\s+INDIA\s+PRESS[^\n\r]*"),
    re.compile(r"(?i)\bPUBLISHED\s+BY\s+THE\s+CONTROLLER\s+OF\s+PUBLICATIONS\b[^\n\r]*"),
    re.compile(r"(?i)\bUPLOADED\s+BY\s+THE\s+DIRECTORATE\s+OF\s+PRINTING\b[^\n\r]*"),
    re.compile(r"(?i)\bGOVERNMENT\s+OF\s+INDIA\s+PRESS\s*,\s*RING\s+ROAD[^\n\r]*"),
]

# 5. Administrative watermarks and operational distribution labels
WATERMARK_PATTERNS = [
    re.compile(r"(?i)\bCONFIDENTIAL\s*[\-]\s*FOR\s+INTERNAL\s+USE\s+ONLY\b"),
    re.compile(r"(?i)\bFOR\s+OFFICIAL\s+USE\s+ONLY\b"),
    re.compile(r"(?i)\bDRAFT\s+FOR\s+DISCUSSION(?:\s+PURPOSES?)?\s+ONLY\b"),
    re.compile(r"(?i)\bADVANCE\s+COPY\s*[\-]\s*NOT\s+FOR\s+SALE\b"),
]


class FurnitureStripper:
    """Intelligent regex-driven gazette furniture stripper preserving string length."""

    def __init__(self, config: FurnitureConfig | None = None) -> None:
        self.config = config or FurnitureConfig()

    def strip(
        self, text: str, config: FurnitureConfig | None = None
    ) -> tuple[str, StrippedFurnitureSummary]:
        """Replace all matched furniture substrings with exact identical lengths of spaces.

        Guarantees len(cleaned_text) == len(raw_text).
        """
        cfg = config or self.config
        if not text:
            return text, StrippedFurnitureSummary()

        original_len = len(text)
        cleaned = text
        categories_matched: list[str] = []
        total_chars_stripped = 0
        total_tokens_stripped = 0

        # Helper to blank matched substring while tallying metrics
        def make_blanker(category: str) -> Callable[[re.Match[str]], str]:
            def _blanker(match: re.Match[str]) -> str:
                nonlocal total_chars_stripped, total_tokens_stripped
                matched_str = match.group(0)
                m_len = len(matched_str)
                tokens = len(matched_str.split())
                total_chars_stripped += m_len
                total_tokens_stripped += tokens
                if category not in categories_matched:
                    categories_matched.append(category)
                return " " * m_len

            return _blanker

        # 1. Gazette stamps
        if cfg.strip_gazette_stamps:
            for pattern in GAZETTE_STAMP_PATTERNS:
                cleaned = pattern.sub(make_blanker("gazette_stamps"), cleaned)

        # 2. Authority publication banners
        if cfg.strip_authority_banners:
            for pattern in AUTHORITY_BANNER_PATTERNS:
                cleaned = pattern.sub(make_blanker("authority_banners"), cleaned)

        # 3. Page numbers and footers
        if cfg.strip_page_numbers:
            for pattern in PAGE_NUMBER_PATTERNS:
                cleaned = pattern.sub(make_blanker("page_numbers"), cleaned)

        # 4. Printer signatures and colophons
        if cfg.strip_printer_signatures:
            for pattern in PRINTER_SIGNATURE_PATTERNS:
                cleaned = pattern.sub(make_blanker("printer_signatures"), cleaned)

        # 5. Administrative watermarks
        if cfg.strip_watermarks:
            for pattern in WATERMARK_PATTERNS:
                cleaned = pattern.sub(make_blanker("watermarks"), cleaned)

        # Invariant check: Length must remain 100% identical
        if len(cleaned) != original_len:
            raise RuntimeError(
                f"Furniture stripping violated length invariant: {original_len} -> {len(cleaned)}"
            )

        if total_tokens_stripped > 0:
            try:
                FURNITURE_TOKENS_STRIPPED_TOTAL.inc(total_tokens_stripped)
            except Exception as metric_err:
                logger.debug("furniture_stripper.metric_error", error=str(metric_err))

        summary = StrippedFurnitureSummary(
            total_characters_stripped=total_chars_stripped,
            total_tokens_stripped=total_tokens_stripped,
            categories_matched=categories_matched,
        )

        return cleaned, summary


_DEFAULT_STRIPPER: FurnitureStripper | None = None


def get_default_furniture_stripper() -> FurnitureStripper:
    """Return default singleton instance of FurnitureStripper."""
    global _DEFAULT_STRIPPER
    if _DEFAULT_STRIPPER is None:
        _DEFAULT_STRIPPER = FurnitureStripper()
    return _DEFAULT_STRIPPER


def strip_furniture(
    text: str,
    config: FurnitureConfig | None = None,
) -> tuple[str, StrippedFurnitureSummary]:
    """Convenience helper to strip gazette furniture while strictly preserving character offsets."""
    stripper = FurnitureStripper(config) if config else get_default_furniture_stripper()
    return stripper.strip(text, config=config)
