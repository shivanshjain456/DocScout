"""Automated Stage Exit Criteria Validator (FEAT-053).

Evaluates stage exit criteria empirically against ingested telemetry,
test suites, and milestone deliverable evidence before permitting
playbook stage promotion.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from app.api.metrics import STAGE_PROMOTIONS_ATTEMPTED_TOTAL
from app.workflows.engine import (
    InvalidStateTransitionError,
    PlaybookEngine,
    get_default_playbook_engine,
)

logger = structlog.get_logger(__name__)


class ExitCriteriaPreconditionFailedError(InvalidStateTransitionError):
    """Raised when stage exit criteria are not met and promotion is blocked."""

    def __init__(self, message: str, blocking_issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.blocking_issues = blocking_issues or []


@dataclass(frozen=True)
class ExitValidatorConfig:
    """Configuration schema for automated stage exit validation."""

    enforce_strict_exit: bool = True
    min_override_length: int = 15


@dataclass
class CriterionCheck:
    """Evaluation result for an individual statutory exit criterion."""

    criterion: str
    status: Literal["PASSED", "FAILED"]
    evidence_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "status": self.status,
            "evidence_ref": self.evidence_ref,
        }


@dataclass
class ExitValidationResult:
    """Comprehensive stage exit verification report."""

    can_advance: bool
    exit_statement: str
    checks_evaluated: list[CriterionCheck]
    blocking_issues: list[str]
    override_applied: bool = False
    validation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "can_advance": self.can_advance,
            "exit_statement": self.exit_statement,
            "checks_evaluated": [c.to_dict() for c in self.checks_evaluated],
            "blocking_issues": self.blocking_issues,
            "override_applied": self.override_applied,
        }


class ExitCriteriaValidator:
    """Automated stage exit criteria evaluation and verification engine."""

    def __init__(
        self,
        config: ExitValidatorConfig | None = None,
        engine: PlaybookEngine | None = None,
    ) -> None:
        self.config = config or ExitValidatorConfig()
        self.engine = engine or get_default_playbook_engine()
        self._history: dict[str, list[ExitValidationResult]] = {}
        self._simulated_evidence: dict[tuple[str, int], dict[str, Any]] = {}

    def set_simulated_evidence(
        self,
        run_id: str,
        stage_number: int,
        evidence: dict[str, Any],
    ) -> None:
        """Inject simulated telemetry or test suite results for automated testing."""
        self._simulated_evidence[(run_id, stage_number)] = evidence

    def clear_simulated_evidence(self, run_id: str | None = None) -> None:
        """Clear simulated evidence overrides."""
        if run_id:
            keys_to_remove = [k for k in self._simulated_evidence if k[0] == run_id]
            for k in keys_to_remove:
                self._simulated_evidence.pop(k, None)
        else:
            self._simulated_evidence.clear()

    def validate_stage_exit(
        self,
        run_id: str,
        current_stage: int,
        tenant_id: str = "default",
        override_justification: str | None = None,
        conn: Any = None,
    ) -> ExitValidationResult:
        """Empirically evaluate exit criteria for the active stage of a playbook run.

        Blocks promotion if any exit criterion is unsatisfied, unless a valid
        administrative override justification is provided.
        """
        run = self.engine.get_run(run_id, tenant_id=tenant_id, conn=conn)
        if not run:
            raise ValueError(f"Playbook run '{run_id}' not found for tenant '{tenant_id}'.")

        if run.current_stage != current_stage:
            raise ValueError(
                f"Requested stage {current_stage} does not match active stage "
                f"{run.current_stage} of run '{run_id}'."
            )

        template = self.engine.get_template(run.playbook_id)
        if not template:
            raise ValueError(f"Playbook template '{run.playbook_id}' not found.")

        current_stage_def = next(
            (s for s in template.stages if s.stage_number == current_stage),
            None,
        )
        if not current_stage_def:
            raise ValueError(f"Stage {current_stage} not found in playbook '{run.playbook_id}'.")

        blocking_issues: list[str] = []
        checks_evaluated: list[CriterionCheck] = []

        # 1. Inspect completed milestones in this stage
        completed_milestones = [
            m
            for m in run.stage_data.get("completed_milestones", [])
            if m.get("stage_number") == current_stage
        ]
        completed_ids = {m.get("milestone_id") for m in completed_milestones}

        for milestone_def in current_stage_def.milestones:
            if milestone_def.id not in completed_ids:
                blocking_issues.append(
                    f"Milestone {milestone_def.id} ('{milestone_def.title}') is incomplete."
                )

        # 2. Inspect simulated telemetry or empirical test evidence
        sim_evidence = self._simulated_evidence.get((run_id, current_stage), {})

        # 3. Evaluate each stage exit criterion
        criteria_list = (
            current_stage_def.exit_criteria
            if current_stage_def.exit_criteria
            else ["All stage deliverables and evidence records verified."]
        )
        exit_statement = " ; ".join(criteria_list)

        for criterion in criteria_list:
            if sim_evidence.get("failing") or sim_evidence.get("missing"):
                fail_reason = sim_evidence.get(
                    "error",
                    "Simulated automated verification failure",
                )
                checks_evaluated.append(
                    CriterionCheck(
                        criterion=criterion,
                        status="FAILED",
                        evidence_ref=f"FAIL: {fail_reason}",
                    )
                )
                blocking_issues.append(f"Exit criterion unfulfilled: '{criterion}' ({fail_reason})")
            elif sim_evidence.get("evidence_ref"):
                ref = str(sim_evidence["evidence_ref"])
                checks_evaluated.append(
                    CriterionCheck(
                        criterion=criterion,
                        status="PASSED",
                        evidence_ref=ref,
                    )
                )
            else:
                # Default evaluation: require all stage milestones to be completed
                missing_for_stage = [
                    m.id for m in current_stage_def.milestones if m.id not in completed_ids
                ]
                if missing_for_stage:
                    checks_evaluated.append(
                        CriterionCheck(
                            criterion=criterion,
                            status="FAILED",
                            evidence_ref="MISSING_DELIVERABLES",
                        )
                    )
                    blocking_issues.append(
                        f"Exit criterion unfulfilled: '{criterion}' (pending deliverables: {', '.join(missing_for_stage)})"
                    )
                else:
                    # Collect attached evidence refs from completed milestones
                    evidence_refs = [
                        m.get("evidence_doc_id")
                        for m in completed_milestones
                        if m.get("evidence_doc_id")
                    ]
                    ref_summary = (
                        ", ".join(evidence_refs)
                        if evidence_refs
                        else f"VERIFIED: {len(completed_milestones)} milestones complete"
                    )
                    checks_evaluated.append(
                        CriterionCheck(
                            criterion=criterion,
                            status="PASSED",
                            evidence_ref=ref_summary,
                        )
                    )

        # 4. Handle administrative override if supplied
        override_applied = False
        can_advance = len(blocking_issues) == 0

        if override_justification is not None:
            clean_override = override_justification.strip()
            if len(clean_override) >= self.config.min_override_length:
                override_applied = True
                can_advance = True
            else:
                blocking_issues.append(
                    f"Administrative override justification must be at least "
                    f"{self.config.min_override_length} characters long (entered: {len(clean_override)})."
                )
                can_advance = False

        if not self.config.enforce_strict_exit and not can_advance:
            can_advance = True

        validation_id = str(uuid.uuid4())
        result = ExitValidationResult(
            validation_id=validation_id,
            can_advance=can_advance,
            exit_statement=exit_statement,
            checks_evaluated=checks_evaluated,
            blocking_issues=blocking_issues,
            override_applied=override_applied,
        )

        # 5. Telemetry & Metrics
        metric_status = "override" if override_applied else ("passed" if can_advance else "failed")
        try:
            STAGE_PROMOTIONS_ATTEMPTED_TOTAL.labels(status=metric_status).inc()
        except Exception as metric_err:
            logger.debug("exit_validator.metric_error", error=str(metric_err))

        logger.info(
            "playbook.stage_exit_validated",
            run_id=run_id,
            stage=current_stage,
            playbook_id=run.playbook_id,
            status=metric_status,
            can_advance=can_advance,
            blocking_issues_count=len(blocking_issues),
            override_applied=override_applied,
        )

        # 6. Database Persistence
        if conn is not None:
            try:
                conn.execute(
                    """
                    INSERT INTO stage_exit_validations (
                        validation_id, run_id, tenant_id, playbook_id, stage_number,
                        can_advance, exit_statement, checks_evaluated, blocking_issues,
                        override_applied, override_justification, validated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        validation_id,
                        run_id,
                        tenant_id,
                        run.playbook_id,
                        current_stage,
                        can_advance,
                        exit_statement,
                        json.dumps([c.to_dict() for c in checks_evaluated]),
                        json.dumps(blocking_issues),
                        override_applied,
                        override_justification,
                        datetime.now(UTC),
                    ),
                )
            except Exception as err:
                logger.debug("exit_validator.db_sync_error", error=str(err))

        self._history.setdefault(run_id, []).append(result)
        return result

    def get_validation_history(self, run_id: str) -> list[ExitValidationResult]:
        """Return in-memory validation history for a run."""
        return self._history.get(run_id, [])


_DEFAULT_EXIT_VALIDATOR: ExitCriteriaValidator | None = None


def get_default_exit_validator() -> ExitCriteriaValidator:
    """Singleton provider for ExitCriteriaValidator."""
    global _DEFAULT_EXIT_VALIDATOR
    if _DEFAULT_EXIT_VALIDATOR is None:
        _DEFAULT_EXIT_VALIDATOR = ExitCriteriaValidator()
    return _DEFAULT_EXIT_VALIDATOR
