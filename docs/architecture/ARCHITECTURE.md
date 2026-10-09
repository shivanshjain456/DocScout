# DocScout: Architecture

**Status:** authoritative architecture document. Last updated **2026-10-09**.
**Implementation status:** fully implemented, tested (511 tests passing), and verified in production containers.

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / RESOLVED**) are defined in `SPEC.md` §1.

**Relationship to `docs/architecture/system-diagram.md`:** that file holds the Mermaid rendering of
the system and the trust-boundary table.

---

## 1. Architectural drivers

What shapes this design:

1. **Citations are the product, not a feature.** An answer without a resolvable citation is a
   failure. This forces chunk-level provenance all the way from fetched bytes to rendered citations
   (`SPEC.md` FR-7, FR-11, FR-14).
2. **Corpus text is hostile by assumption.** Public PDFs are untrusted input that reaches language
   model contexts. This forces strict delimiter discipline and data/instruction separation (`SECURITY.md` S-7).
3. **Measured, not asserted.** Quality and performance claims must be backed by a committed artifact
   (`docs/QUALITY_BAR.md` Q-7). The evaluation harness is a first-class component.
4. **Target hardware efficiency.** High performance on a 2 vCPU / 1.9 GiB RAM CPU floor with no GPU
   requirement. The embedder and retrieval stack operate with low latency (p95 42 ms cold, 2 ms warm).
5. **Offline and online paths must not share credentials.** Ingestion runs with no deploy credentials
   (`SECURITY.md` S-4).

---

## 2. System context

```
   RBI / SEBI public websites            Compliance analyst (browser)
            | HTTPS, read-only                     | HTTPS
            v                                      v
   +---------------------+              +----------------------+
   |  OFFLINE: ingestion |              |  ONLINE: query path  |
   |  no deploy creds    |              |  API-key gated       |
   +----------+----------+              +----------+-----------+
              | writes                              | reads
              v                                     v
        +----------------------------------------------+
        |  Postgres 18.6 + pgvector 0.8.6 (VERIFIED)   |
        |  documents, versions, chunks, audit log      |
        +----------------------------------------------+
                     ^                      |
                     | reads only           v
        +------------+-----------+   +--------------+
        |  EVAL harness (offline)|   |  In-process  |
        |  no ingest network     |   |  cache/limits|
        +------------------------+   +--------------+
```

The runtime paths share only the database. The evaluation harness reads the database and the
committed gold set with no network access to ingestion sources.

---

## 3. Components

### 3.1 `app/ingest/`: offline pipeline (VERIFIED)

Stages: **fetch -> extract -> guard -> clean -> chunk -> embed -> store -> scan -> refresh.**

Built and verified over 35 documents and 230 chunks:
- **fetch**: Host allowlist of exactly three hosts (`www.rbi.org.in`, `rbidocs.rbi.org.in`, `www.sebi.gov.in`), HTTPS only, redirect re-validation (`app/ingest/fetch.py`, `allowlist.py`).
- **extract**: `pypdf` for PDFs, `trafilatura` for HTML, iframe resolution for SEBI detail stubs (`app/ingest/extract.py`).
- **guard**: Rejection of documents under 500 clean non-whitespace characters (`app/ingest/guards.py`).
- **clean**: Stripping invisible codepoints, mojibake, and formatting artifacts while preserving character offsets (`app/ingest/clean.py`).
- **chunk**: Fixed-width 1,000 characters with 150-character overlap on whitespace boundaries, 512-token ceiling (ADR-0003, `app/ingest/chunk.py`).
- **embed**: `BAAI/bge-small-en-v1.5`, 384 dimensions, L2-normalized unit vectors (ADR-0002, `app/ingest/embed.py`).
- **store**: Transactional storage with content-hash deduplication and immutable versions (`app/ingest/store.py`).
- **scanner**: Ingestion-time scanning for API keys, private keys, SaaS tokens, and PII with automatic sample masking (`app/ingest/scanner.py`, ADR-0015).
- **refresh**: Scheduled audit and conditional HTTP change checking (`app/ingest/refresh.py`, ADR-0013).
- **metadata**: Authoritative document titles and dates populated across all corpus documents (Migration 0006, `app/ingest/metadata.py`, ADR-0018).

Idempotency (NFR-8) is verified: unchanged documents are skipped in 0.015 s. Content-derived UUIDv5 chunk identifiers
ensure stable cross-version citations (ADR-0005).

### 3.2 `app/retrieval/`: hybrid retrieval and expansion (VERIFIED)

Stages:
1. **Domain query expansion**: `DomainQueryExpander` provides bidirectional acronym/synonym expansion
   across 36+ regulatory terms and optional HyDE formulation (ADR-0017).
2. **Metadata filtering**: In-query SQL filtering in PostgreSQL (`app/retrieval/dense.py`) backed by composite indices,
   and in-index candidate pruning in BM25 (`app/retrieval/lexical.py`), supporting authority, date windows, currency,
   and document targets without top-k candidate starvation (ADR-0016).
