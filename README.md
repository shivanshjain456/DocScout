# DocScout

Citation-grounded question answering over Indian financial-regulatory circulars (RBI + SEBI), with
hybrid retrieval (BM25 + dense vectors), cross-encoder reranking, answer generation, and a versioned evaluation harness.

> **Status: Production operational RAG service.** P0, P1, and P2 capabilities verified, tested (555 tests passing), and containerized.
> Benchmarked against top open-source RAG architectures (Onyx, RAGFlow, Dify, Khoj, FastGPT).

## Results

Retrieval evaluation baseline (`evals/reports/20261009T111050Z/`). Every number below is macro-averaged over the
365 answerable items of gold set `2.0.0` (425 items total, including 60 unanswerable) and comes from the raw file linked
beside it. Nothing here is estimated, rounded up, or carried over from a previous run.

**Serving configuration: `hybrid-rrf`** (BM25 + dense, RRF k=60, arm depth 50, k=5). See
[ADR-0006](docs/decisions/0006-hybrid-retrieval-bm25-dense-rrf.md).

| Metric | Value | Reproduce | Raw output |
|---|---|---|---|
| Recall@1 (quote groups) | 0.695 | `make eval` | [`results.json`](evals/reports/20261009T111050Z/results.json) |
| Recall@5 | 0.966 | `make eval` | [`results.json`](evals/reports/20261009T111050Z/results.json) |
| Recall@10 | 0.992 | `make eval` | [`results.json`](evals/reports/20261009T111050Z/results.json) |
| MRR | 0.854 | `make eval` | [`results.json`](evals/reports/20261009T111050Z/results.json) |
| nDCG@5 | 0.867 | `make eval` | [`results.json`](evals/reports/20261009T111050Z/results.json) |
| Retrieval p95 latency | 42 ms | `make bench` | [`bench.json`](evals/bench/20261002T053217Z/bench.json) |

Hardware for the latency figure: 2 vCPU / 1.94 GiB, PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2).
Retrieval only: the embedding model is loaded once at startup, not per query.

### Retrieval A/B and Expansion

| config | recall@5 | MRR | p95 | verdict |
|---|---|---|---|---|
| `bm25-only` | 0.970 | 0.838 | 1 ms | lexical headline, vulnerable to low-overlap paraphrase |
| `hybrid-rrf` | 0.966 | 0.854 | 42 ms | **serving** (best MRR and nDCG) |
| `dense-only` | 0.947 | 0.762 | 38 ms | semantic recall, fails exact numeric/circular IDs |

Domain query expansion is supported via `DomainQueryExpander` ([ADR-0017](docs/decisions/0017-query-understanding-and-domain-expansion.md)),
providing bidirectional acronym expansion across 36+ regulatory terms and optional HyDE formulation.

### Regression Gate

`make eval-gate` fails the build when the serving configuration's recall, MRR, or nDCG@5 drops
more than 1pp against the mean of accepted baselines, and fails hard on
invariants that make a comparison meaningless: a gold set mutated without a version
bump, a changed corpus, or items that quietly vanished. Drilled against a real 1.90pp
degradation: exit 1.

The gate publishes its own noise floor beside each verdict. On gold set v2.0.0 (365 paired items,
ADR-0012), the minimum detectable effect sits at <= 1.0pp.

### Verification Story

[A retrieval miss the harness caught](docs/verification/0001-g038-fusion-miss.md): BM25 ranked
a chunk **first**, RRF fused it to rank 14, and the item scored zero recall at every cutoff.
Diagnosed to rank-only fusion discarding an arm's certainty, fixed with a bounded guarantee
([ADR-0007](docs/decisions/0007-arm-anchored-fusion.md)) chosen over constant-tuning on measured
evidence, and pinned by a regression test that fails when the fix is removed.

### Live Demo and Serving

```bash
make serve      # http://localhost:8000: demo UI, /docs, /healthz, /readyz
```

