# DocScout — Architecture

**Status:** authoritative architecture document. Last updated **2026-10-01**.
**Implementation status:** the component boundaries below are fixed and enforced by review
(`AGENTS.md`); **none of the components contain code.** Every `app/**/__init__.py` is 0 bytes
(VERIFIED 2026-10-01). Read every "does" in this document as "is specified to do".

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9.

**Relationship to `docs/architecture/system-diagram.md`:** that file holds the Mermaid rendering of
the same system and the trust-boundary table. It remains current and is referenced, not duplicated,
here. If the two disagree, this document wins and the diagram is a defect to be fixed.

---

## 1. Architectural drivers

What actually shapes this design, in order of force:

1. **Citations are the product, not a feature.** An answer without a resolvable citation is a
   failure, not a degraded success. This forces chunk-level provenance all the way from the fetched
   bytes to the rendered answer (`SPEC.md` FR-7, FR-11).
2. **Corpus text is hostile by assumption.** Public PDFs are untrusted input that reaches a language
   model. This forces a hard data/instruction separation (`SECURITY.md` S-7).
3. **Measured, not asserted.** Quality and performance claims must be backed by an artifact
   (`docs/QUALITY_BAR.md` Q-7). This forces the evaluation harness to be a first-class component,
   not a test directory.
4. **A 2 vCPU / 1.9 GiB floor** (VERIFIED environment, K-15) with **no GPU** and **no hosted model
   credentials** (K-1). This forces CPU-sized local models and makes the reranker a measured cost in
   the latency budget, not a free improvement.
5. **Offline and online paths must not share credentials.** Ingestion runs with no deploy
   credentials (`AGENTS.md`, `SECURITY.md` S-4).

---

## 2. System context

```
   RBI / SEBI public websites            Compliance analyst (browser)
            │ HTTPS, read-only                     │ HTTPS
            ▼                                      ▼
   ┌─────────────────────┐              ┌──────────────────────┐
   │  OFFLINE: ingestion │              │  ONLINE: query path  │
   │  no deploy creds    │              │  API-key gated       │
   └──────────┬──────────┘              └──────────┬───────────┘
              │ writes                              │ reads
              ▼                                     ▼
        ┌──────────────────────────────────────────────┐
        │  Postgres 18.4 + pgvector 0.8.2  (VERIFIED)  │
        │  documents · versions · chunks · embeddings  │
        └──────────────────────────────────────────────┘
                     ▲                      │
                     │ reads only           ▼
        ┌────────────┴───────────┐   ┌──────────────┐
        │  EVAL harness (offline)│   │  Redis 7     │
        │  no ingest network     │   │  cache, rate │
        └────────────────────────┘   └──────────────┘
```

The two runtime paths share only the database. The evaluation harness reads the database and the
committed gold set and has no network access to the ingestion sources.

---

## 3. Components

Directory boundaries are **fixed**; crossing one requires an ADR in `docs/decisions/` (`AGENTS.md`).

### 3.1 `app/ingest/` — offline pipeline — VERIFIED

Stages: **fetch → extract → guard → clean → chunk → embed → store.**

Built and run against the live database: 21 documents, **170 chunks**, 0 failures, 41.0 s on
the 2 vCPU floor. Evidence: `docs/setup/verify/m2-ingestion.txt`,
`docs/corpus/evidence/m2-ingest-run/ingest.json`. Entry point `python -m app.ingest`
(`make ingest`), never an API route (OUT-5).

