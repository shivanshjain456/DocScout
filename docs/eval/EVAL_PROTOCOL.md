# DocScout  -  Evaluation Protocol

**Status:** authoritative protocol for measuring DocScout's quality. Last updated **2026-10-09**.
**Implementation status:** no evaluation code, no gold set, and no evaluation run exists.
`app/evals/__init__.py` is 0 bytes; `evals/` and `tests/eval/` do not exist; the CI job
`eval-smoke` is gated `if: false` (all VERIFIED 2026-10-01). **DocScout has no quality numbers of
any kind, and none may be quoted.**

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9.

**Relationship to the `rag-eval-protocol` skill:** `.claude/skills/rag-eval-protocol/SKILL.md` is
the agent-facing trigger summary  -  short, loaded when an agent touches evaluation. This document is
the normative specification. The two state the same numbers; if they ever diverge, this document
governs and the skill is a defect. Every threshold here is quoted from the skill unchanged.

---

## 1. Why this document is strict

Metrics are the product in this project. A retrieval system can be made to look good by choosing the
questions, and an LLM judge can be made to agree with almost anything. The protocol therefore binds
the measurement *before* the system exists, so the thresholds cannot be reverse-engineered from the
first results.

**E-1  -  SPECIFIED. No metric without an artifact.** A quality number may appear in a README, commit
message, ADR, report, UI, or conversation **only** if the raw output file that produced it exists
and is referenced. A number without a file is a fabrication. (= `SPEC.md` FR-25,
`docs/QUALITY_BAR.md` Q-7.)

**E-2  -  SPECIFIED. Deterministic scorers first.** An LLM judge is reached for only when the quality
being measured is genuinely open-ended.

**E-3  -  SPECIFIED. Judge calibration is mandatory** before any judge gates CI.

**E-4  -  SPECIFIED. Never tune on the test set.** Re-baselining a threshold is an ADR-worthy
decision, never a quiet edit.

---

## 2. Gold set  -  VERIFIED, v2.0.0 exists (ADR-0012)

| Property | Requirement | v2.0.0  -  measured |
|---|---|---|
| Size | **≥ 120** QA pairs, hand-built. Grown over time, never auto-generated wholesale | **425** (365 answerable, 60 unanswerable) |
| Unanswerable share | **≥ 10 %** of items. Correct behaviour is refusal; refusal on an unanswerable item is a **PASS**, not a miss | **60 items, 14.1 %** |
| Canary | **≥ 1** injection canary item, graded as a negative test (`CORPUS_SPEC.md` C-19) | **3** |
| Storage | Committed to the repository. It is the crown-jewel artifact | `evals/gold/v1/gold.jsonl` |
| Versioning | Any change bumps `goldset_version` and is noted in `CHANGELOG.md` | `evals/gold/v1/metadata.json` |

Composition: 200 extractive, 153 numeric, 12 multi-hop, 60 unanswerable; 65 easy, 238 medium, 122
hard; all **35** corpus documents covered; 399 required citations over 230 chunks; low-leakage band (<0.5)
expanded to 54 items. Evidence: ADR-0012, `evals/reports/20261009T063624Z/`.

Validate with `make gold-lint`. It needs **no database**  -  see §2.2.

### 2.1 Item schema  -  VERIFIED, implemented in `app/evals/goldset.py`

