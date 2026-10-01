# DocScout — Evaluation Protocol

**Status:** authoritative protocol for measuring DocScout's quality. Last updated **2026-10-01**.
**Implementation status:** no evaluation code, no gold set, and no evaluation run exists.
`app/evals/__init__.py` is 0 bytes; `evals/` and `tests/eval/` do not exist; the CI job
`eval-smoke` is gated `if: false` (all VERIFIED 2026-10-01). **DocScout has no quality numbers of
any kind, and none may be quoted.**

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9.

**Relationship to the `rag-eval-protocol` skill:** `.claude/skills/rag-eval-protocol/SKILL.md` is
the agent-facing trigger summary — short, loaded when an agent touches evaluation. This document is
the normative specification. The two state the same numbers; if they ever diverge, this document
governs and the skill is a defect. Every threshold here is quoted from the skill unchanged.

---

## 1. Why this document is strict

Metrics are the product in this project. A retrieval system can be made to look good by choosing the
questions, and an LLM judge can be made to agree with almost anything. The protocol therefore binds
the measurement *before* the system exists, so the thresholds cannot be reverse-engineered from the
first results.

**E-1 — SPECIFIED. No metric without an artifact.** A quality number may appear in a README, commit
message, ADR, report, UI, or conversation **only** if the raw output file that produced it exists
and is referenced. A number without a file is a fabrication. (= `SPEC.md` FR-25,
`docs/QUALITY_BAR.md` Q-7.)

**E-2 — SPECIFIED. Deterministic scorers first.** An LLM judge is reached for only when the quality
being measured is genuinely open-ended.

**E-3 — SPECIFIED. Judge calibration is mandatory** before any judge gates CI.

**E-4 — SPECIFIED. Never tune on the test set.** Re-baselining a threshold is an ADR-worthy
decision, never a quiet edit.

---

## 2. Gold set specification — SPECIFIED, does not exist yet

| Property | Requirement |
|---|---|
| Size | **≥ 120** QA pairs, hand-built. Grown over time, never auto-generated wholesale |
| Unanswerable share | **≥ 10 %** of items. Correct behaviour is refusal; refusal on an unanswerable item is a **PASS**, not a miss |
| Canary | **≥ 1** injection canary item, graded as a negative test (`CORPUS_SPEC.md` C-19) |
| Storage | Committed to the repository. It is the crown-jewel artifact |
| Versioning | Any change bumps `goldset_version` and is noted in `CHANGELOG.md` |

### 2.1 Item schema — SPECIFIED

| Field | Meaning |
|---|---|
| `question` | Natural phrasing, in the voice of a compliance analyst (`SPEC.md` §3.1 — persona is PROPOSED, U-17) |
| `required_citation_chunk_ids` | The chunk IDs a correct answer MUST cite |
| `expected_answer_key_points` | Atomic facts that must appear in the answer |
| `difficulty` | `easy` \| `medium` \| `hard` |
| `source_docs` | The document set the answer is derived from |
| `answer_type` | `extractive` \| `numeric` \| `multi-hop` \| `unanswerable` |
| `stable` | `true` once the item survives the review pass unchanged |

**E-5 — SPECIFIED. Scope rule.** No question may be answerable from more than its intended
`source_docs`. If it can be answered from general knowledge or from a document outside
`source_docs`, it is rewritten. *Test:* an item whose answer is reproduced by the generator with an
empty retrieval context fails the gold-set lint.

**E-6 — SPECIFIED. Labelling protocol.** Two-pass self-label, then a disagreement review pass.
The disagreement rate is recorded. Items surviving review unchanged are marked `stable: true`.

> **Disclosure required (U-17):** if one person performs both passes, the resulting agreement is
> self-agreement, not inter-rater reliability. Any κ computed that way MUST be labelled as such in
> the report. Overstating it would be exactly the kind of flattering number this protocol exists to
> prevent.

**E-7 — SPECIFIED. Chunk-ID stability.** Because `required_citation_chunk_ids` are foreign keys into
the corpus, gold items break when the chunker changes. On any chunking change the gold set MUST be
re-pinned and the full suite re-run (§8). This is a direct dependency on U-8.

---

## 3. Scoring layer 1 — deterministic — SPECIFIED

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

## 4. Scoring layer 2 — LLM judge — BLOCKED (U-1)

Reserved for genuinely open-ended quality: **faithfulness** (claims entailed by the retrieved
context), **answer relevance**, **completeness**.

**Current state — VERIFIED.** Every hosted model role in `config/models.json` carries `id: null`,
`verified_at: null`, `status: BLOCKED_NO_CREDENTIAL`; Phase 0 API spend was **$0.00**; V11 of the
verification matrix is BLOCKED. The judge layer **cannot run at all today**.

**E-8 — SPECIFIED.** Judge prompts are versioned files. Editing a prompt creates a new judge version
and **invalidates prior calibration**.

**E-9 — SPECIFIED.** Cross-provider judging: generator and judge come from different vendors. A
model MUST NOT judge its own output in a headline number.

**E-10 — SPECIFIED.** Judges run at temperature 0, with the model version and seed recorded. Residual
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

---

## 5. Judge calibration — mandatory and blocking — SPECIFIED

