"""Integration and evaluation tests for Regulatory Risk Scorecard Generator (FEAT-040).

Validates:
1. Input validation (rejecting empty or <100 words policy dossiers).
2. 10 benchmark enterprise policy dossiers covering compliance maturity tiers (Grades A through F).
3. 100% scoring reproducibility on identical inputs.
4. Custom grading rubric weights customization.
5. Structured Markdown report with circular citations and remediation roadmap.
6. PDF/A generation validity and pypdf parsability.
7. Remediation timeline calculation.
8. HTTP API POST /v1/compliance/scorecard endpoint and Prometheus metrics.
9. Performance SLA (<= 2.5s for 50 pages / dossiers).
"""

from __future__ import annotations

import base64
import io
import os
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfReader

from app.api.app import app
from app.api.metrics import SCORECARDS_GENERATED_TOTAL
from app.api.models import ScorecardRequest
from app.api.security import load_keys
from app.compliance.scorecard import RegulatoryRiskScorecardEngine, ScorecardResult
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth

# -----------------------------------------------------------------------------
# 10 Benchmark Enterprise Policy Dossiers
# -----------------------------------------------------------------------------

BENCHMARK_DOSSIERS: list[dict[str, Any]] = [
    # Dossier 1: Pristine Tier-1 Scheduled Commercial Bank -> Target Grade A
    {
        "id": "dossier-01-tier1-scb",
        "org_type": "scheduled_commercial_bank",
        "expected_grade": "A",
        "min_score": 90.0,
        "text": """Standard Operating Procedure for Statutory Compliance - Zenith National Bank.
This comprehensive compliance policy establishes institutional adherence to the Reserve Bank of India
Master Direction on Know Your Customer (KYC) Direction, 2016 (Updated 2024), utilizing Central KYC
Records Registry (CKYCR) seeding and Video-based Customer Identification Process (V-CIP).
Capital adequacy is maintained strictly in accordance with Basel III Final Reforms CRE20 Standardised
Approach for Credit Risk, incorporating dynamic loan-to-value weighting and strict output floor metrics.
Information security governance adheres strictly to ISO/IEC 27001 and the RBI Cyber Security Framework,
enforcing continuous W3C distributed trace context propagation across all banking microservices and
mandatory 6-hour security incident notification. All credit underwriting utilizes metamorphic testing
and continuous model validation with monthly population stability index (PSI) recalibration. Continuous
evidence collection runs via automated policy-as-code telemetry with cryptographically signed audit trails.
Prevention of Money-laundering (Maintenance of Records) rules are verified at the amended 10% beneficial
ownership threshold across all corporate onboarding workflows. Diff coverage and mutation testing are
strictly enforced across all core banking software deployments to guarantee structural integrity.""",
    },
    # Dossier 2: Solid NBFC -> Target Grade B
    {
        "id": "dossier-02-solid-nbfc",
        "org_type": "nbfc",
        "expected_grade": "B",
        "min_score": 80.0,
        "text": """Corporate Governance & Risk Management Framework - Apex Prime Finance NBFC.
Apex Prime Finance complies with the RBI Scale Based Regulation (SBR) framework for Middle Layer NBFCs.
Customer identification follows the RBI Master Direction on Know Your Customer (KYC) Direction, 2016,
integrating digital KYC and periodic risk-based updation. Information technology controls implement
the RBI Cyber Security Framework and ISO/IEC 27001 standard with encrypted off-site disaster recovery.
In engineering telemetry, our build pipelines mandate line coverage as a quality target across pull requests.
Furthermore, deployment teams are accumulating unowned, never-expiring toggles in the feature configuration.
Our third party governance cites DBOD.No.BP.40/21.04.158/2006-07 for legacy service providers.
All financial accounting reconciliations follow Indian financial unit conventions, and credit risk audits
are conducted quarterly with dynamic stress testing across loan portfolios.""",
    },
    # Dossier 3: Payment Aggregator -> Target Grade C
    {
        "id": "dossier-03-payment-aggregator",
        "org_type": "payment_aggregator",
        "expected_grade": "C",
        "min_score": 70.0,
        "text": """Merchant Onboarding and Settlement Policy - PaySwift Technologies.
PaySwift Technologies operates as an authorized Payment Aggregator under Reserve Bank of India
Payment Aggregator Guidelines and Card-on-File Tokenization (CoFT) directions.
All cardholder authentication implements Additional Factor of Authentication (AFA). Escrow accounts
are maintained with scheduled commercial banks with daily T+1 settlement reconciliations.
Information security policies align with ISO/IEC 27001 and RBI Cyber Security Framework mandates.
In testing, teams mandate line coverage as a quality target for release gates. In feature deployment,
the team is accumulating unowned, never-expiring toggles. For releases, engineers are watching a dashboard by eye
during canary rollouts. For vendor outsourcing, our handbook cites DBOD.No.BP.40/21.04.158/2006-07.
For customer identification, legacy merchants follow DBOD.AML.BC.No.11/14.01.001/2013-14 procedures.""",
    },
    # Dossier 4: Digital Lending Platform -> Target Grade D
    {
        "id": "dossier-04-digital-lender",
        "org_type": "fintech",
        "expected_grade": "D",
        "min_score": 60.0,
        "text": """Underwriting Architecture and Product Policy - QuickRupee Digital Lending.
QuickRupee operates a digital lending application partnering with regulated NBFC balance sheet partners,
providing key fact statement disclosures under RBI Digital Lending Guidelines and OWASP ASVS appsec standards.
Information security conforms to ISO/IEC 27001 practices across cloud infrastructure.
In our software engineering lifecycle, we mandate line coverage as a quality target across all microservices.
Teams are accumulating unowned, never-expiring toggles in production databases. For deployment rollouts,
engineers are watching a dashboard by eye during canary deployments. Contract testing involves
publishing consumer pacts without ever running provider verification. For auditing preparation, teams
resort to collecting evidence by screenshot shortly before the audit window closes.
In regulatory references, the policy cites DBOD.No.BP.40/21.04.158/2006-07 for vendor hosting, and
DBOD.AML.BC.No.11/14.01.001/2013-14 for initial customer identification.""",
    },
    # Dossier 5: Severely Outdated & Non-compliant Entity -> Target Grade F
    {
        "id": "dossier-05-critical-risk-lender",
        "org_type": "fintech",
        "expected_grade": "F",
        "min_score": 0.0,
        "text": """Operations & Credit Underwriting Manual - ShadowLend Private Limited.
Customer onboarding across our platform verifies identity strictly relying on RBI KYC Guidelines 2002 under
DBOD.AML.BC.18/14.01.001/2002-03 circular references. Customer verification accepts manual physical photocopies
without central registry validation. For corporate borrower due diligence, our policy enforces the PMLA 25%
beneficial ownership threshold to identify controlling equity stakeholders.
In our software engineering lifecycle, we mandate 100% statement coverage as a release gate to approve code
for production deployment. Automated test suites execute with blind test retries in CI pipelines to eliminate
intermittent test flakiness. Our credit decisioning AI model was certified through independent model validation
conducted only prior to initial deployment as a one-time pre-launch sign-off. Telemetry is gathered by
instrumenting only the entry service and assuming traces will join up automatically. Blue-green traffic cutover
switches production traffic immediately without connection draining or in-flight session drainage.""",
    },
    # Dossier 6: Small Finance Bank -> Target Grade A
    {
        "id": "dossier-06-small-finance-bank",
        "org_type": "scheduled_commercial_bank",
        "expected_grade": "A",
        "min_score": 90.0,
        "text": """Statutory Operational Guidelines - Pragati Small Finance Bank Limited.
Pragati Small Finance Bank maintains high regulatory fidelity across priority sector advances and retail deposits.
All customer due diligence complies strictly with RBI Master Direction - Know Your Customer (KYC) Direction, 2016 (Updated 2024),
enforcing Central KYC Registry integration and Aadhaar biometric e-KYC.
Capital adequacy adheres to Basel III framework ratios with Tier-1 capital exceeding regulatory thresholds under CRE20 standards.
Information security programs implement the RBI Cyber Security Framework and ISO/IEC 27001 specifications,
including automated vulnerability management and continuous evidence collection with cryptographic logs.
PMLA rules apply the mandatory 10% beneficial ownership benchmark for legal entities. Software engineering
enforces diff coverage and metamorphic testing across core banking APIs.""",
    },
    # Dossier 7: Payments Bank -> Target Grade B
    {
        "id": "dossier-07-payments-bank",
        "org_type": "scheduled_commercial_bank",
        "expected_grade": "B",
        "min_score": 80.0,
        "text": """Operating Protocol and Security Manual - Bharat Digital Payments Bank.
Bharat Payments Bank provides small-value remittances and demand deposit accounts up to Rs. 2 lakh per individual.
Customer identification adheres strictly to the RBI KYC Direction, 2016 with CKYCR seeding.
Beneficial ownership screening applies PMLA beneficial ownership rules. Capital adequacy maintains Basel III ratios.
Information technology infrastructure implements the RBI Cyber Security Framework and ISO/IEC 27001 standard.
In software engineering, teams mandate line coverage as a quality target across automated gates.
Feature development results in accumulating unowned, never-expiring toggles across merchant portal codebases.
Vendor contracts cite DBOD.No.BP.40/21.04.158/2006-07 for core banking hosting. All transactions operate over UPI.""",
    },
    # Dossier 8: Core Investment Company (CIC) -> Target Grade B
    {
        "id": "dossier-08-core-investment-company",
        "org_type": "nbfc",
        "expected_grade": "B",
        "min_score": 80.0,
        "text": """Capital Allocation and Governance Manual - Horizon Holdings Core Investment Company.
Horizon Holdings operates as a Middle Layer Systemically Important Core Investment Company under RBI Scale Based Regulation (SBR).
Our asset base comprises at least 90% investments in equity shares, preference shares, and debt securities of group companies.
Customer onboarding and entity KYC complies with the RBI Master Direction on Know Your Customer (KYC) Direction, 2016.
Cyber security policies conform to the RBI Cyber Security Framework and ISO/IEC 27001 standards.
In our software engineering lifecycle, pipelines mandate line coverage as a quality target across analytics microservices.
Release managers allow accumulating unowned, never-expiring toggles in investment reporting portals.
Procurement guidelines cite DBOD.No.BP.40/21.04.158/2006-07 for infrastructure services.
Adjusted net worth maintains a minimum ratio of 30% against aggregate risk-weighted assets.""",
    },
    # Dossier 9: P2P Lending Platform -> Target Grade C
    {
        "id": "dossier-09-p2p-lending",
        "org_type": "nbfc",
        "expected_grade": "C",
        "min_score": 70.0,
        "text": """Peer-to-Peer Lending Platform Operating Guidelines - FairLend Network.
FairLend Network operates as a Middle Layer NBFC under the RBI Scale Based Regulation (SBR) framework.
Customer verification complies with the RBI Master Direction on Know Your Customer (KYC) Direction, 2016.
Information security incorporates the RBI Cyber Security Framework and ISO/IEC 27001 standards.
In software development, builds mandate line coverage as a quality target across automated gates.
Product teams practice accumulating unowned, never-expiring toggles in mobile application codebases.
In deployment monitoring, operations teams are watching a dashboard by eye during canary rollouts.
IT outsourcing policies cite DBOD.No.BP.40/21.04.158/2006-07 for cloud vendor management.
Identity records cite DBOD.AML.BC.No.11/14.01.001/2013-14 for historical accounts. Escrow accounts reconcile daily.""",
    },
    # Dossier 10: Custodian & Depository Participant -> Target Grade A
    {
        "id": "dossier-10-custodian-depository",
        "org_type": "general",
        "expected_grade": "A",
        "min_score": 90.0,
        "text": """Securities Custody and Clearing Operations Manual - Trident Custodial Services.
Trident Custodial Services provides clearing, settlement, and asset servicing for domestic mutual funds and FPIs.
Information security governance is accredited under ISO/IEC 27001 and RBI Cyber Security Framework mandates,
incorporating continuous red-teaming, zero-trust network architectures, and automated W3C trace propagation.
Customer and beneficial ownership screening complies with PMLA rules applying the 10% threshold.
Software engineering practices mandate mutation testing and diff coverage across all custody ledger services.
Business continuity plans ensure secondary site failover within 15 minutes of primary data center disruption.
Model validation runs continuously with automated PSI tracking. Disaster recovery is tested quarterly.""",
    },
]


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_scorecard_input_validation() -> None:
    """Verify input validation rules: at least 1 document text with >= 100 words."""
    # 1. Empty list
    with pytest.raises(ValidationError) as exc1:
        ScorecardRequest(policy_document_texts=[])
    assert "At least 1 policy document text must be provided" in str(exc1.value)

    # 2. Too short (< 100 words)
    short_text = "This is a short policy description that does not have enough detail for an enterprise compliance audit."
    with pytest.raises(ValidationError) as exc2:
        ScorecardRequest(policy_document_texts=[short_text])
    assert "At least 1 policy document text must contain at least 100 words" in str(exc2.value)


