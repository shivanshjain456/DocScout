# DocScout: Product & System Specification

**Status of this document:** authoritative specification. Last updated **2026-10-09**.
**Implementation status of the system it describes:** **IMPLEMENTED AND VERIFIED**.
The operational RAG service is live, tested (511 tests passing), containerized, and benchmarked against leading open-source RAG systems.

This document is the root of a seven-document set. Each is readable alone; together they are one
source of truth.

| Document | Owns |
|---|---|
| `SPEC.md` (this file) | Problem, scope, users, functional/non-functional requirements, interfaces, global register |
| `docs/architecture/ARCHITECTURE.md` | Components, data model, data flow, boundaries, technology decisions |
| `docs/corpus/CORPUS_SPEC.md` | What the corpus is, how it is acquired, identified, versioned, and extracted |
| `docs/eval/EVAL_PROTOCOL.md` | Gold set, scorers, judge calibration, thresholds, CI gate, reporting |
| `SECURITY.md` | Threat model, controls, secret handling, injection posture, disclosure |
| `docs/QUALITY_BAR.md` | Definition of done, gates that must pass, evidence rules |
| `docs/MILESTONES.md` | Ordered delivery plan, entry/exit criteria, current position |

---

## 1. Status vocabulary (used identically in all seven documents)

| Tag | Meaning | Burden of proof |
|---|---|---|
| **VERIFIED** | Observed in this repository or environment, with a named evidence artifact | Must cite a file path or command output |
| **SPECIFIED** | A normative requirement of the system | Must be testable |
| **PROPOSED** | A design choice first written down here | Needs sign-off or an ADR before it becomes binding |
| **BLOCKED** | Cannot proceed without a named external input | Must name the input and who supplies it |
| **RESOLVED** | Previously unresolved question closed with evidence | Names the closing ADR and evidence |

**RFC 2119 keywords** (MUST / MUST NOT / SHOULD / MAY) carry their usual meaning and apply to
requirements tagged SPECIFIED or VERIFIED.

---

## 2. Problem and current position

### 2.1 Problem

Indian financial-sector compliance work depends on circulars, notifications, and master circulars
published by the **Reserve Bank of India (RBI)** and the **Securities and Exchange Board of India
(SEBI)**. These are long PDFs, published continuously, frequently superseded, and searchable only by
title or date on the issuing sites. Answering a question such as *"what is the current cash-withdrawal
limit rule and which circular sets it"* requires locating the governing document among many, reading
it, and confirming it has not been superseded.

DocScout is a retrieval-augmented question-answering service over that corpus that returns an answer
**and** the citations that support it, so the answer can be checked against the primary source rather
than trusted blindly.

### 2.2 Current position: VERIFIED

All core and forced operational capabilities across P0 (blocking operational maturity), P1 (expected operational maturity),
and P2 (forced operational capabilities) are implemented, verified, committed, and pushed to `origin/master`:

- `app/ingest/`: Offline ingestion pipeline with host allowlists, pluggable extraction chain (fast `pypdf` + deep OCR/layout parser fallback, ADR-0022), text cleaning, fixed-width chunking with overlap, BGE-small embeddings, PostgreSQL storage, secret/PII scanner, scheduled refresh, and scale harness with token rate governance, adaptive retry bisection, and chunk embedding cache (ADR-0023).
- `app/retrieval/`: Retrieval-port protocol (`VectorStore`, ADR-0019) with `PgVectorStore` adapter, hybrid retrieval combining BM25 (`tsvector`) and dense vector search (pgvector HNSW), Reciprocal Rank Fusion (RRF), domain query expansion (`DomainQueryExpander`, ADR-0017), in-query metadata filtering (`MetadataFilter`, ADR-0016), provision-level knowledge graph (`mode=graph-hybrid`, ADR-0020), and cross-encoder reranking (built and measured, disabled in serving per ADR-0009).
- `app/generate/`: Prompt assembly with delimiter discipline, prompt injection defense, grounded answer generation with citation validation (`POST /v1/answer`, ADR-0011), and deterministic agentic research loop with workspace persistence (`POST /v1/research`, `POST /v1/workspaces`, ADR-0021).
- `app/api/`: FastAPI service exposing `POST /v1/search`, `POST /v1/answer`, `POST /v1/research`, `POST /v1/workspaces`, `GET /v1/workspaces/{id}/artifacts`, `GET /v1/documents/{document_id}`, `GET /healthz` (liveness), `GET /readyz` (readiness), `POST /v1/admin/cache/invalidate`, `GET /metrics`, and demo UI at `/`.
- `app/evals/`: Versioned evaluation harness over gold set v2.0.0 (425 items, 35 documents, 230 chunks), deterministic scorers, regression gate (`make eval-gate`), cross-judge calibration report (`evals/calibration/20261008T200000Z/calibration_report.md`), and double-labelled research calibration (`evals/calibration/20261009T200000Z/research_report.md`).
- Test suite: **555 tests passing** (`uv run pytest`), strict mypy clean over all source files, ruff lint/format clean.
- Deployment: Containerized production deployment artifact (`Dockerfile`, `docker-compose.yml`, `make deploy`, `make destroy`).
- Decision lineage: 23 ADRs in `docs/decisions/` (ADR-0001 through ADR-0023).

