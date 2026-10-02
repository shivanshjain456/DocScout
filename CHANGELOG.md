# Changelog

All notable changes to DocScout are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **`GET /metrics`: Prometheus instrumentation** (audit G4). RED — rate, errors, duration —
  plus the two signals that explain this service's latency: cache hit ratio and per-mode
  retrieval time, alongside in-flight requests, rate-limit rejections and the retrievable
  chunk count.
  Cardinality was designed, not discovered: `route` is the **matched route template**, so
  two scanner probes to `/wp-admin` and `/.env` collapse into one `route="unmatched"`
  series instead of creating one each; status codes are kept at full granularity because
  the enumeration is small and known, and collapsing to `4xx` would hide a rate-limited
  caller behind an unauthenticated one; nothing per-request is a label, so query text, API
  keys and request ids stay in the structured log, which carries the request id for
  joining. 114 series total on a live scrape.
  Histogram buckets come from this service's own measurements rather than a default ladder
  — dense below 100 ms where the distribution sits (cache hit p95 2.11 ms, cold p95
  48.11 ms) with an exact boundary at the **3 s NFR-1 budget**, so SLO compliance is a
  bucket ratio rather than an interpolation.
  `prometheus-client` is declared in `pyproject.toml` and locked; `uv sync --frozen` still
  resolves. 14 tests, including one asserting the scanner-probe collapse and one asserting
  no label value looks like per-request data.

### Changed
- The shared serving-API test fixtures (`client`, the key constants, `auth()`, the
  rate-limiter reset) moved from `tests/test_api.py` into `tests/conftest.py`, now that two
  suites drive the API. Importing a fixture across test modules shadows the parameter of
  the same name in every test that uses it — ruff flagged it 14 times.
- **`app/observability.py`: structured logging and request correlation** (audit G2 + G3).
  There was no logging configuration anywhere in the repository: six `logger.*` calls wrote
  to an unconfigured root logger, so every INFO record — including every access line — was
  silently discarded. Now one structlog pipeline renders *all* records, including stdlib
  ones from uvicorn and psycopg, so a process emits one format instead of two that drift.
  JSON off a TTY, human-readable on one, `DOCSCOUT_LOG_JSON` to override,
  `DOCSCOUT_LOG_LEVEL` for level.
  This uses the `structlog` dependency that was previously declared and imported nowhere,
  removing that supply-chain surface rather than adding a new one.
- **Credential redaction as a pipeline processor, not a convention.** Any event key that
  looks like a credential has its *string* value replaced before rendering, so one
  forgetful call site cannot leak a key. Verified against the running service: the
  configured API key appears **0 times** in the logs.
- **Request correlation.** Every request binds a `request_id` contextvar that appears on
  every record emitted while handling it — ours and uvicorn's — and is echoed as
  `X-Request-ID` on every response including errors. An inbound id is honoured only if it
  is short and free of control characters, because it is attacker-controlled text that
  lands in every log line. The 500 handler now reuses that id, so the reference a caller is
  given is the string that appears in the logs. One access line per request, after the
  fact, carrying status and duration.
- 30 tests in `tests/test_observability.py` plus 4 API-level correlation tests, asserting on
  emitted records rather than on configuration — the failure that mattered was "nothing came
  out", which no configuration-shaped assertion would have caught.
- **`docs/AUDIT-2026-10-02.md`** — a production-readiness audit against researched recruiter
  and senior-engineer expectations (10 cited sources, accessed 2026-10-02, with the
  disagreements between them resolved explicitly), and a prioritised 27-item gap checklist.
  Each item carries the expectation, verified current-state evidence, the exact gap,
  hiring-signal impact, priority, dependencies, acceptance criteria and a verification
  method.

### Fixed
- **`docker-compose.yml` pinned a pgvector version no published number was measured on.**
  It specified `pgvector/pgvector:0.8.2-pg18` while `scripts/dev_db_native.sh` and the CI
  job both provision **0.8.6** — so a reviewer following the compose path got a different
  extension version than every baseline in this repository. The README compounded it by
  stating "There is no `docker compose up`" about a file tracked at the repo root.
  Compose is now pinned to `0.8.6-pg18-trixie`, identical to CI, and documented as the
  supported alternative to the native script. `tests/test_config_coherence.py` (7 tests)
  fails the build if the three provisioning paths ever disagree again, if the tag stops
  being fully qualified, or if compose declares a service nothing in `app/` connects to.
  The unused Redis service is removed: `REDIS_URL` remains in `.env.example` for a future
  multi-worker deployment, but starting a container nothing talks to is scaffolding
  presented as architecture. Audit item G7.
