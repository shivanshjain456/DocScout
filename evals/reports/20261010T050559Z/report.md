# Retrieval baseline  -  2026-10-10T05:06:27Z

Retrieval only. No reranker, no generator, no LLM judge: those stages do not exist yet, and are reported as `null` rather than as zeros.

## Methods & Limits: Evaluation vs Production Invariant

In accordance with ADR-0024 and ADR-0025, production retrieval strictly excludes synthetic documents (`NOT d.is_synthetic`), serving the 20 authoritative regulator documents. This evaluation gate measures retrieval over the full 35-document evaluation corpus (20 real + 15 synthetic fixtures) via the explicit `include_synthetic=True` evaluation override, preserving continuous measurement across all 365 answerable gold items. Production recall is bounded to real documents; evaluation recall measures total retrieval capability over the multi-document benchmark corpus.

## Configurations compared

| config | mode | k_dense | k_lexical | k_final | rrf_k |
|---|---|---|---|---|---|
| `dense-only` | dense | 50 |  -  | 10 |  -  |
| `bm25-only` | bm25 |  -  | 50 | 10 |  -  |
| `hybrid-rrf` | hybrid | 50 | 50 | 10 | 60 |
| `hybrid-expanded` | hybrid | 50 | 50 | 10 | 60 |
| `graph-hybrid` | graph-hybrid | 50 | 50 | 10 |  -  |

Scored on 365 answerable gold items; 60 unanswerable items excluded from retrieval metrics (they carry no citations to cover; they are scored for abstention instead).

## Results @ k=1

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.685 | 0.699 | 0.807 | 0.699 |
| `bm25-only` | 0.742 | 0.762 | 0.858 | 0.762 |
| `hybrid-rrf` | 0.742 | 0.759 | 0.854 | 0.759 |
| `hybrid-expanded` | 0.712 | 0.729 | 0.838 | 0.729 |
| `graph-hybrid` | 0.090 | 0.093 | 0.323 | 0.093 |

## Results @ k=3

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.911 | 0.921 | 0.807 | 0.812 |
| `bm25-only` | 0.951 | 0.959 | 0.858 | 0.863 |
| `hybrid-rrf` | 0.940 | 0.951 | 0.854 | 0.855 |
| `hybrid-expanded` | 0.942 | 0.953 | 0.838 | 0.845 |
| `graph-hybrid` | 0.388 | 0.392 | 0.323 | 0.255 |

## Results @ k=5

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.952 | 0.959 | 0.807 | 0.829 |
| `bm25-only` | 0.979 | 0.981 | 0.858 | 0.875 |
| `hybrid-rrf` | 0.966 | 0.970 | 0.854 | 0.867 |
| `hybrid-expanded` | 0.966 | 0.970 | 0.838 | 0.855 |
| `graph-hybrid` | 0.700 | 0.701 | 0.323 | 0.383 |

## Results @ k=10

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.974 | 0.975 | 0.807 | 0.836 |
| `bm25-only` | 0.992 | 0.992 | 0.858 | 0.879 |
| `hybrid-rrf` | 0.997 | 0.997 | 0.854 | 0.877 |
| `hybrid-expanded` | 0.997 | 0.997 | 0.838 | 0.865 |
| `graph-hybrid` | 0.964 | 0.970 | 0.323 | 0.471 |

## Latency

Measured on 24 vCPU / None GiB, Windows-11-10.0.26200-SP0. Retrieval only; the embedding model is loaded once before the run and excluded, because loading it per query would measure startup.

| config | mean | p50 | p95 | max |
|---|---|---|---|---|
| `dense-only` | 81.3 ms | 81.2 ms | 102.1 ms | 139.6 ms |
| `bm25-only` | 1.6 ms | 1.6 ms | 2.2 ms | 3.3 ms |
| `hybrid-rrf` | 92.0 ms | 88.5 ms | 114.4 ms | 380.6 ms |
| `hybrid-expanded` | 73.7 ms | 70.2 ms | 96.6 ms | 741.2 ms |
| `graph-hybrid` | 114.6 ms | 111.5 ms | 147.0 ms | 450.0 ms |