| Stage | Behaviour | Status |
|---|---|---|
| fetch | Host allowlist of exactly three hosts, HTTPS only, userinfo refused, and **every redirect hop re-validated** — automatic redirects are disabled because an allowed host can 302 anywhere | VERIFIED (`app/ingest/fetch.py`, `allowlist.py`). Crawling the listing pages remains in `scripts/verify_corpus_fetch.py`; ingestion reads the manifest |
| extract | `pypdf` for PDFs, `trafilatura` for HTML, then **whitespace normalisation** to the canonical document text | VERIFIED — extraction reproduces all 21 of Phase 0's recorded `char_count` values exactly, pinned by a test |
| guard | Reject under 500 **non-whitespace** clean characters (FR-3) | VERIFIED against a stub-page fixture that reproduces the K-17 failure mode |
| clean | Blank Devanagari, mojibake, `U+FFFD`, page furniture **without moving any offset**, re-checked on every call | VERIFIED (ADR-0003) |
| chunk | 1,000 chars / 150 overlap, whitespace boundaries, hard split at 512 tokens | VERIFIED — 170 chunks, mean 253 / max 441 tokens, **0 uncovered non-whitespace characters**, 0 chunks over the ceiling |
| embed | `bge-small-en-v1.5`, 384 d, L2-normalised, no prefix on passages | VERIFIED — max `abs(norm − 1)` across all 170 stored vectors is 9e-8 |
| store | One transaction per document; hash-first de-duplication | VERIFIED — runs as `docscout_app` with no DELETE and no DDL |

**Idempotency (NFR-8) is measured, not asserted.** The content-hash check runs *before*
extraction and embedding, so a re-run over an unchanged corpus takes **0.013 s against
41.0 s** and leaves every row count identical. See the two report files above.

**Offsets are verified twice.** `chunk_document` refuses to emit a chunk whose offsets do
not re-extract its own text, and `make ingest-verify` re-derives all 21 documents from
their source PDFs and re-checks all 170 stored chunks against the database — 170/170.

**Known gap, not fabricated around:** `documents.title` and `published_date` are left NULL.
The manifest records neither, and the first line of a regulator's PDF is a letterhead, not
a title. FR-14 requires a citation to state title and date, so that requirement is **not
yet satisfiable** and closing it needs a titling strategy with its own measurement rather
than a heuristic quietly invented here. `authority` is populated, being exactly derivable
from `source`.

### 3.2 `app/retrieval/` — online retrieval — SPECIFIED, 0 bytes

Three stages, in order:

1. **Lexical arm** — Postgres full-text search over a `tsvector` column. VERIFIED available:
   full-text search is confirmed working in the Phase 0 database (`docs/setup/verify/step2-services.txt`).
2. **Dense arm** — pgvector KNN over an **HNSW** index using cosine distance. VERIFIED available:
   pgvector 0.8.2 with `vector_cosine_ops`; the `hnsw.iterative_scan` GUC exists and is `off` by
   default (`docs/setup/verify/step2-services-hnsw.txt`).
3. **Fusion** — Reciprocal Rank Fusion over the two ranked lists (`k=60`), then each arm's own
   top hit is guaranteed a seat in the returned `k` (**ADR-0007**). Cross-encoder reranking is
   **implemented and available but DISABLED in the serving configuration** (**ADR-0009**).

   **Cost correction (2026-10-02).** This section previously recorded "VERIFIED cost:
   `ms-marco-MiniLM-L-6-v2` at **4.56 ms/pair** … reranking 50 candidates is therefore ≈ 230 ms".
   That figure was measured on short synthetic sentences and understates the real cost by about
   twenty times. Re-measured on this corpus: **5.54 ms/pair on short text, 102–126 ms/pair on real
   chunks** (946 characters / 267 tokens mean), because transformer cost scales with sequence
   length. Reranking 50 candidates is therefore ≈ **6.3 s**, not 230 ms — it breaks the p95 < 3 s
   budget rather than fitting inside it. ADR-0009 has the measurements and the decision.

RRF constant and rerank depth are now **CLOSED** by ADR-0007 and ADR-0009, both with full sweeps
over the gold set. Per-arm candidate depth (`k_dense`, `k_lexical` = 50) remains **UNRESOLVED
(U-10)**. All of them are configuration, not literals.

**Why hybrid rather than dense-only:** regulatory questions carry exact tokens — circular numbers,
section references, defined terms — that dense retrieval alone retrieves unreliably, while purely
lexical search misses paraphrase. This is the standard justification and is **PROPOSED** here as the
rationale; the evidence that validates it for this corpus is a per-arm ablation in the first full
evaluation run (`EVAL_PROTOCOL.md` §8).

### 3.3 `app/generate/` — grounded generation — SPECIFIED, 0 bytes

Assembles the prompt, calls the model, validates the result.

- Retrieved chunks are wrapped in `<document>` delimiters, with a system instruction stating that
  text inside them is **data and never instructions** (FR-12, S-7).