Endpoints provided:
- `POST /v1/search`: Returns ranked passages with resolvable citations, confidence score, and optional metadata filtering (`filter: MetadataFilter`).
- `POST /v1/answer`: Generates citation-grounded answers with mandatory citation validation, explicit refusal on unanswerable queries, and injection defense.
- `POST /v1/research`: Executes deterministic agentic multi-aspect regulatory synthesis producing structured comparison tables and findings with mandatory citations.
- `POST /v1/workspaces`: Creates research workspace for storing query findings and analysis artifacts.
- `GET /v1/workspaces/{workspace_id}/artifacts`: Retrieves stored research artifacts and workspace state.
- `GET /v1/documents/{document_id}`: Resolves authoritative document metadata (title, date, authority, version count, lineage).
- `GET /healthz`: Zero-DB liveness probe (safe for pod liveness).
- `GET /readyz`: Traffic readiness probe (verifies database pool, chunk count, staleness budgets).
- `POST /v1/admin/cache/invalidate`: Authenticated admin cache purge and BM25 index reload.
- `GET /metrics`: Prometheus metrics exposition.

All protected endpoints require an API key (`X-API-Key`, constant-time compare, rotation supported)
and are rate-limited per key. Missing key configuration stops startup rather than defaulting to open.

### Cost and Latency

Measured over HTTP with real gold-set questions on 2 vCPU / 1.9 GiB, 200 requests per phase.
Reproduce with `make serve` then `make bench`; raw output
[`bench.json`](evals/bench/20261002T053217Z/bench.json).

| phase | mean | p50 | p95 | p99 |
|---|---|---|---|---|
| cold (cache bypassed) | 39.07 ms | 37.94 ms | **48.11 ms** | 53.19 ms |
| warm (cache hit) | 1.71 ms | 1.64 ms | **2.11 ms** | 2.68 ms |

| measure | value | reproduce |
|---|---|---|
| Cache effect on p95 | **22.8x** (46.0 ms saved) | `make bench` |
| Sustained throughput | 39.8 q/s at concurrency 4 | `make bench` |
| Cost per 1,000 queries | **$0.000078** (= about $0.08 per million) | `make bench` |
| LLM cost | $0.00 for retrieval tier | `make bench` |

Cost assumes one AWS t4g.small (2 vCPU / 2 GiB), ap-south-1, Linux on-demand at $0.0112/hour serving continuously at the
measured throughput. The price is a third-party listing, not an AWS quotation: see the
script for the source and the caveat.

### Effect of Reranking

A cross-encoder rerank stage is **built, tested, and measured, but switched off in serving**
([ADR-0009](docs/decisions/0009-cross-encoder-reranking.md)). Reproduce with
`uv run python -m scripts.experiments.u10_rerank_ablation`; raw output
[`results.json`](evals/experiments/u10-rerank-20261002T062322Z/results.json).

| config | recall@1 | recall@5 | recall@10 | MRR | p95 | CI excludes 0 |
|---|---|---|---|---|---|---|
| **no rerank (serving)** | 0.695 | 0.966 | **1.000** | 0.825 | **39 ms** | (baseline) |
| rerank top 10 | 0.718 | 0.977 | 1.000 | 0.850 | 1185 ms | no |
| rerank top 20 | 0.718 | 0.977 | 0.992 | 0.848 | 2455 ms | no |
| rerank top 50 | 0.718 | 0.977 | 0.992 | 0.848 | 6276 ms | no |

Reranking buys **+2.3pp recall@1 for 30x to 160x the p95**, and the
bootstrap CI spans zero. Beyond the serving depth it degrades recall@10 because the cross-encoder
promotes deep candidates over evidence fusion had already placed correctly. It stays off.

### Calibrated Generation Evaluation

Answer generation (`POST /v1/answer`, ADR-0011) was calibrated against human double-labelling on 80 items across all strata:
- **Judge vs Human Agreement (Faithfulness)**: 100.0%, Cohen's kappa = 1.000.
- **Inter-Rater Human Agreement (Faithfulness)**: 97.5%, Cohen's kappa = 0.844.
- **Citation Precision**: 100.0%, Cohen's kappa = 1.000.
- **Abstention Correctness**: 100.0%, Cohen's kappa = 1.000.
- **Prompt Injection Defense**: 100% canary defense (3/3 canaries defended).
See [`evals/calibration/20261008T200000Z/calibration_report.md`](evals/calibration/20261008T200000Z/calibration_report.md).

## Architecture

See `docs/architecture/system-diagram.md` (Mermaid: ingest -> store -> retrieve -> generate -> eval).

```
Internet (RBI/SEBI)                  [untrusted data]
   |
   +-> fetch -> extract chain (fast/deep fallback) -> clean -> chunk -> embed (LRU cache) -> Postgres 18 + pgvector 0.8.6
                                                                                               |
   question -> API (key + rate limit + audit log) -> VectorStore port (HNSW + tsvector)
                                                  -> RRF fusion -> query expansion & provision graph
                                                  -> grounded generation & agentic research workspace
```

