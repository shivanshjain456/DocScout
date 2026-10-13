"""Unit and integration tests for Sunset Clause & Mandatory Cutover Alerting (FEAT-035).

Verifies:
1. Benchmark transition circular deadline extraction (CoFT cutover, T+1 settlement, PA net worth).
2. Date extraction precision >= 95%, recall >= 90%.
3. Regression guard: Zero false-positive historical dates tagged as future deadlines.
4. Excluded behavior: "to be notified separately" emits no speculative dates.
5. Input validation: Text non-empty, length >= 100 characters.
6. Urgency classification: CRITICAL (<=15d), WARNING (<=45d), INFO (>45d).
7. DeadlineNotifier integration: Countdown calculation and notification dispatch.
8. Performance: Deadline extraction latency <= 2.0 ms per document.
"""

from __future__ import annotations

import time
from datetime import date
from unittest.mock import MagicMock

import pytest

from app.digests.deadline_notifier import (
    DeadlineAlertConfig,
    DeadlineNotifier,
)
from app.ingest.deadline_extractor import (
    DeadlineExtractor,
    RegulatoryDeadline,
    extract_regulatory_deadlines,
)

# 15 Benchmark Transition Circular Excerpts (evaluation dataset per FEAT-035 spec)
BENCHMARK_TRANSITION_CIRCULARS = [
    {
        "doc_id": "doc-rbi-coft-2022",
        "text": (
            "Reserve Bank of India - Department of Payment and Settlement Systems. "
            "Card-on-File Tokenization (CoFT) implementation timeline. "
            "With a view to ensuring consumer data security, all regulated entities (REs) and "
            "authorized payment aggregators shall transition to Card-on-File Tokenization (CoFT). "
            "The timeline for implementation of CoFT guidelines is extended up to September 30, 2024. "
            "No entity in the card transaction flow other than card issuers and card networks shall "
            "store actual card details on or after October 01, 2024. All stakeholders are advised to comply."
        ),
        "reference_date": date(2024, 8, 15),
        "expected_dates": [date(2024, 9, 30), date(2024, 10, 1)],
    },
    {
        "doc_id": "doc-sebi-t1-settlement",
        "text": (
            "Securities and Exchange Board of India (SEBI) Circular on T+1 Settlement Cycle. "
            "In super-session of previous circulars on settlement mechanics, all listed securities "
            "shall transition by March 31, 2023 to the phased T+1 settlement mechanism. "
            "Stock exchanges, clearing corporations, and depositories shall ensure that all trades "
            "executed on and from April 01, 2023 shall settle on T+1 basis. Necessary infrastructure "
            "upgrades shall be operationalized immediately."
        ),
        "reference_date": date(2023, 1, 15),
        "expected_dates": [date(2023, 3, 31), date(2023, 4, 1)],
    },
    {
        "doc_id": "doc-rbi-pa-networth-stage1",
        "text": (
            "Guidelines for Regulation of Payment Aggregators and Payment Gateways. "
            "Existing Payment Aggregators (PAs) shall achieve a minimum net-worth of Rs. 15 crore "
            "by March 31, 2021 and a net-worth of Rs. 25 crore by March 31, 2023. "
            "Applications for authorization shall be submitted on or before September 30, 2021. "
            "Failure to achieve net-worth milestones will result in closure of operations."
        ),
        "reference_date": date(2020, 10, 1),
        "expected_dates": [date(2021, 3, 31), date(2021, 9, 30), date(2023, 3, 31)],
    },
    {
        "doc_id": "doc-rbi-outsourcing-cutover",
        "text": (
            "Master Direction on Outsourcing of Information Technology Services 2023. "
            "These directions shall come into force with effect from October 01, 2023. "
            "All existing outsourcing agreements shall be brought in conformity with these directions "
            "at the time of renewal or by March 31, 2024, whichever is earlier. Regulated entities shall "
            "submit compliance confirmation to the Reserve Bank accordingly."
        ),
        "reference_date": date(2023, 6, 1),
        "expected_dates": [date(2023, 10, 1), date(2024, 3, 31)],
    },
    {
        "doc_id": "doc-sebi-cyber-resilience-2024",
        "text": (
            "SEBI Framework on Cyber Security and Cyber Resilience for Qualified Registrars. "
            "All qualified registrar entities shall transition to the updated ISO 27001:2022 "
            "controls and zero-trust authentication framework. The mandatory cutover date is "
            "December 31, 2024. Regulated entities failing to comply shall face administrative sanctions."
        ),
        "reference_date": date(2024, 11, 1),
        "expected_dates": [date(2024, 12, 31)],
    },
    {
        "doc_id": "doc-rbi-lei-extension",
        "text": (
            "Legal Entity Identifier (LEI) for Large Value Transactions in Centralised Payment Systems. "
            "Non-individual borrowers with aggregate fund and non-fund exposure of Rs. 50 crore and above "
            "shall obtain LEI codes. Compliance shall be ensured on or before April 30, 2025. "
            "Banks shall not grant renewal or enhancement of credit facilities in absence of valid LEI."
        ),
        "reference_date": date(2025, 1, 1),
        "expected_dates": [date(2025, 4, 30)],
    },
    {
        "doc_id": "doc-rbi-sunset-legacy-cheque",
        "text": (
            "Standardization of Cheque Processing in Cheque Truncation System (CTS). "
            "The legacy non-CTS-2010 standard cheques shall sunset on December 31, 2025. "
            "With effect from January 01, 2026, no non-compliant instruments shall be accepted for "
            "clearing sessions across all regional grid hubs in Mumbai, Chennai, and New Delhi."
        ),
        "reference_date": date(2025, 6, 1),
        "expected_dates": [date(2025, 12, 31), date(2026, 1, 1)],
    },
    {
        "doc_id": "doc-sebi-algo-testing",
        "text": (
            "Testing and Audit of Algorithmic Trading Systems in Indian Stock Markets. "
            "Stock brokers utilizing algorithmic facilities shall complete independent system audits. "
            "All testing environments shall transition by June 30, 2025 to deterministic order simulation. "
            "The compliance certificate must be furnished on or before July 15, 2025 to the exchange."
        ),
        "reference_date": date(2025, 4, 1),
        "expected_dates": [date(2025, 6, 30), date(2025, 7, 15)],
    },
    {
        "doc_id": "doc-rbi-basel-lcr-phasein",
        "text": (
            "Basel III Framework on Liquidity Standards - Liquidity Coverage Ratio (LCR). "
            "Banks shall maintain minimum LCR of 90% by January 01, 2026 and shall achieve "
            "the full 100% calibration with effect from January 01, 2027. High Quality Liquid Assets (HQLA) "
            "computations shall adhere to Annex 1 specifications throughout the transition window."
        ),
        "reference_date": date(2025, 9, 1),
        "expected_dates": [date(2026, 1, 1), date(2027, 1, 1)],
    },
    {
        "doc_id": "doc-sebi-client-funds-upstream",
        "text": (
            "Upstreaming of Clients' Funds by Stock Brokers to Clearing Corporations. "
            "To safeguard investor interests, stock brokers shall upstream all unencumbered client funds. "
            "The revised operational mechanism shall come into force on November 01, 2023. "
            "No broker shall retain unallocated client ledger balances overnight beyond this milestone."
        ),
        "reference_date": date(2023, 9, 15),
        "expected_dates": [date(2023, 11, 1)],
    },
    {
        "doc_id": "doc-rbi-digital-lending-firstloss",
        "text": (
            "Regulatory Framework for Digital Lending - First Loss Default Guarantee (FLDG). "
            "Contractual arrangements between REs and Loan Service Providers for default loss guarantees "
            "shall conform to Section 4. Existing FLDG arrangements shall be regularized on or before "
            "August 20, 2024. Non-compliant default guarantee structures stand prohibited thereafter."
        ),
        "reference_date": date(2024, 7, 1),
        "expected_dates": [date(2024, 8, 20)],
    },
    {
        "doc_id": "doc-sebi-esg-disclosures-brsr",
        "text": (
            "Business Responsibility and Sustainability Reporting (BRSR) Core Requirements. "
            "Top 250 listed entities by market capitalization shall undergo mandatory reasonable assurance "
            "of BRSR Core. The mandatory cutover date for third-party ESG assurance is March 31, 2025. "
            "Subsequent tiers shall comply by March 31, 2026 as outlined in Schedule III."
        ),
        "reference_date": date(2024, 12, 1),
        "expected_dates": [date(2025, 3, 31), date(2026, 3, 31)],
    },
    {
        "doc_id": "doc-rbi-kyc-c-kyc-migration",
        "text": (
            "Master Direction - Know Your Customer (KYC) Direction, 2016 Amendments. "
            "Reporting entities shall upload KYC records of legal entities to CKYCR. "
            "The upload mechanism for all non-individual accounts opened from April 01, 2021 onwards "
            "shall transition by September 30, 2021. Compliance status shall be reviewed by the board."
        ),
        "reference_date": date(2021, 5, 1),
        "expected_dates": [date(2021, 9, 30)],
    },
    {
        "doc_id": "doc-rbi-cloud-security-baseline",
        "text": (
            "Cyber Security Controls for Third Party Cloud Computing Deployments. "
            "Banks adopting multi-tenant cloud hosting shall implement cryptographic key separation. "
            "All cloud service agreements shall come into force with effect from February 28, 2025. "
            "Continuous automated configuration audits must be active on or before March 15, 2025."
        ),
        "reference_date": date(2025, 1, 10),
        "expected_dates": [date(2025, 2, 28), date(2025, 3, 15)],
    },
    {
        "doc_id": "doc-sebi-odi-reporting-system",
        "text": (
            "Offshore Derivative Instruments (ODIs) Regulatory Reporting Architecture. "
            "Foreign Portfolio Investors (FPIs) issuing ODIs shall transition to automated API filing. "
            "The timeline for implementation is extended up to May 31, 2026. After this deadline, manual "
            "spreadsheet declarations will not be acknowledged by SEBI Market Regulation Department."
        ),
        "reference_date": date(2026, 2, 1),
        "expected_dates": [date(2026, 5, 31)],
    },
]


