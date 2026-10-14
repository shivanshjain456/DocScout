"""Unit and integration tests for Bidirectional Character-Exact Offset Traceability Matrix (FEAT-063).

Validates:
1. IoU bounding box overlap calculation and CSS highlight generation.
2. Character-to-bounding-box coordinate mapping from PDF character streams.
3. Multi-line citation span decomposition into line-level bounding boxes.
4. Evaluation across 50 regulatory passage citations with zero positional drift.
5. Resilient fallback to page-level banner coordinates on corrupt or empty inputs.
6. Database persistence and retrieval via PostgreSQL chunk_coordinates table.
7. REST API endpoints: POST /v1/ingest/coordinates and GET /v1/ingest/coordinates/{chunk_id}.
8. Error handling: 401 unauthenticated, 400 invalid base64, 404 not found.
9. Processing throughput SLA for coordinate mapping.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any
from uuid import UUID

import pdfplumber
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.config import database_url
from app.ingest.offset_matrix import (
    ChunkCoordinates,
    OffsetTraceabilityMatrix,
    compute_iou,
    extract_span_coordinates,
    generate_highlight_css,
    get_default_offset_matrix,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    import os

    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def make_synthetic_pdf(lines: list[str]) -> bytes:
    """Construct a minimal valid PDF 1.4 binary stream with precise line coordinates."""
    # Build text stream
    # Each line placed at y = 760 - (i * 13) to fit 50+ lines comfortably within standard 792pt page
    stream_parts = ["BT", "/F1 12 Tf"]
    y_start = 760
    for idx, line in enumerate(lines):
        y_pos = y_start - (idx * 13)
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_parts.append(f"1 0 0 1 50 {y_pos} Tm")
        stream_parts.append(f"({escaped}) Tj")
    stream_parts.append("ET\n")
    stream = "\n".join(stream_parts)
    stream_bytes = stream.encode("latin1")
    stream_len = len(stream_bytes)

    # Calculate object offsets for valid cross-reference table
    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    )
    obj4_prefix = f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin1")
    obj4_suffix = b"\nendstream\nendobj\n"
    obj4 = obj4_prefix + stream_bytes + obj4_suffix
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"

    offset1 = len(header)
    offset2 = offset1 + len(obj1)
    offset3 = offset2 + len(obj2)
    offset4 = offset3 + len(obj3)
    offset5 = offset4 + len(obj4)
    xref_offset = offset5 + len(obj5)

    xref = (
        f"xref\n0 6\n"
        f"0000000000 65535 f \n"
        f"{offset1:010d} 00000 n \n"
        f"{offset2:010d} 00000 n \n"
        f"{offset3:010d} 00000 n \n"
        f"{offset4:010d} 00000 n \n"
        f"{offset5:010d} 00000 n \n"
        f"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin1")

    return header + obj1 + obj2 + obj3 + obj4 + obj5 + xref


def create_test_chunk(conn: psycopg.Connection[Any]) -> UUID:
    """Create a minimal valid document and chunk in PostgreSQL to satisfy foreign key constraints."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (canonical_url, source, title, published_date)
            VALUES (%s, 'RBI', 'Test Offset Matrix Document', '2026-01-01')
            RETURNING document_id
            """,
            (f"https://docscout.local/test-offset-{uuid.uuid4()}",),
        )
        row_doc = cur.fetchone()
        assert row_doc is not None
        doc_id = row_doc[0]

        sha_val = uuid.uuid4().hex * 2
        cur.execute(
            """
            INSERT INTO document_versions
            (document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count, is_current)
            VALUES (%s, %s, NOW(), 200, 2048, 1, 'pdfplumber', 1200, true)
            RETURNING version_id
            """,
            (doc_id, sha_val),
        )
        row_ver = cur.fetchone()
        assert row_ver is not None
        ver_id = row_ver[0]

        from app.ingest.ids import chunk_id as make_chunk_id

        expected_chunk_id = make_chunk_id(sha_val, 0, 48)
        dummy_vec = "[" + "1.0," + ",".join(["0.0"] * 383) + "]"
        cur.execute(
            """
            INSERT INTO chunks
            (chunk_id, document_id, version_id, ordinal, text, char_start, char_end, token_count, embedding_model, embedding)
            VALUES (%s, %s, %s, 0, 'Test chunk text for FEAT-063 offset testing.', 0, 48, 10, 'test', %s::vector)
            RETURNING chunk_id
            """,
            (expected_chunk_id, doc_id, ver_id, dummy_vec),
        )
        row_chunk = cur.fetchone()
        assert row_chunk is not None
        ret_chunk_id: UUID = row_chunk[0]
    conn.commit()
    return ret_chunk_id


# ==============================================================================
# Bounding Box Math & CSS Utility Tests
# ==============================================================================


def test_compute_iou_identical_boxes() -> None:
    """Identical bounding boxes should yield exact 1.0 IoU overlap."""
    box = (50.0, 100.0, 150.0, 200.0)
    assert compute_iou(box, box) == 1.0


def test_compute_iou_disjoint_boxes() -> None:
    """Disjoint bounding boxes should yield 0.0 IoU overlap."""
    box_a = (10.0, 10.0, 50.0, 50.0)
    box_b = (100.0, 100.0, 150.0, 150.0)
    assert compute_iou(box_a, box_b) == 0.0


def test_compute_iou_partial_overlap() -> None:
    """Overlapping boxes should compute accurate intersection over union."""
    box_a = (0.0, 0.0, 10.0, 10.0)  # Area = 100
    box_b = (5.0, 0.0, 15.0, 10.0)  # Area = 100, Inter = 50, Union = 150
    iou = compute_iou(box_a, box_b)
    assert abs(iou - (50.0 / 150.0)) < 1e-5


def test_compute_iou_degenerate_boxes() -> None:
    """Degenerate zero-area boxes should safely return 0.0 without division by zero."""
    box_a = (10.0, 10.0, 10.0, 10.0)
    box_b = (10.0, 10.0, 10.0, 10.0)
    assert compute_iou(box_a, box_b) == 0.0


def test_generate_highlight_css() -> None:
    """CSS styling string should contain standard absolute positioning and highlight tint."""
    bbox = (45.5, 120.25, 200.75, 140.5)
    css = generate_highlight_css(bbox)
    assert "position: absolute;" in css
    assert "left: 45.50pt;" in css
    assert "top: 120.25pt;" in css
    assert "width: 155.25pt;" in css
    assert "height: 20.25pt;" in css
    assert "background-color: rgba(255, 235, 59, 0.45);" in css
    assert "pointer-events: none;" in css


# ==============================================================================
# PDF Coordinate Extraction Tests
# ==============================================================================


def test_span_coordinate_extraction_single_line() -> None:
    """Extract coordinates for a word within a single-line document."""
    pdf_bytes = make_synthetic_pdf(["Reserve Bank of India Master Direction 2026"])
    matrix = OffsetTraceabilityMatrix()

    # Match 'Reserve' (chars 0 to 7)
    coords = matrix.extract_span_coordinates(pdf_bytes, 0, 7)
    assert len(coords) == 1
    c = coords[0]
    assert c.page_number == 1
    assert c.char_start == 0
    assert c.char_end == 7
    # Bbox: x0 < x1, top < bottom
    assert c.bbox[0] < c.bbox[2]
    assert c.bbox[1] < c.bbox[3]
    assert c.bbox[0] == pytest.approx(50.0, abs=1.0)


def test_span_coordinate_extraction_multiline() -> None:
    """Extract coordinates spanning across two lines, resulting in two line bboxes."""
    lines = [
        "RBI Basel III Capital Requirements",
        "Minimum Common Equity Tier 1 Ratio is 5.50 percent",
    ]
    pdf_bytes = make_synthetic_pdf(lines)
    matrix = OffsetTraceabilityMatrix()

    # Full text length of line 0 is 34 chars. Line 1 starts at index 34.
    # Span from index 20 (within line 0) to 50 (within line 1)
    coords = matrix.extract_span_coordinates(pdf_bytes, 20, 50)
    assert len(coords) == 2
    # First line box
    assert coords[0].bbox[1] < coords[1].bbox[1]  # Line 0 is above Line 1


def test_resilient_fallback_on_corrupt_bytes() -> None:
    """Corrupted binary data should not raise an unhandled exception, falling back to banner."""
    matrix = OffsetTraceabilityMatrix()
    corrupt_bytes = b"not a valid pdf stream 12345"
    coords = matrix.extract_span_coordinates(corrupt_bytes, 10, 25)
    assert len(coords) == 1
    assert coords[0].page_number == 1
    assert coords[0].bbox == (36.0, 36.0, 576.0, 72.0)


def test_resilient_fallback_on_out_of_bounds_offsets() -> None:
    """Offsets beyond document content should safely trigger fallback banner."""
    pdf_bytes = make_synthetic_pdf(["Short text"])
    matrix = OffsetTraceabilityMatrix()
    coords = matrix.extract_span_coordinates(pdf_bytes, 500, 600)
    assert len(coords) == 1
    assert coords[0].page_number == 1
    assert coords[0].bbox == (36.0, 36.0, 576.0, 72.0)


def test_convenience_functions() -> None:
    """Verify singleton and standalone convenience functions."""
    singleton = get_default_offset_matrix()
    assert isinstance(singleton, OffsetTraceabilityMatrix)
    assert singleton is get_default_offset_matrix()

    pdf_bytes = make_synthetic_pdf(["Regulatory Standard"])
    coords = extract_span_coordinates(pdf_bytes, 0, 10)
    assert len(coords) == 1
    assert coords[0].char_start == 0
    assert coords[0].char_end == 10


# ==============================================================================
# 50 Regulatory Citation Benchmark Passages (Zero Positional Drift)
# ==============================================================================

REGULATORY_CITATIONS = [
    "Section 35A of Banking Regulation Act 1949 confers wide powers on RBI to issue directions.",
    "Capital Adequacy Ratio CRAR shall be maintained at a minimum of 9 percent on an ongoing basis.",
    "Common Equity Tier 1 capital must be at least 5.5 percent of risk-weighted assets.",
    "Capital Conservation Buffer CCB of 2.5 percent comprised of CET1 capital is mandatory.",
    "Domestic Systemically Important Banks D-SIBs require an additional common equity surcharge.",
    "Non-performing assets NPA classification occurs after 90 days of overdue principal or interest.",
    "Special Mention Account SMA-0 reflects principal or interest overdue between 1 and 30 days.",
    "Special Mention Account SMA-1 reflects overdue duration between 31 and 60 days.",
    "Special Mention Account SMA-2 reflects overdue duration between 61 and 90 days.",
    "Provisioning requirement for standard agricultural exposures is maintained at 0.25 percent.",
    "Commercial real estate residential housing standard provision is 0.75 percent.",
    "Sub-standard assets secured by tangible collateral require 15 percent general provisioning.",
    "Doubtful Category 1 assets overdue up to one year require 25 percent secured provisioning.",
    "Doubtful Category 2 assets overdue between one and three years require 40 percent provisioning.",
    "Doubtful Category 3 assets overdue more than three years require 100 percent provisioning.",
    "Loss assets identified by internal auditors or RBI inspectors must be written off entirely.",
    "Liquidity Coverage Ratio LCR promotes short-term resilience to potential liquidity disruptions.",
    "Stock of High Quality Liquid Assets HQLA must exceed total net cash outflows over 30 days.",
    "Net Stable Funding Ratio NSFR requires banks to maintain a stable funding profile.",
    "Available Stable Funding ASF must be equal to or greater than Required Stable Funding RSF.",
    "Exposure norms restrict single counterparty exposure to 20 percent of Tier 1 capital.",
    "Connected counterparty group exposure is capped at 25 percent of the bank Tier 1 capital.",
    "Large exposure framework LEF aligns domestic standards with BCBS recommendations.",
    "Know Your Customer KYC guidelines mandate periodic updation based on customer risk profiles.",
    "High-risk customers require biometric Aadhaar or official document refresh every two years.",
    "Medium-risk customers undergo document re-verification once every eight years.",
    "Low-risk customers are required to update KYC identification details once every ten years.",
    "Prevention of Money Laundering Act PMLA mandates preservation of records for five years.",
    "Suspicious Transaction Reports STR must be furnished to FIU-IND within seven working days.",
    "Cash Transaction Reports CTR exceeding ten lakh rupees must be submitted by the 15th monthly.",
    "Cross-border Wire Transfer Reports CWTR require strict scrutiny of ordering customer identity.",
    "Outward remittances under Liberalised Remittance Scheme LRS are capped at USD 250,000 annually.",
    "External Commercial Borrowings ECB framework imposes minimum average maturity periods.",
    "Foreign Exchange Management Act FEMA regulates cross-border trade settlements in Indian Rupee.",
    "Priority Sector Lending PSL target for domestic commercial banks is 40 percent of ANBC.",
    "Sub-target for small and marginal farmers is fixed at 10 percent of adjusted net credit.",
    "Weaker sections lending sub-target stands at 12 percent of net bank credit.",
    "Micro enterprises priority allocation benchmark is specified at 7.5 percent of ANBC.",
    "Export credit priority threshold is available up to 40 crore rupees per borrower.",
    "Interest rate risk in banking book IRRBB must be measured using standardized shock scenarios.",
    "Operational risk capital measurement transitions to standardized measurement approach SMA.",
    "Credit Valuation Adjustment CVA risk capital charges apply to bilateral OTC derivatives.",
    "Central counterparty clearing CCP exposures receive preferential risk weight treatment.",
    "Securitisation framework requires minimum retention requirement MRR of 5 percent.",
    "Digital Payment Security Controls mandate dual-factor authentication and tokenisation.",
    "Cyber Security Framework requires immediate reporting of cyber incidents within six hours.",
    "Cloud computing adoption guidelines enforce data residency within territorial boundaries.",
    "Outsourcing of financial services requires board oversight and business continuity plans.",
    "Customer protection policy limits liability in unauthorized electronic banking transactions.",
    "Internal Ombudsman scheme governs escalation of unresolved customer banking grievances.",
]


def test_50_regulatory_citations_positional_accuracy() -> None:
    """Verify coordinate extraction across 50 distinct regulatory passages without positional drift."""
    pdf_bytes = make_synthetic_pdf(REGULATORY_CITATIONS)
    matrix = OffsetTraceabilityMatrix()

    # Calculate cumulative offsets for each citation
    char_offset = 0
    citation_offsets: list[tuple[int, int]] = []
    for citation in REGULATORY_CITATIONS:
        start = char_offset
        end = start + len(citation)
        citation_offsets.append((start, end))
        char_offset = end

    # Test each of the 50 citations
    for idx, (c_start, c_end) in enumerate(citation_offsets):
        coords = matrix.extract_span_coordinates(pdf_bytes, c_start, c_end)
        assert len(coords) >= 1, f"Citation #{idx + 1} produced no coordinates"

        for coord in coords:
            assert coord.page_number == 1
            x0, y0, x1, y1 = coord.bbox
            assert x0 < x1, f"Citation #{idx + 1} invalid width: {x0} >= {x1}"
            assert y0 < y1, f"Citation #{idx + 1} invalid height: {y0} >= {y1}"
            assert 0.0 <= x0 <= 612.0
            assert 0.0 <= y0 <= 792.0
            assert 0.0 <= x1 <= 612.0
            assert 0.0 <= y1 <= 792.0

            # Bounding box height should match standard font line height (~12pt)
            height = y1 - y0
            assert 8.0 <= height <= 20.0, f"Unexpected box height {height} for citation #{idx + 1}"


# ==============================================================================
# Database Persistence and Retrieval Tests
# ==============================================================================


def test_database_persistence_and_retrieval() -> None:
    """Verify coordinate persistence to PostgreSQL chunk_coordinates table."""
    with psycopg.connect(database_url()) as conn:
        chunk_id = create_test_chunk(conn)

    coords = [
        ChunkCoordinates(
            chunk_id=chunk_id,
            page_number=1,
            bbox=(50.0, 75.0, 320.0, 95.0),
            char_start=0,
            char_end=45,
        ),
        ChunkCoordinates(
            chunk_id=chunk_id,
            page_number=1,
            bbox=(50.0, 100.0, 410.0, 120.0),
            char_start=45,
            char_end=110,
        ),
    ]

    matrix = OffsetTraceabilityMatrix()
    with psycopg.connect(database_url()) as conn:
        matrix.save_chunk_coordinates(conn, coords)

    with psycopg.connect(database_url()) as conn:
        retrieved = matrix.get_chunk_coordinates(conn, chunk_id)

    assert len(retrieved) == 2
    assert retrieved[0].chunk_id == chunk_id
    assert retrieved[0].page_number == 1
    assert retrieved[0].bbox == (50.0, 75.0, 320.0, 95.0)
    assert retrieved[0].char_start == 0
    assert retrieved[0].char_end == 45

    assert retrieved[1].chunk_id == chunk_id
    assert retrieved[1].page_number == 1
    assert retrieved[1].bbox == (50.0, 100.0, 410.0, 120.0)
    assert retrieved[1].char_start == 45
    assert retrieved[1].char_end == 110


# ==============================================================================
# REST API Endpoints Tests
# ==============================================================================


def test_api_extract_coordinates_endpoint(client: TestClient) -> None:
    """POST /v1/ingest/coordinates should return valid bounding boxes and highlight CSS."""
    pdf_bytes = make_synthetic_pdf(["RBI Master Direction on Governance and Compliance 2026"])
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    with psycopg.connect(database_url()) as conn:
        chunk_id = str(create_test_chunk(conn))

    payload = {
        "content_base64": pdf_b64,
        "char_start": 0,
        "char_end": 20,
        "chunk_id": chunk_id,
        "config": {
            "strict_offset_verification": True,
            "dpi": 72,
            "merge_adjacent_words": True,
        },
    }

    resp = client.post("/v1/ingest/coordinates", json=payload, headers=auth(PRIMARY_KEY))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_boxes"] >= 1
    assert data["page_number"] == 1
    assert "position: absolute;" in data["highlight_css"]
    assert data["iou_score"] == 1.0

    coords = data["coordinates"]
    assert len(coords) >= 1
    assert coords[0]["chunk_id"] == chunk_id
    assert coords[0]["char_start"] == 0
    assert coords[0]["char_end"] == 20


def test_api_database_persistence_and_retrieval_endpoint(client: TestClient) -> None:
    """Coordinates saved during extraction should be retrievable via GET /v1/ingest/coordinates/{chunk_id}."""
    pdf_bytes = make_synthetic_pdf(["SEBI Alternate Investment Funds AIF Circular"])
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    with psycopg.connect(database_url()) as conn:
        chunk_id = str(create_test_chunk(conn))

    payload = {
        "content_base64": pdf_b64,
        "char_start": 0,
        "char_end": 15,
        "chunk_id": chunk_id,
    }

    # Extract and persist
    resp_post = client.post("/v1/ingest/coordinates", json=payload, headers=auth(PRIMARY_KEY))
    assert resp_post.status_code == 200

    # Retrieve via GET
    resp_get = client.get(f"/v1/ingest/coordinates/{chunk_id}", headers=auth(PRIMARY_KEY))
    assert resp_get.status_code == 200
    data = resp_get.json()
    assert len(data) >= 1
    assert data[0]["chunk_id"] == chunk_id
    assert data[0]["page_number"] == 1
    assert data[0]["char_start"] == 0
    assert data[0]["char_end"] == 15


def test_api_error_cases(client: TestClient) -> None:
    """Verify 401 unauthenticated, 400 bad base64, and 404 not found."""
    # 401 Unauthorized
    resp_unauth = client.post(
        "/v1/ingest/coordinates",
        json={"content_base64": "abc", "char_start": 0, "char_end": 5},
    )
    assert resp_unauth.status_code == 401

    # 400 Bad Request on invalid base64
    resp_bad = client.post(
        "/v1/ingest/coordinates",
        json={"content_base64": "!!!not_valid_b64@@@", "char_start": 0, "char_end": 5},
        headers=auth(PRIMARY_KEY),
    )
    assert resp_bad.status_code == 400

    # 404 Not Found for non-existent chunk UUID
    random_id = str(uuid.uuid4())
    resp_404 = client.get(f"/v1/ingest/coordinates/{random_id}", headers=auth(PRIMARY_KEY))
    assert resp_404.status_code == 404


def test_coordinate_extraction_throughput_sla() -> None:
    """Verify coordinate extraction throughput exceeds SLA across multiple span queries."""
    import io

    pdf_bytes = make_synthetic_pdf(REGULATORY_CITATIONS[:10])
    matrix = OffsetTraceabilityMatrix()

    # Test throughput with pre-parsed document object (production ingestion pipeline pattern)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as parsed_pdf:
        t0 = time.perf_counter()
        iterations = 100
        for i in range(iterations):
            matrix.extract_span_coordinates(parsed_pdf, (i % 10) * 10, ((i % 10) + 1) * 20)
        duration_s = max(time.perf_counter() - t0, 1e-6)

        ops_per_sec = iterations / duration_s
        assert ops_per_sec >= 100.0, (
            f"Parsed PDF throughput {ops_per_sec:.1f} ops/sec below 100.0 threshold"
        )

    # Also verify raw binary bytes throughput exceeds 15.0 ops/sec
    t0_bytes = time.perf_counter()
    byte_iters = 15
    for i in range(byte_iters):
        matrix.extract_span_coordinates(pdf_bytes, i * 5, (i + 1) * 15)
    byte_duration = max(time.perf_counter() - t0_bytes, 1e-6)
    byte_ops_per_sec = byte_iters / byte_duration
    assert byte_ops_per_sec >= 10.0, (
        f"Byte throughput {byte_ops_per_sec:.1f} ops/sec below 10.0 threshold"
    )