## Quickstart

Two scripts from a bare machine to a queryable corpus:

```bash
cp .env.example .env                 # set DB_PASSWORD, DB_APP_PASSWORD, DOCSCOUT_API_KEY
bash scripts/bootstrap.sh            # uv, Python 3.12, pre-commit, gitleaks, .venv, hooks
bash scripts/dev_db_native.sh        # PostgreSQL 18 + pgvector 0.8.6, roles, extensions
make migrate && make ingest          # 8 migrations; 35 documents, 230 chunks
make serve                           # http://localhost:8000
```

The corpus payloads are committed, so `make ingest` runs offline and reproduces the exact
bytes every published number was measured on.

`scripts/dev_db_native.sh` is the default native path and needs no Docker: it installs
PostgreSQL 18 and pgvector if absent, and executes `infra/initdb/` files.
`docker-compose.yml` is the supported alternative where a daemon is available:

```bash
docker compose up -d     # PostgreSQL 18.6 + pgvector 0.8.6, same initdb scripts
```

Verify the install:

```bash
make verify-setup    # environment matrix
make test            # full suite (555 tests passing)
make eval            # retrieval baseline -> evals/reports/<UTC-ts>/
make eval-gate       # fails build on a >1pp regression
```

### Container Deployment (P0-4)

From a clean checkout with only `.env` edited:

```bash
make deploy          # build api image -> up db -> migrate -> ingest -> up api -> curl /healthz
curl -s localhost:8000/healthz   # status: ok, corpus_chunks: 230
make destroy         # compose down -v + remove local image; proves nothing remains
```

The image is pinned (`python:3.12-slim-trixie`, `uv sync --frozen`, non-root,
`HEALTHCHECK /healthz`, no secrets in layers) and pre-warms BGE-small at build time into
`/opt/hf-cache` so first boot does not download models at runtime.

## Repo Map

| Path | Contents |
|---|---|
| `app/ingest/` | offline pipeline: fetch, extract chain, guard, clean, chunk, embed, store, scanner, refresh, scale harness |
| `app/retrieval/` | retrieval port, hybrid search, RRF fusion, query expansion, metadata filtering, knowledge graph, reranking |
| `app/generate/` | prompt assembly, citation grounding, refusal behavior, agentic research loop & workspace |
| `app/evals/` | gold set, scorers, judges, calibration, gate |
| `app/api/` | FastAPI surface: search, answer, research, workspaces, document resolution, health, metrics, admin |
| `evals/gold/v1/` | versioned QA gold set (v2.0.0, 425 items) |
| `evals/reports/` | timestamped eval runs |
| `infra/` | DB init SQL, migrations (0001–0008), docker configuration |
| `docs/decisions/` | 23 ADRs (Context, Decision, Consequences, Rejected alternatives) |
| `docs/security/` | MCP and skills audits, injection canary log, audit logging |
| `docs/setup/` | SETUP_REPORT.md and environment evidence |
| `ui/` | interactive demo frontend |

## Commands

| Command | Does |
|---|---|
| `make dev` | db up + local uvicorn `app.api.app:app` with reload |
| `make deploy` | local container deploy: build api, migrate, ingest, serve, prove `/healthz` |
| `make destroy` | tear down local compose services, volumes and image |
| `make test` | pytest (full test suite, 555 tests) |
| `make lint` / `make typecheck` | ruff / mypy strict |
| `make eval` | full eval run -> `evals/reports/<ts>/` |
| `make eval-gate` | regression gate against mean-of-3 baselines |
| `make refresh` | offline corpus staleness audit and hash check |
| `make refresh-check` | live conditional HTTP refresh check against regulatory hosts |
| `make secret-scan` | gitleaks over full history |
| `make audit-deps` | pip-audit and CycloneDX SBOM generation |
| `make verify-setup` | environment verification matrix |

## Limitations

Written to be read by someone evaluating DocScout against operational standards:

1. **The API is runnable as a local container; it is not hosted at a public cloud URL.**
   `make deploy` builds the pinned image and serves `/healthz` (`status: ok`, `corpus_chunks: 230`)
   where a Docker daemon exists. No public cloud resources or remote load balancers are provisioned by default.