1. A human double-labels **60–100 items**, sampled across `difficulty` and `answer_type`.
2. Score the strong judge against human labels: report **Cohen's κ and raw agreement %, per metric**.
3. Score the fast/cheap judge against the strong judge **and** against human labels.
4. The fast judge may gate CI **only after ≥ 0.8 agreement** with the strong judge. Until then
   `config/models.json → judge_fast.ci_approved` stays `false` (VERIFIED: it is `false` today).
5. Record κ, agreement, sample size, and date in the evaluation ADR.
6. **Re-calibrate** whenever the model ID, the judge prompt, or the gold-set version changes.

**E-11 — SPECIFIED. Agreement alone lies.** With skewed labels (most answers acceptable) a judge that
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

**E-12 — SPECIFIED. CI gate.** Fail the build on a **> 1 pp regression on any threshold metric**
measured against the **mean of the last three baseline runs**. The gate **fails**; it does not warn.

**Current state — VERIFIED.** `.github/workflows/ci.yml` defines an `eval-smoke` job carrying the
comment "activated once the gold set exists; stub for now" and gated `if: false`. The gate is
therefore **specified but not enforced**. The two jobs that *are* enforced are `quality` (uv sync
--frozen, ruff check, ruff format --check, mypy app, pytest) and `secrets` (gitleaks, full history).

Note the dependency chain: the gate needs a gold set, which needs chunk IDs, which need a chunker
(U-8) and an embedding dimension (**U-9 — closed by ADR-0002 at `D = 384`**). This ordering is why
`docs/MILESTONES.md` puts the gate at M4 and not earlier. ADR-0002 also makes the reverse
dependency explicit: pinning `D` *before* the gold set exists is what keeps it cheap to change,
because once baselines are recorded a new `D` invalidates them.

---

## 7. Run artifacts and reproducibility

**E-13 — SPECIFIED.** Every run writes
`evals/reports/<UTC-timestamp>/{results.json, report.md, raw-judge-outputs/}`.

**E-14 — SPECIFIED.** `results.json` MUST record, alongside the metrics, enough to reproduce the
run: `goldset_version`, corpus manifest SHA-256 set or manifest digest, chunker parameters,
embedding model ID and dimension, retrieval parameters (RRF constant, depths), reranker ID,
generator and judge model IDs with temperature, `uv.lock` hash, and the host CPU/RAM.

The reason E-14 is this specific: `evals/reports/` and the fetched corpus bytes are **gitignored**,
and the sources mutate upstream (`CORPUS_SPEC.md` C-8). One anchor does survive in the repository —
`corpus/raw/manifest.json` is tracked as of 2026-10-01 (ADR-0001), so every document's URL, SHA-256
and fetch timestamp is recoverable from git even when the bytes are not. That is what makes a
manifest digest in `results.json` a meaningful pin rather than a reference to nothing. Without the
remaining fields recorded inside the report, a past run still cannot be reconstructed.

**E-15 — SPECIFIED.** A report that is cited anywhere durable (README, ADR, release notes) MUST be
copied out of the gitignored directory into a tracked location, or the citation is dangling.

**E-16 — SPECIFIED.** Hardware context is mandatory on any latency-bearing number. The Phase 0
baseline hardware is 2 vCPU / 1.9 GiB RAM (K-15); measured reranker cost is 4.56 ms/pair, and
embedding throughput is 112.4 sentences/s on generic sentences but **6.9 chunks/s on real
1,000-char corpus chunks** — quote the latter for any corpus-scale estimate (ADR-0002).

---

## 8. When the full suite must be re-run — SPECIFIED

Any one of these invalidates previous results:

- chunking parameters (U-8), embedding model or dimension (U-9), index parameters
- RRF constant, candidate depth, rerank depth (U-10)
- reranker or generator model identity
- judge prompt or judge model (also triggers re-calibration, §5)
- gold-set version
- corpus re-ingest that changes any `sha256` in the manifest

Re-running only the retrieval tests after a chunking change is a known trap: **context precision
degrades silently when the chunker changes.**

### 8.1 Ablations required at the first full run — SPECIFIED

Three numbers are needed to justify the architecture rather than assume it:

1. **Lexical arm ablation** — dense + rerank only, versus hybrid. Settles whether fusion earns its
   complexity (`ARCHITECTURE.md` §8).
2. **Rerank ablation** — fused ranking with and without the cross-encoder, reported with its latency
   cost, feeding U-10 and U-14.
3. **Chunking sweep** — at least two strategies, to produce the U-8 ADR.

**E-17 — SPECIFIED.** Sweep results MUST NOT be used to pick the final configuration by gold-set
score alone without holding out a slice. Tuning chunk size by watching the gold-set score turns the
gold set into a training set; hold out a slice that is looked at only before a release.

---

## 9. Known traps carried forward

- **RAGAS metric names and import paths move between versions** — `ragas.metrics` →
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

U-1 (judge feasibility — blocks §4 entirely), U-17 (who writes and labels ≥ 120 items; persona
validation), and the downstream dependencies U-8 and U-10 that must close before a gold set can be
pinned. U-9 is closed (ADR-0002). All appear in `SPEC.md` §9.
