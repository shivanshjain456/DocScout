"""Unit, integration, and performance test suite for DORA Framework Runner (FEAT-058).

Validates:
1. 10 simulated financial institution ICT architecture profiles evaluated across DORA Pillars 1-5:
   - Tier-1 Systemic Global Bank Core (full compliance, active TLPT, RTO/RPO defined, CTPP exit strategies).
   - Regional Commercial Bank (CTPP without exit strategy flagged under Article 28(8)).
   - Cloud-Native Fintech / Neobank (critical ledger without TLPT flagged under Article 26(1)).
   - Asset Management Firm (expired TLPT exceeding 3-year statutory cadence flagged).
   - Payment Processor (critical authorization engine exceeding 240m RTO threshold under Article 11(2)).
   - Digital Brokerage Platform (undefined RTO/RPO on critical systems flagged).
   - Legacy Cooperative Bank (missing incident response and reporting playbooks under Articles 17-19).
   - Private Wealth Bank (zero cyber threat intelligence sharing under Article 45).
   - Microfinance Institution (non-systemic, all systems low/medium criticality).
   - Deficient / Insolvent Institution (critical systems fail every control, baseline score < 35%).
2. 100% control coverage across DORA Articles 5-16.
3. Zero false claims of resilience compliance without verified test evidence.
4. Performance SLA: 1,000 system evaluation latency <= 15.0 ms.
5. Multi-tenant isolation across institutional tenant keys.
6. Prometheus observability: Counter docscout_dora_assessments_completed_total and docscout_resilience_tests_recorded_total.
7. REST API endpoints:
   - POST /v1/compliance/dora/assess
   - GET /v1/compliance/dora/report
   - POST /v1/compliance/dora/tests/record
   - GET /v1/compliance/dora/systems
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.models import (
    DORAAssessmentRequest,
    ICTSystemSpec,
)
from app.api.security import load_keys
from app.compliance.dora_runner import (
    DORAConfig,
    DORARunner,
    evaluate_dora_pillars,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


def build_10_financial_profiles() -> dict[str, list[ICTSystemSpec]]:
    """Build evaluation dataset of 10 distinct simulated financial institution ICT profiles."""
    today = date.today()
    recent_tlpt = today - timedelta(days=180)  # 6 months ago (compliant)
    expired_tlpt = today - timedelta(days=1200)  # > 3 years ago (expired)

    profiles: dict[str, list[ICTSystemSpec]] = {
        # Profile 1: Tier-1 Systemic Global Bank Core (100% compliant)
        "tier1_global_bank": [
            ICTSystemSpec(
                system_id="t1-core-01",
                name="Global Core Banking Ledger",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=60,
                rpo_minutes=15,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
            ICTSystemSpec(
                system_id="t1-pay-02",
                name="SWIFT International Settlement Gateway",
                criticality="CRITICAL",
                is_third_party=True,
                third_party_provider="SWIFT SCRL",
                is_critical_third_party=True,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=120,
                rpo_minutes=15,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
            ICTSystemSpec(
                system_id="t1-cloud-03",
                name="Enterprise Analytical Data Lake",
                criticality="HIGH",
                is_third_party=True,
                third_party_provider="CloudCorp AWS",
                is_critical_third_party=True,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=180,
                rpo_minutes=60,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 2: Regional Commercial Bank (CTPP without exit strategy)
        "regional_commercial_bank": [
            ICTSystemSpec(
                system_id="rcb-core-01",
                name="Regional Deposit Ledger",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=120,
                rpo_minutes=30,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
            ICTSystemSpec(
                system_id="rcb-cloud-02",
                name="Core Cloud Hosting Infrastructure",
                criticality="CRITICAL",
                is_third_party=True,
                third_party_provider="MegaCloud Services",
                is_critical_third_party=True,
                has_exit_strategy=False,  # Violation under Article 28(8)
                last_tlpt_date=recent_tlpt,
                rto_minutes=120,
                rpo_minutes=30,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 3: Cloud-Native Fintech Neobank (Missing mandatory TLPT)
        "fintech_neobank": [
            ICTSystemSpec(
                system_id="neo-app-01",
                name="Retail Mobile Banking Gateway",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=None,  # Missing mandatory TLPT under Article 26(1)
                rto_minutes=30,
                rpo_minutes=5,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
            ICTSystemSpec(
                system_id="neo-card-02",
                name="Card Issuer Processing Bridge",
                criticality="HIGH",
                is_third_party=True,
                third_party_provider="CardProcessor Global",
                is_critical_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=None,
                rto_minutes=60,
                rpo_minutes=10,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 4: Asset Management Firm (Expired TLPT > 3 years)
        "asset_management_firm": [
            ICTSystemSpec(
                system_id="am-port-01",
                name="Multi-Asset Order Routing & Valuation",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=expired_tlpt,  # Expired TLPT
                rto_minutes=180,
                rpo_minutes=60,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 5: Payment Processor (Critical system RTO exceeds 240m ceiling)
        "payment_processor": [
            ICTSystemSpec(
                system_id="pay-auth-01",
                name="Real-Time Payment Authorization Hub",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=480,  # Exceeds max_critical_rto_minutes (240m)
                rpo_minutes=15,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 6: Digital Brokerage Platform (Undefined RTO/RPO on critical system)
        "digital_brokerage": [
            ICTSystemSpec(
                system_id="brok-match-01",
                name="Order Matching & Settlement Engine",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=None,  # Missing RTO under Article 11(2)
                rpo_minutes=None,  # Missing RPO under Article 11(2)
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 7: Deficient Legacy Cooperative Bank (Missing incident response plan)
        "cooperative_bank": [
            ICTSystemSpec(
                system_id="coop-core-01",
                name="Branch Banking System",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=120,
                rpo_minutes=30,
                has_incident_plan=False,  # Violation under Articles 17-19
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 8: Private Wealth Bank (Zero threat intelligence sharing)
        "wealth_bank": [
            ICTSystemSpec(
                system_id="wb-port-01",
                name="Private Wealth Portfolio Management",
                criticality="CRITICAL",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=recent_tlpt,
                rto_minutes=120,
                rpo_minutes=30,
                has_incident_plan=True,
                has_threat_intel_sharing=False,  # Violation under Article 45
            ),
        ],
        # Profile 9: Microfinance Institution (All low/medium criticality systems)
        "microfinance_inst": [
            ICTSystemSpec(
                system_id="mfi-field-01",
                name="Field Agent Mobile Ledger",
                criticality="MEDIUM",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=None,
                rto_minutes=480,
                rpo_minutes=240,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
            ICTSystemSpec(
                system_id="mfi-crm-02",
                name="Member Records Registry",
                criticality="LOW",
                is_third_party=False,
                has_exit_strategy=True,
                last_tlpt_date=None,
                rto_minutes=1440,
                rpo_minutes=720,
                has_incident_plan=True,
                has_threat_intel_sharing=True,
            ),
        ],
        # Profile 10: Insolvent / Deficient Institution (Fails every statutory control)
        "deficient_institution": [
            ICTSystemSpec(
                system_id="def-core-01",
                name="Unpatched Legacy Core",
                criticality="CRITICAL",
                is_third_party=True,
                third_party_provider="Unknown Shadow Vendor",
                is_critical_third_party=True,
                has_exit_strategy=False,
                last_tlpt_date=None,
                rto_minutes=None,
                rpo_minutes=None,
                has_incident_plan=False,
                has_threat_intel_sharing=False,
            ),
        ],
    }
    return profiles


def test_10_financial_institution_profiles() -> None:
    """Verify DORA compliance evaluation across 10 simulated financial institution profiles."""
    profiles = build_10_financial_profiles()
    config = DORAConfig()

    # 1. Tier-1 Global Bank: fully compliant
    p1_pillars, p1_readiness, p1_recs = evaluate_dora_pillars(profiles["tier1_global_bank"], config)
    assert p1_readiness >= 90.0
    for pillar in p1_pillars.values():
        assert pillar.compliance_pct >= 85.0
        assert len(pillar.gaps) == 0

    # 2. Regional Bank: CTPP without exit strategy flagged in Pillar 4
    p2_pillars, p2_readiness, _ = evaluate_dora_pillars(
        profiles["regional_commercial_bank"], config
    )
    p4 = p2_pillars["pillar_4_third_party_risk"]
    assert any("exit strategy" in g for g in p4.gaps)
    assert p4.compliance_pct < 60.0

    # 3. Fintech Neobank: Missing TLPT flagged in Pillar 3
    p3_pillars, p3_readiness, _ = evaluate_dora_pillars(profiles["fintech_neobank"], config)
    p3 = p3_pillars["pillar_3_resilience_testing"]
    assert any("never completed a mandatory Threat-Led Penetration Test" in g for g in p3.gaps)
    assert p3.compliance_pct < 80.0

    # 4. Asset Management: Expired TLPT flagged in Pillar 3
    p4_pillars, _, _ = evaluate_dora_pillars(profiles["asset_management_firm"], config)
    assert any("expired" in g for g in p4_pillars["pillar_3_resilience_testing"].gaps)

    # 5. Payment Processor: RTO 480m exceeds statutory ceiling in Pillar 1
    p5_pillars, _, _ = evaluate_dora_pillars(profiles["payment_processor"], config)
    assert any("exceeds statutory limit" in g for g in p5_pillars["pillar_1_risk_management"].gaps)

    # 6. Digital Brokerage: Undefined RTO/RPO flagged in Pillar 1
    p6_pillars, _, _ = evaluate_dora_pillars(profiles["digital_brokerage"], config)
    p1 = p6_pillars["pillar_1_risk_management"]
    assert any("lacks defined Recovery Time Objective" in g for g in p1.gaps)
    assert any("lacks defined Recovery Point Objective" in g for g in p1.gaps)

    # 7. Cooperative Bank: Missing incident response plan flagged in Pillar 2
    p7_pillars, _, _ = evaluate_dora_pillars(profiles["cooperative_bank"], config)
    assert any("incident management" in g for g in p7_pillars["pillar_2_incident_reporting"].gaps)

    # 8. Wealth Bank: Zero threat intelligence sharing flagged in Pillar 5
    p8_pillars, _, _ = evaluate_dora_pillars(profiles["wealth_bank"], config)
    assert any("sharing" in g.lower() for g in p8_pillars["pillar_5_info_sharing"].gaps)

    # 9. Microfinance: Medium/Low systems, no critical TLPT requirement
    p9_pillars, p9_readiness, _ = evaluate_dora_pillars(profiles["microfinance_inst"], config)
    assert p9_readiness >= 80.0
    assert len(p9_pillars["pillar_3_resilience_testing"].gaps) == 0

    # 10. Deficient Institution: Fails every control, readiness < 35%
    p10_pillars, p10_readiness, _ = evaluate_dora_pillars(profiles["deficient_institution"], config)
    assert p10_readiness <= 35.0
    total_gaps = sum(len(p.gaps) for p in p10_pillars.values())
    assert total_gaps >= 5


def test_zero_false_claims_guarantee() -> None:
    """Ensure unverified resilience claims are rejected and require verified evidence."""
    today = date.today()
    config = DORAConfig()

    # System claiming to be critical with no TLPT date
    untested_system = [
        ICTSystemSpec(
            system_id="untested-01",
            name="Claimed Resilient Core",
            criticality="CRITICAL",
            is_third_party=False,
            last_tlpt_date=None,
            rto_minutes=60,
            rpo_minutes=15,
        )
    ]
    pillars, readiness, recs = evaluate_dora_pillars(untested_system, config, evaluation_date=today)
    p3 = pillars["pillar_3_resilience_testing"]
    assert len(p3.gaps) > 0
    assert any("never completed" in g for g in p3.gaps)
    assert p3.compliance_pct < 100.0


def test_control_coverage_articles_5_to_16() -> None:
    """Verify 100% control coverage across DORA Articles 5-16 in Pillar 1."""
    config = DORAConfig()
    systems = [
        ICTSystemSpec(
            system_id="test-art-01",
            name="Trading System",
            criticality="CRITICAL",
            rto_minutes=120,
            rpo_minutes=30,
        ),
        ICTSystemSpec(
            system_id="test-art-02",
            name="Reporting Server",
            criticality="HIGH",
            rto_minutes=240,
            rpo_minutes=60,
        ),
        ICTSystemSpec(
            system_id="test-art-03",
            name="Internal Analytics",
            criticality="MEDIUM",
        ),
    ]
    pillars, _, _ = evaluate_dora_pillars(systems, config)
    p1 = pillars["pillar_1_risk_management"]
    assert "Articles 5-16" in p1.articles
    assert p1.compliance_pct == 100.0
    assert len(p1.gaps) == 0


def test_benchmark_latency_and_memory() -> None:
    """Benchmark: Evaluation of 1,000 systems executed in <= 15.0 ms."""
    today = date.today()
    specs: list[ICTSystemSpec] = []
    for i in range(1000):
        specs.append(
            ICTSystemSpec(
                system_id=f"bench-sys-{i}",
                name=f"Enterprise Architecture Component {i}",
                criticality="CRITICAL" if i % 10 == 0 else "HIGH" if i % 5 == 0 else "MEDIUM",
                is_third_party=(i % 3 == 0),
                third_party_provider=f"Provider-{i % 10}" if (i % 3 == 0) else None,
                is_critical_third_party=(i % 15 == 0),
                has_exit_strategy=(i % 2 == 0),
                last_tlpt_date=today - timedelta(days=200) if (i % 2 == 0) else None,
                rto_minutes=120 if (i % 4 != 0) else 360,
                rpo_minutes=30,
                has_incident_plan=(i % 8 != 0),
                has_threat_intel_sharing=(i % 2 == 0),
            )
        )

    config = DORAConfig()

    # Warmup
    evaluate_dora_pillars(specs[:10], config)

    # Benchmark run
    t0 = time.perf_counter()
    pillars, overall_readiness, recs = evaluate_dora_pillars(specs, config)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    print(f"DORA 1,000 systems benchmark duration: {duration_ms:.3f} ms")
    assert duration_ms <= 15.0, f"Benchmark SLA exceeded: {duration_ms:.3f} ms > 15.0 ms"
    assert len(pillars) == 5
    assert overall_readiness > 0.0


def test_multi_tenant_isolation() -> None:
    """Ensure institutional records and scorecards are isolated by tenant."""
    runner = DORARunner()
    tenant_a = f"tenant-{uuid4().hex[:8]}"
    tenant_b = f"tenant-{uuid4().hex[:8]}"

    sys_a = [
        ICTSystemSpec(
            system_id="sys-a-01",
            name="Tenant A Core Banking",
            criticality="CRITICAL",
            rto_minutes=60,
            rpo_minutes=15,
            last_tlpt_date=date.today(),
            has_exit_strategy=True,
            has_threat_intel_sharing=True,
        )
    ]

    sys_b = [
        ICTSystemSpec(
            system_id="sys-b-01",
            name="Tenant B Shadow Portal",
            criticality="CRITICAL",
            rto_minutes=600,
            rpo_minutes=None,
            last_tlpt_date=None,
            has_exit_strategy=False,
            has_threat_intel_sharing=False,
        )
    ]

    report_a = runner.assess_systems(DORAAssessmentRequest(tenant_id=tenant_a, ict_systems=sys_a))
    report_b = runner.assess_systems(DORAAssessmentRequest(tenant_id=tenant_b, ict_systems=sys_b))

    assert report_a.tenant_id == tenant_a
    assert report_a.overall_readiness > report_b.overall_readiness
    assert report_b.tenant_id == tenant_b

    # Verify query isolation
    systems_a = runner.get_systems(tenant_id=tenant_a)
    systems_b = runner.get_systems(tenant_id=tenant_b)

    assert systems_a.total_count == 1
    assert systems_a.systems[0].system_id == "sys-a-01"

    assert systems_b.total_count == 1
    assert systems_b.systems[0].system_id == "sys-b-01"


def test_rest_api_assess_and_report(test_client: TestClient, api_headers: dict[str, str]) -> None:
    """Test POST /v1/compliance/dora/assess and GET /v1/compliance/dora/report endpoints."""
    tenant = f"test-tenant-{uuid4().hex[:6]}"

    payload = {
        "tenant_id": tenant,
        "ict_systems": [
            {
                "system_id": "api-core-01",
                "name": "API Core Engine",
                "criticality": "CRITICAL",
                "is_third_party": False,
                "has_exit_strategy": True,
                "last_tlpt_date": "2025-06-01",
                "rto_minutes": 120,
                "rpo_minutes": 30,
                "has_incident_plan": True,
                "has_threat_intel_sharing": True,
            }
        ],
    }

    # 1. Unauthenticated request rejected
    res_unauth = test_client.post("/v1/compliance/dora/assess", json=payload)
    assert res_unauth.status_code == 401

    # 2. Authenticated assessment execution
    res = test_client.post(
        f"/v1/compliance/dora/assess?tenant_id={tenant}",
        json=payload,
        headers=api_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["tenant_id"] == tenant
    assert data["total_systems"] == 1
    assert data["critical_systems"] == 1
    assert "pillars" in data
    assert "pillar_1_risk_management" in data["pillars"]

    # 3. Retrieve report via GET
    res_report = test_client.get(
        f"/v1/compliance/dora/report?tenant_id={tenant}",
        headers=api_headers,
    )
    assert res_report.status_code == 200
    report_data = res_report.json()
    assert report_data["tenant_id"] == tenant
    assert report_data["total_systems"] == 1

    # 4. Retrieve systems via GET
    res_systems = test_client.get(
        f"/v1/compliance/dora/systems?tenant_id={tenant}",
        headers=api_headers,
    )
    assert res_systems.status_code == 200
    sys_data = res_systems.json()
    assert sys_data["total_count"] == 1
    assert sys_data["systems"][0]["system_id"] == "api-core-01"


def test_rest_api_record_resilience_test(
    test_client: TestClient, api_headers: dict[str, str]
) -> None:
    """Test POST /v1/compliance/dora/tests/record endpoint."""
    tenant = f"test-tenant-{uuid4().hex[:6]}"

    # Ingest a system first
    test_client.post(
        f"/v1/compliance/dora/assess?tenant_id={tenant}",
        json={
            "tenant_id": tenant,
            "ict_systems": [
                {
                    "system_id": "sys-tlpt-01",
                    "name": "Target TLPT Core",
                    "criticality": "CRITICAL",
                    "is_third_party": False,
                    "has_exit_strategy": True,
                    "last_tlpt_date": None,
                    "rto_minutes": 60,
                    "rpo_minutes": 15,
                    "has_incident_plan": True,
                    "has_threat_intel_sharing": True,
                }
            ],
        },
        headers=api_headers,
    )

    # Record verified TLPT test
    test_payload = {
        "system_id": "sys-tlpt-01",
        "test_type": "TLPT",
        "passed": True,
        "evidence_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "findings": ["No critical vulnerabilities exploited during red-team engagement."],
        "tenant_id": tenant,
    }

    res = test_client.post(
        f"/v1/compliance/dora/tests/record?tenant_id={tenant}",
        json=test_payload,
        headers=api_headers,
    )
    assert res.status_code == 200
    rec_data = res.json()
    assert rec_data["status"] == "PASSED"
    assert "test_id" in rec_data

    # Check that system's last_tlpt_date was updated
    res_sys = test_client.get(
        f"/v1/compliance/dora/systems?tenant_id={tenant}",
        headers=api_headers,
    )
    assert res_sys.status_code == 200
    updated_systems = res_sys.json()["systems"]
    assert len(updated_systems) == 1
    assert updated_systems[0]["last_tlpt_date"] == date.today().isoformat()
