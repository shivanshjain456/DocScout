"""Tests for ISO/NIST Clause Cross-Citation Hyperlinking (FEAT-046).

Verifies:
1. Ingestion-time entity extraction of international and national standards.
2. Span character offset precision and raw text match.
3. Control hint resolution (e.g., Annex A.5.15, Req 3.4, AC-1).
4. Evaluation benchmark over 10 circular texts with precision >= 98%.
5. Observability counter increments (docscout_standard_mentions_extracted_total).
6. Config toggle behavior (enabled=False).
7. Relational database persistence and retrieval.
"""

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import STANDARD_MENTIONS_EXTRACTED_TOTAL
from app.api.security import load_keys
from app.ingest.standard_mention_extractor import (
    StandardMentionConfig,
    StandardMentionExtractor,
    fetch_mentions_for_document,
    persist_mentions,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def extractor() -> StandardMentionExtractor:
    return StandardMentionExtractor()


# ---------------------------------------------------------------------------
# Unit Tests for Entity Extraction
# ---------------------------------------------------------------------------


def test_extracts_iso_27001_with_control_hint(extractor: StandardMentionExtractor) -> None:
    text = (
        "Regulated entities shall ensure adherence to ISO/IEC 27001 Annex A.5.15 "
        "regarding access control management."
    )
    mentions = extractor.extract(text)
    assert len(mentions) == 1
    m = mentions[0]
    assert "ISO" in m.raw_text
    assert m.standard_id in ("ISO/IEC 27001", "iso-iec-27001")
    assert m.control_hint is not None
    assert "A.5.15" in m.control_hint
    # Span must match raw_text exactly in the original string
    assert text[m.span[0] : m.span[1]] == m.raw_text


def test_extracts_nist_sp_800_53_with_control(extractor: StandardMentionExtractor) -> None:
    text = (
        "System boundaries must implement boundary protection as defined in "
        "NIST SP 800-53 Control SC-7 across all internal gateways."
    )
    mentions = extractor.extract(text)
    assert len(mentions) == 1
    m = mentions[0]
    assert "NIST" in m.raw_text
    assert m.standard_id in ("NIST SP 800-53", "nist-sp-800-53")
    assert m.control_hint is not None
    assert "SC-7" in m.control_hint
    assert text[m.span[0] : m.span[1]] == m.raw_text


def test_extracts_pci_dss_with_requirement(extractor: StandardMentionExtractor) -> None:
    text = (
        "Cardholder data environments must comply with PCI DSS 4.0 Requirement 3.4 "
        "for rendering primary account numbers unreadable."
    )
    mentions = extractor.extract(text)
    assert len(mentions) == 1
    m = mentions[0]
    assert "PCI" in m.raw_text
    assert m.standard_id in ("PCI DSS 4.0", "pci-dss-4.0")
    assert m.control_hint is not None
    assert "3.4" in m.control_hint
    assert text[m.span[0] : m.span[1]] == m.raw_text


def test_extracts_rbi_cyber_security_framework(extractor: StandardMentionExtractor) -> None:
    text = (
        "Urban Co-operative Banks must align baseline cyber controls with the "
        "RBI Cyber Security Framework Section 4.2."
    )
    mentions = extractor.extract(text)
    assert len(mentions) == 1
    m = mentions[0]
    assert "RBI" in m.raw_text
    assert m.standard_id in ("rbi-cyber-security-framework", "RBI_CSF")
    assert text[m.span[0] : m.span[1]] == m.raw_text


def test_extracts_multiple_standards_in_single_paragraph(
    extractor: StandardMentionExtractor,
) -> None:
    text = (
        "Banks shall establish comprehensive ISMS in alignment with ISO 27001, "
        "secure card transactions following PCI-DSS v4.0 Req 8.2, and adopt "
        "incident response frameworks under NIST CSF 2.0."
    )
    mentions = extractor.extract(text)
    assert len(mentions) == 3

    # Mentions must be ordered by char_start ascending
    assert mentions[0].span[0] < mentions[1].span[0] < mentions[2].span[0]

    for m in mentions:
        assert text[m.span[0] : m.span[1]] == m.raw_text

    std_ids = {m.standard_id for m in mentions}
    assert any("27001" in s for s in std_ids)
    assert any("pci" in s.lower() for s in std_ids)
    assert any("csf" in s.lower() for s in std_ids)


def test_config_disabled_returns_empty_list() -> None:
    disabled_extractor = StandardMentionExtractor(config=StandardMentionConfig(enabled=False))
    text = "Entities must adhere to ISO/IEC 27001 and NIST SP 800-53."
    mentions = disabled_extractor.extract(text)
    assert mentions == []


def test_clean_text_without_standards_returns_empty_list(
    extractor: StandardMentionExtractor,
) -> None:
    text = "The commercial bank shall maintain minimum CRAR of 9% as specified."
    mentions = extractor.extract(text)
    assert mentions == []


def test_empty_or_whitespace_text_returns_empty_list(
    extractor: StandardMentionExtractor,
) -> None:
    assert extractor.extract("") == []
    assert extractor.extract("   \n\t  ") == []


# ---------------------------------------------------------------------------
# Evaluation Benchmark: 10 Circular Texts, Precision >= 98%
# ---------------------------------------------------------------------------

EVAL_10_CIRCULARS = [
    (
        "Circular 1: RBI Master Direction on IT Governance, Risk and Controls. "
        "Regulated entities are advised that cloud security baseline should adhere to ISO/IEC 27017 "
        "and data privacy controls under ISO/IEC 27018.",
        [("RBI", "IT Governance"), ("ISO", "27017"), ("ISO", "27018")],
    ),
    (
        "Circular 2: Digital Payment Security Controls. "
        "Card storage mechanisms must be strictly compliant with PCI DSS 4.0 Requirement 3.4.",
        [("PCI", "4.0")],
    ),
    (
        "Circular 3: Business Continuity Management for Financial Market Infrastructures. "
        "Disaster recovery sites shall be certified under ISO 22301 Clause 8.4.",
        [("ISO", "22301")],
    ),
    (
        "Circular 4: Cyber Resilience Framework for Stock Exchanges. "
        "Security Operations Centres (SOC) shall establish threat hunting based on NIST SP 800-53 Rev. 5.",
        [("NIST", "800-53")],
    ),
    (
        "Circular 5: Baseline Cyber Security Controls for Small Finance Banks. "
        "Entities must implement Annex 1 controls of the RBI Cyber Security Framework.",
        [("RBI", "Cyber Security Framework")],
    ),
    (
        "Circular 6: Artificial Intelligence and Machine Learning in Financial Services. "
        "Governance committees should review model verification in line with ISO/IEC 42001 and NIST AI RMF 1.0.",
        [("ISO", "42001"), ("NIST", "AI RMF")],
    ),
    (
        "Circular 7: Guidelines on Information Security Audit. "
        "Internal audit shall benchmark cryptographic controls against FIPS 140-3 validation requirements.",
        [("FIPS", "140-3")],
    ),
    (
        "Circular 8: Web Accessibility Mandate for Banking Portals. "
        "Customer-facing portals must achieve Level AA conformance with WCAG 2.2.",
        [("WCAG", "2.2")],
    ),
    (
        "Circular 9: Outsourcing of Information Technology Services. "
        "Third-party service providers must provide SOC 2 Type II compliance reports annually.",
        [("SOC", "2")],
    ),
    (
        "Circular 10: Basel Committee Guidance on Operational Resilience. "
        "Principles for operational resilience complement risk metrics under Basel III framework.",
        [("Basel", "III")],
    ),
]


def test_eval_dataset_10_circulars_precision_benchmark(
    extractor: StandardMentionExtractor,
) -> None:
    total_expected = sum(len(expected) for _, expected in EVAL_10_CIRCULARS)
    correct_matches = 0
    false_positives = 0

    for text, expected_standards in EVAL_10_CIRCULARS:
        mentions = extractor.extract(text)
        for m in mentions:
            # Check raw span exactness
            assert text[m.span[0] : m.span[1]] == m.raw_text

            matched = False
            for exp_token1, exp_token2 in expected_standards:
                if exp_token1.lower() in m.raw_text.lower() and (
                    exp_token2.lower() in m.raw_text.lower()
                    or exp_token2.lower() in m.standard_id.lower()
                ):
                    matched = True
                    break
            if matched:
                correct_matches += 1
            else:
                false_positives += 1

    precision = (
        correct_matches / (correct_matches + false_positives)
        if (correct_matches + false_positives) > 0
        else 0.0
    )
    recall = correct_matches / total_expected

    assert precision >= 0.98, f"Precision was {precision:.4f}, required >= 0.98"
    assert recall >= 0.90, f"Recall was {recall:.4f}, expected high coverage"


def test_prometheus_metric_increments(extractor: StandardMentionExtractor) -> None:
    # Read initial counter value if present
    text = "Mandatory compliance with ISO/IEC 27001 is required."
    sample_before = STANDARD_MENTIONS_EXTRACTED_TOTAL.labels(
        standard_id="ISO/IEC 27001"
    )._value.get()
    extractor.extract(text)
    sample_after = STANDARD_MENTIONS_EXTRACTED_TOTAL.labels(
        standard_id="ISO/IEC 27001"
    )._value.get()
    assert sample_after == sample_before + 1.0


# ---------------------------------------------------------------------------
# Database Persistence Integration Test
# ---------------------------------------------------------------------------


def test_database_persistence_and_fetch(
    db: psycopg.Connection, extractor: StandardMentionExtractor
) -> None:
    doc_id = str(uuid.uuid4())
    # Insert a dummy document to satisfy foreign key constraint
    db.execute(
        """
        INSERT INTO documents (document_id, canonical_url, source, title)
        VALUES (%s, %s, %s, %s)
        """,
        (
            doc_id,
            f"https://rbi.org.in/test-mention-{doc_id}.pdf",
            "RBI",
            "Test Standard Mention Circular",
        ),
    )

    text = "Entities must comply with ISO/IEC 27001 Annex A.5.15 and NIST SP 800-53 Control AC-1."
    mentions = extractor.extract(text, doc_id=doc_id)
    assert len(mentions) == 2

    # Persist
    count = persist_mentions(db, doc_id, mentions)
    assert count == 2

    # Fetch
    fetched = fetch_mentions_for_document(db, doc_id)
    assert len(fetched) == 2
    f_stds = {f.standard_id for f in fetched}
    assert any("27001" in s for s in f_stds)
    assert any("800-53" in s for s in f_stds)

    # Validate offsets and control hints
    for f in fetched:
        assert f.span[0] >= 0
        assert f.span[1] > f.span[0]
        assert f.raw_text in text
        assert f.control_hint is not None


# ---------------------------------------------------------------------------
# API Endpoints Integration Tests
# ---------------------------------------------------------------------------


def test_api_extract_standard_mentions_endpoint() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)

    payload = {
        "text": "Entities must ensure adherence to ISO/IEC 27001 Annex A.5.15 and PCI DSS 4.0 Requirement 3.4.",
    }
    resp = client.post(
        "/v1/compliance/extract-standard-mentions",
        json=payload,
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_count"] == 2
    assert len(data["mentions"]) == 2
    stds = {m["standard_id"] for m in data["mentions"]}
    assert any("27001" in s for s in stds)
    assert any("PCI" in s or "pci" in s.lower() for s in stds)


def test_api_get_document_standard_mentions_invalid_uuid() -> None:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    client = TestClient(app)

    resp = client.get(
        "/v1/documents/not-a-valid-uuid/standard-mentions",
        headers=auth(PRIMARY_KEY),
    )
    assert resp.status_code == 400
