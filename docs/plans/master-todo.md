# DocScout  -  Master TODO (transformation to production-grade operational RAG service)

- **Baseline:** `32b427178d7feb2dbeb94db294bd097268c2a4b1` (master, 2026-10-02T12:45:13Z), 333 tracked files, 46 commits.
- **Benchmark revisions (2026-10-08 SHAs):** RAGFlow `ef150bc2`, Onyx `f858083d`, Dify `2b65f0e8`, FastGPT `2ae3c721`, Khoj `ae229ca8`.
- **Corpus / gold at baseline:** 21 documents (20 PDFs + 1 synthetic canary) → 170 chunks → 150 citations → 153 gold items (131 answerable + 22 unanswerable). Serving: `POST /v1/search` (retrieval-with-citations, no generation), `GET /healthz`, `GET /metrics`, `GET /` demo, `GET /docs`.
- **Method for this file:** every item restated from `do not commit!/docscout_assessment.md` §5 (which cites file:line evidence at the pinned baseline). No implementation approach is prescribed here  -  only WHAT / QUALITY BAR / SUCCESS.
- **Status vocabulary:** `TODO` / `PLANNED` / `IN_PROGRESS` / `DONE` / `VERIFIED` (`VERIFIED` = gates green + evidence artifact committed).
- **Execution rule:** strictly one task at a time, highest remaining P0 → P1 → P2. Update status after each task.

---

## 0. Existing strengths that must not regress (§10.1, load-bearing)

These are verified at baseline and every task must keep them green. Regression here is a failure even if the new task passes.

| # | Strength | Evidence anchor (baseline) |
|---|---|---|
| S-1 | Citation correctness via uuid5 + FR-7 re-derive | `app/ingest/ids.py` (uuid5 `4ffde409…`, `sha256:char_start:char_end`), `app/ingest/chunk.py::verify_offsets`, `app/ingest/pipeline.py::verify_stored_chunks`, `migrations/0002_chunk_id_content_derived.up.sql` (drops uuidv7 default), M4 verify `170/170` |
| S-2 | Invisible-codepoint hygiene | `app/ingest/clean.py::blank_invisible` (Cf/Co/Cs, length-preserving, re-checked), `find_invisible`, audit G1 4→0 |
| S-3 | Leakage-aware measurement | `app/evals/runner.py::_leakage_bands` (fixed cuts 0–0.5/0.5–0.8/≥0.8), victim 0.733 vs random 0.094 (7.8×), low band n=8 reported despite small-n |
| S-4 | Paired bootstrap + McNemar on every comparison | `app/evals/stats.py::paired_bootstrap` (10k, seed 0) + `mcnemar_counts`, `runner.py::_comparisons` |
| S-5 | Gate with noise floor | `app/evals/gate.py::check_regression` (1pp vs mean-of-3, `_DELTA_PRECISION=6`) + `noise_floor` (MDE 3.24pp reported beside verdict) |
| S-6 | Reproducibility trifecta | `corpus/raw/` tracked + `source.py::iter_manifest_documents` re-hash, triple-pin pgvector 0.8.6 guarded by `tests/test_config_coherence.py`, `uv sync --frozen` 169-lock, `scripts/bootstrap.sh` idempotent |
| S-7 | Observability single-service | `app/observability.py::configure_logging` (+ `_redact_sensitive` processor), `app/api/app.py::correlate_and_log` (one line, X-Request-ID echo), `app/api/metrics.py` (7 metrics, bounded labels, buckets incl. 3s SLO) |
| S-8 | Decision hygiene | 9 ADRs in `docs/decisions/` each with Rejected alternatives + `docs/decisions/evidence/`, U-1 withdrawal enforced by `tests/test_rescope.py`, `docs/AUDIT-2026-10-02.md` DONE vs ABSENT honesty |
| S-9 | Defect-found-fixed-proven pattern | G23 (10/10 superseded served → filtered in both arms, `tests/test_supersession.py`), G1 (U+F0E0 → blank → 0), G7 (0.8.2 vs 0.8.6 → coherence test) |

