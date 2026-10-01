# DocScout — Milestones

**Status:** authoritative delivery plan. Last updated **2026-10-01**.
**Implementation status / current position: Phase 0 complete; M0 not started.** No milestone beyond
Phase 0 has any work in it — `app/**` is empty (`SPEC.md` §2.2).

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9.

**No dates appear in this document.** Nothing in the repository establishes a schedule, a team size,
or an availability budget, so any date would be invented. Milestones are ordered by dependency, and
each has testable exit criteria.

---

## 1. Rules for this plan

1. **Milestones are gated, not aspirational.** A milestone is complete only when every exit
   criterion has a named artifact (`docs/QUALITY_BAR.md` Q-0).
2. **Each milestone closes specific Unresolved Register items.** If it closes none and resolves no
   requirement, it is not a milestone.
3. **One-way doors are front-loaded.** The embedding dimension and the chunking strategy cannot be
   changed later without a reindex and a full re-evaluation, so they are decided in M1.
4. **No milestone may claim a quality number without the artifact rules in
   `docs/eval/EVAL_PROTOCOL.md` E-13.**

---

## 2. Phase 0 — Environment — **COMPLETE** (VERIFIED)

Completed 2026-10-01, reported in `docs/setup/SETUP_REPORT.md`, signed off by the agent with the
human checkbox left open.

**What it delivered:** a pinned, verified toolchain (Python 3.12.14, uv, 169 locked packages),
Postgres 18.4 + pgvector 0.8.2 and Redis 7 running healthy under compose, CPU model tier proven
(embedder 384 d at 112.4 sentences/s; reranker 4.56 ms/pair), **corpus acquisition proven on 20
documents with 20/20 extracting > 500 chars plus an injection canary**, repository gates live (11
pre-commit hooks, gitleaks blocking a planted secret, agent command denylist 11/11 deny / 6/6
allow), a CI skeleton, a UI scaffold, and a working k6 harness.

**Result:** `make verify-setup` → **PASS=15, FAIL=0, BLOCKED=2** (V10 CI run, V11 hosted models).

**What it explicitly did not deliver:** any DocScout code. That was the point — Phase 0 was scoped
to the environment and stopped at the human gate.

---

## 3. M0 — Foundation repair — **NOT STARTED**

The smallest milestone, and the one everything else sits on. It exists because of defects found
after Phase 0 closed, not because of new scope.

**Goal:** make the verified environment reproducible and the repository safe to work in.

**Entry criteria:** none — this is the current front.

**Work and status:**

| # | Item | Status |
|---|---|---|
| 1 | Restore version control (`.git/` was absent; Phase 0 history `695e0f4` → `c88f59b` unrecoverable) | **DONE** 2026-10-01 — `git init -b master`, three commits, every one through the full hook chain, no `--no-verify`. History deliberately not fabricated (ADR-0001) |
| 2 | Write `scripts/bootstrap.sh` to reinstall the Phase 0 toolchain | **DONE** — pinned, idempotent, tiered, with `--check`. `core` tier verified: ~14 s, `uv.lock` SHA-256 unchanged at `600c9001…1b98d`, 164 packages installed, all four quality gates green |
| 3 | Add `.gitkeep` to the empty directories existing Makefile targets reference (K-14) | **DONE** for `tests/eval/` and `docs/deploys/`. `evals/reports/` deliberately left untracked — it is gitignored generated output the harness will `mkdir -p` |
| 4 | Fix the `.gitignore` defects found while staging | **DONE** — `corpus/` anchored to `/corpus/` (it was silently excluding `docs/corpus/CORPUS_SPEC.md`); `corpus/raw/manifest.json` now tracked, matching what `docs/corpus-provenance.md` already claimed |
| 5 | Create `app/main.py`, or fix `make dev` and `AGENTS.md`, which both invoke `uvicorn app.main:app` | **OPEN** — `app/main.py` does not exist, so `make dev` fails. Deliberately deferred: a module that only exists to satisfy a Makefile target is feature code without a requirement behind it. Decide at M1 alongside the API contract (U-13) |
| 6 | Exercise `bootstrap.sh full` and re-run the V1–V17 matrix | **DONE** — every tool reinstalled at its Phase 0 pin; services healthy in 6 s; matrix reproduced **PASS=15 / FAIL=0 / BLOCKED=2**. Evidence: `docs/setup/verify/m0-verify-setup-rerun.txt` |
| 7 | Fix the two defects that re-run exposed | **DONE** — `bootstrap.sh` was missing `gh`/`psql`/`jq` (V1); and all 16 shebang scripts had lost their executable bit in the snapshot and were committed that way, leaving the agent command denylist (`SECURITY.md` S-16) inert. Modes restored; `check-shebang-scripts-are-executable` added to pre-commit so it cannot recur |