3. **Lexical arm**: BM25 ranking over stored chunks with in-memory term indexing (`app/retrieval/lexical.py`).
4. **Dense arm**: pgvector KNN over HNSW index using cosine distance (`app/retrieval/dense.py`).
5. **Fusion**: Reciprocal Rank Fusion (RRF k=60) combining lexical and dense candidate lists with arm-anchored guarantees (ADR-0006, ADR-0007).
6. **Reranking**: Cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`) built, tested, and evaluated,
   but disabled in serving configuration (ADR-0009).

### 3.3 `app/generate/`: grounded answer generation (VERIFIED)

Assembles prompts, invokes local model generation, validates citations, and implements explicit refusal (ADR-0011):
- Chunks wrapped in `<document>` delimiters with system instructions marking context as data and never instructions (FR-12).
- Citations are validated deterministically: every cited chunk must have been present in the retrieved context (FR-11).
- Unanswerable and prompt-injection canary inputs trigger explicit refusals (FR-13).
- Calibrated cross-judge agreement: Cohen's kappa 1.000 / 0.844, 100% canary defense.

### 3.4 `app/evals/`: evaluation and regression gating (VERIFIED)

Owns the gold set (v2.0.0, 425 items), deterministic scorers (recall, MRR, nDCG, citation P/R),
cross-judge calibration, and automated regression gating (`app/evals/gate.py`, `make eval-gate`).

### 3.5 `app/api/`: serving and operational probes (VERIFIED)

FastAPI service (`app.api.app:app`) providing:
- `POST /v1/search`: evidence-only retrieval with resolvable citations, confidence score, and metadata filtering.
- `POST /v1/answer`: grounded answer generation with mandatory citation validation.
- `GET /v1/documents/{document_id}`: document resolution endpoint returning full metadata and version lineage.
- `GET /healthz`: zero-DB liveness probe (safe for orchestrator liveness checks).
- `GET /readyz`: traffic readiness probe (verifies DB pool, chunk count, staleness budgets).
- `POST /v1/admin/cache/invalidate`: authenticated admin endpoint for cache clearance and index reload.
- `GET /metrics`: Prometheus metrics exposition.
- `GET /`: interactive demo UI.

---

## 4. Data model: VERIFIED

Applied through 6 migrations (`migrations/0001` through `migrations/0006`):

| Table | Key columns | Purpose |
|---|---|---|
| `documents` | `document_id` (PK, uuidv7), `canonical_url` (unique), `source`, `title`, `authority`, `published_date`, `detail_page` | One logical circular, stable across reissues |
| `document_versions` | `version_id` (PK), `document_id` (FK), `sha256` (globally unique), `fetch_ts`, `http_status`, `bytes`, `pages`, `extractor`, `char_count`, `is_current` | One observed byte-state; new sha256 creates new version |
| `chunks` | `chunk_id` (PK, uuid5), `document_id` + `version_id` (FK), `ordinal`, `text`, `char_start`, `char_end`, `token_count`, `tsv` (STORED), `embedding` (`vector(384)`) | Retrievable chunk with content-derived UUIDv5 |
| `corpus_sync_state` | `singleton_id` (PK), `last_checked_at`, `stale_hours`, `is_stale`, `current_version_count`, `superseded_version_count` | Singleton table tracking corpus audit and freshness |
| `retrieval_audit_log` | `log_id` (PK), `timestamp`, `key_fingerprint`, `query_hash`, `mode`, `k`, `returned_chunk_ids`, `latency_ms`, `cache_hit`, `has_generated_answer`, `corpus_generation` | Append-only audit record for retrieval forensics |

Indices:
- HNSW on `chunks.embedding` using `vector_cosine_ops` (m=16, ef_construction=64).
- GIN on `chunks.tsv` for full-text search.
- B-tree indices on `documents(source)`, `documents(published_date)`, `documents(source, published_date)`.
- B-tree indices on `document_versions(fetch_ts)` and `document_versions(is_current)`.

---

## 5. Technology decisions

| Decision | Status | Rationale | ADR |
|---|---|---|---|
| Postgres + pgvector single store | DECIDED | Transactional consistency, lexical + vector in one engine | ADR-0004 |
| HNSW index | DECIDED | High recall without training phase, incremental inserts | ADR-0004 |
| Embedding model `bge-small-en-v1.5` | DECIDED | 384 dims, zero truncation at 512 tokens, CPU-efficient | ADR-0002 |
| Fixed-width chunking (1000/150) | DECIDED | Preserves legal clause context, 96.5% span integrity | ADR-0003 |
| Content-derived chunk UUIDv5 | DECIDED | Chunk IDs survive re-ingestion and database rebuilds | ADR-0005 |
| Hybrid RRF retrieval | DECIDED | Combines exact token matching with semantic recall | ADR-0006 |
| Arm-anchored fusion | DECIDED | Guarantees top hit from each arm is represented | ADR-0007 |
| Grounded answer generation | DECIDED | Model answers grounded in evidence, validated citations | ADR-0011 |
| Corpus scale expansion | DECIDED | 35 docs, 230 chunks, 425 gold items desaturates recall | ADR-0012 |
| Scheduled refresh and freshness | DECIDED | Automated drift detection and staleness budgeting | ADR-0013 |
| Invalidation on supersession | DECIDED | Event-driven cache clearance and readiness probe split | ADR-0014 |
| Append-only audit log & PII scan | DECIDED | Forensic traceability with query privacy (SHA-256) | ADR-0015 |
| In-query metadata filtering | DECIDED | Prevents candidate starvation, filtered index scans | ADR-0016 |
| Domain query expansion | DECIDED | Recovers regulatory acronyms and synonyms | ADR-0017 |
| Authoritative citation titles | DECIDED | Enriches citations with official titles and dates | ADR-0018 |