Gates that guard S-1…S-9: `ruff check + ruff format --check`, `mypy` strict (`python_version 3.12`, `warn_unused_ignores`), 11 pre-commit hooks, 4 CI jobs (`quality`, `secrets`, `supply-chain`, `eval-gate`), `make verify-setup` V1–V17, `make test`, `make eval`, `make eval-gate`, `make bench`, `make audit-deps`, `make mutation` (scoped to `scorers.py`/`stats.py`).

---

## P0  -  Blocking operational-retrieval maturity (build in this order)

Order rationale (assessment §5): P0-4 first (unblocks reviewability) → P0-1 (capability ceiling) → P0-3 (makes tuning measurable) → P0-2 (freshness truth) → P0-5 (correctness fix triggered by P0-2).

### P0-4  -  Runnable Production Deploy Artifact | Status: VERIFIED (`docs/deploys/20261008T190000Z-p0-4-live.md`: image built + served, `/healthz` ok/170, eval+gate green, destroy proven)

- **Dimension:** Deployment and reproducibility (§3.16).
- **Current evidenced state:** Reproducibility ahead (native `scripts/dev_db_native.sh`, compose `docker-compose.yml` single `db` service `pgvector/pgvector:0.8.6-pg18-trixie`, CI `services.postgres` same image; triple-pin guarded by `tests/test_config_coherence.py`). Deployability behind: no `Dockerfile`, no Helm/ECS/K8s, `Makefile:104-115` `deploy`/`destroy` are intentional `exit 1` stubs (audit G6 ABSENT, G15 ABSENT). `README.md:260-263` honestly states "API is not deployed … No cloud resources".
- **Benchmark comparator:** Onyx (compose prod/dev/airgap/multitenant/lite + Helm + ECS Fargate + Terraform), RAGFlow (compose CPU/GPU/CN/macOS + nginx + Dockerfiles), Dify (compose middleware profiles + Helm), FastGPT (`deploy/k8s` + docker templates), Khoj (compose pgvector + migrations + deploy docs). All five build an image and serve it; DocScout does not.
- **Practical significance:** A reviewer can `git clone → make verify-setup → make eval` and reproduce every number but cannot `docker build → docker run → curl /healthz`. Reproducibility without deployability keeps the system a local demo rather than an operable service.
- **WHAT TO DO:** Provide the artifact(s) that make DocScout buildable and runnable as a containerized service from a clean checkout with only `.env` edited, and document the one-command path to a locally running service that serves `/healthz`.
- **QUALITY BAR:** Reproducibility and deployability are coherent (the same pgvector 0.8.6 pairing that benchmarks were measured on, `uv sync --frozen` 169-lock honored, non-root runtime, healthcheck, no secret in image or history, model cache handled explicitly rather than downloaded silently at boot). Existing `test_config_coherence.py` triple-pin invariant remains green.
- **WHAT SUCCESS LOOKS LIKE:** From a clean clone, the documented build+run sequence succeeds where a daemon exists, `curl /healthz` returns `status: ok` with `corpus_chunks: 170`, and the steps are verified by at least one CI job or a committed verify log. `make deploy`/`make destroy` are no longer intentional `exit 1` stubs. `README.md` Limitations honestly reflects the new state.

### P0-1  -  Answer Construction Behind Passages, With Judged Evaluation | Status: VERIFIED (`evals/calibration/20261008T200000Z/calibration_report.md`: 80 double-labelled items, kappa 1.000 / 0.844, 100% canary defense, ADR-0011)