**Exit criteria (all testable):**

| # | Criterion | State |
|---|---|---|
| 1 | `git log` shows the repository under version control with the seven specification documents committed through the full hook chain, no `--no-verify` | **MET** |
| 2 | `bash scripts/bootstrap.sh full && make verify-setup` reaches **PASS=15, FAIL=0, BLOCKED=2** (or better), output saved to `docs/setup/verify/` | **MET** — exit 0. Caveat recorded in the evidence: `~/.cache` persisted, so this was a rebuild-in-place, not a pristine-host run |
| 3 | `make dev` starts a server, or the target and `AGENTS.md` are corrected to match reality | **NOT MET** (item 5) |
| 4 | `make eval` and `make load` fail only for the documented stub reason, never on a missing path | **PARTIAL** — the missing-path failure is fixed; `make eval` will now fail on "no tests collected", which is the documented stub state |

**Closes:** **U-15**. **Does not close:** anything else.

**M0 is complete except exit criterion 3**, which is deliberately held for M1 so that `app/main.py`
is written against a signed API contract rather than to silence a Makefile target.

---

## 4. M1 — Decisions and data model — IN PROGRESS

**Goal:** close the one-way-door decisions and put a schema in the database.

**Entry criteria:** M0 complete.

**Work and exit criteria:**

1. ~~**ADR: embedding model and dimension**~~ — **DONE 2026-10-01, ADR-0002**, closes **U-9**.
   `bge-small-en-v1.5` at `D = 384`. A five-arm bake-off on the real corpus found no significant
   quality difference between candidates, so the choice rests on structural grounds (zero
   truncation at 512 tokens, smallest index, $0). A hosted embedder stays BLOCKED by U-1.
2. ~~**ADR: chunking strategy**~~ — **DONE 2026-10-01, ADR-0003**, closes **U-8**. Fixed-width
   1,000 chars with 150-char overlap over offset-preserved cleaned text. Overlap raises span
   integrity 0.855 → 0.965 (p = 0.0001) at no citation cost; 1,200 chars was disqualified for
   breaching ADR-0002's 512-token ceiling. Clause-aware chunking was tested and parked — it gives
   the tightest citations but loses span integrity, because pypdf preserved no layout.
3. **ADR: datastore choice**, recording Elasticsearch and dedicated vector databases as rejected
   alternatives (`ARCHITECTURE.md` §6 flags this ADR as owed). **STILL OPEN.** ADR-0004 applied
   the schema to Postgres, which deepens the commitment, but it deliberately did not argue the
   alternatives; writing that ADR after the fact must not become a rationalisation of a choice
   already made.
4. ~~**ADR: HNSW vs IVFFlat**~~ — **DONE 2026-10-01, in ADR-0004.** HNSW, because IVFFlat needs a
   training corpus up front and rebuilds as data grows, which fits incremental ingestion badly.
   Decided on structure, not measurement: at ~170 chunks the difference is unmeasurable, and
   `m = 16 / ef_construction = 64` are pgvector's defaults held deliberately pending U-10.
5. ~~**Schema migration**~~ — **DONE 2026-10-01, ADR-0004.** `migrations/0001_initial_schema`
   applied to the compose database (PG 18.4 / pgvector 0.8.2) in 28 ms; `documents`,
   `document_versions`, `chunks` with HNSW and GIN. 19 tests in `tests/test_schema.py`, including
   the required FR-4 test that `chunk_id` resolves after its version is superseded. Three
   constraints were mutation-checked to prove they are load-bearing, and the runner's four claimed
   properties — serialisation, atomicity, drift detection, reversibility — were each exercised
   rather than assumed. Evidence: `docs/setup/verify/m1-schema-migration.txt`.
6. **Sign-off or revision of the API contract** in `SPEC.md` §4.3 — closes **U-13** and retags it
   SPECIFIED.