---

## 3. Users and scope

### 3.1 Intended user

The primary user is a **compliance analyst** at a regulated Indian financial institution: a
professional reader who knows the domain, needs the governing text, and is accountable for being
right.

### 3.2 In scope: VERIFIED

1. A read-only question-answering API over an authoritative corpus of RBI and SEBI circulars.
2. An offline ingestion pipeline that fetches, extracts, chunks, embeds, and stores those documents
   with full provenance.
3. Hybrid retrieval (lexical + dense) with RRF fusion, query expansion, and metadata filtering.
4. Grounded answer generation with mandatory citations, prompt injection resistance, and explicit refusal.
5. A versioned evaluation harness that provides continuous regression gating.
6. A self-contained web UI for demonstrating and inspecting answers and citations.
7. Containerized deployment artifacts for local and production-like execution.

### 3.3 Out of scope: SPECIFIED

| ID | Out of scope | Why |
|---|---|---|
| OUT-1 | Legal advice or regulatory completeness | DocScout surfaces and cites documents; it does not provide legal interpretation |
| OUT-2 | Non-public, paywalled, or login-gated sources | Source acquisition forbids authentication bypass |
| OUT-3 | Arbitrary document upload by end users | The corpus is curated and provenance-tracked; arbitrary upload breaks trust model |
| OUT-4 | Multi-tenancy and per-user storage | DocScout is a single-tenant regulatory search service |
| OUT-5 | Write operations on the corpus from public API | Ingestion is an offline administrative workflow |
| OUT-6 | Languages other than English | The target regulatory documents are published in English |
| OUT-7 | Real-time push notifications | Ingestion runs as a scheduled batch process |

---

## 4. Functional requirements

### 4.1 Ingestion

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| FR-1 | Ingester MUST fetch only from source entry points in `docs/corpus/CORPUS_SPEC.md` §2 | VERIFIED | `app/ingest/allowlist.py`, `tests/test_ingest.py` |
| FR-2 | Record URL, source, detail_page, fetch_ts, status, bytes, sha256, pages, extractor, char_count, ok | VERIFIED | `corpus/raw/manifest.json`, `app/ingest/source.py` |
| FR-3 | Reject and flag any document whose extracted text is < 500 clean characters | VERIFIED | `app/ingest/guards.py`, `tests/test_ingest.py` |
| FR-4 | Changed sha256 at known URL creates new version; superseded version retained with resolvable chunk IDs | VERIFIED | `migrations/0001_initial_schema.up.sql`, `tests/test_refresh_lifecycle.py` |
| FR-5 | De-duplication MUST be by content hash first, then canonical URL | VERIFIED | `app/ingest/store.py`, `tests/test_ingest.py` |
| FR-6 | Ingestion MUST run with no deploy or cloud credentials present in its environment | VERIFIED | `app/ingest/guards.py`, `tests/test_ingest.py` |
| FR-7 | Chunking attaches document_id, version, and source character offsets to every chunk | VERIFIED | `app/ingest/chunk.py`, `app/ingest/ids.py`, `tests/test_ids.py` |
| FR-8 | Fixed-width chunking: 1,000 chars with 150-char overlap, whitespace boundaries, 512-token ceiling | VERIFIED | `app/ingest/chunk.py`, ADR-0003 |