- **Superseded document versions were still retrievable and would be served as current.**
  The schema has modelled `is_current` since migration 0001, `store.py` demotes the
  previous version correctly on supersession, and FR-4 keeps the old rows because the
  application role holds no DELETE — but **no retrieval path filtered on it**. Marking one
  version superseded in a rolled-back transaction left **all ten of its chunks in the top
  ten**. For a tool over circulars that are amended and withdrawn as a matter of routine,
  serving superseded regulatory text as though in force is the worst failure available.
  Latent only because every ingested document currently has exactly one version.
  The dense arm, the BM25 arm and metadata hydration now all join `document_versions` and
  filter on `is_current`. The lexical arm excludes at **index build** rather than after
  scoring: superseded terms left in the table distort document frequency and average
  document length, changing the score of every *current* chunk. Retention is unaffected and
  a test asserts both halves. 6 tests; 5 of them fail against the unfiltered paths.
  Eval gate PASS with metrics unchanged, as expected for a single-version corpus.
  Amends ADR-0004. Audit item G23, re-prioritised from P2 after research identified data
  staleness as the failure production RAG teams most often skip.
- **Third-party INFO noise buried the signal.** Loading the encoder emitted ~30 `httpx`
  lines resolving files on the Hugging Face hub, around the one `api.ready` line that
  matters. Library loggers are quieted to WARNING; measured 30 → 0 at startup.
- **The redactor destroyed an operational signal.** Matching on key name alone turned
  `api_keys=1` — the *count* of configured keys, logged at startup — into "[redacted]".
  A credential is a string; a count, a flag and a duration are not. Redaction now applies
  to string and bytes values only.
- **A latent test-isolation defect, surfaced by the new tests.**
  `test_unhandled_errors_do_not_leak_internals` constructed a second `TestClient` over the
  same application object; exiting its lifespan closed the connection pool the
  module-scoped client still held, so every test ordered after it failed with `PoolClosed`.
  Nothing ran after it before, so it had never shown. It now reuses the module client.
- **Invisible and private-use characters survived ingestion into embeddings and citations**
  (OWASP LLM09). A character-level scan of all 170 stored chunks found four occurrences of
  **U+F0E0** — the Wingdings breadcrumb arrow in SEBI circulars, "under the link *Legal →
  Circulars*" — embedded into the vector, tokenised, served in API responses, and present
  in **two chunks the gold set cites**. `clean.py` enumerated Unicode *ranges* and so could
  only ever catch what someone had thought of; it now blanks by **category** (Cf format,
  Co private-use, Cs surrogate), which is what the rule actually is. Cc is excluded on
  purpose — newline and tab are structure.
  The substitution stays one-space-per-character, so ADR-0003's offset contract holds.
  Verified across a full rebuild: **170/170 chunk ids unchanged, all offsets identical,
  72/72 gold citations resolvable, FR-7 passing, eval gate PASS** (recall and nDCG
  unchanged, MRR +0.03pp). `find_invisible()` reports what was removed per document, so the
  removal is auditable rather than silent. 9 new tests; the end-to-end one reads the live
  database and failed against it before the fix.
- **U-1 is closed: the calibrated-judge claim is formally withdrawn** (`EVAL_PROTOCOL.md`
  §4.2, outcome (b)). M4's exit criterion 5 said carrying this past M4 was not permitted; it
  had been carried past M4 and M5. Two independent reasons, either sufficient: no paid API
  credentials are available and none will be acquired, and — the stronger one — ADR-0008
  serves retrieved evidence rather than generated prose, so faithfulness has **no subject**.
  With no generated claim the honest value is *undefined*, not 1.0. The optional local judge
  the protocol permits was declined for the same reason: it would have nothing to evaluate.
- **`tests/test_rescope.py` (52 cases) enforces the withdrawal mechanically.** A decision
  recorded only in prose decays, and the pressure to publish a faithfulness number is real —
  it is the metric a reader expects and it would take one line to invent. The build now fails
  if a withdrawn metric appears as a published value in the README, SPEC, QUALITY_BAR,
  MILESTONES, ARCHITECTURE, EVAL_PROTOCOL, any ADR or any verification story; if a judge or
  generator role is marked verified or CI-approved without calibration evidence; or if a
  committed eval report claims a judge ran. Twelve of those cases test the detector itself
  against text that must trip it and text that must not, because a scanner that matches
  nothing passes forever and protects nothing.
- `config/models.json` carries a `_u1_rescope` block, so the decision is discoverable from the
  configuration and not only from the protocol.

