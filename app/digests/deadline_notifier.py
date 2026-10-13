"""Deadline and cutover notification dispatcher - FEAT-035.

Computes remaining countdown days against statutory deadlines, generates
compliance officer alert payloads, and dispatches Brevo transactional alerts.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.api.metrics import DEADLINE_ALERTS_SENT_TOTAL, UPCOMING_DEADLINES_COUNT
from app.digests.brevo_client import BrevoTransactionalClient
from app.ingest.deadline_extractor import (
    DeadlineAlertConfig,
    RegulatoryDeadline,
)
from app.observability import get_logger

logger = get_logger("docscout.digests.deadline_notifier")


@dataclass(frozen=True)
class DeadlineDispatchResult:
    """Summary of executed deadline alerting pass."""

    total_checked: int
    alerts_dispatched: int
    critical_count: int
    warning_count: int
    info_count: int
    duration_ms: float


class DeadlineNotifier:
    """Dispatches statutory cutover notifications and countdown alerts."""

    def __init__(
        self,
        pool: Any | None = None,
        brevo_client: BrevoTransactionalClient | None = None,
        config: DeadlineAlertConfig | None = None,
    ) -> None:
        self.pool = pool
        self.brevo_client = brevo_client or BrevoTransactionalClient()
        self.config = config or DeadlineAlertConfig()

    def dispatch_alerts(
        self,
        deadlines: Sequence[RegulatoryDeadline],
        recipients: Sequence[str],
        dry_run: bool = False,
    ) -> DeadlineDispatchResult:
        """Dispatch countdown alerts for pending regulatory cutovers.

        Args:
            deadlines: List of validated regulatory deadlines.
            recipients: Target email addresses for compliance officers.
            dry_run: If True, skips external email transmission and db writes.

        Returns:
            DeadlineDispatchResult summarizing counts and latency.
        """
        t0 = time.perf_counter()

        critical_count = sum(1 for d in deadlines if d.urgency_level == "CRITICAL")
        warning_count = sum(1 for d in deadlines if d.urgency_level == "WARNING")
        info_count = sum(1 for d in deadlines if d.urgency_level == "INFO")

        # Update gauge telemetry
        UPCOMING_DEADLINES_COUNT.labels(urgency="CRITICAL").set(critical_count)
        UPCOMING_DEADLINES_COUNT.labels(urgency="WARNING").set(warning_count)
        UPCOMING_DEADLINES_COUNT.labels(urgency="INFO").set(info_count)

        dispatched_count = 0

        for deadline in deadlines:
            # Render notification content
            subject = (
                f"[{deadline.urgency_level}] Statutory Cutover Alert: "
                f"{deadline.doc_id} ({deadline.days_remaining} days remaining)"
            )
            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h2 style="color: {"#dc2626" if deadline.urgency_level == "CRITICAL" else "#d97706" if deadline.urgency_level == "WARNING" else "#2563eb"};">
                    Regulatory Cutover Alert &mdash; {deadline.urgency_level}
                </h2>
                <p><strong>Document ID:</strong> {deadline.doc_id}</p>
                <p><strong>Effective Date:</strong> {deadline.effective_date.isoformat()}</p>
                <p><strong>Countdown:</strong> {deadline.days_remaining} days remaining</p>
                <div style="background-color: #f8fafc; padding: 12px; border-left: 4px solid #3b82f6; margin: 16px 0;">
                    <em>{deadline.mandate_description}</em>
                </div>
                <p style="font-size: 12px; color: #64748b;">
                    Generated automatically by DocScout Enterprise Regulatory Intelligence Engine.
                </p>
            </div>
            """

            for recipient in recipients:
                if not dry_run:
                    try:
                        self.brevo_client.send_transactional_email(
                            recipient_email=recipient,
                            subject=subject,
                            html_content=html_body,
                        )
                    except Exception as err:
                        logger.warning(
                            "Failed to send deadline alert email via Brevo",
                            recipient=recipient,
                            doc_id=deadline.doc_id,
                            error=str(err),
                        )

                    # Persist record to PostgreSQL if database connection pool is active
                    if self.pool is not None:
                        try:
                            with self.pool.connection() as conn:
                                conn.execute(
                                    """
                                    INSERT INTO deadline_alert_history (
                                        id, deadline_id, doc_id, recipient_email, channel,
                                        urgency_level, days_remaining, sent_at, delivery_status
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                                    """,
                                    (
                                        str(uuid4()),
                                        f"{deadline.doc_id}-{deadline.effective_date.isoformat()}",
                                        deadline.doc_id,
                                        recipient,
                                        "EMAIL",
                                        deadline.urgency_level,
                                        deadline.days_remaining,
                                        "SENT",
                                    ),
                                )
                        except Exception as db_err:
                            logger.warning(
                                "Failed to log deadline alert history in database",
                                error=str(db_err),
                            )

                DEADLINE_ALERTS_SENT_TOTAL.labels(
                    channel="EMAIL",
                    urgency=deadline.urgency_level,
                ).inc()
                dispatched_count += 1

        duration_ms = (time.perf_counter() - t0) * 1000.0

        return DeadlineDispatchResult(
            total_checked=len(deadlines),
            alerts_dispatched=dispatched_count,
            critical_count=critical_count,
            warning_count=warning_count,
            info_count=info_count,
            duration_ms=duration_ms,
        )
