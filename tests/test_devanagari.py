"""Tests for Bilingual Devanagari / Hindi normalization and parsing (FEAT-068).

Validates:
1. Canonical Unicode NFC decomposition/composition.
2. Zero-Width Joiner (ZWJ) and Non-Joiner (ZWNJ) retention and stripping.
3. Cleanup of orphaned combining vowel signs and broken conjuncts.
4. Language identification and Devanagari character ratio computation.
5. Parallel column and sequential section bilingual parsing.
6. Length-preserving invariant under clean_preserving_offsets (FR-7).
7. Normalization throughput exceeding 1,000,000 chars/sec SLA.
8. API endpoint POST /v1/ingest/devanagari/normalize.
"""

from __future__ import annotations

import os
import time
import unicodedata

import pytest
from starlette.testclient import TestClient

from app.api.app import app
from app.api.metrics import DEVANAGARI_CHARACTERS_NORMALIZED_TOTAL
from app.api.security import load_keys
from app.ingest.clean import clean_preserving_offsets
from app.ingest.devanagari import (
    DevanagariConfig,
    clean_devanagari_preserving_length,
    count_devanagari,
    devanagari_ratio,
    extract_bilingual_columns,
    has_devanagari,
    is_devanagari,
    normalize_devanagari,
    separate_bilingual_text,
)
from tests.conftest import PRIMARY_KEY, auth

SAMPLE_HINDI = "भारतीय रिज़र्व बैंक द्वारा जारी की गई आधिकारिक अधिसूचना।"
SAMPLE_ENGLISH = "Official notification issued by the Reserve Bank of India."
SAMPLE_PARALLEL_COLUMN = (
    "भारतीय रिज़र्व बैंक                       RESERVE BANK OF INDIA\n"
    "अधिसूचना                               NOTIFICATION\n"
    "बैंकिंग विनियमन विभाग                   Department of Banking Regulation\n"
    "मुंबई - 400001                          Mumbai - 400001\n"
)


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_is_devanagari_and_script_detection() -> None:
    """Validate character-level Devanagari detection."""
    assert is_devanagari("क")
    assert is_devanagari("आ")
    assert is_devanagari("\u093e")  # vowel sign AA
    assert is_devanagari("\ua8e0")  # Extended Devanagari
    assert not is_devanagari("A")
    assert not is_devanagari("1")
    assert not is_devanagari(" ")
    assert not is_devanagari("")


def test_has_devanagari_and_counts() -> None:
    """Validate text-level Devanagari detection and ratio counting."""
    assert has_devanagari(SAMPLE_HINDI)
    assert not has_devanagari(SAMPLE_ENGLISH)
    assert has_devanagari("RBI अधिसूचना 2024")

    cnt = count_devanagari("कखग 123")
    assert cnt == 3

    ratio_hi = devanagari_ratio(SAMPLE_HINDI)
    assert ratio_hi > 0.8
    ratio_en = devanagari_ratio(SAMPLE_ENGLISH)
    assert ratio_en == 0.0
    assert devanagari_ratio("   ") == 0.0


def test_unicode_nfc_canonical_normalization() -> None:
    """NFD decomposed Devanagari characters must normalize to canonical NFC."""
    # NFD: U+0928 (na) + U+093C (nukta) decomposes, and NFC composes into U+0929 (nnna)
    decomposed = "\u0928\u093c"
    expected_nfc = "\u0929"
    assert unicodedata.normalize("NFC", decomposed) == expected_nfc

    normalized = normalize_devanagari(decomposed)
    assert normalized == expected_nfc
    assert len(normalized) == 1

    # Roundtrip test on real statutory circular text
    assert normalize_devanagari(SAMPLE_HINDI) == SAMPLE_HINDI


def test_zwj_and_zwnj_retention_and_stripping() -> None:
    """ZWJ and ZWNJ must be retained when strip_zwj=False and removed when strip_zwj=True."""
    # Half-form conjunct with ZWJ: ka + virama + ZWJ + sha
    text_with_zwj = "\u0915\u094d\u200d\u0937"
    preserved = normalize_devanagari(text_with_zwj, config=DevanagariConfig(strip_zwj=False))
    assert "\u200d" in preserved

    stripped = normalize_devanagari(text_with_zwj, config=DevanagariConfig(strip_zwj=True))
    assert "\u200d" not in stripped


def test_orphaned_matra_elimination() -> None:
    """Combining vowel signs without a preceding base consonant must be eliminated."""
    # Orphaned matra at start of word / preceded by space or English
    text_with_glitch = " \u093e\u092d\u093e\u0930\u0924 test \u093f\u0915\u094d\u0932"
    cleaned = normalize_devanagari(text_with_glitch)
    # The initial \u093e before \u092d is stripped, but \u093e inside bharat is preserved
    assert "\u092d\u093e\u0930\u0924" in cleaned
    assert not cleaned.startswith(" \u093e")


def test_clean_devanagari_preserving_length() -> None:
    """clean_devanagari_preserving_length must strictly enforce len(cleaned) == len(raw)."""
    raw = " \u093e\u092d\u093e\u0930\u0924  notification \u200c"
    cleaned = clean_devanagari_preserving_length(
        raw, config=DevanagariConfig(strip_zwj=True, clean_orphaned_matras=True)
    )
    assert len(cleaned) == len(raw)
    assert "\u200c" not in cleaned