### Changed
- **`QUALITY_BAR.md` §5 reconciled against measured reality.** The table still said "SPECIFIED,
  not yet enforceable" and described blockers that had since cleared. Now: Q-12 **ENFORCED**
  (`make eval-gate`, drilled to exit 1), Q-17 **MEASURED and PASSING** (48.11 ms p95 against a
  3 s budget — 1.6 % of it), Q-18 **MET** (153 items, 14.4 % unanswerable, 3 canaries),
  Q-13/Q-14/Q-15 **WITHDRAWN** with the replacement measurement named beside each, and Q-16
  **NOT APPLICABLE BY DESIGN** — no model reads retrieved text, so there is nothing to inject
  into, and the gate reactivates the day a generator lands.
- **`SPEC.md` FR-28 amended.** It required CI to fail on a >1 pp regression in faithfulness,
  context precision and citation precision — all three now withdrawn — and recorded the CI job
  as `if: false`, which stopped being true when the gate landed. The requirement's intent is
  unchanged; the gate now protects the deterministic metrics that exist: recall@5, MRR and
  nDCG@5.
- README, `ARCHITECTURE.md`, `MILESTONES.md` and the verification story now say **withdrawn**
  rather than **blocked**. The distinction is the whole point: blocked implies a queue.
- **M4 is complete.** All five exit criteria are met or formally resolved.
- **`app/retrieval/rerank.py` and ADR-0009: the cross-encoder rerank stage — built, measured,
  and shipped disabled.** `ARCHITECTURE.md` had specified this stage since M1 and it did not
  exist; it now does, with explicit `max_length`, deterministic tie-breaking toward the
  incoming fusion order, a score/candidate length check, and `rerank_top_n >= k_final`
  validation. Measured over the full gold set: **+2.3pp recall@1 (three items out of 131) for
  30x to 160x the p95**, with a bootstrap CI spanning zero. At top-20 and top-50 it also drops
  recall@10 from 1.000 to 0.992 by promoting deep candidates over evidence fusion had already
  placed correctly. `SERVING_CONFIG.rerank` stays `False`. Closes the rerank half of U-10 and
  the §8.1 rerank ablation.
- `scripts/experiments/u10_rerank_ablation.py` with raw output under `evals/experiments/`, and
  `tests/test_rerank.py` (12 cases; the 4 that load the real model are marked `slow` and run by
  default). A registered `slow` pytest marker.

### Fixed
- **A documented "verified" cost was wrong by about twenty times, and the Phase 0 gate it
  passed should have failed.** `ARCHITECTURE.md` recorded the reranker at **4.56 ms/pair**,
  measured on short synthetic sentences. On real corpus chunks (946 chars / 267 tokens mean)
  the same model on the same hardware costs **102–126 ms/pair**, because transformer cost
  scales with sequence length. `SETUP_REPORT.md` §10.2 applied a ">50 ms/pair ⇒ downgrade"
  threshold and recorded "PASS with wide margin"; the honest result is **FAIL by 2x**. Its
  prediction that reranking 50 candidates costs ≈230 ms is really ≈6.3 s.
  Corrected in `ARCHITECTURE.md` (§3, the pipeline diagram and the capability table),
  `EVAL_PROTOCOL.md` (E-16), `ADR-0003` (which cited the reranker as a mitigation that is not
  in the serving path), and `MILESTONES.md`. The signed `SETUP_REPORT.md` keeps its original
  numbers with a correction block beside them, because a point-in-time record should not be
  silently rewritten.
  **E-16 is now a rule rather than a fact**: every model cost must be quoted from a measurement
  on real corpus chunks. The project already applied exactly this reasoning to the embedder
  (112.4 sentences/s generic vs 6.9 chunks/s real) and had not carried it across to the
  reranker.
- **`app/api/`: the serving API — citation-grounded retrieval over HTTP.** `POST /v1/search`
  returns ranked passages carrying a stable `chunk_id`, source document, canonical URL and
  character span, so a citation can be checked against the original PDF. **No model
  generates text in the request path**, so the endpoint cannot hallucinate: every character
  of regulatory text in a response is a substring of a stored chunk, and a test re-reads
  each returned chunk from the database to prove it. Reasoning and the reversal condition
  are in **ADR-0008**.
- API-key authentication (`X-API-Key`), constant-time comparison, comma-separated keys for
  rotation, and a per-key sliding-window rate limit. Missing key configuration **stops
  startup** rather than defaulting to open. Errors return a correlation id, never a
  traceback or a connection string; the 422 handler strips Pydantic's `input` field so
  caller data is not reflected back.
