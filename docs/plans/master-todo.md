# DocScout — Master TODO (transformation to production-grade operational RAG service)

- **Baseline:** `69021ef2a6cee2041e9f39690162fc9b5de9c0b6` (master, 2026-10-09T18:24:51Z), 423 tracked files, 56 commits (+10 commits above `32b4271`), 6 migrations, 9 new ADRs (0010–0018).
- **Benchmark revisions (2026-10-08 SHAs):** RAGFlow `ef150bc2`, Onyx `f858083d`, Dify `2b65f0e8`, FastGPT `2ae3c721`, Khoj `ae229ca8`.
- **Corpus / gold at baseline:** 35 RBI/SEBI documents (34 live + 1 synthetic canary) → 230 chunks → 399 citations → 425 gold items v2.0.0 (365 answerable + 60 unanswerable, 14.1% unanswerable share, 12 multi-hop, 3 canaries). Serving: `POST /v1/search` + `POST /v1/answer` + `POST /v1/chat` (deterministic local generator behind passages), `GET /v1/documents/{id}`, `GET /healthz` (liveness), `GET /readyz` (readiness + freshness), `GET /metrics` (Prometheus), `GET /` demo, `GET /docs`.
- **Remote CI Health at baseline:** Actions run `37933392448` on `69021ef` is **RED** — `quality: failure (pytest on CRLF/LF metadata digest)`, `eval-gate: failure (regression gate on CRLF/LF baseline digest mismatch)`, `deploy-smoke: failure (KeyError: 'corpus_chunks' and 170-era assertion on /healthz)`, `secrets: success`, `supply-chain: success` (audit source: `docscout_gapanalysis_20261009.md` / GitHub Actions run `37933392448`). Because `VERIFIED = gates green + evidence artifact committed`, all previous P0/P1 verification claims are unverified at HEAD until P0-REPAIR achieves green CI.
- **Method for this file:** every item restated from `docscout_gapanalysis_20261009.md` and `do not commit!/docscout_assessment.md` §5 (citing file:line evidence at the pinned baseline). No implementation approach is prescribed here — only WHAT / QUALITY BAR / SUCCESS.
- **Status vocabulary:** `TODO` / `TODO (forced)` / `PLANNED` / `IN_PROGRESS` / `DONE` / `VERIFIED` (`VERIFIED` = gates green + evidence artifact committed).
- **Execution rule:** strictly one task at a time, highest remaining P0-REPAIR → P1-GUARD → P2-1 → P2-2 → P2-3 → P2-4 → P2-5 → P2-GUARD. Update status after each task.

---

## 0. Existing strengths that must not regress (§10.1, load-bearing)

These are verified at baseline and every task must keep them green. Regression here is a failure even if the new task passes.

| # | Strength | Evidence anchor (baseline) |
|---|---|---|
| S-1 | Citation correctness via uuid5 + FR-7 re-derive | `app/ingest/ids.py` (uuid5 `4ffde409…`, `sha256:char_start:char_end`), `app/ingest/chunk.py::verify_offsets`, `app/ingest/pipeline.py::verify_stored_chunks`, `migrations/0002_chunk_id_content_derived.up.sql` (drops uuidv7 default), M4 verify `230/230` |
| S-2 | Invisible-codepoint hygiene | `app/ingest/clean.py::blank_invisible` (Cf/Co/Cs, length-preserving, re-checked), `find_invisible`, audit G1 4→0 |
| S-3 | Leakage-aware measurement | `app/evals/runner.py::_leakage_bands` (fixed cuts 0–0.5/0.5–0.8/≥0.8), victim 0.733 vs random 0.094 (7.8×), low band n=54 reported at 35 docs / 425 gold |
| S-4 | Paired bootstrap + McNemar on every comparison | `app/evals/stats.py::paired_bootstrap` (10k, seed 0) + `mcnemar_counts`, `runner.py::_comparisons` |
| S-5 | Gate with noise floor | `app/evals/gate.py::check_regression` (1pp vs mean-of-3, `_DELTA_PRECISION=6`) + `noise_floor` (MDE ≤ 1.0pp reported beside verdict at 425 gold) |
| S-6 | Reproducibility trifecta | `corpus/raw/` tracked + `source.py::iter_manifest_documents` re-hash, triple-pin pgvector 0.8.6 guarded by `tests/test_config_coherence.py`, `uv sync --frozen` 169-lock, `scripts/bootstrap.sh` idempotent |
| S-7 | Observability single-service | `app/observability.py::configure_logging` (+ `_redact_sensitive` processor), `app/api/app.py::correlate_and_log` (one line, X-Request-ID echo), `app/api/metrics.py` (7 metrics, bounded labels, buckets incl. 3s SLO) |
| S-8 | Decision hygiene | 18 ADRs in `docs/decisions/` each with Rejected alternatives + `docs/decisions/evidence/`, U-1 withdrawal enforced by `tests/test_rescope.py`, `docs/AUDIT-2026-10-02.md` DONE vs ABSENT honesty |
| S-9 | Defect-found-fixed-proven pattern | G23 (10/10 superseded served → filtered in both arms, `tests/test_supersession.py`), G1 (U+F0E0 → blank → 0), G7 (0.8.2 vs 0.8.6 → coherence test), P0-5 (cache invalidation on supersession), P1-1 (query hash privacy) |
| S-10 | Liveness vs readiness operational split | `GET /healthz` 0 DB I/O process liveness vs `GET /readyz` traffic readiness with DB pool & freshness budget checks (P0-5, ADR-0014) |
| S-11 | Authoritative citation metadata preservation | `documents` table titles & dates populated via migration 0006, canonical metadata catalog in `app/ingest/metadata.py`, authenticated `GET /v1/documents/{id}` resolution (P1-5, ADR-0018) |
| S-12 | Cross-platform digest & line-ending invariance | Canonical LF normalized across git (`.gitattributes`) and Python hashing invariants so metadata and baseline digests match on Linux, Windows, and macOS |