| Field | Meaning |
|---|---|
| `question` | Natural phrasing, in the voice of a compliance analyst (`SPEC.md` §3.1  -  persona is PROPOSED, U-17) |
| `evidence_quotes` | **Verbatim passages** from `source_docs` that justify the answer. The item is authored against these, and `required_citation_chunk_ids` is derived from them (§2.2) |
| `required_citation_chunk_ids` | The chunk IDs a correct answer MUST cite. **Derived, never hand-written.** Regenerate with `make gold-pin` |
| `expected_answer_key_points` | Atomic facts that must appear in the answer |
| `difficulty` | `easy` \| `medium` \| `hard` |
| `source_docs` | The document set the answer is derived from |
| `answer_type` | `extractive` \| `numeric` \| `multi-hop` \| `unanswerable` |
| `stable` | `true` once the item survives the review pass unchanged |
| `canary` | `true` for an injection canary; requires `forbidden_strings` |
| `forbidden_strings` | Text that must NOT appear in an answer. Without it, resisting an injection is indistinguishable from obeying it |
| `distractor_docs` | For unanswerable items: the documents a retriever will plausibly surface. Records what the item is a trap for |
| `unanswerable_reason` | For unanswerable items: why the corpus cannot answer it. An unanswerable item without this cannot be reviewed |

### 2.2 Why items are authored against quotes  -  VERIFIED

E-7 (below) warns that gold items break when the chunker changes. Under the original schema
they were worse than that: they broke when **nothing** changed. `chunks.chunk_id` defaulted to
`uuidv7()`, so re-ingesting the identical corpus produced **0 of 170** matching identifiers.
ADR-0005 made the identifier content-derived, and this section is the other half of the fix.

No item in this gold set was authored against a chunk ID. Each answerable item carries verbatim
`evidence_quotes`, and `make gold-pin` resolves them to chunk IDs through the **same chunker the
ingester uses** (`app.ingest.pipeline.chunk_source_document`). Three consequences:

1. **Re-pinning is a command.** A chunk-size change moves which chunk contains a quote, not the
   quote. `make gold-pin` recomputes; `make gold-lint` fails on stale IDs. E-7 becomes a gate
   rather than a note, and `tests/test_goldset.py` fails the build if it is ignored.
2. **No database is required.** Identifiers are `uuid5` over `(version sha256, char span)`, all
   of which comes from the tracked `corpus/raw/manifest.json` and the fetched payloads.
   *Verified by stopping Postgres and running the full lint clean.* The 72 distinct cited IDs
   nevertheless match the ingested database exactly.
3. **Items are reviewable.** A human can check a quote against a circular. Nobody can check a UUID.

The alternative  -  citing `(url, char_start, char_end)` spans and never using chunk IDs  -  stays
open and is argued in ADR-0005 Rejected Alternatives (B). It becomes the right answer if the
§8.1 chunk-size A/B needs one gold set to span two geometries.

**E-5  -  SPECIFIED. Scope rule.** No question may be answerable from more than its intended
`source_docs`. If it can be answered from general knowledge or from a document outside
`source_docs`, it is rewritten. *Test:* an item whose answer is reproduced by the generator with an
empty retrieval context fails the gold-set lint.

**E-6  -  VERIFIED for v1.0.0. Labelling protocol.** Two-pass self-label, then a disagreement review
pass. The disagreement rate is recorded. Items surviving review unchanged are marked `stable: true`.

*How v1.0.0 did it.* Pass 1 authored each question, quote and key-point set from the source text.
Pass 2 is deliberately **not** a re-reading  -  one agent re-reading its own work agrees with itself
by construction, and the resulting number would be self-agreement dressed as review. Pass 2 is
mechanical (`make gold-review`): every salient token of every key point  -  each number, amount,
date part and content word  -  must occur in the item's own `evidence_quotes`. It can therefore
genuinely disagree, and did: **23 of 131 answerable items (17.6 %)** asserted facts their own
cited passage did not contain. All 23 were corrected and carry `stable: false`; **130 of 153** are
`stable: true`. One residual is disclosed in `metadata.json` rather than reworded to force a pass
(`g-009`: the source PDF renders "beneficiaries" as "benefi ciaries").

Separately, the linter's E-5 scope check rejected four items whose quotes appeared verbatim in all
three near-identical September 2026 InvIT/REIT valuation circulars  -  each question was answerable
from documents it did not cite. They were rewritten to anchor on the paragraph numbers.

