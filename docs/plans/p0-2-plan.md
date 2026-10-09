# Plan: P0-2 — Scheduled Corpus Refresh and Freshness Signal

**Status:** VERIFIED
**Owner:** Principal Engineer
**Target:** Transform DocScout from a static offline ingestion demonstrator into an operable service with continuous regulatory freshness tracking, operator/API visibility, staleness budgeting, alerting on manifest changes, and proven supersession/rebuild procedures.

---

## 1. Problem Statement & Baseline Deficiencies

1. **Stale Regulatory Retrieval Risk:**
   - RBI and SEBI amend, update, and withdraw circulars continuously. Stale retrieval is the primary catastrophic failure in financial compliance RAG.
   - Gold item `g-038` concerns a withdrawn circular; currently, the live corpus has 1 version per document and 0 superseded versions live. Supersession was unit-tested (`tests/test_supersession.py`) but never exercised in an operational lifecycle or verified across live documents.
2. **Absence of Freshness / Staleness Signal:**
   - `GET /healthz` only probed database connectivity and `chunks > 0`. A deployment that has not been refreshed in weeks would report `status: "ok"`.
   - Prometheus `/metrics` reported query latencies and chunk counts, but zero freshness metrics (`last_checked_at`, `stale_hours`, `staleness_budget_hours`, `is_stale`).
3. **No Scheduled Refresh or Change Detection:**
   - Ingestion was purely manual via `make ingest`. There was no scheduled refresh runner, no automated check for changed circular hashes or new publications, and no alerting when manifest or remote documents change.
4. **Untested Rebuild Procedure:**
   - `README.md` lines 509–521 described a manual `TRUNCATE chunks, document_versions, documents CASCADE; make ingest ...` procedure, but this recovery path was described in prose without automated test coverage.

---

## 2. Architecture Decisions & Design (ADR-0013)

1. **Durable Freshness Tracking (Migration 0003):**
   - Create table `corpus_sync_state` with single-row constraint (`id = 1`):
     - `last_checked_at`: timestamptz NOT NULL
     - `last_manifest_sha`: char(64)
     - `check_status`: text NOT NULL ('ok', 'warning', 'error', 'manifest_changed')
     - `documents_checked`: integer NOT NULL DEFAULT 0
     - `documents_current`: integer NOT NULL DEFAULT 0
     - `documents_superseded`: integer NOT NULL DEFAULT 0
     - `details`: jsonb NOT NULL DEFAULT '{}'
     - `updated_at`: timestamptz NOT NULL DEFAULT now()
   - Grant `SELECT, INSERT, UPDATE` on `corpus_sync_state` to `docscout_app`.
2. **Configurable Staleness Budget:**
   - In `app/config.py`: introduce `CORPUS_STALENESS_BUDGET_HOURS` (default 168.0 hours = 7 days, configurable via `DOCSCOUT_STALENESS_BUDGET_HOURS` or `STALENESS_BUDGET_HOURS`).
3. **Freshness Visibility on API & Metrics:**
   - In `HealthResponse` (`app/api/models.py` & `app/api/app.py`):
     - Expose `last_checked_at: datetime | None`, `stale_hours: float | None`, `staleness_budget_hours: float`, `is_stale: bool`.
     - When `is_stale` is true (`stale_hours > staleness_budget_hours`), health endpoint degrades (`status: "degraded"`), signaling to operators/load balancers that the corpus requires refresh.
   - In `app/api/metrics.py`:
     - Expose Prometheus gauges:
       - `docscout_corpus_last_checked_timestamp_seconds`
       - `docscout_corpus_stale_hours`
       - `docscout_corpus_staleness_budget_hours`
       - `docscout_corpus_is_stale`
       - `docscout_corpus_versions_current`
       - `docscout_corpus_versions_superseded`
       - `docscout_manifest_changed_total` (counter)
