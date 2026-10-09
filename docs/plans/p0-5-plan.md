# Plan: P0-5 — Cache Invalidation on Supersession + Liveness/Readiness Split

**Status:** VERIFIED
**Owner:** Principal Engineer
**Target:** Eliminate the post-supersession wrong-citation window where `TTLCache(300s)` serves passages from replaced chunks, and split readiness from liveness so orchestrators and load balancers can distinguish a starting service from a broken one.

---

## 1. Problem Statement & Baseline Deficiencies

1. **Stale Cache Serving Replaced Passages:**
   - In `app/api/app.py`, `state.result_cache` is a `TTLCache` with a 300-second TTL keyed on `(query, mode, k, generate_answer)`.
   - When a document is amended or superseded at a known canonical URL (`Action.SUPERSEDED`), the database correctly updates `is_current = false` for the previous version.
   - However, `state.result_cache` had zero invalidation path on supersession. For up to 5 minutes (300 seconds), subsequent queries for the same question returned cached passages from the superseded version, violating compliance and regulatory accuracy.
   - Furthermore, `BM25Index` builds its in-memory term dictionary and postings at service startup (`WHERE v.is_current`). An un-invalidated `BM25Index` would continue serving superseded chunk IDs in the lexical retrieval arm.
2. **Conflated Health Check (`GET /healthz`):**
   - `GET /healthz` currently probes both process health and database connectivity / chunk counts / operational staleness.
   - If the database suffers a transient blip, or if the container is still warming up model weights (~13s), `/healthz` returns `status: "degraded"`.
   - In standard orchestration (Kubernetes, ECS, Nomad), conflating liveness and readiness causes the orchestrator to prematurely kill and restart pods during startup or temporary downstream network hiccups, inducing cascading restart loops.

---

## 2. Architecture Decisions & Design (ADR-0014)

1. **Liveness (`GET /healthz`) vs Readiness (`GET /readyz`) Split:**
   - **Liveness (`GET /healthz`):**
     - Fast, lightweight probe reflecting internal process health and event loop liveness.
     - Does not execute database I/O; returns HTTP 200 as long as the application process is alive and responsive.
     - Exposes `status: "ok"`, `uptime_seconds`, `single_process: true`, `model_loaded`, `corpus_generation`.
   - **Readiness (`GET /readyz`):**
     - Probe reflecting serving availability for query traffic.
     - Verifies database connection pool, validates chunk availability (`corpus_chunks > 0`), checks model readiness and BM25 index status.
     - Probes `corpus_sync_state` for staleness budget compliance.
     - Returns HTTP 200 with `status: "ok"` when ready, HTTP 200 with `status: "degraded"` when corpus is stale, and HTTP 503 with `status: "unready"` when DB is unreachable or corpus chunks are missing.
2. **Event-Driven & Generation-Tagged Cache Invalidation:**
   - **Corpus Invalidation Signal:**
     - Implemented `trigger_corpus_invalidation()` and callback registry in `app/api/cache.py`.
     - In `app/ingest/store.py`, `store_document()` executes `trigger_corpus_invalidation()` on `Action.SUPERSEDED` and `Action.INSERTED`.
   - **In-Memory Cache & BM25 Invalidation:**
     - Result cache: clears all cached search and answer responses (`result_cache.clear()`).
     - BM25 Index: marks the in-memory index for reload (`state.bm25_needs_reload = True`) and reloads under `bm25_lock`.
     - Generation Counter: increments `state.corpus_generation += 1`.
   - **Thread Safety & In-Flight Concurrency:**
     - `search()` records generation at start; if generation increments in-flight, caching is skipped to prevent stale cache resurrection.
3. **Dedicated Administrative Invalidation Route:**
   - Exposes `POST /v1/admin/cache/invalidate` (authenticated with API key) allowing external ingestion runners or operators to trigger immediate cache clearance and index reload.

---

## 3. Sub-Tasks & Execution Steps

- [x] **Sub-Task 1: Plan & Architecture Specification (ADR-0014)**
  - Draft plan and design decisions.
- [x] **Sub-Task 2: Liveness vs Readiness Endpoint Split**
  - Implement `GET /readyz` in `app/api/app.py` with `ReadinessResponse`.
  - Refactor `GET /healthz` to pure liveness probe with `LivenessResponse`.
  - Add tests in `tests/test_api.py`.
- [x] **Sub-Task 3: Event-Driven Cache & BM25 Invalidation Engine**
  - Wire invalidation hooks in `app/ingest/store.py` (`store_document`) on `Action.SUPERSEDED`.
  - Wire cache clear, BM25 index reload, and generation increment in `app/api/app.py`.
  - Add `POST /v1/admin/cache/invalidate`.
- [x] **Sub-Task 4: Dedicated Integration Tests**
  - Author `tests/test_supersession_cache_invalidation.py`:
    - Test query caching -> supersession -> immediate query returns new version and never superseded version.
    - Test BM25 index refreshes to exclude superseded terms and include new terms.
    - Test `/healthz` vs `/readyz` distinct failure semantics.
    - Test in-flight concurrency during cache invalidation.
- [x] **Sub-Task 5: Documentation, ADR-0014, Verification & Push**
  - Author ADR-0014.
  - Update `README.md` and `docs/plans/master-todo.md`.
  - Run full verification gates (`ruff`, `mypy`, `pytest`, `eval-gate`).
  - Commit atomically and push to `origin/master`.
