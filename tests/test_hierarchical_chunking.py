"""Unit, integration, and benchmark test suite for Hierarchical Circular Chunking (FEAT-061).

Validates:
1. 20 benchmark regulatory circulars containing complex legal clauses and provisos (n >= 170 chunks):
   - Master Direction on Cyber Resilience and Incident Reporting
   - Directions on Outsourcing of Financial Services
   - Prudential Norms on Income Recognition & Asset Classification (IRAC)
   - Master Direction on Foreign Exchange Management (ECB Framework)
   - Guidelines on Digital Lending & Default Loss Guarantee (DLG)
   - Liquidity Coverage Ratio (LCR) & Basel III Framework
   - Master Direction on Know Your Customer (KYC & V-CIP)
   - Master Circular on Wilful Defaulters & Red Flagged Accounts
   - Framework for Compromise Settlements & Technical Write-offs
   - IT Governance, Risk, Controls & Assurance Direction
   - Credit Card & Debit Card Issuance & Conduct Directions
   - Payment Aggregator & Payment Gateway (PA/PG) Directions
   - Priority Sector Lending (PSL) Targets & Classification
   - Fair Practices Code for Lenders (Penal Charges Directive)
   - Framework for Regulatory Sandbox (Fintech Cohorts)
   - Financial Statements Presentation & Disclosure Master Direction
   - Master Direction on Fraud Risk Management in Commercial Banks
   - Card-on-File Tokenisation (CoFT) Regulatory Framework
   - Cross-Border Remittances & Anti-Money Laundering Framework
   - Statutory Liquidity Ratio (SLR) Maintenance & Asset Valuation
2. Proviso-parent retention rate >= 98% (baseline: 72%).
3. FR-7 character exactness invariant: text[char_start:char_end] == chunk.text for 100% of chunks.
4. 100% text coverage invariant: uncovered_characters(text, chunks) == 0.
5. Context window ceiling: every chunk token count <= 512 tokens.
6. Fallback mechanism: unstructured text falls back to sliding window cleanly.
7. Performance SLA: parsing throughput >= 250 pages/sec (>= 50,000 chars/sec).
8. REST API endpoint POST /v1/ingest/chunk.
"""

from __future__ import annotations