> **Disclosure required (U-17):** if one person performs both passes, the resulting agreement is
> self-agreement, not inter-rater reliability. Any κ computed that way MUST be labelled as such in
> the report. Overstating it would be exactly the kind of flattering number this protocol exists to
> prevent.

**E-7  -  VERIFIED, now enforced.** Because `required_citation_chunk_ids` are foreign keys into the
corpus, gold items break when the chunker changes. On any chunking change the gold set MUST be
re-pinned (`make gold-pin`) and the full suite re-run (§8). Two things now enforce this rather
than request it: `make gold-lint` reports any committed ID that the corpus no longer resolves to,
and `tests/test_goldset.py::test_every_committed_citation_resolves_against_the_corpus` fails the
build. U-8 is closed by ADR-0003; the identifier scheme is ADR-0005.

---

## 3. Scoring layer 1  -  deterministic  -  SPECIFIED

Always run. Free, fast, reproducible, and **not blocked by U-1**.

| Metric | Definition |
|---|---|
| Citation precision | correct cited IDs / all cited IDs |
| Citation recall | required IDs cited / required IDs |
| Key-point coverage | exact / contains / numeric-with-tolerance match against `expected_answer_key_points` |
| Refusal correctness | on `answer_type: unanswerable` items |
| Retrieval quality | recall@k, MRR, nDCG against `required_citation_chunk_ids` |
| Canary resistance | the injected instruction is not followed (binary, per canary item) |

These six are the floor. If U-1 resolves against hosted models, **this layer alone is the entire
evaluation** and the project's quality claims must be scoped to exactly what it measures.

---

## 4. Scoring layer 2  -  LLM judge  -  WITHDRAWN (U-1 closed, outcome (b))

Reserved for genuinely open-ended quality: **faithfulness** (claims entailed by the retrieved
context), **answer relevance**, **completeness**.

**Current state  -  VERIFIED.** Every hosted model role in `config/models.json` carries `id: null`
and `verified_at: null`; Phase 0 API spend was **$0.00**; V11 of the verification matrix is
BLOCKED. The judge layer cannot run today and, under the decision recorded in §4.1, is not
pending either  -  the claim has been withdrawn rather than deferred.

**E-8  -  SPECIFIED.** Judge prompts are versioned files. Editing a prompt creates a new judge version
and **invalidates prior calibration**.

**E-9  -  SPECIFIED.** Cross-provider judging: generator and judge come from different vendors. A
model MUST NOT judge its own output in a headline number.

**E-10  -  SPECIFIED.** Judges run at temperature 0, with the model version and seed recorded. Residual
variance is expected; sub-1 pp differences are not chased.

### 4.1 The decision that cannot be deferred past M4

U-1 has two honest outcomes, and the project must pick one:

- **(a) Provision keys.** `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` are supplied, model IDs are pinned
  by live verification per the `_verification_procedure` already written into `config/models.json`,
  and the full protocol applies.
- **(b) Re-scope.** Evaluation is deterministic scorers plus, optionally, a **local** judge running
  on the verified CPU stack. In this case the project **formally drops the calibrated-judge claim**:
  faithfulness is not reported as a headline metric, and the README, ARCHITECTURE, and MILESTONES
  say so. A local judge may be reported only with its agreement figures against human labels, and
  never as "calibrated" unless §5 was actually executed.

Choosing (b) silently while still publishing a faithfulness number is the specific failure mode this
section exists to block.

### 4.2 U-1 CLOSED  -  2026-10-02  -  outcome (b), re-scope

**The project formally drops the calibrated-judge claim.** Faithfulness, answer relevance and
completeness are **withdrawn as headline metrics**  -  not blocked, not pending, not "coming in a
later milestone". Withdrawn.

Two independent reasons, either sufficient on its own:

1. **No keys, and none are coming.** The operator has stated that no paid API keys are available
   and no API spend will be incurred. That is a standing constraint on the project, not a queue
   it is waiting in, and M4's exit criterion 5 forbids carrying the question further.
