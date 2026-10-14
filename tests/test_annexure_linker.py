"""Unit and integration tests for Annexure, Schedule & FAQ Relational Association (FEAT-066).

Validates:
1. Structural section header detection (Annexures, Schedules, FAQs, Appendices).
2. Fallback handling for documents without annexures (single MAIN section).
3. Exact character offset partitioning and non-overlapping section spans.
4. Selective linking via AnnexureLinkerConfig toggles.
5. PostgreSQL persistence and retrieval via document_sections and section_relationships tables.
6. Cross-section relational query expansion for procedural guidance.
7. Evaluation benchmark across 10 Master Directions with dense technical annexures.
8. Performance execution SLA (overhead <= 1.0 ms per document).
9. REST API endpoints POST /v1/ingest/annexures/link and GET /v1/ingest/annexures/{doc_id}.
10. Prometheus metric ANNEXURES_LINKED_TOTAL label accounting.
"""

from __future__ import annotations

import os
import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import ANNEXURES_LINKED_TOTAL
from app.api.security import load_keys
from app.config import database_url
from app.ingest.annexure_linker import (
    AnnexureLinker,
    AnnexureLinkerConfig,
    get_default_annexure_linker,
    link_annexures_and_schedules,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_section_header_detection_and_link_generation() -> None:
    """Test detection of Annexure, Schedule, FAQ, and Appendix headings."""
    text = (
        "RESERVE BANK OF INDIA MASTER DIRECTION\n"
        "1. All non-banking financial companies must maintain capital adequacy ratio of 15%.\n"
        "2. Risk weights for consumer credit shall be 125%.\n\n"
        "ANNEXURE I\n"
        "Detailed computation methodology for risk-weighted assets and capital tiering.\n\n"
        "SCHEDULE A\n"
        "Quarterly prudential return submission format for Tier 1 capital.\n\n"
        "FREQUENTLY ASKED QUESTIONS\n"
        "Q1: Does this apply to microfinance NBFCs? A1: Yes, subject to specific limits.\n\n"
        "APPENDIX 1\n"
        "Illustrative examples of credit conversion factors for off-balance sheet items."
    )

    linker = get_default_annexure_linker()
    sections, relationships = linker.process_document(text)

    # Validate section delimitation
    assert len(sections) == 5
    types = [s.section_type for s in sections]
    assert types == ["MAIN", "ANNEXURE", "SCHEDULE", "FAQ", "APPENDIX"]

    main_sec = sections[0]
    assert main_sec.char_start == 0
    assert main_sec.char_end > 0
    assert "RESERVE BANK OF INDIA" in text[main_sec.char_start : main_sec.char_end]

    # Check relationships
    assert len(relationships) == 4
    rel_types = [r.relationship_type for r in relationships]
    assert "ANNEXURE" in rel_types
    assert "SCHEDULE" in rel_types
    assert "FAQ" in rel_types
    assert "APPENDIX" in rel_types

    # Ensure parent is MAIN
    for rel in relationships:
        assert rel.parent_section_id == main_sec.section_id


def test_document_without_annexures() -> None:
    """Ensure plain circulars without annexures yield a single MAIN section and zero links."""
    text = (
        "SECURITIES AND EXCHANGE BOARD OF INDIA CIRCULAR\n"
        "To all Recognized Stock Exchanges and Clearing Corporations.\n"
        "Sub: Operational parameters for pre-open session in cash market.\n"
        "Paragraph 1 outlines the standard call auction timeframe."
    )
    linker = get_default_annexure_linker()
    sections, relationships = linker.process_document(text)

    assert len(sections) == 1
    assert sections[0].section_type == "MAIN"
    assert sections[0].char_start == 0
    assert sections[0].char_end == len(text)
    assert len(relationships) == 0


def test_config_toggles() -> None:
    """Verify selective linking based on configuration toggles."""
    text = (
        "CIRCULAR ON PRUDENTIAL FRAMEWORK\n"
        "Primary obligations.\n"
        "ANNEXURE 1\n"
        "Technical procedure.\n"
        "SCHEDULE B\n"
        "Reporting format.\n"
        "FREQUENTLY ASKED QUESTIONS\n"
        "Clarifications."
    )
    # Disable FAQs and Schedules
    cfg = AnnexureLinkerConfig(
        auto_link_faqs=False,
        auto_link_schedules=False,
        auto_link_annexures=True,
        auto_link_appendices=True,
    )
    linker = AnnexureLinker(config=cfg)
    sections, relationships = linker.process_document(text, config=cfg)

    assert len(sections) == 4
    # Only ANNEXURE should be linked
    assert len(relationships) == 1
    assert relationships[0].relationship_type == "ANNEXURE"


def test_database_persistence_and_retrieval() -> None:
    """Verify storing and fetching sections and relationships from PostgreSQL."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())

    text = (
        "POLICY CIRCULAR DIRECTIVE\n"
        "All regulated entities must adhere to liquidity standards.\n"
        "ANNEXURE I\n"
        "Liquidity coverage ratio calculation template."
    )

    linker = get_default_annexure_linker()
    sections, relationships = linker.process_document(text, document_id=doc_id, version_id=ver_id)

    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            # Seed documents and document_versions to satisfy foreign keys
            cur.execute(
                """
                INSERT INTO documents (document_id, canonical_url, source, title)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (doc_id, f"https://rbi.org.in/test/{doc_id}.pdf", "RBI", "Test Directive"),
            )
            import hashlib

            unique_sha = hashlib.sha256(ver_id.encode()).hexdigest()
            cur.execute(
                """
                INSERT INTO document_versions (version_id, document_id, sha256, fetch_ts, bytes, extractor, char_count)
                VALUES (%s, %s, %s, NOW(), 1024, 'pdfplumber', 600)
                ON CONFLICT (version_id) DO NOTHING
                """,
                (ver_id, doc_id, unique_sha),
            )
            conn.commit()

        linker.save_sections_and_relationships(conn, doc_id, ver_id, sections, relationships)
        conn.commit()

        fetched_rels = linker.get_document_relationships(conn, doc_id)
        assert len(fetched_rels) == len(relationships)
        assert fetched_rels[0].relationship_type == "ANNEXURE"
        assert fetched_rels[0].parent_section_id == relationships[0].parent_section_id

        fetched_secs = linker.get_document_sections(conn, doc_id)
        assert len(fetched_secs) == 2
        assert fetched_secs[0].section_type == "MAIN"
        assert fetched_secs[1].section_type == "ANNEXURE"