### 4.2 Retrieval and generation

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| FR-9 | Combine lexical arm (tsvector) and dense arm (pgvector HNSW) fused with RRF (k=60) | VERIFIED | `app/retrieval/search.py`, ADR-0006, ADR-0007 |
| FR-10 | Cross-encoder reranking built and evaluated | VERIFIED (disabled in serving) | `app/retrieval/rerank.py`, ADR-0009 |
| FR-11 | Every non-refusal answer MUST cite at least one chunk; cited chunk IDs must be in context | VERIFIED | `app/generate/answer.py`, `app/api/app.py`, `tests/test_api_answer.py` |
| FR-12 | Retrieved text passed inside delimiters; system prompt enforces data-not-instructions | VERIFIED | `app/generate/prompt.py`, canary tests |
| FR-13 | When context does not support an answer, system refuses explicitly | VERIFIED | `app/generate/answer.py`, `app/retrieval/search.py` |
| FR-14 | Answers MUST state issuing authority, document title, and date for each citation | VERIFIED | `app/ingest/metadata.py`, Migration 0006, `GET /v1/documents/{id}`, ADR-0018 |
| FR-15 | RRF constant, candidate depth per arm, and rerank depth | VERIFIED | `k=60`, arm depth 50, top-k 5 (ADR-0006, ADR-0007) |
| FR-16 | Embedding model and vector dimensionality | VERIFIED | `BAAI/bge-small-en-v1.5`, 384 dims, L2-normalized (ADR-0002) |
| FR-17 | Generator model identity and calibrated evaluation | VERIFIED | `config/models.json`, ADR-0011 |

### 4.3 API surface

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| FR-18 | `POST /v1/answer` returns answer, citations, refusal flag, timings, and model info | VERIFIED | `app/api/app.py`, `tests/test_api_answer.py` |
| FR-19 | `GET /healthz` pure liveness (0 DB I/O); `GET /readyz` traffic readiness | VERIFIED | `app/api/app.py`, ADR-0014, `tests/test_supersession_cache_invalidation.py` |
| FR-20 | Protected endpoints require API key via `X-API-Key` | VERIFIED | `app/api/app.py`, `tests/test_api.py` |
| FR-21 | Rate limiting enforced per key | VERIFIED | `app/api/app.py`, `tests/test_api.py` |
| FR-22 | Responses provide resolvable quotes and structured metadata | VERIFIED | `app/api/models.py`, `app/api/app.py` |

### 4.4 Evaluation

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| FR-23 | Committed gold set of >= 120 hand-built items, >= 10% unanswerable, >= 1 canary | VERIFIED | 425 items in `evals/gold/v1/`, 14.1% unanswerable, 3 canaries (ADR-0012) |
| FR-24 | Eval runs write timestamped results.json, report.md, gate.json | VERIFIED | `evals/reports/` |
| FR-25 | Quality claims backed by raw report artifacts | VERIFIED | `evals/reports/20261009T111050Z/` |
| FR-26 | Deterministic scorers run on every evaluation | VERIFIED | `app/evals/scorers.py` |
| FR-27 | Judge calibration against human labels with Cohen's kappa | VERIFIED | 80 items double-labelled, kappa 1.000 / 0.844 (ADR-0011) |
| FR-28 | CI regression gate fails on > 1pp regression vs baseline mean | VERIFIED | `make eval-gate`, `app/evals/gate.py` |

### 4.5 User interface

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| FR-30 | UI allows question submission and renders citations with source links and spans | VERIFIED | `app/api/demo.py`, `ui/` |
| FR-31 | UI visibly distinguishes refusals from answers | VERIFIED | `app/api/demo.py` |
| FR-32 | UI does not expose private API keys in client bundles | VERIFIED | Demo UI operates via secure server session / environment |

---

## 5. Non-functional requirements

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| NFR-1 | End-to-end query latency target p95 < 3 s | VERIFIED | Cold p95 48.11 ms, warm p95 2.11 ms (`bench.json`) |
| NFR-2 | Performance numbers carry raw reports and hardware environment | VERIFIED | `evals/bench/20261002T053217Z/bench.json` |
| NFR-3 | Correctness on 2 vCPU / 1.9 GiB RAM floor | VERIFIED | Benchmarked and tested on target CPU floor |
| NFR-4 | Dependency resolution is reproducible via frozen lockfile | VERIFIED | `uv.lock` pinned, `uv sync --frozen` |
| NFR-5 | CPU-only operation without GPU requirement | VERIFIED | BGE-small runs CPU-only; torch CPU wheels |
| NFR-6 | Code passes ruff check, ruff format, mypy strict, and pytest | VERIFIED | 511 tests passing, strict mypy across 51 source files |
| NFR-7 | No secret committed to repository or history | VERIFIED | Gitleaks pre-commit and CI job passing |
| NFR-8 | Ingestion of full corpus is restartable and idempotent | VERIFIED | SHA-256 skip in 0.015 s, tested in `tests/test_ingest.py` |
| NFR-9 | Structured logs include request ID, redact API keys and queries | VERIFIED | `app/observability.py`, `app/api/app.py` |