- **Dimension:** Context/answer construction and model integration (§3.7) + evaluation quality (§3.9).
- **Current evidenced state:** Deliberate scoped-out state, not an omission: `app/generate/__init__.py` is 0 bytes by design (ADR-0008 `docs/decisions/0008-serve-evidence-not-answers.md`); `config/models.json` hosted IDs all `null` with `status: BLOCKED_NO_CREDENTIAL`; `docs/eval/EVAL_PROTOCOL.md §4.2` closes U-1 as outcome (b) re-scope (judge WITHDRAWN); `tests/test_rescope.py` fails the build if faithfulness/kappa reappears as a published number. `POST /v1/search` returns `Passage[]` + provenance, no prose; eval measures passages (recall/MRR/nDCG), faithfulness undefined-not-1.0.
- **Benchmark comparator:** All five construct answers: RAGFlow 11-phase `chat_pipeline.go` (5,350 lines) + DeepResearcher depth-3 + citation insertion `citation.go`; Onyx `run_llm_loop` + `DynamicCitationProcessor`; Dify workflow graph + agent strategies; FastGPT workflow/dispatch; Khoj `routers/helpers.py` (3,458 lines) + research tool loop. DocScout has no comparable product tier.
- **Practical significance:** Everything an analyst uses is an answer, not passages. Retrieval is measured; the product tier is not. Without a generator DocScout cannot demonstrate faithful synthesis or citation-faithful generation, the two hardest RAG signals.
- **WHAT TO DO:** Introduce answer generation that sits **behind** the existing retrieval-with-citations surface (passages remain in the response; generated answer is an additional field, not a replacement), hardened against prompt injection from untrusted corpus content, and introduce a calibrated, human-grounded evaluation of answer faithfulness and citation precision/recall.
- **QUALITY BAR:** No hallucination posture: every generated claim is grounded in returned passages; corpus text is treated as data, never instructions (injection canary remains a graded negative test). Evaluation is not an opinion: it is a measured instrument with known error  -  cross-provider judge, double-labelled human agreement, reported kappa, and abstention at the answer level where the corpus cannot answer. The withdrawn scope (U-1 outcome b, `EVAL_PROTOCOL.md §4.2`, `config/models.json` BLOCKED hosted IDs, `tests/test_rescope.py` enforcement) is reopened only when its explicit reopen conditions are met; no faithfulness number is published without the calibration artifact.
- **WHAT SUCCESS LOOKS LIKE:** A new endpoint or field returns an answer **and** the passages; a committed evaluation report shows faithfulness, answer citation precision/recall, and hallucination rate with judge calibration evidence (60–100 double-labelled items, agreement metrics, per-item raw outputs). Injection canary still correctly detected (not obeyed). All existing retrieval metrics still reported and still describe the passages being served.

### P0-3  -  Corpus and Gold Scale Beyond Saturation | Status: VERIFIED (35 docs, 230 chunks, 425 gold items v2.0.0, recall@10 < 1.000, MDE <= 1.0pp, low-leakage n=54, ADR-0012)

- **Dimension:** Evaluation quality + retrieval measurability (§3.6, §3.9, §3.17).
- **Current evidenced state:** `corpus/raw/manifest.json` 21 docs, 170 chunks; `evals/gold/v1/metadata.json` v1.0.0 153 items (131 answerable + 22 unanswerable), 150 citations, `CORPUS_SPEC.md` C-3/C-5 breadth undecided; pinned report `evals/reports/20261002T124408Z/report.md`: recall@10 = 1.000 (hybrid + bm25), dense 0.981; one item = 0.76pp, MDE 3.24pp, gate 1pp runs below noise; leakage victim 0.733 vs random 0.094 (7.8×), low-leakage band n=8.
- **Benchmark comparator:** RAGFlow benchmark reports, Onyx `run_eval` + daily/regression suites, Khoj HF datasets + judge harness  -  all evaluate over corpora where depth-10 still discriminates. DocScout's depth-10 has no discriminative power left.
- **Practical significance:** No architecture can be told from any other at recall@10 = 1.000; rerank headroom invisible (ADR-0009 +2.3pp@1 for 30× p95 on 170 chunks); BM25-vs-hybrid verdict is one item. Harness is precise about an imprecise ruler.
- **WHAT TO DO:** Grow the corpus and gold set to where retrieval is no longer saturated (recall@10 < 1.000 for at least one configuration) and the regression gate's minimum detectable effect is at or below the 1pp threshold, with query variants that reduce the lexical leakage advantage (currently victim 0.733 vs random 0.094, 7.8×, low-leakage band n=8).
- **QUALITY BAR:** Growth is principled, not bulk. Corpus breadth decisions (`CORPUS_SPEC.md` C-3/C-5) are made and recorded. Query variants are paraphrased in human language, not templated from evidence quotes. Gold set version is bumped when its ruler changes; invariants in `gate.py` correctly detect a ruler change. No synthetic padding that inflates metrics.
- **WHAT SUCCESS LOOKS LIKE:** Committed `corpus/raw/` + `manifest.json` growth with re-hashed evidence; `evals/gold/v1/` version bump with updated `metadata.json` composition and honest `labelling` disclosure; `make eval` shows `report.md` with recall@10 no longer 1.000 for every config, leakage low-band n is statistically credible, and `gate.json` shows `minimum_detectable_effect_pp ≤ 1.0`.