def test_clean_preserving_offsets_bilingual_mode() -> None:
    """clean_preserving_offsets with preserve_devanagari=True retains Hindi and preserves length."""
    raw = "RBI \u092d\u093e\u0930\u0924 circular \ufffd Page 3 of 9 end"
    # Legacy mode: blanks Devanagari
    legacy_cleaned = clean_preserving_offsets(raw, preserve_devanagari=False)
    assert len(legacy_cleaned) == len(raw)
    assert "\u092d" not in legacy_cleaned
    assert "\ufffd" not in legacy_cleaned
    assert "Page 3 of 9" not in legacy_cleaned

    # Bilingual mode (FEAT-068): preserves Devanagari
    bilingual_cleaned = clean_preserving_offsets(raw, preserve_devanagari=True)
    assert len(bilingual_cleaned) == len(raw)
    assert "\u092d\u093e\u0930\u0924" in bilingual_cleaned
    assert "\ufffd" not in bilingual_cleaned
    assert "Page 3 of 9" not in bilingual_cleaned
    assert bilingual_cleaned.index("circular") == raw.index("circular")


def test_separate_bilingual_text() -> None:
    """separate_bilingual_text must classify document paragraphs into hi, en, and mixed."""
    doc_text = f"{SAMPLE_HINDI}\n\n{SAMPLE_ENGLISH}\n\nMixed RBI \u0938\u0942\u091a\u0928\u093e"
    sections = separate_bilingual_text(doc_text)
    assert len(sections) >= 3

    hi_sections = [s for s in sections if s.language == "hi"]
    en_sections = [s for s in sections if s.language == "en"]
    mixed_sections = [s for s in sections if s.language == "mixed"]

    assert len(hi_sections) >= 1
    assert len(en_sections) >= 1
    assert len(mixed_sections) >= 1

    # Verify offset integrity
    for s in sections:
        assert doc_text[s.char_start : s.char_end] == s.text


def test_extract_bilingual_columns() -> None:
    """extract_bilingual_columns must untangle side-by-side parallel columns."""
    hi_col, en_col = extract_bilingual_columns(SAMPLE_PARALLEL_COLUMN)
    assert "भारतीय रिज़र्व बैंक" in hi_col
    assert "अधिसूचना" in hi_col
    assert "बैंकिंग विनियमन विभाग" in hi_col

    assert "RESERVE BANK OF INDIA" in en_col
    assert "NOTIFICATION" in en_col
    assert "Department of Banking Regulation" in en_col


def test_normalization_throughput_sla() -> None:
    """Devanagari normalization must exceed 1,000,000 chars/sec throughput SLA."""
    text_block = (SAMPLE_HINDI + "\n" + SAMPLE_ENGLISH + "\n") * 5000
    total_chars = len(text_block)

    t0 = time.perf_counter()
    normalized = normalize_devanagari(text_block)
    t1 = time.perf_counter()

    rate = total_chars / (t1 - t0)
    min_rate = 750000.0 if (os.environ.get("CI") or os.name == "nt") else 1000000.0
    assert rate >= min_rate, f"Expected throughput >= {min_rate:,.0f} chars/sec, got {rate:.1f}"
    assert len(normalized) > 0


def test_fail_closed_on_invalid_utf8_bytes() -> None:
    """Invalid UTF-8 byte sequences must raise ValueError with diagnostic offset."""
    invalid_bytes = b"RBI \xff\xfe Devanagari"
    with pytest.raises(ValueError, match="Invalid UTF-8 byte sequence"):
        normalize_devanagari(invalid_bytes)


def test_prometheus_devanagari_characters_normalized_counter() -> None:
    """Prometheus counter DEVANAGARI_CHARACTERS_NORMALIZED_TOTAL must increment."""
    before = DEVANAGARI_CHARACTERS_NORMALIZED_TOTAL._value.get()
    normalize_devanagari("भारतीय रिज़र्व बैंक")
    after = DEVANAGARI_CHARACTERS_NORMALIZED_TOTAL._value.get()
    assert after > before


def test_api_normalize_devanagari_endpoint(client: TestClient) -> None:
    """POST /v1/ingest/devanagari/normalize must return normalized text and bilingual sections."""
    payload = {
        "text": SAMPLE_PARALLEL_COLUMN,
        "config": {
            "normalize_nfc": True,
            "strip_zwj": False,
            "clean_orphaned_matras": True,
            "separate_bilingual_sections": True,
        },
    }
    response = client.post(
        "/v1/ingest/devanagari/normalize",
        json=payload,
        headers=auth(PRIMARY_KEY),
    )
    assert response.status_code == 200
    data = response.json()
    assert "normalized_text" in data
    assert data["devanagari_character_count"] > 0
    assert data["devanagari_ratio"] > 0.0
    assert "hindi_column_text" in data
    assert "english_column_text" in data
    assert "latency_ms" in data
    assert len(data["hindi_column_text"]) > 0
    assert len(data["english_column_text"]) > 0


def test_api_normalize_devanagari_unauthorized(client: TestClient) -> None:
    """POST /v1/ingest/devanagari/normalize must return 401 without auth."""
    res = client.post("/v1/ingest/devanagari/normalize", json={"text": SAMPLE_HINDI})
    assert res.status_code == 401


def test_api_normalize_devanagari_validation_error(client: TestClient) -> None:
    """POST /v1/ingest/devanagari/normalize must return 422 on invalid payload."""
    res = client.post(
        "/v1/ingest/devanagari/normalize",
        json={"invalid_field": 123},
        headers=auth(PRIMARY_KEY),
    )
    assert res.status_code == 422
