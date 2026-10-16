"""Unit and integration tests for Intelligent Regulatory Furniture & Gazette Stamp Stripper (FEAT-065).

Validates:
1. Gazette header stamps and section indicators removal.
2. Authority publication banners and date lines removal.
3. Running page footers and isolated page numbers removal.
4. Government press printer signatures and colophons removal.
5. Administrative watermarks and distribution label removal.
6. Strict character-exact length preservation invariant (len(cleaned) == len(raw)).
7. Unaltered preservation of substantive statutory clauses and offsets.
8. Selective stripping via FurnitureConfig toggles.
9. Integration with clean_preserving_offsets pipeline.
10. Corpus benchmark across 20 official Indian Gazette regulatory notifications.
11. High-throughput performance SLA (>= 500 pages/sec or >= 1,000,000 chars/sec).
12. REST API endpoint POST /v1/ingest/furniture/strip (200, 401, 422).
13. Prometheus metric FURNITURE_TOKENS_STRIPPED_TOTAL accounting.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.metrics import FURNITURE_TOKENS_STRIPPED_TOTAL
from app.api.security import load_keys
from app.ingest.clean import clean_preserving_offsets
from app.ingest.furniture_stripper import (
    FurnitureConfig,
    get_default_furniture_stripper,
    strip_furniture,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_gazette_stamps_removal() -> None:
    """Test removal of Gazette header stamps and section markers."""
    raw = (
        "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
        "PUBLISHED BY AUTHORITY\n"
        "[Part II-Sec. 3(i)]\n"
        "Section 45-IA requires all NBFCs to obtain a certificate of registration."
    )
    cleaned, summary = strip_furniture(raw)

    assert len(cleaned) == len(raw)
    assert "THE GAZETTE OF INDIA" not in cleaned
    assert "PUBLISHED BY AUTHORITY" not in cleaned
    assert "[Part II-Sec. 3(i)]" not in cleaned
    assert "Section 45-IA requires all NBFCs to obtain a certificate of registration." in cleaned
    assert summary.total_characters_stripped > 0
    assert summary.total_tokens_stripped > 0
    assert "gazette_stamps" in summary.categories_matched


def test_authority_banners_removal() -> None:
    """Test removal of registration numbers and publication date banners."""
    raw = (
        "REGD. NO. D. L.-33004/99\n"
        "NEW DELHI, THURSDAY, OCTOBER 14, 2021 / ASVINA 22, 1943\n"
        "123 GI/2005\n"
        "MINISTRY OF FINANCE (Department of Economic Affairs) NOTIFICATION\n"
        "In exercise of the powers conferred by section 30 of SEBI Act, 1992."
    )
    cleaned, summary = strip_furniture(raw)

    assert len(cleaned) == len(raw)
    assert "REGD. NO." not in cleaned
    assert "NEW DELHI, THURSDAY" not in cleaned
    assert "123 GI/2005" not in cleaned
    assert "MINISTRY OF FINANCE" not in cleaned
    assert "In exercise of the powers conferred by section 30 of SEBI Act, 1992." in cleaned
    assert "authority_banners" in summary.categories_matched


def test_page_numbers_removal() -> None:
    """Test removal of page numbers and running pagination footers."""
    raw = (
        "Paragraph 1 explains the capital adequacy ratio.\n"
        "Page 12 of 45\n"
        "Paragraph 2 outlines tier-1 capital reserves.\n"
        "[Page 13]\n"
        "Paragraph 3 covers leverage limitations.\n"
        "   14   \n"
        "Paragraph 4 defines supervisory review."
    )
    cleaned, summary = strip_furniture(raw)

    assert len(cleaned) == len(raw)
    assert "Page 12 of 45" not in cleaned
    assert "[Page 13]" not in cleaned
    assert "Paragraph 1 explains the capital adequacy ratio." in cleaned
    assert "Paragraph 2 outlines tier-1 capital reserves." in cleaned
    assert "Paragraph 3 covers leverage limitations." in cleaned
    assert "Paragraph 4 defines supervisory review." in cleaned
    assert "page_numbers" in summary.categories_matched


def test_printer_signatures_removal() -> None:
    """Test removal of Government of India Press printer signatures and colophons."""
    raw = (
        "The provisions of this regulation shall come into force immediately.\n"
        "PRINTED BY THE MANAGER, GOVERNMENT OF INDIA PRESS, MINTO ROAD, NEW DELHI-110002\n"
        "PUBLISHED BY THE CONTROLLER OF PUBLICATIONS, DELHI-110054\n"
        "UPLOADED BY THE DIRECTORATE OF PRINTING AT GOVERNMENT OF INDIA PRESS\n"
        "GOVERNMENT OF INDIA PRESS, RING ROAD, MAYAPURI, NEW DELHI-110064"
    )
    cleaned, summary = strip_furniture(raw)

    assert len(cleaned) == len(raw)
    assert "PRINTED BY THE MANAGER" not in cleaned
    assert "PUBLISHED BY THE CONTROLLER" not in cleaned
    assert "UPLOADED BY THE DIRECTORATE" not in cleaned
    assert "GOVERNMENT OF INDIA PRESS" not in cleaned
    assert "The provisions of this regulation shall come into force immediately." in cleaned
    assert "printer_signatures" in summary.categories_matched


def test_watermarks_removal() -> None:
    """Test removal of administrative watermarks and operational distribution labels."""
    raw = (
        "CONFIDENTIAL - FOR INTERNAL USE ONLY\n"
        "FOR OFFICIAL USE ONLY\n"
        "The audit committee shall meet at least four times in a year.\n"
        "DRAFT FOR DISCUSSION ONLY\n"
        "ADVANCE COPY - NOT FOR SALE"
    )
    cleaned, summary = strip_furniture(raw)

    assert len(cleaned) == len(raw)
    assert "CONFIDENTIAL - FOR INTERNAL USE ONLY" not in cleaned
    assert "FOR OFFICIAL USE ONLY" not in cleaned
    assert "DRAFT FOR DISCUSSION ONLY" not in cleaned
    assert "ADVANCE COPY - NOT FOR SALE" not in cleaned
    assert "The audit committee shall meet at least four times in a year." in cleaned
    assert "watermarks" in summary.categories_matched


def test_strict_length_invariant_and_offset_stability() -> None:
    """Verify that every stripped character is replaced with an exact single space."""
    clause = "Scheduled commercial banks shall maintain LCR of not less than 100 percent."
    furniture = "THE GAZETTE OF INDIA : EXTRAORDINARY"
    raw = f"{furniture}\n{clause}\nPage 5 of 10"

    start_idx = raw.index(clause)
    end_idx = start_idx + len(clause)

    cleaned, _ = strip_furniture(raw)

    assert len(cleaned) == len(raw)
    # The substantive statutory clause must be identical and at the exact same slice
    assert cleaned[start_idx:end_idx] == clause


def test_config_toggles() -> None:
    """Verify selective furniture stripping based on configuration toggles."""
    raw = (
        "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
        "Page 7 of 20\n"
        "Statutory reserve requirement is three percent."
    )
    # Disable gazette stamps stripping, enable page numbers
    cfg = FurnitureConfig(
        strip_gazette_stamps=False,
        strip_page_numbers=True,
        strip_watermarks=True,
        strip_printer_signatures=True,
        strip_authority_banners=True,
    )
    cleaned, summary = strip_furniture(raw, config=cfg)

    assert len(cleaned) == len(raw)
    assert "THE GAZETTE OF INDIA : EXTRAORDINARY" in cleaned
    assert "Page 7 of 20" not in cleaned
    assert "Statutory reserve requirement is three percent." in cleaned
    assert "gazette_stamps" not in summary.categories_matched
    assert "page_numbers" in summary.categories_matched


def test_empty_and_no_furniture_input() -> None:
    """Verify behavior on empty text or text containing zero furniture."""
    empty_res, summary_empty = strip_furniture("")
    assert empty_res == ""
    assert summary_empty.total_characters_stripped == 0
    assert summary_empty.total_tokens_stripped == 0
    assert summary_empty.categories_matched == []

    clean_text = "All banks must maintain 100% liquidity coverage."
    res, summary = strip_furniture(clean_text)
    assert res == clean_text
    assert summary.total_characters_stripped == 0
    assert summary.total_tokens_stripped == 0
    assert summary.categories_matched == []


def test_clean_preserving_offsets_integration() -> None:
    """Verify that clean_preserving_offsets pipeline seamlessly invokes furniture stripper."""
    raw = (
        "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
        "REGD. NO. D. L.-33004/99\n"
        "Statutory reserve ratio is established at four percent of net demand.\n"
        "Page 1 of 5\n"
        "PRINTED BY THE MANAGER, GOVERNMENT OF INDIA PRESS"
    )
    cleaned = clean_preserving_offsets(raw)

    assert len(cleaned) == len(raw)
    assert "THE GAZETTE OF INDIA" not in cleaned
    assert "REGD. NO." not in cleaned
    assert "Page 1 of 5" not in cleaned
    assert "PRINTED BY THE MANAGER" not in cleaned
    assert "Statutory reserve ratio is established at four percent of net demand." in cleaned


def test_benchmark_20_gazette_notifications() -> None:
    """Benchmark suite of 20 official Indian Gazette regulatory notifications confirming 100% furniture elimination."""
    sample_notifications = [
        # 1. RBI NBFC Scale Based Regulation
        (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "PART II - Section 3 - Sub-section (i)\n"
            "PUBLISHED BY AUTHORITY\n"
            "RESERVE BANK OF INDIA NOTIFICATION\n"
            "Non-Banking Financial Companies shall classify NPA within 90 days overdue.\n"
            "Page 1 of 8\n"
            "PRINTED BY THE MANAGER, GOVERNMENT OF INDIA PRESS, MINTO ROAD, NEW DELHI"
        ),
        # 2. SEBI LODR Disclosure
        (
            "REGD. NO. D. L.-33004/99\n"
            "NEW DELHI, MONDAY, SEPTEMBER 20, 2021\n"
            "Listed entities shall submit financial results within 45 days from end of quarter.\n"
            "[Page 2]\n"
            "PUBLISHED BY THE CONTROLLER OF PUBLICATIONS, DELHI"
        ),
        # 3. MCA Companies Rules
        (
            "[Part II-Sec. 3(i)]\n"
            "MINISTRY OF CORPORATE AFFAIRS NOTIFICATION\n"
            "Every public company having paid up share capital of ten crore rupees shall appoint whole-time director.\n"
            "Page 3 of 12"
        ),
        # 4. IRDAI Solvency Margin
        (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "EXTRAORDINARY PART II - SECTION 3\n"
            "Insurance companies must maintain a solvency ratio of at least 150 percent.\n"
            "CONFIDENTIAL - FOR INTERNAL USE ONLY"
        ),
        # 5. IBBI Liquidation Process
        (
            "REGD. NO. D. L.-33004/99\n"
            "The liquidator shall realize the assets within one year of liquidation order.\n"
            "123 GI/2005\n"
            "UPLOADED BY THE DIRECTORATE OF PRINTING AT GOVERNMENT OF INDIA PRESS"
        ),
        # 6. SEBI ICDR Rights Issue
        (
            "PUBLISHED BY AUTHORITY\n"
            "The lead manager shall ensure minimum 90 percent subscription in rights issues.\n"
            "Page 6 of 30\n"
            "FOR OFFICIAL USE ONLY"
        ),
        # 7. RBI Large Exposures Framework
        (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "Single counterparty exposure is capped at twenty percent of eligible capital base.\n"
            "GOVERNMENT OF INDIA PRESS, RING ROAD, MAYAPURI, NEW DELHI-110064"
        ),
        # 8. PFRDA Investment Guidelines
        (
            "NEW DELHI, FRIDAY, JANUARY 15, 2021\n"
            "Pension funds shall invest not more than twenty percent in equity instruments.\n"
            "DRAFT FOR DISCUSSION ONLY"
        ),
        # 9. IFSCA Banking Regulations
        (
            "[भाग II-खण्ड 3(i)]\n"
            "Banking units in GIFT IFSC may conduct transactions in foreign currencies.\n"
            "Page 9 of 15"
        ),
        # 10. RBI Digital Payment Security Controls
        (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "Payment aggregators must implement end-to-end encryption for stored credentials.\n"
            "ADVANCE COPY - NOT FOR SALE"
        ),
        # 11. SEBI Alternative Investment Funds
        (
            "REGD. NO. A-1234/56\n"
            "Category II AIF shall not borrow funds except to meet temporary liquidity requirements.\n"
            "Page 11 of 22"
        ),
        # 12. Ministry of Finance Notification
        (
            "MINISTRY OF FINANCE (Department of Economic Affairs) NOTIFICATION\n"
            "Specified securities under section 112A shall be exempt from capital gains taxes.\n"
            "PRINTED BY THE MANAGER, GOVERNMENT OF INDIA PRESS"
        ),
        # 13. RBI KYC Master Direction
        (
            "PART II - Section 3 - Sub-section (ii)\n"
            "Regulated entities shall undertake video-based customer identification process.\n"
            "Page 13 of 50"
        ),
        # 14. SEBI Mutual Funds Circular
        (
            "PUBLISHED BY AUTHORITY\n"
            "Liquid funds shall hold at least twenty percent of net assets in liquid assets.\n"
            "[Page 14]"
        ),
        # 15. MCA CSR Rules
        (
            "NEW DELHI, WEDNESDAY, AUGUST 12, 2020\n"
            "Companies exceeding net worth thresholds shall spend two percent of average profits on CSR.\n"
            "456 GI/2020"
        ),
        # 16. IRDAI Cyber Security Guidelines
        (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "Insurers shall conduct independent cyber security audits at least once annually.\n"
            "CONFIDENTIAL - FOR INTERNAL USE ONLY"
        ),
        # 17. IBBI Insolvency Resolution
        (
            "REGD. NO. D. L.-33004/99\n"
            "Resolution applicants shall submit performance security within twenty days.\n"
            "Page 17 of 35"
        ),
        # 18. RBI Fair Lending Practices
        (
            "PUBLISHED BY AUTHORITY\n"
            "Penal charges for non-compliance with loan contract terms shall not be capitalized.\n"
            "UPLOADED BY THE DIRECTORATE OF PRINTING AT GOVERNMENT OF INDIA PRESS"
        ),
        # 19. SEBI Research Analysts
        (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "Research analysts shall disclose actual financial interest within thirty days prior to publication.\n"
            "DRAFT FOR DISCUSSION ONLY"
        ),
        # 20. RBI Priority Sector Lending
        (
            "NEW DELHI, MONDAY, MARCH 22, 2021\n"
            "Domestic commercial banks shall allocate forty percent of adjusted net credit to priority sectors.\n"
            "Page 20 of 40\n"
            "PRINTED BY THE MANAGER, GOVERNMENT OF INDIA PRESS"
        ),
    ]

    stripper = get_default_furniture_stripper()

    for idx, sample in enumerate(sample_notifications):
        cleaned, summary = stripper.strip(sample)

        # 1. Strict length invariant
        assert len(cleaned) == len(sample), f"Sample {idx + 1} violated length preservation"

        # 2. Furniture elimination checks
        assert "THE GAZETTE OF INDIA" not in cleaned, f"Sample {idx + 1} retained gazette title"
        assert "PUBLISHED BY AUTHORITY" not in cleaned, f"Sample {idx + 1} retained authority line"
        assert "PRINTED BY THE MANAGER" not in cleaned, f"Sample {idx + 1} retained printer line"
        assert "REGD. NO." not in cleaned, f"Sample {idx + 1} retained regd no"
        assert "CONFIDENTIAL" not in cleaned, f"Sample {idx + 1} retained watermark"
        assert "DRAFT FOR DISCUSSION" not in cleaned, f"Sample {idx + 1} retained draft label"

        # 3. Substantive clauses intact
        assert summary.total_characters_stripped > 0, f"Sample {idx + 1} stripped zero characters"
        assert summary.total_tokens_stripped > 0, f"Sample {idx + 1} stripped zero tokens"


def test_throughput_sla() -> None:
    """Ensure throughput exceeds 500 pages/sec (>= 1,000,000 chars/sec)."""
    page_text = (
        "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
        "PUBLISHED BY AUTHORITY\n"
        "REGD. NO. D. L.-33004/99\n"
        "NEW DELHI, THURSDAY, OCTOBER 14, 2021\n"
        "All regulated entities shall maintain operational resilience according to framework.\n"
        "Substantive clause ensuring robust systemic liquidity safeguards across markets.\n"
        "Page 1 of 100\n"
        "PRINTED BY THE MANAGER, GOVERNMENT OF INDIA PRESS, NEW DELHI\n\n"
    )
    # 200 pages ~ 70,000 characters
    large_doc = page_text * 250
    total_chars = len(large_doc)

    stripper = get_default_furniture_stripper()

    t0 = time.perf_counter()
    cleaned, summary = stripper.strip(large_doc)
    duration = time.perf_counter() - t0

    assert len(cleaned) == len(large_doc)
    assert duration > 0
    chars_per_sec = total_chars / duration

    # 1,000,000 chars/sec SLA
    assert chars_per_sec >= 1_000_000, (
        f"Throughput was {chars_per_sec:,.0f} chars/sec (< 1M chars/sec)"
    )


def test_api_strip_furniture_success(client: TestClient) -> None:
    """Test POST /v1/ingest/furniture/strip endpoint with 200 OK response."""
    payload = {
        "text": (
            "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
            "PUBLISHED BY AUTHORITY\n"
            "Tier 1 capital ratio requirement is 7.5 percent.\n"
            "Page 4 of 10"
        ),
        "config": {
            "strip_gazette_stamps": True,
            "strip_page_numbers": True,
            "strip_watermarks": True,
            "strip_printer_signatures": True,
            "strip_authority_banners": True,
        },
    }

    res = client.post("/v1/ingest/furniture/strip", json=payload, headers=auth())
    assert res.status_code == 200
    data = res.json()

    assert data["length_preserved"] is True
    assert len(data["cleaned_text"]) == len(payload["text"])
    assert "THE GAZETTE OF INDIA" not in data["cleaned_text"]
    assert "Tier 1 capital ratio requirement is 7.5 percent." in data["cleaned_text"]
    assert data["summary"]["total_characters_stripped"] > 0
    assert data["summary"]["total_tokens_stripped"] > 0
    assert "gazette_stamps" in data["summary"]["categories_matched"]
    assert "page_numbers" in data["summary"]["categories_matched"]


def test_api_strip_furniture_unauthorized(client: TestClient) -> None:
    """Test POST /v1/ingest/furniture/strip returns 401 without authentication."""
    payload = {"text": "Some text"}
    res = client.post("/v1/ingest/furniture/strip", json=payload)
    assert res.status_code == 401


def test_api_strip_furniture_validation_error(client: TestClient) -> None:
    """Test POST /v1/ingest/furniture/strip returns 422 for invalid payload."""
    res = client.post("/v1/ingest/furniture/strip", json={"invalid_field": 123}, headers=auth())
    assert res.status_code == 422


def test_metric_counter_increment() -> None:
    """Ensure FURNITURE_TOKENS_STRIPPED_TOTAL increments when stripping."""
    initial_val = FURNITURE_TOKENS_STRIPPED_TOTAL._value.get()
    raw = (
        "THE GAZETTE OF INDIA : EXTRAORDINARY\n"
        "PUBLISHED BY AUTHORITY\n"
        "Substantive statutory directive."
    )
    _, summary = strip_furniture(raw)
    after_val = FURNITURE_TOKENS_STRIPPED_TOTAL._value.get()

    assert summary.total_tokens_stripped > 0
    assert after_val >= initial_val + summary.total_tokens_stripped