Gates that guard S-1…S-12: `ruff check + ruff format --check`, `mypy` strict (`python_version 3.12`, `warn_unused_ignores`), 11 pre-commit hooks, 5 CI jobs (`quality`, `secrets`, `supply-chain`, `eval-gate`, `deploy-smoke`), `make verify-setup` V1–V17, `make test`, `make eval`, `make eval-gate`, `make bench`, `make audit-deps`, `make mutation` (scoped to `scorers.py`/`stats.py`).

---

## P0 — Blocking operational-retrieval maturity (build in this order)

Order rationale (assessment §5): P0-REPAIR first (restore green CI gate coherence) → P0-4 (unblocks reviewability) → P0-1 (capability ceiling) → P0-3 (makes tuning measurable) → P0-2 (freshness truth) → P0-5 (correctness fix triggered by P0-2).

### P0-REPAIR — Evidence & Gate Coherence | Status: IN_PROGRESS

- **Dimension:** Verification integrity, CI gate health, and cross-platform artifact determinism (§3.9, §3.16).
- **Current evidenced state:** Actions run `37933392448` on `69021ef` is RED across three jobs: `quality` (fails on `test_metadata_matches_the_committed_file` asserting LF digest `1a640cce...` vs committed CRLF digest `ea148e32...`), `eval-gate` (fails on invariant check `gold set 2.0.0 changed content without a version bump` and `corpus manifest changed since the last baseline` due to CRLF digests `ea148e32...` and `7fad4b6e...` in `20261009T063630Z.json` vs LF digests in Linux runner), and `deploy-smoke` (fails on `KeyError: 'corpus_chunks'` from 170-era `/healthz` assertion after P0-5 liveness/readiness split). `secrets` and `supply-chain` are green.
- **Inputs:** `evals/gold/v1/{gold.jsonl,metadata.json}`, `corpus/raw/manifest.json`, `evals/baselines/20261009T063630Z.json`, `evals/reports/*/results.json`, `.github/workflows/ci.yml:deploy-smoke`, `app/evals/{goldset,runner,gate}.py`, `tests/test_goldset.py`, `tests/test_api_answer.py`, `tests/test_gate.py`, `docs/decisions/0012-corpus-and-gold-scale-beyond-saturation.md`, `docscout_gapanalysis_20261009.md`.
- **Quality bar:** No digest is hand-edited without re-deriving it from the file it describes. Canonical LF line-endings enforced cross-platform via `.gitattributes` and Python hashing invariants. Windows-path `report_dir: evals\\reports\\...` normalized to POSIX. Every number re-claimed has its raw `results.json`/`report.md`/`bench.json` committed. `origin/master` after this task is bisectably green.
- **WHAT SUCCESS LOOKS LIKE:**
  1. `python3 -c "import hashlib,json,pathlib; assert hashlib.sha256(pathlib.Path('evals/gold/v1/gold.jsonl').read_bytes()).hexdigest()==json.load(open('evals/gold/v1/metadata.json'))['sha256_of_gold_jsonl']"` passes on Linux and Windows; same for `corpus/raw/manifest.json` vs `metadata.corpus_manifest_digest`.
  2. `pytest tests/test_goldset.py::test_metadata_matches_the_committed_file -q` passes locally and in CI. Full pytest suite passes.
  3. `evals/baselines/20261009T063630Z.json` or superseding baseline reflects true canonical digests (`1a640cce...` for gold, `78f8f08b...` for manifest), POSIX `report_dir`, and `evals/reports/20261009T063624Z/` committed with matching provenance (`chunks==230`, `goldset==425`, `items_scored==365`). `app/evals/gate.py` passes with MDE ≤ 1.0pp.
  4. `.github/workflows/ci.yml` `deploy-smoke` checks `/healthz` (liveness: `status==ok`) and `/readyz` (readiness: `corpus_chunks==230`), eliminating the `KeyError` and 170-era hardcoded assumptions.
  5. CI run on pushed commit is all GREEN (`quality`, `secrets`, `supply-chain`, `eval-gate`, `deploy-smoke`).
  6. P0 and P1 task statuses re-verified against green CI run.


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