### P0-2  -  Scheduled Corpus Refresh and Freshness Signal | Status: VERIFIED (Migration 0003 corpus_sync_state singleton, staleness budgeting, /healthz & Prometheus freshness gauges, app.ingest refresh CLI + GHA cron, supersession lifecycle & DR truncate proven in tests/test_refresh_lifecycle.py, ADR-0013)

- **Dimension:** Ingestion/sync (§3.1) + corpus lifecycle (§3.4).
- **Current evidenced state:** Offline deterministic idempotent ingest (`app/ingest/source.py::iter_manifest_documents` re-hash + allowlist re-validation, `pipeline.py::run_ingest` `version_exists` fast path, `store.py::store_document` INSERTED/SUPERSEDED/SKIPPED_UNCHANGED/SKIPPED_DUPLICATE_CONTENT, FR-4 retention no-DELETE, `is_current` filtered in both arms after G23 fix). No scheduled re-fetch, no change detection beyond manual `make ingest`, no `last_checked_at`/`stale_hours`, no backup/restore (audit G24). Live corpus 1 version/doc (21 current, 0 superseded) so supersession tested (`tests/test_supersession.py`) not exercised; g-038 withdrawn-circular class unexercised live. `README.md:509-521` documents manual `TRUNCATE → ingest → verify → eval → gate` but untested.
- **Benchmark comparator:** RAGFlow `internal/syncer/` scheduler + coordinator + checkpoint store + prune runner (93 connectors); Onyx Celery `docfetching/docprocessing/pruning/monitoring/scheduled_tasks` (59 connectors, checkpointed); Dify `TenantIsolatedTaskQueue` + reconciliation. Continuous sync is the operational baseline for regulatory text.
- **Practical significance:** RBI/SEBI amend and withdraw continuously; stale retrieval is the primary production failure for this domain. A future stale-circular answer looks identical to today's correct one without a freshness signal.
- **WHAT TO DO:** Provide a scheduled refresh path for the RBI/SEBI corpus and a freshness/staleness signal that is visible to operators and retrievable by the API, with alerting on manifest change and a tested path for supersession and re-embedding.
- **QUALITY BAR:** The refresh does not re-fetch live documents inside the CI gate (determinism preserved); it is a scheduled job with its own evidence. Freshness is not a log line  -  it is a metric/health field with a staleness budget. Supersession remains retention-guaranteed (FR-4) with no DELETE, and the re-embed truncate path already documented in `README.md` is tested rather than described.
- **WHAT SUCCESS LOOKS LIKE:** A committed schedule (cron or equivalent) and a `last_checked_at`/`stale_hours` field surfaced via `GET /healthz` or `GET /metrics`, plus a documented and tested `TRUNCATE → ingest → verify → eval → gate` procedure that correctly handles a changed `sha256` at a known `canonical_url` (gold item g-038 withdrawn-circular class exercised).

### P0-5  -  Cache Invalidation on Supersession + Liveness/Readiness Split | Status: VERIFIED (`docs/decisions/0014-cache-invalidation-on-supersession-and-readiness-split.md`: `tests/test_supersession_cache_invalidation.py` 4/4 passing, `GET /healthz` pure liveness with 0 DB I/O, `GET /readyz` traffic readiness with 503 on DB outage, event-driven cache & BM25 invalidation on `Action.SUPERSEDED`, admin endpoint `POST /v1/admin/cache/invalidate`)

