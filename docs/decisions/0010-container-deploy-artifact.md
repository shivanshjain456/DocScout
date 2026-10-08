# ADR-0010: Ship a local container deploy artifact before any cloud topology

- **Status:** accepted
- **Date:** 2026-10-08
- **Deciders:** DocScout agent operator
- **Related:** `docs/AUDIT-2026-10-02.md` G6 (ABSENT Dockerfile), G15 (ABSENT deploy path) · `docker-compose.yml` · `Dockerfile` · `.dockerignore` · `Makefile` `deploy`/`destroy` · `tests/test_config_coherence.py` · `scripts/verify_setup.sh` V2/V3/V17
- **Evidence:** `Dockerfile` (pinned base digest, `uv sync --frozen`, non-root, HEALTHCHECK, explicit HF cache) · `docker-compose.yml` (`db` unchanged + `api` service) · `.github/workflows/ci.yml` `deploy-smoke` job · `docs/deploys/` evidence pattern

## Context

Reproducibility is ahead: native `scripts/dev_db_native.sh`, compose `db`
(`pgvector/pgvector:0.8.6-pg18-trixie`), and CI `services.postgres` agree on one
pairing, guarded by a test that fails the build on drift. Deployability is
behind: no `Dockerfile`, no runnable image, and `make deploy`/`make destroy`
are intentional `exit 1` stubs. A reviewer can reproduce every number locally
but cannot build and run the service as a container where a daemon exists.

The datastore pairing is the measured baseline (every published number was
measured on PostgreSQL 18.6 + pgvector 0.8.6). Any deploy artifact that forks
that pairing silently re-measures on a different engine. The model cache
(BGE-small 129 MB) is the other silent variable: downloaded at first boot it
becomes an unmeasured cold-start cost.

## Decision

We will ship exactly one local container path, in this order:

1. **One `Dockerfile`** for the API: Debian trixie Python 3.12 pinned by
   manifest-list digest, `uv sync --frozen --no-dev` against the committed
   lock, non-root `app` user, `HEALTHCHECK` against `/healthz`, no secret in
   layers or history, BGE-small pre-warmed at build time into `/opt/hf-cache`
   with the same path as a named volume (`hf-cache`) at run time.
2. **One `api` service in `docker-compose.yml`** sharing the existing `db`
   contract (same image, same `infra/initdb/` mount, same healthcheck).
   `DATABASE_URL` inside compose addresses `db:5432`; passwords interpolate
   from `.env` and are never hardcoded. The `db` definition is unchanged in
   behavior.
3. **Real `make deploy` / `make destroy`** scoped to local compose only:
   `deploy` builds `api`, starts `db`, waits healthy, runs `migrate up` +
   `ingest run`, starts `api`, waits on `/healthz`, and prints the health
   body; `destroy` tears down containers, volumes, and the local image and
   proves nothing remains. Neither creates cloud resources.
4. **Guards stay green and get stronger:** `test_config_coherence.py` keeps
   the triple-pin and gains Dockerfile/api/entrypoint assertions; no assertion
   is loosened. `verify_setup.sh` V2 moves from the stale `0.8.2` to the
   measured `0.8.6`; V3/V17 stop expecting a `redis` service nothing connects
   to. `Makefile dev` and `AGENTS.md` name the runnable `app.api.app:app`.

## Consequences

What becomes easier: a reviewer with a daemon runs the documented sequence
and reaches `status: ok` with `corpus_chunks: 170`; each later task is
reviewable against a running service; CI `deploy-smoke` proves the image
builds and serves on every push.

What becomes harder: the base digest must be re-pinned deliberately when
trixie moves; the image is large (torch CPU + transformers + 129 MB weights);
`deploy` takes minutes on first build. All three are visible costs, not
silent ones.

What we monitor: base-image freshness, image size, cold-start time
(embedder + BM25 warmup inside lifespan, covered by `start_period: 60s`),
and `hf-cache` volume growth.

## Rejected alternatives

### A. Cloud deploy (registry + managed Postgres + hosted URL) now

Plausible because it would close the deploy gap completely. Rejected: it
requires credentials, spend, and a billing alarm before any value is proven,
and it would fork the measured pairing (managed Postgres version, extension
availability) without a local proof first. Revisit when the local artifact is
green in CI and a concrete hosting decision exists with its own ADR.

### B. Helm / multi-service orchestration now

Plausible because the comparators ship Helm charts. Rejected: one stateless
API + one Postgres does not need orchestration; a chart with one replica and
no queue is scaffolding presented as architecture. Revisit when a second
service (worker, queue) justifies it.

### C. Bake migrations + ingest into the image build

Plausible because it would make `docker run` immediately serve 170 chunks.
Rejected: build-time ingestion bakes a database snapshot into a layer,
breaks the `store.py` retention/transaction contract (which assumes a live
`db`), and hides the `migrate → ingest → verify` sequence the runbook must
prove. The image carries code + weights; data enters at deploy time via the
documented steps.

### D. Download the model silently at first boot

Plausible because it keeps the image small. Rejected: first-boot download
makes cold-start latency unmeasured and fails closed on networks without
Hugging Face access. Pre-warming at build fails the build instead of the
boot, and the named volume makes reuse explicit.

### E. Keep `make deploy` / `make destroy` as documented stubs

Plausible because stubs are honest about missing scope. Rejected: the gap is
now the blocking one, and a stub that stays after the artifact exists is a
dead path. Both targets are implemented and both are tested; neither is
scaffolded.