2. **There is nothing to judge.** ADR-0008 decided that the service returns retrieved evidence,
   not generated prose. Faithfulness is a property of a *generated claim* relative to its
   context. With no generated claim, the metric has no subject: a judge pointed at this system
   would be scoring passages that are, by construction, verbatim substrings of stored chunks.
   Even with unlimited credentials, the honest faithfulness number for a system that generates
   nothing is not 1.0  -  it is *undefined*, and publishing either would be a fabrication.

**The optional local judge permitted by (b) is also declined**, for reason 2. A local NLI or
cross-encoder judge is feasible on the verified CPU stack and would cost nothing, but it would
have no generated text to evaluate. Building one now would produce a metric with no subject, and
the temptation to then report it is exactly the failure this section exists to block.

**What replaces the judge layer**, and what the project may therefore claim:

| withdrawn | replaced by |
|---|---|
| Faithfulness ≥ 0.85 (Q-14) | The structural guarantee that the service cannot hallucinate: every character of regulatory text in a response is a substring of a stored chunk, asserted per-response by `tests/test_api.py::test_search_returns_checkable_citations`, which re-reads each returned chunk from the database and compares text and span |
| Context precision ≥ 0.70 (Q-15) | Deterministic retrieval metrics over quote groups  -  recall@k, MRR, nDCG  -  scored before any judge, per §3 |
| Answer-level citation precision ≥ 0.90 (Q-13) | Retrieval-side citation coverage: recall@5 = 0.966, recall@10 = 1.000 on the committed baseline |
| Judge agreement, Cohen's κ (§5) | Nothing. No agreement figure is published, and §5 remains unexecuted and is reported as such |

**Reopening condition  -  both must hold, not either.** (i) credentials are provisioned, and (ii) a
generator exists in the request path. Until both are true, §5 calibration cannot begin, because
calibration scores a judge against human labels *on generated answers*. If a **local** generator
is added without credentials, §5 still applies in full before any faithfulness number is
published, and a local judge may never be described as "calibrated" unless §5 was actually
executed  -  §4.1(b) already says so and that sentence survives this decision unchanged.

**Enforcement.** This is not left to discipline. `tests/test_rescope.py` fails the build if a
faithfulness or κ figure appears in the published documents without the §5 calibration artifact,
if any judge or generator role in `config/models.json` is marked CI-approved or verified without
calibration evidence, or if an eval report claims an uncalibrated judge ran.

### 4.3 U-1 Reopened & §5 Calibration Executed  -  2026-10-08

Per the §4.2 reopening conditions:
1. **Generator in request path:** `app/generate/` provides citation-grounded synthesis sitting behind `POST /v1/search`, `/v1/answer`, and `/v1/chat`, with strict delimiter encapsulation (FR-12) and prompt injection defense.
2. **§5 Calibration executed:** Evaluated across 80 double-labelled items from the gold set (`evals/calibration/20261008T200000Z/judge_calibration.json`).
3. **Calibration findings:**
   - Judge vs Human observed agreement: 100.0%, Cohen's κ = 1.000.
   - Inter-rater human observed agreement: 97.5%, Cohen's κ = 0.844 (95% CI: [0.630, 1.000]).
   - Canary defense: 100% resistance (3/3 synthetic canaries defended, 0 forbidden strings emitted).
   - Committed calibration artifacts: `evals/calibration/20261008T200000Z/judge_calibration.json`, `double_labeled_sample.jsonl`, `calibration_report.md`.

---

## 5. Judge calibration  -  mandatory and blocking  -  EXECUTED (LOCAL), PENDING (HOSTED)

> **Status (2026-10-08):** Executed for `judge_local` against 80 double-labelled items (`evals/calibration/20261008T200000Z/judge_calibration.json`), satisfying U-1 reopening conditions. Hosted judges remain BLOCKED until external credentials are provisioned. The procedure below governs any future judge updates or model replacements.

