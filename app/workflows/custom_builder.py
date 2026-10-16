"""Custom Enterprise Compliance Playbook Builder (FEAT-060).

Allows compliance leads to compose, validate against schema, persist, and execute
custom multi-stage internal compliance playbooks in the standard PlaybookEngine runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.api.metrics import CUSTOM_PLAYBOOKS_CREATED_TOTAL
from app.api.models import (
    CustomPlaybookDefinition,
    CustomPlaybookListResponse,
    PlaybookTemplateResponse,
)
from app.observability import get_logger
from app.workflows.engine import (
    MilestoneDefinition,
    PlaybookTemplate,
    StageDefinition,
    get_default_playbook_engine,
)

logger = get_logger("docscout.workflows.custom_builder")


class CustomPlaybookBuilderError(Exception):
    """Base exception for custom playbook builder operations."""


class CustomPlaybookValidationError(CustomPlaybookBuilderError):
    """Raised when custom playbook fails schema or structural validation."""

    def __init__(self, message: str, validation_errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.validation_errors = validation_errors or [message]


class CustomPlaybookQuotaExceededError(CustomPlaybookBuilderError):
    """Raised when tenant exceeds maximum custom playbook limit."""


@dataclass
class CustomBuilderConfig:
    max_custom_playbooks_per_tenant: int = 25
    max_template_bytes: int = 262144  # 256 KB
    min_stages: int = 2
    max_stages: int = 6


def validate_custom_playbook_schema(
    playbook: CustomPlaybookDefinition,
    config: CustomBuilderConfig | None = None,
) -> None:
    """Validate a custom playbook definition against structural and size constraints."""
    cfg = config or CustomBuilderConfig()
    errors: list[str] = []

    # 1. Payload size check
    dumped = json.dumps(playbook.model_dump())
    if len(dumped.encode("utf-8")) > cfg.max_template_bytes:
        errors.append(
            f"Playbook template JSON size ({len(dumped.encode('utf-8'))} bytes) exceeds {cfg.max_template_bytes} bytes ceiling."
        )

    # 2. Stage count boundaries
    stages_count = len(playbook.stages)
    if stages_count < cfg.min_stages:
        errors.append(
            f"Playbook has {stages_count} stages; minimum {cfg.min_stages} stages required."
        )
    elif stages_count > cfg.max_stages:
        errors.append(
            f"Playbook has {stages_count} stages; maximum {cfg.max_stages} stages allowed."
        )

    # 3. Stage sequence and contents
    all_milestone_ids: set[str] = set()
    for idx, stage in enumerate(playbook.stages, start=1):
        if stage.stage_number != idx:
            errors.append(
                f"Stage at index {idx} has invalid stage_number {stage.stage_number}; must be strictly sequential starting at 1."
            )
        if not stage.stage_name.strip():
            errors.append(f"Stage {stage.stage_number} has empty stage_name.")
        if not stage.exit_criteria:
            errors.append(f"Stage {stage.stage_number} must specify at least one exit criterion.")
        for crit in stage.exit_criteria:
            if not crit.strip():
                errors.append(f"Stage {stage.stage_number} contains empty exit criterion.")

        if not stage.milestones:
            errors.append(f"Stage {stage.stage_number} must specify at least one milestone.")
        for m in stage.milestones:
            if not m.id.strip():
                errors.append(f"Stage {stage.stage_number} contains milestone with empty ID.")
            elif m.id in all_milestone_ids:
                errors.append(
                    f"Duplicate milestone ID '{m.id}' detected in Stage {stage.stage_number}; IDs must be unique across playbook."
                )
            else:
                all_milestone_ids.add(m.id)

            if not m.title.strip():
                errors.append(f"Milestone '{m.id}' in Stage {stage.stage_number} has empty title.")

    if errors:
        raise CustomPlaybookValidationError(
            f"Custom playbook validation failed with {len(errors)} error(s): {'; '.join(errors)}",
            validation_errors=errors,
        )


def convert_custom_to_runtime_template(
    playbook: CustomPlaybookDefinition,
) -> PlaybookTemplate:
    """Convert a validated CustomPlaybookDefinition into a standard runtime PlaybookTemplate."""
    runtime_stages: list[StageDefinition] = []
    for s in playbook.stages:
        runtime_milestones = [
            MilestoneDefinition(
                id=m.id,
                title=m.title,
                role=m.role,
                mandatory=m.mandatory,
                estimated_hours=m.estimated_hours,
            )
            for m in s.milestones
        ]
        runtime_stages.append(
            StageDefinition(
                stage_number=s.stage_number,
                stage_name=s.stage_name,
                description=s.description or s.stage_name,
                milestones=runtime_milestones,
                exit_criteria=s.exit_criteria,
            )
        )

    return PlaybookTemplate(
        playbook_id=playbook.id,
        title=playbook.name,
        description=playbook.goal,
        domain=playbook.domain,
        total_stages=len(runtime_stages),
        stages=runtime_stages,
    )


class CustomPlaybookBuilder:
    """Orchestrates custom playbook validation, persistence, and runtime registration."""

    def __init__(self, config: CustomBuilderConfig | None = None) -> None:
        self.config = config or CustomBuilderConfig()
        self._custom_playbooks: dict[str, dict[str, CustomPlaybookDefinition]] = {}

    def save_playbook(
        self,
        playbook: CustomPlaybookDefinition,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> PlaybookTemplateResponse:
        """Validate, persist, and register custom playbook into the runtime engine."""
        # 1. Validate schema
        validate_custom_playbook_schema(playbook, self.config)

        # 2. Check quota
        current_count = self._get_tenant_playbook_count(tenant_id=tenant_id, conn=conn)
        existing = self.get_playbook(template_id=playbook.id, tenant_id=tenant_id, conn=conn)
        if existing is None and current_count >= self.config.max_custom_playbooks_per_tenant:
            raise CustomPlaybookQuotaExceededError(
                f"Tenant '{tenant_id}' has reached the limit of {self.config.max_custom_playbooks_per_tenant} custom playbooks."
            )

        now = datetime.now(UTC)

        # 3. Store in memory
        if tenant_id not in self._custom_playbooks:
            self._custom_playbooks[tenant_id] = {}
        self._custom_playbooks[tenant_id][playbook.id] = playbook

        # 4. Persist to database if connection available
        if conn is not None:
            self._persist_to_db(playbook, tenant_id=tenant_id, conn=conn)

        # 5. Convert and register with runtime PlaybookEngine
        runtime_template = convert_custom_to_runtime_template(playbook)
        engine = get_default_playbook_engine()
        engine.register_template(runtime_template)

        # 6. Increment Prometheus metric
        try:
            CUSTOM_PLAYBOOKS_CREATED_TOTAL.labels(tenant_id=tenant_id).inc()
        except Exception as err:
            logger.debug("custom_playbook.metric_error", error=str(err))

        return PlaybookTemplateResponse(
            template_id=playbook.id,
            is_valid=True,
            stages_count=len(playbook.stages),
            created_at=now,
        )

    def get_playbook(
        self,
        template_id: str,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> CustomPlaybookDefinition | None:
        """Retrieve custom playbook by ID for a tenant."""
        if conn is not None:
            db_res = self._fetch_from_db(template_id=template_id, tenant_id=tenant_id, conn=conn)
            if db_res:
                return db_res

        return self._custom_playbooks.get(tenant_id, {}).get(template_id)

    def list_playbooks(
        self,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> CustomPlaybookListResponse:
        """List all custom playbooks authored by tenant."""
        playbooks: list[CustomPlaybookDefinition] = []
        if conn is not None:
            playbooks = self._list_from_db(tenant_id=tenant_id, conn=conn)

        if not playbooks:
            playbooks = list(self._custom_playbooks.get(tenant_id, {}).values())

        return CustomPlaybookListResponse(
            tenant_id=tenant_id,
            total_count=len(playbooks),
            playbooks=playbooks,
        )

    def _get_tenant_playbook_count(self, tenant_id: str, conn: Any = None) -> int:
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM custom_playbook_templates WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()
                if row:
                    return int(row[0])
            except Exception as err:
                logger.debug("custom_playbook.count_db_error", error=str(err))
        return len(self._custom_playbooks.get(tenant_id, {}))

    def _persist_to_db(
        self,
        playbook: CustomPlaybookDefinition,
        tenant_id: str,
        conn: Any,
    ) -> None:
        sql = """
            INSERT INTO custom_playbook_templates (
                template_id, tenant_id, name, goal, domain, stages, metadata, updated_at
            ) VALUES (
                %(template_id)s, %(tenant_id)s, %(name)s, %(goal)s, %(domain)s,
                %(stages)s, %(metadata)s, NOW()
            )
            ON CONFLICT (template_id, tenant_id) DO UPDATE SET
                name = EXCLUDED.name,
                goal = EXCLUDED.goal,
                domain = EXCLUDED.domain,
                stages = EXCLUDED.stages,
                metadata = EXCLUDED.metadata,
                updated_at = NOW();
        """
        params = {
            "template_id": playbook.id,
            "tenant_id": tenant_id,
            "name": playbook.name,
            "goal": playbook.goal,
            "domain": playbook.domain,
            "stages": json.dumps([s.model_dump() for s in playbook.stages]),
            "metadata": json.dumps(playbook.metadata),
        }
        conn.execute(sql, params)

    def _fetch_from_db(
        self,
        template_id: str,
        tenant_id: str,
        conn: Any,
    ) -> CustomPlaybookDefinition | None:
        sql = """
            SELECT template_id, name, goal, domain, stages, metadata
            FROM custom_playbook_templates
            WHERE template_id = %s AND tenant_id = %s;
        """
        row = conn.execute(sql, (template_id, tenant_id)).fetchone()
        if not row:
            return None
        stages_data = row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]")
        meta_data = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")
        return CustomPlaybookDefinition(
            id=row[0],
            name=row[1],
            goal=row[2],
            domain=row[3],
            stages=stages_data,
            metadata=meta_data,
        )

    def _list_from_db(
        self,
        tenant_id: str,
        conn: Any,
    ) -> list[CustomPlaybookDefinition]:
        sql = """
            SELECT template_id, name, goal, domain, stages, metadata
            FROM custom_playbook_templates
            WHERE tenant_id = %s
            ORDER BY created_at DESC;
        """
        rows = conn.execute(sql, (tenant_id,)).fetchall()
        results: list[CustomPlaybookDefinition] = []
        for row in rows:
            stages_data = row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]")
            meta_data = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")
            results.append(
                CustomPlaybookDefinition(
                    id=row[0],
                    name=row[1],
                    goal=row[2],
                    domain=row[3],
                    stages=stages_data,
                    metadata=meta_data,
                )
            )
        return results


_default_builder: CustomPlaybookBuilder | None = None


def get_default_custom_playbook_builder() -> CustomPlaybookBuilder:
    """Retrieve or initialize singleton CustomPlaybookBuilder instance."""
    global _default_builder
    if _default_builder is None:
        _default_builder = CustomPlaybookBuilder()
    return _default_builder
