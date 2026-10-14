"""4-Stage Progressive Milestone Tracker (FEAT-052).

Granular milestone checklist management, evidence artifact grounding,
and stage exit criteria calculation across the 4 discrete playbook stages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.api import metrics
from app.observability import get_logger
from app.workflows.engine import (
    InvalidStateTransitionError,
    PlaybookEngine,
    PlaybookRun,
    PlaybookRunNotFoundError,
    get_default_playbook_engine,
)

logger = get_logger("docscout.workflows.milestones")


@dataclass(frozen=True)
class MilestoneConfig:
    """Validation configuration for statutory milestone sign-off."""

    require_evidence_attachment: bool = True
    min_notes_length: int = 10


@dataclass
class MilestoneRecord:
    """Relational representation of a completed milestone deliverable."""

    milestone_record_id: str
    run_id: str
    tenant_id: str
    playbook_id: str
    stage_number: int
    milestone_id: str
    completed: bool
    evidence_doc_id: str | None
    notes: str
    completed_at: datetime
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone_record_id": self.milestone_record_id,
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "playbook_id": self.playbook_id,
            "stage_number": self.stage_number,
            "milestone_id": self.milestone_id,
            "completed": self.completed,
            "evidence_doc_id": self.evidence_doc_id,
            "notes": self.notes,
            "completed_at": self.completed_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class StageProgress:
    """Progress metrics and exit readiness for a specific playbook stage."""

    stage_number: int
    stage_name: str
    total_milestones: int
    completed_milestones: int
    completion_ratio: float
    exit_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_number": self.stage_number,
            "stage_name": self.stage_name,
            "total_milestones": self.total_milestones,
            "completed_milestones": self.completed_milestones,
            "completion_ratio": self.completion_ratio,
            "exit_ready": self.exit_ready,
        }


class MilestoneTracker:
    """Manages milestone records, evidence attachments, and stage progress evaluation."""

    def __init__(
        self,
        engine: PlaybookEngine | None = None,
        config: MilestoneConfig | None = None,
    ) -> None:
        self.engine = engine or get_default_playbook_engine()
        self.config = config or MilestoneConfig()
        # In-memory store: (run_id, tenant_id, milestone_id) -> MilestoneRecord
        self._records: dict[tuple[str, str, str], MilestoneRecord] = {}

    def record_milestone(
        self,
        run_id: str,
        milestone_id: str,
        tenant_id: str = "default",
        evidence_doc_id: str | None = None,
        notes: str = "",
        conn: Any = None,
    ) -> StageProgress:
        """Sign off a discrete milestone deliverable with grounding evidence."""
        run: PlaybookRun | None = self.engine.get_run(run_id, tenant_id, conn)
        if not run:
            raise PlaybookRunNotFoundError(f"Run '{run_id}' not found for tenant '{tenant_id}'.")

        if run.status != "ACTIVE":
            raise InvalidStateTransitionError(
                f"Cannot complete milestone on run with status '{run.status}'."
            )

        template = self.engine.get_template(run.playbook_id)
        if not template:
            raise PlaybookRunNotFoundError(f"Template for playbook '{run.playbook_id}' not found.")

        current_stage = next(
            (s for s in template.stages if s.stage_number == run.current_stage), None
        )
        if not current_stage:
            raise InvalidStateTransitionError(
                f"Stage {run.current_stage} not defined in template '{run.playbook_id}'."
            )

        # Validate milestone belongs to active stage of current run
        matching_milestone = next(
            (m for m in current_stage.milestones if m.id == milestone_id), None
        )
        if not matching_milestone:
            # Check if milestone belongs to another stage
            belongs_to_other = any(
                any(m.id == milestone_id for m in s.milestones)
                for s in template.stages
                if s.stage_number != run.current_stage
            )
            if belongs_to_other:
                raise InvalidStateTransitionError(
                    f"Cannot complete milestone '{milestone_id}' for inactive stage; active stage is {run.current_stage}."
                )
            raise InvalidStateTransitionError(
                f"Milestone '{milestone_id}' not found in playbook '{run.playbook_id}'."
            )

        # Validate minimum notes length (statutory requirement >= 10 chars)
        clean_notes = (notes or "").strip()
        if len(clean_notes) < self.config.min_notes_length:
            raise ValueError(
                f"Milestone verification notes must be at least {self.config.min_notes_length} characters."
            )

        # Validate evidence attachment if configured
        clean_evidence = (evidence_doc_id or "").strip() if evidence_doc_id else None
        if self.config.require_evidence_attachment and not clean_evidence:
            raise ValueError("Evidence document ID attachment required for statutory sign-off.")

        now = datetime.now(UTC)
        record_id = str(uuid.uuid4())
        record = MilestoneRecord(
            milestone_record_id=record_id,
            run_id=run.run_id,
            tenant_id=tenant_id,
            playbook_id=run.playbook_id,
            stage_number=run.current_stage,
            milestone_id=milestone_id,
            completed=True,
            evidence_doc_id=clean_evidence,
            notes=clean_notes,
            completed_at=now,
            created_at=now,
        )

        # Persist to database if connection available
        if conn is not None:
            try:
                conn.execute(
                    """
                    INSERT INTO playbook_milestones (
                        milestone_record_id, run_id, tenant_id, playbook_id,
                        stage_number, milestone_id, completed, evidence_doc_id, notes,
                        completed_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, stage_number, milestone_id) DO UPDATE
                    SET evidence_doc_id = EXCLUDED.evidence_doc_id,
                        notes = EXCLUDED.notes,
                        completed_at = EXCLUDED.completed_at
                    """,
                    (
                        record.milestone_record_id,
                        record.run_id,
                        record.tenant_id,
                        record.playbook_id,
                        record.stage_number,
                        record.milestone_id,
                        record.completed,
                        record.evidence_doc_id,
                        record.notes,
                        record.completed_at,
                        record.created_at,
                    ),
                )
            except Exception as err:
                logger.debug("milestone.db_sync_error", error=str(err))

        self._records[(run.run_id, tenant_id, milestone_id)] = record

        # Sync milestone state with core PlaybookEngine run
        self.engine.complete_milestone(
            run_id=run.run_id,
            milestone_id=milestone_id,
            tenant_id=tenant_id,
            stage_number=run.current_stage,
            evidence_doc_id=clean_evidence,
            notes=clean_notes,
            conn=conn,
        )

        metrics.MILESTONES_COMPLETED_TOTAL.labels(
            playbook_id=run.playbook_id,
            stage=str(run.current_stage),
        ).inc()

        return self.get_stage_progress(run.run_id, run.current_stage, tenant_id, conn)

    def get_stage_progress(
        self,
        run_id: str,
        stage_number: int,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> StageProgress:
        """Calculate deliverable progress and exit criteria readiness for a stage."""
        run = self.engine.get_run(run_id, tenant_id, conn)
        if not run:
            raise PlaybookRunNotFoundError(f"Run '{run_id}' not found for tenant '{tenant_id}'.")

        template = self.engine.get_template(run.playbook_id)
        if not template:
            raise PlaybookRunNotFoundError(f"Template for playbook '{run.playbook_id}' not found.")

        target_stage = next((s for s in template.stages if s.stage_number == stage_number), None)
        if not target_stage:
            raise InvalidStateTransitionError(
                f"Stage {stage_number} not defined in playbook '{run.playbook_id}'."
            )

        total_milestones = len(target_stage.milestones)
        completed_set: set[str] = set()

        if conn is not None:
            try:
                rows = conn.execute(
                    """
                    SELECT milestone_id FROM playbook_milestones
                    WHERE run_id = %s AND tenant_id = %s AND stage_number = %s AND completed = TRUE
                    """,
                    (run_id, tenant_id, stage_number),
                ).fetchall()
                completed_set = {str(r[0]) for r in rows}
            except Exception as err:
                logger.debug("milestone.db_read_error", error=str(err))

        if not completed_set:
            # Fallback to run stage_data and memory store
            for m in run.stage_data.get("completed_milestones", []):
                if m.get("stage_number") == stage_number:
                    completed_set.add(m.get("milestone_id"))
            for (r_id, t_id, m_id), rec in self._records.items():
                if r_id == run_id and t_id == tenant_id and rec.stage_number == stage_number:
                    completed_set.add(m_id)

        target_ids = {m.id for m in target_stage.milestones}
        completed_count = len(target_ids.intersection(completed_set))
        ratio = round(completed_count / total_milestones, 4) if total_milestones > 0 else 1.0
        exit_ready = completed_count >= total_milestones and total_milestones > 0

        return StageProgress(
            stage_number=stage_number,
            stage_name=target_stage.stage_name,
            total_milestones=total_milestones,
            completed_milestones=completed_count,
            completion_ratio=ratio,
            exit_ready=exit_ready,
        )

    def list_stage_progress(
        self,
        run_id: str,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> list[StageProgress]:
        """Return progress across all 4 sequential stages for a playbook run."""
        run = self.engine.get_run(run_id, tenant_id, conn)
        if not run:
            raise PlaybookRunNotFoundError(f"Run '{run_id}' not found for tenant '{tenant_id}'.")

        return [
            self.get_stage_progress(run_id, stage_num, tenant_id, conn)
            for stage_num in range(1, run.total_stages + 1)
        ]

    def reset_milestones(
        self,
        run_id: str,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> None:
        """Purge all milestone records for a run, preventing orphaned state."""
        if conn is not None:
            try:
                conn.execute(
                    "DELETE FROM playbook_milestones WHERE run_id = %s AND tenant_id = %s",
                    (run_id, tenant_id),
                )
            except Exception as err:
                logger.debug("milestone.db_delete_error", error=str(err))

        run = self.engine.get_run(run_id, tenant_id, conn)
        if run:
            run.stage_data["completed_milestones"] = []
            if conn is not None:
                try:
                    import json

                    conn.execute(
                        "UPDATE playbook_runs SET stage_data = %s WHERE run_id = %s AND tenant_id = %s",
                        (json.dumps(run.stage_data), run_id, tenant_id),
                    )
                except Exception as err:
                    logger.debug("milestone.db_reset_error", error=str(err))

        keys_to_remove = [k for k in self._records if k[0] == run_id and k[1] == tenant_id]
        for k in keys_to_remove:
            del self._records[k]


_DEFAULT_MILESTONE_TRACKER: MilestoneTracker | None = None


def get_default_milestone_tracker() -> MilestoneTracker:
    """Return the singleton instance of MilestoneTracker."""
    global _DEFAULT_MILESTONE_TRACKER
    if _DEFAULT_MILESTONE_TRACKER is None:
        _DEFAULT_MILESTONE_TRACKER = MilestoneTracker(
            config=MilestoneConfig(require_evidence_attachment=False)
        )
    return _DEFAULT_MILESTONE_TRACKER
