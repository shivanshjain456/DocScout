# ADR-0014: Cache Invalidation on Supersession and Liveness/Readiness Probe Split

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0004 (persistence schema), ADR-0005 (chunk IDs and geometry), ADR-0006 (hybrid retrieval), ADR-0008 (serving API), ADR-0013 (corpus refresh and freshness signal)
- **Evidence:** `app/api/cache.py`, `app/api/app.py`, `app/api/models.py`, `app/api/metrics.py`, `app/ingest/store.py`, `tests/test_supersession_cache_invalidation.py`, `tests/test_api.py`, `tests/test_refresh_lifecycle.py`

---

## 1. Context

DocScout is built specifically for citation-grounded retrieval over RBI and SEBI regulatory circulars. In this regulatory domain, superseded circulars must never be quoted as authoritative law once amended or withdrawn.

Prior to this decision, two critical operational vulnerabilities existed:

1. **Stale Cache Serving Superseded Passages:**
   - In `app/api/app.py`, `state.result_cache` was an in-memory `TTLCache(512)` with a 300-second (5-minute) TTL.
   - When a circular was superseded (`Action.SUPERSEDED` via `store_document`), PostgreSQL demoted the old version (`is_current = false`) and marked the new version `is_current = true`.
   - However, `state.result_cache` had zero invalidation mechanism. Any query executed within the 300-second window returned cached passages from the superseded circular, serving outdated regulatory passages with stale citations.
   - Furthermore, `BM25Index` was initialized at startup (`WHERE v.is_current = true`) and kept its term postings in memory. Upon supersession, the in-memory index retained terms and chunk IDs from the superseded version, polluting lexical retrieval and Reciprocal Rank Fusion (RRF).

2. **Conflated Liveness and Readiness in `/healthz`:**
   - `GET /healthz` simultaneously probed process health, database connection pool, chunk count, and staleness budget.
   - There was no distinct `GET /readyz` endpoint.
   - In standard container orchestrators (Kubernetes, ECS, Nomad), conflating liveness and readiness creates cascading failure modes: a temporary downstream database blip or network hiccup causes the liveness probe to fail, prompting the orchestrator to abruptly restart pods rather than simply removing them from the routing pool.

---

## 2. Decision

### 2.1 Event-Driven & Generation-Tagged Cache Invalidation
1. **Invalidation Listener Registry (`app/api/cache.py`):**
   - Implemented thread-safe `register_invalidation_listener()`, `unregister_invalidation_listener()`, and `trigger_corpus_invalidation()`.
   - In `app/ingest/store.py`: `store_document()` invokes `trigger_corpus_invalidation()` when `outcome.action in {Action.SUPERSEDED, Action.INSERTED}`.
2. **App Lifespan Registration (`app/api/app.py`):**
   - The FastAPI lifespan handler registers an invalidation callback `_on_corpus_invalidated()`.
   - When triggered, it:
     - Clears all entries in `app.state.result_cache`.
     - Increments `app.state.corpus_generation += 1`.
     - Sets `app.state.bm25_needs_reload = True`.
     - Updates Prometheus gauges `docscout_corpus_generation` and counter `docscout_cache_invalidations_total[reason]`.
     - Emits structured audit log `cache.invalidated`.
3. **Thread-Safe BM25 Index Reload:**
   - When `bm25_needs_reload` is `True`, `search()` and `readyz()` reload `BM25Index(conn)` from PostgreSQL inside a dedicated connection lease protected by `state.bm25_lock`.
   - Old in-memory instances remain valid for any queries currently executing in worker threads until garbage collected.
4. **In-Flight Cache-Poisoning Prevention:**
   - In `search()`, the request generation `req_generation = state.corpus_generation` is recorded at request entry.
   - Upon completion, the result is only stored into `result_cache` if `state.corpus_generation == req_generation`. If an invalidation occurred while the request was in flight, caching is safely skipped with a structured log `search.cache_skip_stale_generation`.
5. **Response Provenance Generation Tagging:**
   - `Provenance` model now includes `corpus_generation: int`, certifying which corpus generation produced each retrieval response.

### 2.2 Dedicated Administrative Cache Invalidation Route
- Implemented `POST /v1/admin/cache/invalidate` requiring valid API key authentication (`require_api_key`).
- Clears the result cache, increments corpus generation, immediately reloads the BM25 index against active chunks, and returns `CacheInvalidateResponse(status="ok", previous_generation, new_generation, entries_cleared, corpus_chunks)`.
- Enables external ingestion CLI scripts (`python -m app.ingest refresh`) or CI/CD pipelines to invalidate running services without process restarts.

### 2.3 Liveness (`GET /healthz`) vs Readiness (`GET /readyz`) Split
1. **Liveness Probe (`GET /healthz`):**
   - Pure process liveness check.
   - **Performs zero database, disk, or network I/O.**
   - Returns HTTP 200 `LivenessResponse` containing `status: "ok"`, `uptime_seconds`, `model_loaded`, `single_process: true`, `corpus_generation`.
   - Guaranteed never to fail due to downstream database connectivity, preventing restart storms.
2. **Readiness Probe (`GET /readyz`):**
   - Traffic routing check for load balancers and orchestrator ingress.
   - Leases a connection from `state.pool`, verifies chunk availability (`chunks > 0`), checks model weights and BM25 index readiness, and audits staleness budget against `corpus_sync_state`.
   - Returns HTTP 200 with `status: "ok"` when fully ready.
   - Returns HTTP 200 with `status: "degraded"` when corpus exceeds staleness budget (alertable, but still serving).
   - Returns HTTP 503 `Service Unavailable` with `status: "unready"` if the database is unreachable or chunks are missing.

---

## 3. Evidence & Consequences

1. **Integration Test Suite (`tests/test_supersession_cache_invalidation.py`):**
   - `test_cache_invalidation_on_supersession_lifecycle`: Proves cold cache miss -> warm cache hit -> supersession -> immediate cache miss -> new generation tag -> zero passages served from superseded version -> BM25 term reload for amended keywords.
   - `test_liveness_healthz_vs_readiness_readyz_split`: Simulates database pool outage; asserts `/healthz` remains HTTP 200 OK while `/readyz` returns HTTP 503 Service Unavailable.
   - `test_admin_cache_invalidate_endpoint`: Asserts 401 unauthenticated rejection and 200 OK authenticated invalidation with counter increment and cache clearance.
   - `test_inflight_request_skips_caching_if_generation_moves`: Asserts in-flight requests during invalidation do not re-populate the cache with pre-invalidation results.
2. **Regression & Quality Gates:**
   - All 447 tests passing (`uv run pytest -q`).
   - Clean linting and formatting (`uv run ruff check .`, `uv run ruff format --check .`).
   - Strict static type checking (`uv run mypy app tests` -> 0 issues across 75 source files).
   - Evaluation gate passes (`uv run python -m app.evals.gate` -> PASS, mrr@5 +1.96pp, ndcg@5 +1.48pp).
