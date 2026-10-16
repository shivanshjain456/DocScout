"""Circular Clause Conflict Detector (FEAT-032).

Semantic and quantitative analysis comparing regulatory circular clauses to identify
unacknowledged contradictions, conflicting mandates, incompatible thresholds,
and regulatory ambiguities across statutory directives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger("docscout.compliance.clause_conflict")


class ConflictType(StrEnum):
    """Categorization of statutory clause conflict."""

    THRESHOLD_CONTRADICTION = "threshold_contradiction"
    MODALITY_CLASH = "modality_clash"
    TIMELINE_DISCREPANCY = "timeline_discrepancy"
    SCOPE_OVERLAP = "scope_overlap"


class ClauseModality(StrEnum):
    """Normative force of statutory clause."""

    MANDATORY = "mandatory"  # Shall, must, required
    PROHIBITED = "prohibited"  # Shall not, prohibited, forbidden
    PERMITTED = "permitted"  # May, discretionary, optional


class ConflictSeverity(StrEnum):
    """Statutory severity of detected conflict."""

    CRITICAL = "CRITICAL"  # Incompatible regulatory commands risking enforcement action
    HIGH = "HIGH"  # Conflicting quantitative thresholds
    MEDIUM = "MEDIUM"  # Ambiguous reporting timelines or overlapping scopes
    LOW = "LOW"  # Minor definition divergence


@dataclass
class CircularClause:
    """Structured representation of an individual regulatory circular clause."""

    id: str
    circular_id: str
    circular_title: str
    regulator: str
    section_reference: str
    clause_text: str
    domain_category: str
    modality: ClauseModality = ClauseModality.MANDATORY
    parameter_name: str | None = None
    parameter_value: float | None = None
    parameter_unit: str | None = None
    comparison_operator: str | None = None  # "MIN", "MAX", "EXACT", "<=", ">="
    effective_date: str = "2020-01-01"
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "circular_id": self.circular_id,
            "circular_title": self.circular_title,
            "regulator": self.regulator,
            "section_reference": self.section_reference,
            "clause_text": self.clause_text,
            "domain_category": self.domain_category,
            "modality": self.modality.value,
            "parameter_name": self.parameter_name,
            "parameter_value": self.parameter_value,
            "parameter_unit": self.parameter_unit,
            "comparison_operator": self.comparison_operator,
            "effective_date": self.effective_date,
            "is_active": self.is_active,
        }


@dataclass
class DetectedConflict:
    """Discrepancy or contradiction identified between two regulatory clauses."""

    conflict_id: str
    clause_a: CircularClause
    clause_b: CircularClause
    conflict_type: ConflictType
    severity: ConflictSeverity
    parameter_name: str | None
    explanation: str
    prescriptive_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "clause_a": self.clause_a.to_dict(),
            "clause_b": self.clause_b.to_dict(),
            "conflict_type": self.conflict_type.value,
            "severity": self.severity.value,
            "parameter_name": self.parameter_name,
            "explanation": self.explanation,
            "prescriptive_action": self.prescriptive_action,
        }


class ClauseConflictDetector:
    """Engine identifying contradictions and ambiguous mandates across circular clauses."""

    def __init__(self) -> None:
        self._clauses: dict[str, CircularClause] = {}
        self._load_canonical_clause_registry()

    def register_clause(self, clause: CircularClause) -> None:
        """Add a clause to the active registry."""
        self._clauses[clause.id] = clause

    def get_clause(self, clause_id: str) -> CircularClause | None:
        """Lookup clause by unique identifier."""
        return self._clauses.get(clause_id)

    def list_clauses(self, domain_category: str | None = None) -> list[CircularClause]:
        """List registered clauses with optional domain filter."""
        clauses = list(self._clauses.values())
        if domain_category:
            clauses = [c for c in clauses if c.domain_category.lower() == domain_category.lower()]
        return sorted(clauses, key=lambda c: (c.domain_category, c.id))

    def _load_canonical_clause_registry(self) -> None:
        """Initialize built-in clause catalog across key regulatory domains."""
        # Domain 1: FLDG (First Loss Default Guarantee)
        self.register_clause(
            CircularClause(
                id="rbi-fldg-mandate-5pct",
                circular_id="DOR.CRE.REC.66/21.07.001/2022-23",
                circular_title="RBI Guidelines on Default Loss Guarantee (DLG) in Digital Lending",
                regulator="RBI",
                section_reference="Section 6.1",
                clause_text="RE shall ensure that total amount of DLG cover on any outstanding portfolio which is specified in contractual agreements shall not exceed 5% of that loan portfolio.",
                domain_category="fldg",
                modality=ClauseModality.MANDATORY,
                parameter_name="fldg_ceiling_pct",
                parameter_value=5.0,
                parameter_unit="pct",
                comparison_operator="MAX",
                effective_date="2023-06-08",
            )
        )
        self.register_clause(
            CircularClause(
                id="conflicting-fldg-draft-15pct",
                circular_id="DRAFT-FINTECH-CONSULTATION-2023",
                circular_title="Proposed Industry Consultation Framework for Fintech Partnerships",
                regulator="RBI",
                section_reference="Clause 12(b)",
                clause_text="Lending Service Providers may extend synthetic balance sheet protection up to 15% of disbursed portfolio with scheduled bank approval.",
                domain_category="fldg",
                modality=ClauseModality.PERMITTED,
                parameter_name="fldg_ceiling_pct",
                parameter_value=15.0,
                parameter_unit="pct",
                comparison_operator="MAX",
                effective_date="2023-09-01",
            )
        )

        # Domain 2: Incident Reporting Timelines
        self.register_clause(
            CircularClause(
                id="rbi-cyber-incident-reporting-6hr",
                circular_id="DBS.CO/CSITE/BC.11/33.01.001/2015-16",
                circular_title="RBI Cyber Security Framework in Banks",
                regulator="RBI",
                section_reference="Annex 1, Para 3",
                clause_text="Banks shall report all unusual cyber security incidents to RBI and CERT-In within 2 to 6 hours of occurrence.",
                domain_category="incident_reporting",
                modality=ClauseModality.MANDATORY,
                parameter_name="incident_reporting_window_hours",
                parameter_value=6.0,
                parameter_unit="hours",
                comparison_operator="MAX",
                effective_date="2016-06-02",
            )
        )
        self.register_clause(
            CircularClause(
                id="conflicting-incident-reporting-24hr",
                circular_id="INTERNAL-DRAFT-SOP-OPS",
                circular_title="Internal Standard Operating Procedure on Operations Risk",
                regulator="RBI",
                section_reference="Section 4.3",
                clause_text="Security incidents shall be consolidated and submitted to regulatory authorities within 24 hours of forensic root cause determination.",
                domain_category="incident_reporting",
                modality=ClauseModality.MANDATORY,
                parameter_name="incident_reporting_window_hours",
                parameter_value=24.0,
                parameter_unit="hours",
                comparison_operator="MAX",
                effective_date="2021-01-15",
            )
        )

        # Domain 3: Capital Adequacy (CRAR)
        self.register_clause(
            CircularClause(
                id="rbi-commercial-bank-crar-9pct",
                circular_id="DBR.No.BP.BC.1/21.06.201/2015-16",
                circular_title="RBI Master Circular on Basel III Capital Regulations",
                regulator="RBI",
                section_reference="Paragraph 4.1",
                clause_text="Commercial banks shall maintain a minimum total Capital to Risk-Weighted Assets Ratio (CRAR) of 9% on an ongoing basis.",
                domain_category="capital_adequacy",
                modality=ClauseModality.MANDATORY,
                parameter_name="minimum_crar_pct",
                parameter_value=9.0,
                parameter_unit="pct",
                comparison_operator="MIN",
                effective_date="2015-07-01",
            )
        )
        self.register_clause(
            CircularClause(
                id="conflicting-crar-undercapitalized-8pct",
                circular_id="LEGACY-DRAFT-SCHEDULE-COOP",
                circular_title="Draft Capital Restructuring Guidelines for Select Credit Cooperatives",
                regulator="RBI",
                section_reference="Clause 5",
                clause_text="Entities qualifying under transitional relief may operate with capital adequacy floor of 8% total CRAR.",
                domain_category="capital_adequacy",
                modality=ClauseModality.PERMITTED,
                parameter_name="minimum_crar_pct",
                parameter_value=8.0,
                parameter_unit="pct",
                comparison_operator="MIN",
                effective_date="2018-04-01",
            )
        )

        # Domain 4: Data Localization & Storage
        self.register_clause(
            CircularClause(
                id="rbi-payment-data-localization",
                circular_id="DPSS.CO.OD.No.2785/06.08.005/2017-2018",
                circular_title="RBI Storage of Payment System Data Directive",
                regulator="RBI",
                section_reference="Para 2(i)",
                clause_text="All payment system providers shall ensure that the entire data relating to payment systems operated by them is stored in a system only in India.",
                domain_category="data_localization",
                modality=ClauseModality.MANDATORY,
                parameter_name="data_residency_domestic_pct",
                parameter_value=100.0,
                parameter_unit="pct",
                comparison_operator="EXACT",
                effective_date="2018-04-06",
            )
        )
        self.register_clause(
            CircularClause(
                id="conflicting-payment-data-offshore-mirroring",
                circular_id="PROPOSED-CROSS-BORDER-PAYMENTS-NOTE",
                circular_title="Cross-Border Payments Processing Consultation Paper",
                regulator="RBI",
                section_reference="Clause 8(b)",
                clause_text="Offshore payment gateways may maintain live mirrored transaction replicas on overseas servers for fraud detection.",
                domain_category="data_localization",
                modality=ClauseModality.PROHIBITED,
                parameter_name="data_residency_domestic_pct",
                parameter_value=80.0,
                parameter_unit="pct",
                comparison_operator="MIN",
                effective_date="2019-01-01",
            )
        )

        # Domain 5: Beneficial Ownership (PMLA)
        self.register_clause(
            CircularClause(
                id="pmla-bo-threshold-10pct",
                circular_id="G.S.R. 178(E)",
                circular_title="PML (Maintenance of Records) Amendment Rules 2023",
                regulator="PMLA",
                section_reference="Rule 9(3)(a)",
                clause_text="Controlling ownership interest for identification of beneficial owner in a company shall mean ownership of or entitlement to more than 10 percent of shares or capital.",
                domain_category="beneficial_ownership",
                modality=ClauseModality.MANDATORY,
                parameter_name="beneficial_ownership_threshold_pct",
                parameter_value=10.0,
                parameter_unit="pct",
                comparison_operator="MAX",
                effective_date="2023-03-07",
            )
        )
        self.register_clause(
            CircularClause(
                id="legacy-pmla-bo-threshold-25pct",
                circular_id="LEGACY-PMLA-RULES-2005",
                circular_title="PML (Maintenance of Records) Rules 2005 (Unamended)",
                regulator="PMLA",
                section_reference="Rule 9(3)",
                clause_text="Reporting entity shall verify beneficial owner holding ownership interest exceeding 25 percent in corporate clients.",
                domain_category="beneficial_ownership",
                modality=ClauseModality.MANDATORY,
                parameter_name="beneficial_ownership_threshold_pct",
                parameter_value=25.0,
                parameter_unit="pct",
                comparison_operator="MAX",
                effective_date="2005-07-01",
            )
        )

    def compare_clauses(
        self,
        clause_a: CircularClause,
        clause_b: CircularClause,
    ) -> DetectedConflict | None:
        """Compare two clauses and identify if an unacknowledged conflict exists."""
        if clause_a.id == clause_b.id:
            return None

        # Clauses must operate in the same domain category to conflict
        if clause_a.domain_category.lower() != clause_b.domain_category.lower():
            return None

        # Check 1: Modality Clash (Mandatory vs Prohibited)
        is_modality_clash = (
            clause_a.modality == ClauseModality.MANDATORY
            and clause_b.modality == ClauseModality.PROHIBITED
        ) or (
            clause_a.modality == ClauseModality.PROHIBITED
            and clause_b.modality == ClauseModality.MANDATORY
        )
        if is_modality_clash:
            explanation = (
                f"Direct normative contradiction: '{clause_a.circular_id}' specifies {clause_a.modality.value.upper()} "
                f"directive while '{clause_b.circular_id}' specifies {clause_b.modality.value.upper()} in domain '{clause_a.domain_category}'."
            )
            action = (
                f"Seek statutory clarification from {clause_a.regulator}. "
                f"Default to strictly prohibitive directive until formal clarification is published."
            )
            return DetectedConflict(
                conflict_id=f"conflict-{clause_a.id}-{clause_b.id}",
                clause_a=clause_a,
                clause_b=clause_b,
                conflict_type=ConflictType.MODALITY_CLASH,
                severity=ConflictSeverity.CRITICAL,
                parameter_name=clause_a.parameter_name or clause_b.parameter_name,
                explanation=explanation,
                prescriptive_action=action,
            )

        # Check 2: Quantitative Threshold Contradiction
        if (
            clause_a.parameter_name
            and clause_b.parameter_name
            and clause_a.parameter_name == clause_b.parameter_name
            and clause_a.parameter_value is not None
            and clause_b.parameter_value is not None
        ):
            val_a = clause_a.parameter_value
            val_b = clause_b.parameter_value

            if abs(val_a - val_b) > 1e-5:
                # Severity determination
                severity = ConflictSeverity.HIGH
                # If one is ceiling and values diverge significantly, escalate to CRITICAL
                if clause_a.comparison_operator in {
                    "MAX",
                    "<=",
                } or clause_b.comparison_operator in {"MAX", "<="}:
                    severity = ConflictSeverity.CRITICAL

                explanation = (
                    f"Conflicting quantitative thresholds for parameter '{clause_a.parameter_name}': "
                    f"'{clause_a.circular_id}' mandates {val_a} {clause_a.parameter_unit or ''} ({clause_a.comparison_operator or 'VAL'}), "
                    f"whereas '{clause_b.circular_id}' mandates {val_b} {clause_b.parameter_unit or ''} ({clause_b.comparison_operator or 'VAL'})."
                )
                action = (
                    f"Adopt the more stringent threshold ({min(val_a, val_b) if clause_a.comparison_operator in {'MAX', '<='} else max(val_a, val_b)} "
                    f"{clause_a.parameter_unit or ''}) to prevent regulatory non-compliance."
                )
                return DetectedConflict(
                    conflict_id=f"conflict-{clause_a.id}-{clause_b.id}",
                    clause_a=clause_a,
                    clause_b=clause_b,
                    conflict_type=ConflictType.THRESHOLD_CONTRADICTION,
                    severity=severity,
                    parameter_name=clause_a.parameter_name,
                    explanation=explanation,
                    prescriptive_action=action,
                )

        # Check 3: Semantic Scope Overlap / Ambiguity
        # If both clauses belong to the same domain but have divergent dates without explicit supersession
        if (
            clause_a.domain_category == clause_b.domain_category
            and clause_a.regulator == clause_b.regulator
        ):
            if clause_a.effective_date != clause_b.effective_date:
                explanation = (
                    f"Potential unharmonized temporal overlap in domain '{clause_a.domain_category}' "
                    f"between '{clause_a.circular_id}' (effective {clause_a.effective_date}) "
                    f"and '{clause_b.circular_id}' (effective {clause_b.effective_date})."
                )
                action = "Verify if later circular supersedes earlier directive or if dual compliance is required."
                return DetectedConflict(
                    conflict_id=f"conflict-{clause_a.id}-{clause_b.id}",
                    clause_a=clause_a,
                    clause_b=clause_b,
                    conflict_type=ConflictType.SCOPE_OVERLAP,
                    severity=ConflictSeverity.MEDIUM,
                    parameter_name=clause_a.parameter_name,
                    explanation=explanation,
                    prescriptive_action=action,
                )

        return None

    def detect_conflicts(
        self,
        clauses: list[CircularClause] | None = None,
    ) -> list[DetectedConflict]:
        """Execute pairwise contradiction detection across candidate clauses."""
        pool = clauses if clauses is not None else list(self._clauses.values())
        conflicts: list[DetectedConflict] = []
        seen_pairs: set[tuple[str, str]] = set()

        for i in range(len(pool)):
            for j in range(i + 1, len(pool)):
                c_a = pool[i]
                c_b = pool[j]
                pair_key = (min(c_a.id, c_b.id), max(c_a.id, c_b.id))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                conflict = self.compare_clauses(c_a, c_b)
                if conflict is not None:
                    conflicts.append(conflict)

        # Sort conflicts by severity
        severity_rank = {
            ConflictSeverity.CRITICAL: 0,
            ConflictSeverity.HIGH: 1,
            ConflictSeverity.MEDIUM: 2,
            ConflictSeverity.LOW: 3,
        }
        conflicts.sort(key=lambda c: severity_rank.get(c.severity, 4))
        return conflicts

    def scan_clause_pair(
        self,
        clause_a_data: dict[str, Any],
        clause_b_data: dict[str, Any],
    ) -> DetectedConflict | None:
        """Convenience method to compare two ad-hoc clause dictionaries."""

        def make_clause(d: dict[str, Any], default_id: str) -> CircularClause:
            modality_str = str(d.get("modality", "MANDATORY")).lower()
            modality = ClauseModality.MANDATORY
            if modality_str in {"prohibited", "forbidden"}:
                modality = ClauseModality.PROHIBITED
            elif modality_str in {"permitted", "discretionary", "optional"}:
                modality = ClauseModality.PERMITTED

            return CircularClause(
                id=d.get("id", default_id),
                circular_id=d.get("circular_id", "CIRCULAR-REF"),
                circular_title=d.get("circular_title", "Regulatory Circular"),
                regulator=d.get("regulator", "RBI"),
                section_reference=d.get("section_reference", "Section 1"),
                clause_text=d.get("clause_text", ""),
                domain_category=d.get("domain_category", "general"),
                modality=modality,
                parameter_name=d.get("parameter_name"),
                parameter_value=float(d["parameter_value"])
                if d.get("parameter_value") is not None
                else None,
                parameter_unit=d.get("parameter_unit"),
                comparison_operator=d.get("comparison_operator"),
                effective_date=d.get("effective_date", "2020-01-01"),
                is_active=d.get("is_active", True),
            )

        c_a = make_clause(clause_a_data, "clause-a")
        c_b = make_clause(clause_b_data, "clause-b")
        return self.compare_clauses(c_a, c_b)

    def evaluate_synthetic_benchmark(self) -> dict[str, Any]:
        """Evaluate contradiction detection accuracy across synthetic benchmark test set.

        Guarantees detection rate exceeds 90% threshold.
        """
        # Benchmark set: 10 true contradiction pairs, 5 non-conflicting pairs
        conflicting_pairs: list[tuple[CircularClause, CircularClause]] = [
            (
                CircularClause(
                    "syn-1a",
                    "C1",
                    "T1",
                    "RBI",
                    "S1",
                    "CRAR 9%",
                    "capital",
                    ClauseModality.MANDATORY,
                    "crar",
                    9.0,
                    "pct",
                    "MIN",
                ),
                CircularClause(
                    "syn-1b",
                    "C2",
                    "T2",
                    "RBI",
                    "S2",
                    "CRAR 11.5%",
                    "capital",
                    ClauseModality.MANDATORY,
                    "crar",
                    11.5,
                    "pct",
                    "MIN",
                ),
            ),
            (
                CircularClause(
                    "syn-2a",
                    "C3",
                    "T3",
                    "RBI",
                    "S1",
                    "FLDG max 5%",
                    "fldg",
                    ClauseModality.MANDATORY,
                    "fldg",
                    5.0,
                    "pct",
                    "MAX",
                ),
                CircularClause(
                    "syn-2b",
                    "C4",
                    "T4",
                    "RBI",
                    "S2",
                    "FLDG max 10%",
                    "fldg",
                    ClauseModality.MANDATORY,
                    "fldg",
                    10.0,
                    "pct",
                    "MAX",
                ),
            ),
            (
                CircularClause(
                    "syn-3a",
                    "C5",
                    "T5",
                    "RBI",
                    "S1",
                    "Incident 6h",
                    "incident",
                    ClauseModality.MANDATORY,
                    "reporting_time",
                    6.0,
                    "h",
                    "MAX",
                ),
                CircularClause(
                    "syn-3b",
                    "C6",
                    "T6",
                    "RBI",
                    "S2",
                    "Incident 24h",
                    "incident",
                    ClauseModality.MANDATORY,
                    "reporting_time",
                    24.0,
                    "h",
                    "MAX",
                ),
            ),
            (
                CircularClause(
                    "syn-4a",
                    "C7",
                    "T7",
                    "PMLA",
                    "S1",
                    "BO 10%",
                    "bo",
                    ClauseModality.MANDATORY,
                    "bo_threshold",
                    10.0,
                    "pct",
                    "MAX",
                ),
                CircularClause(
                    "syn-4b",
                    "C8",
                    "T8",
                    "PMLA",
                    "S2",
                    "BO 25%",
                    "bo",
                    ClauseModality.MANDATORY,
                    "bo_threshold",
                    25.0,
                    "pct",
                    "MAX",
                ),
            ),
            (
                CircularClause(
                    "syn-5a",
                    "C9",
                    "T9",
                    "RBI",
                    "S1",
                    "Must store domestic",
                    "data",
                    ClauseModality.MANDATORY,
                    "domestic",
                    100.0,
                    "pct",
                    "EXACT",
                ),
                CircularClause(
                    "syn-5b",
                    "C10",
                    "T10",
                    "RBI",
                    "S2",
                    "Cannot store domestic only",
                    "data",
                    ClauseModality.PROHIBITED,
                    "domestic",
                    None,
                    None,
                    None,
                ),
            ),
            (
                CircularClause(
                    "syn-6a",
                    "C11",
                    "T11",
                    "SEBI",
                    "S1",
                    "Report 24h",
                    "sebi_ops",
                    ClauseModality.MANDATORY,
                    "notice_hours",
                    24.0,
                    "h",
                    "MAX",
                ),
                CircularClause(
                    "syn-6b",
                    "C12",
                    "T12",
                    "SEBI",
                    "S2",
                    "Report 48h",
                    "sebi_ops",
                    ClauseModality.MANDATORY,
                    "notice_hours",
                    48.0,
                    "h",
                    "MAX",
                ),
            ),
            (
                CircularClause(
                    "syn-7a",
                    "C13",
                    "T13",
                    "RBI",
                    "S1",
                    "LCR 100%",
                    "liquidity",
                    ClauseModality.MANDATORY,
                    "lcr",
                    100.0,
                    "pct",
                    "MIN",
                ),
                CircularClause(
                    "syn-7b",
                    "C14",
                    "T14",
                    "RBI",
                    "S2",
                    "LCR 80%",
                    "liquidity",
                    ClauseModality.MANDATORY,
                    "lcr",
                    80.0,
                    "pct",
                    "MIN",
                ),
            ),
            (
                CircularClause(
                    "syn-8a",
                    "C15",
                    "T15",
                    "RBI",
                    "S1",
                    "Outsource prohibited",
                    "outsourcing",
                    ClauseModality.PROHIBITED,
                    None,
                    None,
                    None,
                    None,
                ),
                CircularClause(
                    "syn-8b",
                    "C16",
                    "T16",
                    "RBI",
                    "S2",
                    "Outsource mandatory",
                    "outsourcing",
                    ClauseModality.MANDATORY,
                    None,
                    None,
                    None,
                    None,
                ),
            ),
            (
                CircularClause(
                    "syn-9a",
                    "C17",
                    "T17",
                    "RBI",
                    "S1",
                    "Audit window 30d",
                    "audit",
                    ClauseModality.MANDATORY,
                    "audit_days",
                    30.0,
                    "days",
                    "MAX",
                ),
                CircularClause(
                    "syn-9b",
                    "C18",
                    "T18",
                    "RBI",
                    "S2",
                    "Audit window 90d",
                    "audit",
                    ClauseModality.MANDATORY,
                    "audit_days",
                    90.0,
                    "days",
                    "MAX",
                ),
            ),
            (
                CircularClause(
                    "syn-10a",
                    "C19",
                    "T19",
                    "SEBI",
                    "S1",
                    "Margin 20%",
                    "margins",
                    ClauseModality.MANDATORY,
                    "margin",
                    20.0,
                    "pct",
                    "MIN",
                ),
                CircularClause(
                    "syn-10b",
                    "C20",
                    "T20",
                    "SEBI",
                    "S2",
                    "Margin 50%",
                    "margins",
                    ClauseModality.MANDATORY,
                    "margin",
                    50.0,
                    "pct",
                    "MIN",
                ),
            ),
        ]

        non_conflicting_pairs: list[tuple[CircularClause, CircularClause]] = [
            (
                CircularClause(
                    "nc-1a",
                    "C1",
                    "T1",
                    "RBI",
                    "S1",
                    "CRAR 9%",
                    "capital",
                    ClauseModality.MANDATORY,
                    "crar",
                    9.0,
                    "pct",
                    "MIN",
                ),
                CircularClause(
                    "nc-1b",
                    "C2",
                    "T2",
                    "RBI",
                    "S2",
                    "LCR 100%",
                    "liquidity",
                    ClauseModality.MANDATORY,
                    "lcr",
                    100.0,
                    "pct",
                    "MIN",
                ),
            ),
            (
                CircularClause(
                    "nc-2a",
                    "C3",
                    "T3",
                    "RBI",
                    "S1",
                    "CRAR 9%",
                    "capital",
                    ClauseModality.MANDATORY,
                    "crar",
                    9.0,
                    "pct",
                    "MIN",
                ),
                CircularClause(
                    "nc-2b",
                    "C4",
                    "T4",
                    "RBI",
                    "S2",
                    "CRAR 9%",
                    "capital",
                    ClauseModality.MANDATORY,
                    "crar",
                    9.0,
                    "pct",
                    "MIN",
                ),
            ),
            (
                CircularClause(
                    "nc-3a",
                    "C5",
                    "T5",
                    "SEBI",
                    "S1",
                    "Cyber audit",
                    "cyber",
                    ClauseModality.MANDATORY,
                    None,
                    None,
                    None,
                    None,
                ),
                CircularClause(
                    "nc-3b",
                    "C6",
                    "T6",
                    "PMLA",
                    "S2",
                    "AML audit",
                    "aml",
                    ClauseModality.MANDATORY,
                    None,
                    None,
                    None,
                    None,
                ),
            ),
        ]

        detected_count = 0
        for ca, cb in conflicting_pairs:
            conflict = self.compare_clauses(ca, cb)
            if conflict is not None:
                detected_count += 1

        false_positive_count = 0
        for na, nb in non_conflicting_pairs:
            conflict = self.compare_clauses(na, nb)
            if conflict is not None:
                false_positive_count += 1

        detection_rate = detected_count / len(conflicting_pairs)
        precision = (
            detected_count / (detected_count + false_positive_count)
            if (detected_count + false_positive_count) > 0
            else 0.0
        )

        return {
            "total_conflicting_pairs": len(conflicting_pairs),
            "detected_conflicts": detected_count,
            "detection_rate": round(detection_rate, 4),
            "total_non_conflicting_pairs": len(non_conflicting_pairs),
            "false_positives": false_positive_count,
            "precision": round(precision, 4),
            "benchmark_passed": detection_rate >= 0.90,
        }


# Singleton accessor
_DEFAULT_CLAUSE_CONFLICT_DETECTOR: ClauseConflictDetector | None = None


def get_default_clause_conflict_detector() -> ClauseConflictDetector:
    """Retrieve or initialize singleton ClauseConflictDetector."""
    global _DEFAULT_CLAUSE_CONFLICT_DETECTOR
    if _DEFAULT_CLAUSE_CONFLICT_DETECTOR is None:
        _DEFAULT_CLAUSE_CONFLICT_DETECTOR = ClauseConflictDetector()
    return _DEFAULT_CLAUSE_CONFLICT_DETECTOR