- Citations are mandatory and **validated after generation**: a cited chunk ID that was not in the
  supplied context is a rejected answer, not a warning (FR-11). This check is deterministic and
  belongs here, not in the evaluation harness.
- Refusal is a first-class output (FR-13), not an error path.
- The generator model is **BLOCKED (U-1)**: every hosted role in `config/models.json` is
  `id: null`, `status: BLOCKED_NO_CREDENTIAL` (VERIFIED). The interface MUST therefore be written
  against a provider-agnostic port so the project is not blocked on that decision.

### 3.4 `app/evals/` — evaluation harness — SPECIFIED, 0 bytes

Owns the gold set, deterministic scorers, judge adapters, and report writing. Normative content is
`docs/eval/EVAL_PROTOCOL.md`. Architecturally it matters that this is a **component, not a test
suite**: it reads the database and the gold set, never the ingestion network, and its output is a
timestamped report directory (FR-24).

A related rough edge, partly fixed: `make eval` runs `uv run pytest tests/eval -q`. That directory
was missing entirely and the target failed on a bad path; it now exists with a `.gitkeep`
(2026-10-01), so the target fails on "no tests collected" — the documented stub state — until the
harness lands. See `docs/MILESTONES.md` M0.

### 3.5 `app/api/` — HTTP surface — SPECIFIED, 0 bytes

FastAPI. **The only place** API keys and rate limits are handled (`AGENTS.md`). Exposes the
PROPOSED contract in `SPEC.md` §4.3 (U-13). `app/main.py` is referenced by `make dev` and
`AGENTS.md` but **does not exist**, so `make dev` fails. Deliberately left that way: a module
written only to satisfy a Makefile target is feature code with no requirement behind it. It is
decided at M1 together with the API contract (`docs/MILESTONES.md` M0 item 5).

### 3.6 `ui/` — demonstration UI — scaffold VERIFIED, DocScout UI SPECIFIED

React 19.2.8 + Vite ^8.3.0 + TypeScript ~6.0.2, linted by oxlint, smoke-tested by Playwright
(chromium). The scaffold builds to 222 KB JS / 69 KB gzip (VERIFIED). It renders the Vite starter,
not DocScout. Note `ui/package.json` has **no `test` script**; Playwright is invoked directly as
`pnpm exec playwright test` (VERIFIED).

### 3.7 Supporting infrastructure — VERIFIED

| Piece | State |
|---|---|
| `docker-compose.yml` | Postgres `pgvector/pgvector:0.8.2-pg18` + Redis `7-alpine`, both with healthchecks; both ran healthy in Phase 0 |
| `infra/initdb/01-extensions.sql`, `02-app-role.sh` | Extension creation and a least-privilege application role at first boot |
| `scripts/verify_setup.sh` | The V1–V17 matrix; `make verify-setup`; last result PASS=15 FAIL=0 BLOCKED=2 |
| `scripts/verify_corpus_fetch.py` | Fetch/extract verification that produced `corpus/raw/manifest.json` |
| `scripts/mcp_probe.py` | Real `tools/list` probes against configured MCP servers |
| `loadtests/smoke.js` | k6 scenario; exercised against a stub server only |

A **deviation from the brief** is encoded in the compose file and must not be "fixed" back: pg18
images require the volume mounted at `/var/lib/postgresql`, **not** `/var/lib/postgresql/data`; the
brief's path makes the container exit(1) (K-5). Likewise `infra/initdb/02-app-role.sh` exists because
`${DB_APP_PASSWORD}` does not expand in a `.sql` init file (K-6).

---

## 4. Data model — VERIFIED

**Bound by ADR-0004** and applied to the live database as `migrations/0001_initial_schema.up.sql`
(PG 18.4 / pgvector 0.8.2). This section now describes a schema that exists; `migrate.py status`
reports version 1 applied. Evidence: `docs/setup/verify/m1-schema-migration.txt`; 19 tests in
`tests/test_schema.py`.