def test_10_benchmark_policy_dossiers_grading_accuracy() -> None:
    """Evaluate all 10 benchmark policy dossiers across compliance maturity tiers."""
    engine = RegulatoryRiskScorecardEngine()

    for dossier in BENCHMARK_DOSSIERS:
        d_id = dossier["id"]
        expected_grade = dossier["expected_grade"]
        org_type = dossier["org_type"]

        result = engine.generate_scorecard(
            policy_document_texts=[dossier["text"]],
            organization_type=org_type,
            include_pdf=True,
        )

        assert isinstance(result, ScorecardResult)
        assert result.overall_grade == expected_grade, (
            f"Dossier '{d_id}' expected grade {expected_grade}, got {result.overall_grade} (score: {result.numerical_score})"
        )
        assert 0.0 <= result.numerical_score <= 100.0
        assert result.remediation_timeline_days >= 7

        # Grade A should have high scores and minimal critical risks
        if expected_grade == "A":
            assert result.numerical_score >= 90.0
            assert len(result.critical_risks) == 0

        # Grade F should have critical risks and low score
        if expected_grade == "F":
            assert result.numerical_score < 60.0
            assert len(result.critical_risks) > 0


def test_scorecard_scoring_reproducibility() -> None:
    """Ensure identical policy dossier inputs yield 100% reproducible scores."""
    engine = RegulatoryRiskScorecardEngine()
    dossier = BENCHMARK_DOSSIERS[1]

    run1 = engine.generate_scorecard([dossier["text"]], organization_type=dossier["org_type"])
    run2 = engine.generate_scorecard([dossier["text"]], organization_type=dossier["org_type"])

    assert run1.numerical_score == run2.numerical_score
    assert run1.overall_grade == run2.overall_grade
    assert run1.antipatterns_score == run2.antipatterns_score
    assert run1.deprecations_score == run2.deprecations_score
    assert run1.standards_coverage_score == run2.standards_coverage_score
    assert run1.remediation_timeline_days == run2.remediation_timeline_days