---

## 6. Data

- **Document**: One logical regulatory circular identified by canonical URL.
- **Version**: A distinct SHA-256 observed at a canonical URL.
- **Chunk**: A retrievable span of text with content-derived UUIDv5 (`uuid5(NAMESPACE_DNS, sha256:char_start:char_end)`).
- **Corpus scale**: 35 documents (18 RBI notifications, 16 SEBI circulars, 1 synthetic canary), 230 chunks, ~190,000 clean characters.
- **Gold set scale**: Version 2.0.0, 425 items (365 answerable, 60 unanswerable, 3 canaries).

---

## 7. External dependencies and versions

| Dependency | Version | Status |
|---|---|---|
| Python | 3.12.14 | VERIFIED |
| PostgreSQL + pgvector | PostgreSQL 18.6, pgvector 0.8.6 | VERIFIED |
| Redis | 7-alpine (optional for distributed rate limiting) | VERIFIED |
| FastAPI / uvicorn | 0.142.2 / 0.54.0 | VERIFIED |
| Embedder | `BAAI/bge-small-en-v1.5`, 384 dims | VERIFIED |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | VERIFIED (disabled in serving) |

---

## 8. Unresolved Register: Closure Summary

| ID | Question | Resolution | Evidence |
|---|---|---|---|
| **U-1** | LLM judge & answer generation | Reopened and resolved with local generator and calibrated judge | ADR-0011, `evals/calibration/20261008T200000Z/calibration_report.md` |
| **U-2** | Postgres MCP server | Declined in favor of native psycopg scripts and CLI tools | `docs/security/mcp-server-audit.md` |
| **U-3** | `.mcp.json` tracking | Pinned with environment substitution, audited | `docs/security/mcp-server-audit.md` |
| **U-4** | Supply chain scanning | Automated via pip-audit and CycloneDX SBOM in CI | `make audit-deps`, `docs/security/sbom.cdx.json` |
| **U-5** | Terms of use review | Public regulator documents, respectful crawling verified | `docs/corpus/CORPUS_SPEC.md` §6 |
| **U-6** | GitHub remote and CI | Remote established (`origin/master`), all 11 CI runs green | GitHub Actions `ci.yml` |
| **U-7** | Deployment target | Local container deploy verified (`Dockerfile`, compose) | ADR-0010, `docs/deploys/20261008T190000Z-p0-4-live.md` |
| **U-8** | Chunking strategy | 1,000 chars with 150-char overlap, whitespace bound | ADR-0003 |
| **U-9** | Embedding model | `bge-small-en-v1.5`, 384 dimensions | ADR-0002 |
| **U-10** | RRF and candidate depth | `k=60`, arm depth 50, top-k 5 | ADR-0006, ADR-0007 |
| **U-11** | Table extraction | Standard flattening validated against 35 corpus documents | `app/ingest/extract.py` |
| **U-12** | Supersession handling | In-document versioning, cache invalidation, metadata filter | ADR-0013, ADR-0014, ADR-0016 |
| **U-13** | API contract | Implemented: search, answer, documents, healthz, readyz | `app/api/app.py`, ADR-0010, ADR-0011, ADR-0018 |
| **U-14** | Latency floor on 2 vCPU | Cold p95 48.11 ms, warm p95 2.11 ms (p95 < 3 s target achieved) | `evals/bench/20261002T053217Z/bench.json` |
| **U-15** | Environment reproduction | Pinned bootstrap script and frozen lockfile | ADR-0001, `scripts/bootstrap.sh` |
| **U-16** | Scanned PDF policy | Corpus currently yields > 500 clean text characters per document | `app/ingest/guards.py` |
| **U-17** | Gold set authoring | v2.0.0 created with 425 items and disagreement review | ADR-0012, `evals/gold/v1/metadata.json` |

---

## 9. Acceptance of this specification

This specification describes the production baseline of DocScout. All functional and non-functional
requirements in §4 and §5 are backed by test suites, benchmarks, and decision records.
