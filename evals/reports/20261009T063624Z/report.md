# Retrieval baseline  -  2026-10-09T06:36:30Z

Retrieval only. No reranker, no generator, no LLM judge: those stages do not exist yet, and are reported as `null` rather than as zeros.

## Configurations compared

| config | mode | k_dense | k_lexical | k_final | rrf_k |
|---|---|---|---|---|---|
| `dense-only` | dense | 50 |  -  | 10 |  -  |
| `bm25-only` | bm25 |  -  | 50 | 10 |  -  |
| `hybrid-rrf` | hybrid | 50 | 50 | 10 | 60 |

Scored on 365 answerable gold items; 60 unanswerable items excluded from retrieval metrics (they carry no citations to cover; they are scored for abstention instead).

## Results @ k=1

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.685 | 0.699 | 0.807 | 0.699 |
| `bm25-only` | 0.742 | 0.762 | 0.858 | 0.762 |
| `hybrid-rrf` | 0.742 | 0.759 | 0.854 | 0.759 |

## Results @ k=3

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.911 | 0.921 | 0.807 | 0.812 |
| `bm25-only` | 0.951 | 0.959 | 0.858 | 0.863 |
| `hybrid-rrf` | 0.940 | 0.951 | 0.854 | 0.855 |

## Results @ k=5

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.952 | 0.959 | 0.807 | 0.829 |
| `bm25-only` | 0.979 | 0.981 | 0.858 | 0.875 |
| `hybrid-rrf` | 0.966 | 0.970 | 0.854 | 0.867 |

## Results @ k=10

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.974 | 0.975 | 0.807 | 0.836 |
| `bm25-only` | 0.992 | 0.992 | 0.858 | 0.879 |
| `hybrid-rrf` | 0.997 | 0.997 | 0.854 | 0.877 |

## Latency

Measured on 24 vCPU / None GiB, Windows-11-10.0.26200-SP0. Retrieval only; the embedding model is loaded once before the run and excluded, because loading it per query would measure startup.

| config | mean | p50 | p95 | max |
|---|---|---|---|---|
| `dense-only` | 109.0 ms | 107.6 ms | 122.1 ms | 253.9 ms |
| `bm25-only` | 1.0 ms | 0.8 ms | 1.7 ms | 3.7 ms |
| `hybrid-rrf` | 111.4 ms | 109.0 ms | 126.2 ms | 270.1 ms |

## A/B outcome

Ranked by recall@5: **`bm25-only`** leads at 0.979.

- `hybrid-rrf`: recall@5 0.966 (+0.014 vs leader, +5.0 items), MRR 0.854, p95 126.2 ms.
- `dense-only`: recall@5 0.952 (+0.027 vs leader, +10.0 items), MRR 0.807, p95 122.1 ms.

### Is the difference real?

Paired bootstrap, 10,000 resamples, fixed seed. `excludes zero` means the sign of the difference survived resampling; it is not a hypothesis test.

| comparison | diff (recall) | 95% CI | in items | discordant hits | excludes zero |
|---|---|---|---|---|---|
| `dense-only` vs `bm25-only` | -0.0178 | [-0.0342, -0.0027] | -6.5 | dense-only:1 / bm25-only:7 | yes |
| `dense-only` vs `hybrid-rrf` | -0.0233 | [-0.0397, -0.0096] | -8.5 | dense-only:0 / hybrid-rrf:8 | yes |
| `bm25-only` vs `hybrid-rrf` | -0.0055 | [-0.0137, +0.0000] | -2.0 | bm25-only:0 / hybrid-rrf:2 | **no** |

### Leakage caveat

The gold set's questions were authored from the evidence quotes, so they share vocabulary with the chunk they point at: on this run a question's analyzed terms appear in its own gold chunk far more often than in a random one. That advantages the lexical arm, so BM25's standing here is inflated by construction and is not evidence that BM25 beats hybrid on questions a human would type. Recall by leakage band:

| question/evidence term overlap | `dense-only` | `bm25-only` | `hybrid-rrf` | n |
|---|---|---|---|---|
| low <0.5 | 0.889 | 0.889 | 0.889 | 54 |
| mid 0.5-0.8 | 0.946 | 0.992 | 0.972 | 193 |
| high >=0.8 | 0.992 | 1.000 | 0.992 | 118 |

## Abstention

Signal: evidence coverage, separation AUC **0.8297** (0.5 is chance). At the shipped threshold 0.65:

| metric | value |
|---|---|
| abstention recall | 0.583 |
| false rejection rate | 0.090 |
| refusal precision | 0.515 |
| selective accuracy | 0.864 |
| refusal rate | 0.160 |

| threshold | caught unanswerable | wrongly flagged | precision |
|---|---|---|---|
| 0.40 | 7/60 | 0/365 | 1.00 |
| 0.50 | 19/60 | 3/365 | 0.86 |
| 0.55 | 25/60 | 6/365 | 0.81 |
| 0.60 | 31/60 | 11/365 | 0.74 |
| 0.65 | 35/60 | 33/365 | 0.51 |
| 0.70 | 41/60 | 46/365 | 0.47 |
| 0.75 | 46/60 | 70/365 | 0.40 |
| 0.80 | 49/60 | 115/365 | 0.30 |
| 0.90 | 54/60 | 224/365 | 0.19 |

## Reproduce

```bash
make eval
```

Gold set `2.0.0` (sha256 `ea148e329453e820…`), corpus manifest `7fad4b6ebf713303…`, uv.lock `47bf85305a1bcbc1…`.

Raw per-item rankings: `results.json`.
