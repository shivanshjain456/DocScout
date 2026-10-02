# ADR-0009: Build the reranker, measure it, and leave it switched off

- **Status:** accepted
- **Date:** 2026-10-02
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Closes:** the rerank half of **U-10** (candidate depth and rerank depth) and the rerank ablation that `EVAL_PROTOCOL.md` §8.1 requires
- **Amends:** `ARCHITECTURE.md` §3, which specified an always-on cross-encoder stage and quoted a per-pair cost that this ADR corrects by a factor of ~20
- **Related:** ADR-0006 (deferred the reranker with a prediction) · ADR-0007 (made recall@10 = 1.000, which bounds what a reranker can achieve) · ADR-0008 (serving configuration and its latency budget)
- **Also answers:** "why not HyDE?" — rejected alternative D, on three independent grounds
- **Evidence:** `scripts/experiments/u10_rerank_ablation.py` and `evals/experiments/u10-rerank-20261002T062322Z/results.json` · `app/retrieval/rerank.py` · `tests/test_rerank.py` (12 cases)

## Context

`ARCHITECTURE.md` §3 has specified a cross-encoder rerank stage since M1, and
`MILESTONES.md` lists it as M4 work. It was never built. ADR-0006 deferred it with an
explicit prediction — that a reranker "cannot fix a recall ceiling, and at recall@10 near
0.98 there is almost nothing left for it to recover" — and ADR-0007 then raised recall@10
to **1.000**, which makes the prediction sharper rather than obsolete: on this corpus a
reranker provably **cannot** improve recall at the serving depth, because retrieval already
returns every piece of required evidence.

That leaves exactly one open question, and it is a fair one. recall@1 is **0.695**. All the
remaining headroom is at the top of the list, which is precisely where a cross-encoder is
supposed to be strongest. The brief also requires the *measured effect of reranking* as a
first-class artifact. So the stage was built, measured, and judged on its numbers.

## What was measured

Full gold set, 131 answerable items, serving configuration as the baseline, paired
bootstrap on recall@1 (`scripts/experiments/u10_rerank_ablation.py`):

| variant | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@5 | p95 | Δ R@1 | CI excludes 0 |
|---|---|---|---|---|---|---|---|---|---|
| **no rerank (serving)** | 0.695 | **0.927** | 0.966 | **1.000** | 0.825 | 0.844 | **39 ms** | — | — |
| rerank top 10 | **0.718** | 0.924 | **0.977** | **1.000** | **0.850** | **0.867** | 1,185 ms | +0.023 | **no** |
| rerank top 20 | 0.718 | 0.924 | 0.977 | 0.992 | 0.848 | 0.867 | 2,455 ms | +0.023 | no |
| rerank top 50 | 0.718 | 0.924 | 0.977 | 0.992 | 0.848 | 0.867 | 6,276 ms | +0.023 | no |

Four things in that table decide this ADR.

**1. The quality gain is three items and does not survive resampling.** +2.3pp recall@1 is
3 items out of 131, and the bootstrap CI includes zero. MRR and nDCG move about 2.3pp in
the same direction. This is the same magnitude of evidence that ADR-0006 and ADR-0007 both
declined to act on, and consistency is not optional.

**2. It costs 30× to 160× the p95.** 39 ms becomes 1,185 ms at top-10 and 6.3 s at top-50.
The NFR budget is p95 < 3 s end to end, so top-20 and top-50 breach it outright, and top-10
spends 40% of the entire budget on a stage whose benefit cannot be distinguished from noise.

**3. Reranking deeper than the serving depth *breaks* recall@10.** At top-20 and top-50 it
falls from 1.000 to 0.992. This is not a measurement artifact — it is structural. Once the
pool is larger than `k_final`, the cross-encoder can promote a chunk from rank 11–50 over a
chunk fusion had correctly placed in the top 10, and the displaced chunk was the evidence.
ADR-0007's guarantee was bought with a careful, bounded change; this would spend it.

**4. A documented performance number was wrong by ~20×, and using it exposed that.**
`ARCHITECTURE.md` §3 recorded "VERIFIED cost: `ms-marco-MiniLM-L-6-v2` at **4.56 ms/pair**".
Re-measured on this machine:

| input | ms per pair |
|---|---|
| short synthetic sentences (what the original figure used) | **5.54** |
| real corpus chunks (946 chars / 267 tokens mean) | **102–126** |

The original measurement was arithmetically fine and substantively misleading: transformer
cost scales with sequence length, and the project's real chunks are roughly 18× longer than
the strings it was measured on. A cost model built on 4.56 ms/pair would have predicted
~46 ms for a top-10 rerank; the truth is ~1.1 s. The figure is corrected in
`ARCHITECTURE.md` with a pointer here.

## Decision

**Implement the reranker properly, test it, expose it as a configuration flag, and leave
`SERVING_CONFIG.rerank = False`.**

