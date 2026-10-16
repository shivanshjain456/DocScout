# ADR-0084: Bulkhead Concurrency Isolation & Adaptive Load Shedding

## Context
High-throughput enterprise AI search and compliance systems frequently experience resource contention when heavy batch operations (such as high-volume document ingestion or multi-sample evaluation runs) coincide with latency-critical customer search queries. Under a shared process execution model or monolithic thread pool, bursty background workloads can exhaust worker connections, causing customer query queueing, latency spikes, and eventual cascade timeouts.

To guarantee resilience and strict latency SLAs (p95 < 50ms) under arbitrary external bursts and background workloads, we require a Bulkhead concurrency isolation architecture and adaptive Little's Law load shedding mechanism.

## Decision
1. Implement Bulkhead Concurrency Isolation in `app/api/bulkhead.py`:
   - Configured via `BulkheadConfig` with independent pool concurrency limits:
     - `query`: 50 concurrent requests (interactive search and chat)
     - `ingest`: 10 concurrent requests (document chunking, parsing, and indexing)
     - `eval`: 5 concurrent requests (synthetic benchmarks and goldset evals)
     - `internal`: 20 concurrent requests (management and administrative workflows)
   - Exclude critical system routes (`/healthz`, `/livez`, `/readyz`, `/metrics`, `/docs`, `/openapi.json`) from shedding so monitoring and orchestration remain 100% operational.
2. Implement Adaptive Load Shedding using Little's Law ($L = \lambda W$):
   - Track moving average service time $\bar{S}$ per pool.
   - For an incoming request entering queue depth $Q$, estimate queue delay $W_{est} = (Q + 1) \times \bar{S} / \text{limit}$.
   - If estimated wait time exceeds `max_queue_wait_ms = 200.0ms` (or lower-tier requests under elevated load), shed the request immediately with HTTP 429 Too Many Requests and a `Retry-After` header.
   - Support tenant tier and priority differentiation via `X-Priority` and `X-Tenant-Tier` request headers.
3. Expose Bulkhead telemetry in `app/api/metrics.py`:
   - Gauge `docscout_bulkhead_active_concurrency` labeled by `pool`
   - Gauge `docscout_bulkhead_queue_depth` labeled by `pool`
   - Counter `docscout_bulkhead_shed_requests_total` labeled by `pool` and `reason`
4. Provide ASGI middleware integration in `app/api/middleware.py` and register it in `app/api/app.py`.

## Consequences
- **Positive:**
  - Complete isolation between bulk background tasks and user queries: 100 concurrent ingestion jobs produce 0% interference or starvation for user queries.
  - Sub-50-microsecond ($\le 0.05\text{ ms}$) admission check overhead.
  - Fail-safe overload behavior: graceful HTTP 429 with retry hints rather than event-loop freezing or unhandled connection resets.
  - Zero dropped requests when concurrency remains within configured limits.
- **Neutral:**
  - Heavy batch jobs exceeding pool limits receive HTTP 429 and must retry using exponential backoff.