def test_input_validation() -> None:
    """Verifies that invalid or truncated document texts are rejected."""
    extractor = DeadlineExtractor()

    # Empty text
    with pytest.raises(ValueError, match="non-empty"):
        extractor.extract(text="", doc_id="doc-test-1")

    # Length < 100 characters
    short_text = "Reserve Bank circular. Cutover on 2025-01-01."
    with pytest.raises(ValueError, match="at least 100 characters"):
        extractor.extract(text=short_text, doc_id="doc-test-2")


def test_excluded_behavior_to_be_notified_separately() -> None:
    """SPEC EXCLUSION: Guessing cutover dates when text says 'to be notified separately' is forbidden."""
    text = (
        "Reserve Bank of India Master Circular on Capital Adequacy. "
        "The date of implementation for advanced internal rating-based approach (AIRB) for "
        "regional rural banks and small finance banks shall be notified separately. "
        "In the interim, all existing credit risk capital adequacy standards shall remain in force. "
        "No speculative cutover timeline shall be inferred by regulated entities."
    )
    extractor = DeadlineExtractor()
    deadlines = extractor.extract(text=text, doc_id="doc-rbi-unnotified")
    assert len(deadlines) == 0, (
        "Must not emit speculative dates when marked 'to be notified separately'"
    )


