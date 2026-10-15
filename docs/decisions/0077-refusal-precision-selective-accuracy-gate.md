# ADR-0077: Refusal Precision & Selective Accuracy Gate (FEAT-086)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Assurance Guild, Search & Retrieval Engineering, Risk & Compliance Team
* **Informed:** Core Platform Engineers, Operations

---

## Context and Problem Statement

In regulatory and statutory compliance, producing an incorrect or hallucinated citation when statutory provisions do not exist is far more dangerous than abstaining. DocScout enforces the strict invariant: "Every answer cites its source or it refuses to answer" (ADR-0068).

However, an abstention mechanism must be evaluated across dual performance dimensions:
1. **Refusal Precision:** When the system chooses to refuse, is the query genuinely unanswerable by the corpus? (Target >= 0.980 to ensure operators trust refusal alerts).
2. **Selective Accuracy:** On the subset of queries the system chooses to answer, is the retrieval accuracy exceptionally high? (Target >= 0.950, baseline 0.966).
3. **False Rejection Rate:** The system must not over-refuse valid answerable inquiries (Target <= 0.030).

FEAT-086 establishes an automated CI evaluation gate that computes Selective Accuracy, Refusal Precision, and False Rejection Rate over paired answerable (365) and unanswerable (60) gold sets, failing closed if any threshold is violated.

---

## Decision Drivers

1. **Strict Selective Prediction Contract:**
   Mathematically evaluate selective accuracy as Correct Answered / Total Answered and refusal precision as True Unanswerable Refused / Total Refused.
2. **CI Regression Gating:**
   Enforce `min_selective_accuracy = 0.95`, `min_refusal_precision = 0.98`, and `max_false_rejection_rate = 0.03` in `app/evals/gate.py`.
3. **Schema Invariants:**
   Define `AbstentionGateConfig` and `AbstentionGateResult` in `app/evals/abstention.py`.
4. **Execution Performance:**
   Evaluation executes in <= 100 ms with zero runtime memory overhead.
5. **Typographical Invariant:** Zero UTF-8 em-dashes (\xe2\x80\x94).

---

## Decision Outcome

We implement:
- `app/evals/abstention.py`: `AbstentionGateConfig`, `AbstentionGateResult`, `evaluate_abstention_gate`, `evaluate_query_subset_abstention`
- `app/evals/gate.py`: Hook `check_abstention_gate` into regression evaluation gate runner
- `app/evals/__init__.py`: Export `AbstentionGateConfig`, `AbstentionGateResult`, `evaluate_abstention_gate`
- `tests/test_abstention_gate.py`: Verification tests covering pass/fail thresholds, mathematical correctness, edge cases, and report integration

---

## Validation and Testing

1. Mathematical verification against known ground-truth distributions.
2. Threshold violation assertions verifying fail-closed CI behavior when selective accuracy < 0.95 or refusal precision < 0.98.
3. Integration with `app.evals.gate` ensuring `make eval-gate` passes with 0 regressions.
