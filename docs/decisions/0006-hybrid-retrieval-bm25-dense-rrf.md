# ADR-0006: Keep hybrid BM25 + dense + RRF, on evidence that does not yet prove it

- **Status:** accepted, with a named experiment that could overturn it
- **Date:** 2026-10-01
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Related:** ADR-0002 (embedding arm, `bge-small-en-v1.5` at 384-d) · ADR-0003 (chunk geometry; 150-char overlap is why citations are scored in groups) · ADR-0004 (`vector_cosine_ops` HNSW, GIN on `tsv`) · ADR-0005 (content-derived `chunk_id`, which is what makes these numbers comparable across rebuilds) · `EVAL_PROTOCOL.md` §8.1 (ablations), E-12 (1pp CI gate), E-13/E-14 (run artifacts and provenance)
- **Evidence:** `evals/reports/<timestamp>/results.json` and `report.md` from `make eval` · `app/retrieval/` · `app/evals/scorers.py` · `app/evals/stats.py` · `tests/test_retrieval.py` · `tests/test_scorers.py`

## Context

The brief requires an A/B of at least two retrieval configurations, reporting the loser's
numbers and why it lost. Three were run over the full 131 answerable gold items: dense-only,
bm25-only, and hybrid fused with Reciprocal Rank Fusion at `k=60`, all at equal arm depth
(50 candidates) and `k_final=10`.

The expected result was the conventional one: hybrid wins, dense-only is the loser, ADR
closed. That is not what the numbers said, and the gap between what they said and what
they support is the substance of this ADR.

## What was measured

Macro-averaged over 131 answerable items (22 unanswerable items excluded — they measure
abstention, a generation property). Recall is the fraction of *quote groups* covered, where
a group is the set of chunks containing one evidence quote; ADR-0003's overlap means a
boundary-adjacent quote legitimately lives in two chunks and citing either is correct.

| config | recall@5 | hit@5 | MRR | nDCG@5 | p95 latency |
|---|---|---|---|---|---|
| `bm25-only` | 0.970 | 0.977 | 0.838 | 0.855 | 1 ms |
| `hybrid-rrf` | 0.966 | 0.977 | 0.824 | 0.844 | 34 ms |
| `dense-only` | 0.947 | 0.962 | 0.762 | 0.793 | 43 ms |

Read naively: BM25 wins, is 34× faster, and the dense arm is dead weight. That reading is
wrong twice over.

### 1. None of the differences survive resampling

Paired bootstrap, 10,000 resamples, fixed seed, on recall@5:

| comparison | difference | 95% CI | in items | discordant hits | CI excludes zero |
|---|---|---|---|---|---|
| `dense-only` vs `bm25-only` | −0.0191 | [−0.0420, +0.0000] | −2.5 | 0 / 2 | no |
| `dense-only` vs `hybrid-rrf` | −0.0115 | [−0.0305, +0.0000] | −1.5 | 0 / 1 | no |
| `bm25-only` vs `hybrid-rrf` | +0.0076 | [+0.0000, +0.0229] | +1.0 | 1 / 0 | no |

Every interval touches zero. The entire BM25-over-hybrid "win" is **one item out of 131**.
On this gold set, at this corpus size, the three configurations are indistinguishable, and
any sentence of the form "X beats Y" would be an overstatement of the evidence.

This also calibrates the CI gate: E-12 fails a run that drops more than 1pp against the mean
of the last three baselines, and 1pp here is 1.3 items. The gate currently operates at
roughly single-item resolution. That is a property of a 131-item gold set, not of the metric,
and it is a reason to grow the gold set rather than to loosen the gate.

### 2. The gold set is biased toward the lexical arm, by construction

The gold set's questions were authored *from* the evidence quotes (EVAL_PROTOCOL §2.2, which
is also what makes citations re-pinnable rather than hand-maintained). The side effect is that
questions inherit the vocabulary of the chunk they point at. Measured on this run: a question's
analyzed terms appear in its own gold chunk **73.3%** of the time versus **9.4%** for a random
chunk — a **7.8× lexical advantage handed to BM25 before it retrieves anything**.

Stratifying recall@5 by that overlap separates the confound from the signal:

| question/evidence term overlap | `dense-only` | `bm25-only` | `hybrid-rrf` | n |
|---|---|---|---|---|
| low (<0.5) | 0.875 | **0.750** | 0.875 | 8 |
| mid (0.5–0.8) | 0.931 | 0.986 | 0.972 | 72 |
| high (≥0.8) | 0.980 | 0.980 | 0.971 | 51 |

BM25's advantage is concentrated exactly where the leakage is, and in the band that most
resembles a question a human would actually type — low overlap — it is the **worst** of the
three, while hybrid matches the best. With n=8 that band proves nothing on its own. It is
consistent with the mechanism, it is the opposite of the headline, and it is the reason the
dense arm stays.

