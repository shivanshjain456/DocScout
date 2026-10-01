# Retrieval baseline — 2026-10-01T20:46:29Z

Retrieval only. No reranker, no generator, no LLM judge: those stages do not exist yet, and are reported as `null` rather than as zeros.

## Configurations compared

| config | mode | k_dense | k_lexical | k_final | rrf_k |
|---|---|---|---|---|---|
| `dense-only` | dense | 50 | — | 10 | — |
| `bm25-only` | bm25 | — | 50 | 10 | — |
| `hybrid-rrf` | hybrid | 50 | 50 | 10 | 60 |

Scored on 131 answerable gold items; 22 unanswerable items excluded from retrieval metrics (they measure abstention, which is a generation property).

## Results @ k=1

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.611 | 0.626 | 0.762 | 0.626 |
| `bm25-only` | 0.702 | 0.725 | 0.838 | 0.725 |
| `hybrid-rrf` | 0.695 | 0.710 | 0.825 | 0.710 |

## Results @ k=3

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.882 | 0.901 | 0.762 | 0.765 |
| `bm25-only` | 0.927 | 0.947 | 0.838 | 0.837 |
| `hybrid-rrf` | 0.927 | 0.954 | 0.825 | 0.828 |

## Results @ k=5

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.947 | 0.962 | 0.762 | 0.793 |
| `bm25-only` | 0.969 | 0.977 | 0.838 | 0.855 |
| `hybrid-rrf` | 0.966 | 0.977 | 0.825 | 0.844 |

## Results @ k=10

| config | recall | hit rate | MRR | nDCG |
|---|---|---|---|---|
| `dense-only` | 0.981 | 0.985 | 0.762 | 0.804 |
| `bm25-only` | 1.000 | 1.000 | 0.838 | 0.866 |
| `hybrid-rrf` | 1.000 | 1.000 | 0.825 | 0.856 |

## Latency

Measured on 2 vCPU / 1.94 GiB, Linux-6.1.158+-x86_64-with-glibc2.41. Retrieval only; the embedding model is loaded once before the run and excluded, because loading it per query would measure startup.

| config | mean | p50 | p95 | max |
|---|---|---|---|---|
| `dense-only` | 33.2 ms | 31.4 ms | 45.5 ms | 73.2 ms |
| `bm25-only` | 0.5 ms | 0.4 ms | 0.9 ms | 1.0 ms |
| `hybrid-rrf` | 33.7 ms | 32.6 ms | 41.9 ms | 59.3 ms |

## A/B outcome

Ranked by recall@5: **`bm25-only`** leads at 0.969.

- `hybrid-rrf`: recall@5 0.966 (+0.004 vs leader, +0.5 items), MRR 0.825, p95 41.9 ms.
- `dense-only`: recall@5 0.947 (+0.023 vs leader, +3.0 items), MRR 0.762, p95 45.5 ms.

### Is the difference real?

Paired bootstrap, 10,000 resamples, fixed seed. `excludes zero` means the sign of the difference survived resampling; it is not a hypothesis test.

| comparison | diff (recall) | 95% CI | in items | discordant hits | excludes zero |
|---|---|---|---|---|---|
| `dense-only` vs `bm25-only` | -0.0191 | [-0.0420, +0.0000] | -2.5 | dense-only:0 / bm25-only:2 | **no** |
| `dense-only` vs `hybrid-rrf` | -0.0191 | [-0.0420, +0.0000] | -2.5 | dense-only:0 / hybrid-rrf:2 | **no** |
| `bm25-only` vs `hybrid-rrf` | +0.0000 | [+0.0000, +0.0000] | +0.0 | bm25-only:0 / hybrid-rrf:0 | **no** |

### Leakage caveat

The gold set's questions were authored from the evidence quotes, so they share vocabulary with the chunk they point at: on this run a question's analyzed terms appear in its own gold chunk far more often than in a random one. That advantages the lexical arm, so BM25's standing here is inflated by construction and is not evidence that BM25 beats hybrid on questions a human would type. Recall by leakage band:

| question/evidence term overlap | `dense-only` | `bm25-only` | `hybrid-rrf` | n |
|---|---|---|---|---|
| low <0.5 | 0.875 | 0.750 | 0.875 | 8 |
| mid 0.5-0.8 | 0.931 | 0.986 | 0.972 | 72 |
| high >=0.8 | 0.980 | 0.980 | 0.971 | 51 |

## Reproduce

```bash
make eval
```

Gold set `1.0.0` (sha256 `172b8fec0bfe2e12…`), corpus manifest `eca4908c2f22c68a…`, uv.lock `600c90010345412c…`.

Raw per-item rankings: `results.json`.
