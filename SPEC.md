# DocScout — Product & System Specification

**Status of this document:** authoritative specification. Last updated **2026-10-01**.
**Implementation status of the system it describes:** *not implemented*. Phase 0 (environment) is
complete; no DocScout feature code exists (see §2.2 for the evidence).

This document is the root of a seven-document set. Each is readable alone; together they are one
source of truth.

| Document | Owns |
|---|---|
| `SPEC.md` (this file) | Problem, scope, users, functional/non-functional requirements, interfaces, the global **Unresolved Register** |
| `docs/architecture/ARCHITECTURE.md` | Components, data model, data flow, boundaries, technology decisions |
| `docs/corpus/CORPUS_SPEC.md` | What the corpus is, how it is acquired, identified, versioned, and extracted |
| `docs/eval/EVAL_PROTOCOL.md` | Gold set, scorers, judge calibration, thresholds, CI gate, reporting |
| `SECURITY.md` | Threat model, controls, secret handling, injection posture, disclosure |
| `docs/QUALITY_BAR.md` | Definition of done, gates that must pass, evidence rules |
| `docs/MILESTONES.md` | Ordered delivery plan, entry/exit criteria, current position |

---

## 1. Status vocabulary (used identically in all seven documents)

| Tag | Meaning | Burden of proof |
|---|---|---|
| **VERIFIED** | Observed in this repository or environment, with a named evidence artifact | Must cite a file path or command output |
| **SPECIFIED** | A normative requirement of the system. Not built yet | Must be testable |
| **PROPOSED** | A design choice first written down here. Not yet binding | Needs sign-off or an ADR before it becomes SPECIFIED |
| **BLOCKED** | Cannot proceed without a named external input | Must name the input and who supplies it |
| **UNRESOLVED** | Open question | Must appear in the §9 register with the decision and the evidence that settles it |

**RFC 2119 keywords** (MUST / MUST NOT / SHOULD / MAY) carry their usual meaning and apply only to
requirements tagged SPECIFIED.

**Reading rule:** absence of a VERIFIED tag means the behaviour does not exist yet. No statement in
these documents describes DocScout as working unless it is tagged VERIFIED and names its evidence.

---

## 2. Problem and current position

### 2.1 Problem

Indian financial-sector compliance work depends on circulars, notifications, and master circulars
published by the **Reserve Bank of India (RBI)** and the **Securities and Exchange Board of India
(SEBI)**. These are long PDFs, published continuously, frequently superseded, and searchable only by
title or date on the issuing sites. Answering a question such as *"what is the current cash-withdrawal
limit rule and which circular sets it"* requires locating the governing document among many, reading
it, and confirming it has not been superseded.

DocScout is **SPECIFIED** as a retrieval-augmented question-answering service over that corpus that
returns an answer **and** the citations that support it, so the answer can be checked against the
primary source rather than trusted.

### 2.2 Current position — VERIFIED

Phase 0 (environment setup) completed on 2026-10-01 and is reported in
`docs/setup/SETUP_REPORT.md`. The verification matrix `scripts/verify_setup.sh` (runnable as
`make verify-setup`) recorded **PASS = 15, FAIL = 0, BLOCKED = 2** (V10 CI run, V11 hosted models).

No application code exists. Evidence, re-checked 2026-10-01:

- `app/__init__.py`, `app/api/__init__.py`, `app/evals/__init__.py`, `app/generate/__init__.py`,
  `app/ingest/__init__.py`, `app/retrieval/__init__.py` are each **0 bytes**.
- `app/main.py` **does not exist**, although `make dev` and `AGENTS.md` both invoke
  `uvicorn app.main:app`. That command currently fails. (§9, U-15)
- The entire test suite is `tests/test_placeholder.py` (175 bytes, 1 test).
- The only executable project code is tooling: `scripts/verify_setup.sh`,
  `scripts/verify_corpus_fetch.py`, `scripts/mcp_probe.py`, `loadtests/smoke.js`, `infra/initdb/*`,
  and the `ui/` Vite scaffold.

What Phase 0 *did* establish is a verified, pinned toolchain and a proven ability to fetch and
extract the corpus. See `docs/MILESTONES.md` §2 for exactly what that buys.

### 2.3 Environment reproducibility — defect found, now largely repaired

