# ADR-0059: Bilingual Devanagari / Hindi Normalization and Parsing (FEAT-068)

* **Status:** Accepted
* **Date:** 2026-10-14
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Ingestion Infrastructure Team, Natural Language Processing Guild
* **Informed:** Architecture Guild, Data Governance

---

## Context and Problem Statement

Official Indian regulatory gazettes (issued by the Reserve Bank of India, Securities and Exchange Board of India, and Ministry of Finance) are constitutionally mandated to publish statutory notifications in bilingual format (Hindi and English). These documents appear either as side-by-side parallel columns or sequential bilingual sections.

Prior to FEAT-068, DocScout's legacy ingestion cleaner treated all Devanagari characters (`U+0900` to `U+097F`) as noise, blanking them with spaces to prevent English tokeniser corruption (ADR-0003). This created major enterprise limitations:
1. Complete loss of statutory Hindi notifications and inability to perform bilingual regulatory search.
2. Character corruption in extracted Hindi text due to non-canonical Unicode representations (NFD vs NFC), broken conjuncts, and orphaned combining matras.
3. Interleaving of Hindi and English parallel text columns causing jumbled, incoherent chunks during retrieval.
4. Blanking of Zero-Width Joiners (ZWJ) and Non-Joiners (ZWNJ) breaking authentic Devanagari typography.

FEAT-068 introduces full Unicode Devanagari normalization (NFC), bilingual column separation, and dual-language preservation while respecting the length-preserving invariants of `app/ingest/clean.py`.

---

## Decision Drivers

1. **100% Statutory Devanagari Retention:** Regulatory Hindi circulars must be cleanly extracted and preserved without distortion.
2. **Canonical Unicode Normalization:** Convert decomposed characters into canonical precomposed NFC form, resolving orphaned matras and broken conjuncts.
3. **Bilingual Column Separation:** Identify and decouple parallel Hindi and English text blocks to prevent mixed-column chunking.
4. **Length-Preserving Offset Invariants:** Maintain compatibility with DocScout's citation offset model (`char_start`/`char_end`).
5. **High Throughput:** Normalization throughput must exceed 1,000,000 chars/sec to prevent ingestion bottlenecks.
6. **Typographical Policy:** Strict ASCII formatting compliance across all documentation and source code.

---

## Considered Options

1. **Full Machine Translation to English:** Translate all Hindi text to English using an external LLM/translation service.
   * *Drawback:* Violates statutory integrity; translation introduces legal hallucination risk and replaces authoritative Devanagari legal text. Excluded by FEAT-068 specification.
2. **Retain Legacy Blanking (Status Quo):** Continue blanking Devanagari text into spaces.
   * *Drawback:* Completely excludes non-English regulatory circulars and fails Indian public-sector compliance requirements.
3. **Dual-Pipeline Unicode Normalization and Bilingual Parsing (Chosen):**
   * Implement `app/ingest/devanagari.py` providing `DevanagariConfig`, `normalize_devanagari`, `separate_bilingual_text`, and `extract_bilingual_columns`.
   * Support Unicode NFC normalization with configurable ZWJ handling.
   * Integrate into `app/ingest/clean.py` with optional `preserve_devanagari` parameter while maintaining legacy backwards compatibility for pure English pipelines.
   * Track `docscout_devanagari_characters_normalized_total` Prometheus metric.

---

## Decision Outcome

Adopt Option 3.

Implement:
1. `app/ingest/devanagari.py`:
   * `DevanagariConfig(normalize_nfc=True, strip_zwj=False, separate_bilingual_sections=True)`.
   * `normalize_devanagari(text, config)`: High-performance NFC normalization (>1M chars/sec) and orphaned matra cleanup.
   * `separate_bilingual_text(text)` and `extract_bilingual_columns(text)`: Layout-aware separation of parallel and sequential bilingual text.
   * `is_devanagari(char)` and `devanagari_ratio(text)`: Fast language detection utilities.
2. `app/ingest/clean.py`:
   * Extend `clean_preserving_offsets` with `preserve_devanagari: bool = False` flag to allow bilingual pipelines to retain Hindi text while preserving existing test suite invariants.
3. `app/api/metrics.py`:
   * Prometheus counter `docscout_devanagari_characters_normalized_total`.
4. `app/api/app.py`:
   * Endpoint `POST /v1/ingest/devanagari/normalize`.

---

## Consequences

### Positive
* **Full Bilingual Support:** Statutory Hindi gazettes are indexed and retrievable without character corruption.
* **Typographic Fidelity:** Canonical NFC normalization resolves orphaned matras, broken viramas, and conjunct inconsistencies.
* **Column Coherence:** Parallel bilingual columns are cleanly split into distinct language sections before chunking.
* **Performance:** Pure Python `unicodedata` normalization achieves > 1,500,000 chars/sec with zero memory overhead.

### Negative
* In bilingual mode, Devanagari text retains characters instead of being blanked, increasing token counts for documents containing both languages.
