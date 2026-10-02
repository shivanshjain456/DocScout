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

## 5. M2 — Ingestion at scale — SUBSTANTIALLY COMPLETE

**Goal:** turn the proven 20-document fetch into a real pipeline.

**Entry criteria:** M1 complete (chunking and embedding dimension are fixed).

**Work:** implement `app/ingest/` — fetch (host allowlist, C-1), extract (PDF + SEBI iframe
following, C-2), the < 500-char guard (C-11), chunking, embedding, transactional store; decide the
corpus date window (C-3) and target size (C-5).

**Exit criteria:**

1. ~~Full corpus ingested~~ — **DONE 2026-10-01.** 21 documents, 170 chunks, 0 failures, 41.0 s.
   The manifest already records every attempt (C-22).
2. ~~Tests~~ — **DONE.** 37 tests in `tests/test_ingest.py`: off-allowlist rejection (plus
   userinfo smuggling and **redirect** escape, which a URL-only check misses), stub-page
   rejection, hash-first de-duplication, new-version creation with stable old chunk IDs,
   and an idempotent re-run that writes nothing.
3. ~~Deploy-credential refusal~~ — **DONE.** Four tests, including that the error names the
   variable but never echoes its value.
4. ~~Row counts as evidence~~ — **DONE.** `docs/setup/verify/m2-ingestion.txt`, with the raw
   run reports under `docs/corpus/evidence/`.

**Still open in M2:** the corpus is the 21 documents Phase 0 fetched, not a refreshed crawl,
so the date window (C-3) and target size (C-5) are not yet decided; and `title` /
`published_date` are NULL, which leaves FR-14 unsatisfiable (see ARCHITECTURE §3.1).

**Closes:** C-3, C-5. **Decides or defers with an ADR:** U-11 (tables), U-16 (scanned PDFs),
U-12 (supersession).

**Risk:** the RBI archive may contain a material share of scanned PDFs. C-11 makes that visible as
a flagged-document count rather than silent data loss — the count is itself an M2 deliverable.

---

## 6. M3 — Gold set v1 — **DONE** (2026-10-01)

**Goal:** build the measuring instrument before the thing it measures is tuned.

**Entry criteria:** M2 complete — chunk IDs must be stable, since gold items reference them (E-7).

> **This entry criterion was not met when M2 was declared complete, and nobody noticed.**
> `chunks.chunk_id` was `DEFAULT uuidv7()`, minted from the clock at insert time, so re-ingesting
> the identical corpus produced **0 of 170** matching identifiers. The criterion was written
> correctly and then not checked. It was caught only by starting M3 and asking what the gold
> set's foreign keys actually point at. **ADR-0005** makes the identifier content-derived
> (`uuid5` over the version hash and the character span); the same experiment now produces
> **170 of 170**. Evidence: `docs/decisions/evidence/adr-0005-chunk-id-stability.txt`.
>
> The lesson is recorded rather than tidied away: an exit criterion that is never executed is a
> sentence, not a gate. M2's criteria were all verified by running something; this one belonged
> to M3 and was verified by nobody.

**Work completed:** 153 items (floor 120) to the `EVAL_PROTOCOL.md` §2.1 schema, over all 21
corpus documents — 87 extractive, 40 numeric, 4 multi-hop, 22 unanswerable (14.4 %, floor 10 %)
and 3 injection canaries. Two-pass labelling with the disagreement rate recorded, and
`stable: true` on the 130 items the review left unchanged.

**How the items are anchored, and why it matters.** No item was authored against a chunk ID.
Each answerable item carries verbatim `evidence_quotes`; `make gold-pin` resolves them to chunk
IDs through the same chunker the ingester uses. Re-pinning after a chunk-size change is a
command, stale IDs fail `make gold-lint` and the suite, and the whole set validates **with no
database** — verified by stopping Postgres and linting clean, with all 72 distinct cited IDs
still matching the ingested database exactly.

**Exit criteria — met.**