**The defect, observed 2026-10-01.** Work resumed in a fresh sandbox holding the complete working
tree — and nothing else. `.git/` was gone, taking the Phase 0 history (`695e0f4` → `c88f59b`) with
it. So were `uv`, `docker`, `psql`, `k6`, `gitleaks`, `pre-commit`, `gh`, `aws` and `pnpm`, the
1.8 GB `.venv`, the model cache, `node_modules/`, and every empty directory (`evals/`,
`tests/eval/`, `docs/deploys/`). This is consistent with the platform's snapshot rules: virtualenvs,
caches, build output and credential paths such as `.git/config` are excluded from persistence.

The repository was therefore in the worst possible state for a project whose first rule is
*evidence or it didn't happen*: it **documented** a verified environment while offering no path
back to one. A verification matrix nobody can re-run is folklore.

**The repair — VERIFIED 2026-10-01**, decided in
`docs/decisions/0001-restore-version-control-and-bootstrap.md`:

| Action | Result |
|---|---|
| `scripts/bootstrap.sh` added — pinned, idempotent, tiered (`core` / `full`), with a `--check` mode that installs nothing and exits non-zero on a gap | `core` tier rebuilt the environment in **~14 s** |
| `uv sync --frozen` from the committed lockfile | `uv.lock` SHA-256 **unchanged** at `600c9001…1b98d`; **164** packages installed on linux-x86_64 |
| The four CI `quality` gates re-run | `ruff check`, `ruff format --check`, `mypy app` (strict), `pytest` — **all green** |
| Version control re-initialised, history **not** fabricated | Three commits, each through the full **11-hook** chain, no `--no-verify` |

**Two latent defects were caught during that repair**, both of which would have failed silently:

1. **`.gitignore` had an unanchored `corpus/` pattern.** Git matches such a pattern at *any* depth,
   so `docs/corpus/` — the home of `CORPUS_SPEC.md` — was excluded. The document would simply not
   have been committed, with no error. Now anchored to `/corpus/`.
2. **`corpus/raw/manifest.json` was untracked**, despite `docs/corpus-provenance.md` stating it is
   tracked. The manifest is what makes the corpus re-derivable, so the claim was hollow. The
   manifest (16 KB) is now tracked; the fetched bytes remain ignored.

**Residual risk, stated plainly.** Bootstrap does not make the environment persistent — the
toolchain still lives outside the repository and will be lost again at the next snapshot. What
changed is the cost of recovery: one command and ~14 s, instead of re-deriving the install steps
from a report. The `full` tier (Docker, Compose, Node/pnpm, k6, AWS CLI) has **not** been exercised
on a clean machine, so `make verify-setup` has not been re-run since Phase 0. U-15 stays open for
exactly that remainder.

### 2.4 Non-goals for this specification

This document specifies the system. It does **not** claim any part of it is built, does not set
dates, and does not substitute for the ADRs required by `AGENTS.md` for decisions with a rejected
alternative.

---

## 3. Users and scope

### 3.1 Intended user — PROPOSED

The primary user is a **compliance analyst** at a regulated Indian financial institution: a
professional reader who knows the domain, needs the governing text, and is accountable for being
right. This persona is already assumed by the gold-set spec in `.claude/skills/rag-eval-protocol`
("in the voice of a real user (compliance analyst)").

It is **PROPOSED**, not validated: no user research has been conducted. The persona is consequential
because it sets the refusal bar (§4.3) and the citation requirement (§4.2). Recorded as U-17.

### 3.2 In scope — SPECIFIED

1. A read-only question-answering API over a corpus of RBI and SEBI public documents.
2. An offline ingestion pipeline that fetches, extracts, chunks, embeds, and stores those documents
   with full provenance.
3. Hybrid retrieval (lexical + dense) with reranking.
4. Grounded answer generation with mandatory citations and explicit refusal.
5. A versioned evaluation harness that is the project's primary quality evidence.
6. A minimal web UI for demonstrating and manually inspecting answers.

### 3.3 Out of scope — SPECIFIED

| ID | Out of scope | Why |
|---|---|---|
| OUT-1 | Legal advice, or any claim of regulatory completeness | DocScout surfaces and cites documents; it does not interpret authoritatively |
| OUT-2 | Non-public, paywalled, or login-gated sources | §6 of `docs/corpus/CORPUS_SPEC.md` forbids authentication bypass |
| OUT-3 | Document upload by end users | The corpus is curated and provenance-tracked; arbitrary upload breaks the trust model (`SECURITY.md` §4) |
| OUT-4 | Multi-tenancy, user accounts, per-user history | Not required by any requirement below; adds auth surface |
| OUT-5 | Write operations on the corpus from the API surface | The online path is read-only by design (`ARCHITECTURE.md` §3) |
| OUT-6 | Languages other than English | The corpus sample is English; the embedder `BAAI/bge-small-en-v1.5` is English-only (VERIFIED, 384 dims) |
| OUT-7 | Real-time or push notification of new circulars | Ingestion is batch |

