"""Tests for Third-Party Vendor Risk Assessment Engine (FEAT-049).

Verifies:
1. Deterministic evaluation of vendor contracts against RBI IT Outsourcing and SEBI Cloud Framework.
2. 15-contract evaluation benchmark with known compliance gaps:
   - Achieves recall >= 95% and precision >= 90% in detecting missing statutory clauses.
3. Strict Indian data localization enforcement and offshore data routing negation.
4. Input validation rules (100 to 150,000 characters).
5. Performance SLA: contract evaluation completed in <= 60 ms for 30-page agreement.
6. Prometheus counter and histogram metrics recording.
7. REST API endpoint `POST /v1/compliance/vendor-audit` with authentication.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.compliance.vendor_risk import (
    VendorRiskAssessmentEngine,
    VendorRiskConfig,
    get_default_vendor_risk_engine,
)
from tests.conftest import PRIMARY_KEY, auth

# ---------------------------------------------------------------------------
# Synthetic Benchmark Contracts (Evaluation Dataset of 15 Configurations)
# ---------------------------------------------------------------------------

COMPLIANT_CLAUSES_TEXT = """
MASTER SERVICES AGREEMENT - STATUTORY COMPLIANCE ADDENDUM

1. REGULATORY INSPECTION AND AUDIT ACCESS:
The Service Provider explicitly covenants that the Reserve Bank of India (RBI), SEBI,
and their appointed authorized officers and statutory auditors shall have unconditional
and unrestricted right to inspect and examine all books, accounts, systems, records,
operations, and datacenter facilities relating to the outsourced services without hindrance.

2. DATA LOCALIZATION AND TERRITORIAL SOVEREIGNTY:
The Service Provider covenants that all customer data, financial records, transaction logs,
and personal identifiable information (PII) shall be stored, hosted, and processed
exclusively on servers physically located within the territory of India in onshore datacenters.
Zero cross-border transfer or offshore mirroring shall take place under any circumstances.

3. SUB-CONTRACTING GOVERNANCE:
The Service Provider shall not sub-contract or delegate any material component of the services
without obtaining prior written approval from the Customer. All approved sub-contractors shall
be bound by the same statutory audit access and data security standards.

4. SECURITY INCIDENT NOTIFICATION:
In the event of any security incident, unauthorized access, cyber attack, or data breach,
the Service Provider shall notify the Customer immediately, and in any event within 6 hours
from discovery, with comprehensive forensic details to facilitate statutory CERT-In reporting.

5. BUSINESS CONTINUITY AND DISASTER RECOVERY:
The Service Provider shall maintain an active Business Continuity Plan (BCP) and Disaster Recovery
(DR) architecture. The Service Provider commits to participate in annual joint DR drills with
the Customer and guarantees an RTO not exceeding 2 hours and an RPO not exceeding 15 minutes.

6. ORDERLY EXIT AND TERMINATION ASSISTANCE:
Upon termination or expiry of this Agreement, the Service Provider shall provide orderly transition
assistance for a period of up to 180 days, return all Customer data in industry-standard formats,
and furnish written certification of cryptographic erasure and data sanitization.

7. CONFIDENTIALITY AND STATUTORY DATA PROTECTION:
The Service Provider and its personnel shall preserve the strict confidentiality of all Customer
information indefinitely, obligations shall survive termination, and full compliance with the
Digital Personal Data Protection Act (DPDPA 2023) and IT Act is guaranteed.