| Criterion | Result |
|---|---|
| ≥ 120 items | **153** |
| ≥ 10 % unanswerable | **22, 14.4 %** |
| ≥ 1 injection canary | **3** |
| Passes a lint enforcing the schema and the scope rule (E-5) | **clean**; the E-5 check first *failed* 4 items whose quotes appeared verbatim in all three near-identical InvIT/REIT circulars, which were rewritten |
| Disagreement rate recorded | **23 of 131 answerable items, 17.6 %**, all corrected; 1 residual disclosed |
| E-6 disclosure if one person did both passes | **stated in `metadata.json`, in `EVAL_PROTOCOL.md` §E-6 and in the evidence file**: self-agreement, not inter-rater reliability; no Cohen's κ reported, and a test asserts none is claimed |

**Closes:** U-17 (authored and labelled by the DocScout agent, disclosed as such).

**Deliberately still open:** the corpus is Phase 0's 21 documents, so topical coverage is narrow
while C-3 and C-5 are undecided; §5 human double-labelling is not done, so no κ exists for any
judge; and no retrieval or generation metric has been measured. **This milestone produced the
ruler, not a measurement.**

**Evidence:** `docs/setup/verify/m3-goldset.txt` · `evals/gold/v1/metadata.json` · ADR-0005.

---

## 7. M4 — Retrieval and the live quality gate — PARTIALLY COMPLETE

**Goal:** hybrid retrieval, measured, with CI enforcing regressions.

**Entry criteria:** M3 complete. Met — and unlike the M2→M3 transition, checked rather than
assumed: the gold set's 72 cited chunk IDs were re-resolved against a database rebuilt from
nothing on a different Postgres install, 72/72.

**Status, honestly (2026-10-01).** Exit criteria 1 and 2 are met for *retrieval*. Criterion 3 is
met for the lexical/dense ablation and deliberately deferred for rerank. Criteria 4 and 5 are
NOT met. M4 is therefore not complete, and is not recorded as complete.

| # | Exit criterion | State |
|---|---|---|
| 1 | Baseline run with E-14 pinning fields | **DONE** — `evals/reports/20261001T192924Z/`, committed |
| 2 | recall@k, MRR, nDCG with their artifact | **DONE** for retrieval; citation precision/recall need a generator, so they are absent, not estimated |
| 3 | Lexical and rerank ablations | **PARTIAL, extended** — dense/BM25/hybrid A/B (ADR-0006) plus a full RRF-constant sweep (ADR-0007, U-10 partially closed); rerank still deferred with a reason, and ADR-0007 records why a reranker could not have fixed g-038 at all — dense/BM25/hybrid A/B done (ADR-0006); rerank deferred with a reason, not forgotten (recall@10 ≈ 0.98 leaves a reranker nothing to recover on a 170-chunk corpus) |
| 4 | `eval-smoke` enforcing the >1pp gate | **DONE, with one honest caveat** — `make eval-gate` enforces the rule and fails the build (exit 1, drilled against a real 1.90pp degradation); the CI job is written and pinned but has never run, because there is no remote (V10 BLOCKED), so no badge is claimed. The gate reports that 1pp sits below the gold set's 3.24pp noise floor rather than silently widening the threshold. Evidence: `docs/setup/verify/m4-eval-gate.txt` |
| 5 | U-1 decided | **NOT DONE** — no API keys; the formal re-scope is still owed in writing |

**What the baseline actually showed, recorded because it is inconvenient.** The ablation did not
produce a winner. Every pairwise 95 % bootstrap CI includes zero, and the gold set leaks 73.3 % of
each question's terms into its own gold chunk (9.4 % for a random chunk), which flatters the
lexical arm by 7.8×. §8.1's instruction "if the lexical arm adds nothing, remove it" cannot be
executed on this evidence in either direction, and acting on it would have deleted the dense arm
on the strength of a one-item difference. Hybrid is kept, the reasoning is in ADR-0006, and the
decisive experiment is **U-18**.

**Remaining work:** close U-1 in writing; grow the corpus and the gold set so the gate stops
operating at single-item resolution; U-18; then the reranker ablation.

**Also landed with the gate (2026-10-02):** the corpus payloads are now tracked in git. The
manifest alone did not make them re-derivable — the corpus contains withdrawn circulars, and
`make eval` is only a reproduction command if `make ingest` can run offline. 7.8 MB; the
manifest still governs, since ingest rejects any file whose hash disagrees with it.

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

## 8. M5 — Generation, API, UI — API DONE, GENERATION DEFERRED

**Goal:** an answer a compliance analyst can check.