---

## 4. Functional requirements

Each requirement is identified, testable, and tagged. **None is implemented.**

### 4.1 Ingestion

| ID | Requirement | Tag | Test |
|---|---|---|---|
| FR-1 | The ingester MUST fetch documents only from the source entry points enumerated in `docs/corpus/CORPUS_SPEC.md` §2 | SPECIFIED | Unit test asserting a host allowlist rejects an off-list URL |
| FR-2 | For every fetched document the ingester MUST record `url`, `source`, `detail_page`, `fetch_ts`, `http_status`, `bytes`, `sha256`, `pages`, `extractor`, `char_count`, `ok` | SPECIFIED (schema VERIFIED in `corpus/raw/manifest.json`) | Schema test over the emitted manifest |
| FR-3 | The ingester MUST reject and flag any document whose extracted text is < 500 clean characters, rather than ingesting it | SPECIFIED | Test with a stub-HTML fixture (the SEBI detail-page failure mode, ~227 chars) asserting a raised error |
| FR-4 | A changed `sha256` at a known `url` MUST create a new document version; the superseded version MUST be retained and its chunk IDs MUST remain resolvable | SPECIFIED | Test ingesting two byte-different payloads at one URL, asserting two versions and stable old chunk IDs |
| FR-5 | De-duplication MUST be by content hash first, then canonical URL | SPECIFIED | Test ingesting one payload under two URLs, asserting one stored document |
| FR-6 | Ingestion MUST run with no deploy or cloud credentials present in its environment | SPECIFIED | Test asserting the ingest entrypoint fails fast if deploy-credential env vars are set (`SECURITY.md` S-4) |
| FR-7 | Chunking MUST attach `document_id`, `version`, and source offsets to every chunk so a citation resolves to a byte range in a specific document version | SPECIFIED | Property test: every chunk's offsets re-extract to its stored text |
| FR-8 | Chunk boundary strategy (size, overlap, structural awareness) | UNRESOLVED (U-8) | — |

### 4.2 Retrieval and generation

| ID | Requirement | Tag | Test |
|---|---|---|---|
| FR-9 | Retrieval MUST combine a lexical arm (Postgres `tsvector` full-text) and a dense arm (pgvector KNN) and fuse them with Reciprocal Rank Fusion | SPECIFIED | Test with a seeded index asserting a document found only lexically and one found only densely both appear in the fused list |
| FR-10 | Fused candidates MUST be reranked by a cross-encoder before generation | SPECIFIED | Test asserting output order differs from fusion order for a crafted case, and that rerank is applied to exactly the configured depth |
| FR-11 | Every non-refusal answer MUST cite at least one chunk, and every cited chunk ID MUST exist in the index and have been in the reranked context passed to the generator | SPECIFIED | Test rejecting a generated answer citing an ID absent from its context |
| FR-12 | Retrieved text MUST be passed to the model inside explicit delimiters, with a system instruction declaring text inside them to be data and never instructions | SPECIFIED | Test using the injection canary document asserting the injected instruction is not followed (`SECURITY.md` S-7) |
| FR-13 | When retrieved context does not support an answer, the system MUST refuse explicitly rather than answer from parametric knowledge | SPECIFIED | Test over gold-set `answer_type: unanswerable` items asserting refusal (`EVAL_PROTOCOL.md` E-6) |
| FR-14 | Answers MUST state the issuing authority, document title or number, and date for each citation | SPECIFIED | Schema test on the citation object |
| FR-15 | RRF constant, candidate depth per arm, and rerank depth | UNRESOLVED (U-10) | — |
| FR-16 | Production embedding model and its vector dimensionality | UNRESOLVED (U-9) | — |
| FR-17 | Generator model identity | BLOCKED (U-1) — `config/models.json` holds `id: null`, `status: BLOCKED_NO_CREDENTIAL` for every hosted role | — |

### 4.3 API surface

The HTTP contract below is **PROPOSED**: it is written here for the first time and is not derived
from existing repository content beyond the boundary rule that `app/api/` owns keys and rate limits
(`AGENTS.md`). It requires sign-off before it becomes SPECIFIED. Tracked as U-13.

