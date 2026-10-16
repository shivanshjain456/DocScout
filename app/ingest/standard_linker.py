"""Standard-Linked Formula Annotator (FEAT-025).

Cross-links formula definitions in regulatory text and circulars directly to parent
international and national standards (e.g. ISO/IEC 21031 for SCI, Basel III / RBI
Master Directions for CRAR).

Enriches formulas with standard metadata, statutory governing bodies, and citations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
import structlog

from app.api.metrics import STANDARD_FORMULA_LINKS_TOTAL, STANDARD_LINKING_DURATION_SECONDS
from app.api.models import FormulaDefinition
from app.compliance.formula_engine import (
    FormulaEngine,
    RegisteredFormula,
    get_default_formula_engine,
)
from app.compliance.standards_registry import (
    StandardDefinition,
    StandardsRegistry,
    get_default_standards_registry,
)
from app.ingest.formula_extractor import ExtractedFormula

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StandardLinkerConfig:
    """Configuration for standard formula linking."""

    strict_matching: bool = True
    enable_db_sync: bool = False


@dataclass(frozen=True)
class AnnotatedFormula:
    """Formula cross-linked with its governing regulatory or technical standard."""

    formula_id: str
    formula_name: str
    expression: str
    standard_id: str | None = None
    standard_name: str | None = None
    governing_body: str | None = None
    domain: str | None = None
    standard_citation: str | None = None
    confidence: float = 1.0
    status: Literal["LINKED", "UNLINKED", "AMBIGUOUS"] = "LINKED"
    linked_clauses: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical Standard Mappings for Taxonomy & Banking Formulas
# ---------------------------------------------------------------------------

_FORMULA_CANONICAL_STANDARDS: dict[str, str] = {
    # 24 Taxonomy Formulas
    "sci": "ISO/IEC 21031:2024",
    "error-budget": "SRE_RELIABILITY_FRAMEWORK",
    "burn-rate": "SRE_RELIABILITY_FRAMEWORK",
    "mcdc": "DO-178C",
    "mutation-score": "ISO/IEC/IEEE 29119",
    "dre": "ISO/IEC 25010",
    "littles-law": "ISO/IEC 25010",
    "usl": "ISO/IEC 25010",
    "amdahl": "ISO/IEC 25010",
    "apdex": "ISO/IEC 25010",
    "disparate-impact": "NIST SP 1270",
    "ece": "ISO/IEC 42001",
    "faithfulness": "ISO/IEC 42001",
    "hallucination-rate": "ISO/IEC 42001",
    "asr": "OWASP Top 10 for LLM Applications 2025",
    "srm": "ISO/IEC 5259",
    "cuped": "ISO/IEC 5259",
    "power": "ISO/IEC 5259",
    "coordinated-omission": "ISO/IEC 25010",
    "t-way": "ISO/IEC/IEEE 29119",
    "coverage-gap": "DO-178C",
    "cve-triage": "CVSS",
    "capacity-headroom": "SRE_RELIABILITY_FRAMEWORK",
    "toil-ratio": "SRE_RELIABILITY_FRAMEWORK",
    # Banking Statutory Ratios
    "crar": "RBI_BASEL_III_CAPITAL",
    "lcr": "RBI_LIQUIDITY_RISK",
    "leverage-ratio": "RBI_BASEL_III_CAPITAL",
    "nsfr": "RBI_LIQUIDITY_RISK",
    "tier1": "RBI_BASEL_III_CAPITAL",
    "net_npa": "RBI_PCA_FRAMEWORK",
    "psl": "RBI_PSL_FRAMEWORK",
}


class StandardFormulaAnnotator:
    """High-performance cross-linker connecting mathematical formulas to governing standards."""

    def __init__(
        self,
        registry: StandardsRegistry | None = None,
        engine: FormulaEngine | None = None,
        config: StandardLinkerConfig | None = None,
    ) -> None:
        self._registry = registry or get_default_standards_registry()
        self._engine = engine or get_default_formula_engine()
        self._config = config or StandardLinkerConfig()

    def annotate_formula(
        self,
        formula: FormulaDefinition | RegisteredFormula | ExtractedFormula | dict[str, Any] | str,
        standard_hint: str | None = None,
    ) -> AnnotatedFormula:
        """Link a formula to its governing standard in <= 0.5ms."""
        start_ts = time.perf_counter()

        # 1. Unpack input parameters
        formula_id = ""
        formula_name = ""
        expression = ""
        explicit_std: str | list[str] | None = standard_hint

        if isinstance(formula, str):
            formula_id = formula
            reg = self._engine.get_registered_formula(formula)
            if reg:
                formula_name = reg.name
                expression = reg.expression
                explicit_std = explicit_std or reg.standard
            else:
                formula_name = formula.upper()
                expression = formula
        elif isinstance(formula, ExtractedFormula):
            formula_id = formula.doc_id or formula.formula_name.lower().replace(" ", "-")
            formula_name = formula.formula_name
            expression = formula.raw_expression
            explicit_std = explicit_std or formula.standard
        elif isinstance(formula, dict):
            formula_id = formula.get("id") or formula.get("formula_id") or ""
            formula_name = formula.get("name") or formula.get("formula_name") or formula_id
            expression = formula.get("expression") or formula.get("raw_expression") or ""
            explicit_std = explicit_std or formula.get("standard")
        elif hasattr(formula, "id") and hasattr(formula, "name"):
            formula_id = str(getattr(formula, "id", ""))
            formula_name = str(getattr(formula, "name", formula_id))
            expression = str(getattr(formula, "expression", ""))
            explicit_std = explicit_std or getattr(formula, "standard", None)

        # 2. Resolve target standard definition
        resolved_std: StandardDefinition | None = None

        # Check explicit standard reference if provided
        if explicit_std:
            if isinstance(explicit_std, list) and explicit_std:
                for candidate in explicit_std:
                    resolved_std = self._registry.resolve_standard(str(candidate))
                    if resolved_std:
                        break
            elif isinstance(explicit_std, str):
                resolved_std = self._registry.resolve_standard(explicit_std)

        # Fallback to canonical taxonomy mapping
        if resolved_std is None and formula_id:
            norm_fid = formula_id.lower().replace("_", "-")
            if norm_fid in _FORMULA_CANONICAL_STANDARDS:
                target_id = _FORMULA_CANONICAL_STANDARDS[norm_fid]
                resolved_std = self._registry.get_standard(target_id)

        # Fallback to name/expression fuzzy match if not strict
        if resolved_std is None and not self._config.strict_matching:
            search_text = f"{formula_name} {expression}"
            resolved_std = self._registry.resolve_standard(search_text)

        elapsed = time.perf_counter() - start_ts
        STANDARD_LINKING_DURATION_SECONDS.observe(elapsed)

        # 3. Construct AnnotatedFormula output
        if resolved_std is not None:
            STANDARD_FORMULA_LINKS_TOTAL.labels(standard_id=resolved_std.id, status="LINKED").inc()
            return AnnotatedFormula(
                formula_id=formula_id,
                formula_name=formula_name,
                expression=expression,
                standard_id=resolved_std.id,
                standard_name=resolved_std.name,
                governing_body=resolved_std.governing_body,
                domain=resolved_std.domain,
                standard_citation=f"{resolved_std.governing_body} {resolved_std.name} ({resolved_std.id})",
                confidence=1.0,
                status="LINKED",
                linked_clauses=[resolved_std.note] if resolved_std.note else [],
            )

        # Unmatched standard fallback behavior
        logger.debug(
            "standard_linker.unmatched_standard",
            formula_id=formula_id,
            formula_name=formula_name,
            explicit_hint=explicit_std,
        )
        STANDARD_FORMULA_LINKS_TOTAL.labels(standard_id="none", status="UNLINKED").inc()

        return AnnotatedFormula(
            formula_id=formula_id,
            formula_name=formula_name,
            expression=expression,
            standard_id=None,
            standard_name=None,
            governing_body=None,
            domain=None,
            standard_citation=None,
            confidence=0.0,
            status="UNLINKED",
            linked_clauses=[],
        )

    def annotate_all_registered_formulas(self) -> list[AnnotatedFormula]:
        """Annotate all registered formulas in the formula engine."""
        results: list[AnnotatedFormula] = []
        for f in self._engine.list_formulas():
            annotated = self.annotate_formula(f)
            results.append(annotated)
        return results

    def sync_to_database(
        self,
        db_connection: psycopg.Connection[Any] | None = None,
    ) -> int:
        """Seed standards_registry table and update document_formulas standard_id."""
        if db_connection is None:
            return 0

        synced_count = 0
        try:
            with db_connection.cursor() as cur:
                # 1. Insert/Update standards in standards_registry
                for std in self._registry.list_standards():
                    cur.execute(
                        """
                        INSERT INTO standards_registry (
                            id, name, governing_body, domain, jurisdiction, category,
                            description, official_reference_url, note
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            governing_body = EXCLUDED.governing_body,
                            domain = EXCLUDED.domain,
                            note = EXCLUDED.note;
                        """,
                        (
                            std.id,
                            std.name,
                            std.governing_body,
                            std.domain,
                            std.jurisdiction,
                            std.category,
                            std.description,
                            std.official_reference_url,
                            std.note,
                        ),
                    )
                    synced_count += 1

                # 2. Update existing document_formulas rows
                cur.execute("SELECT id, formula_name, standard FROM document_formulas;")
                rows = cur.fetchall()
                for row_id, fname, fstd in rows:
                    annotated = self.annotate_formula(
                        {"name": fname, "standard": fstd}, standard_hint=fstd
                    )
                    if annotated.standard_id:
                        cur.execute(
                            "UPDATE document_formulas SET standard_id = %s WHERE id = %s;",
                            (annotated.standard_id, row_id),
                        )

            db_connection.commit()
            logger.info("standards_registry.synced", count=synced_count)
        except Exception as exc:
            logger.warning("standards_registry.sync_error", error=str(exc))
            db_connection.rollback()

        return synced_count


_DEFAULT_ANNOTATOR: StandardFormulaAnnotator | None = None


def get_default_standard_annotator() -> StandardFormulaAnnotator:
    """Singleton getter for default formula annotator."""
    global _DEFAULT_ANNOTATOR
    if _DEFAULT_ANNOTATOR is None:
        _DEFAULT_ANNOTATOR = StandardFormulaAnnotator()
    return _DEFAULT_ANNOTATOR
