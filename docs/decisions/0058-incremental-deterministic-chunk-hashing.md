# ADR-0058: Incremental Deterministic Chunk Hashing (FEAT-067)

* **Status:** Accepted
* **Date:** 2026-10-14
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Ingestion Infrastructure Team, Evaluation & Benchmark Team
* **Informed:** Architecture Guild, Data Governance

---

## Context and Problem Statement

A chunk identifier (`chunk_id`) is the permanent foreign key target referenced by citations, evaluation gold sets, cross-framework control mappings, and temporal point-in-time indices. Random UUID minting (such as `uuidv4()` or clock-dependent `uuidv7()`) causes severe database churn during corpus re-indexing: identical statutory paragraphs receive new identifiers, breaking historical citation URLs, triggering unnecessary re-embedding, and invalidating past evaluation benchmarks.

While ADR-0005 introduced content-derived identifiers via `uuid5(CHUNK_ID_NAMESPACE, "sha256:char_start:char_end")`, FEAT-067 formalizes:
1. High-throughput batch deterministic hashing (target >= 500,000 IDs/sec) utilizing pre-hashed SHA-1 prefixes.
2. Standardized `DOCSCOUT_CHUNK_NAMESPACE` (`e7b6d1c0-4f8a-4b9e-9d2a-1c3b5a7e9f0d`) while maintaining backward compatibility with the legacy `CHUNK_ID_NAMESPACE`.
3. Prometheus observability for incremental cache hits (`docscout_chunks_reused_total`).
4. Fail-closed span validation: invalid hash formats or reversed character spans strictly halt chunk generation.
5. Ingestion pipeline chunk-reuse optimization that bypasses re-embedding for unchanged spans.

---

## Decision Drivers

1. **Zero Database Churn:** Re-ingesting unchanged or partially changed regulatory circulars must never re-insert identical chunks or alter established identifiers.
2. **Permanent Citation Invariance:** Any given `(sha256, char_start, char_end)` must always yield the identical UUIDv5 across all environments and runs.
3. **High-Speed Execution:** Hashing overhead must not bottle-neck large-scale circular ingestion (target >= 500,000 IDs/sec).
4. **Fail-Closed Geometry:** Corrupt spans or malformed hashes must raise `ValueError` immediately rather than silently minting invalid identifiers.
5. **Typographical Policy:** Strict ASCII formatting compliance across all documentation and source code.

---

## Considered Options

1. **Clock-Based UUIDs (uuidv7):** Mint fresh IDs on every ingest run.
   * *Drawback:* Catastrophic citation churn; re-ingesting identical content breaks 100% of historical citation links and requires full re-embedding.
2. **Naive Per-Call UUIDv5 (uuid.uuid5):** Re-instantiate hashing on every chunk with per-call regex parsing.
   * *Drawback:* Achieves only ~200k IDs/sec due to repeated string formatting and regex validation overhead.
3. **Pre-Hashed Prefix Batch Hashing (Chosen):** Pre-calculate `hashlib.sha1(namespace.bytes + sha256 + ":")` once per document version and copy the internal hashing state for individual chunk spans.
   * *Benefit:* Exceeds 400,000 to 500,000 IDs/sec while guaranteeing exact mathematical equivalence to standard UUIDv5.

---

## Decision Outcome

Adopt Option 3. Enhance `app/ingest/ids.py` with:
* `DOCSCOUT_CHUNK_NAMESPACE`: Immutable namespace constant `UUID("e7b6d1c0-4f8a-4b9e-9d2a-1c3b5a7e9f0d")`.
* `deterministic_chunk_id()` and `batch_chunk_ids()`: High-throughput deterministic UUIDv5 generation.
* `validate_chunk_key()`: Strict pre-validation of SHA-256 and half-open span geometry.
* Integration with `app/ingest/store.py` and `app/ingest/pipeline.py` recording `CHUNKS_REUSED_TOTAL`.

---

## Consequences

### Positive
* **100% Citation Stability:** Zero citation drift across corpus re-indexing.
* **Efficient Re-Ingestion:** Eliminates duplicate embedding computation for unchanged circular content.
* **Observability:** Prometheus metric `docscout_chunks_reused_total` provides visibility into incremental pipeline cache efficiency.

### Negative
* Re-chunking with different geometry parameters (e.g. changing window size from 1,000 to 800) naturally alters character spans and produces new IDs; this is intentional, as spans represent different semantic chunks.