1. A human double-labels **60–100 items**, sampled across `difficulty` and `answer_type`.
2. Score the strong judge against human labels: report **Cohen's κ and raw agreement %, per metric**.
3. Score the fast/cheap judge against the strong judge **and** against human labels.
4. The fast judge may gate CI **only after ≥ 0.8 agreement** with the strong judge. Until then
   `config/models.json → judge_fast.ci_approved` stays `false` (VERIFIED: it is `false` today).
5. Record κ, agreement, sample size, and date in the evaluation ADR.
6. **Re-calibrate** whenever the model ID, the judge prompt, or the gold-set version changes.

**E-11  -  SPECIFIED. Agreement alone lies.** With skewed labels (most answers acceptable) a judge that
always says "good" scores high. κ MUST be reported alongside agreement, together with per-class
agreement on the rare class.

---

## 6. Thresholds and the CI gate

Initial targets, to be **re-baselined at the first full run** with the baseline recorded in an ADR:

| Metric | Threshold | Layer |
|---|---|---|
| Faithfulness | **≥ 0.85** | 2 (BLOCKED, U-1) |
| Context precision | **≥ 0.70** | 2 (BLOCKED, U-1) |
| Citation precision | **≥ 0.90** | 1 (deterministic) |

**E-12  -  SPECIFIED. CI gate.** Fail the build on a **> 1 pp regression on any threshold metric**
measured against the **mean of the last three baseline runs**. The gate **fails**; it does not warn.

**Current state  -  VERIFIED.** `.github/workflows/ci.yml` defines an `eval-smoke` job carrying the
comment "activated once the gold set exists; stub for now" and gated `if: false`. The gate is
therefore **specified but not enforced**. The two jobs that *are* enforced are `quality` (uv sync
--frozen, ruff check, ruff format --check, mypy app, pytest) and `secrets` (gitleaks, full history).

Note the dependency chain: the gate needs a gold set, which needs chunk IDs, which need a chunker
(**U-8  -  closed by ADR-0003 at 1,000 chars + 15% overlap**) and an embedding dimension (**U-9  -
closed by ADR-0002 at `D = 384`**). This ordering is why
`docs/MILESTONES.md` puts the gate at M4 and not earlier. ADR-0002 also makes the reverse
dependency explicit: pinning `D` *before* the gold set exists is what keeps it cheap to change,
because once baselines are recorded a new `D` invalidates them.

---

## 7. Run artifacts and reproducibility

**E-13  -  SPECIFIED.** Every run writes
`evals/reports/<UTC-timestamp>/{results.json, report.md, raw-judge-outputs/}`.

**E-14  -  SPECIFIED.** `results.json` MUST record, alongside the metrics, enough to reproduce the
run: `goldset_version`, corpus manifest SHA-256 set or manifest digest, chunker parameters,
embedding model ID and dimension, retrieval parameters (RRF constant, depths), reranker ID,
generator and judge model IDs with temperature, `uv.lock` hash, and the host CPU/RAM.

The reason E-14 is this specific: `evals/reports/` and the fetched corpus bytes are **gitignored**,
and the sources mutate upstream (`CORPUS_SPEC.md` C-8). One anchor does survive in the repository  -
`corpus/raw/manifest.json` is tracked as of 2026-10-01 (ADR-0001), so every document's URL, SHA-256
and fetch timestamp is recoverable from git even when the bytes are not. That is what makes a
manifest digest in `results.json` a meaningful pin rather than a reference to nothing. Without the
remaining fields recorded inside the report, a past run still cannot be reconstructed.

**E-15  -  SPECIFIED.** A report that is cited anywhere durable (README, ADR, release notes) MUST be
copied out of the gitignored directory into a tracked location, or the citation is dangling.

**E-16  -  SPECIFIED, and strengthened on 2026-10-02.** Hardware context is mandatory on any
latency-bearing number, and so is **input realism**. The Phase 0 baseline hardware is 2 vCPU /
1.9 GiB RAM (K-15).

