"""Historical Formula Evolution & Versioning (FEAT-030).

Tracks regulatory formula revisions over time, resolves point-in-time statutory definitions
based on effective date windows, and computes semantic diffs between circular revisions
(Basel II vs Basel III, LCR phase-in schedules, IRAC norms, and ISO/IEC 21031).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import structlog

from app.compliance.dependency_graph import extract_variables_from_expression

logger = structlog.get_logger("docscout.compliance.formula_evolution")


class ChangeClassification(StrEnum):
    """Categorization of regulatory changes between formula revisions."""

    BREAKING = "breaking"  # Structural formula change, new required inputs, or stricter threshold
    PHASE_IN = "phase_in"  # Scheduled transitional threshold adjustment
    AMENDMENT = "amendment"  # Minor parameter or definition refinement
    CLARIFICATION = "clarification"  # Variable renaming or wording clarification


@dataclass
class FormulaVersion:
    """Historical version snapshot of a regulatory calculation formula."""

    id: str
    formula_id: str
    version_label: str
    regulatory_framework: str
    effective_from: str  # YYYY-MM-DD
    effective_to: str | None = None  # YYYY-MM-DD or None if currently active
    expression: str = ""
    eval_expression: str = ""
    variables: list[str] = field(default_factory=list)
    thresholds: dict[str, Any] = field(default_factory=dict)
    circular_reference: str | None = None
    change_summary: str = ""

    def __post_init__(self) -> None:
        if not self.variables and self.expression:
            self.variables = extract_variables_from_expression(self.expression)

    def is_active_on(self, as_of: str | date) -> bool:
        """Check whether this formula version was active on a given date."""
        target_date = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        from_date = date.fromisoformat(self.effective_from)
        if target_date < from_date:
            return False
        if self.effective_to is not None:
            to_date = date.fromisoformat(self.effective_to)
            if target_date > to_date:
                return False
        return True

    @property
    def is_currently_active(self) -> bool:
        """Returns True if this version has no sunset date and is currently active."""
        return self.effective_to is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "formula_id": self.formula_id,
            "version_label": self.version_label,
            "regulatory_framework": self.regulatory_framework,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "expression": self.expression,
            "eval_expression": self.eval_expression,
            "variables": self.variables,
            "thresholds": self.thresholds,
            "circular_reference": self.circular_reference,
            "change_summary": self.change_summary,
            "is_currently_active": self.effective_to is None,
        }


@dataclass
class FormulaVersionDiff:
    """Comparative delta between two historical versions of a statutory formula."""

    formula_id: str
    version_a_id: str
    version_b_id: str
    version_a_label: str
    version_b_label: str
    expression_changed: bool
    expression_a: str
    expression_b: str
    variables_added: list[str]
    variables_removed: list[str]
    variables_retained: list[str]
    threshold_changes: dict[str, dict[str, Any]]
    change_type: ChangeClassification
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "version_a_id": self.version_a_id,
            "version_b_id": self.version_b_id,
            "version_a_label": self.version_a_label,
            "version_b_label": self.version_b_label,
            "expression_changed": self.expression_changed,
            "expression_a": self.expression_a,
            "expression_b": self.expression_b,
            "variables_added": self.variables_added,
            "variables_removed": self.variables_removed,
            "variables_retained": self.variables_retained,
            "threshold_changes": self.threshold_changes,
            "change_type": self.change_type.value,
            "summary": self.summary,
        }


class FormulaEvolutionManager:
    """Registry and query engine for historical statutory formula evolutions."""

    _instance: FormulaEvolutionManager | None = None

    def __init__(self) -> None:
        self._versions_by_id: dict[str, FormulaVersion] = {}
        self._versions_by_formula: dict[str, list[FormulaVersion]] = {}
        self._load_canonical_history()

    @classmethod
    def get_instance(cls) -> FormulaEvolutionManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_version(self, version: FormulaVersion) -> None:
        """Register a formula version in the in-memory timeline."""
        self._versions_by_id[version.id] = version
        hist = self._versions_by_formula.setdefault(version.formula_id, [])
        # Replace if existing or append
        existing_idx = next((i for i, v in enumerate(hist) if v.id == version.id), None)
        if existing_idx is not None:
            hist[existing_idx] = version
        else:
            hist.append(version)
        hist.sort(key=lambda v: v.effective_from)

    def get_version(self, version_id: str) -> FormulaVersion | None:
        """Retrieve a specific version by its unique identifier."""
        return self._versions_by_id.get(version_id)

    def get_history(self, formula_id: str) -> list[FormulaVersion]:
        """Return chronological timeline of formula versions for a given metric."""
        fid = formula_id.lower().strip()
        hist = self._versions_by_formula.get(fid)
        if hist is None:
            raise KeyError(f"No historical formula records found for '{formula_id}'.")
        return list(hist)

    def resolve_version(self, formula_id: str, as_of: str | date) -> FormulaVersion:
        """Resolve the active statutory formula definition for a specific point in time."""
        history = self.get_history(formula_id)
        target = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of

        for v in history:
            if v.is_active_on(target):
                return v

        # If date is earlier than earliest version, return earliest with warning
        if target < date.fromisoformat(history[0].effective_from):
            logger.warning(
                "as_of_date_prior_to_earliest_statutory_record",
                as_of=str(target),
                earliest=history[0].effective_from,
                formula=formula_id,
            )
            return history[0]

        # If date is later than all, return most recent
        return history[-1]

    def compare_versions(self, version_a_id: str, version_b_id: str) -> FormulaVersionDiff:
        """Compute structured diff and semantic impact between two formula versions."""
        ver_a = self.get_version(version_a_id)
        if ver_a is None:
            raise KeyError(f"Formula version '{version_a_id}' not found.")
        ver_b = self.get_version(version_b_id)
        if ver_b is None:
            raise KeyError(f"Formula version '{version_b_id}' not found.")

        expr_changed = ver_a.expression.strip() != ver_b.expression.strip()
        vars_a = set(ver_a.variables)
        vars_b = set(ver_b.variables)

        added = sorted(vars_b - vars_a)
        removed = sorted(vars_a - vars_b)
        retained = sorted(vars_a & vars_b)

        # Detect threshold changes
        th_changes: dict[str, dict[str, Any]] = {}
        all_th_keys = set(ver_a.thresholds.keys()) | set(ver_b.thresholds.keys())
        for k in sorted(all_th_keys):
            old_val = ver_a.thresholds.get(k)
            new_val = ver_b.thresholds.get(k)
            if old_val != new_val:
                th_changes[k] = {"old": old_val, "new": new_val}

        # Classify change
        if len(added) > 0 or len(removed) > 0:
            classification = ChangeClassification.BREAKING
            summary_text = (
                f"Structural formula change: {len(added)} variable(s) introduced ({', '.join(added)}), "
                f"{len(removed)} variable(s) phased out ({', '.join(removed)})."
            )
        elif th_changes:
            classification = ChangeClassification.PHASE_IN
            summary_text = f"Regulatory threshold revision across {len(th_changes)} parameter(s)."
        elif expr_changed:
            classification = ChangeClassification.AMENDMENT
            summary_text = "Mathematical formulation revised without changing variable footprint."
        else:
            classification = ChangeClassification.CLARIFICATION
            summary_text = "Minor administrative clarification."

        return FormulaVersionDiff(
            formula_id=ver_b.formula_id,
            version_a_id=ver_a.id,
            version_b_id=ver_b.id,
            version_a_label=ver_a.version_label,
            version_b_label=ver_b.version_label,
            expression_changed=expr_changed,
            expression_a=ver_a.expression,
            expression_b=ver_b.expression,
            variables_added=added,
            variables_removed=removed,
            variables_retained=retained,
            threshold_changes=th_changes,
            change_type=classification,
            summary=summary_text,
        )

    def list_tracked_formulas(self) -> list[dict[str, Any]]:
        """List summary of all formulas with available historical version records."""
        summaries = []
        for fid, versions in sorted(self._versions_by_formula.items()):
            active = next((v for v in versions if v.effective_to is None), versions[-1])
            summaries.append(
                {
                    "formula_id": fid,
                    "current_label": active.version_label,
                    "regulatory_framework": active.regulatory_framework,
                    "version_count": len(versions),
                    "earliest_effective": versions[0].effective_from,
                    "current_expression": active.expression,
                    "current_thresholds": active.thresholds,
                }
            )
        return summaries

    def _load_canonical_history(self) -> None:
        """Seed registry with authoritative regulatory evolution timelines."""
        # 1. Capital Adequacy Ratio (CRAR / Basel evolution)
        crar_versions = [
            FormulaVersion(
                id="crar_basel1",
                formula_id="crar",
                version_label="Basel I Accord (RBI 1992)",
                regulatory_framework="RBI Master Circular - Basel I",
                effective_from="1992-04-01",
                effective_to="1999-03-31",
                expression="(tier1_capital + tier2_capital) / credit_rwa * 100",
                eval_expression="(tier1_capital + tier2_capital) / credit_rwa * 100",
                variables=["tier1_capital", "tier2_capital", "credit_rwa"],
                thresholds={"minimum_crar": 8.0, "tier1_minimum": 4.0},
                circular_reference="DBOD.No.BP.BC.129/21.01.002/92",
                change_summary="Original Basel I capital adequacy implementation targeting 8% minimum solvency on credit risk.",
            ),
            FormulaVersion(
                id="crar_basel2",
                formula_id="crar",
                version_label="Basel II Framework (RBI 1999/2007)",
                regulatory_framework="RBI Master Circular - Basel II",
                effective_from="1999-04-01",
                effective_to="2013-03-31",
                expression="(tier1_capital + tier2_capital) / (credit_rwa + market_rwa + operational_rwa) * 100",
                eval_expression="(tier1_capital + tier2_capital) / (credit_rwa + market_rwa + operational_rwa) * 100",
                variables=[
                    "tier1_capital",
                    "tier2_capital",
                    "credit_rwa",
                    "market_rwa",
                    "operational_rwa",
                ],
                thresholds={"minimum_crar": 9.0, "tier1_minimum": 6.0},
                circular_reference="DBOD.No.BP.BC.90/20.06.001/2006-07",
                change_summary="Incorporated Market Risk and Operational Risk into total RWA; increased minimum CRAR to 9% in India.",
            ),
            FormulaVersion(
                id="crar_basel3_interim",
                formula_id="crar",
                version_label="Basel III Interim Phase-In (RBI 2013-2019)",
                regulatory_framework="RBI Master Direction - Basel III",
                effective_from="2013-04-01",
                effective_to="2019-03-31",
                expression="(cet1_capital + at1_capital + tier2_capital) / total_rwa * 100",
                eval_expression="(cet1_capital + at1_capital + tier2_capital) / total_rwa * 100",
                variables=["cet1_capital", "at1_capital", "tier2_capital", "total_rwa"],
                thresholds={
                    "minimum_crar": 9.0,
                    "cet1_minimum": 5.5,
                    "tier1_minimum": 7.0,
                    "capital_conservation_buffer": 1.875,
                },
                circular_reference="DBOD.No.BP.BC.98/21.06.001/2011-12",
                change_summary="Introduced Common Equity Tier 1 (CET1) and Additional Tier 1 (AT1); phased in Capital Conservation Buffer.",
            ),
            FormulaVersion(
                id="crar_basel3_current",
                formula_id="crar",
                version_label="Basel III Fully Phased In (Current)",
                regulatory_framework="RBI Master Direction - Basel III Capital Regulations",
                effective_from="2019-04-01",
                effective_to=None,
                expression="(cet1_capital + at1_capital + tier2_capital) / total_rwa * 100",
                eval_expression="(cet1_capital + at1_capital + tier2_capital) / total_rwa * 100",
                variables=["cet1_capital", "at1_capital", "tier2_capital", "total_rwa"],
                thresholds={
                    "minimum_crar": 9.0,
                    "cet1_minimum": 5.5,
                    "tier1_minimum": 7.0,
                    "capital_conservation_buffer": 2.50,
                    "total_capital_with_ccb": 11.50,
                },
                circular_reference="DOR.CAP.REC.3/21.06.201/2022-23",
                change_summary="Full 2.50% Capital Conservation Buffer operationalized, requiring 11.50% total regulatory capital.",
            ),
        ]
        for v in crar_versions:
            self.register_version(v)

        # 2. Liquidity Coverage Ratio (LCR 2015-2019 phase-in schedule)
        lcr_versions = [
            FormulaVersion(
                id="lcr_2015",
                formula_id="lcr",
                version_label="LCR 2015 Phase-In (60%)",
                regulatory_framework="RBI Liquidity Risk Management Framework",
                effective_from="2015-01-01",
                effective_to="2015-12-31",
                expression="(total_hqla / net_cash_outflows) * 100",
                eval_expression="(total_hqla / net_cash_outflows) * 100",
                variables=["total_hqla", "net_cash_outflows"],
                thresholds={"minimum_lcr": 60.0},
                circular_reference="DBOD.BP.BC.No.120/21.04.098/2013-14",
                change_summary="Inception of statutory Liquidity Coverage Ratio with starting prudential floor at 60%.",
            ),
            FormulaVersion(
                id="lcr_2016",
                formula_id="lcr",
                version_label="LCR 2016 Phase-In (70%)",
                regulatory_framework="RBI Liquidity Risk Management Framework",
                effective_from="2016-01-01",
                effective_to="2016-12-31",
                expression="(total_hqla / net_cash_outflows) * 100",
                eval_expression="(total_hqla / net_cash_outflows) * 100",
                variables=["total_hqla", "net_cash_outflows"],
                thresholds={"minimum_lcr": 70.0},
                circular_reference="DBR.BP.BC.No.86/21.04.098/2015-16",
                change_summary="Annual step-up incrementing LCR threshold to 70%.",
            ),
            FormulaVersion(
                id="lcr_2017",
                formula_id="lcr",
                version_label="LCR 2017 Phase-In (80%)",
                regulatory_framework="RBI Liquidity Risk Management Framework",
                effective_from="2017-01-01",
                effective_to="2017-12-31",
                expression="(total_hqla / net_cash_outflows) * 100",
                eval_expression="(total_hqla / net_cash_outflows) * 100",
                variables=["total_hqla", "net_cash_outflows"],
                thresholds={"minimum_lcr": 80.0},
                circular_reference="DBR.BP.BC.No.86/21.04.098/2015-16",
                change_summary="Annual step-up incrementing LCR threshold to 80%.",
            ),
            FormulaVersion(
                id="lcr_2018",
                formula_id="lcr",
                version_label="LCR 2018 Phase-In (90%)",
                regulatory_framework="RBI Liquidity Risk Management Framework",
                effective_from="2018-01-01",
                effective_to="2018-12-31",
                expression="(total_hqla / net_cash_outflows) * 100",
                eval_expression="(total_hqla / net_cash_outflows) * 100",
                variables=["total_hqla", "net_cash_outflows"],
                thresholds={"minimum_lcr": 90.0},
                circular_reference="DBR.BP.BC.No.86/21.04.098/2015-16",
                change_summary="Annual step-up incrementing LCR threshold to 90%.",
            ),
            FormulaVersion(
                id="lcr_current",
                formula_id="lcr",
                version_label="LCR Full Standard (100% Minimum)",
                regulatory_framework="RBI Basel III Liquidity Standards",
                effective_from="2019-01-01",
                effective_to=None,
                expression="(total_hqla / net_cash_outflows) * 100",
                eval_expression="(total_hqla / net_cash_outflows) * 100",
                variables=["total_hqla", "net_cash_outflows"],
                thresholds={"minimum_lcr": 100.0},
                circular_reference="DOR.BP.BC.No.4/21.04.098/2020-21",
                change_summary="Terminal 100% statutory floor enacted permanently across all scheduled commercial banks.",
            ),
        ]
        for v in lcr_versions:
            self.register_version(v)

        # 3. Provision Coverage Ratio (PCR)
        pcr_versions = [
            FormulaVersion(
                id="pcr_2009",
                formula_id="pcr",
                version_label="PCR Benchmark Norm (RBI 2009)",
                regulatory_framework="RBI Master Circular - Prudential Norms",
                effective_from="2009-12-01",
                effective_to="2011-04-20",
                expression="(cumulative_provisions / gross_npa) * 100",
                eval_expression="(cumulative_provisions / gross_npa) * 100",
                variables=["cumulative_provisions", "gross_npa"],
                thresholds={"statutory_benchmark": 70.0},
                circular_reference="DBOD.No.BP.BC.64/21.04.048/2009-10",
                change_summary="Mandated statutory 70% provision coverage benchmark ratio as a counter-cyclical measure.",
            ),
            FormulaVersion(
                id="pcr_current",
                formula_id="pcr",
                version_label="PCR Buffer Framework (RBI 2011-Present)",
                regulatory_framework="RBI Prudential Norms on IRAC",
                effective_from="2011-04-21",
                effective_to=None,
                expression="(cumulative_provisions / gross_npa) * 100",
                eval_expression="(cumulative_provisions / gross_npa) * 100",
                variables=["cumulative_provisions", "gross_npa"],
                thresholds={"recommended_floor": 70.0, "floating_provision_buffer": True},
                circular_reference="DBOD.No.BP.BC.87/21.04.048/2010-11",
                change_summary="Transitioned 70% threshold into a floating buffer requirement segregated in a separate reserve.",
            ),
        ]
        for v in pcr_versions:
            self.register_version(v)

        # 4. Software Carbon Intensity (SCI)
        sci_versions = [
            FormulaVersion(
                id="sci_draft_v1",
                formula_id="sci",
                version_label="GSF Specification Draft v1.0",
                regulatory_framework="Green Software Foundation",
                effective_from="2021-11-01",
                effective_to="2024-03-31",
                expression="(energy_kwh * carbon_intensity + embodied_carbon) / functional_unit",
                eval_expression="(energy_kwh * carbon_intensity + embodied_carbon) / functional_unit",
                variables=["energy_kwh", "carbon_intensity", "embodied_carbon", "functional_unit"],
                thresholds={},
                circular_reference="GSF-SCI-v1.0",
                change_summary="Initial operational drafting specification defining Software Carbon Intensity rate.",
            ),
            FormulaVersion(
                id="sci_iso_21031",
                formula_id="sci",
                version_label="ISO/IEC 21031:2024 Standard",
                regulatory_framework="ISO/IEC Standard",
                effective_from="2024-04-01",
                effective_to=None,
                expression="((energy_kwh * grid_intensity) + (embodied_carbon * time_share * res_share)) / functional_unit_r",
                eval_expression="((energy_kwh * grid_intensity) + (embodied_carbon * time_share * res_share)) / functional_unit_r",
                variables=[
                    "energy_kwh",
                    "grid_intensity",
                    "embodied_carbon",
                    "time_share",
                    "res_share",
                    "functional_unit_r",
                ],
                thresholds={"audit_conformance": True},
                circular_reference="ISO/IEC 21031:2024",
                change_summary="International standard adding explicit time-share and resource-share allocation parameters to embodied carbon.",
            ),
        ]
        for v in sci_versions:
            self.register_version(v)


def get_default_formula_evolution_manager() -> FormulaEvolutionManager:
    """Return singleton instance of the FormulaEvolutionManager."""
    return FormulaEvolutionManager.get_instance()
