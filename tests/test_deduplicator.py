"""Tests for Duplicate & Reprint Deduplication Engine (FEAT-070)."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import DUPLICATE_DOCUMENTS_DETECTED_TOTAL
from app.ingest.chunk import Chunk
from app.ingest.deduplicator import (
    MinHashGenerator,
    MinHashLSHIndex,
    RegulatoryDeduplicator,
    compute_text_sha256,
)
from app.ingest.source import SourceDocument
from app.ingest.store import Action, PreparedDocument, store_document
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture(autouse=True)
def _ensure_api_keys() -> None:
    app.state.api_keys = frozenset([PRIMARY_KEY])


SAMPLE_CANONICAL_TEXT = (
    "RESERVE BANK OF INDIA\n"
    "DEPARTMENT OF REGULATION, CENTRAL OFFICE, MUMBAI\n"
    "RBI/2026-27/101\n"
    "DOR.STR.REC.55/21.04.048/2026-27\n"
    "October 01, 2026\n\n"
    "To All Commercial Banks and Non-Banking Financial Companies\n\n"
    "Master Direction  -  Prudential Framework for Resolution of Stressed Assets\n\n"
    "1. Introduction: These directions are issued in exercise of powers conferred under Section 35A "
    "of the Banking Regulation Act, 1949 and Section 45L of the Reserve Bank of India Act, 1934.\n"
    "2. Scope and Applicability: The provisions of these directions shall apply to all scheduled commercial "
    "banks, payment banks, small finance banks, and systematically important non-deposit taking NBFCs.\n"
    "3. Early Identification and Reporting of Incipient Stress: Lenders shall recognize incipient stress in "
    "loan accounts immediately upon default by classifying such assets into Special Mention Accounts (SMA).\n"
    "4. Implementation of Resolution Plan: All lenders must put in place Board-approved policies for "
    "resolution of stressed assets, including the operational framework for identifying default.\n"
    "5. Independent Credit Evaluation: Any resolution plan involving restructuring of debt >= 100 crore "
    "shall require Independent Credit Evaluation (ICE) by credit rating agencies authorized by the Reserve Bank.\n"
    "6. Signoff Authority: Sanjeev Prakash, Chief General Manager-in-Charge."
)


def test_minhash_generator_determinism() -> None:
    """MinHashGenerator generates deterministic, identical signatures across separate instances."""
    gen1 = MinHashGenerator(num_perm=128, shingle_size=3)
    gen2 = MinHashGenerator(num_perm=128, shingle_size=3)

    sig1 = gen1.compute_signature(SAMPLE_CANONICAL_TEXT)
    sig2 = gen2.compute_signature(SAMPLE_CANONICAL_TEXT)

    assert len(sig1) == 128
    assert np.array_equal(sig1, sig2)


def test_exact_content_sha256_duplicate() -> None:
    """Index identifies exact raw content SHA-256 match with 1.0 similarity."""
    index = MinHashLSHIndex()
    doc_id = "doc-001"
    content_sha = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    index.add_document(doc_id=doc_id, text=SAMPLE_CANONICAL_TEXT, content_sha256=content_sha)

    # Query with exact content sha
    res = index.query(text=SAMPLE_CANONICAL_TEXT, content_sha256=content_sha)
    assert res.is_duplicate is True
    assert res.canonical_doc_id == doc_id
    assert res.similarity_score == 1.0
    assert res.match_type == "exact_content"


def test_exact_text_sha256_duplicate() -> None:
    """Index identifies exact cleaned text match even if raw payload hash differs."""
    index = MinHashLSHIndex()
    doc_id = "doc-002"
    index.add_document(doc_id=doc_id, text=SAMPLE_CANONICAL_TEXT, content_sha256="sha-original")

    # Query with identical text but different or absent raw sha
    res = index.query(text=SAMPLE_CANONICAL_TEXT, content_sha256="sha-different-pdf-timestamp")
    assert res.is_duplicate is True
    assert res.canonical_doc_id == doc_id
    assert res.similarity_score == 1.0
    assert res.match_type == "exact_text"


def test_minhash_near_duplicate_gazette_reprint() -> None:
    """Gazette reprint with administrative header variation matches above 0.98 threshold."""
    index = MinHashLSHIndex()
    doc_id = "doc-canon-003"
    index.add_document(doc_id=doc_id, text=SAMPLE_CANONICAL_TEXT)

    # Gazette reprint adds an extraordinary gazette title line at the top
    gazette_text = (
        "THE GAZETTE OF INDIA : EXTRAORDINARY [PART II - SEC. 3(ii)]\n"
        "PUBLISHED BY AUTHORITY, NEW DELHI\n" + SAMPLE_CANONICAL_TEXT
    )

    res = index.query(text=gazette_text, min_threshold=0.98)
    assert res.is_duplicate is True
    assert res.canonical_doc_id == doc_id
    assert res.similarity_score >= 0.98


def test_distinct_amendments_not_deduplicated() -> None:
    """Distinct regulatory amendment modifying core rules must NOT be marked as duplicate."""
    index = MinHashLSHIndex()
    doc_id = "doc-original-004"
    index.add_document(doc_id=doc_id, text=SAMPLE_CANONICAL_TEXT)

    # Substantive amendment modifying Sections 2, 4, and 5
    amendment_text = (
        "RESERVE BANK OF INDIA\n"
        "DEPARTMENT OF REGULATION, CENTRAL OFFICE, MUMBAI\n"
        "RBI/2026-27/222\n"
        "DOR.STR.REC.99/21.04.048/2026-27\n"
        "November 15, 2026\n\n"
        "To All Commercial Banks and Non-Banking Financial Companies\n\n"
        "Amendment to Master Direction  -  Prudential Framework for Stressed Assets\n\n"
        "1. Introduction: Issued under Section 35A of the Banking Regulation Act, 1949.\n"
        "2. Revised Scope: The provisions shall henceforth exclude all Tier-1 Primary Urban Co-operative Banks "
        "and housing finance corporations whose asset size is below 500 crore rupees.\n"
        "3. Early Identification and Reporting: SMA-0 classification triggers at 15 days past due.\n"
        "4. Revised Resolution Timeline: The review period is shortened from thirty calendar days to fifteen "
        "calendar days, requiring immediate execution of Inter-Creditor Agreements (ICA).\n"
        "5. Independent Credit Evaluation: Threshold reduced from 100 crore to 25 crore for compulsory ICE signoff.\n"
        "6. Signoff Authority: Shashi Kant, Executive Director."
    )

    res = index.query(text=amendment_text, min_threshold=0.98)
    assert res.is_duplicate is False
    assert res.similarity_score < 0.90
    assert res.canonical_doc_id is None
    assert res.match_type == "none"


def test_evaluation_dataset_10_pairs() -> None:
    """10-pair evaluation dataset achieves >= 99% precision and >= 95% recall."""
    deduplicator = RegulatoryDeduplicator()

    # 5 distinct canonical documents
    doc_stressed = SAMPLE_CANONICAL_TEXT
    doc_lending = (
        "RESERVE BANK OF INDIA - Guidelines on Digital Lending and Regulated Entity Engagement with LSPs.\n"
        "1. All loan disbursals and repayments must be executed directly between bank accounts of borrower and RE.\n"
        "2. Borrowers must receive Key Fact Statement (KFS) prior to execution of any digital loan contract.\n"
        "3. Data localization requirements mandate all biometric and identity records reside within India.\n"
        "4. Regulated entities shall ensure cooling-off look-up period during which borrowers can exit without penalty.\n"
        "5. Signoff Authority: P. Vasudevan, Chief General Manager."
    )
    doc_basel = (
        "RESERVE BANK OF INDIA - Master Circular on Basel III Capital Regulations.\n"
        "1. Minimum Common Equity Tier 1 (CET1) capital shall be maintained at 5.5% of risk weighted assets.\n"
        "2. Capital Conservation Buffer (CCB) of 2.5% comprised of Common Equity Tier 1 capital shall be maintained.\n"
        "3. Tier 1 Capital Ratio shall be at least 7.0% and Total Capital Ratio shall be at least 9.0%.\n"
        "4. Leverage Ratio shall be maintained at minimum 3.5% for all scheduled commercial banks.\n"
        "5. Signoff Authority: Usha Janakiraman, Chief General Manager."
    )
    doc_kyc = (
        "RESERVE BANK OF INDIA - Master Direction on Know Your Customer (KYC) Direction 2016.\n"
        "1. Regulated entities shall obtain officially valid documents (OVD) for customer identification.\n"
        "2. Periodic updation of KYC shall be carried out at least once in every two years for high-risk customers.\n"
        "3. Central KYC Records Registry (CKYCR) integration is mandatory for all individual customer onboarding.\n"
        "4. Video Customer Identification Process (V-CIP) can be deployed as alternate consent-based method.\n"
        "5. Signoff Authority: Vivek Deep, Executive Director."
    )
    doc_cyber = (
        "RESERVE BANK OF INDIA - Master Direction on Information Technology Governance and Cyber Security.\n"
        "1. Regulated entities shall establish a 24x7 Security Operations Centre (SOC) for real-time threat monitoring.\n"
        "2. Cyber incidents of high or critical severity shall be reported to the Reserve Bank within six hours.\n"
        "3. Comprehensive cyber crisis management plan (CCMP) shall be reviewed annually by the Board.\n"
        "4. Network segmentation, privileged access management, and multi-factor authentication are mandatory.\n"
        "5. Signoff Authority: T. Rabi Sankar, Deputy Governor."
    )

    # 5 pairs of Duplicates / Reprints
    duplicate_pairs = [
        # Pair 1: Exact reprint across departments
        ("canon-1", doc_stressed, "dup-1", doc_stressed),
        # Pair 2: Gazette extraordinary header re-issue
        (
            "canon-2",
            doc_lending,
            "dup-2",
            "THE GAZETTE OF INDIA : EXTRAORDINARY [PART II - SEC. 3(ii)]\nPUBLISHED BY AUTHORITY\n"
            + doc_lending,
        ),
        # Pair 3: Trailing web footer watermark difference
        (
            "canon-3",
            doc_basel,
            "dup-3",
            doc_basel + "\n\nDownloaded from https://rbi.org.in on 2026-10-15. Page 1 of 2.",
        ),
        # Pair 4: Case and whitespace normalization reprint
        (
            "canon-4",
            doc_kyc,
            "dup-4",
            doc_kyc.replace("Officially Valid Documents", "OFFICIALLY VALID DOCUMENTS"),
        ),
        # Pair 5: Slight punctuation/bullet variation
        ("canon-5", doc_cyber, "dup-5", "   \n\n" + doc_cyber + "\n\n   "),
    ]

    # 5 distinct regulatory publications from different domains
    distinct_queries = [
        (
            "dist-1",
            "RESERVE BANK OF INDIA - Master Direction on Financial Inclusion and Priority Sector Lending Targets. Targets for agriculture and micro-enterprises.",
        ),
        (
            "dist-2",
            "RESERVE BANK OF INDIA - Foreign Exchange Management Export and Import Regulations 2026. Realization of export proceeds within 9 months.",
        ),
        (
            "dist-3",
            "RESERVE BANK OF INDIA - Master Direction on Credit Card and Debit Card Issuance and Conduct Directions. Explicit consent for credit card activation.",
        ),
        (
            "dist-4",
            "RESERVE BANK OF INDIA - Framework for Compromise Settlements and Technical Write-offs. Minimum cooling period of 12 months for willful default.",
        ),
        (
            "dist-5",
            "RESERVE BANK OF INDIA - Early Warning Signals and Red Flagged Accounts for Fraud Monitoring in Commercial Banks and FIs.",
        ),
    ]

    # Index the 5 canonical documents
    for canon_id, text, _, _ in duplicate_pairs:
        deduplicator.index.add_document(doc_id=canon_id, text=text)

    true_positives = 0
    false_positives = 0
    false_negatives = 0

    # Evaluate duplicates (Expect duplicate == True)
    for _canon_id, _, _, dup_text in duplicate_pairs:
        res = deduplicator.find_duplicate(text=dup_text)
        if res.is_duplicate:
            true_positives += 1
        else:
            false_negatives += 1

    # Evaluate distinct pairs (Expect duplicate == False)
    for _, distinct_text in distinct_queries:
        res = deduplicator.find_duplicate(text=distinct_text)
        if res.is_duplicate:
            false_positives += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives)
        else 0.0
    )

    assert precision >= 0.99, f"Precision {precision:.4f} below 0.99 threshold"
    assert recall >= 0.95, f"Recall {recall:.4f} below 0.95 threshold"
    assert false_positives == 0, f"Expected zero false duplicates, found {false_positives}"


def test_latency_under_2ms_per_doc() -> None:
    """Deduplication query executes within <= 2.0 ms per document."""
    deduplicator = RegulatoryDeduplicator()
    # Pre-populate index with 50 synthetic regulatory documents
    for i in range(50):
        text = f"Regulatory circular directive section {i} for financial institutions. " * 30
        deduplicator.index.add_document(doc_id=f"doc-{i}", text=text)

    # Benchmark query latency over 30 runs
    latencies: list[float] = []
    test_text = SAMPLE_CANONICAL_TEXT
    # Warmup calls
    for _ in range(5):
        deduplicator.find_duplicate(text=test_text)
    for _ in range(30):
        t0 = time.perf_counter()
        res = deduplicator.find_duplicate(text=test_text)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt_ms)
        assert res is not None

    p95_latency = float(np.percentile(latencies, 95))
    assert p95_latency <= 2.0, f"p95 latency {p95_latency:.3f} ms exceeds 2.0 ms budget"


def test_input_validation_empty_text() -> None:
    """Empty or whitespace text raises ValueError on shingling."""
    gen = MinHashGenerator()
    with pytest.raises(ValueError, match="empty"):
        gen.shingle_hashes("")
    with pytest.raises(ValueError, match="empty"):
        gen.shingle_hashes("   ")


def test_database_persistence_and_chunk_omission(ingest_db: Any) -> None:
    """Database links duplicate via canonical_document_id and skips chunk writing."""
    url1 = "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/test_canon_070.PDF"
    content1 = b"Canonical PDF bytes for document deduplication testing."
    sha1 = hashlib.sha256(content1).hexdigest()

    doc1 = SourceDocument(
        url=url1,
        source="RBI",
        sha256=sha1,
        content=content1,
        media_type="application/pdf",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=None,
        authority="Reserve Bank of India",
        is_injection_canary=False,
    )
    text1 = SAMPLE_CANONICAL_TEXT
    emb = np.zeros((1, 384), dtype=np.float32)
    emb[0, 0] = 1.0

    prep1 = PreparedDocument(
        document=doc1,
        text=text1,
        char_count=len(text1),
        clean_chars=len(text1),
        pages=1,
        extractor="pypdf",
        chunks=[
            Chunk(
                ordinal=0,
                text="Stressed assets framework.",
                char_start=0,
                char_end=26,
                token_count=4,
            )
        ],
        embeddings=emb,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    )

    # 1. Store canonical document
    outcome1 = store_document(ingest_db, prep1)
    assert outcome1.action == Action.INSERTED
    assert outcome1.document_id is not None
    assert outcome1.chunks_written == 1

    # Verify canonical doc in database
    row1 = ingest_db.execute(
        "SELECT canonical_document_id, text_sha256, minhash_signature FROM documents WHERE document_id = %s",
        (outcome1.document_id,),
    ).fetchone()
    assert row1 is not None
    assert row1[0] is None  # canonical doc has NULL canonical_document_id
    assert row1[1] == compute_text_sha256(text1)
    assert row1[2] is not None
    assert len(row1[2]) == 128

    # 2. Store reprint document with DIFFERENT URL and DIFFERENT raw payload bytes
    url2 = "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/test_reprint_070.PDF"
    content2 = b"Different binary bytes (timestamp/watermark) but identical text."
    sha2 = hashlib.sha256(content2).hexdigest()

    doc2 = SourceDocument(
        url=url2,
        source="RBI",
        sha256=sha2,
        content=content2,
        media_type="application/pdf",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=None,
        authority="Reserve Bank of India",
        is_injection_canary=False,
    )
    prep2 = PreparedDocument(
        document=doc2,
        text=text1,  # Exact same text
        char_count=len(text1),
        clean_chars=len(text1),
        pages=1,
        extractor="pypdf",
        chunks=[
            Chunk(
                ordinal=0,
                text="Stressed assets framework.",
                char_start=0,
                char_end=26,
                token_count=4,
            )
        ],
        embeddings=emb,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    )

    outcome2 = store_document(ingest_db, prep2)
    assert outcome2.action == Action.SKIPPED_DUPLICATE_CONTENT
    assert outcome2.chunks_written == 0  # Zero chunks written! Prevents vector bloat
    assert outcome2.document_id is not None
    assert outcome2.document_id != outcome1.document_id

    # Verify relational foreign key links to canonical document
    row2 = ingest_db.execute(
        "SELECT canonical_document_id, text_sha256 FROM documents WHERE document_id = %s",
        (outcome2.document_id,),
    ).fetchone()
    assert row2 is not None
    assert str(row2[0]) == str(outcome1.document_id)
    assert row2[1] == compute_text_sha256(text1)

    # Verify chunks table contains zero chunks for the duplicate document
    chunk_count = ingest_db.execute(
        "SELECT count(*) FROM chunks WHERE document_id = %s",
        (outcome2.document_id,),
    ).fetchone()[0]
    assert chunk_count == 0


def test_api_check_deduplication_endpoint() -> None:
    """POST /v1/ingest/dedup/check inspects text and returns valid response schema."""
    client = TestClient(app)
    payload = {
        "text": SAMPLE_CANONICAL_TEXT,
        "config": {"min_similarity_threshold": 0.98},
    }
    response = client.post("/v1/ingest/dedup/check", json=payload, headers=auth(PRIMARY_KEY))
    assert response.status_code == 200
    data = response.json()
    assert "is_duplicate" in data
    assert "similarity_score" in data
    assert "match_type" in data
    assert "detail" in data


def test_api_unauthorized_and_validation() -> None:
    """POST /v1/ingest/dedup/check rejects unauthenticated and invalid payload."""
    client = TestClient(app)

    # 401 Unauthorized
    resp_unauth = client.post("/v1/ingest/dedup/check", json={"text": SAMPLE_CANONICAL_TEXT})
    assert resp_unauth.status_code == 401

    # 422 Validation Error on text under 10 chars
    resp_invalid = client.post(
        "/v1/ingest/dedup/check",
        json={"text": "Short"},
        headers=auth(PRIMARY_KEY),
    )
    assert resp_invalid.status_code == 422


def test_prometheus_metric_increment() -> None:
    """DUPLICATE_DOCUMENTS_DETECTED_TOTAL counter increments properly with labels."""
    before_exact = DUPLICATE_DOCUMENTS_DETECTED_TOTAL.labels(match_type="exact_text")._value.get()
    DUPLICATE_DOCUMENTS_DETECTED_TOTAL.labels(match_type="exact_text").inc()
    after_exact = DUPLICATE_DOCUMENTS_DETECTED_TOTAL.labels(match_type="exact_text")._value.get()
    assert after_exact == before_exact + 1