- A self-contained demo page at `/` (no external asset of any kind — a test asserts it),
  plus `/docs` and an unauthenticated `/healthz` reporting readiness, cache counters and
  `single_process: true`.
- **`scripts/bench_api.py` and `make bench`: measured cost and latency.** Over HTTP with
  real gold-set questions on 2 vCPU / 1.9 GiB: cold p95 **51.43 ms**, warm p95 **3.16 ms**
  — caching is worth **16.3x on p95** (48.3 ms saved) — 37.0 q/s at concurrency 4, and
  **$0.000084 per 1,000 queries (~$0.08 per million)**. Raw output committed under
  `evals/bench/`. With no model in the request path that is the entire query cost.
- `make serve`. Bounded LRU+TTL caches with hit/miss counters (`app/api/cache.py`), and a
  configurable rate limit (`DOCSCOUT_RATE_LIMIT_PER_MINUTE`) with no value that disables it.
- `tests/test_api.py`: 35 cases weighted toward security — absent and wrong keys are
  indistinguishable, a rejected payload is not echoed, an internal exception leaks nothing,
  the demo page loads no third-party asset.

### Fixed
- **The Quickstart documented a setup that does not exist.** It instructed `docker compose
  up -d` against a compose file this project deliberately does not have, named pgvector
  0.8.2 where 0.8.6 is installed, and required Node 22 for a UI that was never built. It now
  documents the two scripts that actually work, measured at ~2 minutes from a bare machine.
- `SearchRequest.query` used `Field(strip_whitespace=True)`, which Pydantic v2 silently
  ignores. Queries were never stripped, so `"  rate  "` and `"rate"` were different cache
  keys and a repeat query reported a miss. Now `StringConstraints`.
- **ADR-0007 and the first verification story: a retrieval miss the harness caught.** Gold
  item g-038 scored zero recall at every cutoff while BM25 ranked the correct chunk **first**
  — RRF at k=60 fused lexical-rank-1 and dense-rank-41 into rank 14, outside the served depth.
  Rank-only fusion cannot express certainty: at k=60, rank 1 is worth only 1.66x rank 41, so
  broad agreement beats one arm's conviction. Fixed by reserving a seat for each arm's own top
  hit (`RetrievalConfig.anchor_arm_top1`, enabled on the new `app.retrieval.SERVING_CONFIG`),
  **not** by tuning the constant: a sweep over the full gold set showed `rrf_k=5` gains 1.15pp
  recall@5, which is 1.5 items with a CI spanning zero. Per-item over 131 items: **0 worse, 1
  better**. Recall@10 **0.9924 → 1.0000**, MRR 0.8240 → 0.8247. Four regression tests, two of
  which were verified to fail with the fix removed, and one deliberately inverted so the
  guarantee cannot become cargo cult. Story:
  `docs/verification/0001-g038-fusion-miss.md`.
- `scripts/experiments/u10_rrf_constant_sweep.py`: the RRF constant sweep behind ADR-0007,
  with raw output under `evals/experiments/`. Partially closes U-10 — the constant stays at
  the published default with measurements behind it; candidate depth and rerank depth remain
  open.
- **`app/evals/gate.py` and `make eval-gate`: the E-12 regression gate.** Fails the build
  when the serving configuration's recall, MRR or nDCG@5 drops more than 1pp against the mean
  of the last three accepted baselines (`evals/baselines/`, promoted explicitly with
  `make eval-baseline`). Drilled against a real 1.90pp degradation: exit 1. Invariants run
  first and fail hard — gold set mutated without a version bump, corpus manifest changed,
  or fewer items scored than the baseline — because a gold set that quietly shrinks to its
  easy items makes every metric improve. The gate publishes its own noise floor
  (3.24pp here) beside each verdict instead of widening the 1pp rule.
- **The corpus payloads are now tracked in git** (7.8 MB, 41 files). The manifest did not make
  them re-derivable: the corpus contains *withdrawn* circulars — gold item g-038 is about one —
  and `make eval` is only a reproduction command if `make ingest` runs offline. Verified by
  truncating the database and re-ingesting from tracked bytes alone: 21 documents, 170 chunks.
- **The `eval-gate` CI job**, pinned to `pgvector/pgvector:0.8.6-pg18-trixie` (the exact
  PostgreSQL 18.6 / pgvector 0.8.6 pairing used locally). Committed **unverified**: this
  repository has no remote, so the workflow has never run and no CI badge is claimed. The
  same commands are verified locally at `docs/setup/verify/m4-eval-gate.txt`.
- **A README `Limitations` section**, stating the leakage, the saturated corpus, the gate's
  noise floor, the absent generator and judge, and the missing badge.