- **Dimension:** Concurrency/caching (§3.13) + backend/API (§3.11) + fallbacks/recovery (§3.19).
- **Current evidenced state:** Invalidation is event-driven and generation-tagged via `trigger_corpus_invalidation()` on `Action.SUPERSEDED` and `Action.INSERTED` in `app/ingest/store.py`. `app/api/app.py` registers lifespan invalidation listener: clears `result_cache`, increments `state.corpus_generation`, sets `bm25_needs_reload = True`, updates Prometheus gauges and counters (`docscout_cache_invalidations_total`, `docscout_corpus_generation`), and protects against in-flight cache poisoning. `GET /healthz` is split into a pure liveness probe (0 DB I/O, returns 200 even under DB failure) and `GET /readyz` is the traffic readiness probe (validates pool connection, chunk count, staleness; returns 503 on outage, 200 on ok/degraded). Authenticated admin endpoint `POST /v1/admin/cache/invalidate` allows explicit invalidation.
- **Benchmark comparator:** RAGFlow `PruneDeletedChunks` + retry ladder; Onyx pruning tasks + checkpointed reindex; Dify vector-index reconciliation. All three ensure replaced/deleted content stops being served; DocScout's FK fix without cache invalidation did not until P0-5.
- **Practical significance:** Correct filtering in SQL is now matched by immediate cache clearance and BM25 index reload. Orchestrators and load balancers distinguish process liveness from traffic readiness.
- **WHAT TO DO:** Eliminate the post-supersession wrong-citation window where `TTLCache(300s)` keyed on `(query,mode,k)` serves passages from replaced chunks, and split readiness from liveness so a load balancer can distinguish "starting" from "broken."
- **QUALITY BAR:** Invalidation is generation-tagged or event-driven, not TTL-hopeful. In-flight requests are not dropped on invalidation. Readiness reflects pooled DB + corpus availability; liveness reflects process health. `single_process: true` disclosure remains accurate until multi-process exists.
- **WHAT SUCCESS LOOKS LIKE:** After a supersession, a subsequent `POST /v1/search` never returns a chunk whose `version.is_current = false` (proven by `tests/test_supersession_cache_invalidation.py` which supersedes a version and immediately queries the affected question); `GET /readyz` and `GET /healthz` exist with distinct semantics, both tested.

---

## P1  -  Expected operational maturity (after P0, any defensible order)

### P1-1  -  Durable Retrieval Audit Log + Corpus Secret/PII Scan | Status: VERIFIED (Migration 0004 retrieval_audit_log with append-only permissions, query privacy SHA-256 hash, key fingerprinting, file sink fallback, app.ingest.scanner detecting secrets & PII with masking and quarantine policy, tests/test_audit_and_pii_scan.py 11/11 passing, ADR-0015)

- **Dimension:** Security/privacy (§3.15) + observability (§3.18).
- **Current evidenced state:** Controls verified (allowlist, blanking, credential isolation, fail-closed auth, compare_digest, no-reflect 422, rate limit, redaction processor, gitleaks, SBOM, canary `corpus/raw/canary-001-synthetic.txt` + 3 gold canaries). Audit findings G12 & G13 closed: Migration 0004 `retrieval_audit_log` records `(timestamp, key_fingerprint, query_hash, mode, k, returned_chunk_ids, latency_ms, cache_hit, has_generated_answer, corpus_generation)` with strict `docscout_app` append-only permissions (no UPDATE, no DELETE, no TRUNCATE); query privacy enforced (SHA-256 query hash, plaintext never stored); credential isolation enforced (key fingerprint only); optional file sink (`DOCSCOUT_AUDIT_LOG_FILE`); `app/ingest/scanner.py` runs ingestion-time scanning for candidate secrets and PII with automatic sample masking; policy separates secrets (quarantine/fail) from PII (informational warnings without blocking ingestion false positives); 90-day retention policy documented in ADR-0015.
- **Benchmark comparator:** No benchmark publishes an equivalent control trace; OWASP LLM09 ("audit retrieval logs") is the standard none fully meets. DocScout traceability otherwise ahead.
- **Practical significance:** Without `(timestamp, key fingerprint, query hash, mode, chunk ids, latency)` forensics ("what was retrieved for whom?") is unanswerable; regulator PDFs can carry incidental email/phone/address verbatim into `chunks.text` and responses.
- **WHAT TO DO:** Introduce an append-only, retention-documented audit record of retrieval events and an ingestion-time scan of corpus content for secrets/PII.
- **QUALITY BAR:** Audit log records timestamp, key fingerprint (never raw key), query hash (not plaintext by default), mode, returned chunk IDs, latency  -  not query text, not key, not request ID as a label. Corpus scan flags candidate secrets/PII in extracted text, records findings in the ingest report, and quarantines or fails per a documented policy  -  without blocking on a PII false positive. OWASP LLM09 traceability.
- **WHAT SUCCESS LOOKS LIKE:** A committed log sink (file or table) with a documented retention window; `tests` prove query text is hashed not stored by default and that gitleaks-on-repo is not confused with corpus scanning; ingest report correctly flags a synthetic secret injected via the canary path.

