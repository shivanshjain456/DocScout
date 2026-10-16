# DocScout

<p align="center">
  <a href="https://github.com/shivanshjain456/DocScout/actions/workflows/ci.yml"><img src="https://github.com/shivanshjain456/DocScout/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI"></a>
  <a href="evals/reports/20261010T050559Z/results.json"><img src="https://img.shields.io/badge/evals-365%20scored-brightgreen?style=flat-square" alt="Evals"></a>
  <a href="https://github.com/shivanshjain456/DocScout/actions"><img src="https://img.shields.io/badge/tests-544%20passing-brightgreen?style=flat-square" alt="Tests"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.12-blue?style=flat-square" alt="Python"></a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/svg/docscout-primary-dark.svg">
    <img src="docs/brand/svg/docscout-primary.svg" alt="DocScout - citation-grounded regulatory retrieval over RBI/SEBI circulars" width="420">
  </picture>
</p>

<p align="center">
  <strong>Clone to queryable in 90 seconds:</strong> <code>cp .env.example .env && make deploy && curl -s localhost:8000/healthz</code> · <a href="https://github.com/shivanshjain456/DocScout/actions/runs/38902601761">5/5 green at 38902601761</a><br>
  Without clone: <code>docker run -p 8000:8000 ghcr.io/shivanshjain456/docscout:2.0.0</code>
</p>

<p align="center">
  <img src="docs/assets/demo.png" width="800" alt="DocScout demo citation grounded answer with sources">
</p>

> Citation-grounded QA over RBI and SEBI circulars for analysts, auditors, and fintech teams.
>
> *Every answer cites its source or it refuses to answer.*

<p align="center">
  <a href="#quickstart">Quick Start</a> ·
  <a href="#results">Results</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#api">API</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

## Contents