**Exit criteria:** four ADRs committed; migration applied and tested; `SPEC.md` §4.3 carries no
PROPOSED tags; `SPEC.md` §9 shows U-8, U-9, U-13 closed with evidence. **Items 1, 2, 4 and 5 are
done (ADR-0002, ADR-0003, ADR-0004); U-8 and U-9 are closed. Remaining: item 3 (datastore ADR)
and item 6 (API contract, U-13).**

---

## 5. M2 — Ingestion at scale — NOT STARTED

**Goal:** turn the proven 20-document fetch into a real pipeline.

**Entry criteria:** M1 complete (chunking and embedding dimension are fixed).

**Work:** implement `app/ingest/` — fetch (host allowlist, C-1), extract (PDF + SEBI iframe
following, C-2), the < 500-char guard (C-11), chunking, embedding, transactional store; decide the
corpus date window (C-3) and target size (C-5).

**Exit criteria:**

1. Full corpus ingested; `corpus/raw/manifest.json` records **every** attempt including failures
   (C-22).
2. Tests pass for: off-allowlist rejection, SEBI stub-page rejection, hash-based dedup, new-version
   creation with stable old chunk IDs, idempotent re-run performing no writes (NFR-8).
3. A test asserts the ingester refuses to start with deploy credentials in the environment (S-4).
4. Row counts for documents, versions, and chunks recorded as evidence.

**Closes:** C-3, C-5. **Decides or defers with an ADR:** U-11 (tables), U-16 (scanned PDFs),
U-12 (supersession).

**Risk:** the RBI archive may contain a material share of scanned PDFs. C-11 makes that visible as
a flagged-document count rather than silent data loss — the count is itself an M2 deliverable.

---

## 6. M3 — Gold set v1 — NOT STARTED

**Goal:** build the measuring instrument before the thing it measures is tuned.

**Entry criteria:** M2 complete — chunk IDs must be stable, since gold items reference them (E-7).

**Work:** hand-build **≥ 120** QA items to the schema in `EVAL_PROTOCOL.md` §2.1, with **≥ 10 %**
unanswerable and **≥ 1** injection canary; two-pass labelling plus a disagreement review; record the
disagreement rate; mark surviving items `stable: true`; commit the set with a `goldset_version` and
a `CHANGELOG.md` entry.

**Exit criteria:** the set exists at ≥ 120 items and passes a gold-set lint that enforces the scope
rule (E-5) and the schema; the disagreement rate is recorded; if one person did both labelling
passes, the report says so explicitly (E-6 disclosure).

**Closes:** U-17. **Blocks:** everything downstream — without this there is no number.

---

## 7. M4 — Retrieval and the live quality gate — NOT STARTED

**Goal:** hybrid retrieval, measured, with CI enforcing regressions.

**Entry criteria:** M3 complete.

**Work:** implement `app/retrieval/` (lexical arm, dense arm, RRF fusion, cross-encoder rerank) and
`app/evals/` layer-1 deterministic scorers; run the three required ablations
(`EVAL_PROTOCOL.md` §8.1); close **U-10** with a sweep ADR; flip `eval-smoke` from `if: false` to
enforcing.

**Exit criteria:**

1. First full baseline run written to `evals/reports/<ts>/` with all E-14 pinning fields.
2. recall@k, MRR, nDCG, citation precision/recall reported with their artifact.
3. Lexical-arm and rerank ablations reported — if the lexical arm adds nothing, remove it
   (`ARCHITECTURE.md` §8).
4. `eval-smoke` enforcing the **> 1 pp** regression gate against baseline (Q-12).
5. **U-1 decided.** Either keys are provisioned and judge calibration begins, or the project
   formally re-scopes to deterministic plus local scoring and drops the calibrated-judge claim in
   writing (`EVAL_PROTOCOL.md` §4.1). Carrying U-1 past M4 is not permitted — it determines what
   M5 is allowed to claim.

**Closes:** U-10, U-1.

---

## 8. M5 — Generation, API, UI — NOT STARTED

**Goal:** an answer a compliance analyst can check.

**Entry criteria:** M4 complete.

**Work:** implement `app/generate/` (delimiter discipline S-7, mandatory citations FR-11,
server-side citation validation S-9, refusal FR-13); implement `app/api/` to the M1-signed contract
with key auth and Redis rate limiting; build the UI to FR-30 … FR-32; if U-1 resolved toward keys,
execute judge calibration (`EVAL_PROTOCOL.md` §5).