def test_zero_historical_false_positives() -> None:
    """REGRESSION LIMIT: Historical dates (e.g. past circular citations) must NOT be tagged as future deadlines."""
    historical_reference_text = (
        "Reserve Bank of India Circular RBI/2026-27/89. Reference is drawn to circular dated "
        "March 15, 2018 and circular dated July 01, 2020 on outsourcing of financial services. "
        "The committee constituted on November 10, 2016 submitted its report on January 05, 2017. "
        "All REs shall note that these past historical references are recorded for legislative history. "
        "New compliance reporting shall come into force with effect from December 31, 2026."
    )
    extractor = DeadlineExtractor()
    # Reference date is August 1, 2026. Only Dec 31, 2026 is future. 2016, 2017, 2018, 2020 are historical.
    deadlines = extractor.extract(
        text=historical_reference_text,
        doc_id="doc-rbi-history-ref",
        reference_date=date(2026, 8, 1),
    )

    assert len(deadlines) == 1
    assert deadlines[0].effective_date == date(2026, 12, 31)
    # Check that none of the past dates are present
    past_dates = {date(2018, 3, 15), date(2020, 7, 1), date(2016, 11, 10), date(2017, 1, 5)}
    for dl in deadlines:
        assert dl.effective_date not in past_dates
        assert dl.days_remaining >= 0


def test_urgency_banding() -> None:
    """Verifies CRITICAL (<=15d), WARNING (<=45d), and INFO (>45d) threshold assignment."""
    config = DeadlineAlertConfig(critical_threshold_days=15, warning_threshold_days=45)
    extractor = DeadlineExtractor(config=config)
    ref = date(2026, 10, 1)

    text_critical = (
        "Department of Payment and Settlement Systems directive. "
        "All regulated banks and payment aggregators shall transition by October 10, 2026. "
        "Immediate compliance reporting is mandatory before system shutoff. Full board oversight."
    )
    deadlines_crit = extractor.extract(text=text_critical, doc_id="doc-crit", reference_date=ref)
    assert len(deadlines_crit) == 1
    assert deadlines_crit[0].days_remaining == 9
    assert deadlines_crit[0].urgency_level == "CRITICAL"

    text_warning = (
        "Department of Payment and Settlement Systems directive. "
        "All regulated banks and payment aggregators shall transition by November 10, 2026. "
        "Operational readiness tests must be scheduled without delay. Full board oversight."
    )
    deadlines_warn = extractor.extract(text=text_warning, doc_id="doc-warn", reference_date=ref)
    assert len(deadlines_warn) == 1
    assert deadlines_warn[0].days_remaining == 40
    assert deadlines_warn[0].urgency_level == "WARNING"

    text_info = (
        "Department of Payment and Settlement Systems directive. "
        "All regulated banks and payment aggregators shall transition by December 31, 2026. "
        "Strategic architecture plans shall be submitted in due course. Full board oversight."
    )
    deadlines_info = extractor.extract(text=text_info, doc_id="doc-info", reference_date=ref)
    assert len(deadlines_info) == 1
    assert deadlines_info[0].days_remaining == 91
    assert deadlines_info[0].urgency_level == "INFO"


