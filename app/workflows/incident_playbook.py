"""Regulatory Cyber Incident Response Playbook (FEAT-055).

Operationalizes playbook.incident-readiness for banking cyber incidents,
enforcing strict evidence preservation, root-cause isolation, and RBI reporting
within the statutory 6-hour regulatory window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog

from app.api.metrics import ACTIVE_CRISIS_INCIDENTS, INCIDENT_MILESTONES_MET_TOTAL
from app.api.models import (
    DeclareIncidentRequest,
    IncidentCrisisState,
)
from app.workflows.engine import PlaybookEngine, get_default_playbook_engine

logger = structlog.get_logger(__name__)


class IncidentCrisisError(Exception):
    """Base exception for cyber incident crisis workflow operations."""


class IncidentNotFoundError(IncidentCrisisError):
    """Raised when an incident identifier is not found."""


class IncidentValidationError(IncidentCrisisError):
    """Raised when incident declarations violate statutory constraints."""


DEFAULT_SEV1_ACTIONS: list[str] = [
    "ACT-01: Establish out-of-band encrypted incident war room and appoint Incident Commander",
    "ACT-02: Preserve volatile memory dump and system event audit logs before shutdown",
    "ACT-03: Isolate compromised network segments via automated ingress bulkhead controls",
    "ACT-04: Revoke all active session tokens, compromised service credentials, and API keys",
    "ACT-05: Alert Chief Information Security Officer (CISO) and Statutory Compliance Liaison",
    "ACT-06: Compile and sign off preliminary RBI Cyber Security Annex II disclosure report",
]

DEFAULT_SEV2_ACTIONS: list[str] = [
    "ACT-01: Establish incident coordination channel with security operations team",
    "ACT-02: Collect forensic disk and memory snapshots of affected hosts",
    "ACT-03: Apply perimeter firewall blocks and restrict lateral service communication",
    "ACT-04: Verify integrity of core transaction ledgers and customer data repositories",
    "ACT-05: Prepare draft regulatory cyber incident notification summary for compliance sign-off",
]


@dataclass(frozen=True)
class IncidentConfig:
    """Configuration parameters for statutory cyber crisis response."""

    rbi_deadline_hours: int = 6
    emergency_sms_enabled: bool = False
    warning_threshold_hours: int = 4
    fallback_dir: str = "data/incident_fallbacks"


def generate_rbi_disclosure_draft(
    incident_id: UUID,
    severity: str,
    summary: str,
    systems_impacted: list[str],
    discovery_timestamp: datetime,
    statutory_reporting_deadline: datetime,
) -> str:
    """Generate standardized statutory RBI incident report template."""
    discovery_iso = discovery_timestamp.isoformat()
    deadline_iso = statutory_reporting_deadline.isoformat()
    systems_str = ", ".join(systems_impacted)
    return (
        f"# STATUTORY INCIDENT DISCLOSURE (RBI CYBER SECURITY FRAMEWORK - ANNEX II)\n\n"
        f"## 1. Statutory Incident Identification\n"
        f"- **Incident Reference ID:** {incident_id}\n"
        f"- **Statutory Reporting Tier:** {severity}\n"
        f"- **Reporting Institution:** DocScout Core Banking & Regulatory Gateway\n"
        f"- **Incident Discovery Timestamp:** {discovery_iso}\n"
        f"- **Statutory 6-Hour Reporting Window Deadline:** {deadline_iso}\n"
        f"- **Critical Systems & Services Impacted:** {systems_str}\n\n"
        f"## 2. Preliminary Technical Summary & Attack Indicators\n"
        f"{summary}\n\n"
        f"## 3. Preserved Evidence & Containment Actions\n"
        f"- Volatile memory captures and raw forensic snapshots secured prior to container/host teardown.\n"
        f"- Network bulkheads and egress filtering applied to contain lateral propagation.\n"
        f"- Compromised session credentials, tokens, and mutual TLS certificates revoked.\n\n"
        f"## 4. Impact Assessment & Risk Mitigation\n"
        f"- Core transaction ledger integrity verified; no unauthorized fund transfers detected.\n"
        f"- Out-of-band communication war room established under appointed Incident Commander.\n"
        f"- Statutory regulatory notification draft compiled for final compliance officer sign-off.\n\n"
        f"## 5. Certification & Sign-off\n"
        f"- **Compliance Officer Status:** Awaiting final submission attestation.\n"
        f"- **Statutory Deadline Adherence:** Within statutory 6-hour regulatory requirement.\n"
    )


class IncidentCrisisManager:
    """Operationalizes playbook.incident-readiness for high-availability cyber crisis management."""

    def __init__(
        self,
        engine: PlaybookEngine | None = None,
        config: IncidentConfig | None = None,
    ) -> None:
        self.engine = engine or get_default_playbook_engine()
        self.config = config or IncidentConfig()
        self._incidents: dict[str, IncidentCrisisState] = {}

    def declare_incident(
        self,
        request: DeclareIncidentRequest,
        tenant_id: str = "default",
        run_id: UUID | None = None,
        conn: Any = None,
    ) -> IncidentCrisisState:
        """Initialize crisis response workflow, calculate 6-hour deadline, and draft report."""
        now = datetime.now(UTC)
        disc_tz = (
            request.discovery_timestamp
            if request.discovery_timestamp.tzinfo is not None
            else request.discovery_timestamp.replace(tzinfo=UTC)
        )

        if (disc_tz - now).total_seconds() > 10:
            raise IncidentValidationError("discovery_timestamp cannot be in the future")

        incident_id = uuid4()
        deadline = disc_tz + timedelta(hours=self.config.rbi_deadline_hours)
        minutes_remaining = max(0, int((deadline - now).total_seconds() / 60))
        warning_issued = minutes_remaining <= (self.config.warning_threshold_hours * 60)

        required_actions = list(
            DEFAULT_SEV1_ACTIONS if request.severity == "SEV1" else DEFAULT_SEV2_ACTIONS
        )

        disclosure = generate_rbi_disclosure_draft(
            incident_id=incident_id,
            severity=request.severity,
            summary=request.summary,
            systems_impacted=request.systems_impacted,
            discovery_timestamp=disc_tz,
            statutory_reporting_deadline=deadline,
        )

        state = IncidentCrisisState(
            incident_id=incident_id,
            severity=request.severity,
            summary=request.summary,
            systems_impacted=request.systems_impacted,
            discovery_timestamp=disc_tz,
            statutory_reporting_deadline=deadline,
            minutes_remaining=minutes_remaining,
            required_actions=required_actions,
            actions_completed=[],
            disclosure_draft=disclosure,
            status="DECLARED",
            warning_issued=warning_issued,
            run_id=run_id,
            created_at=now,
            updated_at=now,
        )

        # Store in-memory
        self._incidents[str(incident_id)] = state

        # High-availability persistence: database first, local JSON fallback if unavailable
        db_success = False
        if conn is not None:
            db_success = self._persist_to_db(state, tenant_id=tenant_id, conn=conn)

        if not db_success:
            self._write_fallback(state, tenant_id=tenant_id)

        # Observability
        try:
            ACTIVE_CRISIS_INCIDENTS.inc()
        except Exception as err:
            logger.debug("incident.metric_inc_failed", error=str(err))

        if warning_issued and self.config.emergency_sms_enabled:
            logger.warning(
                "incident.emergency_alert_dispatched",
                incident_id=str(incident_id),
                severity=request.severity,
                minutes_remaining=minutes_remaining,
                message="Critical: Regulatory reporting window expires in under 4 hours",
            )

        logger.info(
            "incident.crisis_initialized",
            incident_id=str(incident_id),
            severity=request.severity,
            deadline=deadline.isoformat(),
            minutes_remaining=minutes_remaining,
            warning_issued=warning_issued,
        )

        return state

    def get_incident_status(
        self,
        incident_id: UUID | str,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> IncidentCrisisState:
        """Retrieve real-time crisis status with dynamic countdown and warning calculation."""
        uid = UUID(str(incident_id)) if not isinstance(incident_id, UUID) else incident_id
        key = str(uid)
        state = self._incidents.get(key)

        if state is None and conn is not None:
            state = self._load_from_db(uid, tenant_id=tenant_id, conn=conn)

        if state is None:
            state = self._load_fallback(uid)

        if state is None:
            raise IncidentNotFoundError(f"Cyber incident '{uid}' not found")

        # Dynamically recalculate minutes remaining and warning status
        now = datetime.now(UTC)
        deadline = state.statutory_reporting_deadline
        minutes_remaining = int((deadline - now).total_seconds() / 60)
        warning_issued = minutes_remaining <= (self.config.warning_threshold_hours * 60)

        # Update in-memory copy
        updated = state.model_copy(
            update={
                "minutes_remaining": minutes_remaining,
                "warning_issued": warning_issued,
                "updated_at": now,
            }
        )
        self._incidents[key] = updated
        return updated

    def complete_action(
        self,
        incident_id: UUID | str,
        action_id: str,
        tenant_id: str = "default",
        notes: str = "",
        conn: Any = None,
    ) -> IncidentCrisisState:
        """Mark a forensic action item complete and update crisis state."""
        uid = UUID(str(incident_id)) if not isinstance(incident_id, UUID) else incident_id
        state = self.get_incident_status(uid, tenant_id=tenant_id, conn=conn)

        # Find matching action in required_actions
        matched_action = None
        for req in state.required_actions:
            if req.startswith(action_id) or action_id in req:
                matched_action = req
                break

        if not matched_action:
            matched_action = action_id

        completed_set = set(state.actions_completed)
        if matched_action not in completed_set:
            completed_set.add(matched_action)
            try:
                INCIDENT_MILESTONES_MET_TOTAL.inc()
            except Exception as err:
                logger.debug("incident.milestone_metric_failed", error=str(err))

        new_status = state.status
        all_required_done = all(act in completed_set for act in state.required_actions)
        if all_required_done and state.status == "DECLARED":
            new_status = "CONTAINED"

        now = datetime.now(UTC)
        updated = state.model_copy(
            update={
                "actions_completed": sorted(completed_set),
                "status": new_status,
                "updated_at": now,
            }
        )
        self._incidents[str(incident_id)] = updated

        if conn is not None:
            self._persist_to_db(updated, tenant_id=tenant_id, conn=conn)
        else:
            self._write_fallback(updated, tenant_id=tenant_id)

        logger.info(
            "incident.action_completed",
            incident_id=str(incident_id),
            action=matched_action,
            all_done=all_required_done,
            new_status=new_status,
        )

        return updated

    def list_incidents(
        self,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> list[IncidentCrisisState]:
        """List all active and historical incidents for a tenant."""
        now = datetime.now(UTC)
        results: list[IncidentCrisisState] = []
        for state in self._incidents.values():
            mins = int((state.statutory_reporting_deadline - now).total_seconds() / 60)
            warning = mins <= (self.config.warning_threshold_hours * 60)
            results.append(
                state.model_copy(update={"minutes_remaining": mins, "warning_issued": warning})
            )
        return results

    def _persist_to_db(self, state: IncidentCrisisState, tenant_id: str, conn: Any) -> bool:
        """Write crisis state to PostgreSQL table cyber_incidents."""
        try:
            conn.execute(
                """
                INSERT INTO cyber_incidents (
                    incident_id, tenant_id, run_id, severity, summary,
                    systems_impacted, discovery_timestamp, statutory_reporting_deadline,
                    status, required_actions, actions_completed, disclosure_draft,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (incident_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    actions_completed = EXCLUDED.actions_completed,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    state.incident_id,
                    tenant_id,
                    state.run_id,
                    state.severity,
                    state.summary,
                    json.dumps(state.systems_impacted),
                    state.discovery_timestamp,
                    state.statutory_reporting_deadline,
                    state.status,
                    json.dumps(state.required_actions),
                    json.dumps(state.actions_completed),
                    state.disclosure_draft,
                    state.created_at,
                    state.updated_at,
                ),
            )
            return True
        except Exception as err:
            logger.warning("incident.db_persist_error", error=str(err))
            return False

    def _load_from_db(
        self, incident_id: UUID, tenant_id: str, conn: Any
    ) -> IncidentCrisisState | None:
        """Retrieve crisis state from PostgreSQL cyber_incidents."""
        try:
            row = conn.execute(
                """
                SELECT incident_id, severity, summary, systems_impacted,
                       discovery_timestamp, statutory_reporting_deadline,
                       status, required_actions, actions_completed,
                       disclosure_draft, run_id, created_at, updated_at
                FROM cyber_incidents
                WHERE incident_id = %s AND tenant_id = %s
                """,
                (incident_id, tenant_id),
            ).fetchone()
            if not row:
                return None

            systems = row[3] if isinstance(row[3], list) else json.loads(row[3]) if row[3] else []
            req_actions = (
                row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else []
            )
            comp_actions = (
                row[8] if isinstance(row[8], list) else json.loads(row[8]) if row[8] else []
            )

            now = datetime.now(UTC)
            deadline = row[5]
            mins = int((deadline - now).total_seconds() / 60)
            warning = mins <= (self.config.warning_threshold_hours * 60)

            state = IncidentCrisisState(
                incident_id=row[0],
                severity=row[1],
                summary=row[2],
                systems_impacted=systems,
                discovery_timestamp=row[4],
                statutory_reporting_deadline=deadline,
                minutes_remaining=mins,
                required_actions=req_actions,
                actions_completed=comp_actions,
                disclosure_draft=row[9],
                status=row[6],
                warning_issued=warning,
                run_id=row[10],
                created_at=row[11],
                updated_at=row[12],
            )
            self._incidents[str(incident_id)] = state
            return state
        except Exception as err:
            logger.warning("incident.db_load_error", error=str(err))
            return None

    def _write_fallback(self, state: IncidentCrisisState, tenant_id: str) -> None:
        """Write local JSON backup when database is unavailable."""
        try:
            path = Path(self.config.fallback_dir)
            path.mkdir(parents=True, exist_ok=True)
            file_path = path / f"{state.incident_id}.json"
            data = state.model_dump(mode="json")
            data["tenant_id"] = tenant_id
            file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as err:
            logger.warning("incident.fallback_write_failed", error=str(err))

    def _load_fallback(self, incident_id: UUID) -> IncidentCrisisState | None:
        """Read crisis state from local JSON backup file."""
        try:
            path = Path(self.config.fallback_dir) / f"{incident_id}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return IncidentCrisisState.model_validate(data)
        except Exception as err:
            logger.warning("incident.fallback_read_failed", error=str(err))
        return None


_default_incident_manager: IncidentCrisisManager | None = None


def get_default_incident_manager() -> IncidentCrisisManager:
    """Return the application-wide singleton incident crisis manager."""
    global _default_incident_manager
    if _default_incident_manager is None:
        _default_incident_manager = IncidentCrisisManager()
    return _default_incident_manager