- [Why DocScout](#why-docscout)
- [Quickstart](#quickstart)
- [Demo](#demo)
- [Results](#results)
- [Architecture](#architecture)
- [API](#api)
- [Configuration](#configuration)
- [Commands](#commands)
- [Verification](#verification)
- [FAQ](#faq)
- [Repo Map](#repo-map)

---

## Why DocScout

- **Problem:** RBI/SEBI circulars are dispersed across regulator sites. Keyword search misses paraphrases; dense search fails IDs.
- **Solution:** Hybrid BM25 and BGE-small-en-v1.5 384d retrieval via RRF (k=60), 36-term domain expansion, and citation-grounded generation with refusal.
- **Proof:** 0.966 Recall@5, 0.854 MRR, and 48.11 ms cold / 2.11 ms warm p95 across 365 items; 100% citation precision; kappa 1.000 / 0.844.

---

## Quickstart

```bash
cp .env.example .env && make deploy          # build, migrate, ingest, serve, verify /healthz
curl -s localhost:8000/healthz               # {"status":"ok","corpus_chunks":170}
curl -s -H "X-API-Key: $DOCSCOUT_API_KEY" -H "Content-Type: application/json" \
     -d '{"question":"What is the timeline for filing regulatory capital returns?","k":5}' \
     localhost:8000/v1/search | jq
```

Verify: `make test && make eval-gate` (544 tests passing). Native DB: `bash scripts/dev_db_native.sh`; Docker: `docker compose up -d`. See [SETUP_REPORT.md](docs/setup/SETUP_REPORT.md).

---

## Demo

```bash
make serve                                   # serves API on http://localhost:8000
curl -s -H "X-API-Key: $DOCSCOUT_API_KEY" http://localhost:8000/v1/documents/doc-rbi-001 | jq
```

<p align="center">
  <img src="docs/assets/ui-console.png" width="800" alt="DocScout UI Console search identity and digest operations">
</p>

React console for Search, Citations, Auth0, Brevo, and OCR. Architecture Summary: [EXECUTIVE_SUMMARY.md](docs/overview/EXECUTIVE_SUMMARY.md).

---

## Results

Retrieval baseline on gold set `2.0.0` (365 scored items, 60 unanswerable). Macro-averaged; links to committed artifacts.

Serving config: **hybrid-rrf**: BM25 + dense, RRF k=60, arm depth 50, k=5, arm-anchored top-1 guarantee per [ADR-0007](docs/decisions/0007-arm-anchored-fusion.md).

| Metric | Value | Reproduce | Raw output |
|---|---|---|---|
| Recall@1 (quote groups) | 0.695 | `make eval` | [`results.json`](evals/reports/20261010T050559Z/results.json) |
| Recall@5 | 0.966 | `make eval` | [`results.json`](evals/reports/20261010T050559Z/results.json) |
| Recall@10 | 0.992 | `make eval` | [`results.json`](evals/reports/20261010T050559Z/results.json) |
| MRR | 0.854 | `make eval` | [`results.json`](evals/reports/20261010T050559Z/results.json) |
| nDCG@5 | 0.867 | `make eval` | [`results.json`](evals/reports/20261010T050559Z/results.json) |
| Retrieval p95 latency | 48.11 ms cold / 2.11 ms warm | `make bench` | [`bench.json`](evals/bench/20261002T054058Z/bench.json) |

*Hardware: 2 vCPU, 1.94 GiB, PostgreSQL 18.6. Model loaded at startup. 170 chunks in bench server, 230 in eval corpus ([ADR-0025](docs/decisions/0025-evaluation-and-production-corpus-reconciliation.md)).*

<details><summary><b>Retrieval A/B and Expansion</b></summary>

| config | recall@5 | MRR | p95 | verdict |
|---|---|---|---|---|
| `bm25-only` | 0.970 | 0.838 | 1 ms | lexical headline, fails paraphrase |
| `hybrid-rrf` | 0.966 | 0.854 | 48.11 ms cold / 2.11 ms warm | **serving** (best MRR/nDCG) |
| `dense-only` | 0.947 | 0.762 | 38 ms | semantic recall, fails circular IDs |

Domain expansion via `DomainQueryExpander` ([ADR-0017](docs/decisions/0017-query-understanding-and-domain-expansion.md)): 36+ acronyms and HyDE.

</details>

<details><summary><b>Effect of Reranking</b></summary>

Cross-encoder adds +2.3pp recall@1 for 30x-160x p95 latency; CI spans zero; degrades recall@10 deep. Disabled in serving ([ADR-0009](docs/decisions/0009-cross-encoder-reranking.md), [`results.json`](evals/experiments/u10-rerank-20261002T062322Z/results.json)):

| config | R@1 | R@5 | R@10 | MRR | p95 | CI>0 |
|---|---|---|---|---|---|---|
| no rerank (serving) | 0.695 | 0.966 | 1.000 | 0.825 | 39 ms | (base) |
| rerank top 10 | 0.718 | 0.977 | 1.000 | 0.850 | 1185 ms | no |
| rerank top 20 | 0.718 | 0.977 | 0.992 | 0.848 | 2455 ms | no |
| rerank top 50 | 0.718 | 0.977 | 0.992 | 0.848 | 6276 ms | no |

</details>

<details><summary><b>Calibrated Generation</b></summary>

Answer generation (`POST /v1/answer`, [ADR-0011](docs/decisions/0011-answer-generation-and-calibrated-judge.md)) calibrated on 80 double-labelled items:
- Faithfulness agreement: 100.0% (kappa = 1.000).
- Inter-rater agreement: 97.5% (kappa = 0.844).
- Citation precision: 100.0%.
- Abstention correctness: 100.0%.
- Prompt canary defense: 100% (3/3 defended).

Report: [`calibration_report.md`](evals/calibration/20261008T200000Z/calibration_report.md).

</details>

<details><summary><b>Cost and Latency</b></summary>

Measured over HTTP on 2 vCPU / 1.94 GiB ([`bench.json`](evals/bench/20261002T054058Z/bench.json)):

| phase | mean | p50 | p95 | p99 |
|---|---|---|---|---|
| cold | 39.07 ms | 37.94 ms | **48.11 ms** | 53.19 ms |
| warm | 1.71 ms | 1.64 ms | **2.11 ms** | 2.68 ms |

22.8x speedup (46.0 ms saved); 39.82 q/s throughput; $0.000078 / 1k queries (~$0.08 / million) on AWS t4g.small ($0.0112/hr compute).

</details>

---

## Architecture

End-to-end system architecture from offline regulatory acquisition to citation-grounded answering, agentic research, and regression gating:

<p align="center">
  <a href="docs/assets/architecture-diagram.svg">🔍 Vector SVG Asset</a> ·
  <a href="docs/assets/architecture-diagram-dark.png">🌙 Dark Theme (PNG)</a> ·
  <a href="docs/assets/architecture-diagram-light.png">☀️ Light Theme (PNG)</a> ·
  <a href="docs/architecture/system-diagram.mermaid">📄 Raw .mermaid Source</a> ·
  <a href="docs/architecture/system-diagram.md">📘 System Architecture Spec</a>
</p>

```mermaid
flowchart TB
    %% =========================================================================
    %% DOCSCOUT SYSTEM ARCHITECTURE (VERTICAL STACK OF HORIZONTAL SWIMLANES)
    %% Top: Ingestion  |  Mid-Top: Serving & Retrieval  |  Mid-Bottom: Storage  |  Bottom: Evals
    %% =========================================================================

    %% -------------------------------------------------------------------------
    %% LANE 1: OFFLINE INGESTION PIPELINE (Top Swimlane)
    %% -------------------------------------------------------------------------
    subgraph LANE1["1. Offline Regulatory Ingestion Pipeline (app/ingest · No Deploy Credentials)"]
        direction LR
        SRC["Regulatory Sources<br/>RBI &amp; SEBI Portals<br/><i>(Read-Only HTTPS)</i>"]
        FETCH["1. Allowlist Fetch<br/><code>httpx</code> · 3 Verified Domains<br/><i>Host Allowlist (FR-1)</i>"]
        EXTRACT["2. Pluggable Extract<br/><code>pypdf</code> / <code>pdfplumber</code><br/><i>Layout &amp; Table Parser (ADR-0022)</i>"]
        GUARD["3. Guard &amp; Clean<br/>&gt; 500 Clean Chars<br/><i>Mojibake Strip (FR-3)</i>"]
        CHUNK["4. Chunker (ADR-0003)<br/>1,000 Chars · 150 Overlap<br/><b>UUIDv5 IDs</b> (FR-8)"]
        EMBED["5. Vector Embedder<br/><code>bge-small-en-v1.5</code><br/><i>384d Unit (ADR-0002)</i>"]
        GRAPH_EXT["6. Graph Extractor<br/>Provisions &amp; Citations<br/><i>Clause Links (ADR-0020)</i>"]
        SCAN["7. PII &amp; Secret Scan<br/>Credentials &amp; PII<br/><i>Masking (ADR-0015)</i>"]

        SRC --> FETCH --> EXTRACT --> GUARD --> CHUNK --> EMBED --> GRAPH_EXT --> SCAN
    end

    %% -------------------------------------------------------------------------
    %% LANE 2: ONLINE SERVING & HYBRID RETRIEVAL (Second Swimlane)
    %% -------------------------------------------------------------------------
    subgraph LANE2["2. Online Serving & Hybrid Retrieval Engine (app/api &amp; app/retrieval · FastAPI)"]
        direction LR
        CLIENTS["Compliance Analyst <i>(React Console)</i><br/>&amp; API Clients <i>(HTTPS / REST)</i>"]
        GATEWAY["API Gateway (FastAPI)<br/><code>X-API-Key</code> · Rate Limiter<br/><i>Audit Logger · Probes (FR-20, FR-21)</i>"]
        EXP["Domain Expander<br/>36+ Regulatory Terms<br/><i>HyDE (ADR-0017)</i>"]
        FILT["Metadata Filter<br/>Authority · Dates · Currency<br/><i>SQL &amp; BM25 (ADR-0016)</i>"]
        DUAL["Dual-Arm Retrieval<br/>BM25 (Exact Circular IDs)<br/>+ Dense HNSW KNN (ADR-0006)"]
        FUSION["Arm-Anchored RRF<br/>k=60 · Depth 50<br/><b>Top-1 Guarantee</b> (ADR-0007)"]
        GRAPH["Graph Traversal<br/>1-Hop Provision Links<br/><i>Fallback to RRF (ADR-0020)</i>"]
        CACHE[("In-Process TTL Cache<br/>Invalidation on Supersession<br/><i>(ADR-0014)</i>")]

        CLIENTS --> GATEWAY --> EXP --> FILT --> DUAL --> FUSION --> GRAPH --> CACHE
    end

    %% -------------------------------------------------------------------------
    %% LANE 3: GROUNDED GENERATION & RESEARCH AGENT (Third Swimlane)
    %% -------------------------------------------------------------------------
    subgraph LANE3["3. Grounded Generation & Agentic Synthesis Tier (app/generate)"]
        direction LR
        DELIMIT["Context Delimiter &amp; Canary Defense<br/>Strict <code>&lt;document&gt;</code> Tags (Data-Not-Instructions)<br/><i>Prompt Canary Token Defense (FR-12, S-7)</i>"]
        GEN_ANS["Grounded Generator (ADR-0011)<br/>Deterministic Citation Validator (FR-11)<br/><i>Calibrated Explicit Refusal (FR-13)</i>"]
        GEN_AGENT["4-Stage Research Agent (ADR-0021)<br/>1. Plan (Aspects) → 2. Retrieve (Hybrid)<br/>3. Synthesize (Tables) → 4. Critique"]

        OUT_SEARCH["POST /v1/search<br/><i>Ranked Evidence Passages</i>"]
        OUT_ANS["POST /v1/answer<br/><i>Grounded Answer &amp; Citations</i>"]
        OUT_RES["POST /v1/research<br/><i>Comparative Condition Tables</i>"]

        DELIMIT --> GEN_ANS --> OUT_ANS
        GEN_AGENT --> OUT_RES
    end

    %% -------------------------------------------------------------------------
    %% LANE 4: PERSISTENCE ENGINE (Fourth Swimlane)
    %% -------------------------------------------------------------------------
    subgraph LANE4["4. Core Persistence Engine (PostgreSQL 18.6 + pgvector 0.8.6)"]
        direction LR
        DB_DOCS[("<code>documents</code> &amp; <code>versions</code><br/>Canonical URL · SHA-256 · is_current")]
        DB_CHUNKS[("<code>chunks</code> (UUIDv5 PK)<br/>GIN (tsv) · HNSW Cosine (384d vector)")]
        DB_GRAPH[("<code>graph_nodes</code> &amp; <code>edges</code><br/>Provisions · cites/amends/supersedes")]
        DB_WORK[("<code>workspaces</code> &amp; <code>artifacts</code><br/>Condition Tables · Execution Traces")]
        DB_AUDIT[("<code>retrieval_audit_log</code> &amp; <code>sync_state</code><br/>Append-Only Log · Staleness Singleton")]
    end

    %% -------------------------------------------------------------------------
    %% LANE 5: EVALUATION & OPTIONAL INTEGRATIONS (Bottom Swimlane)
    %% -------------------------------------------------------------------------
    subgraph LANE5["5. Offline Quality Verification & Optional Integrations (app/evals)"]
        direction LR

        subgraph EVAL_SUB["Offline Evaluation &amp; CI Gate"]
            direction LR
            GOLD["Gold Set v2.0.0 (ADR-0012)<br/>425 Curated Items (14.1% Refusal)"]
            SCORERS["Deterministic Scorers (FR-26)<br/>Recall@1/5/10 · MRR · nDCG@5 · Citation P/R"]
            JUDGE["Calibrated LLM Judge (ADR-0011)<br/>Kappa 1.000 / 0.844 (80 Items)"]
            GATE["CI Regression Gate (FR-28)<br/><code>make eval-gate</code> (&lt; 1pp Delta)"]

            GOLD --> SCORERS & JUDGE --> GATE
        end

        subgraph OPT_SUB["Optional External Integrations (Config-Gated)"]
            direction LR
            OPT_AUTH0["Auth0 IdP (ADR-0024)<br/>OpenID Connect / OAuth 2.0 (RS256)"]
            OPT_OCR["OCR.space Cloud (ADR-0024)<br/>PDF Fallback (&le;3 Pages · Cached)"]
            OPT_BREVO["Brevo Email (ADR-0024)<br/>Regulatory Topic Digests (RFC-8058)"]
        end
    end

    %% -------------------------------------------------------------------------
    %% CROSS-LANE FLOWS & DATA PIPELINES
    %% -------------------------------------------------------------------------
    %% Ingestion writes to Database
    SCAN -.->|Insert Chunks, Vectors, Graph &amp; Audit| LANE4

    %% Retrieval reads from Database
    DUAL -.->|HNSW Cosine Search &amp; GIN FTS| DB_CHUNKS
    GRAPH -.->|1-Hop Provision Traversal| DB_GRAPH
    GATEWAY -.->|Append Audit Record| DB_AUDIT

    %% Serving to Generation
    CACHE -->|Ranked Passages| OUT_SEARCH
    CACHE -->|Evidence Context Chunks| DELIMIT
    GATEWAY -.->|Research Inquiries| GEN_AGENT
    GEN_AGENT -.->|Persist Workspaces &amp; Tables| DB_WORK
    GEN_AGENT -.->|Multi-Aspect Sub-queries| EXP

    %% Evaluation reads from DB & Generator
    DB_CHUNKS -.->|Corpus Chunks| SCORERS
    GEN_ANS -.->|Evaluated Answers| JUDGE

    %% Optional Integrations
    GATEWAY -.->|Optional: JWT Bearer Auth| OPT_AUTH0
    EXTRACT -.->|Optional: Scanned PDF Fallback| OPT_OCR
    OPT_BREVO -.->|Optional: Topic Digests| DB_DOCS

    %% =========================================================================
    %% STYLING CLASSES (Restrained, professional engineering palette)
    %% =========================================================================
    classDef sourceNode fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px,color:#14532d;
    classDef clientNode fill:#eff6ff,stroke:#2563eb,stroke-width:1.5px,color:#1e3a8a;
    classDef ingestNode fill:#f8fafc,stroke:#475569,stroke-width:1.5px,color:#0f172a;
    classDef gwNode fill:#f1f5f9,stroke:#334155,stroke-width:1.5px,color:#0f172a;
    classDef retNode fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px,color:#713f12;
    classDef genNode fill:#faf5ff,stroke:#9333ea,stroke-width:1.5px,color:#581c87;
    classDef storeNode fill:#f0f9ff,stroke:#0284c7,stroke-width:2px,color:#0c4a6e;
    classDef evalNode fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#7c2d12;
    classDef outNode fill:#ecfdf5,stroke:#059669,stroke-width:1.5px,color:#064e3b;
    classDef optNode fill:#ffffff,stroke:#94a3b8,stroke-width:1.5px,stroke-dasharray: 4 4,color:#475569;

    class SRC sourceNode;
    class CLIENTS clientNode;
    class FETCH,EXTRACT,GUARD,CHUNK,EMBED,GRAPH_EXT,SCAN ingestNode;
    class GATEWAY gwNode;
    class EXP,FILT,DUAL,FUSION,GRAPH,CACHE retNode;
    class DELIMIT,GEN_ANS,GEN_AGENT genNode;
    class DB_DOCS,DB_CHUNKS,DB_GRAPH,DB_WORK,DB_AUDIT storeNode;
    class GOLD,SCORERS,JUDGE,GATE evalNode;
    class OUT_SEARCH,OUT_ANS,OUT_RES outNode;
    class OPT_AUTH0,OPT_OCR,OPT_BREVO optNode;
```

*System pipeline from regulatory ingestion to citation-grounded answering. See [system-diagram.md](docs/architecture/system-diagram.md) and [ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md).*

### Architectural Invariants & Trust Boundaries

| Boundary | Invariant / Security Control | Verified Evidence |
|---|---|---|
| **Internet &rarr; Ingestion** | Untrusted data; host allowlist of exactly 3 domains (`rbi.org.in`, `rbidocs.rbi.org.in`, `sebi.gov.in`); HTTPS only; zero deploy credentials. | `app/ingest/allowlist.py`, `SECURITY.md` S-4 |
| **Ingestion &rarr; Storage** | Strict extraction guard (&gt;500 clean chars), deterministic UUIDv5 chunk hashing, BGE-small embeddings (384d), and PII scanning with sample masking. | `app/ingest/guards.py`, `app/ingest/scanner.py`, ADR-0015 |
| **Storage &rarr; Retrieval** | Single-store PostgreSQL 18.6 + pgvector 0.8.6. Dual-arm candidate generation (in-memory BM25 + dense HNSW KNN) fused via arm-anchored RRF ($k=60$). | `app/retrieval/search.py`, ADR-0006, ADR-0007 |
| **Retrieval &rarr; Generator** | Context chunks enclosed in `<document>` delimiters (data, never instructions); deterministic citation validation; calibrated explicit refusal. | `app/generate/prompt.py`, `app/generate/generator.py`, ADR-0011 |
| **Public &rarr; API Gateway** | API key authentication (`X-API-Key`) with rotation support; sliding-window rate limiter; append-only audit log with SHA-256 query hashing. | `app/api/security.py`, `app/api/audit.py`, ADR-0015 |
| **Evaluation Harness** | Committed Gold Set v2.0.0 (425 items); deterministic scorers; calibrated judge ($\kappa = 1.000 / 0.844$); CI regression gate (`make eval-gate`). | `app/evals/gate.py`, `evals/reports/`, ADR-0012 |
| **Optional Integrations** | Auth0 JWT (RS256), Brevo email digests, and OCR.space fallback are config-gated and fail safely without breaking the core engine. | `app/api/auth0.py`, `app/digests/`, ADR-0024 |


---

## API

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `POST /v1/search` | POST | `X-API-Key` | Ranked passages with citations |
| `POST /v1/answer` | POST | `X-API-Key` | Grounded answer with refusal |
| `POST /v1/research` | POST | `X-API-Key` | Multi-step research agent |
| `GET /v1/documents/{id}` | GET | `X-API-Key` | Document metadata and lineage |
| `GET /healthz` | GET | None | Zero-DB liveness probe |
| `GET /readyz` | GET | None | Readiness probe (pool, staleness) |
| `POST /v1/admin/cache/invalidate` | POST | `X-API-Key` | Cache purge and index reload |
| `GET /metrics` | GET | None | Prometheus metrics exposition |

Protected endpoints require `X-API-Key`.

---

## Configuration

Core runtime settings configured via `.env` (derived from [`.env.example`](.env.example)):

| Variable | Default | Description |
|---|---|---|
| `DB_PASSWORD` | *(required)* | Postgres admin password |
| `DB_APP_PASSWORD` | *(required)* | Application DML password |
| `DOCSCOUT_API_KEY` | *(required)* | API keys with rotation support |
| `REDIS_URL` | `redis://localhost:6379/0` | Multi-worker cache and rate limiter |
| `DOCSCOUT_CORPUS_STALENESS_BUDGET_HOURS` | `168.0` | Staleness budget for `/readyz` |
| `DOCSCOUT_LOG_JSON` | `0` | Set 1 for JSON logs |

---

## Commands

| Command | Does |
|---|---|
| `make dev` | Run DB and API with reload |
| `make deploy` | Full deploy: migrate, ingest, serve |
| `make destroy` | Tear down local containers and image |
| `make test` | Run test suite (544 passing) |
| `make lint` | Run ruff checks |
| `make typecheck` | Run strict mypy |
| `make eval` | Run retrieval eval (365 items) |
| `make eval-gate` | Run regression gate (< 1pp delta) |

---

## Verification

- `make test`: Full test suite (544 test functions, 1819 collected cases across 130 test modules).
- `make eval`: Offline retrieval eval over gold set v2.0.0 (365 scored items).
- `make eval-gate`: Regression gate fails if Recall, MRR, or nDCG@5 drops > 1pp (noise floor <= 1.0pp).

<details><summary><b>Limitations</b></summary>

1. **Local container deployment:** Shipped via `make deploy` or Docker; no public cloud URL.
2. **Single-worker default:** In-process cache and rate limiter; multi-worker uses `REDIS_URL`.
3. **Reranker disabled:** Hybrid reaches 0.992 Recall@10; reranker adds 30x-160x p95 for minimal gain.
4. **Abstention selectivity:** Coverage AUC 0.730; 0.65 threshold gives 0.273 recall. Refusal handles rest.
5. **In-memory BM25 index:** Startup index loads in memory; scales to thousands of chunks.
6. **Compute-only cost:** $0.08 / million queries covers t4g.small compute only.

Boundaries:
- 91 ADRs in [`docs/decisions/`](docs/decisions/) (ADR-0001 through ADR-0091).
- Metadata filtering: `source`, `date_from`, `date_to`, `is_current`.
- Superseded versions retained, excluded from search ([ADR-0014](docs/decisions/0014-cache-invalidation-on-supersession-and-readiness-split.md)).
- Authoritative citations ([ADR-0018](docs/decisions/0018-human-readable-citation-rendering.md)), VectorStore port ([ADR-0019](docs/decisions/0019-retrieval-port-adapter.md)).
- Provision graph and research agent ([ADR-0020](docs/decisions/0020-knowledge-graph-regulatory-provisions.md), [ADR-0021](docs/decisions/0021-tight-agentic-research-loop.md)).

</details>

<details><summary><b>Supply Chain and Security</b></summary>

- `make audit-deps`: [`dependency-audit.json`](docs/security/dependency-audit.json) and CycloneDX SBOM [`sbom.cdx.json`](docs/security/sbom.cdx.json).
- Pinned base `python:3.12-slim-trixie`, `uv sync --frozen`, non-root user, zero credentials.
- Append-only audit log in PostgreSQL ([ADR-0015](docs/decisions/0015-retrieval-audit-log-and-corpus-pii-scan.md)); queries and keys unlogged.
- Ingestion PII scanner (`app.ingest.scanner`) with quarantine and masking.

</details>

<details><summary><b>Metrics and Observability</b></summary>

Prometheus exposition via `GET /metrics` (`/healthz` liveness; `/readyz` readiness):

| metric | type | labels |
|---|---|---|
| `docscout_http_requests_total` | counter | method, route, status |
| `docscout_http_request_duration_seconds` | histogram | method, route |
| `docscout_http_requests_in_flight` | gauge | - |
| `docscout_retrieval_duration_seconds` | histogram | mode |
| `docscout_cache_events_total` | counter | result |
| `docscout_rate_limited_total` | counter | - |
| `docscout_corpus_chunks` | gauge | - |
| `docscout_corpus_last_checked_timestamp_seconds` | gauge | - |
| `docscout_corpus_stale_hours` | gauge | - |
| `docscout_corpus_staleness_budget_hours` | gauge | - |
| `docscout_corpus_is_stale` | gauge | - |
| `docscout_corpus_versions_current` | gauge | - |
| `docscout_corpus_versions_superseded` | gauge | - |
| `docscout_manifest_changed_total` | counter | - |

</details>

---

## FAQ

<details><summary><b>Why is reranking switched off if it gains +2.3pp Recall@1?</b></summary>

Cross-encoder adds 30x-160x p95 latency (39 ms to 1,185-6,276 ms) for +2.3pp Recall@1 with CI spanning zero, while degrading Recall@10 deep ([ADR-0009](docs/decisions/0009-cross-encoder-reranking.md), [`results.json`](evals/experiments/u10-rerank-20261002T062322Z/results.json)).

</details>

<details><summary><b>Why is the default serving process single-worker?</b></summary>

In-memory cache and rate limiter eliminate network overhead (< 2.11 ms warm p95). Multi-worker setups enable `REDIS_URL` for shared state.

</details>

<details><summary><b>Why does retrieval abstention score 0.273 recall at threshold 0.65?</b></summary>

Coverage yields AUC 0.730. At 0.65, it intercepts 27.3% of unanswerable queries at retrieval (86.9% selective accuracy); generator refuses the rest ([ADR-0011](docs/decisions/0011-answer-generation-and-calibrated-judge.md), [0002-abstention-signal.md](docs/verification/0002-abstention-signal.md)).

</details>

<details><summary><b>How do you rebuild derived data after modifying chunking or embedding models?</b></summary>

Ingestion skips unchanged SHA-256 hashes. Force rebuild:
```bash
psql "$MIGRATION_DATABASE_URL" -c "TRUNCATE chunks, document_versions, documents CASCADE;"
make ingest && python -m app.ingest verify && make eval && make eval-gate
```
Verified in `tests/test_refresh_lifecycle.py`.

</details>

---

## Repo Map

| Path | Contents |
|---|---|
| `app/ingest/` | Fetch, extract, clean, chunk, embed, store |
| `app/retrieval/` | Hybrid search, RRF fusion, expansion, graph |
| `app/generate/` | Grounded generation, refusal, research agent |
| `app/evals/` | Gold set schemas, scorers, calibration, gate |
| `app/api/` | FastAPI routes: search, answer, research, docs |
| `evals/` | Gold set v2.0.0 (425 items), reports, benchmarks |
| `infra/` | Postgres init SQL, migrations (0001-0053), compose |
| `docs/` | 91 ADRs, architecture, 10-pillar specifications, security |

---

## Contributing

Contributions welcome via pull requests. Please read our [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md) before submitting changes.

- **Contributing Guide:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Code of Conduct:** [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **Accessibility:** [ACCESSIBILITY.md](ACCESSIBILITY.md)
- **Support & Help:** [SUPPORT.md](SUPPORT.md)
- **Security Policy:** [SECURITY.md](SECURITY.md)

Verify changes locally with `make lint`, `make typecheck`, and `make test`.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Acknowledgments

PostgreSQL 18.6, pgvector 0.8.6, BAAI/bge-small-en-v1.5, FastAPI, rank-bm25, and structlog.

---

<footer>Assessment date: 2026-10-16 UTC · Verified against CI 38902601761 and bench evals/bench/20261002T054058Z/bench.json</footer>

<!-- MARKDOWN LINKS AND IMAGES -->
[ci-badge]: https://github.com/shivanshjain456/DocScout/actions/workflows/ci.yml/badge.svg?branch=master
[ci-url]: https://github.com/shivanshjain456/DocScout/actions/workflows/ci.yml