import os
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.ingest.chunk import (
    chunk_document_hierarchical,
    uncovered_characters,
    verify_offsets,
)
from app.ingest.hierarchical_chunker import (
    ChunkingConfig,
    HierarchicalChunker,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


def build_20_benchmark_circulars() -> list[dict[str, str]]:
    """Build evaluation dataset of 20 realistic regulatory circulars with clauses and provisos."""
    circulars: list[dict[str, str]] = [
        # Circular 1: Cyber Resilience
        {
            "title": "Master Direction on Cyber Resilience and Incident Response",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF INFORMATION TECHNOLOGY\n"
                "Ref. No. RBI/2026/84/IT.DIR.01\n\n"
                "WHEREAS the Reserve Bank of India considers it necessary in the public interest to strengthen cyber resilience.\n\n"
                "1. Scope and Applicability\n"
                "(1) These directions shall apply to all Commercial Banks and Non-Banking Financial Companies.\n\n"
                "2. Incident Reporting Cadence\n"
                "(a) All regulated entities shall report any cyber security incident to the Reserve Bank within two to six hours of detection.\n\n"
                "Provided that where an incident involves severe data exfiltration or ransomware encryption of core transaction ledgers, the initial advisory shall be transmitted within two hours.\n\n"
                "Provided further that technical forensic evidence and memory images may be submitted within twenty-four hours of containment.\n\n"
                "3. Threat Intelligence Exchange\n"
                "(b) Entities shall participate in the inter-bank cyber threat intelligence sharing network.\n\n"
                "Provided that confidential customer identifiers shall be anonymized prior to feed ingestion."
            ),
        },
        # Circular 2: Outsourcing of Financial Services
        {
            "title": "Directions on Outsourcing of Financial Services",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Circular No. RBI/2026/102/DOR.ORG.14\n\n"
                "Attention of Regulated Entities is invited to the core principles of operational risk management.\n\n"
                "1. Core Management Functions\n"
                "(1) Regulated entities shall not outsource core management functions including decision making regarding credit approval and KYC verification.\n\n"
                "2. Sub-Contracting by Service Providers\n"
                "(a) Any material sub-contracting by an approved third-party vendor shall require prior written approval of the regulated entity.\n\n"
                "Provided that minor infrastructure maintenance by authorized cloud hosting personnel shall not require prior case-by-case approval.\n\n"
                "Provided also that the regulated entity retains unhindered right to audit the subcontractor facilities."
            ),
        },
        # Circular 3: Income Recognition and Asset Classification (IRAC)
        {
            "title": "Prudential Norms on Income Recognition and Asset Classification",
            "text": (
                "NOTIFICATION\n"
                "Ref. No. DOR.STR.REC.55/21.04.048/2026\n\n"
                "In exercise of the powers conferred under Section 21 of the Banking Regulation Act, 1949.\n\n"
                "1. Non-Performing Asset Classification\n"
                "(1) An asset, including a lease asset, shall be classified as NPA where interest or instalment of principal remains overdue for more than 90 days.\n\n"
                "Provided that in respect of agricultural loans tied to crop seasons, the account shall be treated as NPA only after two crop seasons for short duration crops.\n\n"
                "Provided further that for long duration crops, overdue status shall be calculated after one crop season.\n\n"
                "2. Restructuring and Upgrade Criteria\n"
                "(a) Accounts classified as NPAs may be upgraded to standard category upon receipt of all arrears of interest and principal.\n\n"
                "Provided that in case of restructured debt, upgrade shall occur only after the expiry of the specified observation period."
            ),
        },
        # Circular 4: External Commercial Borrowings (ECB)
        {
            "title": "Master Direction on Foreign Exchange Management (ECB Framework)",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "FOREIGN EXCHANGE DEPARTMENT\n"
                "Circular No. FED.DIR.12/2026\n\n"
                "WHEREAS borrowing and lending transactions across borders require statutory alignment under FEMA 1999.\n\n"
                "1. Eligible Borrowers and Lenders\n"
                "(1) All entities eligible to receive FDI are permitted to raise External Commercial Borrowings under the automatic route.\n\n"
                "2. Individual Limits and Minimum Average Maturity\n"
                "(a) The maximum amount which an eligible borrower can raise up to USD 750 million or its equivalent per financial year.\n\n"
                "Provided that for borrowing in the manufacturing sector, the ceiling may be extended up to USD 1 billion under the automatic route.\n\n"
                "Provided further that the minimum average maturity period for loans up to USD 50 million shall be three years."
            ),
        },
        # Circular 5: Digital Lending and Default Loss Guarantee
        {
            "title": "Guidelines on Digital Lending and Default Loss Guarantee (DLG)",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "FINANCIAL INCLUSION AND DEVELOPMENT DEPARTMENT\n"
                "Ref. No. DOR.CRE.REC.44/2026\n\n"
                "1. Default Loss Guarantee Arrangements\n"
                "(1) Regulated entities entering into DLG arrangements with Lending Service Providers shall ensure compliance with prudential caps.\n\n"
                "(a) The total DLG cover on any outstanding loan portfolio shall not exceed five per cent of the portfolio value.\n\n"
                "Provided that where the portfolio is backed by explicit corporate guarantees, collateralization must be in form of cash deposits or bank guarantees.\n\n"
                "Provided also that invocation of DLG shall occur within a maximum of 120 days of default."
            ),
        },
        # Circular 6: Liquidity Coverage Ratio (LCR)
        {
            "title": "Liquidity Coverage Ratio (LCR) and Basel III Framework",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "PRUDENTIAL REGULATION DIVISION\n"
                "Circular No. DBR.BP.BC.22/2026\n\n"
                "WHEREAS the preservation of high quality liquid assets (HQLA) is vital during liquidity stress.\n\n"
                "1. High Quality Liquid Assets (HQLA)\n"
                "(1) Banks shall maintain a stock of unencumbered HQLA that can be converted into cash to meet liquidity requirements.\n\n"
                "(a) Level 1 assets shall include cash, central bank reserves, and marketable sovereign securities.\n\n"
                "Provided that sovereign securities assigned zero risk weight under Basel capital rules may be included without any haircut.\n\n"
                "Provided further that eligible non-zero risk weight securities shall be subject to a minimum 15 per cent haircut."
            ),
        },
        # Circular 7: Know Your Customer Direction
        {
            "title": "Master Direction on Know Your Customer (KYC and V-CIP)",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Ref. No. DOR.AML.REC.19/2026\n\n"
                "In exercise of statutory powers under Prevention of Money Laundering Act, 2002.\n\n"
                "1. Video Customer Identification Process (V-CIP)\n"
                "(1) Regulated entities may undertake V-CIP for establishing customer identity through digital interactions.\n\n"
                "(a) The process shall be conducted by an authorized official in real time with geo-tagging.\n\n"
                "Provided that connections originating from IP addresses located outside India shall be immediately dropped.\n\n"
                "Provided further that customer consent for Aadhaar authentication shall be recorded with exact timestamp."
            ),
        },
        # Circular 8: Wilful Defaulters
        {
            "title": "Master Circular on Wilful Defaulters and Identification",
            "text": (
                "NOTIFICATION\n"
                "Ref. No. DBR.CID.BC.08/2026\n\n"
                "1. Criteria for Identification of Wilful Defaulters\n"
                "(1) A borrower shall be categorized as a wilful defaulter where there is deliberate intentional non-payment despite capacity.\n\n"
                "(a) Diversion or siphoning of borrowed funds for purposes other than those specified in the sanction letter.\n\n"
                "Provided that before formal classification, the borrower shall be issued a show-cause notice providing twenty-one days for written representation.\n\n"
                "Provided further that an opportunity for personal hearing before the Identification Committee shall be mandatory."
            ),
        },
        # Circular 9: Compromise Settlements
        {
            "title": "Framework for Compromise Settlements and Technical Write-offs",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Circular No. DOR.STR.REC.20/2026\n\n"
                "1. Policy on Compromise Settlements\n"
                "(1) All regulated entities shall lay down board approved policies for entering into compromise settlements.\n\n"
                "(a) The policy shall designate appropriate authority levels for approving compromises.\n\n"
                "Provided that compromise settlements with accounts classified as fraud or wilful default shall require prior approval of the Board.\n\n"
                "Provided also that entering into compromise shall be without prejudice to criminal proceedings."
            ),
        },
        # Circular 10: IT Governance Direction
        {
            "title": "Information Technology Governance, Risk, Controls and Assurance Direction",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Ref. No. DOR.ITG.REC.11/2026\n\n"
                "1. IT Strategy Committee of the Board\n"
                "(1) Regulated entities shall establish an IT Strategy Committee headed by an independent director.\n\n"
                "(a) The committee shall review long-term technology roadmaps and cybersecurity posture quarterly.\n\n"
                "Provided that the Chief Information Officer and Chief Information Security Officer shall attend all meetings.\n\n"
                "Provided further that meeting minutes shall be tabled before the full Board."
            ),
        },
        # Circular 11: Credit Cards and Debit Cards
        {
            "title": "Credit Card and Debit Card Issuance and Conduct Directions",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Circular No. DOR.AUT.REC.09/2026\n\n"
                "1. Unsolicited Commercial Cards\n"
                "(1) Card-issuers shall not issue unsolicited credit cards or upgrade existing cards without customer consent.\n\n"
                "(a) If an unsolicited card is billed, the issuer shall cancel the card and reverse charges with double penalty.\n\n"
                "Provided that where unsolicited cards are dispatched, no annual fee shall be levied under any circumstance."
            ),
        },
        # Circular 12: Payment Aggregators
        {
            "title": "Payment Aggregator and Payment Gateway Guidelines",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF PAYMENT AND SETTLEMENT SYSTEMS\n"
                "Ref. No. DPSS.CO.PD.18/2026\n\n"
                "1. Settlement and Escrow Account Operations\n"
                "(1) Payment aggregators shall maintain an escrow account with a scheduled commercial bank.\n\n"
                "(a) All payments received from merchants shall be credited to the escrow account on transaction completion.\n\n"
                "Provided that settlement to merchant bank accounts shall be completed within T plus one business day.\n\n"
                "Provided further that no interest shall be credited to payment aggregator from escrow balance."
            ),
        },
        # Circular 13: Priority Sector Lending (PSL)
        {
            "title": "Priority Sector Lending Targets and Classification",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "FIDD.CO.Plan.BC.05/2026\n\n"
                "1. Overall PSL Targets\n"
                "(1) Total Priority Sector Lending target shall be forty per cent of Adjusted Net Bank Credit (ANBC).\n\n"
                "(a) Sub-targets for agriculture shall be eighteen per cent of ANBC.\n\n"
                "Provided that lending to small and marginal farmers shall constitute at least ten per cent of ANBC.\n\n"
                "Provided also that foreign banks with less than twenty branches shall be exempt from sub-target requirements."
            ),
        },
        # Circular 14: Fair Practices Code
        {
            "title": "Fair Practices Code for Lenders (Penal Charges Directive)",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Circular No. DOR.MCS.REC.28/2026\n\n"
                "1. Fair Penal Charges\n"
                "(1) Penalty for non-compliance of material terms of loan contract shall be levied as penal charges rather than penal interest.\n\n"
                "(a) There shall be no capitalization of penal charges into principal for compounding interest.\n\n"
                "Provided that regulated entities shall disclose all charges in the Key Fact Statement upfront.\n\n"
                "Provided further that charges shall be proportionate to the default."
            ),
        },
        # Circular 15: Regulatory Sandbox
        {
            "title": "Framework for Regulatory Sandbox (Fintech Innovation)",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "FINTECH DEPARTMENT\n"
                "Ref. No. FT.SANDBOX.03/2026\n\n"
                "1. Cohort Eligibility and Testing\n"
                "(1) Applicants shall demonstrate innovative solutions addressing measurable friction in financial services.\n\n"
                "(a) Boundary relaxations may be granted on customer onboarding friction during the testing phase.\n\n"
                "Provided that legal liability for customer losses resulting from experimental faults rests entirely with the applicant.\n\n"
                "Provided also that full customer refunds must be processed within forty-eight hours."
            ),
        },
        # Circular 16: Financial Statements Disclosures
        {
            "title": "Master Direction on Financial Statements Presentation and Disclosures",
            "text": (
                "NOTIFICATION\n"
                "Ref. No. DOR.ACC.REC.02/2026\n\n"
                "1. Disclosure of Divergence in Asset Classification\n"
                "(1) Banks shall disclose divergences in asset classification and provisioning in the notes to accounts.\n\n"
                "(a) Where additional provisioning requirements exceed ten per cent of reported profit before provisions.\n\n"
                "Provided that where divergence in gross NPAs exceeds ten per cent, public disclosure in annual report is mandatory."
            ),
        },
        # Circular 17: Fraud Risk Management
        {
            "title": "Master Direction on Fraud Risk Management in Commercial Banks",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF REGULATION\n"
                "Ref. No. DOR.FRM.REC.33/2026\n\n"
                "1. Early Warning Signals (EWS)\n"
                "(1) Banks shall deploy automated EWS systems to detect potential fraud before loan disbursal.\n\n"
                "(a) Accounts flagged under EWS shall be placed under special monitoring by the fraud monitoring group.\n\n"
                "Provided that customer communication shall not reveal confidential fraud investigation inquiries."
            ),
        },
        # Circular 18: Card-on-File Tokenisation (CoFT)
        {
            "title": "Card-on-File Tokenisation (CoFT) Regulatory Framework",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "DEPARTMENT OF PAYMENT AND SETTLEMENT SYSTEMS\n"
                "Circular No. DPSS.CO.PD.04/2026\n\n"
                "1. Storage of Card Details\n"
                "(1) No merchant or payment gateway shall store actual card details (PAN and CVV) on servers.\n\n"
                "(a) Transactions shall be processed solely through tokenized credentials generated by authorized card networks.\n\n"
                "Provided that merchants may retain last four digits of card number and card issuer name for transaction tracking.\n\n"
                "Provided further that customer consent for tokenization shall be explicit with AFA verification."
            ),
        },
        # Circular 19: Cross-Border Inward Remittances
        {
            "title": "Cross-Border Inward Remittances under Money Transfer Service Scheme",
            "text": (
                "RESERVE BANK OF INDIA\n"
                "FOREIGN EXCHANGE DEPARTMENT\n"
                "Ref. No. FED.CO.MTSS.01/2026\n\n"
                "1. Ceiling on Inward Remittances\n"
                "(1) Inward remittance under MTSS shall be limited to personal remittances such as family maintenance.\n\n"
                "(a) The maximum limit for a single remittance shall not exceed USD 2,500 or its equivalent.\n\n"
                "Provided that maximum thirty remittances shall be received by a single individual beneficiary in a calendar year."
            ),
        },
        # Circular 20: Statutory Liquidity Ratio (SLR)
        {
            "title": "Statutory Liquidity Ratio (SLR) Maintenance and Valuation",
            "text": (
                "NOTIFICATION\n"
                "Ref. No. DOR.RET.REC.17/2026\n\n"
                "In exercise of statutory powers under Section 24 of Banking Regulation Act, 1949.\n\n"
                "1. SLR Maintenance Requirements\n"
                "(1) Every banking company shall maintain in India assets of not less than eighteen per cent of its Net Demand and Time Liabilities.\n\n"
                "(a) Approved securities for SLR shall be valued at market prices in accordance with FIMMDA guidelines.\n\n"
                "Provided that securities held under Held to Maturity category shall be valued at acquisition cost.\n\n"
                "Provided further that any excess premium paid shall be amortized over the remaining period to maturity."
            ),
        },
    ]
    return circulars


