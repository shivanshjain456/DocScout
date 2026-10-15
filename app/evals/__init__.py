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
from app.evals.scorers import faithfulness_score

__all__ = [
    "AbstentionGateConfig",
    "AbstentionGateResult",
    "AbstentionScore",
    "CalibrationConfig",
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
    "PerturbationRule",
    "PredictionPair",
    "compute_ece",
    "evaluate_abstention_gate",
    "evaluate_query_subset_abstention",
    "faithfulness_score",
    "get_default_calibration_config",
    "get_default_canary_manager",
    "get_default_citation_validator",
    "get_default_counterfactual_evaluator",
    "get_default_faithfulness_evaluator",
]
