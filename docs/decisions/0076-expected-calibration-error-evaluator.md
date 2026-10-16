# ADR-0076: Expected Calibration Error (ECE) Evaluator (FEAT-085)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Assurance Guild, Search & Retrieval Engineering, Risk & Compliance Team
* **Informed:** Core Platform Engineers, Operations

---

## Context and Problem Statement

In regulatory compliance and statutory search, stated confidence scores guide high-stakes compliance decisions. If DocScout reports a confidence score of 0.90 (90%), compliance officers and automated gates expect that 90% of such responses are factually accurate and complete.

However, uncalibrated confidence heuristics (such as raw lexical evidence coverage) typically suffer from calibration drift (baseline ECE approximately 0.14), where stated confidence diverges from observed empirical accuracy across probability strata.

FEAT-085 provides an Expected Calibration Error (ECE) and Maximum Calibration Error (MCE) evaluation suite:
1. Partitions predictions into discrete probability bins (default 10 bins over [0.0, 1.0]).
2. Calculates bin-level accuracy vs confidence gap and the overall sample-weighted ECE:
   ECE = sum_{b=1}^B (n_b / N) * |acc(b) - conf(b)|
3. Computes Maximum Calibration Error (MCE) = max_b |acc(b) - conf(b)|.
4. Enforces strict calibration gating (max allowed ECE <= 0.06, target <= 0.05).
5. Provides empirical isotonic/temperature calibration to transform raw heuristics into calibrated probabilities.
6. Emits Prometheus telemetry via `docscout_eval_ece_score` and embeds calibration reports in evaluation artifacts.

---

## Decision Drivers

1. **Mathematical Calibration Guarantee:**
   Ensure DocScout's stated confidence matches empirical retrieval accuracy (target ECE <= 0.05, ceiling <= 0.06).
2. **Standard Discrete Bin Partitioning:**
   Uniform 10-bin partitioning over the [0.0, 1.0] confidence interval according to standard statistical calibration literature.
3. **Structured Report & CI Gating:**
   `ECEReport` schema with `ece_score`, `bin_accuracies`, `bin_confidences`, `max_calibration_error`, `is_calibrated`, `bin_counts`, and `improvement_pct`.
4. **Input Validation & Safety:**
   Strict input validation requiring minimum 100 samples in standard mode and bounded [0.0, 1.0] confidences.
5. **Observability & Telemetry:**
   Export Prometheus gauge `docscout_eval_ece_score`.
6. **Performance Limits:**
   ECE calculation over 1,000 predictions executes in <= 5.0 ms with zero memory overhead.
7. **Typographical Invariant:** Strict ASCII typographical compliance across all documentation and code.

---

## Decision Outcome

We implement:
- `app/evals/calibration.py`: `CalibrationConfig`, `PredictionPair`, `ECEReport`, `compute_ece`, `EmpiricalCalibrator`, `ECERunner`
- `app/api/metrics.py`: `EVAL_ECE_SCORE` gauge
- `app/evals/__init__.py`: Export calibration types
- `tests/test_calibration.py`: Comprehensive test suite verifying binning, mathematical correctness, calibration transformations, input bounds, metrics, and CI gates

---

## Validation and Testing

1. Verified mathematical correctness against known ground truth distributions (perfect calibration ECE = 0.0, complete miscalibration ECE = 1.0).
2. Validated 10-bin discretization and MCE calculation.
3. Verified empirical calibration reduces uncalibrated baseline (ECE ~ 0.14) to ECE <= 0.05.
4. Verified execution latency over 1,000 samples is well below 5.0 ms (measured < 1.0 ms).
5. Checked Prometheus gauge updates.
