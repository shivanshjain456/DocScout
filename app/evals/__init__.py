"""Evaluation harness: the gold set, the deterministic scorers, and the reports.

`EVAL_PROTOCOL.md` is the contract this package implements. The package exists separately
from `app/ingest` because the eval harness must be able to judge the pipeline without
importing its conclusions -- it reuses the chunker (so citations resolve to real chunks) and
nothing else.
"""

from app.evals.abstention import (
    AbstentionGateConfig,
    AbstentionGateResult,
    AbstentionScore,
    evaluate_abstention_gate,
    evaluate_query_subset_abstention,
)
from app.evals.calibration import (
    CalibrationConfig,
    ECEReport,
    ECERunner,
    EmpiricalCalibrator,
    PredictionPair,
    compute_ece,
    get_default_calibration_config,
)
from app.evals.canary import (
    CanaryAuditReport,
    CanaryConfig,
    CanaryManager,
    CanaryToken,
    get_default_canary_manager,
)
from app.evals.citation_validator import (
    CitationValidationResult,
    CitationValidator,
    CitationValidatorConfig,
    get_default_citation_validator,
)
from app.evals.counterfactual import (
    CounterfactualConfig,
    CounterfactualEvaluator,
    CounterfactualGenerator,
    CounterfactualItem,
    CounterfactualItemResult,
    CounterfactualTestResult,
    PerturbationRule,
    get_default_counterfactual_evaluator,
)
from app.evals.faithfulness import (
    ClaimDecomposer,
    ClaimEntailmentEvaluator,
    ClaimEvaluation,
    FaithfulnessConfig,
    FaithfulnessEvaluation,
    FaithfulnessEvaluator,
    get_default_faithfulness_evaluator,
)
from app.evals.judge_calibration import (
    GOLD_JUDGE_HUMAN_BENCHMARK_100,
    CalibrationReport,
    JudgeCalibrationConfig,
    calibrate_judge,
    check_judge_calibration_gate,
    evaluate_judge_calibration_suite,
)
from app.evals.leakage import (
    LeakageConfig,
    LeakageStratificationReport,
    MetricSlice,
    build_stratification_report,
    compute_quote_lexical_overlap,
    stratify_goldset_items,
)
from app.evals.scorers import faithfulness_score

__all__ = [
    "AbstentionGateConfig",
    "AbstentionGateResult",
    "AbstentionScore",
    "CalibrationConfig",
    "CalibrationReport",
    "CanaryAuditReport",
    "CanaryConfig",
    "CanaryManager",
    "CanaryToken",
    "CitationValidationResult",
    "CitationValidator",
    "CitationValidatorConfig",
    "ClaimDecomposer",
    "ClaimEntailmentEvaluator",
    "ClaimEvaluation",
    "CounterfactualConfig",
    "CounterfactualEvaluator",
    "CounterfactualGenerator",
    "CounterfactualItem",
    "CounterfactualItemResult",
    "CounterfactualTestResult",
    "ECEReport",
    "ECERunner",
    "EmpiricalCalibrator",
    "FaithfulnessConfig",
    "FaithfulnessEvaluation",
    "FaithfulnessEvaluator",
    "GOLD_JUDGE_HUMAN_BENCHMARK_100",
    "JudgeCalibrationConfig",
    "LeakageConfig",
    "LeakageStratificationReport",
    "MetricSlice",
    "PerturbationRule",
    "PredictionPair",
    "build_stratification_report",
    "calibrate_judge",
    "check_judge_calibration_gate",
    "compute_ece",
    "compute_quote_lexical_overlap",
    "evaluate_abstention_gate",
    "evaluate_judge_calibration_suite",
    "evaluate_query_subset_abstention",
    "faithfulness_score",
    "get_default_calibration_config",
    "get_default_canary_manager",
    "get_default_citation_validator",
    "get_default_counterfactual_evaluator",
    "get_default_faithfulness_evaluator",
    "stratify_goldset_items",
]
