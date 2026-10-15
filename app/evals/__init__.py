"""Evaluation harness: the gold set, the deterministic scorers, and the reports.

`EVAL_PROTOCOL.md` is the contract this package implements. The package exists separately
from `app/ingest` because the eval harness must be able to judge the pipeline without
importing its conclusions -- it reuses the chunker (so citations resolve to real chunks) and
nothing else.
"""

from app.evals.citation_validator import (
    CitationValidationResult,
    CitationValidator,
    CitationValidatorConfig,
    get_default_citation_validator,
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
    "CitationValidationResult",
    "CitationValidator",
    "CitationValidatorConfig",
    "ClaimDecomposer",
    "ClaimEntailmentEvaluator",
    "ClaimEvaluation",
    "FaithfulnessConfig",
    "FaithfulnessEvaluation",
    "FaithfulnessEvaluator",
    "faithfulness_score",
    "get_default_citation_validator",
    "get_default_faithfulness_evaluator",
]
