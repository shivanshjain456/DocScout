# ADR-0060: Automated Regulatory Metadata and Notification ID Extraction (FEAT-069)

* **Status:** Accepted
* **Date:** 2026-10-14
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Ingestion Infrastructure Team, Compliance Architecture Guild
* **Informed:** Core Platform Engineers, Regulatory Operations

---

## Context and Problem Statement

Statutory circulars issued by Indian financial regulators (Reserve Bank of India, Securities and Exchange Board of India, and Ministry of Finance) carry authoritative administrative identifiers in their headers and footers. These include:
1. Official circular reference numbers (e.g., `RBI/2026-27/273`, `RBI/2024-25/111`, `SEBI/HO/DDHS/DDHS-PoD-1/P/CIR/2024/123`, `HO/19/34/14(8)2026-AFD-POD2/ I/19251/2026`).
2. Issuing department names (e.g., `Department of Regulation`, `Department of Currency Management`, `Department of Debt and Hybrid Securities`).
3. Official subject/title directives (e.g., `Cassette - Swaps in ATMs`, `Guidelines on Digital Lending`).
4. Issue date (e.g., `October 01, 2026`, `September 04, 2024`).
5. Signoff authority name and rank (e.g., `(Sanjeev Prakash) Chief General Manager-in-Charge`, `(R. Lakshmi) Chief General Manager`).

Prior to FEAT-069, document metadata ingestion relied either on hardcoded static lookup mappings in `CANONICAL_DOCUMENT_METADATA` or manual manifest annotations. In-flight and unseen regulatory gazettes lacked automated extraction of these fields, leaving relational database columns (`circular_no`, `issuing_department`, `subject`, `signoff_authority`) populated with NULL values or unparsed strings. This prevented exact administrative filtering and granular regulatory discovery.

FEAT-069 introduces high-performance, deterministic layout-aware regex metadata extraction immediately following text extraction, populating structured columns in PostgreSQL with >= 98% accuracy on official regulatory publications.

---

## Decision Drivers

1. **High Extraction Accuracy (>= 98%):** Successfully extract circular reference numbers, issuing departments, subjects, dates, and signoff officers across official RBI and SEBI publications.
2. **Deterministic and Sub-millisecond Execution:** Extraction latency must remain <= 1.5 ms per document with zero extra memory overhead, precluding expensive LLM calls during ingestion.
3. **Strict Validation and Non-Invention:** Never invent or fabricate circular numbers for informal documents, press releases, or synthetic canaries; gracefully fall back to NULL with diagnostic logging.
4. **Relational Schema Integration:** Persist extracted metadata into dedicated columns on `documents(circular_no, issuing_department, subject, signoff_authority)` with indexed lookup capability.
5. **Prometheus Observability:** Instrument extraction metrics via `docscout_metadata_fields_extracted_total{field_name}` counter.
6. **Typographical Compliance:** Strict ASCII adherence across all documentation and implementation files.

---

## Considered Options

1. **LLM-Based Metadata Extraction:** Run an LLM prompt on the document header to extract JSON fields.
   * *Drawbacks:* High latency (500-2000 ms vs <= 1.5 ms requirement), nondeterministic output, expensive token costs, and legal hallucination risks on regulatory identifiers.
2. **Static Mapping Table (Status Quo):** Continue maintaining manual metadata tables per URL.
   * *Drawbacks:* Fails completely on continuous ingestion of newly published circulars and requires manual maintenance.
3. **Layout-Aware Compiled Regular Expression Engine (Chosen):**
   * Implement `app/ingest/metadata_extractor.py` featuring `RegulatoryMetadataExtractor`, `DocumentMetadata`, and `MetadataExtractorConfig`.
   * Compile high-precision patterns for RBI (`RBI/YYYY-YY/NNN`, departmental reference codes, date stamps, signoff patterns) and SEBI (`SEBI/HO/...`, `HO/...`, `CIR/...`).
   * Add PostgreSQL migration `0050_document_metadata_columns.up.sql` to introduce and index `circular_no`, `issuing_department`, `subject`, and `signoff_authority` on `documents`.
   * Integrate seamlessly into `app/ingest/extract_chain.py` and `app/ingest/store.py`.
   * Expose `POST /v1/ingest/metadata/extract` API endpoint and instrument with Prometheus counter `docscout_metadata_fields_extracted_total`.

---

## Decision Outcome

Adopt Option 3.

Implement:
1. `migrations/0050_document_metadata_columns.up.sql` & `.down.sql`:
   * Add `circular_no`, `issuing_department`, `subject`, `signoff_authority` to table `documents`.
   * Create B-tree indexes `idx_documents_circular_no` and `idx_documents_issuing_department`.
2. `app/ingest/metadata_extractor.py`:
   * `DocumentMetadata`: Typed dataclass representing structured document metadata.
   * `MetadataExtractorConfig`: Configuration with `strict_pattern_matching: bool = True`.
   * `RegulatoryMetadataExtractor`: High-speed extractor with compiled regex rules for RBI, SEBI, and Central Government gazettes.
   * `extract_document_metadata(text, filename, config)`: Main entry point enforcing input validation (text >= 100 characters).
3. `app/ingest/extract_chain.py`:
   * Expose `extract_document_metadata` helper for downstream ingestion stages.
4. `app/api/metrics.py`:
   * `METADATA_FIELDS_EXTRACTED_TOTAL` counter with label `field_name`.
5. `app/api/models.py` & `app/api/app.py`:
   * Models `MetadataExtractorConfigModel`, `RegulatoryMetadataExtractRequest`, `RegulatoryMetadataExtractResponse`.
   * Route `POST /v1/ingest/metadata/extract`.
6. `tests/test_metadata_extractor.py`:
   * Comprehensive unit and integration test suite validating >= 98% accuracy across all corpus documents.

---

## Consequences

### Positive
* **Exact Administrative Filtering:** Users and enterprise compliance systems can filter circulars directly by official circular number (`RBI/2026-27/273`) or issuing department (`Department of Regulation`).
* **High Performance:** Regex parsing completes in < 1.0 ms per document with zero allocations or API network calls.
* **Deterministic Lineage:** Guarantees repeatable extraction matching official government gazette numbering conventions.
* **Observability:** Metric tracking provides visibility into field extraction rates and pattern coverage.

### Negative
* New gazette layout formats introduced by regulators in the future may require pattern expansion in `metadata_extractor.py`.
