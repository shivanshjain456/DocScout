# Verification story 1 — a retrieval miss the eval harness caught

A worked example of the loop this project exists to demonstrate: the evaluation harness found
a real defect, the defect was diagnosed rather than patched around, the fix was chosen against
measured alternatives, and a regression test now fails if it ever comes back.

Everything below is reproducible with committed commands and committed raw output.

---

## 1. What the harness found

The first retrieval baseline scored 131 answerable gold items. Six fell short of perfect
recall@5; one was different in kind:

```
g-038  type=extractive  difficulty=hard  groups=1
       recall@5=0.00  recall@10=0.00  first_relevant_rank=None
```

`first_relevant_rank=None` with `recall@10=0.00` means the correct chunk was **not returned at
all**. Every other miss was a ranking problem. This one was a retrieval failure.

> **g-038** — *Which withdrawn circular dealt with CCTV coverage of cash handling operations in
> currency chests, and on what date was it issued?*
>
> Evidence quote: `23-May-14 DCM.(CC).No.G- 20/03.39.01/2013-14 CCTV Coverage of All Cash
> Handling Operations in Currency Chests`
>
> Required citation: `32457830-3217-579d-bb5f-0abe24a87676`

Reproduce:

```bash
make eval
python - <<'PY'
import json, glob
d = json.load(open(sorted(glob.glob("evals/reports/*/results.json"))[-1]))
cfg = next(c for c in d["configs"] if c["config"]["name"] == "hybrid-rrf")
print(next(r for r in cfg["items"] if r["item_id"] == "g-038"))
PY
```

## 2. Diagnosis

The first question was whether the gold item was wrong. It was not: the quote is verbatim in
the source PDF, the citation resolves through the production chunker, and the question is the
product's core use case — an analyst asking what a withdrawn circular said.

So the arms were measured individually:

| arm | rank of the correct chunk | detail |
|---|---|---|
| BM25 | **1** | score 18.09, the top hit by a decisive margin |
| dense | 41 | cosine 0.613, against a top hit of 0.715 |
| hybrid RRF (k=60) | **14** | outside the served depth of 10 |

**One arm had the answer in first place and fusion threw it away.**

The mechanism is arithmetic, not a bug. RRF scores each document `1/(k + rank)` per arm:

```
gold chunk   lexical rank  1 -> 1/61  = 0.01639
             dense   rank 41 -> 1/101 = 0.00990   total 0.02629

rival chunk  dense   rank  1 -> 1/61  = 0.01639
             lexical rank  2 -> 1/62  = 0.01613   total 0.03252   <-- wins
```

At `k=60`, rank 1 is worth only **1.66×** rank 41. Rank-only fusion cannot express certainty,
so broad agreement beats one arm's conviction. `app/retrieval/fusion.py` had already recorded
this as RRF's accepted cost — "an arm that is certain of its top hit contributes exactly as
much as one that barely preferred it". This is that cost arriving, and in this domain it is not
rare: questions turn on exact tokens like a circular number or "CCTV", which is exactly where
BM25 is confident and where the dense arm, embedding a chunk that is a table of fifty unrelated
circulars, has nothing coherent to represent.

## 3. Candidate fixes, measured

Fixing this on one question would be overfitting, so both candidates were run over the whole
gold set with a paired bootstrap:

```bash
uv run python -m scripts.experiments.u10_rrf_constant_sweep
```

| variant | R@1 | R@5 | R@10 | MRR | Δ R@5 vs k=60 | CI excludes 0 | g-038 R@10 |
|---|---|---|---|---|---|---|---|
| k=1 | 0.695 | 0.977 | 0.992 | 0.830 | +0.0115 | no | 1.00 |
| k=5 | 0.695 | 0.977 | 0.992 | 0.826 | +0.0115 | no | 1.00 |
| k=10 | 0.695 | 0.966 | 0.992 | 0.825 | +0.0000 | no | 1.00 |
| k=20 / 30 / 60 / 100 | 0.695 | 0.966 | 0.992 | 0.824 | +0.0000 | no | 0.00 |
| **k=60 + arm anchor** | 0.695 | 0.966 | **1.000** | 0.825 | +0.0000 | — | **1.00** |

Lowering the constant works, but its 1.15pp gain is 1.5 items with a CI spanning zero, and
ADR-0006 had already rejected tuning the constant on exactly that basis. The structural fix —
reserve a seat for each arm's own top hit — is the only variant that makes recall@10 complete,
and a per-item comparison over all 131 items at both cutoffs found **0 items worse, 1 better**.

Chosen: keep `rrf_k=60`, add the guarantee. Full reasoning and five rejected alternatives in
[ADR-0007](../decisions/0007-arm-anchored-fusion.md).

## 4. Before and after

Serving configuration `hybrid-rrf`, all 131 answerable items:

| metric | before | after |
|---|---|---|
| recall@1 | 0.6947 | 0.6947 |
| recall@5 | 0.9656 | 0.9656 |
| **recall@10** | **0.9924** | **1.0000** |
| MRR | 0.8240 | 0.8247 |
| nDCG@5 | 0.8445 | 0.8445 |
| **g-038 recall@10** | **0.00** | **1.00** |
| g-038 first relevant rank | none | 10 |

Raw output: [`evals/reports/20261001T192924Z/`](../../evals/reports/20261001T192924Z/) (before)
and [`evals/reports/20261001T204628Z/`](../../evals/reports/20261001T204628Z/) (after).

The regression gate was run against the fix and passed — recall and nDCG unchanged, MRR
+0.07pp, no invariant violated:

```bash
make eval-gate     # PASS, exit 0
```

## 5. The regression test

Four tests in `tests/test_retrieval.py`. Two of them fail if the fix is removed, verified by
removing it:

```
$ # anchor_arm_top1 temporarily set to False in SERVING_CONFIG
$ uv run pytest tests/test_retrieval.py -k "g038 or anchor"
FAILED tests/test_retrieval.py::test_g038_confident_lexical_hit_survives_fusion
FAILED tests/test_retrieval.py::test_anchored_chunk_keeps_its_real_fused_score
```

One of the four is deliberately inverted — `test_g038_is_still_buried_without_the_anchor`
asserts that plain RRF *still* fails on this query. If a future change makes plain fusion
surface the chunk unaided, that test fails and ADR-0007 gets revisited instead of the
guarantee surviving as cargo cult.

## 6. What this does not prove

- **The aggregate movement is one item.** The fix is adopted because it removes a diagnosed
  structural failure at zero measured cost, not because 131 questions can prove it is better.
  No bootstrap CI here excludes zero.
- **recall@10 = 1.000 is a ceiling effect**, not a solved problem. The corpus is 170 chunks.
  The number will fall as the corpus grows, and recall@10 has now lost its power to
  discriminate; the gate's useful signal is recall@5 and MRR.
- **The dense arm's top hit is anchored too.** It displaced nothing useful here, but on a
  corpus where the dense arm is noisy that is a real cost, and it needs re-measuring.
- **No generator was involved.** This is a retrieval miss, not a hallucination. The equivalent
  story for faithfulness needs a generator and a judge, both blocked on API keys (U-1).