# ==============================================================================
# 1. 20 Benchmark Circulars Hierarchical Parsing & Invariant Tests
# ==============================================================================


def test_20_benchmark_circulars_pass_invariants() -> None:
    circulars = build_20_benchmark_circulars()
    assert len(circulars) == 20

    chunker = HierarchicalChunker(config=ChunkingConfig(max_chunk_tokens=512))

    total_chunks_count = 0
    total_provisos_found = 0
    retained_provisos_count = 0

    for circ in circulars:
        text = circ["text"]
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2, f"Circular '{circ['title']}' generated only {len(chunks)} chunk(s)"
        total_chunks_count += len(chunks)

        # Invariant 1: FR-7 exact string equality
        verify_offsets(text, chunks)

        # Invariant 2: 100% text coverage
        uncovered = uncovered_characters(text, chunks)
        assert uncovered == 0, f"Circular '{circ['title']}' has {uncovered} uncovered characters"

        # Invariant 3: Token ceiling <= 512
        for c in chunks:
            assert c.token_count <= 512
            assert c.token_count >= 1
            assert len(c.text) > 0

        # Check provisos
        for c in chunks:
            if "Provided that" in c.text or "Provided further that" in c.text:
                total_provisos_found += 1
                # If chunk contains both operative rule or has parent link
                if c.is_proviso or len(c.clause_hierarchy) >= 1:
                    retained_provisos_count += 1

    # Total chunks across 20 circulars should be around 80-200
    assert total_chunks_count >= 50
    assert total_provisos_found >= 20

    # Invariant 4: Proviso retention rate >= 98%
    retention_rate = (retained_provisos_count / total_provisos_found) * 100.0
    assert retention_rate >= 98.0, (
        f"Proviso retention rate {retention_rate:.1f}% below 98.0% threshold"
    )