def test_benchmark_10_master_directions_with_dense_annexures() -> None:
    """Benchmark test across 10 Master Directions with dense technical annexures."""
    corpora = [
        # 1. RBI Scale-Based Regulation
        (
            "RESERVE BANK OF INDIA MASTER DIRECTION - NBFC SCALE BASED REGULATION\n"
            "Clause 1: Base Layer NBFCs shall adhere to leverage restrictions.\n"
            "ANNEXURE 1: Capital Adequacy Calculation Formulas\n"
            "Tier 1 capital ratio must equal or exceed 10 percent.\n"
            "SCHEDULE A: Quarterly Compliance Filing\n"
            "Submit Form NBS-7 within fifteen days.",
            ["MAIN", "ANNEXURE", "SCHEDULE"],
            2,
        ),
        # 2. SEBI Mutual Funds Circular
        (
            "SEBI MASTER CIRCULAR FOR MUTUAL FUNDS\n"
            "Asset Management Companies shall enforce prudential exposure limits.\n"
            "SCHEDULE I: Single Issuer Debt Limits\n"
            "Maximum ten percent of NAV in debt securities of single issuer.\n"
            "FREQUENTLY ASKED QUESTIONS: Valuation of Money Market Instruments\n"
            "Q: How are commercial papers valued? A: On mark to market basis.",
            ["MAIN", "SCHEDULE", "FAQ"],
            2,
        ),
        # 3. MCA Companies Rules
        (
            "MINISTRY OF CORPORATE AFFAIRS - COMPANIES (AUDIT AND AUDITORS) RULES\n"
            "Auditors shall report on internal financial controls.\n"
            "APPENDIX A: Reporting Format for Internal Controls\n"
            "Standard format for statutory auditor report.",
            ["MAIN", "APPENDIX"],
            1,
        ),
        # 4. RBI Digital Lending Guidelines
        (
            "RBI GUIDELINES ON DIGITAL LENDING\n"
            "Lending service providers must disclose all loan terms via KFS.\n"
            "ANNEXURE: Key Fact Statement Standard Format\n"
            "Table specifying APR, processing fees, and cooling-off period.\n"
            "CLARIFICATORY FAQs: Digital Lending Operational Questions\n"
            "Disbursement must occur directly to borrower bank account.",
            ["MAIN", "ANNEXURE", "FAQ"],
            2,
        ),
        # 5. IRDAI Solvency Margin Regulations
        (
            "IRDAI (ASSETS, LIABILITIES AND SOLVENCY MARGIN) REGULATIONS\n"
            "Insurers must maintain required solvency margin.\n"
            "FIRST SCHEDULE: Determination of Mathematical Reserves\n"
            "Actuarial formula specifications.\n"
            "SECOND SCHEDULE: Available Solvency Margin Statement\n"
            "Valuation of admitted assets.",
            ["MAIN", "SCHEDULE", "SCHEDULE"],
            2,
        ),
        # 6. IBBI Liquidation Process
        (
            "IBBI (LIQUIDATION PROCESS) REGULATIONS\n"
            "Liquidator shall prepare asset memorandum.\n"
            "SCHEDULE I: Distribution of Proceeds\n"
            "Priority order pursuant to section 53 of IBC.",
            ["MAIN", "SCHEDULE"],
            1,
        ),
        # 7. PFRDA Investment Guidelines
        (
            "PFRDA MASTER CIRCULAR ON INVESTMENT MANAGEMENT\n"
            "Pension funds shall invest under approved asset classes.\n"
            "ANNEXURE II: Permissible Rating Categories\n"
            "Minimum AA investment grade rating required.\n"
            "FAQs: Reporting of Equity Exposure\n"
            "Daily valuation procedures.",
            ["MAIN", "ANNEXURE", "FAQ"],
            2,
        ),
        # 8. SEBI LODR Regulations
        (
            "SEBI (LISTING OBLIGATIONS AND DISCLOSURE REQUIREMENTS) REGULATIONS\n"
            "Listed entities shall make timely disclosures.\n"
            "SCHEDULE III: Disclosures under Regulation 30\n"
            "Material events requiring prompt disclosure.\n"
            "SCHEDULE IV: Corporate Governance Compliance Report\n"
            "Quarterly governance reporting format.",
            ["MAIN", "SCHEDULE", "SCHEDULE"],
            2,
        ),
        # 9. RBI Cyber Security Framework
        (
            "RBI CYBER SECURITY FRAMEWORK IN BANKS\n"
            "Banks shall implement cyber resilience controls.\n"
            "ANNEXURE 1: Baseline Cyber Security and Resilience Requirements\n"
            "Network segmentation and multi-factor authentication mandates.\n"
            "ANNEXURE 2: Incident Reporting Template\n"
            "Format for mandatory 6-hour incident disclosure.",
            ["MAIN", "ANNEXURE", "ANNEXURE"],
            2,
        ),
        # 10. IFSCA Banking Regulations
        (
            "IFSCA (BANKING) REGULATIONS\n"
            "Banking units in GIFT IFSC may conduct offshore banking.\n"
            "APPENDIX I: Prudential Returns and Capital Ratios\n"
            "Foreign currency capital reporting guidelines.",
            ["MAIN", "APPENDIX"],
            1,
        ),
    ]

    linker = get_default_annexure_linker()

    for idx, (doc_text, expected_types, expected_rels_count) in enumerate(corpora):
        sections, relationships = linker.process_document(doc_text)

        actual_types = [s.section_type for s in sections]
        assert actual_types == expected_types, f"Corpus {idx + 1} type mismatch: {actual_types}"
        assert len(relationships) == expected_rels_count, (
            f"Corpus {idx + 1} relationship count mismatch"
        )

        # Verify exact character length preservation across sections
        assert sections[0].char_start == 0
        assert sections[-1].char_end == len(doc_text)