## A/B outcome

Ranked by recall@5: **`bm25-only`** leads at 0.979.

- `hybrid-rrf`: recall@5 0.966 (+0.014 vs leader, +5.0 items), MRR 0.854, p95 114.4 ms.
- `hybrid-expanded`: recall@5 0.966 (+0.014 vs leader, +5.0 items), MRR 0.838, p95 96.6 ms.
- `dense-only`: recall@5 0.952 (+0.027 vs leader, +10.0 items), MRR 0.807, p95 102.1 ms.
- `graph-hybrid`: recall@5 0.700 (+0.279 vs leader, +102.0 items), MRR 0.323, p95 147.0 ms.

### Is the difference real?

Paired bootstrap, 10,000 resamples, fixed seed. `excludes zero` means the sign of the difference survived resampling; it is not a hypothesis test.

| comparison | diff (recall) | 95% CI | in items | discordant hits | excludes zero |
|---|---|---|---|---|---|
| `dense-only` vs `bm25-only` | -0.0178 | [-0.0342, -0.0027] | -6.5 | dense-only:1 / bm25-only:7 | yes |
| `dense-only` vs `hybrid-rrf` | -0.0233 | [-0.0397, -0.0096] | -8.5 | dense-only:0 / hybrid-rrf:8 | yes |
| `dense-only` vs `hybrid-expanded` | -0.0233 | [-0.0397, -0.0096] | -8.5 | dense-only:0 / hybrid-expanded:8 | yes |
| `dense-only` vs `graph-hybrid` | +0.0096 | [-0.0137, +0.0329] | +3.5 | dense-only:10 / graph-hybrid:8 | **no** |
| `bm25-only` vs `hybrid-rrf` | -0.0055 | [-0.0137, +0.0000] | -2.0 | bm25-only:0 / hybrid-rrf:2 | **no** |
| `bm25-only` vs `hybrid-expanded` | -0.0055 | [-0.0164, +0.0055] | -2.0 | bm25-only:1 / hybrid-expanded:3 | **no** |
| `bm25-only` vs `graph-hybrid` | +0.0274 | [+0.0096, +0.0479] | +10.0 | bm25-only:10 / graph-hybrid:2 | yes |
| `hybrid-rrf` vs `hybrid-expanded` | +0.0000 | [-0.0082, +0.0082] | +0.0 | hybrid-rrf:1 / hybrid-expanded:1 | **no** |
| `hybrid-rrf` vs `graph-hybrid` | +0.0329 | [+0.0164, +0.0521] | +12.0 | hybrid-rrf:10 / graph-hybrid:0 | yes |
| `hybrid-expanded` vs `graph-hybrid` | +0.0329 | [+0.0151, +0.0534] | +12.0 | hybrid-expanded:11 / graph-hybrid:1 | yes |

### Leakage caveat

The gold set's questions were authored from the evidence quotes, so they share vocabulary with the chunk they point at: on this run a question's analyzed terms appear in its own gold chunk far more often than in a random one. That advantages the lexical arm, so BM25's standing here is inflated by construction and is not evidence that BM25 beats hybrid on questions a human would type. Recall by leakage band:

| question/evidence term overlap | `dense-only` | `bm25-only` | `hybrid-rrf` | `hybrid-expanded` | `graph-hybrid` | n |
|---|---|---|---|---|---|---|
| low <0.5 | 0.889 | 0.889 | 0.889 | 0.889 | 0.759 | 54 |
| mid 0.5-0.8 | 0.946 | 0.992 | 0.972 | 0.972 | 0.663 | 193 |
| high >=0.8 | 0.992 | 1.000 | 0.992 | 0.992 | 0.733 | 118 |

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

Gold set `2.0.0` (sha256 `1a640cce7d27bf2d…`), corpus manifest `3c7a585f24068d83…`, uv.lock `11d95b4327db31ef…`.

Raw per-item rankings: `results.json`.