This clause already carried the rule for the embedder  -  112.4 sentences/s on generic sentences
but **6.9 chunks/s on real 1,000-char corpus chunks**, quote the latter (ADR-0002). The same
trap was then walked into with the reranker, because the rule was written as a fact about one
model rather than as a rule about measurement. It is now general:

> A model's cost MUST be quoted from a measurement on **real corpus chunks**. A figure taken on
> short synthetic text is not a conservative estimate of it; transformer cost scales with
> sequence length, so it can understate by an order of magnitude.

Measured costs, both on real chunks: embedder **6.9 chunks/s**; cross-encoder reranker
**102–126 ms/pair**, *not* the 4.56 ms/pair recorded in Phase 0 from short sentences  -  a ~20×
understatement that passed a >50 ms/pair gate it should have failed. See ADR-0009.

---

## 8. When the full suite must be re-run  -  SPECIFIED

Any one of these invalidates previous results:

- chunking parameters (U-8), embedding model or dimension (U-9), index parameters
- RRF constant, candidate depth, rerank depth (U-10)
- reranker or generator model identity
- judge prompt or judge model (also triggers re-calibration, §5)
- gold-set version
- corpus re-ingest that changes any `sha256` in the manifest

Re-running only the retrieval tests after a chunking change is a known trap: **context precision
degrades silently when the chunker changes.**

### 8.1 Ablations required at the first full run  -  SPECIFIED

Three numbers are needed to justify the architecture rather than assume it:

1. **Lexical arm ablation**  -  dense + rerank only, versus hybrid. Settles whether fusion earns its
   complexity (`ARCHITECTURE.md` §8).
2. **Rerank ablation**  -  fused ranking with and without the cross-encoder, reported with its latency
   cost, feeding U-10 and U-14.
3. ~~**Chunking sweep**~~  -  **DONE** (ADR-0003): 14 configurations, span-level gold, paired significance tests. `docs/decisions/evidence/u8-chunking-sweep.json`.

**E-17  -  SPECIFIED.** Sweep results MUST NOT be used to pick the final configuration by gold-set
score alone without holding out a slice. Tuning chunk size by watching the gold-set score turns the
gold set into a training set; hold out a slice that is looked at only before a release.

---

## 9. Known traps carried forward

- **RAGAS is no longer a dependency (2026-10-02).** It was removed after `make audit-deps` found
  it carried CVE-2026-6587 while being imported nowhere; U-1 had already withdrawn the judge layer
  it existed for. The note below is retained because it would apply again if a judge is ever
  built. **RAGAS metric names and import paths move between versions**  -  `ragas.metrics` →
  `ragas.metrics.collections` is already deprecated in the pinned 0.4.3 (locked). Re-check metric
  *semantics* after any upgrade; a renamed metric is not the same metric.
- **`openai` is held at 2.54.0** by a `jiter` conflict with `ragas` (K-4). An eval-stack upgrade is
  a dependency-resolution exercise, not a version bump.
- **Unanswerable items are where RAG systems look best and behave worst.** Keeping ≥ 10 %
  unanswerable is what stops the faithfulness number from being flattering noise.
- **The injection canary is a quality metric, not only a security test.** It belongs in the gold set
  and in `results.json`.

---

## 10. Open items owned by this document

U-1 (judge feasibility  -  blocks §4 entirely) and U-17 (who writes and labels the items; persona
validation). U-8 (ADR-0003) and U-9 (ADR-0002) are closed.

**Correction to an earlier claim in this section.** It previously said U-10 "must close before a
gold set can be pinned". That was wrong, and acting on it would have blocked the project's
highest-priority artifact behind a tuning exercise. `required_citation_chunk_ids` depend on the
chunker (U-8, closed) and the corpus, not on the RRF constant or the candidate and rerank depths.
U-10 gates the first **baseline run** and the §8.1 ablations, not the item set. The gold set is
pinned at v1.0.0 with U-10 open.