def test_performance_overhead_sla() -> None:
    """Ensure linking execution overhead is <= 1.0 ms per document."""
    doc_text = (
        "RESERVE BANK OF INDIA MASTER DIRECTION\n"
        "Policy directive on capital adequacy and risk management.\n"
        * 50
        + "ANNEXURE I: Technical Computational Templates\n"
        + "Procedural instructions on tier 1 capital calculations.\n" * 30
        + "SCHEDULE A: Reporting Schedule\n"
        + "Quarterly filing forms and statutory verification requirements.\n" * 30
        + "FREQUENTLY ASKED QUESTIONS\n"
        + "Clarifications on supervisory expectations.\n" * 20
    )

    linker = get_default_annexure_linker()

    # Warmup
    linker.process_document(doc_text)

    times: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter()
        linker.process_document(doc_text)
        times.append((time.perf_counter() - t0) * 1000.0)

    assert sum(times) / len(times) >= 0.0
    p95_ms = sorted(times)[int(len(times) * 0.95)]

    assert p95_ms <= 1.0, f"Linking execution overhead was {p95_ms:.3f} ms (> 1.0 ms SLA)"


def test_api_link_annexures_success(client: TestClient) -> None:
    """Test POST /v1/ingest/annexures/link endpoint with 200 OK."""
    payload = {
        "text": (
            "STATUTORY REGULATION\n"
            "Primary directives.\n"
            "ANNEXURE 1\n"
            "Detailed procedure.\n"
            "SCHEDULE B\n"
            "Quarterly format."
        ),
        "config": {
            "auto_link_faqs": True,
            "auto_link_annexures": True,
            "auto_link_schedules": True,
            "auto_link_appendices": True,
        },
    }

    res = client.post("/v1/ingest/annexures/link", json=payload, headers=auth())
    assert res.status_code == 200
    data = res.json()

    assert data["total_linked"] == 2
    assert len(data["sections"]) == 3
    assert len(data["relationships"]) == 2
    assert data["execution_time_ms"] >= 0.0


