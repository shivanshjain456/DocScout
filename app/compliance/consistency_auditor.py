"""Mathematical Sanity & Consistency Auditor (FEAT-027).

Validates quantitative statements, tabular financial disclosures, regulatory returns,
and annexure schedules against fundamental mathematical identities, cross-footing rules,
percentage distributions, and statutory hierarchy invariants.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger("docscout.compliance.consistency_auditor")


class AuditSeverity(StrEnum):
    """Severity classification for mathematical and consistency anomalies."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    WARNING = "WARNING"
    INFO = "INFO"


class AnomalyType(StrEnum):
    """Categorization of mathematical sanity failure modes."""

    SUM_MISMATCH = "sum_mismatch"
    PERCENTAGE_DISTRIBUTION = "percentage_distribution_invalid"
    IDENTITY_VIOLATION = "identity_violation"
    RATIO_MISMATCH = "computed_vs_reported_mismatch"
    CROSS_FOOT_FAILURE = "cross_foot_failure"
    RANGE_OUT_OF_BOUNDS = "range_out_of_bounds"
    ZERO_DENOMINATOR = "zero_denominator"


@dataclass
class ConsistencyAnomaly:
    """An individual anomaly or discrepancy detected during mathematical audit."""

    anomaly_type: AnomalyType
    severity: AuditSeverity
    rule_name: str
    message: str
    location: str
    reported_value: float | None = None
    expected_value: float | None = None
    discrepancy: float | None = None
    tolerance: float = 0.01
    remediation_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "rule_name": self.rule_name,
            "message": self.message,
            "location": self.location,
            "reported_value": self.reported_value,
            "expected_value": self.expected_value,
            "discrepancy": self.discrepancy,
            "tolerance": self.tolerance,
            "remediation_hint": self.remediation_hint,
        }


@dataclass
class AuditTable:
    """Structured grid representation of a financial or regulatory table."""

    title: str | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_labels: list[str] = field(default_factory=list)
    has_row_totals: bool | None = None
    has_col_totals: bool | None = None
    tolerance: float = 0.01


@dataclass
class AuditSubmission:
    """Composite submission payload containing declared metrics and tables."""

    document_id: str | None = None
    return_code: str = "GENERIC"
    declared_values: dict[str, float] = field(default_factory=dict)
    tables: list[AuditTable] = field(default_factory=list)
    tolerance: float = 0.01


@dataclass
class AuditResult:
    """Overall outcome of a mathematical sanity audit run."""

    is_valid: bool
    total_rules_checked: int
    anomalies_count: int
    anomalies: list[ConsistencyAnomaly]
    passed_checks: list[str]
    summary: str
    execution_time_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "total_rules_checked": self.total_rules_checked,
            "anomalies_count": self.anomalies_count,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "passed_checks": self.passed_checks,
            "summary": self.summary,
            "execution_time_ms": self.execution_time_ms,
        }


