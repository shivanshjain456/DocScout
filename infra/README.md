# DocScout Infrastructure & Deployment Architecture

- **Datastore Pairing:** Single `docker-compose.yml` service `db` pinned to `pgvector/pgvector:0.8.6-pg18-trixie` (PostgreSQL 18.6 + pgvector 0.8.6 triple-pin verified by `tests/test_config_coherence.py`).
- **Worker Concurrency & Caching:** Serving API runs as `api single-worker in-memory cache` with local LRU / TTL semantics for deterministic zero-dependency operations; configure `REDIS_URL` for multi-worker distributed invalidation when scaling horizontally.
- **Probe Semantics:**
  - `GET /healthz`: Zero-DB liveness probe safe for pod liveness and container orchestrator restarts.
  - `GET /readyz`: Deep traffic readiness probe checking PostgreSQL connection pool, chunk count, and staleness budgets.
- **Topology Decision (1.x):** Orchestration is intentionally packaged as a deterministic single-compose stack for 1.x rather than Helm/Kubernetes manifests (recorded architectural trade-off, not an oversight), ensuring immediate developer reproducibility and offline verification under 90 seconds.