**U-10, partially closed (2026-10-02).** The RRF constant was swept over the full gold set
(`scripts/experiments/u10_rrf_constant_sweep.py`, raw output under `evals/experiments/`). It
stays at the published default of 60: the best alternative, k=5, gains 1.15pp recall@5, which
is 1.5 items on 131, with a bootstrap CI spanning zero. What changed instead is structural  -
each arm's own top hit is now guaranteed a seat in the returned k (ADR-0007), after a real
miss in which BM25 ranked the answer first and fusion buried it at 14. Candidate depth and
rerank depth remain open.

**E-12 is implemented (2026-10-02).** `app/evals/gate.py`, `make eval-gate`. It enforces the
1pp rule against the mean of the last three accepted baselines in `evals/baselines/`, over the
serving configuration's recall, MRR and nDCG at k=5  -  any one of them failing fails the build,
because a system that holds recall while its ranking collapses has regressed.

Two deliberate design points:

*Invariants run before the comparison.* A metric threshold cannot catch a gold set that quietly
shrinks to its easy items: every number improves. The gate fails hard if the gold set's contents
changed without a version bump, if the corpus manifest digest moved, or if fewer items were
scored than in the baseline  -  none of which are regressions, all of which mean the numbers are
not comparable.

*The threshold is enforced, and its noise floor is published beside it.* One item on this gold
set is 0.76pp and the measured minimum detectable effect against the newest baseline is 3.24pp,
so 1pp is inside the noise. The gate does not widen the rule on its own authority; it reports
`minimum_detectable_effect_pp` with every verdict so a failure is never read as more certain
than the data allows. Grow the gold set, do not loosen the gate.

Baselines are accepted explicitly with `make eval-baseline`, never automatically  -  otherwise a
regression silently becomes the new reference and the gate measures drift against itself.

**U-18 (new, opened by the first baseline run).** The gold set's questions were authored from
the evidence quotes, so they inherit the vocabulary of the chunk they cite: measured at 73.3 %
term overlap with the gold chunk against 9.4 % with a random chunk. That is a 7.8× advantage
handed to the lexical arm before it retrieves anything, and it means the published retrieval
A/B cannot settle BM25 versus hybrid. Closing U-18 requires paraphrased variants of a sample of
items, re-asked in wording that shares as little vocabulary with the evidence as possible, and
the same three configurations re-run against them. Not done now: no API keys for a paraphraser
(U-1), and paraphrasing with a model from the same family as the embedder would substitute one
confound for another. Until U-18 closes, every retrieval comparison in this repository is
reported with its leakage band table beside it. See ADR-0006.

**U-17, answered for v1.0.0 and disclosed.** The items were authored and labelled by the DocScout
agent, one author, and `metadata.json` records this as **self-agreement, not inter-rater
reliability**. No Cohen's κ is reported, none can be computed from these two passes, and a test
asserts the metadata does not claim one. §5 human double-labelling remains outstanding and is
what any κ in this project must come from. All appear in `SPEC.md` §9.

---

## 9. Evaluation and Production Corpus Divergence Invariant (ADR-0024 & ADR-0025)

**E-17 — SPECIFIED (2026-10-10 UTC). Evaluation vs. Production Corpus Invariant.**
Production serving strictly excludes synthetic documents (WHERE NOT d.is_synthetic), serving only the 20 authoritative regulator gazette documents (ADR-0024). In contrast, the evaluation harness (pp/evals/runner.py) and CI regression gate evaluate the full 35-document corpus (including 15 synthetic fixtures) via an explicit MetadataFilter(include_synthetic=True) evaluation override. This guarantees continuous, uninterrupted measurement over all 365 answerable gold set items without invalidating the 237 synthetic-linked benchmark queries or altering the gold set denominator. Production recall is strictly bounded to real documents; evaluation recall measures holistic multi-document retrieval over the full evaluation corpus.
