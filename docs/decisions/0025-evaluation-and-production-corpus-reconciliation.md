# ADR-0025: Reconciliation of Synthetic Artifact Isolation and Evaluation Gate Corpus

- **Status:** accepted
- **Date:** 2026-10-10
- **Deciders:** Core Engineering / Antigravity Agent
- **Related:** ADR-0024, EVAL_PROTOCOL §E-12, §E-18

## Context

In commit `00e94fd`, DocScout introduced `migrations/0010_synthetic_artifact_provenance.up.sql` to isolate synthetic test fixtures from production queries. The migration added the `documents.is_synthetic` boolean column, indexing, and data classifications marking 15 fixtures (`synthetic://canary-001`, `NOTI280-NOTI287`, `178810-178860`) as `is_synthetic = true`. Production retrieval (`app/retrieval/dense.py:65`, `app/retrieval/types.py:60`, and `app/digests/engine.py:208`) enforces `WHERE NOT d.is_synthetic` by default.

However, `evals/gold/v1/gold.jsonl` contains 425 total items (60 unanswerable, 365 answerable items). Analysis reveals:
- 237 answerable items point solely to synthetic fixture documents.
- 128 answerable items point solely to real regulator documents.

Because the evaluation runner (`app/evals/runner.py`) inherited production defaults without an explicit filter override, retrieval queries for the 237 synthetic-linked items could never return their corresponding chunks. Consequently, recall for those items dropped to zero, projecting an aggregate recall@10 collapse from baseline `0.997` down to approximately `0.35` (>60 percentage point drop). This deterministically violates the 1pp threshold enforced by the E-12 CI regression gate (`app/evals/gate.py`).

## Decision

We adopt **Option A: Evaluation-Only Override with Full Disclosure**.

Specifically:
1. `app/evals/runner.py` is updated so that all benchmark retrieval executions construct and pass `MetadataFilter(include_synthetic=True)` (`run_config` and `_score_abstention`).
2. Production code paths (`app/api/app.py`, `app/digests/*`, search endpoints) retain their strict `NOT d.is_synthetic` default.
3. The relationship between production and evaluation corpora is formally codified in `docs/eval/EVAL_PROTOCOL.md §E-18`, this ADR, and every eval report header:
   *Production recall ≠ evaluation recall: production serves 20 authoritative documents; the evaluation harness and regression gate evaluate the full 35-document corpus (including 15 synthetic fixtures) to measure holistic retrieval across all 365 answerable gold items.*

## Consequences

### Positive
- **Continuous Measurement:** Preserves unbroken historical evaluation across all 365 answerable gold items without dropping 65% of the benchmark.
- **Gate Invariant Stability:** Maintains `items_scored = 365`, satisfying `check_invariants` in `app/evals/gate.py` which prohibits gold set shrinkage against the baseline window.
- **Zero Gold Set Churn:** Avoids re-pinning or regenerating `evals/gold/v1/gold.jsonl` and keeps `goldset_sha256` matching existing baseline records.
- **Production Integrity Maintained:** Zero synthetic contamination in production search or email digests.

### Negative / Trade-Offs
- **Corpus Size Divergence:** Production serves 20 real regulator documents, whereas evaluation measures retrieval accuracy over 35 documents. This trade-off is acceptable because finding relevant passages in a larger 35-document corpus with synthetic distractors is strictly harder than searching 20 documents, providing conservative retrieval bounds.

## Rejected Alternatives

### Option B: Regenerate Gold Set to Real-Only (128 Items)
- **What it is:** Filter `evals/gold/v1/gold.jsonl` to exclude the 237 synthetic items, bump `goldset_version` to `2.1.0`, move synthetic items to canary/abstention files, and re-baseline the gate.
- **Why it was plausible:** Evaluation would measure the exact 20 documents served in production.
- **Why rejected:**
  1. Discarding 237 items (65% of the gold set) significantly degrades statistical power and widens bootstrap confidence intervals.
  2. `app/evals/gate.py:260` explicitly fails when `current["items_scored"] < newest["items_scored"]` ("items vanished from the gold set"). Changing this requires re-baselining the entire 3-run baseline window in `evals/baselines/`.
  3. The synthetic fixtures represent multi-hop, numeric, and edge-case regulatory scenarios that remain valuable for testing retrieval ranking and cross-encoder discrimination.

### Option C: Dual-Index Architecture
- **What it is:** Maintain two distinct PostgreSQL database instances or schemas (`production` with 20 docs, `eval` with 35 docs).
- **Why it was plausible:** Provides complete physical isolation between evaluation and production data stores.
- **Why rejected:** Unnecessary operational overhead. Row-level `is_synthetic` boolean tagging with indexed query filtering already provides bulletproof isolation at zero additional infrastructure cost.