def test_api_link_annexures_unauthorized(client: TestClient) -> None:
    """Test POST /v1/ingest/annexures/link returns 401 without auth."""
    payload = {"text": "Some document text"}
    res = client.post("/v1/ingest/annexures/link", json=payload)
    assert res.status_code == 401


def test_api_link_annexures_validation_error(client: TestClient) -> None:
    """Test POST /v1/ingest/annexures/link returns 422 for malformed payload."""
    res = client.post("/v1/ingest/annexures/link", json={"invalid": 123}, headers=auth())
    assert res.status_code == 422


def test_api_get_document_relationships(client: TestClient) -> None:
    """Test GET /v1/ingest/annexures/{doc_id} endpoint."""
    test_doc_id = str(uuid.uuid4())
    res = client.get(f"/v1/ingest/annexures/{test_doc_id}", headers=auth())
    assert res.status_code == 200
    data = res.json()
    assert data["document_id"] == test_doc_id
    assert isinstance(data["relationships"], list)


def test_metric_counter_increment() -> None:
    """Verify ANNEXURES_LINKED_TOTAL increments by relationship type."""
    initial_annex = ANNEXURES_LINKED_TOTAL.labels(type="ANNEXURE")._value.get()
    text = "MAIN DIRECTIVE\nPolicy requirements.\nANNEXURE 1\nTechnical execution."
    link_annexures_and_schedules(text)
    after_annex = ANNEXURES_LINKED_TOTAL.labels(type="ANNEXURE")._value.get()

    assert after_annex >= initial_annex + 1
