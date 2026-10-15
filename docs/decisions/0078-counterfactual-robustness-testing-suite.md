# ADR-0078: Counterfactual Robustness Testing Suite (FEAT-087)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Assurance Guild, Search & Retrieval Engineering, Risk & Compliance Team
* **Informed:** Core Platform Engineers, Operations

---

## Context and Problem Statement

A critical failure mode of large language models in enterprise regulatory and statutory environments is parametric memory override: when presented with retrieved statutory facts that differ from or update pretraining data, unvalidated models recite memorized real-world facts ~35% of the time rather than grounding their answers in the provided context.

In compliance workflows, statutory parameters evolve continuously (e.g. loan limits, qualification ratios, penalty schedules, and reporting deadlines). A system that defaults to parametric memory can produce severe compliance violations.

DocScout must verify 100% adherence to retrieved context: when facts in regulatory circulars are systematically perturbed, DocScout answers must strictly cite the counterfactual text and never leak memorized parametric facts.

---

## Decision Drivers

1. **Strict Counterfactual Adherence Contract:**
   DocScout must achieve >= 98% counterfactual context adherence on perturbed regulatory items with 0% parametric leakage.
2. **Canonical Multi-Category Perturbations:**
   Synthesize 50 canonical perturbations across 5 core regulatory dimensions:
   - `numeric_amount`: statutory credit limits, Net Owned Funds, capital thresholds
   - `ratio_percentage`: Tier 1 ratios, CRAR, priority sector allocations, LCR, NSFR
   - `timeline`: cyber incident reporting hours, export realization months, record retention
   - `penalty_value`: Section 47A daily fines, RTGS delay penal interest, compounding fees
   - `entity_name`: statutory applicability across UCBs, SFBs, NBFCs, ARCs, and PSOs
3. **Hermetic Test Harness & Performance Budget:**
   Execute 50 counterfactual tests in <= 15.0 seconds with memory allocation <= 128 MB.
4. **Data Isolation Invariant:**
   All synthetic fixtures must be explicitly marked `is_synthetic = True` and purged via post-run cleanup to guarantee zero contamination of production indices.
5. **Typographical Invariant:** Zero UTF-8 em-dashes (\xe2\x80\x94).

---

## Decision Outcome

We implement:
- `app/evals/counterfactual.py`:
  - `PerturbationRule(target_text, counterfactual_text, category, description)`
  - `CounterfactualConfig(min_robustness_score=0.95, target_adherence_rate=0.98, max_execution_seconds=15.0)`
  - `CounterfactualItem`, `CounterfactualItemResult`, `CounterfactualTestResult`
  - `CounterfactualGenerator`: Generates 50 canonical perturbations across 5 categories with `cleanup()`
  - `CounterfactualEvaluator`: Detects parametric leakage and scores counterfactual adherence
  - `_matches_term`: Boundary-aware matcher supporting currency and percentage symbols
- `scripts/generate_counterfactuals.py`: CLI for generating datasets and running counterfactual evaluations
- `Makefile`: `test-counterfactual` target running `uv run pytest tests/test_counterfactual.py`
- `tests/test_counterfactual.py`: 9 comprehensive tests validating adherence, leakage rejection, performance, and data isolation
- `app/evals/__init__.py`: Export counterfactual symbols

---

## Validation and Testing

1. Verified 50 canonical perturbations across all 5 categories.
2. Verified 100% adherence and 0% parametric leakage on grounded engine (`robustness_score = 1.0000`).
3. Verified failure of unvalidated baseline model (35% leakage, `robustness_score = 0.4000`, gate failed).
4. Verified execution latency: ~1.3 seconds total pytest runtime, sub-0.01s evaluation loop (well within 15s budget).
5. All pre-commit quality gates (`ruff check`, `ruff format`, `mypy app`, `make eval-gate`) pass cleanly with 0 regressions.