| ID | Requirement | Tag |
|---|---|---|
| FR-18 | `POST /v1/answer` accepts `{question: string, top_k?: int}` and returns `{answer: string, citations: [{chunk_id, document_id, version, title, authority, published_date, url, quote}], refused: bool, retrieval_ms, generate_ms, model}` | PROPOSED |
| FR-19 | `GET /healthz` returns liveness without touching the database; `GET /readyz` returns readiness only when Postgres and the model artifacts are reachable | PROPOSED |
| FR-20 | Every endpoint except `/healthz` requires an API key; keys are validated in `app/api/` only | SPECIFIED (boundary from `AGENTS.md`); key scheme PROPOSED |
| FR-21 | Requests are rate-limited per key, enforced via Redis | SPECIFIED; limit values UNRESOLVED (U-13) |
| FR-22 | Responses MUST NOT echo raw retrieved context outside the `citations[].quote` field | PROPOSED |

### 4.4 Evaluation

Normative detail lives in `docs/eval/EVAL_PROTOCOL.md`; these are the requirements it must satisfy.

| ID | Requirement | Tag |
|---|---|---|
| FR-23 | A committed gold set of **≥ 120** hand-built QA items, of which **≥ 10 %** are unanswerable and **≥ 1** is an injection canary | SPECIFIED |
| FR-24 | Every evaluation run MUST write `evals/reports/<UTC-timestamp>/{results.json,report.md,raw-judge-outputs/}` | SPECIFIED |
| FR-25 | No quality metric may be stated anywhere (README, commit, ADR, conversation) unless its raw output file exists and is referenced | SPECIFIED |
| FR-26 | Deterministic scorers MUST run on every evaluation; an LLM judge is used only for open-ended quality | SPECIFIED |
| FR-27 | A judge MUST NOT gate CI until calibrated against human labels on 60–100 items with Cohen's κ and raw agreement reported | SPECIFIED |
| FR-28 | CI MUST fail — not warn — on a > 1 pp regression on any threshold metric versus the mean of the last three baseline runs. The threshold metrics are **faithfulness ≥ 0.85**, **context precision ≥ 0.70**, **citation precision ≥ 0.90**, re-baselined at the first full run by ADR | SPECIFIED; CI job `eval-smoke` is currently `if: false` (VERIFIED in `.github/workflows/ci.yml`) |
| FR-29 | Whether a calibrated LLM judge is in scope at all | BLOCKED (U-1) |

### 4.5 User interface

| ID | Requirement | Tag |
|---|---|---|
| FR-30 | A single-page UI MUST allow submitting a question and MUST render every citation as a link to the source URL alongside the quoted span | SPECIFIED |
| FR-31 | The UI MUST visibly distinguish a refusal from an answer | SPECIFIED |
| FR-32 | The UI MUST NOT hold the API key in client-side source | SPECIFIED |

VERIFIED today: the `ui/` scaffold builds (React 19.2.8 / Vite ^8.3.0 / TypeScript ~6.0.2; 222 KB JS,
69 KB gzip) and a Playwright chromium smoke test runs. It renders the scaffold, not DocScout.

---

## 5. Non-functional requirements

| ID | Requirement | Tag | How it will be shown |
|---|---|---|---|
| NFR-1 | End-to-end query latency target **p95 < 3 s** | SPECIFIED as an objective, **unbaselined** | k6 run against the real service per `docs/QUALITY_BAR.md` Q-9 |
| NFR-2 | Any published performance number MUST come with its raw report directory and the hardware it was measured on | SPECIFIED | `loadtests/reports/<ts>/conditions.md` |
| NFR-3 | The service MUST remain correct under the measured hardware floor: 2 vCPU / 1.9 GiB RAM | VERIFIED constraint, consequence UNRESOLVED (U-14) | Load test on equivalent hardware |
| NFR-4 | Dependency resolution MUST be reproducible | **VERIFIED twice** — `uv.lock` sha256 `600c90010345412c62226029af2b86419b26821ab0a9cca30b3172fc6ee1b98d`, unchanged between Phase 0 and the 2026-10-01 rebuild. The lock holds **169** `[[package]]` entries = **168** distinct names (`torch` appears as both `2.14.1` and `2.14.1+cpu`); **164** install on linux-x86_64 — `colorama` and `tzdata` are marker-gated to Windows, `httpx2-jsfetch` is marker-gated, and `docscout` itself is never installed (`[tool.uv] package = false`). CI and `scripts/bootstrap.sh` both use `uv sync --frozen` | `make verify-setup` V5; `scripts/bootstrap.sh` |
| NFR-5 | The service MUST run on CPU only, with no GPU requirement | VERIFIED for the model tier chosen in Phase 0 — `torch 2.14.1+cpu`, embedder 112.4 sentences/s, reranker 4.56 ms/pair | `docs/setup/verify/step3-python.txt` |
| NFR-6 | All code MUST pass `ruff check`, `ruff format --check`, `mypy` in strict mode, and `pytest` before commit | VERIFIED as enforced (pre-commit + CI `quality` job; all four green on the current tree) | `docs/QUALITY_BAR.md` Q-1 |
| NFR-7 | No secret may enter the repository or its history | VERIFIED enforced — gitleaks pre-commit hook blocked a live test secret (V9) and full-history scan was clean | `docs/setup/verify/step6-precommit-secret-block.txt` |
| NFR-8 | Ingestion of the full corpus MUST be restartable and idempotent | SPECIFIED | Test: interrupt and resume yields one copy of each document |
| NFR-9 | Structured logs (`structlog`, JSON) MUST include a request ID and MUST NOT contain the full retrieved context or any API key | SPECIFIED | Log-redaction unit test |