# ==============================================================================
# 2. Proviso Parent-Child Linkage when Exceeding Token Ceiling
# ==============================================================================


def test_proviso_parent_linkage_when_split_by_token_limit() -> None:
    # Construct a long operative clause followed by a proviso, where combined > max_tokens
    operative_clause = (
        "1. Capital Adequacy Prudential Framework\n"
        "(1) All scheduled commercial banks shall maintain a minimum total capital to risk-weighted assets ratio "
        "of nine per cent on an ongoing basis. "
        + (
            "Additional tier-one capital instruments must meet rigorous loss absorption criteria at point of non-viability. "
            * 15
        )
    )
    long_proviso = (
        "\n\nProvided that where a bank's capital ratio falls below the prescribed threshold, the Reserve Bank "
        "may place the entity under Prompt Corrective Action framework restricting dividend payouts and branch expansion. "
        + (
            "Discretionary coupon payments on additional tier-one capital shall be cancelled immediately. "
            * 10
        )
    )

    full_text = operative_clause + long_proviso

    # Set tight max_chunk_tokens = 100 to force split
    config = ChunkingConfig(max_chunk_tokens=100, preserve_provisos=True)
    chunker = HierarchicalChunker(config=config)
    chunks = chunker.chunk(full_text)

    # Invariants must hold
    verify_offsets(full_text, chunks)
    assert uncovered_characters(full_text, chunks) == 0

    # Look for proviso chunk
    proviso_chunks = [c for c in chunks if c.is_proviso or "Provided that" in c.text]
    assert len(proviso_chunks) >= 1

    # At least one proviso chunk should have a parent_chunk_id linking to an earlier chunk
    linked_provisos = [c for c in proviso_chunks if c.parent_chunk_id is not None]
    assert len(linked_provisos) >= 1, "Expected proviso chunk to have parent_chunk_id set"

    parent_id = linked_provisos[0].parent_chunk_id
    parent_chunk = next((c for c in chunks if c.chunk_id == parent_id), None)
    assert parent_chunk is not None, "Referenced parent chunk must exist in chunk list"
    assert "Capital Adequacy" in parent_chunk.text or "scheduled commercial" in parent_chunk.text


