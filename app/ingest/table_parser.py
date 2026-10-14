"""High-Fidelity Table Lineage and Matrix Parser (FEAT-062).

Extracts complex financial disclosure tables, capital adequacy matrices, and fee schedules
from regulatory PDFs and structured text into structured Markdown and JSON, preserving
multi-row headers and lineage.
"""

from __future__ import annotations

import io
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from app.api.metrics import TABLE_EXTRACTION_DURATION_SECONDS, TABLES_EXTRACTED_TOTAL

logger = structlog.get_logger(__name__)

# Pattern to detect Markdown or ASCII table separator rows: |---|---| or +---+---+
PAT_MD_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
PAT_ASCII_SEPARATOR = re.compile(r"^\s*\+?[-=+]+\+?\s*$")
PAT_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
PAT_SPACED_COLS = re.compile(r"\s{2,}|\t+")


@dataclass
class TableParserConfig:
    strategy: Literal["pdfplumber", "docling", "miner_u"] = "pdfplumber"
    min_rows: int = 2
    min_cols: int = 2
    merge_multi_headers: bool = True
    snap_tolerance: float = 3.0
    join_tolerance: float = 3.0


@dataclass
class ExtractedTable:
    table_id: str
    page_number: int
    headers: list[str]
    matrix: list[list[str]]
    markdown_repr: str
    json_repr: dict[str, Any]
    cell_coordinates: list[dict[str, Any]] = field(default_factory=list)


def clean_cell_text(raw_text: Any) -> str:
    """Normalize cell text: collapse whitespace/newlines, preserve numbers and signs."""
    if raw_text is None:
        return ""
    # Replace internal newlines with space
    text = str(raw_text).replace("\r", " ").replace("\n", " ")
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def resolve_multi_row_headers(
    header_rows: list[list[str]],
    merge_multi_headers: bool = True,
) -> list[str]:
    """Merge hierarchical multi-row headers into disambiguated column labels."""
    if not header_rows:
        return []
    if len(header_rows) == 1 or not merge_multi_headers:
        return [clean_cell_text(h) or f"Column_{idx + 1}" for idx, h in enumerate(header_rows[0])]

    num_cols = max(len(r) for r in header_rows)
    normalized_rows: list[list[str]] = []
    for r in header_rows:
        padded = [clean_cell_text(r[idx]) if idx < len(r) else "" for idx in range(num_cols)]
        normalized_rows.append(padded)

    resolved: list[str] = []
    for col_idx in range(num_cols):
        components: list[str] = []
        for row_idx, r in enumerate(normalized_rows):
            cell = r[col_idx]
            if not cell and row_idx < len(normalized_rows) - 1:
                # Check left for spanned header in this row
                for left_idx in range(col_idx - 1, -1, -1):
                    if r[left_idx]:
                        cell = r[left_idx]
                        break
            if cell and (not components or components[-1] != cell):
                components.append(cell)

        if not components:
            resolved.append(f"Column_{col_idx + 1}")
        elif len(components) == 1:
            resolved.append(components[0])
        else:
            resolved.append(" -> ".join(components))

    return resolved


def serialize_to_markdown(headers: list[str], matrix: list[list[str]]) -> str:
    """Render headers and matrix into GitHub-flavored Markdown table format."""
    num_cols = max(len(headers), max((len(r) for r in matrix), default=0))
    if num_cols == 0:
        return ""

    norm_headers = [
        headers[idx] if idx < len(headers) and headers[idx] else f"Col_{idx + 1}"
        for idx in range(num_cols)
    ]

    escaped_headers = [h.replace("|", "\\|") for h in norm_headers]
    header_line = "| " + " | ".join(escaped_headers) + " |"
    sep_line = "| " + " | ".join(["---"] * num_cols) + " |"

    row_lines: list[str] = []
    for r in matrix:
        escaped_cells = []
        for idx in range(num_cols):
            val = r[idx] if idx < len(r) else ""
            escaped_cells.append(val.replace("|", "\\|"))
        row_lines.append("| " + " | ".join(escaped_cells) + " |")

    return "\n".join([header_line, sep_line] + row_lines)