def test_benchmark_transition_circulars_precision_recall() -> None:
    """ACCEPTANCE CRITERIA: Extracts cutover dates from 100% of benchmark transition circulars.

    Threshold: Date extraction precision >= 95%, recall >= 90%.
    """
    extractor = DeadlineExtractor()

    total_expected = 0
    total_extracted = 0
    correctly_extracted = 0

    for item in BENCHMARK_TRANSITION_CIRCULARS:
        doc_id = item["doc_id"]
        text = item["text"]
        ref_date = item["reference_date"]
        expected_dates = set(item["expected_dates"])
        total_expected += len(expected_dates)

        results = extractor.extract(text=text, doc_id=doc_id, reference_date=ref_date)
        extracted_dates = {r.effective_date for r in results}
        total_extracted += len(extracted_dates)

        # Hits
        hits = extracted_dates.intersection(expected_dates)
        correctly_extracted += len(hits)

        # Ensure all expected dates were captured
        missing = expected_dates - extracted_dates
        assert not missing, f"Doc {doc_id} missed expected dates: {missing}"

    precision = correctly_extracted / total_extracted if total_extracted > 0 else 0.0
    recall = correctly_extracted / total_expected if total_expected > 0 else 0.0

    assert precision >= 0.95, f"Precision {precision:.4f} below threshold 0.95"
    assert recall >= 0.90, f"Recall {recall:.4f} below threshold 0.90"


def test_extraction_performance_budget() -> None:
    """PERFORMANCE LIMIT: Deadline extraction <= 2.0 ms per document."""
    extractor = DeadlineExtractor()
    sample = BENCHMARK_TRANSITION_CIRCULARS[0]
    text = sample["text"]
    doc_id = sample["doc_id"]
    ref_date = sample["reference_date"]

    # Warmup
    extractor.extract(text=text, doc_id=doc_id, reference_date=ref_date)

    iterations = 50
    t0 = time.perf_counter()
    for _ in range(iterations):
        extractor.extract(text=text, doc_id=doc_id, reference_date=ref_date)
    duration_per_call_ms = ((time.perf_counter() - t0) / iterations) * 1000.0

    assert duration_per_call_ms <= 2.0, (
        f"Extraction latency {duration_per_call_ms:.3f}ms exceeds 2.0ms SLO"
    )


def test_deadline_notifier_dispatch() -> None:
    """Verifies DeadlineNotifier alert dispatch, Brevo integration, and metrics."""
    mock_brevo = MagicMock()
    mock_brevo.send_transactional_email.return_value = {"messageId": "msg-cutover-123"}

    mock_pool = MagicMock()

    notifier = DeadlineNotifier(pool=mock_pool, brevo_client=mock_brevo)

    deadlines = [
        RegulatoryDeadline(
            doc_id="doc-rbi-coft",
            mandate_description="All REs shall transition by September 30, 2026",
            effective_date=date(2026, 9, 30),
            days_remaining=10,
            urgency_level="CRITICAL",
            extracted_snippet="transition by September 30, 2026",
        ),
        RegulatoryDeadline(
            doc_id="doc-sebi-t1",
            mandate_description="Mandatory cutover date is October 20, 2026",
            effective_date=date(2026, 10, 20),
            days_remaining=30,
            urgency_level="WARNING",
            extracted_snippet="cutover date is October 20, 2026",
        ),
    ]

    result = notifier.dispatch_alerts(
        deadlines=deadlines,
        recipients=["compliance-officer@enterprise.bank"],
        dry_run=False,
    )

    assert result.total_checked == 2
    assert result.alerts_dispatched == 2
    assert result.critical_count == 1
    assert result.warning_count == 1
    assert mock_brevo.send_transactional_email.call_count == 2


def test_convenience_function() -> None:
    """Verifies extract_regulatory_deadlines module-level helper."""
    text = (
        "Reserve Bank of India Master Direction on Payment Aggregators. "
        "All entities shall comply on or before December 31, 2026. "
        "No further extensions shall be granted by the regulatory board."
    )
    deadlines = extract_regulatory_deadlines(
        text=text,
        doc_id="doc-convenience",
        reference_date=date(2026, 1, 1),
    )
    assert len(deadlines) == 1
    assert deadlines[0].effective_date == date(2026, 12, 31)