**Exit criteria:**

1. Citation validation test: an answer citing an out-of-context chunk ID is rejected.
2. Canary test: the injected instruction is not followed, scored in the eval run.
3. Unanswerable items produce refusals, scored as PASS.
4. API contract tests pass; a request without a key is rejected; the rate limiter is demonstrated.
5. UI renders citations as links to source URLs and visibly distinguishes refusals.
6. Faithfulness reported **only** if §5 calibration actually ran; otherwise the re-scope decision
   from M4 is honoured and the metric is absent, not estimated.

---

## 9. M6 — Load baseline and deployment — NOT STARTED

**Goal:** know what it costs and what it can take, before anyone depends on it.

**Entry criteria:** M5 complete; **U-7 resolved** (account, region, hard cost cap).

**Work:** k6 against the real service, replacing the stub harness; close **U-14** with a measured
answer on p95 < 3 s; complete the corpus terms review and determine RBI's crawl directives
(**U-5** / C-17); implement `make deploy` and `make destroy` to `SECURITY.md` S-14 — cost cap and
billing alarm **first**, least-privilege runtime identity, image digest and IaC hash recorded to
`docs/deploys/<ts>.md`.

**Exit criteria:**

1. `loadtests/reports/<ts>/` against the real service, with `conditions.md` naming the hardware.
2. NFR-1 either met, or revised by ADR with the measurement that justified the revision.
3. `make destroy` demonstrated to leave zero resources, verified with provider list commands whose
   empty output is committed as evidence.
4. Terms review signed in `CORPUS_SPEC.md` §6.
5. A disclosure contact exists (`SECURITY.md` §6).

**Closes:** U-5, U-7, U-14, and the disclosure gap.

---

## 10. Dependency map

```
Phase 0 ✔ ─► M0 foundation repair (U-15)
                 └─► M1 decisions + schema (U-8, U-9, U-13)
                        └─► M2 ingestion at scale (C-3, C-5; U-11/U-12/U-16 decided or deferred)
                               └─► M3 gold set ≥120 (U-17)
                                      └─► M4 retrieval + live CI gate (U-10, U-1)
                                             └─► M5 generation + API + UI
                                                    └─► M6 load + deploy (U-5, U-7, U-14)

independent, resolvable at any time:  U-2 (Postgres MCP) · U-3 (.mcp.json) ·
                                      U-4 (SNYK_TOKEN) · U-6 (GitHub remote)
```

U-6 deserves a note: until a remote exists, **no CI job has ever run** (K-2, V10 BLOCKED), so every
gate in `docs/QUALITY_BAR.md` §2.2 is locally-enforced only. It is cheap to resolve and it changes
the credibility of every milestone after it.

---

## 11. Next action

M0 is done apart from exit criterion 3, which is held for M1 on purpose.

**Done: ADR-0002 (U-9), ADR-0003 (U-8) and ADR-0004 (schema + HNSW) are closed.** The data model
is no longer a proposal — it is three tables in the live database, with 19 tests asserting that it
*refuses* what the specification forbids. M1 items 1, 2, 4 and 5 are complete.

Two items remain in M1: **item 3, the datastore ADR**, and **item 6, the API contract (U-13)**.

**The API contract is the right next action.** It is the larger of the two and it blocks more:
`SPEC.md` §4.3 is still PROPOSED, `app/main.py` does not exist so `make dev` fails (M0 exit
criterion 3, deliberately parked for exactly this moment), and M2's ingestion work will want to
know what shape a citation takes on the wire. The schema just fixed the server-side half of that
contract — `chunk_id`, offsets, version identity are now concrete — which makes this the cheapest
it will ever be to specify the client-side half.

The datastore ADR is a smaller, backward-looking piece of writing: the decision is already made
and now implemented. It should still be written, because `ARCHITECTURE.md` §6 records it as owed
and because the rejected alternatives matter to a future reader — but it must be honest that it
documents a settled choice rather than deliberates an open one.

One caveat carried forward from ADR-0004: the schema is applied but **no data has ever been
written to it by real code**. The tests insert synthetic and real-corpus-derived rows, which is
not the same as the ingestion pipeline proving the model survives contact with M2.