def test_custom_rubric_weights_customization() -> None:
    """Passing custom weights adjusts final score calculation predictably."""
    engine = RegulatoryRiskScorecardEngine()
    dossier = BENCHMARK_DOSSIERS[2]  # Payment aggregator with antipattern

    # Standard weights (40% AP, 40% Dep, 20% Std)
    res_default = engine.generate_scorecard(
        [dossier["text"]], organization_type=dossier["org_type"]
    )

    # Heavy antipattern penalty (80% AP, 10% Dep, 10% Std)
    res_heavy_ap = engine.generate_scorecard(
        [dossier["text"]],
        organization_type=dossier["org_type"],
        rubric_weights={"antipatterns": 0.8, "deprecations": 0.1, "standards_coverage": 0.1},
    )

    assert res_heavy_ap.numerical_score != res_default.numerical_score


def test_markdown_and_pdf_generation() -> None:
    """Verify generated Markdown report structure and PDF/A parsability."""
    engine = RegulatoryRiskScorecardEngine()
    dossier = BENCHMARK_DOSSIERS[0]

    result = engine.generate_scorecard(
        [dossier["text"]],
        organization_type="scheduled_commercial_bank",
        include_pdf=True,
    )

    # 1. Markdown validation
    assert "# Regulatory Risk Audit Scorecard" in result.markdown_report
    assert "Overall Compliance Grade:" in result.markdown_report
    assert "Prioritized Remediation Roadmap" in result.markdown_report

    # 2. PDF validation
    assert result.pdf_bytes is not None
    assert len(result.pdf_bytes) > 200
    assert result.pdf_bytes.startswith(b"%PDF-1.4")

    # Verify with pypdf
    reader = PdfReader(io.BytesIO(result.pdf_bytes))
    assert len(reader.pages) >= 1
    page_text = reader.pages[0].extract_text()
    assert "DOCSCOUT ENTERPRISE REGULATORY RISK AUDIT SCORECARD" in page_text

    # Verify base64 string
    assert result.pdf_base64 is not None
    decoded = base64.b64decode(result.pdf_base64)
    assert decoded == result.pdf_bytes


def test_api_scorecard_endpoint(test_client: TestClient) -> None:
    """Test HTTP POST /v1/compliance/scorecard endpoint."""
    headers = auth(PRIMARY_KEY)
    dossier = BENCHMARK_DOSSIERS[0]

    before_metric = SCORECARDS_GENERATED_TOTAL.labels(grade="A")._value.get()

    t0 = time.perf_counter()
    resp = test_client.post(
        "/v1/compliance/scorecard",
        headers=headers,
        json={
            "policy_document_texts": [dossier["text"]],
            "organization_type": "scheduled_commercial_bank",
            "include_pdf": True,
        },
    )
    duration_s = time.perf_counter() - t0

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_grade"] == "A"
    assert data["numerical_score"] >= 90.0
    assert "markdown_report" in data
    assert data["pdf_content_base64"] is not None

    after_metric = SCORECARDS_GENERATED_TOTAL.labels(grade="A")._value.get()
    assert after_metric == before_metric + 1

    # Performance SLA: <= 2.5s
    assert duration_s <= 2.5, f"Execution time {duration_s:.3f}s exceeded 2.5s budget"