### P1-2  -  Metadata Filtering Beyond `is_current` | Status: VERIFIED (Migration 0005 metadata_indices, MetadataFilter DSL across dense, bm25 & hybrid, in-query SQL filtering with parameter binding, in-index BM25 candidate pruning, cache partitioning on canonical_tuple(), EXPLAIN verified index usage, tests/test_metadata_filtering.py 16/16 passing, ADR-0016)

- **Dimension:** Retrieval/filtering (§3.6).
- **Current evidenced state:** Declarative `MetadataFilter` DSL implemented supporting authority scoping (`source` in 'RBI', 'SEBI', 'SYNTHETIC'), temporal bounding (`date_from`, `date_to` over `COALESCE(d.published_date, v.fetch_ts::date)`), version currency (`is_current` defaulting to `True`, with `False` enabling historical legal audits), and target constraints (`document_ids`, `canonical_url`). In-query SQL filtering in `app/retrieval/dense.py` executes directly in Postgres with parameter binding. In-index filtering in `BM25Index` (`app/retrieval/lexical.py`) prunes candidates during posting iteration prior to accumulator updates. Cache partitioning in `app/api/app.py` incorporates `filter.canonical_tuple()` preventing cache collisions. Migration 0005 (`0005_metadata_indices.up.sql`) added indices on `documents(source)`, `documents(published_date)`, `documents(source, published_date)`, `document_versions(fetch_ts)`, and `document_versions(is_current)`. Query plan verification via `EXPLAIN` proves index scan execution. Scaling analysis in ADR-0016 documents measured deferral of chunk denormalization until multi-million scale. Tested by `tests/test_metadata_filtering.py` (16/16 passing) and `tests/test_schema.py`.
- **Benchmark comparator:** Matches Onyx ACL+docset+date+hierarchy in-query filtering and FastGPT collectionFilter metadata pruning without candidate starvation.
- **Practical significance:** Compliance analysts can strictly bound queries to specific regulatory authorities (RBI vs SEBI) and publication date windows without cross-regulatory leakage or post-hoc candidate loss. Legal audits can query superseded historical regulations.
- **WHAT TO DO:** Introduce at least one real filter DSL beyond `is_current` that is relevant to regulatory retrieval (date, circular status, or equivalent), with correct index support.
- **QUALITY BAR:** Filtering is done in-query where the index can use it (not post-hoc), with signed/leased semantics if permission-like. The denormalization or partial-index remedy noted in `dense.py` scaling comments is either implemented or explicitly deferred with a measured reason. Existing `is_current` pruning remains correct and tested.
- **WHAT SUCCESS LOOKS LIKE:** `POST /v1/search` accepts a filter parameter; integration tests show a date-bounded question correctly excludes superseded-era passages; `explain` or equivalent shows index use.