| Table | Key columns | Purpose |
|---|---|---|
| `documents` | `document_id` (PK, `uuidv7()`), `canonical_url` (unique), `source` (`RBI`\|`SEBI`\|`SYNTHETIC`), `title`, `authority`, `published_date`, `detail_page` | One logical circular, stable across reissues |
| `document_versions` | `version_id` (PK), `document_id` (FK), `sha256` (**globally unique**), `fetch_ts`, `http_status`, `bytes`, `pages`, `extractor`, `char_count`, `is_current` | One observed byte-state; a new `sha256` at a known URL is a new row (FR-4) |
| `chunks` | `chunk_id` (PK), `document_id` + `version_id` (**composite FK**), `ordinal`, `text`, `char_start`, `char_end`, `token_count`, `tsv` (generated STORED), `embedding_model`, `embedding` (**`vector(384)`**) | The retrievable unit; `D = 384` fixed by ADR-0002 |

Indexes: HNSW `vector_cosine_ops (m = 16, ef_construction = 64)` on `chunks.embedding`; GIN on
`chunks.tsv`; unique `(version_id, ordinal)` on chunks; partial unique on `is_current`.

**Four deltas from the PROPOSED sketch this section previously carried** (argued in ADR-0004):
`sha256` is unique *globally*, not per document, because the per-document form permits one payload
under two documents and FR-5 forbids exactly that · `chunks` also carries `document_id`, held
honest by a composite FK, because FR-7 cites document + version + offsets · `token_count` and
`embedding_model` are new, enforcing ADR-0002's ceiling and making re-embedding auditable ·
`source` admits `SYNTHETIC` so the injection canary is storable.

The schema enforces the specification rather than describing it. `ON DELETE RESTRICT` and the
absence of a `DELETE` grant make FR-4 retention a privilege rather than a promise; CHECKs reject a
chunk over 512 tokens, a non-unit vector, a `char_count` below 500 (the ~227-char SEBI failure
mode, K-17) and an inverted offset span. Each constraint names its requirement in an inline
comment, and `tests/test_schema.py` asserts the database *refuses* each forbidden thing.

Three constraints that are easy to get wrong and are therefore stated normatively:

- `chunk_id` MUST remain resolvable after its version is superseded, so historical evaluation runs
  stay reproducible (FR-4, `EVAL_PROTOCOL.md` §7). Enforced: `ON DELETE RESTRICT`, no `DELETE`
  privilege, tested both ways.
- The embedding column dimension is **not** changeable without a reindex and a full re-evaluation;
  it is a one-way door, now closed at `vector(384)` by ADR-0002. The cost of reopening it is
  dominated by evaluation, not compute: re-embedding 10k chunks takes ~24 min on the 2 vCPU floor,
  but every historical eval run becomes incomparable and the regression gate needs three fresh
  baselines. That cost is near-zero until U-17 lands and steep afterwards.
- Supersession between *different* documents (a master circular replacing earlier ones) is **not**
  modelled above and is **UNRESOLVED (U-12)**. The schema does not pretend otherwise: `is_current`
  scopes supersession within a single document only.

**Ingest inherits one obligation from FR-7**: `char_start`/`char_end` MUST bracket the *stored*
text. ADR-0003's cleaning strips leading whitespace from a chunk, so ingest MUST advance
`char_start` by the trimmed count and set `char_end = char_start + len(text)`. A property test
asserts `source[char_start:char_end] == text` on both synthetic and real corpus documents.

**Migrations** are numbered plain-SQL `.up`/`.down` pairs under `migrations/`, applied by
`scripts/migrate.py` (`make migrate`, `make migrate-status`, `make migrate-down TO=N`). The runner
takes an advisory lock, runs one transaction per migration, and refuses to proceed if an applied
file's SHA-256 has changed. It connects as `MIGRATION_DATABASE_URL` (owner, DDL); the service
connects as `DATABASE_URL` (`docscout_app`: SELECT/INSERT/UPDATE, no DELETE, no DDL).

---

## 5. Request flow — SPECIFIED

```
POST /v1/answer
  └─ app/api        authenticate key · rate-limit (Redis) · validate body
       └─ app/retrieval
            ├─ lexical: tsvector @@ query          ──┐
            ├─ dense:   embedding <=> query_vector ──┤→ RRF fuse → top-N
            └─ rerank:  cross-encoder — BUILT, MEASURED, OFF (ADR-0009:
                          102-126 ms/pair on real chunks; 30x p95 for +3 items)
       └─ app/generate
            ├─ wrap chunks in <document> delimiters
            ├─ call generator (model BLOCKED, U-1)
            └─ validate: ≥1 citation · every cited ID present in context
       └─ response: answer | refusal + citations + timings
```

