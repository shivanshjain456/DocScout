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

### 3.1 `app/ingest/` — offline pipeline — SPECIFIED, 0 bytes

Stages: **fetch → extract → chunk → embed → store.**

| Stage | Specified behaviour | Grounding |
|---|---|---|
| fetch | `httpx` GET against the host allowlist in `CORPUS_SPEC.md` §2, descriptive User-Agent, rate-limited, no auth | Access patterns VERIFIED by `scripts/verify_corpus_fetch.py` on 20 documents |
| extract | `pypdf` for PDFs, `trafilatura`/`beautifulsoup4` for HTML; **follow the SEBI `<iframe … file=…>` to the PDF** | VERIFIED failure mode: the SEBI detail page yields ~227 extractable chars (K-17) |
| guard | Reject any document extracting < 500 clean chars (FR-3) | The ≥ 500-char criterion is the one Phase 0 used (20/20 passed) |
| chunk | Emit chunks carrying `document_id`, `version`, source offsets | Strategy UNRESOLVED (U-8) |
| embed | Encode chunk text to a fixed-dimension vector | Model UNRESOLVED (U-9); local `bge-small-en-v1.5` VERIFIED at 384 d, 112.4 sentences/s |
| store | Upsert document, version, chunks, embeddings in one transaction per document | SPECIFIED |

Idempotency (NFR-8) comes from the content hash: re-running over an unchanged corpus performs no
writes. The pipeline is a CLI entrypoint, not an API route — nothing in `app/api/` may trigger
ingestion (OUT-5).

### 3.2 `app/retrieval/` — online retrieval — SPECIFIED, 0 bytes

Three stages, in order:

1. **Lexical arm** — Postgres full-text search over a `tsvector` column. VERIFIED available:
   full-text search is confirmed working in the Phase 0 database (`docs/setup/verify/step2-services.txt`).
2. **Dense arm** — pgvector KNN over an **HNSW** index using cosine distance. VERIFIED available:
   pgvector 0.8.2 with `vector_cosine_ops`; the `hnsw.iterative_scan` GUC exists and is `off` by
   default (`docs/setup/verify/step2-services-hnsw.txt`).
3. **Fusion** — Reciprocal Rank Fusion over the two ranked lists, then **cross-encoder rerank** of
   the top candidates. VERIFIED cost: `ms-marco-MiniLM-L-6-v2` at **4.56 ms/pair** on the 2 vCPU
   floor — reranking 50 candidates is therefore ≈ 230 ms of CPU, which is a real line item in the
   p95 < 3 s budget (NFR-1, U-14).

RRF constant, per-arm depth, and rerank depth are **UNRESOLVED (U-10)** and MUST be configuration,
not literals, so a sweep can produce the ADR that closes U-10.

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

## 4. Data model — PROPOSED

No schema exists in the repository; `infra/initdb/` creates extensions and a role only. The
following is the first written form of the schema and needs an ADR before it binds. It is shaped by
requirements FR-2, FR-4, FR-5, FR-7 and by `CORPUS_SPEC.md` §4.

| Table | Key columns | Purpose |
|---|---|---|
| `documents` | `document_id` (PK), `canonical_url`, `source` (`RBI`\|`SEBI`), `title`, `authority`, `published_date`, `detail_page` | One logical circular, stable across reissues |
| `document_versions` | `version_id` (PK), `document_id` (FK), `sha256` (unique with `document_id`), `fetch_ts`, `http_status`, `bytes`, `pages`, `extractor`, `char_count`, `is_current` | One observed byte-state; a new `sha256` at a known URL is a new row (FR-4) |
| `chunks` | `chunk_id` (PK), `version_id` (FK), `ordinal`, `text`, `char_start`, `char_end`, `tsv` (`tsvector`, generated), `embedding` (`vector(D)`) | The retrievable unit; `D` is fixed by U-9 |

Indexes: HNSW with `vector_cosine_ops` on `chunks.embedding`; GIN on `chunks.tsv`; unique
`(document_id, sha256)` on versions; `(version_id, ordinal)` on chunks.

Three constraints that are easy to get wrong and are therefore stated normatively:

- `chunk_id` MUST remain resolvable after its version is superseded, so historical evaluation runs
  stay reproducible (FR-4, `EVAL_PROTOCOL.md` §7).
- The embedding column dimension is **not** changeable without a reindex and a full re-evaluation;
  it is a one-way door and the reason U-9 must close before M2.
- Supersession between *different* documents (a master circular replacing earlier ones) is **not**
  modelled above and is **UNRESOLVED (U-12)**.

---

## 5. Request flow — SPECIFIED

```
POST /v1/answer
  └─ app/api        authenticate key · rate-limit (Redis) · validate body
       └─ app/retrieval
            ├─ lexical: tsvector @@ query          ──┐
            ├─ dense:   embedding <=> query_vector ──┤→ RRF fuse → top-N
            └─ rerank:  cross-encoder (CPU, 4.56 ms/pair measured)
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
| Postgres + pgvector as the single store for lexical **and** dense retrieval | SPECIFIED | One datastore, transactional consistency between text and vectors, no separate search cluster to operate; VERIFIED working at 18.4 / 0.8.2 | Yes — rejected alternatives (Elasticsearch, a dedicated vector DB) must be recorded |
| HNSW over IVFFlat | PROPOSED | HNSW needs no training step and gives better recall at small corpus sizes; `hnsw.iterative_scan` available if filtered recall is poor | Yes |
| Cross-encoder reranking on CPU | SPECIFIED | Measured 4.56 ms/pair, 88 MB — affordable at the 2 vCPU floor | No |
| Local embedder `bge-small-en-v1.5` (384 d) | UNRESOLVED (U-9) | VERIFIED runnable and free; a hosted embedder may score better but reintroduces the credential dependency (K-1) | Yes |
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
