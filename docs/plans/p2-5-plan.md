# P2-5 Implementation Plan — Ingestion-Scale Harness

## 1. Task Definition & Operational Gap

- **Task ID:** `P2-5`
- **Capability:** Ingestion-scale harness featuring token-aware rate limiting with domain isolation, adaptive shrink-retry on 429 / token context ceiling, bounded LRU chunk embedding cache, checkpointed state machine, and concurrent worker execution.
- **Failing Query Class / Operational Gap:**
  - *Ingest throughput/latency scaling curve at 100+ documents.*
  - In production regulatory RAG systems (RBI master directions, SEBI circulars, gazettes), unthrottled ingestion loops lack back-pressure against upstream 429s (HTTP 429 Too Many Requests from embedding providers or document source endpoints).
  - Embedding models hit context length ceilings or batch size rejections when embedding chunk batches.
  - Linear re-embedding of identical or recurring regulatory provisions across corpus refreshes wastes API quota and compute, violating enterprise refresh SLAs.
  - Unbounded single-thread processing lacks parallelism, while naive concurrency leads to race conditions and uncoordinated rate limit exhaustion.
  - Process interruptions mid-batch lack formal state checkpointing and resumption, risking state inconsistency or redundant re-work.
- **DocScout Objective:**
  - Build `app/ingest/harness.py` offering production-grade ingestion scaling primitives.
  - Preserve NFR-8 idempotency: identical document hash yields zero duplicate chunks and skips work cleanly.
  - Implement adaptive batch shrink-retry with exponential jitter backoff on 429 and context-length errors.
  - Provide a content-hash-indexed LRU embedding cache eliminating redundant vector embeddings.
  - Provide a resilient task state machine with stage checkpointing and crash resumption.
  - Benchmark a 200-document simulated ingest run across concurrency 1, 4, and 8, committing raw metrics to `loadtests/reports/` or `evals/bench/reports/`.
  - Author and commit `ADR-0023: Ingestion-Scale Harness and Back-Pressure Architecture`.

---

## 2. Sub-tasks Breakdown

### Sub-task 1: Ingestion Harness Core Architecture (`app/ingest/harness.py`)
- **Scope:**
  - `TokenBucketLimiter` / `DomainRateGovernor`:
    - Leaky/Token Bucket rate limiter with per-domain isolation (e.g. `embedding`, `fetch`).
    - Configurable requests-per-second (`rps`) and tokens-per-second (`tps`).
    - Non-blocking token acquisition with delay estimation and back-pressure.
  - `shrink_retry`:
    - Adaptive batch execution wrapper.
    - Catches rate limit errors (HTTP 429) and context length/batch size ceiling errors.
    - Bisects batch size (e.g., 32 → 16 → 8 → 1) with jittered exponential backoff until successful.
  - `ChunkEmbeddingCache`:
    - Bounded LRU memory cache indexed by content hash `sha256(f"{model_id}:{chunk_text}".encode())`.
    - Returns cached vector embeddings for identical text spans across circular updates, saving 100% of compute for unchanged chunks.
    - Cache statistics tracking (`hits`, `misses`, `hit_ratio`, `evictions`).
  - `IngestionTaskStateMachine`:
    - Explicit lifecycle: `QUEUED` → `EXTRACTING` → `CHUNKING` → `EMBEDDING` → `INDEXING` → `COMPLETED` / `FAILED`.
    - Checkpoints stage results so interrupted batches resume from last known good state.
  - `ConcurrentIngestionHarness`:
    - Multi-worker ingestion orchestrator (concurrency: 1, 4, 8).
    - Thread-safe coordination with domain rate limiter and embedding cache.
    - Telemetry tracking: documents processed, chunks created, tokens encoded, cache hit ratio, total elapsed time, docs/sec throughput.
- **Success Criteria:** `app/ingest/harness.py` passes strict type checks and cleanly exports modular primitives.

---

### Sub-task 2: Unit & Integration Test Suite (`tests/test_ingest_harness.py`)
- **Scope:** Implement exhaustive test suite:
  1. `TokenBucketLimiter`: burst allowance, steady refill, rate limiting delays, and multi-domain isolation.
  2. `shrink_retry`: bisection on batch size ceiling, exponential backoff on simulated 429, error propagation when minimum batch size fails.
  3. `ChunkEmbeddingCache`: cache hits, cache misses, capacity eviction, and vector equality.
  4. `IngestionTaskStateMachine`: state transitions, failure states, and resume-from-checkpoint validation.
  5. `ConcurrentIngestionHarness`: concurrent execution at 1, 4, 8 workers, thread safety, and telemetry aggregation.
  6. Idempotency preservation: re-running identical documents does not write duplicates (NFR-8 invariant).
- **Success Criteria:** 100% of tests pass cleanly.

---

### Sub-task 3: Scale Benchmarking Harness & Artifact Generation
- **Scope:**
  - Create benchmark runner (`scripts/bench_ingest_scale.py` / harness benchmark method).
  - Simulate 200 documents representing regulatory circulars with varying lengths and tabular content.
  - Benchmark concurrency levels 1, 4, and 8 with and without embedding cache.
  - Output structured JSON benchmark report at `loadtests/reports/<timestamp>/ingest-scale.json` or `evals/bench/reports/ingest_scale.json`.
- **Success Criteria:** Committed benchmark report documenting throughput (docs/sec, chunks/sec, tokens/sec), speedup curves, and cache hit ratios.

---

### Sub-task 4: Architecture Decision Record (`docs/decisions/0023-ingestion-scale-harness.md`)
- **Scope:** Document context, decision, consequences, and rejected alternatives for:
  - Token-bucket governor vs external queue services (Celery/RabbitMQ).
  - Content-addressable chunk caching vs document-only deduplication.
  - Adaptive bisection shrink-retry vs fixed retry loops.
  - In-process worker pool vs distributed workers for single-node regulatory services.
- **Success Criteria:** ADR-0023 formatted with standard structure and rejected alternatives.

---

### Sub-task 5: Verification, CI Push & Master Documentation Update
- **Scope:**
  - Run full test suite (`pytest -q`), `ruff check`, `ruff format --check`, `mypy`.
  - Update `docs/plans/master-todo.md` marking P2-5 complete.
  - Commit `feat(P2-5): ingestion scale harness with rate limiting, adaptive retry, and chunk cache`.
  - Push to `origin/master` and verify remote CI run is 100% green.
  - Proceed to `P2-GUARD`.