- `tests/test_gate.py` (18 cases) and `tests/test_git_history.py` (7 cases).
- **`app/retrieval/`: the retrieval layer — a dense arm, a BM25 arm and RRF over both.**
  BM25 is scored over the lexemes Postgres already stores in `chunks.tsv`, parsed by
  `unnest(tsvector)`, so the scorer and the GIN index can never disagree about stemming.
  The three configurations are one code path, so the ablation is hybrid minus a step.
- **`app/evals/scorers.py`: deterministic retrieval metrics, run before any LLM judge.**
  Recall, hit rate, MRR and nDCG are computed over *quote groups* — disjunction within a
  group, conjunction across them — because ADR-0003's 150-char overlap puts a boundary
  quote in two chunks, and scoring the flat ID list charges a retriever 0.5 for a
  perfectly correct answer. 11 of 131 answerable items (8.4 %) are affected.
- **`app/evals/stats.py`: paired bootstrap CIs and discordant-pair counts**, so a
  difference is published with its uncertainty. This caught a real over-claim — see below.
- **`app/evals/runner.py` and `make eval`: the first baseline run**, writing
  `evals/reports/<UTC-ts>/{results.json,report.md}` with full E-14 provenance read from
  the artifacts at run time. The pinned baseline is committed, because E-13 says a metric
  that has no raw output does not exist.
- **ADR-0006 — hybrid retrieval, accepted on evidence that does not prove it.** The A/B
  put `bm25-only` on top (recall@5 0.970 vs hybrid 0.966 vs dense 0.947), and the honest
  reading is that **no pairwise difference's 95 % CI excludes zero**: BM25's lead over
  hybrid is one item out of 131. Worse, the gold set's questions were authored from the
  evidence quotes and share **73.3 %** of their terms with the chunk they point at versus
  **9.4 %** for a random chunk — a 7.8× handicap in the lexical arm's favour. Stratified by
  that overlap, BM25 is the **worst** of the three in the least-contaminated band (0.750 vs
  0.875). Hybrid is kept because it is never worst in any band, and the experiment that
  would overturn the decision is named: paraphrased query variants (**U-18**).
- `scripts/git_history.sh` and `.history/docscout.bundle`: git history persisted as a file
  in the working tree. This sandbox restores the tree but rolls `.git` back to a fixed
  baseline — observed twice, reflog included — which would truncate the project's commit
  history permanently. `bootstrap.sh` restores the bundle, fast-forward only.
- `app/rowtypes.py`: runtime-checked coercions for psycopg row values, so a column type
  change raises at the boundary instead of being silenced by a `cast`.
- `tests/test_retrieval.py` (16 cases) and `tests/test_scorers.py` (18 cases): fusion
  arithmetic and the group model are pinned against hand-computed values.
- **The gold set, `evals/gold/v1/gold.jsonl` — `goldset_version` 1.0.0.** 153 items over all
  21 corpus documents: 87 extractive, 40 numeric, 4 multi-hop, 22 unanswerable (14.4 %, floor
  10 %) and 3 injection canaries. The protocol floor is 120. 150 required citations over 72
  distinct chunks, 42.4 % of the corpus. Evidence: `docs/setup/verify/m3-goldset.txt`.
- **Items are authored against verbatim `evidence_quotes`, and citation IDs are derived from
  them**, not hand-written. Re-pinning after a chunking change is `make gold-pin`, and stale IDs
  fail `make gold-lint` and the test suite — `EVAL_PROTOCOL.md` E-7 turned from a note into a
  gate. Because ADR-0005 made chunk IDs content-derived, the whole gold set validates with **no
  database**; verified by stopping Postgres and linting clean.
- `app/evals/goldset.py`: loader, quote resolver, E-6 review pass and a linter enforcing every
  floor in `EVAL_PROTOCOL.md` §2. `make gold-lint`, `make gold-pin`, `make gold-review`,
  `make gold-stats`.
- `tests/test_goldset.py`: 23 cases. 15 point a deliberately broken item at the linter and
  assert the matching rule fires; 8 assert properties of the committed set, including that
  every citation still resolves and that the metadata claims no Cohen's κ.
- `scripts/dev_db_native.sh`: provisions Postgres 18 + pgvector natively where Docker is
  unavailable, by executing `infra/initdb/` rather than restating it.
- `migrations/0002_chunk_id_content_derived`, `app/ingest/ids.py`, `tests/test_ids.py` and
  `ADR-0005`.