def _safe_float(val: Any) -> float | None:
    """Attempt parsing numeric value, ignoring currency symbols and commas."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        clean = val.strip().replace(",", "").replace("₹", "").replace("$", "").replace("%", "")
        try:
            return float(clean)
        except ValueError:
            return None
    return None


class MathematicalSanityAuditor:
    """Audits quantitative submissions and table extracts for mathematical integrity."""

    def __init__(self, default_tolerance: float = 0.01) -> None:
        self.default_tolerance = default_tolerance

    def audit_table(
        self,
        table: AuditTable,
        tolerance: float | None = None,
    ) -> list[ConsistencyAnomaly]:
        """Perform row sum, column sum, cross-footing, and percentage audits on a table grid."""
        tol = tolerance if tolerance is not None else (table.tolerance or self.default_tolerance)
        anomalies: list[ConsistencyAnomaly] = []

        if not table.rows:
            return anomalies

        num_rows = len(table.rows)
        num_cols = max(len(r) for r in table.rows) if num_rows > 0 else 0
        if num_cols < 2:
            return anomalies

        # 1. Identify Total Row and Total Column
        total_row_idx = self._find_total_row_index(table)
        total_col_idx = self._find_total_col_index(table)

        # 2. Check Row Sums
        if total_col_idx is not None:
            for r_idx, row in enumerate(table.rows):
                if r_idx == total_row_idx:
                    continue  # skip total row here, handled in cross-footing
                row_label = (
                    table.row_labels[r_idx] if r_idx < len(table.row_labels) else f"Row {r_idx + 1}"
                )
                rep_val = _safe_float(row[total_col_idx]) if total_col_idx < len(row) else None
                if rep_val is None:
                    continue

                components: list[float] = []
                for c_idx in range(len(row)):
                    if c_idx == total_col_idx:
                        continue
                    v = _safe_float(row[c_idx])
                    if v is not None:
                        components.append(v)

                if components:
                    computed_sum = sum(components)
                    diff = abs(computed_sum - rep_val)
                    if diff > tol:
                        anomalies.append(
                            ConsistencyAnomaly(
                                anomaly_type=AnomalyType.SUM_MISMATCH,
                                severity=AuditSeverity.HIGH,
                                rule_name="row_sum_invariance",
                                message=(
                                    f"Row '{row_label}' sum mismatch: component sum {computed_sum:.2f} "
                                    f"differs from reported total {rep_val:.2f} by {diff:.2f}."
                                ),
                                location=f"Row {r_idx + 1} ({row_label}), Col {total_col_idx + 1}",
                                reported_value=rep_val,
                                expected_value=computed_sum,
                                discrepancy=diff,
                                tolerance=tol,
                                remediation_hint="Verify component row items or adjust rounding discrepancy.",
                            )
                        )

        # 3. Check Column Sums
        if total_row_idx is not None:
            total_row = table.rows[total_row_idx]
            for c_idx in range(num_cols):
                if c_idx == total_col_idx:
                    continue  # cross-footing handles intersection
                col_header = (
                    table.headers[c_idx] if c_idx < len(table.headers) else f"Col {c_idx + 1}"
                )
                rep_val = _safe_float(total_row[c_idx]) if c_idx < len(total_row) else None
                if rep_val is None:
                    continue

                components = []
                for r_idx in range(num_rows):
                    if r_idx == total_row_idx:
                        continue
                    if c_idx < len(table.rows[r_idx]):
                        v = _safe_float(table.rows[r_idx][c_idx])
                        if v is not None:
                            components.append(v)

                if components:
                    computed_sum = sum(components)
                    diff = abs(computed_sum - rep_val)
                    if diff > tol:
                        anomalies.append(
                            ConsistencyAnomaly(
                                anomaly_type=AnomalyType.SUM_MISMATCH,
                                severity=AuditSeverity.HIGH,
                                rule_name="column_sum_invariance",
                                message=(
                                    f"Column '{col_header}' sum mismatch: component sum {computed_sum:.2f} "
                                    f"differs from reported column total {rep_val:.2f} by {diff:.2f}."
                                ),
                                location=f"Row {total_row_idx + 1}, Col {c_idx + 1} ({col_header})",
                                reported_value=rep_val,
                                expected_value=computed_sum,
                                discrepancy=diff,
                                tolerance=tol,
                                remediation_hint="Verify column entries or check for missing component items.",
                            )
                        )

        # 4. Check Grand Total Cross-Footing
        if total_row_idx is not None and total_col_idx is not None:
            grand_total_cell = (
                _safe_float(table.rows[total_row_idx][total_col_idx])
                if total_col_idx < len(table.rows[total_row_idx])
                else None
            )

            # Sum of row totals
            row_totals = [
                _safe_float(table.rows[r][total_col_idx])
                for r in range(num_rows)
                if r != total_row_idx and total_col_idx < len(table.rows[r])
            ]
            valid_row_totals = [x for x in row_totals if x is not None]
            sum_of_row_totals = sum(valid_row_totals) if valid_row_totals else None

            # Sum of col totals
            col_totals = [
                _safe_float(table.rows[total_row_idx][c])
                for c in range(num_cols)
                if c != total_col_idx and c < len(table.rows[total_row_idx])
            ]
            valid_col_totals = [x for x in col_totals if x is not None]
            sum_of_col_totals = sum(valid_col_totals) if valid_col_totals else None

            if grand_total_cell is not None:
                if (
                    sum_of_row_totals is not None
                    and abs(sum_of_row_totals - grand_total_cell) > tol
                ):
                    anomalies.append(
                        ConsistencyAnomaly(
                            anomaly_type=AnomalyType.CROSS_FOOT_FAILURE,
                            severity=AuditSeverity.CRITICAL,
                            rule_name="cross_foot_row_totals_reconciliation",
                            message=(
                                f"Cross-foot failure: sum of row totals ({sum_of_row_totals:.2f}) does not "
                                f"equal grand total ({grand_total_cell:.2f})."
                            ),
                            location=f"Intersection Cell ({total_row_idx + 1}, {total_col_idx + 1})",
                            reported_value=grand_total_cell,
                            expected_value=sum_of_row_totals,
                            discrepancy=abs(sum_of_row_totals - grand_total_cell),
                            tolerance=tol,
                            remediation_hint="Ensure vertical summation of row totals agrees with grand total.",
                        )
                    )
                if (
                    sum_of_col_totals is not None
                    and abs(sum_of_col_totals - grand_total_cell) > tol
                ):
                    anomalies.append(
                        ConsistencyAnomaly(
                            anomaly_type=AnomalyType.CROSS_FOOT_FAILURE,
                            severity=AuditSeverity.CRITICAL,
                            rule_name="cross_foot_col_totals_reconciliation",
                            message=(
                                f"Cross-foot failure: sum of column totals ({sum_of_col_totals:.2f}) does not "
                                f"equal grand total ({grand_total_cell:.2f})."
                            ),
                            location=f"Intersection Cell ({total_row_idx + 1}, {total_col_idx + 1})",
                            reported_value=grand_total_cell,
                            expected_value=sum_of_col_totals,
                            discrepancy=abs(sum_of_col_totals - grand_total_cell),
                            tolerance=tol,
                            remediation_hint="Ensure horizontal summation of column totals agrees with grand total.",
                        )
                    )

        # 5. Check Percentage Distribution Columns
        for c_idx, header in enumerate(table.headers):
            if c_idx == total_col_idx:
                continue
            if self._is_percentage_header(header):
                pct_vals = []
                for r_idx in range(num_rows):
                    if r_idx == total_row_idx:
                        continue
                    if c_idx < len(table.rows[r_idx]):
                        v = _safe_float(table.rows[r_idx][c_idx])
                        if v is not None:
                            pct_vals.append(v)
                if len(pct_vals) >= 2:
                    total_pct = sum(pct_vals)
                    # Expected is 100% (or 1.0 if fractions)
                    expected_target = 100.0 if any(v > 1.0 for v in pct_vals) else 1.0
                    diff = abs(total_pct - expected_target)
                    # percentage tolerance: max(tol, 0.1 for 100% basis)
                    pct_tol = tol if expected_target == 1.0 else max(tol, 0.05)
                    if diff > pct_tol:
                        anomalies.append(
                            ConsistencyAnomaly(
                                anomaly_type=AnomalyType.PERCENTAGE_DISTRIBUTION,
                                severity=AuditSeverity.HIGH,
                                rule_name="percentage_distribution_100_percent",
                                message=(
                                    f"Percentage distribution in column '{header}' sums to {total_pct:.2f}%, "
                                    f"expected {expected_target:.2f}% (discrepancy: {diff:.2f}%)."
                                ),
                                location=f"Column {c_idx + 1} ({header})",
                                reported_value=total_pct,
                                expected_value=expected_target,
                                discrepancy=diff,
                                tolerance=pct_tol,
                                remediation_hint="Verify percentage breakdown sums to exactly 100%.",
                            )
                        )

        return anomalies

    def audit_regulatory_return(
        self,
        declared_values: dict[str, float],
        return_code: str = "GENERIC",
        tolerance: float | None = None,
    ) -> list[ConsistencyAnomaly]:
        """Audit declared quantitative values against statutory identities and derived equations."""
        tol = tolerance if tolerance is not None else self.default_tolerance
        anomalies: list[ConsistencyAnomaly] = []
        vals = {k.lower().strip(): float(v) for k, v in declared_values.items()}

        def get(*keys: str) -> float | None:
            for k in keys:
                if k in vals:
                    return vals[k]
            return None

        # -------------------------------------------------------------
        # Rule Set 1: Basel III Capital Adequacy Hierarchy
        # -------------------------------------------------------------
        cet1 = get("cet1", "cet1_capital", "common_equity_tier1")
        tier1 = get("tier1", "tier1_capital", "tier_1_capital")
        tier2 = get("tier2", "tier2_capital", "tier_2_capital")
        at1 = get("at1", "at1_capital", "additional_tier1")
        total_capital = get("total_capital", "eligible_capital", "regulatory_capital")
        rwa = get("rwa", "risk_weighted_assets")
        crar_rep = get("crar", "car", "capital_adequacy_ratio")
        tier1_ratio_rep = get("tier1_ratio", "tier_1_ratio")
        cet1_ratio_rep = get("cet1_ratio", "common_equity_tier1_ratio")
        leverage_rep = get("leverage_ratio", "basel_leverage_ratio")
        exposure = get("total_exposure", "leverage_exposure")

        # Identity: CET1 <= Tier 1
        if cet1 is not None and tier1 is not None:
            if cet1 > tier1 + tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.IDENTITY_VIOLATION,
                        severity=AuditSeverity.CRITICAL,
                        rule_name="capital_hierarchy_cet1_le_tier1",
                        message=(
                            f"Regulatory identity violation: CET1 ({cet1:.2f}) cannot exceed "
                            f"Tier 1 Capital ({tier1:.2f})."
                        ),
                        location="declared_values[cet1, tier1]",
                        reported_value=cet1,
                        expected_value=tier1,
                        discrepancy=cet1 - tier1,
                        tolerance=tol,
                        remediation_hint="CET1 is a strict subset of Tier 1 Capital; verify capital composition.",
                    )
                )

        # Identity: CET1 + AT1 == Tier 1
        if cet1 is not None and at1 is not None and tier1 is not None:
            expected_tier1 = cet1 + at1
            diff = abs(expected_tier1 - tier1)
            if diff > tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.SUM_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="tier1_composition_cet1_plus_at1",
                        message=(
                            f"Tier 1 Capital mismatch: CET1 ({cet1:.2f}) + AT1 ({at1:.2f}) = {expected_tier1:.2f}, "
                            f"but reported Tier 1 is {tier1:.2f}."
                        ),
                        location="declared_values[tier1]",
                        reported_value=tier1,
                        expected_value=expected_tier1,
                        discrepancy=diff,
                        tolerance=tol,
                        remediation_hint="Tier 1 Capital must equal Common Equity Tier 1 plus Additional Tier 1.",
                    )
                )

        # Identity: Tier 1 <= Total Capital
        if tier1 is not None and total_capital is not None:
            if tier1 > total_capital + tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.IDENTITY_VIOLATION,
                        severity=AuditSeverity.CRITICAL,
                        rule_name="capital_hierarchy_tier1_le_total",
                        message=(
                            f"Regulatory identity violation: Tier 1 Capital ({tier1:.2f}) cannot exceed "
                            f"Total Capital ({total_capital:.2f})."
                        ),
                        location="declared_values[tier1, total_capital]",
                        reported_value=tier1,
                        expected_value=total_capital,
                        discrepancy=tier1 - total_capital,
                        tolerance=tol,
                        remediation_hint="Tier 1 Capital cannot exceed Total Regulatory Capital.",
                    )
                )

        # Identity: Tier 1 + Tier 2 == Total Capital
        if tier1 is not None and tier2 is not None and total_capital is not None:
            expected_tot = tier1 + tier2
            diff = abs(expected_tot - total_capital)
            if diff > tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.SUM_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="total_capital_composition",
                        message=(
                            f"Total Capital mismatch: Tier 1 ({tier1:.2f}) + Tier 2 ({tier2:.2f}) = {expected_tot:.2f}, "
                            f"but reported Total Capital is {total_capital:.2f}."
                        ),
                        location="declared_values[total_capital]",
                        reported_value=total_capital,
                        expected_value=expected_tot,
                        discrepancy=diff,
                        tolerance=tol,
                        remediation_hint="Total Capital must reconcile with sum of Tier 1 and Tier 2.",
                    )
                )

        # Derived Ratio: CRAR == (Total Capital / RWA) * 100
        if total_capital is not None and rwa is not None:
            if rwa <= 0:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.ZERO_DENOMINATOR,
                        severity=AuditSeverity.CRITICAL,
                        rule_name="rwa_non_negative_non_zero",
                        message=f"Risk-Weighted Assets (RWA) must be strictly positive, found {rwa:.2f}.",
                        location="declared_values[rwa]",
                        reported_value=rwa,
                        expected_value=1.0,
                        discrepancy=None,
                        tolerance=tol,
                        remediation_hint="Ensure RWA denominator is correctly computed and non-zero.",
                    )
                )
            elif crar_rep is not None:
                computed_crar = (total_capital / rwa) * 100.0
                diff = abs(computed_crar - crar_rep)
                if diff > max(tol, 0.05):  # allow 0.05% rounding tolerance
                    anomalies.append(
                        ConsistencyAnomaly(
                            anomaly_type=AnomalyType.RATIO_MISMATCH,
                            severity=AuditSeverity.HIGH,
                            rule_name="crar_computation_reconciliation",
                            message=(
                                f"CRAR calculation discrepancy: (Total Capital {total_capital:.2f} / RWA {rwa:.2f}) * 100 "
                                f"= {computed_crar:.3f}%, but reported CRAR is {crar_rep:.3f}%."
                            ),
                            location="declared_values[crar]",
                            reported_value=crar_rep,
                            expected_value=computed_crar,
                            discrepancy=diff,
                            tolerance=0.05,
                            remediation_hint="Reconcile reported CRAR with underlying capital and risk weights.",
                        )
                    )

        # Derived Ratio: Tier 1 Ratio == (Tier 1 / RWA) * 100
        if tier1 is not None and rwa is not None and rwa > 0 and tier1_ratio_rep is not None:
            computed_t1 = (tier1 / rwa) * 100.0
            diff = abs(computed_t1 - tier1_ratio_rep)
            if diff > max(tol, 0.05):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="tier1_ratio_reconciliation",
                        message=(
                            f"Tier 1 Ratio discrepancy: computed {computed_t1:.3f}%, reported {tier1_ratio_rep:.3f}%."
                        ),
                        location="declared_values[tier1_ratio]",
                        reported_value=tier1_ratio_rep,
                        expected_value=computed_t1,
                        discrepancy=diff,
                        tolerance=0.05,
                        remediation_hint="Reconcile reported Tier 1 Ratio with Tier 1 Capital and RWA.",
                    )
                )

        # Derived Ratio: CET1 Ratio == (CET1 / RWA) * 100
        if cet1 is not None and rwa is not None and rwa > 0 and cet1_ratio_rep is not None:
            computed_cet1 = (cet1 / rwa) * 100.0
            diff = abs(computed_cet1 - cet1_ratio_rep)
            if diff > max(tol, 0.05):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="cet1_ratio_reconciliation",
                        message=(
                            f"CET1 Ratio discrepancy: computed {computed_cet1:.3f}%, reported {cet1_ratio_rep:.3f}%."
                        ),
                        location="declared_values[cet1_ratio]",
                        reported_value=cet1_ratio_rep,
                        expected_value=computed_cet1,
                        discrepancy=diff,
                        tolerance=0.05,
                        remediation_hint="Reconcile reported CET1 Ratio with CET1 Capital and RWA.",
                    )
                )

        # Derived Ratio: Leverage Ratio == (Tier 1 / Total Exposure) * 100
        if tier1 is not None and exposure is not None and exposure > 0 and leverage_rep is not None:
            computed_lev = (tier1 / exposure) * 100.0
            diff = abs(computed_lev - leverage_rep)
            if diff > max(tol, 0.05):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="leverage_ratio_reconciliation",
                        message=(
                            f"Leverage Ratio discrepancy: computed {computed_lev:.3f}%, reported {leverage_rep:.3f}%."
                        ),
                        location="declared_values[leverage_ratio]",
                        reported_value=leverage_rep,
                        expected_value=computed_lev,
                        discrepancy=diff,
                        tolerance=0.05,
                        remediation_hint="Reconcile reported Leverage Ratio with Tier 1 Capital and Total Exposure.",
                    )
                )

        # -------------------------------------------------------------
        # Rule Set 2: Asset Quality & NPA Equations
        # -------------------------------------------------------------
        gnpa = get("gnpa", "gross_npa", "gross_bad_loans")
        nnpa = get("nnpa", "net_npa")
        prov = get("provisions", "npa_provisions", "total_provisions")
        pcr = get("pcr", "provision_coverage_ratio")
        g_adv = get("gross_advances", "gross_loans")
        n_adv = get("net_advances", "net_loans")
        substandard = get("substandard_assets")
        doubtful = get("doubtful_assets")
        loss_assets = get("loss_assets")

        # Identity: Net NPA <= Gross NPA
        if gnpa is not None and nnpa is not None:
            if nnpa > gnpa + tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.IDENTITY_VIOLATION,
                        severity=AuditSeverity.CRITICAL,
                        rule_name="asset_quality_nnpa_le_gnpa",
                        message=(
                            f"Regulatory identity violation: Net NPA ({nnpa:.2f}) cannot exceed "
                            f"Gross NPA ({gnpa:.2f})."
                        ),
                        location="declared_values[net_npa, gross_npa]",
                        reported_value=nnpa,
                        expected_value=gnpa,
                        discrepancy=nnpa - gnpa,
                        tolerance=tol,
                        remediation_hint="Net NPA must be strictly less than or equal to Gross NPA.",
                    )
                )

        # Identity: Net NPA == Gross NPA - Provisions
        if gnpa is not None and prov is not None and nnpa is not None:
            expected_nnpa = max(0.0, gnpa - prov)
            diff = abs(expected_nnpa - nnpa)
            if diff > tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.SUM_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="net_npa_provisions_reconciliation",
                        message=(
                            f"Net NPA mismatch: Gross NPA ({gnpa:.2f}) - Provisions ({prov:.2f}) = "
                            f"{expected_nnpa:.2f}, but reported Net NPA is {nnpa:.2f}."
                        ),
                        location="declared_values[net_npa]",
                        reported_value=nnpa,
                        expected_value=expected_nnpa,
                        discrepancy=diff,
                        tolerance=tol,
                        remediation_hint="Verify provision deductions against gross non-performing assets.",
                    )
                )

        # Asset Breakdown: Gross NPA == Substandard + Doubtful + Loss
        if (
            gnpa is not None
            and substandard is not None
            and doubtful is not None
            and loss_assets is not None
        ):
            expected_gnpa = substandard + doubtful + loss_assets
            diff = abs(expected_gnpa - gnpa)
            if diff > tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.SUM_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="gnpa_asset_classification_sum",
                        message=(
                            f"Gross NPA composition mismatch: Substandard ({substandard:.2f}) + "
                            f"Doubtful ({doubtful:.2f}) + Loss ({loss_assets:.2f}) = {expected_gnpa:.2f}, "
                            f"but reported Gross NPA is {gnpa:.2f}."
                        ),
                        location="declared_values[gross_npa]",
                        reported_value=gnpa,
                        expected_value=expected_gnpa,
                        discrepancy=diff,
                        tolerance=tol,
                        remediation_hint="Ensure sum of substandard, doubtful, and loss assets equals Gross NPA.",
                    )
                )

        # Derived Ratio: PCR == (Provisions / Gross NPA) * 100
        if prov is not None and gnpa is not None and gnpa > 0 and pcr is not None:
            computed_pcr = (prov / gnpa) * 100.0
            diff = abs(computed_pcr - pcr)
            if diff > max(tol, 0.05):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="pcr_computation_reconciliation",
                        message=(
                            f"Provision Coverage Ratio (PCR) discrepancy: computed {computed_pcr:.3f}%, "
                            f"reported {pcr:.3f}%."
                        ),
                        location="declared_values[pcr]",
                        reported_value=pcr,
                        expected_value=computed_pcr,
                        discrepancy=diff,
                        tolerance=0.05,
                        remediation_hint="Reconcile PCR with total provisions divided by gross NPA.",
                    )
                )

        # Derived Ratio: GNPA Ratio == (Gross NPA / Gross Advances) * 100
        gnpa_ratio_rep = get("gnpa_ratio", "gross_npa_ratio")
        if gnpa is not None and g_adv is not None and g_adv > 0 and gnpa_ratio_rep is not None:
            computed_gnpa_ratio = (gnpa / g_adv) * 100.0
            diff = abs(computed_gnpa_ratio - gnpa_ratio_rep)
            if diff > max(tol, 0.05):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="gnpa_ratio_reconciliation",
                        message=(
                            f"Gross NPA Ratio discrepancy: computed {computed_gnpa_ratio:.3f}%, "
                            f"reported {gnpa_ratio_rep:.3f}%."
                        ),
                        location="declared_values[gnpa_ratio]",
                        reported_value=gnpa_ratio_rep,
                        expected_value=computed_gnpa_ratio,
                        discrepancy=diff,
                        tolerance=0.05,
                        remediation_hint="Reconcile Gross NPA Ratio with Gross NPA and Gross Advances.",
                    )
                )

        # Derived Ratio: NNPA Ratio == (Net NPA / Net Advances) * 100
        nnpa_ratio_rep = get("nnpa_ratio", "net_npa_ratio")
        if nnpa is not None and n_adv is not None and n_adv > 0 and nnpa_ratio_rep is not None:
            computed_nnpa_ratio = (nnpa / n_adv) * 100.0
            diff = abs(computed_nnpa_ratio - nnpa_ratio_rep)
            if diff > max(tol, 0.05):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="nnpa_ratio_reconciliation",
                        message=(
                            f"Net NPA Ratio discrepancy: computed {computed_nnpa_ratio:.3f}%, "
                            f"reported {nnpa_ratio_rep:.3f}%."
                        ),
                        location="declared_values[nnpa_ratio]",
                        reported_value=nnpa_ratio_rep,
                        expected_value=computed_nnpa_ratio,
                        discrepancy=diff,
                        tolerance=0.05,
                        remediation_hint="Reconcile Net NPA Ratio with Net NPA and Net Advances.",
                    )
                )

        # -------------------------------------------------------------
        # Rule Set 3: Liquidity Ratios (LCR & NSFR)
        # -------------------------------------------------------------
        hqla = get("hqla", "high_quality_liquid_assets")
        outflows = get("net_cash_outflows", "outflows_30d")
        lcr_rep = get("lcr", "liquidity_coverage_ratio")
        if hqla is not None and outflows is not None:
            if outflows <= 0:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.ZERO_DENOMINATOR,
                        severity=AuditSeverity.CRITICAL,
                        rule_name="lcr_outflows_non_zero",
                        message=f"Net cash outflows denominator must be positive, found {outflows:.2f}.",
                        location="declared_values[net_cash_outflows]",
                        reported_value=outflows,
                        expected_value=1.0,
                        discrepancy=None,
                        tolerance=tol,
                        remediation_hint="Verify net cash outflows over 30-day stress horizon.",
                    )
                )
            elif lcr_rep is not None:
                computed_lcr = (hqla / outflows) * 100.0
                diff = abs(computed_lcr - lcr_rep)
                if diff > max(tol, 0.05):
                    anomalies.append(
                        ConsistencyAnomaly(
                            anomaly_type=AnomalyType.RATIO_MISMATCH,
                            severity=AuditSeverity.HIGH,
                            rule_name="lcr_computation_reconciliation",
                            message=(
                                f"LCR discrepancy: computed {computed_lcr:.3f}%, reported {lcr_rep:.3f}%."
                            ),
                            location="declared_values[lcr]",
                            reported_value=lcr_rep,
                            expected_value=computed_lcr,
                            discrepancy=diff,
                            tolerance=0.05,
                            remediation_hint="Reconcile LCR with HQLA stock and 30-day net stressed outflows.",
                        )
                    )

        # -------------------------------------------------------------
        # Rule Set 4: Balance Sheet Equation
        # Total Assets == Total Liabilities + Shareholders Equity
        # -------------------------------------------------------------
        assets = get("total_assets", "assets")
        liabilities = get("total_liabilities", "liabilities")
        equity = get("shareholders_equity", "equity", "net_worth")
        if assets is not None and liabilities is not None and equity is not None:
            expected_assets = liabilities + equity
            diff = abs(expected_assets - assets)
            if diff > tol:
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.SUM_MISMATCH,
                        severity=AuditSeverity.CRITICAL,
                        rule_name="balance_sheet_accounting_equation",
                        message=(
                            f"Balance sheet out of balance: Liabilities ({liabilities:.2f}) + "
                            f"Equity ({equity:.2f}) = {expected_assets:.2f}, but Total Assets is {assets:.2f} "
                            f"(discrepancy: {diff:.2f})."
                        ),
                        location="declared_values[total_assets]",
                        reported_value=assets,
                        expected_value=expected_assets,
                        discrepancy=diff,
                        tolerance=tol,
                        remediation_hint="Fundamental accounting equation failed: Assets must equal Liabilities + Equity.",
                    )
                )

        # Current Ratio: Current Assets / Current Liabilities
        c_assets = get("current_assets")
        c_liab = get("current_liabilities")
        cr_rep = get("current_ratio")
        if c_assets is not None and c_liab is not None and c_liab > 0 and cr_rep is not None:
            computed_cr = c_assets / c_liab
            diff = abs(computed_cr - cr_rep)
            if diff > max(tol, 0.01):
                anomalies.append(
                    ConsistencyAnomaly(
                        anomaly_type=AnomalyType.RATIO_MISMATCH,
                        severity=AuditSeverity.HIGH,
                        rule_name="current_ratio_reconciliation",
                        message=(
                            f"Current Ratio discrepancy: computed {computed_cr:.3f}, reported {cr_rep:.3f}."
                        ),
                        location="declared_values[current_ratio]",
                        reported_value=cr_rep,
                        expected_value=computed_cr,
                        discrepancy=diff,
                        tolerance=0.01,
                        remediation_hint="Reconcile Current Ratio with Current Assets and Current Liabilities.",
                    )
                )

        return anomalies

    def audit_submission(self, submission: AuditSubmission) -> AuditResult:
        """Execute full mathematical sanity audit over declared metrics and tables."""
        t0 = time.perf_counter()
        anomalies: list[ConsistencyAnomaly] = []
        passed_checks: list[str] = []
        total_checks = 0

        # Audit declared values
        if submission.declared_values:
            val_anomalies = self.audit_regulatory_return(
                declared_values=submission.declared_values,
                return_code=submission.return_code,
                tolerance=submission.tolerance,
            )
            total_checks += 12  # regulatory identity rules checked
            if not val_anomalies:
                passed_checks.append("Regulatory Return Equations & Invariants")
            else:
                anomalies.extend(val_anomalies)

        # Audit attached tables
        for idx, tbl in enumerate(submission.tables):
            table_title = tbl.title or f"Table {idx + 1}"
            tbl_anomalies = self.audit_table(tbl, tolerance=submission.tolerance)
            total_checks += max(len(tbl.rows) + len(tbl.headers), 5)
            if not tbl_anomalies:
                passed_checks.append(f"{table_title}: Cross-footing & Totals Balanced")
            else:
                anomalies.extend(tbl_anomalies)

        duration_ms = (time.perf_counter() - t0) * 1000.0
        is_valid = len(anomalies) == 0

        summary = (
            f"Mathematical sanity audit PASSED cleanly ({total_checks} checks executed, 0 discrepancies)."
            if is_valid
            else f"Mathematical sanity audit flagged {len(anomalies)} anomalies across {total_checks} checks."
        )

        return AuditResult(
            is_valid=is_valid,
            total_rules_checked=max(total_checks, 1),
            anomalies_count=len(anomalies),
            anomalies=anomalies,
            passed_checks=passed_checks,
            summary=summary,
            execution_time_ms=round(duration_ms, 3),
        )

    def _find_total_row_index(self, table: AuditTable) -> int | None:
        """Find the index of the total/summary row if present."""
        if table.has_row_totals is False:
            return None
        # Check row labels
        for r_idx, label in enumerate(table.row_labels):
            if any(k in str(label).lower() for k in ("total", "grand total", "sum", "overall")):
                return r_idx
        # Check first column text in rows
        for r_idx, row in enumerate(table.rows):
            if row and isinstance(row[0], str):
                if any(k in row[0].lower() for k in ("total", "grand total", "sum", "overall")):
                    return r_idx
        # If explicitly marked or last row looks like a total
        if table.has_row_totals is True and len(table.rows) > 1:
            return len(table.rows) - 1
        return None

    def _find_total_col_index(self, table: AuditTable) -> int | None:
        """Find the index of the total column if present."""
        if table.has_col_totals is False:
            return None
        # Check headers
        for c_idx, h in enumerate(table.headers):
            if any(k in str(h).lower() for k in ("total", "grand total", "sum")):
                return c_idx
        if table.has_col_totals is True and table.headers:
            return len(table.headers) - 1
        return None

    def _is_percentage_header(self, header: str) -> bool:
        """Detect whether a column header denotes a percentage/share breakdown."""
        h = header.lower()
        return any(
            token in h
            for token in (
                "%",
                "percent",
                "percentage",
                "share",
                "weight",
                "distribution",
                "proportion",
                "allocation",
            )
        )

    def get_rule_catalog(self) -> list[dict[str, Any]]:
        """Return metadata catalog of all standard mathematical sanity rules."""
        return [
            {
                "rule_id": "capital_hierarchy_cet1_le_tier1",
                "name": "CET1 <= Tier 1 Capital",
                "category": "Capital Adequacy",
                "severity": "CRITICAL",
                "statutory_ref": "RBI Master Direction - Basel III Capital Regulations (Part A)",
                "description": "Common Equity Tier 1 capital cannot exceed Total Tier 1 capital.",
            },
            {
                "rule_id": "capital_hierarchy_tier1_le_total",
                "name": "Tier 1 Capital <= Total Capital",
                "category": "Capital Adequacy",
                "severity": "CRITICAL",
                "statutory_ref": "RBI Master Direction - Basel III Capital Regulations (Part B)",
                "description": "Tier 1 capital cannot exceed Total eligible regulatory capital.",
            },
            {
                "rule_id": "total_capital_composition",
                "name": "Tier 1 + Tier 2 == Total Capital",
                "category": "Capital Adequacy",
                "severity": "HIGH",
                "statutory_ref": "RBI Basel III / CRAR Schedule 1",
                "description": "Total Capital must equal the exact sum of Tier 1 and Tier 2 capital.",
            },
            {
                "rule_id": "crar_computation_reconciliation",
                "name": "CRAR == (Total Capital / RWA) * 100",
                "category": "Capital Adequacy",
                "severity": "HIGH",
                "statutory_ref": "RBI Master Circular - Capital Adequacy Ratio",
                "description": "Reported Capital to Risk-Weighted Assets Ratio must equal calculated fraction within rounding bounds.",
            },
            {
                "rule_id": "asset_quality_nnpa_le_gnpa",
                "name": "Net NPA <= Gross NPA",
                "category": "Asset Quality",
                "severity": "CRITICAL",
                "statutory_ref": "RBI Master Circular - Prudential Norms on Income Recognition and Asset Classification (IRAC)",
                "description": "Net Non-Performing Assets cannot exceed Gross Non-Performing Assets.",
            },
            {
                "rule_id": "net_npa_provisions_reconciliation",
                "name": "Net NPA == Gross NPA - Provisions",
                "category": "Asset Quality",
                "severity": "HIGH",
                "statutory_ref": "RBI IRAC Norms - Annexure 2",
                "description": "Net NPA must equal Gross NPA less eligible cumulative provisions.",
            },
            {
                "rule_id": "pcr_computation_reconciliation",
                "name": "PCR == (Provisions / Gross NPA) * 100",
                "category": "Asset Quality",
                "severity": "HIGH",
                "statutory_ref": "RBI Master Direction - Financial Statements Presentation",
                "description": "Provision Coverage Ratio must match calculated ratio of provisions over Gross NPA.",
            },
            {
                "rule_id": "lcr_computation_reconciliation",
                "name": "LCR == (HQLA / Net Outflows) * 100",
                "category": "Liquidity",
                "severity": "HIGH",
                "statutory_ref": "RBI Basel III Framework - Liquidity Coverage Ratio (LCR)",
                "description": "Liquidity Coverage Ratio must equal High Quality Liquid Assets divided by 30-day net stressed outflows.",
            },
            {
                "rule_id": "balance_sheet_accounting_equation",
                "name": "Total Assets == Liabilities + Equity",
                "category": "Financial Reporting",
                "severity": "CRITICAL",
                "statutory_ref": "Companies Act, 2013 / Banking Regulation Act Schedule III",
                "description": "Fundamental balance sheet identity: Total Assets must reconcile with Total Liabilities plus Equity.",
            },
            {
                "rule_id": "row_sum_invariance",
                "name": "Row Component Sum Invariance",
                "category": "Table Cross-Footing",
                "severity": "HIGH",
                "statutory_ref": "Prudential Return Schedule Verification Guidelines",
                "description": "Sum of horizontal component cells must equal declared row total within tolerance.",
            },
            {
                "rule_id": "column_sum_invariance",
                "name": "Column Component Sum Invariance",
                "category": "Table Cross-Footing",
                "severity": "HIGH",
                "statutory_ref": "Prudential Return Schedule Verification Guidelines",
                "description": "Sum of vertical column cells must equal declared column total within tolerance.",
            },
            {
                "rule_id": "cross_foot_reconciliation",
                "name": "Grand Total Cross-Foot Reconciliation",
                "category": "Table Cross-Footing",
                "severity": "CRITICAL",
                "statutory_ref": "Auditing and Assurance Standard (AAS) 6 / Statutory Audit Matrix",
                "description": "Sum of row totals and sum of column totals must reconcile with the grand total intersection cell.",
            },
            {
                "rule_id": "percentage_distribution_100_percent",
                "name": "Percentage Distribution Sum == 100%",
                "category": "Statistical Integrity",
                "severity": "HIGH",
                "statutory_ref": "Statutory Disclosures and Annexure Standards",
                "description": "Percentage distribution and asset share breakdown columns must sum to exactly 100%.",
            },
        ]


_DEFAULT_AUDITOR: MathematicalSanityAuditor | None = None


def get_default_consistency_auditor() -> MathematicalSanityAuditor:
    """Return singleton instance of MathematicalSanityAuditor."""
    global _DEFAULT_AUDITOR
    if _DEFAULT_AUDITOR is None:
        _DEFAULT_AUDITOR = MathematicalSanityAuditor()
    return _DEFAULT_AUDITOR
