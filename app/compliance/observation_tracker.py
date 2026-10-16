"""Continuous Compliance Observation Window Tracker (FEAT-048).

Ingests continuous security and operational telemetry, calculates rolling audit
observation windows (e.g. 90 days), and generates immutable evidence trails for
SOC-2 Type II and PCI-DSS 4.0 continuous evidence mandates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

import structlog

from app.api.metrics import (
    TELEMETRY_EVENTS_INGESTED_TOTAL,
    TELEMETRY_WINDOW_CALC_DURATION_SECONDS,
)
from app.api.models import TelemetryEventInput

if TYPE_CHECKING:
    import psycopg

logger = structlog.get_logger("docscout.compliance.observation_tracker")

HEX_SHA256_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ObservationConfig:
    """Configuration for continuous compliance observation window."""

    min_window_days: int = 90
    max_clock_skew_seconds: int = 300
    freshness_window_hours: int = 24


@dataclass(frozen=True)
class TelemetryEventRecord:
    """Internal record representing an ingested telemetry event."""

    event_id: UUID
    tenant_id: str
    control_id: str
    observation_timestamp: datetime
    check_result: Literal["PASS", "FAIL"]
    evidence_hash: str
    ingested_at: datetime


@dataclass(frozen=True)
class ObservationStatus:
    """Aggregated status across an active observation window."""

    control_id: str
    tenant_id: str
    observation_window_days: int
    compliance_percentage: float
    unbroken_streak_days: int
    total_observations: int
    pass_count: int
    fail_count: int
    window_start: datetime | None
    window_end: datetime | None
    status: Literal["COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT_DATA"]


class ObservationTracker:
    """Continuous Compliance Observation Window Tracker engine."""

    def __init__(self, config: ObservationConfig | None = None) -> None:
        self.config = config or ObservationConfig()
        # In-memory storage for high-throughput buffering and testing
        self._memory_events: dict[str, list[TelemetryEventRecord]] = {}

    def _normalize_timestamp(self, ts: datetime) -> datetime:
        """Ensure timestamp is timezone-aware in UTC."""
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    def validate_event(
        self,
        event: TelemetryEventInput,
        allow_historical: bool = False,
        now: datetime | None = None,
    ) -> datetime:
        """Validate an incoming telemetry event according to statutory rules.

        Returns normalized UTC observation_timestamp on success.
        Raises ValueError if validation fails.
        """
        control_id = event.control_id.strip()
        if not control_id:
            raise ValueError("control_id cannot be empty")

        if not HEX_SHA256_REGEX.match(event.evidence_hash):
            raise ValueError(f"Invalid SHA-256 evidence hash: '{event.evidence_hash}'")

        if event.check_result not in ("PASS", "FAIL"):
            raise ValueError(f"Invalid check result: '{event.check_result}', must be PASS or FAIL")

        obs_ts = self._normalize_timestamp(event.observation_timestamp)
        current_time = self._normalize_timestamp(now or datetime.now(UTC))

        # Check future timestamp (allow clock skew tolerance)
        skew_threshold = current_time + timedelta(seconds=self.config.max_clock_skew_seconds)
        if obs_ts > skew_threshold:
            raise ValueError(
                f"observation_timestamp cannot be in the future (got {obs_ts.isoformat()}, now is {current_time.isoformat()})"
            )

        # Check freshness unless historical backfill is explicitly allowed
        if not allow_historical:
            oldest_allowed = current_time - timedelta(hours=self.config.freshness_window_hours)
            if obs_ts < oldest_allowed:
                raise ValueError(
                    f"observation_timestamp must be within last {self.config.freshness_window_hours} hours to prevent back-dating (got {obs_ts.isoformat()})"
                )

        return obs_ts

    def ingest_batch(
        self,
        events: list[TelemetryEventInput],
        allow_historical: bool = False,
        now: datetime | None = None,
        conn: psycopg.Connection | None = None,
    ) -> list[str]:
        """Ingest a batch of continuous compliance telemetry events."""
        records: list[TelemetryEventRecord] = []
        ingested_at = self._normalize_timestamp(now or datetime.now(UTC))

        for event in events:
            validated_ts = self.validate_event(event, allow_historical=allow_historical, now=now)
            rec = TelemetryEventRecord(
                event_id=uuid4(),
                tenant_id=event.tenant_id.strip() or "default",
                control_id=event.control_id.strip(),
                observation_timestamp=validated_ts,
                check_result=event.check_result,
                evidence_hash=event.evidence_hash.lower(),
                ingested_at=ingested_at,
            )
            records.append(rec)

        # Record metrics
        for rec in records:
            TELEMETRY_EVENTS_INGESTED_TOTAL.labels(check_result=rec.check_result).inc()

        # Persist to in-memory store
        for rec in records:
            key = f"{rec.tenant_id}:{rec.control_id}"
            if key not in self._memory_events:
                self._memory_events[key] = []
            self._memory_events[key].append(rec)

        # Persist to Postgres if connection is available
        if conn is not None:
            self.persist_events(conn, records)

        logger.info(
            "telemetry_batch_ingested",
            count=len(records),
            controls=list({r.control_id for r in records}),
        )

        return [str(r.event_id) for r in records]

    def persist_events(
        self,
        conn: psycopg.Connection,
        records: list[TelemetryEventRecord],
    ) -> None:
        """Persist telemetry event records into PostgreSQL table."""
        if not records:
            return

        insert_sql = """
            INSERT INTO compliance_telemetry_events (
                event_id, tenant_id, control_id, observation_timestamp,
                check_result, evidence_hash, ingested_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
        """
        params = [
            (
                r.event_id,
                r.tenant_id,
                r.control_id,
                r.observation_timestamp,
                r.check_result,
                r.evidence_hash,
                r.ingested_at,
            )
            for r in records
        ]
        with conn.cursor() as cur:
            cur.executemany(insert_sql, params)
        conn.commit()

    def get_observation_status(
        self,
        control_id: str,
        tenant_id: str = "default",
        window_days: int | None = None,
        now: datetime | None = None,
        conn: psycopg.Connection | None = None,
    ) -> ObservationStatus:
        """Calculate continuous compliance metrics across the observation window."""
        effective_window_days = (
            window_days if window_days is not None else self.config.min_window_days
        )
        current_time = self._normalize_timestamp(now or datetime.now(UTC))
        window_start = current_time - timedelta(days=effective_window_days)

        with TELEMETRY_WINDOW_CALC_DURATION_SECONDS.time():
            if conn is not None:
                return self._calculate_status_from_db(
                    conn=conn,
                    control_id=control_id,
                    tenant_id=tenant_id,
                    window_days=effective_window_days,
                    window_start=window_start,
                    window_end=current_time,
                )
            return self._calculate_status_from_memory(
                control_id=control_id,
                tenant_id=tenant_id,
                window_days=effective_window_days,
                window_start=window_start,
                window_end=current_time,
            )

    def _calculate_streak(self, events: list[TelemetryEventRecord]) -> int:
        """Calculate unbroken streak days of 100% PASS ending at the latest observation."""
        if not events:
            return 0

        # Sort descending by observation_timestamp
        sorted_events = sorted(events, key=lambda e: e.observation_timestamp, reverse=True)

        # Group by calendar date (UTC)
        daily_results: dict[date, list[str]] = {}
        for ev in sorted_events:
            d = ev.observation_timestamp.date()
            if d not in daily_results:
                daily_results[d] = []
            daily_results[d].append(ev.check_result)

        sorted_dates = sorted(daily_results.keys(), reverse=True)
        if not sorted_dates:
            return 0

        # If the most recent active date had any FAIL, unbroken streak is 0
        if "FAIL" in daily_results[sorted_dates[0]]:
            return 0

        streak_count = 0
        expected_date = sorted_dates[0]

        for d in sorted_dates:
            # Check consecutive calendar day continuity
            if d != expected_date:
                break

            results = daily_results[d]
            if "FAIL" in results:
                break

            streak_count += 1
            expected_date = expected_date - timedelta(days=1)

        return streak_count

    def _calculate_status_from_memory(
        self,
        control_id: str,
        tenant_id: str,
        window_days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> ObservationStatus:
        """Calculate observation status from in-memory event buffer."""
        key = f"{tenant_id}:{control_id}"
        all_events = self._memory_events.get(key, [])

        # Filter within window
        window_events = [
            e for e in all_events if window_start <= e.observation_timestamp <= window_end
        ]

        if not window_events:
            return ObservationStatus(
                control_id=control_id,
                tenant_id=tenant_id,
                observation_window_days=window_days,
                compliance_percentage=0.0,
                unbroken_streak_days=0,
                total_observations=0,
                pass_count=0,
                fail_count=0,
                window_start=window_start,
                window_end=window_end,
                status="INSUFFICIENT_DATA",
            )

        pass_count = sum(1 for e in window_events if e.check_result == "PASS")
        fail_count = sum(1 for e in window_events if e.check_result == "FAIL")
        total = len(window_events)
        compliance_pct = round((pass_count / total) * 100.0, 2) if total > 0 else 0.0

        streak_days = self._calculate_streak(window_events)
        status_label: Literal["COMPLIANT", "NON_COMPLIANT"] = (
            "COMPLIANT" if compliance_pct >= 99.0 else "NON_COMPLIANT"
        )

        return ObservationStatus(
            control_id=control_id,
            tenant_id=tenant_id,
            observation_window_days=window_days,
            compliance_percentage=compliance_pct,
            unbroken_streak_days=streak_days,
            total_observations=total,
            pass_count=pass_count,
            fail_count=fail_count,
            window_start=window_start,
            window_end=window_end,
            status=status_label,
        )

    def _calculate_status_from_db(
        self,
        conn: psycopg.Connection,
        control_id: str,
        tenant_id: str,
        window_days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> ObservationStatus:
        """Calculate observation status by querying PostgreSQL with window aggregation."""
        query = """
            SELECT event_id, tenant_id, control_id, observation_timestamp,
                   check_result, evidence_hash, ingested_at
            FROM compliance_telemetry_events
            WHERE tenant_id = %s
              AND control_id = %s
              AND observation_timestamp >= %s
              AND observation_timestamp <= %s
            ORDER BY observation_timestamp DESC
        """
        with conn.cursor() as cur:
            cur.execute(query, (tenant_id, control_id, window_start, window_end))
            rows = cur.fetchall()

        if not rows:
            return ObservationStatus(
                control_id=control_id,
                tenant_id=tenant_id,
                observation_window_days=window_days,
                compliance_percentage=0.0,
                unbroken_streak_days=0,
                total_observations=0,
                pass_count=0,
                fail_count=0,
                window_start=window_start,
                window_end=window_end,
                status="INSUFFICIENT_DATA",
            )

        events: list[TelemetryEventRecord] = [
            TelemetryEventRecord(
                event_id=row[0],
                tenant_id=row[1],
                control_id=row[2],
                observation_timestamp=self._normalize_timestamp(row[3]),
                check_result=row[4],
                evidence_hash=row[5],
                ingested_at=self._normalize_timestamp(row[6]),
            )
            for row in rows
        ]

        total = len(events)
        pass_count = sum(1 for e in events if e.check_result == "PASS")
        fail_count = sum(1 for e in events if e.check_result == "FAIL")
        compliance_pct = round((pass_count / total) * 100.0, 2) if total > 0 else 0.0

        streak_days = self._calculate_streak(events)
        status_label: Literal["COMPLIANT", "NON_COMPLIANT"] = (
            "COMPLIANT" if compliance_pct >= 99.0 else "NON_COMPLIANT"
        )

        return ObservationStatus(
            control_id=control_id,
            tenant_id=tenant_id,
            observation_window_days=window_days,
            compliance_percentage=compliance_pct,
            unbroken_streak_days=streak_days,
            total_observations=total,
            pass_count=pass_count,
            fail_count=fail_count,
            window_start=window_start,
            window_end=window_end,
            status=status_label,
        )


_DEFAULT_TRACKER: ObservationTracker | None = None


def get_default_observation_tracker() -> ObservationTracker:
    """Return singleton instance of ObservationTracker."""
    global _DEFAULT_TRACKER
    if _DEFAULT_TRACKER is None:
        _DEFAULT_TRACKER = ObservationTracker()
    return _DEFAULT_TRACKER