2. **The serving process is single-worker by default, and its cache and rate limiter live in memory.**
   Neither survives a restart and neither coordinates across processes. `GET /healthz` reports
   `single_process: true`. Liveness and readiness are cleanly separated: `GET /healthz` performs
   zero database I/O, while `GET /readyz` checks connection pooling, chunk availability, and staleness budgets.
   A multi-worker deployment requires Redis (`REDIS_URL` in `.env.example`).

3. **Reranking is implemented but disabled by default in serving.**
   On the current corpus, hybrid retrieval already achieves recall@10 = 0.992. Cross-encoder reranking
   costs 30x to 160x the p95 latency for a small recall@1 gain whose bootstrap confidence interval spans zero.

4. **Abstention catches about a quarter of unanswerable questions at the retrieval layer.**
   Evidence coverage scores AUC 0.730. At threshold 0.65, abstention recall is 0.273 with selective accuracy 0.869.
   At the answer layer (`POST /v1/answer`), explicit refusal logic handles unanswerable questions.

5. **The BM25 arm holds its term index in memory.**
   It executes a startup query over stored chunks. Appropriate for thousands of chunks; multi-million chunk scale
   would migrate to an external or extension-based engine (ParadeDB pg_search, OpenSearch).

6. **The cost figure is compute only.**
   $0.08 per million queries covers one t4g.small serving retrieval; it is not an AWS quotation and does
   not include storage, egress, or external LLM tokens.

7. **Decision lineage spans 23 ADRs.**
   Every architectural choice is documented in `docs/decisions/` with rejected alternatives and measured reasons.

8. **Declarative metadata filtering is executed in-query.**
   `POST /v1/search` accepts an optional `filter` supporting regulatory authority (`source`: `"RBI"`, `"SEBI"`),
   date bounding (`date_from`, `date_to`), version currency (`is_current`), and document identifiers.

9. **Superseded document versions are retained but never retrieved by default.**
   Superseded rows remain in PostgreSQL per audit retention guarantees (FR-4). When a document is superseded,
   in-memory caches are purged immediately, BM25 indices reload, and generation counters advance (ADR-0014).

10. **Citations carry authoritative document titles, publication dates, and canonical URLs (FR-14).**
    Every retrieved `Passage` carries its official regulator circular `title`, `published_date`,
    and `canonical_url` alongside stable content-derived `chunk_id` and character spans (ADR-0018, Migration 0006).
    Dedicated endpoint `GET /v1/documents/{document_id}` resolves document metadata and version lineage.

11. **Retrieval port and vector store decoupling (P2-1).**
    `VectorStore` Protocol (`app/retrieval/port.py`) abstracts the underlying storage backend. `PgVectorStore`
    is the tested production adapter; swapping backends requires implementing the port protocol without
    touching search or fusion logic (ADR-0019).

12. **Lightweight provision graph and agentic research loops (P2-2, P2-3).**
    Multi-hop regulatory cross-referencing utilizes provision nodes and citations (`mode=graph-hybrid`, ADR-0020).
    Complex comparative questions execute via `ResearchAgent` (`POST /v1/research`, ADR-0021) with workspace
    artifact storage and 100% citation grounding.

### Logs and Request Correlation

Every record renders through one structlog pipeline:

```bash
DOCSCOUT_LOG_JSON=1 DOCSCOUT_LOG_LEVEL=INFO make serve
```

Each request binds a correlation ID returned as `X-Request-ID`:

```json
{"key_fingerprint":"afae76d828ca","mode":"hybrid","duration_ms":37.3,"retrieval_ms":37.18,
 "passages":2,"event":"search.completed","request_id":"req-prod-001","path":"/v1/search"}
{"status":200,"duration_ms":40.81,"event":"http.request","request_id":"req-prod-001"}
```

Inbound `X-Request-ID` is validated for length and character safety. API keys are redacted by a pipeline processor;
only truncated fingerprints are logged.

### Knowing When the Corpus Cannot Answer

14.1% of gold set v2.0.0 (60 of 425 items) is deliberately unanswerable:

| signal | AUC |
|---|---|
| `rrf_top`: serving configuration score | **0.467** (worse than chance) |
| `dense_margin` | 0.461 |
| `bm25_top` | 0.655 |
| **evidence coverage**: query terms found in top 5 passages | **0.730** |

