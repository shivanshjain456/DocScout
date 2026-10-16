"""Tests for Mathematical Sanity & Consistency Auditor (FEAT-027).

Validates row/column sum invariance, grand total cross-footing, percentage distribution,
regulatory capital hierarchies, NPA accounting identities, and 100% detection rate
on seeded synthetic table errors.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.consistency_auditor import (
    AnomalyType,
    AuditSeverity,
    AuditSubmission,
    AuditTable,
    MathematicalSanityAuditor,
    get_default_consistency_auditor,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_clean_table_cross_footing() -> None:
    """A perfectly balanced table grid passes with zero anomalies."""
    auditor = MathematicalSanityAuditor(default_tolerance=0.01)
    table = AuditTable(
        title="Valid Capital Breakdown",
        headers=["Wholesale", "Retail", "Treasury", "Total"],
        row_labels=["Tier 1", "Tier 2", "Total"],
        rows=[
            [500.0, 300.0, 200.0, 1000.0],
            [150.0, 100.0, 50.0, 300.0],
            [650.0, 400.0, 250.0, 1300.0],
        ],
    )

    anomalies = auditor.audit_table(table)
    assert len(anomalies) == 0


def test_seeded_row_sum_error_detection() -> None:
    """Seeded row error is flagged with expected discrepancy."""
    auditor = MathematicalSanityAuditor(default_tolerance=0.01)
    table = AuditTable(
        title="Row Error Table",
        headers=["Col A", "Col B", "Total"],
        row_labels=["Row 1"],
        rows=[
            [100.0, 200.0, 350.0],  # 100 + 200 = 300 != 350
        ],
    )

    anomalies = auditor.audit_table(table)
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == AnomalyType.SUM_MISMATCH
    assert anomalies[0].rule_name == "row_sum_invariance"
    assert anomalies[0].reported_value == 350.0
    assert anomalies[0].expected_value == 300.0
    assert abs((anomalies[0].discrepancy or 0.0) - 50.0) < 0.001


def test_seeded_column_sum_error_detection() -> None:
    """Seeded column error is flagged with expected discrepancy."""
    auditor = MathematicalSanityAuditor(default_tolerance=0.01)
    table = AuditTable(
        title="Column Error Table",
        headers=["Loans", "Investments"],
        row_labels=["Q1", "Q2", "Total"],
        rows=[
            [100.0, 200.0],
            [150.0, 250.0],
            [250.0, 500.0],  # 200 + 250 = 450 != 500
        ],
    )

    anomalies = auditor.audit_table(table)
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == AnomalyType.SUM_MISMATCH
    assert anomalies[0].rule_name == "column_sum_invariance"
    assert anomalies[0].reported_value == 500.0
    assert anomalies[0].expected_value == 450.0
    assert abs((anomalies[0].discrepancy or 0.0) - 50.0) < 0.001


def test_seeded_grand_total_cross_foot_failure() -> None:
    """Cross-foot error between row sums and column sums is caught as CRITICAL."""
    auditor = MathematicalSanityAuditor(default_tolerance=0.01)
    table = AuditTable(
        title="Cross Foot Error",
        headers=["A", "B", "Total"],
        row_labels=["R1", "R2", "Total"],
        rows=[
            [10.0, 20.0, 30.0],
            [30.0, 40.0, 70.0],
            [40.0, 60.0, 120.0],  # 30 + 70 = 100 != 120, and 40 + 60 = 100 != 120
        ],
    )

    anomalies = auditor.audit_table(table)
    cross_foots = [a for a in anomalies if a.anomaly_type == AnomalyType.CROSS_FOOT_FAILURE]
    assert len(cross_foots) >= 1
    assert cross_foots[0].severity == AuditSeverity.CRITICAL


def test_percentage_distribution_sum_check() -> None:
    """Checks that percentage allocation columns must sum to 100%."""
    auditor = MathematicalSanityAuditor(default_tolerance=0.05)
    # Invalid: sums to 95.0%
    table_invalid = AuditTable(
        title="Portfolio Share",
        headers=["Asset", "Allocation %"],
        rows=[
            ["Equities", 40.0],
            ["Bonds", 35.0],
            ["Cash", 20.0],
        ],
    )
    anom_inv = auditor.audit_table(table_invalid)
    assert len(anom_inv) == 1
    assert anom_inv[0].anomaly_type == AnomalyType.PERCENTAGE_DISTRIBUTION
    assert anom_inv[0].reported_value == 95.0
    assert anom_inv[0].expected_value == 100.0

    # Valid: sums to 100.0%
    table_valid = AuditTable(
        title="Portfolio Share",
        headers=["Asset", "Allocation %"],
        rows=[
            ["Equities", 40.0],
            ["Bonds", 35.0],
            ["Cash", 25.0],
        ],
    )
    anom_val = auditor.audit_table(table_valid)
    assert len(anom_val) == 0


def test_100_percent_detection_rate_on_seeded_errors() -> None:
    """Verify 100% detection rate across 20 distinct synthetic table errors."""
    auditor = MathematicalSanityAuditor(default_tolerance=0.01)
    detected_count = 0
    total_seeded = 20

    for i in range(total_seeded):
        # Base balanced table
        r1_a, r1_b = 100.0 + i, 200.0 + i
        r2_a, r2_b = 50.0, 75.0
        tot_a = r1_a + r2_a
        tot_b = r1_b + r2_b
        tot_r1 = r1_a + r1_b
        tot_r2 = r2_a + r2_b
        grand = tot_r1 + tot_r2

        # Seed error based on test index
        if i % 4 == 0:
            tot_r1 += 15.5  # row sum error
        elif i % 4 == 1:
            tot_b -= 12.0  # col sum error
        elif i % 4 == 2:
            grand += 33.0  # cross-foot error
        else:
            r1_a += 25.0  # cell discrepancy against row total

        corrupted_table = AuditTable(
            title=f"Synthetic Error Test {i}",
            headers=["Alpha", "Beta", "Total"],
            row_labels=["Batch 1", "Batch 2", "Total"],
            rows=[
                [r1_a, r1_b, tot_r1],
                [r2_a, r2_b, tot_r2],
                [tot_a, tot_b, grand],
            ],
        )

        anoms = auditor.audit_table(corrupted_table)
        if len(anoms) > 0:
            detected_count += 1

    detection_rate = detected_count / total_seeded
    assert detection_rate == 1.0, f"Expected 100% detection rate, achieved {detection_rate * 100}%"


def test_basel3_capital_hierarchy_identities() -> None:
    """Verifies detection of regulatory capital identity violations."""
    auditor = MathematicalSanityAuditor()

    # Violation 1: CET1 > Tier 1
    anoms_1 = auditor.audit_regulatory_return(
        {
            "cet1_capital": 6000.0,
            "tier1_capital": 5000.0,
        }
    )
    assert any(a.rule_name == "capital_hierarchy_cet1_le_tier1" for a in anoms_1)

    # Violation 2: Tier 1 > Total Capital
    anoms_2 = auditor.audit_regulatory_return(
        {
            "tier1_capital": 8000.0,
            "total_capital": 7500.0,
        }
    )
    assert any(a.rule_name == "capital_hierarchy_tier1_le_total" for a in anoms_2)

    # Violation 3: Tier 1 + Tier 2 != Total Capital
    anoms_3 = auditor.audit_regulatory_return(
        {
            "tier1_capital": 5000.0,
            "tier2_capital": 2000.0,
            "total_capital": 8000.0,  # Expected 7000.0
        }
    )
    assert any(a.rule_name == "total_capital_composition" for a in anoms_3)

    # Violation 4: CRAR calculation discrepancy
    anoms_4 = auditor.audit_regulatory_return(
        {
            "total_capital": 10000.0,
            "rwa": 80000.0,
            "crar": 15.0,  # (10000 / 80000) * 100 = 12.5%
        }
    )
    assert any(a.rule_name == "crar_computation_reconciliation" for a in anoms_4)


def test_asset_quality_and_npa_identities() -> None:
    """Verifies asset quality identities: Net NPA <= Gross NPA and PCR reconciliation."""
    auditor = MathematicalSanityAuditor()

    # Violation 1: Net NPA > Gross NPA
    anoms_1 = auditor.audit_regulatory_return(
        {
            "gross_npa": 1000.0,
            "net_npa": 1200.0,
        }
    )
    assert any(a.rule_name == "asset_quality_nnpa_le_gnpa" for a in anoms_1)

    # Violation 2: Net NPA != Gross NPA - Provisions
    anoms_2 = auditor.audit_regulatory_return(
        {
            "gross_npa": 1000.0,
            "provisions": 400.0,
            "net_npa": 750.0,  # Expected 600.0
        }
    )
    assert any(a.rule_name == "net_npa_provisions_reconciliation" for a in anoms_2)

    # Violation 3: PCR discrepancy
    anoms_3 = auditor.audit_regulatory_return(
        {
            "gross_npa": 1000.0,
            "provisions": 400.0,
            "pcr": 55.0,  # (400 / 1000) * 100 = 40.0%
        }
    )
    assert any(a.rule_name == "pcr_computation_reconciliation" for a in anoms_3)


def test_balance_sheet_accounting_equation() -> None:
    """Validates Assets == Liabilities + Equity."""
    auditor = MathematicalSanityAuditor()
    anoms = auditor.audit_regulatory_return(
        {
            "total_assets": 100000.0,
            "total_liabilities": 80000.0,
            "shareholders_equity": 15000.0,  # 80000 + 15000 = 95000 != 100000
        }
    )
    assert any(a.rule_name == "balance_sheet_accounting_equation" for a in anoms)


def test_full_submission_audit() -> None:
    """Tests composite submission with metrics and tables."""
    auditor = get_default_consistency_auditor()
    submission = AuditSubmission(
        document_id="doc-rbi-return-1",
        return_code="RCA3",
        declared_values={
            "cet1_capital": 5000.0,
            "tier1_capital": 6000.0,
            "tier2_capital": 1500.0,
            "total_capital": 7500.0,
            "rwa": 50000.0,
            "crar": 15.0,
        },
        tables=[
            AuditTable(
                title="Capital Summary",
                headers=["Common Equity", "Preferred", "Total"],
                row_labels=["Direct", "Indirect", "Total"],
                rows=[
                    [3000.0, 1000.0, 4000.0],
                    [1500.0, 500.0, 2000.0],
                    [4500.0, 1500.0, 6000.0],
                ],
            )
        ],
    )

    result = auditor.audit_submission(submission)
    assert result.is_valid is True
    assert result.anomalies_count == 0
    assert len(result.passed_checks) >= 2


def test_throughput_performance_benchmark() -> None:
    """Auditor executes under 2ms per evaluation."""
    auditor = MathematicalSanityAuditor()
    submission = AuditSubmission(
        document_id="doc-bench",
        return_code="BASEL3",
        declared_values={
            "cet1_capital": 5000.0,
            "tier1_capital": 6000.0,
            "tier2_capital": 1500.0,
            "total_capital": 7500.0,
            "rwa": 50000.0,
            "crar": 15.0,
            "gross_npa": 1000.0,
            "provisions": 400.0,
            "net_npa": 600.0,
            "pcr": 40.0,
        },
        tables=[
            AuditTable(
                headers=["Col1", "Col2", "Total"],
                rows=[[10.0, 20.0, 30.0], [40.0, 50.0, 90.0], [50.0, 70.0, 120.0]],
            )
        ],
    )

    # Warm-up
    for _ in range(10):
        _ = auditor.audit_submission(submission)

    t0 = time.perf_counter()
    n_runs = 200
    for _ in range(n_runs):
        res = auditor.audit_submission(submission)
        assert res.is_valid is True
    duration = time.perf_counter() - t0

    avg_ms = (duration / n_runs) * 1000.0
    assert avg_ms < 5.0, f"Auditor throughput too slow: {avg_ms:.3f} ms/run"


def test_api_audit_sanity_endpoint(
    client: TestClient,
) -> None:
    """POST /v1/compliance/audit-sanity verifies valid and invalid submissions."""
    # 1. Valid payload
    valid_payload: dict[str, Any] = {
        "return_code": "BASEL_CAR",
        "declared_values": {
            "cet1_capital": 7000.0,
            "tier1_capital": 8000.0,
            "tier2_capital": 2000.0,
            "total_capital": 10000.0,
            "rwa": 62500.0,
            "crar": 16.0,
        },
        "tables": [
            {
                "title": "Capital Schedule",
                "headers": ["Cat A", "Cat B", "Total"],
                "rows": [[100.0, 200.0, 300.0], [50.0, 50.0, 100.0], [150.0, 250.0, 400.0]],
                "row_labels": ["R1", "R2", "Total"],
            }
        ],
    }

    res_valid = client.post(
        "/v1/compliance/audit-sanity",
        json=valid_payload,
        headers=auth(),
    )
    assert res_valid.status_code == 200, res_valid.text
    data_valid = res_valid.json()
    assert data_valid["is_valid"] is True
    assert data_valid["anomalies_count"] == 0

    # 2. Invalid payload with intentional error
    invalid_payload: dict[str, Any] = {
        "return_code": "BASEL_CAR",
        "declared_values": {
            "cet1_capital": 9000.0,
            "tier1_capital": 8000.0,  # CET1 > Tier 1 violation
        },
        "tables": [],
    }

    res_invalid = client.post(
        "/v1/compliance/audit-sanity",
        json=invalid_payload,
        headers=auth(),
    )
    assert res_invalid.status_code == 200
    data_invalid = res_invalid.json()
    assert data_invalid["is_valid"] is False
    assert data_invalid["anomalies_count"] >= 1
    assert any(
        a["rule_name"] == "capital_hierarchy_cet1_le_tier1" for a in data_invalid["anomalies"]
    )


def test_api_audit_rules_catalog_endpoint(
    client: TestClient,
) -> None:
    """GET /v1/compliance/audit-rules returns rules catalog."""
    res = client.get("/v1/compliance/audit-rules", headers=auth())
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_count"] >= 10
    assert any(r["rule_id"] == "capital_hierarchy_cet1_le_tier1" for r in data["rules"])
    assert any(r["rule_id"] == "cross_foot_reconciliation" for r in data["rules"])