**Entry criteria:** M4 complete. Partially met — M4's criteria 1–3 are done; criteria 4 (the
CI gate) landed on 2026-10-02; criterion 5 (U-1) is still owed in writing.

**Status, honestly (2026-10-02).** The API half of this milestone is built and measured. The
generation half is deliberately not, and ADR-0008 records why: there are no LLM keys (U-1),
there is no calibrated judge, and prose that nothing measures is the one thing this project
must not ship. The endpoint serves retrieved evidence instead, which is exactly what the
eval harness scores.

| # | Exit criterion | State |
|---|---|---|
| 1 | Citation validation: an out-of-context chunk id is rejected | **N/A by design** — nothing generates citations to validate. The stronger property holds instead: every returned passage IS a stored chunk, and `test_search_returns_checkable_citations` re-reads each one from the database and compares text and span |
| 2 | Canary test: the injected instruction is not followed | **N/A by design** — no model reads the retrieved text, so there is nothing to inject into. The canary documents remain in the corpus and the gold set for when generation lands |
| 3 | Unanswerable items produce refusals | **NOT DONE** — refusal is a generation behaviour |
| 4 | API contract tests; keyless request rejected; rate limiter demonstrated | **DONE** — 35 tests in `tests/test_api.py`; 401 without a key, 401 with a wrong key (indistinguishable), 429 past the limit with `Retry-After`, all asserted |
| 5 | UI renders citations as links and distinguishes refusals | **PARTIAL** — the demo page at `/` renders citations with source links, chunk ids and character spans; refusals do not exist to distinguish |
| 6 | Faithfulness only if §5 calibration ran | **HONOURED** — no faithfulness figure is published anywhere, and the README lists it as absent with the reason |

**Not built, and deliberately:** Redis-backed rate limiting (in-process is correct for one
worker, and `/healthz` says `single_process: true` so the limitation is visible rather than
assumed), and a deployed public URL (no cloud resources are created by this project).

**Also landed:** measured serving cost and latency — cold p95 51.43 ms, warm p95 3.16 ms,
caching worth 16.3x, 37.0 q/s, ~$0.08 per million queries. `scripts/bench_api.py`, raw
output under `evals/bench/`.

**Remaining work:** close U-1 in writing; then generation behind the same endpoint, shipped
only once the judge is calibrated with Cohen's κ reported.

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
                               └─► M3 gold set 153 items — DONE (U-17 closed)
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

**Done: ADR-0002, ADR-0003, ADR-0004, and the M2 ingestion pipeline.** The index is no
longer empty — 170 chunks of real RBI and SEBI text, every one carrying offsets that
re-extract to its source PDF, every embedding a 384-dimension unit vector, and the
injection canary sitting in the index as a retrievable distractor.

**The next action is the evaluation harness, starting with the gold set.**

That is a change of direction from the previous entry here, which named the API contract,
and the reason is that ingestion changed what is possible rather than what is desirable.
A gold set requires `required_citation_chunk_ids` that point at chunks which exist; until
this run there were none, so the single highest-value artefact in the project was blocked
on something that is now done. Everything downstream — the regression gate (FR-28), the
judge calibration (FR-27), any A/B between retrieval configurations — is blocked on the
gold set and on nothing else.

The order that follows from that:

1. **Gold set** (FR-23): ≥ 120 hand-built QA items over the 170 chunks, ≥ 10% unanswerable,
   ≥ 1 injection canary, each with required-citation chunk IDs. U-17 asks who authors it;
   the honest answer is that it is authored here and labelled as such.
2. **Retrieval** (FR-9, FR-10): hybrid BM25 + dense + RRF, then the cross-encoder. Both
   arms are already demonstrated working against the live index (ARCHITECTURE §3.1).
3. **Deterministic scorers first** (FR-26): citation precision and recall need no LLM and
   are therefore not blocked by U-1, unlike faithfulness.

The API contract (U-13) stays open and drops below these. It is a precondition for a
deployed demo, not for a measured one, and the schema has already fixed its server-side
half.

**Carried forward:** `title` and `published_date` are NULL for every document, so FR-14 —
a citation stating authority, title and date — cannot currently be satisfied. The gold set
should cite by `chunk_id`, which is stable, rather than depending on titles that do not
yet exist.
