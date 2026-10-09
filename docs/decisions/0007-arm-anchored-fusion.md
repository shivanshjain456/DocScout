# ADR-0007: Reserve a seat for each arm's top hit, instead of tuning the RRF constant

- **Status:** accepted
- **Date:** 2026-10-02
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Amends:** ADR-0006, which chose unweighted RRF at `k=60`. That constant is unchanged. This adds a bounded guarantee on top of it.
- **Related:** `EVAL_PROTOCOL.md` §8.1 (ablations), E-12 (the regression gate) · U-10 (RRF constant and candidate depth) · ADR-0002 (dense arm) · ADR-0003 (chunk geometry)
- **Evidence:** `docs/verification/0001-g038-fusion-miss.md` (the full story) · `scripts/experiments/u10_rrf_constant_sweep.py` and its `evals/experiments/u10-rrf-*/results.json` · `tests/test_retrieval.py::test_g038_confident_lexical_hit_survives_fusion` · baseline `evals/reports/20261001T204628Z/`

## Context

Gold item g-038 asks which withdrawn circular covered CCTV coverage of cash handling
operations in currency chests. The evidence is one row in a long table of withdrawn
circulars inside an RBI notification.

Measured on the serving configuration before this change:

| arm | rank of the correct chunk |
|---|---|
| BM25 | **1** (score 18.09, the top hit by a decisive margin) |
| dense | 41 (cosine 0.613 against a top hit of 0.715) |
| hybrid RRF, k=60 | **14**  -  outside the served depth of 10 |

The item scored zero recall at every cutoff while one arm had the answer in first place.

This is not a tuning accident, it is the documented cost of rank-only fusion arriving. RRF
scores a document `1/(k + rank)` per arm, so at `k=60` rank 1 is worth `1/61` and rank 41 is
worth `1/101`  -  a ratio of only **1.66×**. A chunk that both arms place near the top
(`1/61 + 1/62 = 0.0325`) therefore outranks a chunk one arm is certain about
(`1/61 + 1/101 = 0.0263`). `app/retrieval/fusion.py` already said RRF "throws away margin …
an arm that is certain of its top hit contributes exactly as much as one that barely
preferred it". Here that cost is the whole answer.

Regulatory retrieval makes this failure mode routine rather than exotic. Questions turn on
exact tokens  -  a circular number, a date, "CCTV"  -  which is precisely where the lexical arm
is confident and the dense arm, facing a chunk that is a table of fifty unrelated circulars,
has nothing coherent to embed.

## What was measured

`scripts/experiments/u10_rrf_constant_sweep.py`, all 131 answerable gold items, two candidate
fixes on identical data.

| variant | R@1 | R@5 | R@10 | MRR | nDCG@5 | Δ recall@5 vs k=60 | CI excludes 0 | g-038 R@10 |
|---|---|---|---|---|---|---|---|---|
| k=1 | 0.695 | 0.977 | 0.992 | 0.830 | 0.853 | +0.0115 | no | 1.00 |
| k=5 | 0.695 | 0.977 | 0.992 | 0.826 | 0.851 | +0.0115 | no | 1.00 |
| k=10 | 0.695 | 0.966 | 0.992 | 0.825 | 0.845 | +0.0000 | no | 1.00 |
| k=20 / 30 / 60 / 100 | 0.695 | 0.966 | 0.992 | 0.824 | 0.844 | +0.0000 | no | 0.00 |
| k=5 + anchor | 0.695 | 0.977 | 0.992 | 0.826 | 0.851 | +0.0115 | no | 1.00 |
| **k=60 + anchor** | 0.695 | 0.966 | **1.000** | 0.825 | 0.844 | +0.0000 |  -  | **1.00** |

Per-item comparison of `k=60 + anchor` against plain `k=60`, at both cutoffs, over all 131
items: **0 items worse, 1 item better.** A strict Pareto improvement on this gold set.

## Decision

**Keep `rrf_k = 60`. Guarantee each arm's own rank-1 chunk a seat in the returned `k_final`.**

Implemented as `RetrievalConfig.anchor_arm_top1`, enabled on `app.retrieval.SERVING_CONFIG`  -
the single definition of what ships, so the eval runner, the regression gate and any future
API cannot drift apart. At most one chunk per arm is inserted, it keeps its real fused score,
and nothing else is reordered or rescored.