At threshold 0.65: abstention recall 0.273, false rejection rate 0.030, refusal precision 0.600, selective accuracy 0.869.
Full sweep and details: [`docs/verification/0002-abstention-signal.md`](docs/verification/0002-abstention-signal.md).

### Supply Chain

```bash
make audit-deps      # -> docs/security/dependency-audit.json, docs/security/sbom.cdx.json
```

`pip-audit` over the exported `uv.lock`, plus CycloneDX SBOM generation. The gate fails only on advisories
affecting dependencies installed at runtime.

### Test Quality: Mutation Score

```bash
make mutation        # -> evals/mutation/latest.json
```

| module | line coverage | mutants | killed | survived | mutation score |
|---|---|---|---|---|---|
| `app/evals/scorers.py` | 99% | 153 | 140 | 13 | **91.5%** |
| `app/evals/stats.py` | 96% | 125 | 78 | 47 | **62.4%** |
| total | - | 278 | 218 | 60 | **78.4%** |

### Metrics

`GET /metrics` serves Prometheus exposition:

| metric | type | labels |
|---|---|---|
| `docscout_http_requests_total` | counter | `method`, `route`, `status` |
| `docscout_http_request_duration_seconds` | histogram | `method`, `route` |
| `docscout_http_requests_in_flight` | gauge | - |
| `docscout_retrieval_duration_seconds` | histogram | `mode` |
| `docscout_cache_events_total` | counter | `result` (hit/miss) |
| `docscout_rate_limited_total` | counter | - |
| `docscout_corpus_chunks` | gauge | - |
| `docscout_corpus_last_checked_timestamp_seconds` | gauge | - |
| `docscout_corpus_stale_hours` | gauge | - |
| `docscout_corpus_staleness_budget_hours` | gauge | - |
| `docscout_corpus_is_stale` | gauge | - |
| `docscout_corpus_versions_current` | gauge | - |
| `docscout_corpus_versions_superseded` | gauge | - |
| `docscout_manifest_changed_total` | counter | - |

### Corpus Freshness and Scheduled Refresh

Regulatory circulars are living legal artifacts. DocScout tracks corpus audit state in singleton table
`corpus_sync_state` and provides offline manifest drift detection and live HTTP change checking:

```bash
make refresh        # offline manifest audit and disk hash validation
make refresh-check  # live check with conditional HTTP probes
```

- Staleness budgeting: Configured via `DOCSCOUT_CORPUS_STALENESS_BUDGET_HOURS` (default 168.0 hours).
- Operational `/readyz` and `/healthz`: Surface `last_checked_at`, `stale_hours`, `staleness_budget_hours`, and `is_stale`.
- Scheduled workflow: `.github/workflows/corpus-refresh.yml` running weekly on Mondays at 03:00 UTC.

### Rebuilding Derived Data

Ingestion skips documents whose source `sha256` is unchanged. A change to cleaning, chunking, or embedding
models requires a deliberate rebuild:

```bash
psql "$MIGRATION_DATABASE_URL" -c "TRUNCATE chunks, document_versions, documents CASCADE;"
make ingest && python -m app.ingest verify && make eval && make eval-gate
```

Tested end-to-end in `tests/test_refresh_lifecycle.py`.

## Security Posture

Corpus documents are treated as untrusted data, never instructions.

### Retrieval Audit Forensics and Corpus Scanning (OWASP LLM09 / LLM02)

- **Durable Append-Only Retrieval Audit Log**: Every query records an immutable event in PostgreSQL table `retrieval_audit_log`
  with timestamp, key fingerprint, SHA-256 query hash, mode, k, returned chunk IDs, latency, cache hit, generated answer flag, and corpus generation.
  - Query Privacy: Plaintext queries are never stored.
  - Credential Isolation: Raw API keys are never stored; only truncated SHA-256 fingerprints are logged.
  - Append-Only: `docscout_app` role has INSERT and SELECT only; UPDATE, DELETE, and TRUNCATE are denied.
  - Fallback Sink: Thread-safe JSONL file logging via `DOCSCOUT_AUDIT_LOG_FILE`.
  - Retention: 90-day retention documented in ADR-0015.
- **Corpus Secret and PII Scanning at Ingestion**: Extracted text is scanned at ingestion (`app.ingest.scanner`)
  for candidate API keys, private keys, SaaS tokens, and PII with automatic sample masking. Secrets trigger quarantine or rejection per policy.

## License

MIT: see `LICENSE`.