Failure behaviour, SPECIFIED: retrieval returning zero candidates produces a refusal, not an empty
answer; a generator timeout produces a 503 with no partial answer; citation validation failure is a
server-side error, never a silently returned uncited answer.

---

## 6. Technology decisions and their status

| Decision | Status | Rationale / evidence | ADR needed |
|---|---|---|---|
| Postgres + pgvector as the single store for lexical **and** dense retrieval | SPECIFIED, schema applied | One datastore, transactional consistency between text and vectors, no separate search cluster to operate; VERIFIED working at 18.4 / 0.8.2 | Yes — ADR-0004 applied the schema but did **not** argue the rejected alternatives (Elasticsearch, a dedicated vector DB); that ADR is still owed |
| HNSW over IVFFlat | **DECIDED (ADR-0004)** | No training step and tolerates incremental inserts, which IVFFlat does not; chosen on structure, as the difference is unmeasurable at this corpus size | Closed by ADR-0004 |
| Cross-encoder reranking on CPU | **BUILT, MEASURED, DISABLED (ADR-0009)** | 102–126 ms/pair on *real* chunks, not the 4.56 ms/pair measured on short synthetic text. Reranking the top 10 costs 30× the p95 for a +3-item recall@1 gain whose CI spans zero; top-20+ also drops recall@10 from 1.000 to 0.992 | Yes |
| Local embedder `bge-small-en-v1.5` (384 d) | **DECIDED (ADR-0002)** | Measured on the real corpus against MiniLM-L6, bge-base (768 d), multilingual-e5 and a BM25 control: no significant quality difference, so chosen for zero truncation at 512 tokens, smallest index and $0 cost. A hosted embedder stays BLOCKED by U-1 (K-1) | Yes |
| Redis for cache + rate limiting | SPECIFIED | VERIFIED running; `AGENTS.md` assigns rate limiting to `app/api/` | No |
| Provider-agnostic generator port | SPECIFIED | Forced by U-1 — the model identity cannot be chosen yet | No |
| FastAPI | SPECIFIED | Pinned and locked (0.142.2); async-native, matches `ASYNC` ruff rules already enabled | No |
| Python 3.12 only | VERIFIED | `requires-python = ">=3.12,<3.13"`; `torch` resolved from an explicit CPU index | No |

---

## 7. Cross-cutting concerns

**Configuration.** Environment variables via `.env` (gitignored; `.env.example` tracked, VERIFIED).
Model roles live in `config/models.json`, which currently records `BLOCKED_NO_CREDENTIAL` for every
hosted role and `_phase0_api_spend_usd: 0.0`.

**Observability.** `structlog` + `orjson` are locked. SPECIFIED: JSON logs with a request ID; logs
MUST NOT contain retrieved context or keys (NFR-9). No metrics or tracing stack has been chosen —
**UNRESOLVED**, folded into U-7 for the deploy target.

**Error handling.** SPECIFIED: upstream fetch failures are recorded in the manifest with their
`http_status` and never silently skipped; the `ok: false` field already exists in the manifest
schema (VERIFIED).

**Trust boundaries.** The table in `docs/architecture/system-diagram.md` is normative and is not
duplicated here; `SECURITY.md` §3 expands each boundary into controls.

---

## 8. What would invalidate this architecture

Stated plainly so the design can be falsified rather than defended:

- If the first evaluation shows the lexical arm contributes nothing over dense-plus-rerank, the
  fusion stage is complexity without benefit and should be removed (test: per-arm ablation, §3.2).
- If p95 on 2 vCPU cannot reach 3 s with reranking in the path, either the rerank depth shrinks,
  the hardware changes, or NFR-1 is revised — U-14 decides, with a measurement, not a preference.
- If a large share of RBI archive documents prove to be scanned images, the ingestion design needs
  an OCR stage that does not exist here (U-16).
- If supersession turns out to dominate answer correctness, U-12 stops being metadata and becomes a
  core part of the retrieval ranking.
