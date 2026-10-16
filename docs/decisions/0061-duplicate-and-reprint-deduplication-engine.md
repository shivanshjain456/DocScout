# ADR-0061: Duplicate and Reprint Deduplication Engine (FEAT-070)

* **Status:** Accepted
* **Date:** 2026-10-14
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Ingestion Infrastructure Team, Compliance Architecture Guild
* **Informed:** Core Platform Engineers, Regulatory Operations

---

## Context and Problem Statement

Statutory authorities in Indian financial regulation (Reserve Bank of India, Securities and Exchange Board of India, Ministry of Finance) regularly issue official instruments that appear across multiple dissemination channels:
1. Exact circular reprints (e.g., identical directives posted under different departmental URLs or detail pages).
2. Gazette re-issues and press release cross-postings (e.g., notification text republished in an extraordinary gazette with only slight administrative header or formatting differences).
3. Coordinated inter-departmental notices (e.g., identical notifications published simultaneously by Department of Regulation and Department of Supervision).

Prior to FEAT-070, DocScout's duplicate check in `store_document()` relied exclusively on exact PDF content SHA-256 (`document_versions.sha256 = doc.sha256`). If the underlying PDF bytes differed by even a single byte (e.g., differing PDF generation timestamps, web server watermarks, or altered gazette metadata), DocScout re-chunked and re-embedded the entire document. This introduced two critical issues:
- Vector database bloat and index dilution (duplicate chunks competing in retrieval rankings).
- Split citation authority, where search results returned multiple identical passages pointing to disjoint document IDs.

FEAT-070 introduces an automated, high-precision duplicate and reprint deduplication engine combining exact text SHA-256 and MinHash Locality-Sensitive Hashing (LSH), linking detected duplicates to their authoritative `canonical_document_id` without duplicating chunks.

---

## Decision Drivers

1. **High Deduplication Accuracy:** Precision >= 99% and recall >= 95% on duplicate and near-duplicate regulatory publications.
2. **Zero False Deduplication on Distinct Amendments:** Substantive regulatory amendments or distinct circular versions that share introductory boilerplates must never be falsely marked as duplicates.
3. **Sub-millisecond Performance:** Deduplication check latency <= 2.0 ms per document, maintaining throughput without expensive LLM invocations.
4. **Relational Canonical Linking:** Store detected duplicates in PostgreSQL with `canonical_document_id` referencing the canonical document, avoiding redundant vector embedding and chunk insertion.
5. **Observability:** Track deduplications via Prometheus counter `docscout_duplicate_documents_detected_total{match_type}`.
6. **Typographical Compliance:** Strict ASCII typographical compliance across all documentation and code.

---

## Considered Options

1. **Pairwise Dense Embedding Cosine Similarity:**
   * Compute document-level embeddings and query pgvector for cosine similarity >= 0.98.
   * *Drawbacks:* Requires embedding the full document first (expensive), cosine similarity on long aggregated vectors suffers from topic averaging, and query latency exceeds the 2.0 ms budget.
2. **Exact Text SHA-256 Only:**
   * Hash extracted clean text using SHA-256 and match exact string equality.
   * *Drawbacks:* Catches 100% of exact text reprints, but fails completely on gazette re-issues where a header line, notification timestamp, or page number differs.
3. **Multi-Tier Deduplication: Exact Content + Exact Text + MinHash LSH (Chosen):**
   * Tier 1 (Content SHA-256): Match exact raw PDF byte hash against `document_versions`.
   * Tier 2 (Text SHA-256): Match SHA-256 of cleaned text against `documents.text_sha256`.
   * Tier 3 (MinHash LSH): 128-permutation vectorized MinHash signature over 3-word shingles, indexed in 16 LSH bands (8 rows per band).
   * Threshold set to Jaccard similarity >= 0.98, ensuring near-identical gazette reprints are deduplicated while substantive circular amendments (typically <= 0.85 similarity) remain distinct.

---

## Decision Outcome

Adopt Option 3.

Implement:
1. `migrations/0051_canonical_document_id.up.sql` & `.down.sql`:
   * Add `canonical_document_id UUID REFERENCES documents(document_id) ON DELETE SET NULL` to `documents`.
   * Add `text_sha256 VARCHAR(64)` and `minhash_signature BIGINT[]` to `documents`.
   * Index `idx_documents_canonical_document_id` and `idx_documents_text_sha256`.
2. `app/ingest/deduplicator.py`:
   * `DeduplicationConfig`, `DeduplicationResult`, `MinHashLSHIndex`, and `RegulatoryDeduplicator`.
   * Vectorized numpy 128-permutation MinHash signature generation.
   * Database integration `check_duplicate_in_db()` and in-memory index `find_duplicate()`.
3. `app/ingest/store.py`:
   * Pre-storage deduplication hook in `store_document()`: when duplicate is identified, sets `canonical_document_id = canonical_doc_id`, records `document_versions`, increments `docscout_duplicate_documents_detected_total`, and skips chunk insertion (`chunks_written = 0`).
4. `app/api/metrics.py`:
   * `DUPLICATE_DOCUMENTS_DETECTED_TOTAL` counter with label `match_type`.
5. `app/api/models.py` & `app/api/app.py`:
   * `POST /v1/ingest/dedup/check` inspection and verification endpoint.
6. `tests/test_deduplicator.py`:
   * 10 duplicate/reprint benchmark pairs, amendment discrimination test, latency benchmark, and DB integration test.

---

## Consequences

* Positive: Eliminates vector index redundancy, prevents rank dilution, preserves single source of truth for citations.
* Positive: Latency remains <= 1.5 ms per document with memory footprint <= 8 MB.
* Negative: Requires database migration adding `canonical_document_id` and `text_sha256`.