- **`app/ingest/`: the corpus ingestion pipeline — the first DocScout feature code.**
  fetch → extract → guard → clean → chunk → embed → store, as a CLI (`make ingest`) and
  never an API route. Run against the live database: **21 documents, 170 chunks, 0
  failures, 41.0 s** on 2 vCPU. Evidence: `docs/setup/verify/m2-ingestion.txt` and the raw
  run reports under `docs/corpus/evidence/`.
- `make ingest`, `make ingest-dry`, `make ingest-status`, `make ingest-verify`. The last
  re-derives all 21 documents from their source PDFs and re-checks all 170 stored chunks'
  offsets against the database — 170/170.
- `tests/test_ingest.py`: 37 tests, each named for the requirement it proves, covering
  every M2 exit criterion. `tests/conftest.py` now holds the shared database fixtures.
- `tests/fixtures/sebi_detail_stub.html`, which reproduces the CORPUS_SPEC K-17 failure
  mode — a page that returns HTTP 200 and extracts 143 clean characters of navigation
  furniture while the circular's real text sits in an iframe.
- **Database schema (migration `0001_initial_schema`), applied to the live Postgres 18.4 /
  pgvector 0.8.2 instance.** `documents`, `document_versions` and `chunks`, with an HNSW index
  (`vector_cosine_ops`, `m = 16`, `ef_construction = 64`) on `chunks.embedding` and a GIN index on
  a generated `tsvector`. Primary keys use PostgreSQL 18's native `uuidv7()`. Every constraint
  carries an inline comment naming the FR or ADR it enforces, because a rule that lives only in
  prose silently stops being true.
- `scripts/migrate.py`: a plain-SQL migration runner (`status` / `up` / `down --to N`) with an
  advisory lock, one transaction per migration, SHA-256 drift detection that refuses to run when
  an applied file has been edited, and a `down` that will not run without an explicit `--to`. All
  four properties were exercised, not assumed. Exposed as `make migrate`, `make migrate-status`
  and `make migrate-down TO=N`.
- `tests/test_schema.py`: 19 tests, each named for the requirement it proves — FR-3, FR-4, FR-5,
  FR-7, FR-9, ADR-0002's dimension and token ceiling, and the least-privilege grants. Three
  constraints were additionally mutation-checked: dropping them inside a rolled-back transaction
  lets the previously rejected row insert, which proves the constraint is what rejects it.
- `ADR-0004`: binds the data model, the migration tooling, `uuidv7` keys and HNSW-over-IVFFlat.
- Evidence: `docs/setup/verify/m1-schema-migration.txt`.
- Project documentation set, each document readable alone and cross-referenced into one source of
  truth: `SPEC.md`, `SECURITY.md`, `docs/QUALITY_BAR.md`, `docs/MILESTONES.md`,
  `docs/architecture/ARCHITECTURE.md`, `docs/corpus/CORPUS_SPEC.md`, `docs/eval/EVAL_PROTOCOL.md`.
  Includes a shared status vocabulary (VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED) and
  a global Unresolved Register, U-1 … U-17.
- `scripts/bootstrap.sh`: pinned, idempotent, tiered (`core` / `full`) reconstruction of the
  Phase 0 toolchain, with a `--check` mode that installs nothing and exits non-zero on a gap.
- `ADR-0001`: re-initialise version control without fabricating the lost Phase 0 history, and make
  the environment reproducible by script.
- Verification evidence for the rebuild: `docs/setup/verify/m0-bootstrap-and-vcs.txt` and
  `docs/setup/verify/m0-verify-setup-rerun.txt`. The V1–V17 matrix was re-run for the first time
  since Phase 0 and reproduced **PASS=15 / FAIL=0 / BLOCKED=2** on a toolchain rebuilt entirely by
  `scripts/bootstrap.sh full`, with every version matching its Phase 0 pin.
- Primary-source `robots.txt` evidence for both corpus sources
  (`docs/setup/verify/robots-txt-evidence.txt`), partially closing Known issue K-16.
- Phase 0 environment: Docker Compose data layer (Postgres 18 + pgvector 0.8.2, Redis 7),
  uv-managed Python 3.12 environment, Node 22 / pnpm, k6, gitleaks, AWS CLI.
- Agent configuration: `AGENTS.md`, `CLAUDE.md`, six project skills, vendored Superpowers v6.4.2.
- Enforcement: pre-commit (ruff, mypy, gitleaks, large-file and private-key checks), Claude Code
  hooks (format-after-edit, dangerous-bash denylist, end-of-session typegate), CI skeleton.
- Security documentation: MCP server audit, skills audit, injection canary log, memory write log.
- Setup tooling: `scripts/mcp_probe.py`, `scripts/verify_corpus_fetch.py`, `scripts/verify_setup.sh`.