---

## 6. Data

Authoritative detail: `docs/corpus/CORPUS_SPEC.md` and `ARCHITECTURE.md` §4.

- A **document** is one source artifact identified by the triple **(URL, fetch date, SHA-256)**.
- A **version** is a distinct SHA-256 observed at a known URL.
- A **chunk** is a retrievable span of one document version, with a stable `chunk_id`.
- VERIFIED sample: 20 documents (10 RBI, 10 SEBI), all extracting > 500 clean characters
  (951 – 47,603), criterion was ≥ 18/20, plus 1 synthetic injection canary. Evidence:
  `corpus/raw/manifest.json`, `docs/setup/verify/step8-corpus.txt`.
- The fetched corpus bytes and `evals/reports/` are **gitignored**, but `corpus/raw/manifest.json`
  **is tracked** (VERIFIED in `.gitignore`, corrected 2026-10-01 — see §2.3). Document identity,
  hashes and fetch timestamps therefore survive in the repository, and the corpus is re-derivable
  from them. This has a direct consequence for evaluation reproducibility, handled in
  `EVAL_PROTOCOL.md` §7.

---

## 7. External dependencies and their status

| Dependency | Pinned version | Status |
|---|---|---|
| Python | 3.12.14 (`requires-python = ">=3.12,<3.13"`) | VERIFIED |
| Postgres + pgvector | server 18.4, extension 0.8.2, image `pgvector/pgvector:0.8.2-pg18` | VERIFIED (0.8.6-pg18 exists upstream — K-11 drift) |
| Redis | 7-alpine | VERIFIED (`PONG`) |
| FastAPI / uvicorn | 0.142.2 / 0.54.0 | VERIFIED locked, unused |
| sentence-transformers / transformers / torch | 6.1.0 / 5.17.0 / 2.14.1+cpu | VERIFIED |
| Embedder | `BAAI/bge-small-en-v1.5`, 384 dims, 129 MB | VERIFIED runnable |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2`, 88 MB | VERIFIED runnable |
| ragas / deepeval | 0.4.3 / 4.2.7 | VERIFIED locked, unused; `openai` held at 2.54.0 by a `jiter` conflict (K-4) |
| Hosted LLM roles | none | **BLOCKED** — all `id: null` in `config/models.json`; Phase 0 API spend $0.00 |

---

## 8. Known issues inherited from Phase 0

`docs/setup/SETUP_REPORT.md` §13 records K-1 … K-17. Those IDs are stable and are referenced by ID
throughout this document set. The ones that constrain the specification rather than merely annotating
it are K-1 (no LLM keys), K-2 (no GitHub remote), K-3 (AWS unconfigured), K-8 (Postgres MCP
rejected), K-9 (no automated MCP/skill scan verdict), K-15 (2 vCPU hardware floor), K-16 (corpus
terms review), and K-17 (SEBI extraction fragility).

---

## 9. Unresolved Register

The single list of open items for the whole document set. Other documents cite these IDs and MUST
NOT restate the decision differently. Items U-1 … U-5 correspond to the five human decisions already
carried in `SETUP_REPORT.md` §15; U-6 onward are additions surfaced while writing this set.

| ID | Question | Decision needed | Evidence that resolves it | Blocks |
|---|---|---|---|---|
| **U-1** | Can an LLM judge be used at all? | Either provision `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, **or** re-scope evaluation to deterministic scorers plus a local judge and formally drop the calibrated-judge claim | Non-null `id` + `verified_at` in `config/models.json` and a response file per role in `docs/setup/model-smoke/`; or an ADR recording the re-scope | FR-17, FR-29, EVAL_PROTOCOL §4–§5, M4 |
| **U-2** | Which Postgres MCP server, if any? | A: none; B: `postgres-mcp` 0.3.0 (crystaldba); C: defer | Human-approved entry in `docs/security/mcp-server-audit.md` and the matching `.mcp.json` state | Agent tooling only |
| **U-3** | Is `.mcp.json` committed? | Keep committed (currently is) or move to an untracked local file | A line in `SECURITY.md` §6 recording the decision | Secret posture of `${GITHUB_PAT}` |
| **U-4** | Issue a `SNYK_TOKEN` for automated MCP/skill scanning? | Yes/no | A scan report under `docs/security/`, or an ADR accepting manual audit only | K-9; no automated supply-chain verdict exists |
| **U-5** | Who performs the corpus terms-of-use review? | Name an owner and complete it | A signed section in `docs/corpus/CORPUS_SPEC.md` §6 | Public deployment (M6) |
| **U-6** | Will there be a GitHub remote? | Provide a PAT and create the repo, or accept local-only | A green CI run URL (V10) | K-2, the entire CI gate story |
| **U-7** | AWS account, region, and cost cap for the demo deploy | Named account + hard budget cap before any resource is created | Billing alarm screenshot + `docs/deploys/<ts>.md` | M6 |
| **U-8** | Chunking strategy: size, overlap, structure awareness | ADR choosing a strategy, with the rejected alternatives | ADR in `docs/decisions/` + a parameter sweep report under `evals/reports/` | FR-8, and every retrieval metric |
| **U-9** | Production embedding model and vector dimensionality | ADR: local `bge-small-en-v1.5` (384 d, verified, free) vs a hosted embedder | ADR + the index DDL that fixes the column dimension | FR-16, the database schema, U-1 |
| **U-10** | RRF constant, per-arm candidate depth, rerank depth | ADR with a sweep | Sweep report + ADR | FR-15, NFR-1 |
| **U-11** | Table-bearing PDFs: table-aware extraction or accept flattening? | ADR | A measured extraction-fidelity comparison on table-heavy circulars | Numeric answer accuracy |
| **U-12** | How is supersession represented and surfaced? | Data-model decision: metadata field, link graph, or out of scope for v1 | Schema + a gold-set item that fails without it | Answer correctness on "current rule" questions |
| **U-13** | API contract: auth scheme, rate-limit values, response schema | Sign-off on §4.3 or a revision | §4.3 retagged SPECIFIED, plus contract tests | FR-18 … FR-22 |
| **U-14** | Is p95 < 3 s achievable on 2 vCPU / 1.9 GiB with rerank in the path? | Measure, then either accept, change hardware, or revise the target | A k6 report against the real service on that hardware | NFR-1, NFR-3 |
| **U-15** | How is the verified environment reproduced? | **Largely resolved 2026-10-01** (ADR-0001): `scripts/bootstrap.sh` exists and version control is restored. **Remaining:** exercise the `full` tier (Docker, Compose, Node/pnpm, k6, AWS CLI) and re-run the V1–V17 matrix | A clean machine running `bash scripts/bootstrap.sh full && make verify-setup` reaching PASS=15 / FAIL=0 / BLOCKED=2, output saved under `docs/setup/verify/` | §2.3; `make verify-setup`, `make dev` |
| **U-16** | Policy for scanned / image-only PDFs | OCR, or exclude with an explicit flag | ADR + a test over a scanned fixture | FR-3, corpus coverage |
| **U-17** | Who writes and double-labels ≥ 120 gold items, and is the persona (§3.1) validated? | Named owner and a labelling plan; single-author labelling makes κ self-agreement, which must be disclosed | A gold set at ≥ 120 items with a recorded disagreement rate | FR-23, FR-27, M3 |

---

## 10. Acceptance of this specification

This specification is accepted when §4 and §5 contain no PROPOSED tags, U-1, U-8, U-9, U-13 are
closed, and `docs/MILESTONES.md` M1 entry criteria are met. Until then it is a working document and
changes to it are ordinary commits, not ADRs — except changes that close an Unresolved Register item,
which require the evidence named in §9.
