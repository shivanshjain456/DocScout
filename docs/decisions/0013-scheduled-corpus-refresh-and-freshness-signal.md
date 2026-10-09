# ADR-0013: Scheduled Corpus Refresh, Operational Freshness Signal, and Supersession Lifecycle

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0004 (persistence schema), ADR-0008 (serve evidence not answers), ADR-0012 (corpus scale), `CORPUS_SPEC.md` §3 (C-4, C-6), `ARCHITECTURE.md` §3.1, §3.3
- **Evidence:** `migrations/0003_corpus_sync_state.up.sql`, `app/ingest/refresh.py`, `app/api/app.py` (`/healthz`), `app/api/metrics.py`, `.github/workflows/corpus-refresh.yml`, `scripts/run_corpus_refresh.sh`, `tests/test_refresh_lifecycle.py`

## Context

Prior to this decision, DocScout operated strictly as an offline, fixed-manifest ingestion demonstrator. While the initial schema (ADR-0004) anticipated multi-versioning through `document_versions.is_current`, four major operational and reliability gaps remained:

1. **Zero Scheduled Re-fetch or Drift Checks (C-4):**
   Manifest and document contents were ingested once via `python -m app.ingest run`. Upstream circular updates or local payload drifts were undetected until manual investigation.
2. **Absence of Freshness Telemetry in Health and Metrics (C-6):**
   `GET /healthz` and `GET /metrics` reported only generic database ping connectivity and raw chunk count. Operators, orchestrators, and automated monitors had no indicator of how long ago the corpus was audited, whether a refresh was overdue, or whether manifest drift had occurred.
3. **Unexercised Supersession Lifecycle:**
   While `is_current` boolean flags existed in the schema, 100% of corpus versions were current (0 superseded documents). The live lifecycle - where an amended circular at a known canonical URL demotes an older version, retains previous chunks for compliance auditability (FR-4), and updates retrieval filters - had no automated end-to-end integration test.
4. **Untested Disaster Recovery Truncate Procedure:**
   The documented disaster-recovery procedure (`README.md` lines 530–545: `TRUNCATE ... CASCADE` followed by pipeline re-run) was never tested end-to-end in CI.

## Decision

1. **Migration 0003: `corpus_sync_state` Singleton Table**
   - Implemented `migrations/0003_corpus_sync_state.up.sql` with a single-row constraint (`CHECK (id = 1)`) storing:
     - `last_checked_at`: UTC timestamp of the last executed sync or audit.
     - `last_manifest_sha`: SHA-256 hash of the manifest file during the sync.
     - `check_status`: Status enum constraint (`ok`, `manifest_changed`, `warning`, `error`).
     - `documents_checked`, `documents_current`, `documents_superseded`: Operational counts.
     - `details`: JSONB audit metadata including item-level drift and duration.
     - `updated_at`: Postgres row timestamp.
   - Least-privilege role `docscout_app` is granted `SELECT`, `INSERT`, `UPDATE`, but denied `DELETE`.

2. **Configurable Staleness Budget & Health Degradation**
   - Added `DOCSCOUT_CORPUS_STALENESS_BUDGET_HOURS` to `app/config.py` (default: 168.0 hours / 7 days).
   - `GET /healthz` probes `corpus_sync_state`, calculates `stale_hours = (now_utc - last_checked_at)`, and evaluates `is_stale = stale_hours > staleness_budget_hours`.
   - When `is_stale` is true, `/healthz` transitions from `status: "ok"` to `status: "degraded"` while maintaining HTTP 200 so orchestrators receive an actionable degraded signal without crash-looping pod restart budgets.

3. **Prometheus Operational Freshness Exposition**
   - Added Prometheus gauges to `app/api/metrics.py`:
     - `docscout_corpus_last_checked_timestamp_seconds` (Unix epoch)
     - `docscout_corpus_stale_hours` (hours since last audit)
     - `docscout_corpus_staleness_budget_hours` (configured threshold)
     - `docscout_corpus_is_stale` (1.0 if stale, 0.0 if fresh)
     - `docscout_corpus_versions_current` (count of active versions)
     - `docscout_corpus_versions_superseded` (count of superseded versions)
     - `docscout_manifest_changed_total` (counter of detected manifest drifts)

4. **Corpus Refresh Engine & Automation**
   - Created `app/ingest/refresh.py` with `run_corpus_refresh()` providing:
     - Manifest file hash auditing and item-level content SHA-256 verification.
     - Optional live HTTP probing (`--check-live`) with `If-None-Match`/`If-Modified-Since` and `Content-Length` mismatch validation against regulatory endpoints.
     - Offline determinism by default (`check_live=False`) ensuring CI runs without external network dependencies.
     - Provenance reporting: writes `RefreshReport` JSON to `corpus/reports/refresh/<timestamp>/refresh.json`.
   - Added CLI command `python -m app.ingest refresh` with `--check-live`, `--dry-run`, and `--no-alert`.
   - Added Makefile targets `make refresh` and `make refresh-check`.
   - Added GitHub Actions workflow `.github/workflows/corpus-refresh.yml` scheduled weekly on Mondays at 03:00 UTC and dispatchable via workflow trigger.

5. **Tested Lifecycle & Disaster Recovery**
   - Test suite `tests/test_refresh_lifecycle.py` validates:
     - Freshness updates and provenance reporting.
     - Alerting and metric increments on manifest hash change.
     - Liveness and operational health degradation under exceeded staleness budget.
     - End-to-end supersession lifecycle at a known URL: verifying older version demotion, chunk retention (FR-4), and retrieval exclusion of superseded text.
     - Documented `TRUNCATE ... CASCADE` disaster-recovery procedure restoring all 35 documents and 230 chunks with zero offset errors.

## Consequences

- **Positive:** Operators have continuous visibility into corpus freshness and upstream drift via standard Prometheus alerts and `/healthz`.
- **Positive:** Regulatory amendments at known URLs can be ingested safely with full historical version auditability and zero retrieval pollution.
- **Positive:** C-4 and C-6 in `CORPUS_SPEC.md` are resolved.
- **Trade-off:** Live checking (`--check-live`) involves external network latency against regulatory domains; by default, CI and standard builds remain fully offline and deterministic.