def serialize_to_json(
    table_id: str,
    page_number: int,
    headers: list[str],
    matrix: list[list[str]],
    cell_coordinates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render table into canonical structured JSON representation."""
    structured_rows: list[dict[str, str]] = []
    for r in matrix:
        row_dict: dict[str, str] = {}
        for idx, h in enumerate(headers):
            val = r[idx] if idx < len(r) else ""
            row_dict[h] = val
        structured_rows.append(row_dict)

    total_cells = sum(len(r) for r in matrix) + len(headers)

    return {
        "table_id": table_id,
        "page_number": page_number,
        "headers": headers,
        "row_count": len(matrix),
        "col_count": len(headers),
        "total_cells": total_cells,
        "rows": structured_rows,
        "raw_matrix": matrix,
        "cell_coordinates": cell_coordinates or [],
    }


class TableParser:
    """High-fidelity Table Lineage and Matrix Parser (FEAT-062)."""

    def __init__(self, config: TableParserConfig | None = None) -> None:
        self.config = config or TableParserConfig()

    def parse_pdf(self, pdf_bytes: bytes) -> list[ExtractedTable]:
        """Extract structured tables from PDF bytes with fallback to text extraction."""
        t0 = time.perf_counter()
        tables: list[ExtractedTable] = []

        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    page_num = page_idx + 1

                    # Extract raw tables via pdfplumber
                    extracted = page.extract_tables()
                    if not extracted:
                        continue

                    # Also attempt to get table bounding boxes if available
                    table_bboxes = []
                    try:
                        table_objects = page.find_tables()
                        for tb in table_objects:
                            table_bboxes.append(tb.bbox)
                    except Exception as bbox_err:
                        logger.debug("table_parser.bbox_error", error=str(bbox_err))

                    for t_idx, raw_table in enumerate(extracted):
                        if not raw_table or len(raw_table) < self.config.min_rows:
                            continue

                        # Clean and filter cells
                        cleaned_rows: list[list[str]] = []
                        for raw_row in raw_table:
                            cleaned_row = [clean_cell_text(cell) for cell in raw_row]
                            # Skip if completely empty row
                            if any(bool(c) for c in cleaned_row):
                                cleaned_rows.append(cleaned_row)

                        if len(cleaned_rows) < self.config.min_rows:
                            continue

                        max_cols = max(len(r) for r in cleaned_rows)
                        if max_cols < self.config.min_cols:
                            continue

                        # Determine if first 1 or 2 rows are headers
                        is_multi_header = False
                        if len(cleaned_rows) >= 3:
                            # Heuristic: if row 0 has empty strings indicating spanning headers
                            # and row 1 has non-empty subheaders
                            r0 = cleaned_rows[0]
                            r1 = cleaned_rows[1]
                            if any(not c for c in r0) and all(bool(c) for c in r1 if c):
                                is_multi_header = True

                        if is_multi_header and self.config.merge_multi_headers:
                            header_rows = [cleaned_rows[0], cleaned_rows[1]]
                            data_matrix = cleaned_rows[2:]
                        else:
                            header_rows = [cleaned_rows[0]]
                            data_matrix = cleaned_rows[1:]

                        headers = resolve_multi_row_headers(
                            header_rows,
                            merge_multi_headers=self.config.merge_multi_headers,
                        )

                        # Pad data matrix to match headers length
                        normalized_matrix: list[list[str]] = []
                        for d_row in data_matrix:
                            padded_row: list[str] = [
                                d_row[i] if i < len(d_row) else "" for i in range(len(headers))
                            ]
                            normalized_matrix.append(padded_row)

                        table_id = f"tbl_{uuid.uuid4().hex[:12]}"
                        cell_coords: list[dict[str, Any]] = []
                        if t_idx < len(table_bboxes):
                            bbox = table_bboxes[t_idx]
                            cell_coords.append(
                                {
                                    "table_bbox": list(bbox),
                                    "page": page_num,
                                }
                            )

                        md_repr = serialize_to_markdown(headers, normalized_matrix)
                        json_repr = serialize_to_json(
                            table_id,
                            page_num,
                            headers,
                            normalized_matrix,
                            cell_coords,
                        )

                        tables.append(
                            ExtractedTable(
                                table_id=table_id,
                                page_number=page_num,
                                headers=headers,
                                matrix=normalized_matrix,
                                markdown_repr=md_repr,
                                json_repr=json_repr,
                                cell_coordinates=cell_coords,
                            )
                        )

            duration = time.perf_counter() - t0
            try:
                TABLES_EXTRACTED_TOTAL.labels(
                    strategy=self.config.strategy,
                    status="success",
                ).inc(len(tables))
                TABLE_EXTRACTION_DURATION_SECONDS.labels(
                    strategy=self.config.strategy,
                ).observe(duration)
            except Exception as metric_err:
                logger.debug("table_parser.metric_error", error=str(metric_err))

            return tables

        except Exception as err:
            logger.warning("table_parser.pdf_error", error=str(err))
            try:
                TABLES_EXTRACTED_TOTAL.labels(
                    strategy=self.config.strategy,
                    status="error",
                ).inc()
            except Exception as metric_err:
                logger.debug("table_parser.metric_error", error=str(metric_err))
            # Graceful fallback: return empty list without crashing
            return []

    def parse_text(self, text: str, page_number: int = 1) -> list[ExtractedTable]:
        """Extract structured tables from raw text or markdown or space-aligned blocks."""
        t0 = time.perf_counter()
        tables: list[ExtractedTable] = []

        lines = [line.rstrip() for line in text.splitlines()]
        idx = 0

        while idx < len(lines):
            line = lines[idx]

            # 1. Check for Pipe-delimited or Markdown table
            if "|" in line:
                table_lines: list[str] = []
                while idx < len(lines) and (
                    "|" in lines[idx] or PAT_ASCII_SEPARATOR.match(lines[idx])
                ):
                    if lines[idx].strip():
                        table_lines.append(lines[idx])
                    idx += 1

                if len(table_lines) >= self.config.min_rows:
                    extracted = self._parse_pipe_table(table_lines, page_number)
                    if extracted is not None:
                        tables.append(extracted)
                continue

            # 2. Check for Space / Tab delimited table block
            cols = [c.strip() for c in PAT_SPACED_COLS.split(line.strip()) if c.strip()]
            if len(cols) >= self.config.min_cols:
                table_lines = [line]
                peek_idx = idx + 1
                while peek_idx < len(lines):
                    peek_line = lines[peek_idx].strip()
                    if not peek_line:
                        break
                    if PAT_ASCII_SEPARATOR.match(peek_line):
                        table_lines.append(lines[peek_idx])
                        peek_idx += 1
                        continue
                    peek_cols = [c.strip() for c in PAT_SPACED_COLS.split(peek_line) if c.strip()]
                    if len(peek_cols) >= 2 or PAT_ASCII_SEPARATOR.match(peek_line):
                        table_lines.append(lines[peek_idx])
                        peek_idx += 1
                    else:
                        break

                if len(table_lines) >= self.config.min_rows:
                    extracted = self._parse_space_delimited_table(table_lines, page_number)
                    if extracted is not None:
                        tables.append(extracted)
                        idx = peek_idx
                        continue

            idx += 1

        duration = time.perf_counter() - t0
        try:
            TABLES_EXTRACTED_TOTAL.labels(
                strategy="text_matrix",
                status="success",
            ).inc(len(tables))
            TABLE_EXTRACTION_DURATION_SECONDS.labels(
                strategy="text_matrix",
            ).observe(duration)
        except Exception as metric_err:
            logger.debug("table_parser.metric_error", error=str(metric_err))

        return tables

    def _parse_pipe_table(self, lines: list[str], page_number: int) -> ExtractedTable | None:
        """Parse pipe-delimited Markdown/ASCII table lines."""
        raw_rows: list[list[str]] = []
        separator_idx = -1

        for line in lines:
            if PAT_MD_SEPARATOR.match(line) or PAT_ASCII_SEPARATOR.match(line):
                if separator_idx == -1 and raw_rows:
                    separator_idx = len(raw_rows)
                continue

            stripped = line.strip()
            if stripped.startswith("|"):
                stripped = stripped[1:]
            if stripped.endswith("|"):
                stripped = stripped[:-1]

            cells = [clean_cell_text(c) for c in stripped.split("|")]
            if any(bool(c) for c in cells):
                raw_rows.append(cells)

        if len(raw_rows) < self.config.min_rows:
            return None

        # Determine header rows
        if separator_idx > 0 and separator_idx <= len(raw_rows):
            header_rows = raw_rows[:separator_idx]
            data_matrix = raw_rows[separator_idx:]
        else:
            header_rows = [raw_rows[0]]
            data_matrix = raw_rows[1:]

        headers = resolve_multi_row_headers(
            header_rows,
            merge_multi_headers=self.config.merge_multi_headers,
        )

        max_cols = len(headers)
        normalized_matrix: list[list[str]] = []
        for row in data_matrix:
            padded_row = [row[i] if i < len(row) else "" for i in range(max_cols)]
            normalized_matrix.append(padded_row)

        table_id = f"tbl_{uuid.uuid4().hex[:12]}"
        md_repr = serialize_to_markdown(headers, normalized_matrix)
        json_repr = serialize_to_json(table_id, page_number, headers, normalized_matrix)

        return ExtractedTable(
            table_id=table_id,
            page_number=page_number,
            headers=headers,
            matrix=normalized_matrix,
            markdown_repr=md_repr,
            json_repr=json_repr,
            cell_coordinates=[],
        )

    def _parse_space_delimited_table(
        self, lines: list[str], page_number: int
    ) -> ExtractedTable | None:
        """Parse space/tab aligned text table lines."""
        raw_rows: list[list[str]] = []
        for line in lines:
            if PAT_ASCII_SEPARATOR.match(line):
                continue
            cols = [clean_cell_text(c) for c in PAT_SPACED_COLS.split(line.strip()) if c.strip()]
            if cols:
                raw_rows.append(cols)

        if len(raw_rows) < self.config.min_rows:
            return None

        header_rows = [raw_rows[0]]
        data_matrix = raw_rows[1:]

        headers = resolve_multi_row_headers(
            header_rows, merge_multi_headers=self.config.merge_multi_headers
        )
        max_cols = max(len(headers), max((len(r) for r in data_matrix), default=0))

        if len(headers) < max_cols:
            for idx in range(len(headers), max_cols):
                headers.append(f"Column_{idx + 1}")

        normalized_matrix: list[list[str]] = []
        for row in data_matrix:
            padded_row = [row[i] if i < len(row) else "" for i in range(max_cols)]
            normalized_matrix.append(padded_row)

        table_id = f"tbl_{uuid.uuid4().hex[:12]}"
        md_repr = serialize_to_markdown(headers, normalized_matrix)
        json_repr = serialize_to_json(table_id, page_number, headers, normalized_matrix)

        return ExtractedTable(
            table_id=table_id,
            page_number=page_number,
            headers=headers,
            matrix=normalized_matrix,
            markdown_repr=md_repr,
            json_repr=json_repr,
            cell_coordinates=[],
        )


_DEFAULT_PARSER: TableParser | None = None


def get_default_table_parser() -> TableParser:
    """Return default singleton instance of TableParser."""
    global _DEFAULT_PARSER
    if _DEFAULT_PARSER is None:
        _DEFAULT_PARSER = TableParser()
    return _DEFAULT_PARSER


def extract_tables_from_pdf(
    pdf_bytes: bytes,
    config: TableParserConfig | None = None,
) -> list[ExtractedTable]:
    """Convenience function to extract tables from PDF bytes."""
    parser = TableParser(config) if config else get_default_table_parser()
    return parser.parse_pdf(pdf_bytes)