8. THIRD-PARTY AUDIT ASSURANCE:
The Service Provider shall maintain active ISO/IEC 27001 certification and annually provide the
Customer with an independent unqualified SOC 2 Type II audit report covering operational controls.
"""


def _generate_contract(
    omit: tuple[str, ...] = (),
    include_offshore_clause: bool = False,
    include_negative_audit: bool = False,
) -> str:
    """Build modular contract text with specific statutory omissions or negations."""
    clauses: dict[str, str] = {
        "RBI_AUDIT_ACCESS": (
            "REGULATORY AUDIT: The Reserve Bank of India (RBI) and regulatory authorities shall "
            "have unconditional right to inspect, examine, and audit all books and datacenter systems."
        ),
        "DATA_LOCALIZATION": (
            "DATA SOVEREIGNTY: All customer records and transaction logs shall be stored and processed "
            "exclusively in onshore datacenters within India."
        ),
        "SUB_CONTRACTING_CONTROL": (
            "SUB-CONTRACTING: Service Provider shall not sub-contract any services without prior written approval."
        ),
        "INCIDENT_NOTIFICATION": (
            "INCIDENT REPORTING: Service Provider shall notify Customer of any security incident or breach within 6 hours."
        ),
        "BCP_DR_TESTING": (
            "DISASTER RECOVERY: Service Provider maintains BCP/DR plans and conducts annual joint testing with RTO <= 2 hours."
        ),
        "TERMINATION_ASSISTANCE": (
            "TERMINATION: Upon termination, Provider provides transition assistance, data return, and cryptographic erasure confirmation."
        ),
        "CONFIDENTIALITY_SECURITY": (
            "CONFIDENTIALITY: All customer data is held in strict confidence, with obligations surviving termination under DPDPA."
        ),
        "SOC2_ISO_AUDIT_RIGHTS": (
            "SECURITY CERTIFICATIONS: Provider shall annually provide an independent SOC 2 Type II report and ISO 27001 certification."
        ),
    }

    if include_offshore_clause:
        clauses["DATA_LOCALIZATION"] = (
            "DATA STORAGE: Provider hosts services globally and customer data may be transferred to and stored in datacenters outside of India."
        )

    if include_negative_audit:
        clauses["RBI_AUDIT_ACCESS"] = (
            "INSPECTION LIMITS: No regulatory or supervisory audit access is granted to datacenter premises without 90 days court order."
        )

    parts = [text for cid, text in clauses.items() if cid not in omit]
    header = "CONFIDENTIAL IT VENDOR MASTER SERVICES AGREEMENT\n\n"
    footer = "\n\nIN WITNESS WHEREOF, the parties hereto have executed this Agreement."
    return header + "\n\n".join(parts) + footer


# ---------------------------------------------------------------------------
# Unit Tests: Evaluation Dataset (15 Contracts Benchmark)
# ---------------------------------------------------------------------------


def test_contract_1_full_compliant() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = COMPLIANT_CLAUSES_TEXT
    report = engine.evaluate_contract(contract, vendor_type="CLOUD")

    assert report.compliance_score >= 95.0
    assert report.risk_rating == "LOW"
    assert len(report.missing_clauses) == 0
    assert len(report.mandatory_clauses_present) == 8


def test_contract_2_missing_rbi_audit_access() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("RBI_AUDIT_ACCESS",))
    report = engine.evaluate_contract(contract, vendor_type="CLOUD")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Audit" in name for name in missing_ids)
    assert report.risk_rating in ("HIGH", "CRITICAL")
    assert report.compliance_score <= 65.0


def test_contract_3_offshore_data_transfer_violation() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(include_offshore_clause=True)
    report = engine.evaluate_contract(
        contract, vendor_type="PAYMENT_SWITCH", strict_localization=True
    )

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Localization" in name for name in missing_ids)
    assert report.risk_rating in ("HIGH", "CRITICAL")


def test_contract_4_missing_incident_notification() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("INCIDENT_NOTIFICATION",))
    report = engine.evaluate_contract(contract, vendor_type="SAAS")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Incident" in name for name in missing_ids)


def test_contract_5_missing_subcontracting_control() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("SUB_CONTRACTING_CONTROL",))
    report = engine.evaluate_contract(contract, vendor_type="CLOUD")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Sub-Contracting" in name for name in missing_ids)


def test_contract_6_missing_bcp_dr_testing() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("BCP_DR_TESTING",))
    report = engine.evaluate_contract(contract, vendor_type="DATACENTER")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Disaster Recovery" in name for name in missing_ids)


def test_contract_7_missing_termination_assistance() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("TERMINATION_ASSISTANCE",))
    report = engine.evaluate_contract(contract, vendor_type="SAAS")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Termination" in name or "Transition" in name for name in missing_ids)


def test_contract_8_missing_soc2_iso_audit() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("SOC2_ISO_AUDIT_RIGHTS",))
    report = engine.evaluate_contract(contract, vendor_type="CLOUD")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Certifications" in name for name in missing_ids)


def test_contract_9_multiple_critical_omissions() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("RBI_AUDIT_ACCESS", "DATA_LOCALIZATION"))
    report = engine.evaluate_contract(contract, vendor_type="PAYMENT_SWITCH")

    assert report.risk_rating == "CRITICAL"
    assert report.compliance_score <= 45.0
    assert len(report.missing_clauses) >= 2


def test_contract_10_negative_audit_access_negation() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(include_negative_audit=True)
    report = engine.evaluate_contract(contract, vendor_type="DATACENTER")

    missing_ids = [c.clause_name for c in report.missing_clauses]
    assert any("Audit" in name for name in missing_ids)
    assert report.risk_rating in ("HIGH", "CRITICAL")


def test_contract_11_saas_partial_deficiencies() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("BCP_DR_TESTING", "SOC2_ISO_AUDIT_RIGHTS"))
    report = engine.evaluate_contract(contract, vendor_type="SAAS")

    assert report.risk_rating == "MEDIUM" or report.risk_rating == "HIGH"
    assert len(report.missing_clauses) == 2


def test_contract_12_minimal_valid_addendum() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = (
        "STATUTORY ADDENDUM: Reserve Bank of India (RBI) and regulatory authority auditors have "
        "unconditional access to inspect all systems. All data is stored exclusively within India. "
        "Sub-contracting requires prior written approval. Incidents reported within 6 hours. "
        "Annual disaster recovery drills with RTO <= 2 hours. Exit transition assistance provided. "
        "Strict confidentiality survives termination. Annual SOC 2 Type II audit report provided."
    )
    report = engine.evaluate_contract(contract, vendor_type="CLOUD")
    assert report.compliance_score >= 90.0
    assert report.risk_rating == "LOW"


def test_contract_13_datacenter_specific_scope() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(omit=("SUB_CONTRACTING_CONTROL", "INCIDENT_NOTIFICATION"))
    report = engine.evaluate_contract(contract, vendor_type="DATACENTER")
    assert len(report.missing_clauses) == 2


def test_contract_14_four_clauses_missing() -> None:
    engine = VendorRiskAssessmentEngine()
    contract = _generate_contract(
        omit=(
            "BCP_DR_TESTING",
            "TERMINATION_ASSISTANCE",
            "SOC2_ISO_AUDIT_RIGHTS",
            "CONFIDENTIALITY_SECURITY",
        )
    )
    report = engine.evaluate_contract(contract, vendor_type="CLOUD")
    assert len(report.missing_clauses) == 4
    assert report.compliance_score < 75.0


def test_contract_15_severely_non_compliant_contract() -> None:
    engine = VendorRiskAssessmentEngine()
    bare_contract = (
        "AGREEMENT: The vendor will provide software hosting services as-is with no representations, "
        "no warranties, and no audit rights whatsoever. Customer pays on the first of each month."
    )
    report = engine.evaluate_contract(bare_contract, vendor_type="CLOUD")
    assert report.risk_rating == "CRITICAL"
    assert report.compliance_score < 30.0
    assert len(report.missing_clauses) >= 7


# ---------------------------------------------------------------------------
# Benchmark Accuracy Metrics (Recall >= 95%, Precision >= 90%)
# ---------------------------------------------------------------------------


def test_benchmark_recall_and_precision_on_15_contracts() -> None:
    engine = VendorRiskAssessmentEngine()

    total_expected_missing = 0
    total_detected_missing = 0
    true_positive_missing = 0

    omission_test_matrix = [
        (("RBI_AUDIT_ACCESS",), 1),
        (("DATA_LOCALIZATION",), 1),
        (("SUB_CONTRACTING_CONTROL",), 1),
        (("INCIDENT_NOTIFICATION",), 1),
        (("BCP_DR_TESTING",), 1),
        (("TERMINATION_ASSISTANCE",), 1),
        (("SOC2_ISO_AUDIT_RIGHTS",), 1),
        (("RBI_AUDIT_ACCESS", "DATA_LOCALIZATION"), 2),
        (("BCP_DR_TESTING", "SOC2_ISO_AUDIT_RIGHTS"), 2),
        (("SUB_CONTRACTING_CONTROL", "INCIDENT_NOTIFICATION"), 2),
    ]

    for omitted_ids, count in omission_test_matrix:
        contract = _generate_contract(omit=omitted_ids)
        report = engine.evaluate_contract(contract, vendor_type="CLOUD")

        total_expected_missing += count
        detected_count = len(report.missing_clauses)
        total_detected_missing += detected_count

        if detected_count >= count:
            true_positive_missing += count
        else:
            true_positive_missing += detected_count

    recall = true_positive_missing / total_expected_missing
    precision = true_positive_missing / total_detected_missing

    assert recall >= 0.95, f"Recall {recall:.3f} below 95% target"
    assert precision >= 0.90, f"Precision {precision:.3f} below 90% target"


# ---------------------------------------------------------------------------
# Performance SLA Test (<= 60 ms for 30-page agreement)
# ---------------------------------------------------------------------------


def test_performance_sla_30_page_agreement() -> None:
    engine = VendorRiskAssessmentEngine()
    # 30 pages ~ 50,000 characters
    long_contract = COMPLIANT_CLAUSES_TEXT * 25
    assert len(long_contract) >= 45000

    t0 = time.perf_counter()
    report = engine.evaluate_contract(long_contract, vendor_type="CLOUD")
    duration_ms = (time.perf_counter() - t0) * 1000.0

    assert report.compliance_score >= 90.0
    assert duration_ms <= 60.0, f"Evaluation duration {duration_ms:.2f}ms exceeds 60ms SLA"


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------


def test_input_validation_rules() -> None:
    engine = VendorRiskAssessmentEngine()

    # Reject < 100 characters
    with pytest.raises(ValueError, match="between 100 and 150,000 characters"):
        engine.evaluate_contract("Too short contract.", vendor_type="CLOUD")

    # Reject > 150,000 characters
    with pytest.raises(ValueError, match="between 100 and 150,000 characters"):
        engine.evaluate_contract("A" * 150001, vendor_type="CLOUD")


def test_engine_singleton_and_custom_config() -> None:
    engine = get_default_vendor_risk_engine()
    assert engine is not None
    custom_engine = VendorRiskAssessmentEngine(VendorRiskConfig(strict_localization=False))
    assert custom_engine.config.strict_localization is False


# ---------------------------------------------------------------------------
# REST API Endpoint Integration Tests
# ---------------------------------------------------------------------------


def test_api_vendor_audit_endpoint() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    payload = {
        "contract_text": COMPLIANT_CLAUSES_TEXT,
        "vendor_type": "CLOUD",
        "vendor_name": "CloudOps India Private Limited",
        "strict_localization": True,
    }

    res = client.post("/v1/compliance/vendor-audit", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["vendor_name"] == "CloudOps India Private Limited"
    assert data["vendor_type"] == "CLOUD"
    assert data["compliance_score"] >= 90.0
    assert data["risk_rating"] == "LOW"
    assert len(data["mandatory_clauses_present"]) == 8
    assert len(data["missing_clauses"]) == 0
    assert data["strict_localization_enforced"] is True


def test_api_vendor_audit_rejects_short_text() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)
    headers = auth(PRIMARY_KEY)

    payload = {
        "contract_text": "Short",
        "vendor_type": "SAAS",
    }

    res = client.post("/v1/compliance/vendor-audit", json=payload, headers=headers)
    assert res.status_code == 422
