# Changelog

All notable changes to DocScout are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
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