### Changed
- **`chunks.chunk_id` is content-derived and the column default is dropped (ADR-0005).** It was
  `DEFAULT uuidv7()`, minted from the clock, so re-ingesting the identical corpus produced **0 of
  170** matching identifiers; it is now `uuid5(namespace, "<version sha256>:<char_start>:<char_end>")`
  and the same experiment produces **170 of 170**. Breaking: every chunk ID changes, so re-ingest
  from empty. `documents.document_id` and `document_versions.version_id` keep `uuidv7()`.
- `EVAL_PROTOCOL.md` §2 moves from *"SPECIFIED, does not exist yet"* to **VERIFIED**, §2.1 is
  implemented, and a new §2.2 records why items are authored against quotes. §10's claim that
  U-10 must close before a gold set can be pinned is **corrected**: citation IDs depend on the
  chunker and the corpus, not on the RRF constant or retrieval depths.
- `prepare_document` is split so the chunking stage is reusable; verified by re-ingesting and
  confirming all 170 chunk identifiers unchanged.
- `ARCHITECTURE.md` §3.1 moves from **SPECIFIED, 0 bytes** to **VERIFIED**, with each
  stage's status backed by a measurement.
- **The FR-7 property tests now exercise the production chunker.** They previously carried
  their own copy of the chunking logic, so they could have passed while the code that
  actually writes chunks was wrong — and it was: the experiment harness behind ADR-0003
  stored stripped text against unstripped offsets, which violates FR-7 on **40 of its 170
  chunks**. The shipped chunker reproduces ADR-0003's 170 chunks exactly with zero
  violations, zero coverage gaps, and no chunk wholly contained in another.
- Idempotency (NFR-8) is now a measurement rather than a claim: the content-hash check
  runs before extraction and embedding, so a re-run over an unchanged corpus takes
  **0.013 s against 41.0 s** and leaves every row count identical.
- `ARCHITECTURE.md` §4 moves from **PROPOSED** to **VERIFIED**, and §6's HNSW row is closed by
  ADR-0004.
- **FR-5 is enforced more strictly than §4 proposed:** `sha256` is unique *globally*, not per
  document. The proposed `UNIQUE (document_id, sha256)` would have permitted one payload to be
  stored under two documents — the exact case FR-5's acceptance test forbids.
- `chunks` carries `document_id` alongside `version_id`, kept honest by a composite foreign key,
  so a citation resolves in one row without the denormalised column being able to disagree.
- **Database roles are split by privilege.** `MIGRATION_DATABASE_URL` is the owner and runs DDL;
  `DATABASE_URL` is `docscout_app` with SELECT/INSERT/UPDATE and **no DELETE and no DDL**. FR-4's
  retention guarantee is now a privilege the service lacks rather than a promise it keeps.

### Decided
- **ADR-0002 pins the embedding model and vector dimension: `BAAI/bge-small-en-v1.5`, `D = 384`.**
  Closes U-9 and unblocks the schema. The decision rests on a five-arm bake-off over the real
  RBI/SEBI corpus (149 chunks, 21 documents) with a BM25 lexical control, two independent probe
  sets, a harness sanity control, and paired significance testing. Evidence:
  `docs/decisions/evidence/u9-embedding-bakeoff.json`, harness
  `scripts/experiments/u9_embedding_bakeoff.py`.
  - No candidate was significantly better than another (all McNemar p >= 0.42; every 95% CI
    straddles zero), so the choice is made on structural and cost grounds and says so.
  - `all-MiniLM-L6-v2` is rejected on evidence rather than leaderboard reputation: its 256-token
    window truncates **72 of 149 chunks**. It still scored 1.0 on the easy document-level probe,
    which is exactly how such a defect survives a casual benchmark.
  - BM25 alone matched or beat every neural embedder, which makes the hybrid retriever an
    evidence-backed requirement rather than an assumption.
- **ADR-0003 pins the chunking strategy: fixed-width 1,000 characters with 150-character (15%)
  overlap, over offset-preserved cleaned text.** Closes U-8 and, with U-9, completes every
  decision gating the database schema. Chosen from a 14-configuration sweep scored with
  character-span gold fixed before any chunker runs, plus paired McNemar and 10,000-sample
  bootstrap tests on identical probes. Evidence:
  `docs/decisions/evidence/u8-chunking-sweep.json` and `u8-chunking-focus.json`, harness
  `scripts/experiments/u8_chunking_sweep.py`.
  - Overlap is the cheapest quality in the sweep: it raises span integrity from 0.855 to 0.965
    (p = 0.0001) for 21 extra chunks and no loss of citation tightness.
  - 1,200-character chunks scored the best recall (+0.070, p = 0.0125) and were still rejected:
    they produced 524-token chunks against ADR-0002's 512-token ceiling, and silent encoder
    truncation would leave `char_end` claiming coverage of text the embedding never saw.
  - Clause-aware chunking was built and tested rather than assumed. It gives the tightest
    citations of any 1,000-char configuration but loses span integrity (p = 0.0433), because
    pypdf preserved no layout: every real document extracts to zero newlines.
  - Cleaning turns out not to improve retrieval at all; it earns its place purely by buying token
    headroom (447 vs 484 peak tokens), which is what keeps 1,000 characters inside the ceiling.