The reasoning for preferring the guarantee over the obvious knob:

1. **Lowering the constant is tuning; ADR-0006 rejected that, and the reason still holds.**
   `k=5` gains 1.15pp recall@5, which is 1.5 items out of 131, and its bootstrap CI includes
   zero. Adopting it would be fitting noise, and the sweep shows the gain is a cliff between
   k=5 and k=10 rather than a smooth optimum  -  the signature of a value that happens to flip
   a couple of items on this gold set.
2. **The guarantee is structural and addresses the diagnosed cause.** The defect is that
   rank-only fusion cannot express certainty. Reserving a seat restores exactly the missing
   property, and does so identically on every corpus, rather than approximating it with a
   constant chosen against 131 questions.
3. **It is the only variant that makes recall@10 complete.** 1.000 means every answerable
   gold question's evidence reaches the generator. That is the property that matters at a
   serving depth of 10, and no constant achieves it.
4. **It is bounded and auditable.** Two arms, at most two inserted chunks, each carrying its
   real score and its arm ranks, so a report can always show why a result is present.

Recorded honestly: the aggregate movement from this change is one item. It is adopted because
it removes a diagnosed structural failure at zero measured cost, not because the gold set can
prove it is better. The gate agrees  -  recall unchanged, MRR +0.07pp, no regression.

## Consequences

- `recall@10` is now 1.000 on the gold set. That is a ceiling effect of a 170-chunk corpus,
  not evidence of a solved problem, and it will fall when the corpus grows. It also means
  recall@10 has lost its power to discriminate and the gate's useful signal now sits at
  recall@5 and MRR.
- The dense arm's top hit is also anchored. On this gold set that never displaced anything
  useful (0 items worse), but it is a real cost on a corpus where the dense arm is noisy, and
  it should be re-measured as the corpus grows.
- U-10 is partially closed: the constant stays at the published default with a measured sweep
  behind it. Candidate depth and rerank depth remain open.
- Two tests pin the behaviour, including one that asserts the defect still exists without the
  anchor, so the guarantee cannot quietly become cargo cult.

## Rejected alternatives

### A. Lower `rrf_k` to 5 (or 1)

The obvious knob, and it does fix g-038 while adding 1.15pp recall@5. Rejected because the
gain is 1.5 items with a CI spanning zero, because ADR-0006 declined exactly this tuning for
exactly this reason, and because the effect is a step between k=5 and k=10 rather than an
optimum  -  a shape that rarely transfers to a different corpus. Revisit when the gold set is
large enough for 1pp to be resolvable.

### B. Weighted RRF favouring the lexical arm

Would also have surfaced g-038, and the leakage analysis in ADR-0006 says the gold set already
flatters BM25 by 7.8×. Up-weighting the lexical arm on evidence drawn from a lexically-biased
benchmark would be measuring the benchmark's bias and calling it a tuning result. Rejected.

### C. Score-level fusion with normalised scores

This would genuinely fix the class of problem, since BM25's margin is exactly the information
RRF discards. Rejected for the reasons in ADR-0006 §C: BM25 is unbounded and corpus-dependent,
cosine is bounded, and any normalisation is itself a tuned, corpus-specific choice that one
arm's score distribution can destabilise. The anchor captures the specific case that matters  -
an arm's single most confident result  -  without importing that whole problem.

### D. Raise `k_final` from 10 to 15

g-038 sat at fused rank 14, so a deeper cut would have included it. Rejected: it treats the
symptom, inflates every downstream prompt by 50%, and raises generation cost and latency for
every query to rescue one. It also fails the next case where a confident hit lands at 16.

### E. Add a cross-encoder reranker

A reranker reorders what retrieval already returned, so it cannot recover a chunk that never
entered the top 10  -  it would not have fixed this at all. Still worth doing for ordering, as
ADR-0006 notes, but it is not a fix for this defect and adopting it here would have been
mistaking activity for diagnosis.

### F. Treat g-038 as a bad gold item and delete it

The quickest green build. Rejected, and worth stating plainly: the item is well-formed, its
quote is verbatim in the corpus, its citation resolves, and a compliance analyst asking which
circular was withdrawn is the product's core use case. Deleting the question that exposes a
defect is how a gold set becomes decoration, and the gate's own invariants exist to make that
visible  -  a shrinking item count fails the build.