### P1-3  -  Query Understanding Expansion | Status: VERIFIED (DomainQueryExpander in app/retrieval/expansion.py, bidirectional acronym/synonym expansion across 36+ regulatory concepts, HyDE formulation, RetrievalConfig & API wiring with cache partitioning, BASELINE_CONFIGS evaluated over 365 items in evals/reports/20261009T111050Z, leakage low-band 0.889 measured, paired bootstrap CI [-0.0082, +0.0082], 14 tests in tests/test_query_expansion.py, ADR-0017 defending serving default)

- **Dimension:** Retrieval (§3.6).
- **Current evidenced state:** Literal query after BM25 analyzer; no HyDE/synonym/decomposition; no `openai`/`anthropic` import in `app/retrieval/`; hybrid ties dense in low-leakage band (dense 0.875, bm25 0.750, hybrid 0.875, n=8) and indistinguishable overall (bm25 leads hybrid by one item, all CIs include zero).
- **Benchmark comparator:** Onyx LLM expansion (semantic+keyword weighted) + scope decision; Khoj structured-JSON expansion; RAGFlow WordNet/synonym + term weights.
- **Practical significance:** Statutes are synonym-dense ("payment aggregator" = "PA" = "intermediary"); BM25 English stemming alone does not recover synonyms where low-leakage questions live.
- **WHAT TO DO:** Introduce one query-understanding strategy (expansion, HyDE, synonym/compound-split, or equivalent) and measure its effect with the leakage-stratified harness.
- **QUALITY BAR:** The strategy is evaluated on the low-leakage band specifically (where BM25 is currently weakest), not on the saturated headline. Cost is reported alongside gain (latency, token budget).
- **WHAT SUCCESS LOOKS LIKE:** `report.md` leakage low-band recall moves (or is correctly shown to not move) with paired bootstrap CIs; the serving default remains defended by measurement, not by inertia.

### P1-4  -  Dead Entrypoint Correction | Status: VERIFIED (rode with P0-4; `Makefile`+`AGENTS.md` name `app.api.app:app`, asserted by `test_entrypoint_addresses_are_coherent`; live `up -d db` + uvicorn path exercised during the P0-4 deploy)

- **Dimension:** Backend/API + operational usability (§3.11, §3.20).
- **Current evidenced state:** `Makefile:16-18` `dev` runs `uv run uvicorn app.main:app --reload` but `app/main.py` does not exist; runnable is `app.api.app:app` (`Makefile:76-77` `serve`). `AGENTS.md:6` repeats `app.main:app`. `SPEC.md §2.2` pre-build `app/**` empty snapshot stale.
- **Benchmark comparator:** All five document one runnable entrypoint that works from a clean checkout.
- **Practical significance:** First command a reviewer runs fails after the environment verified  -  undermines the reproducibility story that is otherwise the strongest asset.
- **WHAT TO DO:** Eliminate the stale `app.main:app` address (`Makefile` `dev` target + `AGENTS.md` still reference it; `app/main.py` does not exist; runnable is `app.api.app:app`).
- **QUALITY BAR:** One story. Either the alias exists or the docs are corrected  -  not both, not neither. No second dead path is introduced.
- **WHAT SUCCESS LOOKS LIKE:** `make dev` succeeds from a clean checkout; a test or `verify_setup` step asserts entrypoint coherence.

### P1-5  -  Human-Readable Citation Rendering (FR-14) | Status: VERIFIED (Migration 0006 backfilling authoritative titles and dates across 35/35 corpus docs, canonical metadata catalog in app/ingest/metadata.py, Passage model & Retrieved enriched with title & published_date, authenticated GET /v1/documents/{document_id} resolution endpoint, demo UI rendering, tests in tests/test_citation_rendering.py 7/7 passing, ADR-0018)

