---
name: rag-eval-protocol
description: Use this skill when touching the DocScout evaluation harness in any way - building or editing the gold set, writing scorers, configuring LLM judges, calibrating a judge against human labels, setting or changing metric thresholds, wiring the CI eval gate, or stating ANY retrieval/answer-quality number in a commit message, README, ADR, report, or conversation. Use it before claiming faithfulness, context precision/recall, citation precision/recall, answer relevancy, MRR, nDCG, recall@k, or win-rate figures. Use it when asked "how good is the RAG system", "did quality regress", "can we ship this retrieval change", or "update the eval".
---

# RAG evaluation protocol

Metrics are the product in this project. A number without a raw output file is a fabrication.

## Non-negotiable rules

1. **No metric without an artifact.** Every run writes
   `evals/reports/<UTC-timestamp>/{results.json,report.md,raw-judge-outputs/}`.
   A metric may appear in README/commits/ADRs **only** if its raw output file exists and is referenced.
2. **Deterministic scorers first.** Reach for an LLM judge only for genuinely open-ended quality.
3. **Judge calibration is mandatory** before any judge gates CI.
4. **Never tune on the test set.** Threshold re-baselining is an ADR-worthy decision, not a quiet edit.

## Gold set spec

- **Size:** ≥120 QA pairs, hand-built. Grown, never auto-generated wholesale.
- **Each item carries:**
  - `question` — natural, in the voice of a real user (compliance analyst).
  - `required_citation_chunk_ids` — the chunk IDs a correct answer MUST cite.
  - `expected_answer_key_points` — list of atomic facts that must appear.
  - `difficulty` — `easy` | `medium` | `hard`.
  - `source_docs` — the document set the answer is derived from.
  - `answer_type` — `extractive` | `numeric` | `multi-hop` | `unanswerable`.
- **Scope rule:** no question may be answerable from more than the intended document set. If a
  question can be answered from general knowledge or from a doc outside `source_docs`, rewrite it.
- **Include negatives:** unanswerable questions (correct behavior = refusal) and ≥1 injection canary
  (see skill `corpus-injection-defense`). Refusal on unanswerable is a PASS, not a miss.
- **Labeling protocol:** two-pass self-label, then a disagreement review pass. Record disagreement
  rate. Items that survive review unchanged are marked `stable: true`.
- **Versioning:** the gold set is committed (it is the crown-jewel artifact). Any change bumps
  `goldset_version` and is noted in CHANGELOG.

## Scoring layers

**Layer 1 — deterministic (always run, free, fast):**
- citation precision = correct cited IDs / all cited IDs
- citation recall = required IDs cited / required IDs
- key-point coverage via exact / contains / numeric-with-tolerance match
- refusal correctness on unanswerable items
- retrieval: recall@k, MRR, nDCG against `required_citation_chunk_ids`

**Layer 2 — LLM judge (open-ended only):** faithfulness (claims entailed by retrieved context),
answer relevance, completeness. Judge prompts are versioned files; a prompt edit is a new judge
version and invalidates prior calibration.

## Judge calibration (mandatory, blocking)

1. Human double-labels **60-100 items** sampled across difficulty and answer_type.
2. Score strong judge vs human: report **Cohen's κ and raw agreement %, per metric**.
3. Score fast/cheap judge vs strong judge AND vs human.
4. The fast judge may be used in CI **only after ≥0.8 agreement** with the strong judge; until then
   `config/models.json → judge_fast.ci_approved` stays `false`.
5. Record κ, agreement, sample size, and date in the eval ADR. Re-calibrate when either model ID,
   the judge prompt, or the gold set version changes.
6. Use **cross-provider** judging (generator and judge from different vendors) to reduce self-
   preference bias. Never let a model judge its own output in the headline number.

## Thresholds and the CI gate

Initial targets (re-baseline at the first full run, record the baseline in an ADR):
- faithfulness ≥ 0.85
- context precision ≥ 0.70
- citation precision ≥ 0.90

CI gate: **fail on regression >1pp on any threshold metric** measured against the mean of the last
3 baseline runs. The gate fails the build; it does not warn.

## Gotchas

- **Agreement % alone lies.** With skewed labels (most answers fine) a judge that always says "good"
  scores high. Always report κ alongside, and report per-class agreement on the rare class.
- **A rewritten judge prompt silently invalidates calibration.** Treat prompts as versioned code.
- **Non-determinism:** judges at temperature > 0 drift between runs. Pin temperature 0 and record
  the seed/model version; expect residual variance and do not chase sub-1pp noise.
- **Context precision degrades silently when the chunker changes.** Re-run the full suite on any
  chunking, embedding, or index parameter change — not just the retrieval tests.
- **RAGAS metric names and import paths move between versions** (`ragas.metrics` →
  `ragas.metrics.collections` is already deprecated in the pinned 0.4.3). Pin the version, and
  re-check metric semantics after any upgrade — a renamed metric is not the same metric.
- **Gold-set leakage:** if you tune chunk size by watching the gold-set score, the gold set is now a
  training set. Hold out a slice you only look at before a release.
- **Unanswerable items are where RAG systems look best and behave worst.** Keep ≥10% of the set
  unanswerable or the faithfulness number is flattering noise.
