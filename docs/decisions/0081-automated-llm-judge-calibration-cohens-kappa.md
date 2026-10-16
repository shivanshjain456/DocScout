# ADR-0081: Automated LLM Judge Calibration with Cohen's Kappa

## Context
Automated evaluation judges (such as LLM-as-a-judge for faithfulness, grounding, relevance, and statutory interpretation) are vital for continuous delivery and gate enforcement across regulatory question answering. However, if an automated judge suffers from systematic bias, sycophancy, or drift, using uncalibrated judge outputs to enforce production gates leads to silent false positives or unwarranted blocking of valid releases.

To ensure automated gating is trustworthy and defensible to regulatory compliance auditors, all automated judges used in CI/CD regression gates must be statistically calibrated against human legal and regulatory expert annotations using Cohen's Kappa ($\kappa$).

## Decision
1. Implement a zero-external-dependency statistical calibration module in `app/evals/judge_calibration.py` leveraging enhanced agreement statistics in `app/evals/stats.py`.
2. Compute Cohen's Kappa ($\kappa = \frac{P_o - P_e}{1 - P_e}$), standard error $SE$, Z-score, and exact two-tailed $p$-value using complementary error function `math.erfc` from the Python standard library.
3. Support both binary classifications (e.g., faithful vs. unfaithful, supported vs. unsupported) and multiclass categorical assessments with full confusion matrix generation.
4. Enforce strict input validation rules: paired evaluations must have identical lengths with a minimum sample size of $N \ge 50$ items.
5. Define `JudgeCalibrationConfig` with `min_kappa = 0.85` (PASS threshold) and `regression_floor_kappa = 0.80` (FAIL threshold below which releases are hard-blocked).
6. Ship a curated gold benchmark dataset of 100 human-annotated regulatory answer evaluation pairs with human expert consensus ratings to benchmark automated judges in CI.
7. Integrate `check_judge_calibration_gate` into `app/evals/gate.py` and CLI subcommands in `app/evals/goldset.py`.

## Consequences
- **Positive:**
  - Automated judges cannot silently drift: inter-annotator agreement with human legal experts is verified before gate verdicts are accepted.
  - Sub-2ms execution time for 500 annotations with zero additional memory overhead or heavy third-party machine learning dependencies.
  - Fail-safe gating: uncalibrated or degrading judges ($\kappa < 0.85$) generate warnings or block CI releases ($\kappa < 0.80$).
- **Neutral:**
  - Requires maintaining curated human-expert gold calibration sets for each evaluated capability.