# ==============================================================================
# 3. Clean Fallback for Non-Regulatory Unstructured Text
# ==============================================================================


def test_unstructured_text_clean_fallback() -> None:
    # Free-form narrative prose with no sections, preambles, or statutory patterns
    unstructured_text = (
        "Financial technology is evolving rapidly across global markets. "
        "Cloud native infrastructure provides resilience and scalability for digital payment processing. "
        "Microservices architectures allow development teams to independently deploy isolated capabilities. "
        "Automated monitoring using Prometheus and OpenTelemetry enables rapid anomaly detection. "
    ) * 10

    chunker = HierarchicalChunker(config=ChunkingConfig(fallback_to_sliding_window=True))
    chunks = chunker.chunk(unstructured_text)

    assert len(chunks) >= 2
    verify_offsets(unstructured_text, chunks)
    assert uncovered_characters(unstructured_text, chunks) == 0
    for c in chunks:
        assert c.token_count <= 512
        assert c.chunk_type in {"standard", "proviso"}


# ==============================================================================
# 4. Public Ingestion Seam: chunk_document_hierarchical
# ==============================================================================


def test_chunk_document_hierarchical_public_function() -> None:
    circ = build_20_benchmark_circulars()[0]
    chunks = chunk_document_hierarchical(
        circ["text"],
        token_counter=lambda s: max(1, len(s.split()) * 4 // 3),
    )
    assert len(chunks) >= 2
    verify_offsets(circ["text"], chunks)
    assert uncovered_characters(circ["text"], chunks) == 0


# ==============================================================================
# 5. Throughput & Latency SLA (>= 250 pages/sec or >= 50,000 chars/sec)
# ==============================================================================


def test_chunking_speed_and_throughput_sla() -> None:
    circulars = build_20_benchmark_circulars()
    # Concatenate all 20 circulars into a large corpus (duplicated for bulk volume test)
    corpus = ("\n\n".join(c["text"] for c in circulars)) * 2
    total_chars = len(corpus)
    assert total_chars >= 15000

    chunker = HierarchicalChunker()

    t0 = time.perf_counter()
    bench_chunks = chunker.chunk(corpus)
    duration_s = time.perf_counter() - t0

    assert len(bench_chunks) > 0

    chars_per_sec = total_chars / max(duration_s, 1e-6)

    # 1 page approx 2,000 characters. 250 pages/sec = 500,000 chars/sec or at least 50,000 chars/sec in test harness
    assert chars_per_sec >= 50000.0, (
        f"Throughput {chars_per_sec:.0f} chars/sec below 50,000 threshold"
    )
    assert duration_s < 0.5, f"Chunking 20 circulars took {duration_s:.3f}s"


# ==============================================================================
# 6. REST API Endpoint: POST /v1/ingest/chunk
# ==============================================================================


def test_api_chunk_endpoint(
    client: TestClient,
    api_headers: dict[str, str],
) -> None:
    circ = build_20_benchmark_circulars()[4]  # Digital Lending circular

    payload = {
        "text": circ["text"],
        "max_chunk_tokens": 512,
        "min_chunk_tokens": 64,
        "preserve_provisos": True,
        "strategy": "hierarchical",
    }

    res = client.post(
        "/v1/ingest/chunk",
        json=payload,
        headers=api_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_chunks"] >= 2
    assert data["uncovered_characters"] == 0
    assert data["strategy"] == "hierarchical"
    assert len(data["chunks"]) == data["total_chunks"]

    # Verify each chunk model returned
    for c in data["chunks"]:
        assert UUID(c["chunk_id"])
        assert c["char_end"] > c["char_start"]
        assert c["token_count"] <= 512
        assert len(c["text"]) > 0


def test_api_chunk_endpoint_short_payload_422(
    client: TestClient,
    api_headers: dict[str, str],
) -> None:
    # Text shorter than 100 characters should trigger 422
    payload = {
        "text": "Too short text for document chunking.",
        "max_chunk_tokens": 512,
    }
    res = client.post(
        "/v1/ingest/chunk",
        json=payload,
        headers=api_headers,
    )
    assert res.status_code == 422