4. **Scheduled Refresh Engine (`app/ingest/refresh.py` & CLI):**
   - Provide `python -m app.ingest refresh` (and `make refresh`).
   - Supports:
     - Manifest check (hashing disk files against manifest, comparing manifest digest).
     - Remote check mode (`--check-live`) to probe regulatory URLs with HEAD/conditional requests.
     - Detects changed `sha256` (supersessions) or new documents.
     - Alerts on manifest/content changes (logs warning, increments metric, writes alert in report).
     - Updates `corpus_sync_state` in PostgreSQL.
     - Writes structured report to `corpus/reports/refresh/<timestamp>/refresh.json`.
   - CI Determinism: Refresh in CI operates on committed manifest / disk cache (preserving 100% determinism), while scheduled workflows run periodic live checks.
   - Provide GitHub Actions workflow `.github/workflows/corpus-refresh.yml` and shell runner `scripts/run_corpus_refresh.sh`.
5. **Tested Supersession & Truncate-Rebuild Lifecycle:**
   - Dedicated test suite `tests/test_refresh_lifecycle.py`:
     - Test 1: Ingestion updates `corpus_sync_state` and surfaces accurate timestamps.
     - Test 2: `GET /healthz` and `GET /metrics` expose freshness fields, staleness hours, and react to simulated stale timestamps by reporting `"degraded"`.
     - Test 3: Supersession lifecycle: When a document at a known canonical URL is re-ingested with an updated `sha256`, the old version is demoted to `is_current = false`, old chunks are retained (FR-4), new chunks are inserted with uuid5 IDs (ADR-0005), and retrieval strictly returns only current chunks.
     - Test 4: Re-embed truncate procedure: Execute `TRUNCATE chunks, document_versions, documents CASCADE`, re-ingest, verify FR-7 offsets roundtrip, verify chunk ID reproducibility and retrieval parity.

---

## 3. Sub-Tasks & Execution Steps

- [x] **Sub-Task 1: Migration 0003 (`corpus_sync_state`)**
  - Author `migrations/0003_corpus_sync_state.up.sql` and `0003_corpus_sync_state.down.sql`.
  - Apply migration via `scripts/migrate.py up` and verify `status`.
  - Add schema tests in `tests/test_schema.py`.
- [x] **Sub-Task 2: Freshness Tracking & Staleness Budgeting**
  - Add `CORPUS_STALENESS_BUDGET_HOURS` to `app/config.py`.
  - Update `app/ingest/store.py` to record and query `corpus_sync_state`.
  - Update `app/ingest/pipeline.py` (`run_ingest`) to record sync state upon ingest completion.
  - Update `app/api/models.py` (`HealthResponse`) with freshness fields.
  - Update `app/api/metrics.py` with freshness Prometheus gauges.
  - Update `app/api/app.py` (`healthz`) to read sync state and set metrics.
- [x] **Sub-Task 3: Scheduled Refresh Engine & CLI**
  - Author `app/ingest/refresh.py`.
  - Wire `python -m app.ingest refresh` in `app/ingest/__main__.py`.
  - Add Makefile targets `refresh` and `refresh-check`.
  - Add `.github/workflows/corpus-refresh.yml` and `scripts/run_corpus_refresh.sh`.
- [x] **Sub-Task 4: Comprehensive Lifecycle & Supersession Tests**
  - Author `tests/test_refresh_lifecycle.py` covering:
    - Freshness state recording & queries.
    - Alerting and metric increments on manifest hash drift.
    - Staleness degradation under exceeded budget.
    - Full supersession lifecycle with changed sha256 at known URL.
    - Truncate-and-rebuild procedure (`TRUNCATE ... CASCADE` -> ingest -> verify).
- [x] **Sub-Task 5: Documentation & Decision Record**
  - Author `docs/decisions/0013-scheduled-corpus-refresh-and-freshness-signal.md` (ADR-0013).
  - Update `README.md` (Rebuilding derived data & Operational freshness sections).
  - Update `docs/corpus/CORPUS_SPEC.md` and `docs/plans/master-todo.md`.
- [x] **Sub-Task 6: Verification Gates, Commit & Push**
  - Run full test suite (`pytest -q`).
  - Run pre-commit hooks and typecheck (`mypy app tests`).
  - Commit atomically: `feat(P0-2): scheduled corpus refresh, freshness signal, and tested supersession lifecycle`.
  - Push to `origin/master`.