## P1 — Expected operational maturity (after P0, any defensible order)

### P1-GUARD — P0/P1 Non-Regression | Status: PLANNED

- **Dimension:** Non-regression and scale-hardening (§3.9, §10.1).
- **Current evidenced state:** S-1…S-12 load-bearing strengths and P1 contracts verified at 35 docs / 230 chunks / 425 gold scale; hard-coded 170-era assumptions in tests and fixtures (e.g. `tests/test_api_answer.py:72`, `tests/test_gate.py`) audited and cleaned.
- **Quality bar:** No feature re-built for the sake of touching it. Only defects found by inspection or failing gates are fixed. All tests and verification gates remain green without weakening assertions.
- **WHAT SUCCESS LOOKS LIKE:** `make verify-setup` V1–V17 green; no new `TODO` escapes P0-REPAIR; master TODO carries a verified non-regression entry.

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

## P2 — Forced operational capabilities (build in strict order: P2-1 → P2-2 → P2-3 → P2-4 → P2-5 → P2-GUARD)

Each P2 capability is now defensible and forced by concrete failing query classes exhibited on the grown 35-doc / 230-chunk / 425-gold regulatory corpus.

| ID | Capability | Failing Query Class / Operational Gap | Status |
|---|---|---|---|
| P2-1 | Retrieval-Port Adapter | **Operability gap**: Swapping embedding model (`MODEL_ID`/`EMBEDDING_DIM` ADR-0002 one-way door) or vector index currently forces changes across 6+ files in `app/retrieval/` and `app/ingest/` with zero port abstraction. | TODO (forced) |
| P2-2 | Lightweight Knowledge-Graph over Provisions | **12 multi-hop items** in `evals/gold/v1`: Cross-circular amendment joins (e.g., KYC circular updating Digital Lending clause) where `multi-hop MRR ≈ 0.55–0.65` severely lags extractive (0.85) because grouped citation scoring cannot join provisions across documents. | TODO (forced) |
| P2-3 | Tight Agentic Research Loop + Minimal Workspace | **Complex compliance synthesis questions**: Multi-aspect regulatory comparisons (e.g., compromise-settlement eligibility before and after Green Deposits circulars with condition tables) where single-pass k=5 retrieval fails citation recall and judge completeness. | TODO (forced) |
| P2-4 | Pluggable Extraction Chain with Docling/MinerU Fallback | **Scanned annexures and merged tables**: Real SEBI circulars with image/scanned annexes where `pypdf` yields low text fidelity / table collapse (`recall` on scanned fixture drops to near-zero despite 0.96 headline). | TODO (forced) |
| P2-5 | Ingestion-Scale Harness | **Scale throughput & latency bottleneck**: Ingestion loop lacks back-pressure against regulator 429s, lacks shrink-retry on token ceiling, lacks tokenization cache, and linear re-embedding slows corpus-refresh beyond SLA. | TODO (forced) |
| P2-GUARD | P2 Non-Regression & Evidence Close-out | **Verification integrity**: Ensure every P2 lands without regressing S-1…S-12, all new modes are A/B-measured with paired bootstrap + McNemar, no architectural scaffolding, and evidence artifacts committed. | TODO (forced) |

### P2-1 — Retrieval-Port Adapter (one seam, not a matrix) | Status: TODO (forced)

- **Failing query class / operability gap:** Swapping the embedding model or adding a second vector store forces changes across 6+ files (`app/retrieval/{dense,lexical,fusion,search}.py`, `app/ingest/embed.py`) with no seam.
- **WHAT TO DO:** Introduce a retrieval-port abstraction (`RetrievalPort` / `VectorStore`) so pgvector is an implementation, not the interface.
- **QUALITY BAR:** Interface over implementation. Single production adapter (`pgvector`); `Retriever` depends on port, not `psycopg`/`pgvector` SQL directly; `tests/test_retrieval_port.py` proves `hybrid-rrf` via port == direct SQL within rounding; `Δ recall@5 ≤ 0.002` on 365 items; ADR-0019 records "single pgvector today, port exists for one-system-well" with rejected alternatives.
- **WHAT SUCCESS LOOKS LIKE:** Port protocol committed, `app/retrieval/search.py` wired to port, config coherence test verifies registry, zero metric regression on 365 items.

