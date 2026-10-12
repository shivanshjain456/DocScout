"""Automated Formula Extraction from Circulars (FEAT-022).

Ingestion-time extractor that parses circular text to identify mathematical formulas,
statutory ratios, and variable definitions. Persists extracted formulas and AST schemas
in PostgreSQL document_formulas table.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from psycopg.types.json import Jsonb

from app.api.metrics import DOCUMENTS_WITH_FORMULAS_TOTAL, FORMULAS_EXTRACTED_TOTAL

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExtractedFormula:
    """A mathematical or statutory formula extracted from regulatory text."""

    doc_id: str
    formula_name: str
    raw_expression: str
    parsed_ast: dict[str, Any]
    variables: dict[str, str]
    span: tuple[int, int]
    confidence: float = 1.0
    standard: str | None = None
    statutory_threshold: str | None = None


@dataclass(frozen=True)
class FormulaExtractorConfig:
    """Configuration for formula extraction."""

    enabled: bool = True
    min_confidence: float = 0.85


# Core regex patterns for regulatory equations
# Example: "CRAR = (Tier I Capital + Tier II Capital) / Risk Weighted Assets"
_RE_EXPLICIT_EQUATION = re.compile(
    r"(?m)^\s*(?:[a-z0-9\.\-\)]+\s*)?"
    r"(?P<lhs>[A-Z][A-Za-z0-9\s\-_\(\)\/]{1,60}?)\s*"
    r"(?:=|:=|is computed as|shall be calculated as)\s*"
    r"(?P<rhs>(?:[A-Za-z0-9\s\-_\+\*\/\(\)\^\.]|\b(?:and|or)\b){4,180}?)"
    r"(?=\s*(?:[;\.\n]|$|\bwhere\b|\bwherein\b))",
)

# Known statutory financial ratios and standard systems equations
_STATUTORY_RATIO_HINTS: dict[str, dict[str, Any]] = {
    "crar": {
        "name": "Capital to Risk-Weighted Assets Ratio (CRAR)",
        "aliases": ("crar", "capital adequacy ratio", "car"),
        "standard": "RBI Master Direction - Basel III Capital Regulations",
        "default_threshold": ">= 0.15",
    },
    "lcr": {
        "name": "Liquidity Coverage Ratio (LCR)",
        "aliases": ("lcr", "liquidity coverage ratio"),
        "standard": "RBI Liquidity Risk Management Framework",
        "default_threshold": ">= 1.00",
    },
    "leverage": {
        "name": "Leverage Ratio",
        "aliases": ("leverage ratio", "basel iii leverage ratio"),
        "standard": "RBI Basel III Capital Regulations",
        "default_threshold": ">= 0.04",
    },
    "nsfr": {
        "name": "Net Stable Funding Ratio (NSFR)",
        "aliases": ("nsfr", "net stable funding ratio"),
        "standard": "RBI Master Direction - Basel III NSFR",
        "default_threshold": ">= 1.00",
    },
    "nof": {
        "name": "Net Owned Fund (NOF)",
        "aliases": ("net owned fund", "nof"),
        "standard": "RBI Act Section 45-IA",
        "default_threshold": ">= 20000000",
    },
    "pcr": {
        "name": "Provisioning Coverage Ratio (PCR)",
        "aliases": ("provisioning coverage ratio", "pcr"),
        "standard": "RBI Master Circular - Prudential Norms on Advances",
        "default_threshold": ">= 0.70",
    },
    "sci": {
        "name": "Software Carbon Intensity (SCI)",
        "aliases": ("sci", "software carbon intensity"),
        "standard": "ISO/IEC 21031:2024",
        "default_threshold": None,
    },
    "burn_rate": {
        "name": "Error Budget Burn Rate",
        "aliases": ("burn rate", "error budget burn rate"),
        "standard": "SRE Reliability Framework",
        "default_threshold": "<= 1.0",
    },
}

# Regex to detect where/wherein variable definitions
_RE_VARIABLE_CLAUSE = re.compile(
    r"(?is)\b(?:where|wherein|in which)\b\s*[:\n]?(?P<defs>[\s\S]{1,600}?)(?=\n\s*\n|\b\d+\.|\bChapter\b|\Z)"
)

_RE_SINGLE_VAR_DEF = re.compile(
    r"(?m)^\s*(?:[\-\*\•]|\([a-z0-9]+\)|\d+\.)?\s*"
    r"(?P<var>(?!where\b|wherein\b)[A-Za-z0-9][A-Za-z0-9_\-\(\)\/\s]{0,40}?)\s*"
    r"(?::=|=|:|\s+-\s+|\b(?:means|shall mean|is defined as|denotes|represents|is)\b)\s*"
    r"(?P<desc>[^\n\r;\.]{3,200})"
)

# Regex to detect statutory thresholds
_RE_THRESHOLD = re.compile(
    r"(?i)(?:not\s+(?:be\s+)?less\s+than|minimum\s+of|at\s+least|shall\s+be\s+maintained\s+at)\s*"
    r"(\d+(?:\.\d+)?)\s*(?:%|per\s+cent)"
)


def _ast_to_dict(node: ast.AST) -> dict[str, Any]:
    """Convert an AST expression into a JSON-serializable dictionary."""
    if isinstance(node, ast.Expression):
        return {"type": "Expression", "body": _ast_to_dict(node.body)}
    if isinstance(node, ast.BinOp):
        return {
            "type": "BinOp",
            "op": node.op.__class__.__name__,
            "left": _ast_to_dict(node.left),
            "right": _ast_to_dict(node.right),
        }
    if isinstance(node, ast.UnaryOp):
        return {
            "type": "UnaryOp",
            "op": node.op.__class__.__name__,
            "operand": _ast_to_dict(node.operand),
        }
    if isinstance(node, ast.Name):
        return {"type": "Name", "id": node.id}
    if isinstance(node, ast.Constant):
        return {"type": "Constant", "value": node.value}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return {
            "type": "Call",
            "func": node.func.id,
            "args": [_ast_to_dict(arg) for arg in node.args],
        }
    return {"type": node.__class__.__name__}


def _clean_math_symbols(expr: str) -> str:
    """Normalize common typography characters into valid Python syntax."""
    return (
        expr.replace("×", "*")
        .replace("÷", "/")
        .replace("–", "-")
        .replace("\u2014", "-")
        .replace("^", "**")
        .strip()
    )


class CircularFormulaExtractor:
    """Parses regulatory texts and extracts formulas with variable dictionaries and AST trees."""

    def __init__(self, config: FormulaExtractorConfig | None = None) -> None:
        self.config = config or FormulaExtractorConfig()

    def extract_formulas(self, text: str, doc_id: str) -> list[ExtractedFormula]:
        """Extract all candidate statutory formulas and quantitative expressions from text."""
        if not self.config.enabled or not text or len(text.strip()) < 50:
            return []

        extracted: list[ExtractedFormula] = []
        seen_names: set[str] = set()

        # Step 1: Scan for equation patterns
        for match in _RE_EXPLICIT_EQUATION.finditer(text):
            raw_lhs = match.group("lhs").strip()
            raw_rhs = match.group("rhs").strip()
            span = (match.start(), match.end())

            # Filter trivial noise (e.g. "Page = 1", single character assignments)
            if (
                len(raw_lhs) < 2
                or len(raw_rhs) < 3
                or raw_lhs.lower() in ("page", "date", "no", "ref")
            ):
                continue

            # Identify statutory ratio hint if applicable
            lhs_clean = raw_lhs.strip()
            lhs_lower = lhs_clean.lower()
            ratio_hint: dict[str, Any] | None = None
            canonical_name = lhs_clean

            for _hint_key, hint_meta in _STATUTORY_RATIO_HINTS.items():
                if any(alias in lhs_lower for alias in hint_meta["aliases"]):
                    ratio_hint = hint_meta
                    canonical_name = hint_meta["name"]
                    break

            # Filter duplicates within same document
            if canonical_name in seen_names:
                continue

            # Step 2: Parse RHS into AST
            clean_rhs = _clean_math_symbols(raw_rhs)
            parsed_ast: dict[str, Any] = {}
            try:
                # Replace multi-word tokens in parentheses with underscores for AST parsing
                ast_expr = re.sub(
                    r"\b([A-Za-z]+)\s+([A-Za-z]+)\b",
                    r"\1_\2",
                    clean_rhs,
                )
                tree = ast.parse(ast_expr, mode="eval")
                parsed_ast = _ast_to_dict(tree)
            except Exception:
                # Heuristic fallback structure if expression contains prose
                parsed_ast = {
                    "type": "HeuristicExpression",
                    "raw_rhs": clean_rhs,
                }

            # Step 3: Extract variable definitions from surrounding window (-400 to +600 chars)
            window_start = max(0, span[0] - 400)
            window_end = min(len(text), span[1] + 600)
            surrounding_text = text[window_start:window_end]

            variables = self._extract_variables(surrounding_text, raw_rhs)

            # Step 4: Extract threshold if mentioned in proximity
            threshold = ratio_hint.get("default_threshold") if ratio_hint else None
            thresh_match = _RE_THRESHOLD.search(surrounding_text)
            if thresh_match:
                pct = float(thresh_match.group(1)) / 100.0
                threshold = f">= {pct:.2f}"

            standard = ratio_hint.get("standard") if ratio_hint else None
            confidence = 1.0 if ratio_hint else 0.90

            if confidence < self.config.min_confidence:
                continue

            formula = ExtractedFormula(
                doc_id=doc_id,
                formula_name=canonical_name,
                raw_expression=f"{raw_lhs} = {raw_rhs}",
                parsed_ast=parsed_ast,
                variables=variables,
                span=span,
                confidence=confidence,
                standard=standard,
                statutory_threshold=threshold,
            )
            extracted.append(formula)
            seen_names.add(canonical_name)

        # Telemetry updates
        if extracted:
            FORMULAS_EXTRACTED_TOTAL.inc(len(extracted))
            DOCUMENTS_WITH_FORMULAS_TOTAL.inc()

        logger.info(
            "formulas_extracted",
            doc_id=doc_id,
            count=len(extracted),
            formulas=[f.formula_name for f in extracted],
        )

        return extracted

    def _extract_variables(self, context_text: str, rhs: str) -> dict[str, str]:
        """Extract variable definitions from where clauses or variable lists in context."""
        variables: dict[str, str] = {}

        # Look for explicit 'where ...' section
        clause_match = _RE_VARIABLE_CLAUSE.search(context_text)
        search_region = clause_match.group("defs") if clause_match else context_text

        for var_match in _RE_SINGLE_VAR_DEF.finditer(search_region):
            var_name = var_match.group("var").strip()
            var_desc = var_match.group("desc").strip()
            if len(var_name) <= 25 and len(var_desc) >= 3:
                variables[var_name] = var_desc

        # If none found via where clause, extract operands from RHS as variables
        if not variables:
            operands = re.findall(r"\b[A-Za-z][A-Za-z0-9_]{1,30}\b", rhs)
            for op in operands:
                if op.lower() not in ("and", "or", "of", "the", "in", "per"):
                    variables[op] = f"Parameter {op}"

        return variables


# Database Persistence Functions


def store_extracted_formulas(
    conn: psycopg.Connection[Any],
    formulas: list[ExtractedFormula],
    document_uuid: str | None = None,
) -> int:
    """Store extracted formulas into document_formulas table."""
    if not formulas:
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for f in formulas:
            cur.execute(
                """
                INSERT INTO document_formulas (
                    document_id,
                    doc_id,
                    formula_name,
                    raw_expression,
                    parsed_ast,
                    variables,
                    char_start,
                    char_end,
                    confidence,
                    standard,
                    statutory_threshold
                ) VALUES (
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s
                )
                """,
                (
                    document_uuid,
                    f.doc_id,
                    f.formula_name,
                    f.raw_expression,
                    Jsonb(f.parsed_ast),
                    Jsonb(f.variables),
                    f.span[0],
                    f.span[1],
                    f.confidence,
                    f.standard,
                    f.statutory_threshold,
                ),
            )
            inserted += 1
    return inserted


def fetch_document_formulas(
    conn: psycopg.Connection[Any],
    doc_id: str,
) -> list[ExtractedFormula]:
    """Retrieve all extracted formulas associated with a document ID."""
    results: list[ExtractedFormula] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                doc_id,
                formula_name,
                raw_expression,
                parsed_ast,
                variables,
                char_start,
                char_end,
                confidence,
                standard,
                statutory_threshold
            FROM document_formulas
            WHERE doc_id = %s
            ORDER BY char_start ASC
            """,
            (doc_id,),
        )
        for row in cur.fetchall():
            results.append(
                ExtractedFormula(
                    doc_id=row[0],
                    formula_name=row[1],
                    raw_expression=row[2],
                    parsed_ast=row[3],
                    variables=row[4],
                    span=(row[5], row[6]),
                    confidence=float(row[7]),
                    standard=row[8],
                    statutory_threshold=row[9],
                )
            )
    return results