- **Offset-preserving cleaning is now a normative ingest requirement** (`ARCHITECTURE.md` §3):
  noise is blanked with equal-length spaces, never deleted, so `char_start`/`char_end` stay valid
  against the original extracted text as FR-7 requires.

### Fixed
- `python -m app.ingest --report-dir <relative path>` crashed with `ValueError` *after*
  successfully writing all 170 chunks: `Path.relative_to` raises for a relative path that
  does not literally start with the repository prefix. The run reported success to the
  database and a traceback to the operator. Covered by a regression test.
- `DATABASE_URL` in `.env` had never worked: it carried an 11-character placeholder password
  against a 48-character real one. Nothing in the repository read the variable, so nothing had
  ever caught it. Both URLs are now derived from the generated passwords and verified by
  connecting rather than by being present.
- **Corrected a ~16x error in the embedding-throughput extrapolation.** `CORPUS_SPEC.md` C-5 read
  112.4 *sentences*/s as "~10,000 chunks is ~90 s". Measured on real 1,000-char regulatory chunks
  the rate is 6.9 chunks/s, so 10k chunks is ~24 minutes. The Phase 0 measurement was sound; only
  the extrapolation to chunks was not. `SETUP_REPORT.md` keeps its signed wording with a pointer
  to the correction.
- **Restored the executable bit on all 16 shebang scripts.** A workspace snapshot stripped it and
  the loss was committed unnoticed, because file modes are invisible in a diff. One of the affected
  files is `.claude/hooks/dangerous-bash.sh`, the agent command denylist — a security control that
  was present, correct and **not running**. Found by V8 on the first re-run of the verification
  matrix. Guarded by a new `check-shebang-scripts-are-executable` pre-commit hook.
- `scripts/bootstrap.sh` full tier: added `jq`, `postgresql-client` and `gh`, which V1 of the
  verification matrix requires and the script did not install.
- `.gitignore`: `loadtests/reports/verify/` is now tracked. V15 asserts that report exists, so the
  matrix depended on an artifact git would not keep. Ad-hoc `make load` runs remain ignored.
- `.gitignore`: anchored `corpus/` to `/corpus/`. Unanchored, it matched any directory named
  `corpus` at any depth and silently excluded `docs/corpus/` — the new `CORPUS_SPEC.md` would not
  have been committed, with no error reported.
- `.gitignore`: `corpus/raw/manifest.json` is now tracked, implementing what
  `docs/corpus-provenance.md` already stated. The manifest is the provenance anchor that makes the
  fetched bytes re-derivable; it was being ignored along with them.
- Added `.gitkeep` to `tests/eval/` and `docs/deploys/`, the two empty directories existing
  `Makefile` targets reference by path (Known issue K-14).

### Security
- The host allowlist re-validates **every redirect hop** and automatic redirects are
  disabled. Checking only the URL a caller passes in is decoration: an allowlisted host
  can answer `302 Location: https://evil.example/…` and the default client follows it.
- Ingestion refuses to start when deploy or cloud credentials are in its environment
  (SECURITY S-4, FR-6), before the database connection and before any network call. Error
  messages name the variable and never its value.
- The pipeline runs as `docscout_app` — SELECT/INSERT/UPDATE, no DELETE, no DDL — and the
  database tests run as that role to prove the write path needs nothing more.
- Rejected the Postgres MCP server named in the original brief: the PyPI package
  `mcp-server-postgres` is an unvetted third-party upload, and the brief's invocation would have
  passed the live database superuser password to it as a command-line argument.
- `.gitignore` is treated as a security control and is now verified per path with
  `git check-ignore -v` rather than by reading the patterns.
- `gitleaks` clean over the full re-initialised history (3 commits, 1.03 MB, no leaks).

### Notes
- No feature code. No metrics published. No cloud resources created.
- The Phase 0 git history (`695e0f4` → `c88f59b`) was lost with the sandbox snapshot and was
  deliberately **not** reconstructed; see ADR-0001.