- **Dimension:** Grounding/citations (§3.8) + chunking/metadata (§3.3).
- **Current evidenced state:** Migration 0006 backfilled authoritative titles and published dates for all 35 documents in PostgreSQL (`documents` table); `app/ingest/metadata.py` defines `CANONICAL_DOCUMENT_METADATA`; `app/ingest/source.py` and `app/ingest/store.py` preserve titles and dates across crawls; `Retrieved` and `Passage` models expose `title` and `published_date`; `GET /v1/documents/{document_id}` resolves complete document metadata and version lineage; demo UI hit cards render titles and dates.
- **Benchmark comparator:** Matches RAGFlow document aggregation and Onyx hyperlink processors.
- **Practical significance:** Compliance analysts can immediately identify cited circulars and publication dates without guessing or dereferencing chunk IDs.
- **WHAT TO DO:** Close the FR-14 gap where `title`/`published_date` are NULL for the current corpus, so citations render as more than `chunk_id`.
- **QUALITY BAR:** Metadata is populated from authoritative source (not hallucinated), nullable correctly remains nullable where unknown, and provenance still emits the full retrieval config. Existing `chunk_id`+span citations remain stable.
- **WHAT SUCCESS LOOKS LIKE:** `Passage` and `GET /v1/documents/{id}` return a human-readable header (title + date + canonical URL) for the current corpus; a reviewer can open the source without guessing which circular it is.

---

## P2  -  Conditional / specialized (build only if product direction justifies it)

Do not build for breadth. Each requires a failing query class on the grown corpus that cannot be solved by P0-1…P1-3  -  not "benchmark X has it."

| ID | Capability | Tradeoff (respecting deliberate narrowness) | Status |
|---|---|---|---|
| P2-1 | Multi-vector-DB adapter (Dify 30, FastGPT 5, RAGFlow 8 engines) | Single pgvector stack is a correct one-system-well tradeoff for a pinned public demonstrator; provider matrix dilutes retrieval-science signal. | TODO (deferred) |
| P2-2 | Knowledge-graph / community retrieval (RAGFlow `graph/`, LightRAG dual-level) | Entity-graph traversal is niche for paragraph Q/A circular-bounded regulator text. | TODO (deferred) |
| P2-3 | Agentic loop / workspace RBAC / artifact rendering / sandbox harness | Product breadth, premature until generation exists; one tight mode beats thin platform clone. | TODO (deferred) |
| P2-4 | Deep doc parsing zoo (MinerU/Docling/PaddleOCR/SOM/TCADP, table/TOC, vision figures) | pypdf+trafilatura succeeds 20/20 on current corpus; OCR fallback only if scanned/image PDFs arrive. | TODO (deferred) |
| P2-5 | Ingestion-scale harness (rate-limit + shrink retry, tokenization cache, 438-file task machine) | NFR-8 idempotency satisfied at 21 docs; harness without load is architecture without a problem. | TODO (deferred) |

Explicitly not required (assessment §7.2): guessed hosted-model IDs (`config/models.json` BLOCKED is correct), multi-user RBAC for a public single-tenant corpus (SPEC OUT-4), Langfuse/tracing service for a single-process API, wider embedding dims (ADR-0002 one-way door), remote CI badge before a remote exists.

---

## Dependencies

- P0-3 (scale) → rerank becomes measurable; P1-3 expansion is uninterpretable until low-band n grows.
- P0-4 (deploy artifact) → reviewability of all later tasks; CI `deploy-smoke` or verify log proves each later task still serves.
- P0-2 (refresh) → P0-5 (invalidation) becomes observable; invalidation test needs a supersession to exercise.
- P0-1 (generator) → needs P0-3 scale for a held-out split and P1-1 audit log for answer-level forensics.
- P1-5 (title/date) → cheapest after P0-3 growth (metadata populated once for the larger manifest).
- P1-4 (entrypoint) → no dependency; may ride with P0-4 since both touch `Makefile`/entrypoints and `verify_setup`.

---

## Evidence rule (applies to every task)

Code + tests + docs in the same commit series. `make verify-setup` green (or explicitly BLOCKED with named external input). Every claimed number has its raw artifact (`evals/reports/<ts>/results.json`, `evals/bench/<ts>/bench.json`, `loadtests/reports/<ts>/summary.json`, `docs/security/sbom.cdx.json`, `evals/mutation/latest.json`). Gate evidence committed where required (baselines via `make eval-baseline`, SBOM via `make audit-deps`, bench via `make bench`). Partial work marked partial in this file and in `README.md` Limitations.