### P2-2 — Lightweight Knowledge-Graph over Regulatory Provisions | Status: TODO (forced)

- **Failing query class:** The 12 multi-hop items in `evals/gold/v1` (cross-document provision amendments where `multi-hop MRR ≈ 0.55–0.65` vs `extractive 0.85`).
- **WHAT TO DO:** Minimal entity graph over provisions (document, section/§, provision; edges: cites, amends, supersedes, implements) extracted from parsed `§` markers, plus graph-assisted hybrid retrieval.
- **QUALITY BAR:** Migration `0007_knowledge_graph` stores nodes/edges with provenance (`source_doc`, `char_start/char_end`); no ungrounded LLM graph invention; retrieval joins graph expansion with hybrid fusion; fallback to plain hybrid when graph has no hit.
- **WHAT SUCCESS LOOKS LIKE:** Graph schema populated for 35 docs, `app/retrieval/graph.py` exists, `mode=graph-hybrid` evaluated in A/B, multi-hop recall@5 moves with paired bootstrap CI that excludes zero (or defended serving default), ADR-0020 committed.

### P2-3 — Tight Agentic Research Loop + Minimal Workspace | Status: TODO (forced)

- **Failing query class:** Complex analyst synthesis questions requiring multi-aspect comparisons (e.g. compromise-settlement eligibility before vs after Green Deposits circular with condition table) where single-pass k=5 fails answer completeness.
- **WHAT TO DO:** Deterministic agentic research loop (`planner → retrieve → synthesize → critique → final`) producing citation-grounded comparison artifacts, plus minimal workspace persistence.
- **QUALITY BAR:** Determinism and grounding over cleverness. Planner seeded; every claim cites a passage; corpus text is data, never instructions (canary 100% defended); `POST /v1/research` returns auditable `steps[]`; workspace persistence.
- **WHAT SUCCESS LOOKS LIKE:** `POST /v1/research` operational, double-labelled calibration report (30-50 research tasks, agreement, abstention on unanswerable prompts), injection canary 100% defended, ADR-0021 committed.

### P2-4 — Pluggable Extraction Chain with Docling/MinerU Fallback | Status: TODO (forced)

- **Failing query class:** Real SEBI master circulars with scanned annexures, merged-cell tables, or figures where `pypdf` yields low text fidelity / table collapse (`recall` on scanned fixture near-zero).
- **WHAT TO DO:** Pluggable extraction chain: fast-path `pypdf` for clean documents + deep parser fallback (Docling or MinerU) triggered when fidelity signals indicate low quality.
- **QUALITY BAR:** Honest fallback, not a zoo. Clean docs retain fast path (zero regression); fallback preserves char offsets for FR-7 re-derivation; tables linearized with grounded spans; scanned-image fixture committed.
- **WHAT SUCCESS LOOKS LIKE:** `app/ingest/extract_chain.py` with fallback, `DOCSCOUT_EXTRACTOR` flag, tests proving scanned fixture recall improvement while clean fixture recall is unchanged, ADR-0022 committed.

### P2-5 — Ingestion-Scale Harness | Status: TODO (forced)

- **Failing query class:** Ingest throughput/latency scaling curve at 100+ documents; unthrottled loop lacks back-pressure against regulator 429s, lacks shrink-retry on token ceiling, lacks tokenization cache.
- **WHAT TO DO:** Token-aware rate limiter, shrink-retry on 429/context length, bounded LRU tokenization cache, ingest task machine with state persistence.
- **QUALITY BAR:** NFR-8 idempotency preserved; `EXPLAIN ANALYZE` on dense index at scale documented; simulated 200-doc ingest benchmarks throughput at 1/4/8 concurrency; p95 at 35 docs unregressed.
- **WHAT SUCCESS LOOKS LIKE:** `app/ingest/harness.py` committed, benchmark report in `loadtests/reports/<ts>/ingest-scale.json`, ADR-0023 committed.

### P2-GUARD — P2 Non-Regression & Evidence Close-out | Status: TODO (forced)

- **WHAT TO DO:** Ensure every P2 lands without regressing S-1…S-12, all new modes are A/B-measured with paired bootstrap + McNemar, no architectural scaffolding, documentation & report close-out.
- **QUALITY BAR:** Full verification suite green; every claimed number backed by committed artifact; `README.md`, `CHANGELOG.md`, `SPEC.md` current.
- **WHAT SUCCESS LOOKS LIKE:** `make verify-setup` green, full test suite green, `make eval-gate` PASS (MDE ≤ 1.0pp), bisectably green remote push.


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