## Decision

**Keep hybrid BM25 + dense + RRF as the serving configuration**, at `k=60`, equal arm depth,
unweighted.

The justification is explicitly *not* "hybrid measured best" — it did not. It is:

1. **No configuration is measurably better**, so the choice falls to which failure modes each
   covers. Hybrid is never worst in any leakage band; each single-arm configuration is worst
   in at least one.
2. **The benchmark's bias runs against hybrid**, so hybrid's parity here is achieved while
   handicapped. Removing the dense arm would be optimising for a measurement artifact.
3. **The cost is affordable and measured**: 34 ms p95 versus 1 ms, on 2 vCPU, against a 3 s
   budget (NFR). Latency is not the binding constraint at this corpus size.
4. **Regulatory text needs both**: exact tokens (circular numbers, "T+1", percentages) are
   lexical; paraphrased intent is semantic. The corpus is 170 chunks, far too small for the
   dense arm's weakness at scale — or its strength — to appear.

## Consequences

- `app/retrieval/` ships three configurations, not one. The ablation is a supported mode, so
  re-running the A/B costs one command, and single-arm numbers come from the same code path
  as hybrid minus a step.
- Every eval report carries the leakage statistic and the banded table. A future reader cannot
  see the headline without seeing what undermines it.
- The 1pp CI gate is near single-item resolution until the gold set grows. Recorded as a known
  limitation rather than silently tolerated.
- The lexical arm builds its term table in memory at startup (one query, ~30k rows at 170
  chunks). Correct now, wrong at a million chunks; the interface does not change when it moves
  to a real BM25 index.

## The experiment that could overturn this

**Paraphrased query variants.** Re-ask a sample of gold questions in wording that shares as
little vocabulary with the evidence as possible, and re-run the same three configurations. If
BM25 still matches hybrid on low-overlap questions, the dense arm is genuinely dead weight on
this corpus and ADR-0006 should be reversed in favour of bm25-only — simpler, 34× faster, one
fewer model to serve.

This is deliberately *not* done with an LLM paraphraser right now: no API keys are available
(U-1), and a paraphrase generated by the same family of model that produces the embeddings
would be a confound of its own. Tracked as **U-18**.

## Rejected alternatives

### A. Dense-only

The configuration the measurement most clearly disfavours: worst recall (0.947), worst MRR
(0.762), worst nDCG, and no latency advantage over hybrid (43 ms vs 34 ms p95 — the dense arm
*is* the slow part, and hybrid's extra BM25 pass costs about a millisecond). It also fails
exactly the queries regulatory users care about, where a circular number must match exactly.
Rejected on its own numbers.

### B. BM25-only

Superficially the strongest case: nominally top of every table and 34× faster. Rejected
because its lead is one item and its measured advantage is concentrated in the leakage the
gold set introduced; in the least-contaminated band it is the worst of the three (0.750). It
is also the configuration with no path to handling a paraphrased question at all. Revisit if
and only if U-18 shows the advantage holds on low-overlap queries.

### C. Score-level fusion (normalise BM25 and cosine, then add)

Rejected. BM25 is unbounded and corpus-dependent; cosine lives in [−1, 1]. Any combination
needs a normalisation that is itself a tuned, corpus-specific choice, and min-max in particular
is dominated by whichever arm has the larger spread on that query. RRF needs no normalisation
and cannot be destabilised by one arm's score distribution shifting. The acknowledged cost is
that RRF discards margin: a confident arm counts the same as a marginal one.

### D. Tune the RRF constant or the arm weights now

Rejected as premature. With every comparison's CI straddling zero, a tuning sweep would be
fitting noise, and the winning constant would be the one that happened to flip a single item.
`k=60` is the published default (Cormack et al., 2009) and is held fixed so the architecture
is the only variable. Revisit after the gold set grows and after U-18.

### E. Postgres `ts_rank_cd` instead of BM25

Rejected. It is already available and index-backed, which is genuinely attractive, but it has
neither IDF saturation nor document-length normalisation, and its scores are not comparable to
any published baseline. Since fusion only consumes ranks, either would function — but a column
labelled BM25 should contain BM25.

### F. Add a cross-encoder reranker before settling this

Rejected for now, and deliberately: a reranker reorders what retrieval already found, so it
cannot fix a recall ceiling, and at recall@10 near 0.98 there is almost nothing left for it to
recover on this corpus. Measuring it here would mostly measure the gold set's easiness. It
belongs after the corpus grows, as its own ADR with its own latency and cost numbers.

### G. Declare hybrid the winner and move on

The tempting option, and the dishonest one. The numbers do not show hybrid winning; they show
that this benchmark cannot yet tell these configurations apart. Writing "hybrid wins, +1.9pp
over dense" would have been defensible-looking, reproducible, and false in its implication.
What is recorded instead is the decision, the weak evidence for it, and the experiment that
would settle it.
