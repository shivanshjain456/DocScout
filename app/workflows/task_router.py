"""Role-Based Compliance Task Routing (FEAT-054).

Dispatches and partitions playbook tasks across statutory taxonomy roles
(developer, qa-engineer, sre, engineering-manager, compliance-officer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from app.api.metrics import TASKS_DISPATCHED_TOTAL
from app.workflows.engine import PlaybookEngine, get_default_playbook_engine

logger = structlog.get_logger(__name__)

VALID_TAXONOMY_ROLES: set[str] = {
    "developer",
    "qa-engineer",
    "sre",
    "engineering-manager",
    "compliance-officer",
}

ROLE_NORMALIZATION_MAP: dict[str, str] = {
    "architect": "developer",
    "frontend-engineer": "developer",
    "backend-engineer": "developer",
    "data-engineer": "developer",
    "embedded-engineer": "developer",
    "mobile-engineer": "developer",
    "ml-engineer": "developer",
    "qa-lead": "qa-engineer",
    "verification-engineer": "qa-engineer",
    "platform-engineer": "sre",
    "security-engineer": "sre",
    "ai-security-engineer": "sre",
    "performance-engineer": "sre",
    "dba": "sre",
    "pentester": "sre",
    "product-manager": "engineering-manager",
    "sustainability-lead": "engineering-manager",
    "auditor": "compliance-officer",
    "safety-engineer": "compliance-officer",
    "accessibility-specialist": "compliance-officer",
}


def normalize_role(role: str) -> str:
    """Normalize specialized or adjacent roles to canonical taxonomy roles."""
    cleaned = role.strip().lower()
    return ROLE_NORMALIZATION_MAP.get(cleaned, cleaned)


@dataclass(frozen=True)
class TaskRouterConfig:
    """Configuration schema for task routing and dispatch."""

    notify_on_assignment: bool = True
    default_estimated_hours: int = 8


@dataclass
class RoleTask:
    """Individual deliverable task dispatched to a specific taxonomy role."""

    task_id: str
    title: str
    stage: int
    term_reference: str = ""
    estimated_hours: int = 8
    role: str = "developer"
    completed: bool = False
    mandatory: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "stage": self.stage,
            "term_reference": self.term_reference,
            "estimated_hours": self.estimated_hours,
            "role": self.role,
            "completed": self.completed,
            "mandatory": self.mandatory,
        }


@dataclass
class RoleTaskList:
    """Role-partitioned actionable deliverable checklist."""

    role: str
    pending_tasks: list[RoleTask] = field(default_factory=list)
    completed_tasks: list[RoleTask] = field(default_factory=list)
    total_estimated_hours: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "pending_tasks": [t.to_dict() for t in self.pending_tasks],
            "completed_tasks": [t.to_dict() for t in self.completed_tasks],
            "total_estimated_hours": self.total_estimated_hours,
        }


class TaskRouter:
    """Dispatches playbook tasks by taxonomy role with sub-2.0ms execution latency."""

    def __init__(
        self,
        config: TaskRouterConfig | None = None,
        engine: PlaybookEngine | None = None,
    ) -> None:
        self.config = config or TaskRouterConfig()
        self.engine = engine or get_default_playbook_engine()

    def get_tasks_for_role(
        self,
        run_id: str,
        role: str | None = None,
        stage_number: int | None = None,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> RoleTaskList:
        """Filter and dispatch tasks by assigned taxonomy role."""
        run = self.engine.get_run(run_id, tenant_id=tenant_id, conn=conn)
        if not run:
            raise ValueError(f"Playbook run '{run_id}' not found for tenant '{tenant_id}'.")

        target_role: str | None = None
        if role is not None and role.strip().lower() != "all":
            normalized = normalize_role(role)
            if normalized not in VALID_TAXONOMY_ROLES:
                raise ValueError(
                    f"Invalid role '{role}'. Supported taxonomy roles: "
                    f"{sorted(VALID_TAXONOMY_ROLES)}"
                )
            target_role = normalized

        template = self.engine.get_template(run.playbook_id)
        if not template:
            raise ValueError(f"Playbook template '{run.playbook_id}' not found.")

        completed_milestones = run.stage_data.get("completed_milestones", [])
        completed_ids = {
            m.get("milestone_id") for m in completed_milestones if m.get("milestone_id")
        }

        stages = (
            [s for s in template.stages if s.stage_number == stage_number]
            if stage_number is not None
            else template.stages
        )

        pending_tasks: list[RoleTask] = []
        completed_tasks: list[RoleTask] = []

        for stage_def in stages:
            for milestone_def in stage_def.milestones:
                assigned_role = normalize_role(milestone_def.role)
                if target_role is None or assigned_role == target_role:
                    is_done = milestone_def.id in completed_ids
                    task = RoleTask(
                        task_id=milestone_def.id,
                        title=milestone_def.title,
                        stage=stage_def.stage_number,
                        term_reference=getattr(
                            milestone_def, "term_reference", f"TAX-{milestone_def.id}"
                        ),
                        estimated_hours=getattr(
                            milestone_def,
                            "estimated_hours",
                            self.config.default_estimated_hours,
                        ),
                        role=assigned_role,
                        completed=is_done,
                        mandatory=getattr(milestone_def, "mandatory", True),
                    )
                    if is_done:
                        completed_tasks.append(task)
                    else:
                        pending_tasks.append(task)

        total_hours = sum(t.estimated_hours for t in pending_tasks)
        display_role = target_role if target_role else "all"

        # Observability
        try:
            if target_role:
                TASKS_DISPATCHED_TOTAL.labels(role=target_role).inc(len(pending_tasks))
            else:
                for r in VALID_TAXONOMY_ROLES:
                    count = sum(1 for t in pending_tasks if t.role == r)
                    if count > 0:
                        TASKS_DISPATCHED_TOTAL.labels(role=r).inc(count)
        except Exception as err:
            logger.debug("task_router.metric_error", error=str(err))

        logger.info(
            "playbook.tasks_routed",
            run_id=run_id,
            role=display_role,
            pending_count=len(pending_tasks),
            completed_count=len(completed_tasks),
            total_hours=total_hours,
        )

        return RoleTaskList(
            role=display_role,
            pending_tasks=pending_tasks,
            completed_tasks=completed_tasks,
            total_estimated_hours=total_hours,
        )

    def sync_tasks_to_db(
        self,
        run_id: str,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> int:
        """Persist all playbook tasks to the relational playbook_tasks table."""
        if conn is None:
            return 0

        run = self.engine.get_run(run_id, tenant_id=tenant_id, conn=conn)
        if not run:
            return 0

        template = self.engine.get_template(run.playbook_id)
        if not template:
            return 0

        completed_ids = {
            m.get("milestone_id")
            for m in run.stage_data.get("completed_milestones", [])
            if m.get("milestone_id")
        }

        inserted = 0
        now = datetime.now(UTC)

        try:
            for stage_def in template.stages:
                for milestone_def in stage_def.milestones:
                    assigned_role = normalize_role(milestone_def.role)
                    is_done = milestone_def.id in completed_ids
                    conn.execute(
                        """
                        INSERT INTO playbook_tasks (
                            task_id, run_id, tenant_id, playbook_id, stage_number,
                            role, title, term_reference, estimated_hours, completed,
                            completed_at, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (run_id, stage_number, task_id) DO UPDATE
                        SET completed = EXCLUDED.completed,
                            completed_at = EXCLUDED.completed_at
                        """,
                        (
                            milestone_def.id,
                            run.run_id,
                            tenant_id,
                            run.playbook_id,
                            stage_def.stage_number,
                            assigned_role,
                            milestone_def.title,
                            f"TAX-{milestone_def.id}",
                            self.config.default_estimated_hours,
                            is_done,
                            now if is_done else None,
                            now,
                        ),
                    )
                    inserted += 1
        except Exception as err:
            logger.debug("task_router.db_sync_error", error=str(err))

        return inserted


_DEFAULT_TASK_ROUTER: TaskRouter | None = None


def get_default_task_router() -> TaskRouter:
    """Return the singleton instance of TaskRouter."""
    global _DEFAULT_TASK_ROUTER
    if _DEFAULT_TASK_ROUTER is None:
        _DEFAULT_TASK_ROUTER = TaskRouter()
    return _DEFAULT_TASK_ROUTER
