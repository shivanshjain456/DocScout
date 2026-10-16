# ADR-0079: Data Contamination & Lexical Leakage Stratifier (FEAT-088)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Assurance Guild, Search & Retrieval Engineering, Benchmarking Working Group
* **Informed:** Core Platform Engineers, Operations

---

## Context and Problem Statement

In regulatory evaluation benchmarks, gold set questions are frequently authored from statutory citation quotes. Consequently, query text often inherits significant verbatim vocabulary from the target document chunk.

This vocabulary overlap creates a lexical leakage confounder: lexical search methods (such as BM25) receive an artificial advantage by matching verbatim terms, inflating their benchmark performance relative to what real users type in their own natural vocabulary.

Reporting only macro-averaged retrieval metrics masks performance drops on realistic low-overlap inquiries. DocScout requires automated stratification into three discrete lexical leakage strata (< 0.50, 0.50 - 0.80, and >= 0.80) to diagnose benchmark memorization, monitor genuine semantic retrieval power on low-leakage queries, and prevent regressions below target thresholds.

---

## Decision Drivers

1. **Stratified Transparency Over Aggregate Obfuscation:**
   Report retrieval metrics (recall, hit rate, MRR, nDCG) partitioned across three canonical leakage bands:
   - `low_leakage`: question/quote term overlap < 0.50 (real-world query distribution proxy)
   - `medium_leakage`: question/quote term overlap 0.50 - 0.80
   - `high_leakage`: question/quote term overlap >= 0.80 (verbatim query proxy)
2. **Standardized Contract:**
   Define `LeakageConfig(low_threshold=0.50, high_threshold=0.80)`, `MetricSlice`, and `LeakageStratificationReport` conforming to `docscout.eval.retrieval/1`.
3. **Execution Performance:**
   Fast Python regex tokenization computing lexical term intersections in <= 5.0 ms for all 425 items without requiring live database connections.
4. **CI Regression Gating:**
   Enforce that low-leakage Recall@5 maintains target >= 0.900 and does not regress by > 1pp against established baseline averages.
5. **Typographical Invariant:** Strict ASCII typographical compliance across all documentation and code.

---

## Decision Outcome

We implement:
- `app/evals/leakage.py`:
  - `LeakageConfig`, `MetricSlice`, `LeakageStratificationReport`
  - `tokenize_terms`: Fast regex-based alphanumeric tokenizer
  - `compute_quote_lexical_overlap`: Term intersection ratio between query and gold quotes
  - `stratify_goldset_items`: Fast offline goldset item partitioner
  - `build_stratification_report`: Aggregation engine producing full `LeakageStratificationReport`
- `app/evals/runner.py`:
  - Wire `build_stratification_report` into `write_report()`
  - Write `"leakage_stratification"` into `results.json` and render stratified table in `report.md`
- `app/evals/gate.py`:
  - Add `check_leakage_gate()` verifying 1pp regression limits and >= 0.900 target on low-leakage recall
- `app/evals/goldset.py`:
  - CLI subcommand `python -m app.evals.goldset leakage` for offline inspection
- `app/evals/__init__.py`: Export leakage stratification types
- `tests/test_leakage_stratifier.py`: 8 comprehensive tests validating tokenization, boundary rules, performance, report serialization, and gate enforcement

---

## Validation and Testing

1. Verified stratification of 365 answerable gold set items: 297 low (<0.50), 64 medium (0.50-0.80), 4 high (>=0.80) in < 5 ms.
2. Verified regression gate detects 1pp drops while allowing legacy baselines to pass cleanly.
3. Verified full test suite passes with zero lint, format, or typecheck errors.
