# Verification story 2  -  measuring when the corpus cannot answer

A seventh of the gold set was doing no work, and the obvious way to use it turned out not
to function. This records what was measured, what was rejected on the evidence, and what
shipped.

Everything below is reproducible with `make eval`; the numbers come from
`evals/reports/<timestamp>/results.json` under the `abstention` key.

---

## 1. The gap

`EVAL_PROTOCOL` Q-18 requires the gold set to be at least 10% unanswerable, and it is:
**22 of 153 items, 14.4%**. Every one of them was excluded from every metric. The eval
runner filtered them out because the retrieval scorers measure citation coverage, and an
item with no citations has none to cover  -  a correct reason to exclude them from *those*
metrics, and a bad reason to leave them unmeasured entirely.

These are the expensive items. Each was written so the corpus *nearly* answers it, and the
`unanswerable_reason` fields say so:

> "The nine-month figure retrieves strongly."
> "The deadline text retrieves strongly, which is what makes the question dangerous."
> "The URL retrieves well."

A question whose topic is absent is easy. A question whose topic is present and whose
**answer** is absent is the one that produces a confident, well-cited, wrong result.

## 2. The obvious signal does not work

The standard advice is confidence gating: abstain when the top retrieval score is low.
Measured over all 153 items, ranked by how well each signal separates answerable from
unanswerable (AUC; 0.5 is chance):

| signal | AUC | verdict |
|---|---|---|
| `rrf_top`  -  the serving configuration's own score | **0.467** | worse than chance |
| `dense_margin`  -  top-1 minus top-5 cosine | 0.461 | no signal, pointing the wrong way |
| `docs_in_top10`  -  how many documents the results span | 0.477 | no signal |
| `dense_top`  -  best cosine similarity | 0.574 | weak |
| `bm25_top`  -  best BM25 score | 0.655 | weak |
| **`cover_top5`**  -  query terms found in the top 5 passages | **0.730** | usable |

`rrf_top` cannot work even in principle: RRF scores by rank, so the top result's score is
nearly constant whether or not anything relevant was found. Shipping a gate on it would
have produced a feature that looked plausible and did nothing.

`bm25_top`, the best of the score-based options, buys 55% of unanswerable questions at the
cost of wrongly refusing **24% of answerable** ones. For a compliance tool that is not a
trade worth making.

## 3. What does work, and why

**Evidence coverage**: the fraction of the question's analyzed terms that appear anywhere
in the top five passages.

The mechanism is the reason it beats the scores. An unanswerable question here is usually
unanswerable because of one specific word the corpus never uses, while every other word in
the question retrieves its topic perfectly. A score rewards the matching topic. Coverage
notices the missing word  -  and can name it:

| item | question | missing terms |
|---|---|---|
| g-129 | "What **penalty** applies to a Market Infrastructure Institution that fails to operationalise…" | `penalti`, `fail`, `operationalis` |
| g-131 | "What is the **minimum** acceptable ITRI score an MII must **maintain**?" | `minimum`, `maintain`, `must` |

Terms come from Postgres's own analyzer through the BM25 index, so the stemming and
stopword list are exactly the lexical arm's. There is no second tokenizer to drift.

## 4. Choosing the operating point

| threshold | caught unanswerable | wrongly flagged | refusal precision |
|---|---|---|---|
| 0.50 | 2/22 (9%) | 0/131 (0%) | 1.00 |
| 0.60 | 4/22 (18%) | 2/131 (2%) | 0.67 |
| **0.65** | **6/22 (27%)** | **4/131 (3%)** | **0.60** |
| 0.70 | 9/22 (41%) | 10/131 (8%) | 0.47 |
| 0.75 | 11/22 (50%) | 16/131 (12%) | 0.41 |
| 0.80 | 15/22 (68%) | 35/131 (27%) | 0.30 |

**0.65 ships.** It is the last point where a flag is right more often than it is wrong
(precision 0.60). At 0.70 the majority of flags are false, which is the threshold at which
users learn to ignore a warning.

At that point: abstention recall **0.273**, false rejection rate **0.030**, refusal
precision **0.600**, selective accuracy **0.869**.

## 5. It is a flag, not a refusal

The API returns the coverage, the missing terms and the `low_evidence` boolean **alongside
the passages**. It does not withhold them.

A signal with AUC 0.730 has no business making that decision for a caller. Over-refusal is
a documented failure mode  -  FinRAG-12B reports GPT-4.1 refusing 20.2% of queries against a
calibrated 12%  -  and at threshold 0.65 this signal would be wrong 40% of the times it
fired. Surfacing uncertainty is useful; acting on it unilaterally at this accuracy is not.

## 6. What this does not show

- **It catches about a quarter of unanswerable questions.** Three quarters still return
  confident-looking passages with no flag. This is an improvement on zero, not a solution.
- **The threshold is calibrated on the same 153 items it is evaluated on.** There is no
  held-out split, because the gold set is the only labelled data that exists. The AUC is
  therefore optimistic and the operating point may not transfer to a larger corpus.
- **Coverage is lexical.** A question answered by a paraphrase the corpus states in other
  words will score low and be flagged wrongly; that is part of the 3%.
- **It says nothing about faithfulness.** This measures whether the evidence covers the
  *question*, not whether any answer derived from it would be correct. There is no
  generator (ADR-0008), so there is no answer to assess.