`app/retrieval/rerank.py` is a real implementation, not a stub: lazy single load, explicit
`max_length=512` so a future checkpoint default cannot silently change every score,
deterministic ordering with ties broken toward the incoming fusion order, and a length
check that refuses a score/candidate mismatch rather than misaligning scores with passages.
`RetrievalConfig.rerank_top_n` is validated to be at least `k_final`, because reranking
fewer candidates than are returned pays for the model and reorders nothing.

It is off because the measurement says it should be off **on this corpus, today**: an
unresolvable gain is not worth 30× the latency and 30× the compute cost, and the one
configuration that preserves recall@10 is also the one with the least room to help.

This is not a permanent verdict and the ADR says so. The honest reading is that the
benchmark is saturated — recall@10 is already 1.000 on 170 chunks — so it has very little
power to detect what a reranker would do on a corpus where retrieval actually struggles.
**Re-run `u10_rerank_ablation.py` when the corpus grows.** That is one command, and the
stage is already built and tested, which is the reason to keep it rather than delete it.

## Consequences

- Serving latency and cost are unchanged: p95 48 ms end to end, ~$0.08 per million queries
  (ADR-0008). Enabling top-10 reranking would make those roughly 1.2 s and ~$2.40 per
  million — a useful number to have measured rather than guessed.
- `ARCHITECTURE.md`'s pipeline description changes from "then cross-encoder rerank" to an
  available, measured, disabled stage. The document no longer describes code that does not
  run.
- The reranker is covered by 12 tests, 4 of which exercise the real model and are marked
  `slow`. A flag that is plumbed but never applied is a classic silent no-op, so one test
  asserts the order actually changes when it is enabled.
- U-10's rerank-depth question is closed with measurements. Candidate depth (`k_dense`,
  `k_lexical` = 50) remains unswept.

## Rejected alternatives

### A. Enable reranking at top-10 anyway

The strongest case against this ADR: it is the only variant that improves R@1, R@5, MRR and
nDCG while holding recall@10 at 1.000, and 1.2 s is inside the 3 s budget. Rejected because
the gain is three items with a CI spanning zero, and buying a 30× latency increase with
noise is exactly the trade ADR-0006 and ADR-0007 both refused. Revisit the moment the gold
set is large enough for 2.3pp to be resolvable.

### B. Enable at top-20 or top-50

Rejected on its own numbers: identical quality to top-10, 2.5–6.3 s p95 which breaches the
NFR, and it drops recall@10 from 1.000 to 0.992 by promoting deep candidates over evidence
fusion had already placed correctly. Strictly worse than top-10 in every column.

### C. A smaller or quantised cross-encoder

`ms-marco-MiniLM-L-2-v2` or an ONNX/int8 export would cut per-pair cost materially. Rejected
as premature rather than wrong: the problem is not that the gain costs too much, it is that
the gain is not yet measurable. Making an unresolvable improvement cheaper does not make it
real. This is the first thing to try if the corpus grows and reranking starts to matter.

### D. HyDE (Hypothetical Document Embeddings) instead

Generate a hypothetical answer with an LLM, embed that, and retrieve with it. Rejected on
three independent grounds, any one of which is sufficient:

1. **It requires a generator, which does not exist** (U-1, no API keys) — and ADR-0008
   declined to put an unmeasured model in the request path.
2. **It targets a problem this system does not have.** HyDE exists to close the vocabulary
   gap between a short question and a long document, which is precisely what the BM25 arm
   already handles on this corpus — and the arm that measurably carries retrieval here
   (ADR-0006).
3. **It could not be evaluated honestly today.** The gold set's questions were authored from
   their evidence quotes and share 73.3% of their terms with the target chunk (U-18). A
   technique whose whole purpose is bridging vocabulary mismatch cannot be fairly assessed
   on a benchmark with almost no vocabulary mismatch; the measurement would be of the
   benchmark, not the technique.

It also adds a generation call to every query's latency and cost — the one expense a
retrieval tier deliberately avoids.

### E. Delete the reranker code since it is disabled

Tempting, and the usual right answer for unused code. Rejected here because it is not
unused: it is reachable through a documented configuration flag, exercised by 12 tests
including 4 against the real model, and executed by a committed experiment whose raw output
this ADR cites. Deleting it would also delete the ability to re-run the ablation in one
command when the corpus grows, which is the explicit condition for revisiting this decision.
What would be dead code is a reranker with no tests, no experiment and no ADR — which is
what the project had this morning, in the form of an architecture document describing a
stage that did not exist.

### F. Run the cross-encoder on a GPU

No GPU is available and none will be provisioned — this project creates no cloud resources.
Worth recording only to note that it would change the arithmetic completely, not the
conclusion: the gain would still be three items with a CI spanning zero.
