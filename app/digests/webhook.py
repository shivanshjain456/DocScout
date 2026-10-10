"""Brevo webhook callback handler for delivery tracking and suppression governance."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from app.config import brevo_webhook_secret
from app.observability import get_logger

logger = get_logger("docscout.brevo_webhook")


def verify_webhook_secret(request: Request, secret_param: str | None = None) -> bool:
    """Verify that incoming Brevo webhook presents the configured shared secret.

    Brevo transactional webhooks do not support HMAC signature headers; shared secret
    via custom header `X-DocScout-Webhook-Secret` or URL query parameter `secret` is the
    official authentication mechanism.
    """
    configured = brevo_webhook_secret()
    if not configured:
        # If no secret is configured, deny all external callback access to fail closed
        return False

    header_secret = request.headers.get("X-DocScout-Webhook-Secret") or request.headers.get(
        "X-Webhook-Secret"
    )
    candidate = header_secret or secret_param or ""
    return secrets.compare_digest(candidate.strip(), configured.strip())


def process_brevo_event(pool: Any, event_data: dict[str, Any]) -> dict[str, Any]:
    """Process one delivery event payload from Brevo webhook callback."""
    event_type = str(event_data.get("event", "")).lower()
    email = str(event_data.get("email", "")).strip().lower()
    msg_id = str(event_data.get("message-id") or event_data.get("messageId") or "").strip()
    reason = str(event_data.get("reason") or event_data.get("description") or "")

    logger.info(
        "brevo.webhook_event_received",
        brevo_event=event_type,
        email=email,
        message_id=msg_id,
        reason=reason,
    )

    with pool.connection() as conn:
        with conn.transaction():
            # 1. Update delivery status if message_id is provided
            if msg_id:
                if event_type == "delivered":
                    conn.execute(
                        """
                        UPDATE digest_deliveries
                           SET status = 'DELIVERED',
                               delivered_at = now()
                         WHERE brevo_message_id = %s
                        """,
                        (msg_id,),
                    )
                elif event_type in ("soft_bounce", "bounced"):
                    conn.execute(
                        """
                        UPDATE digest_deliveries
                           SET status = 'BOUNCED',
                               error_message = %s
                         WHERE brevo_message_id = %s
                        """,
                        (f"Soft bounce: {reason}", msg_id),
                    )
                elif event_type in ("hard_bounce", "invalid_email"):
                    conn.execute(
                        """
                        UPDATE digest_deliveries
                           SET status = 'BOUNCED',
                               error_message = %s
                         WHERE brevo_message_id = %s
                        """,
                        (f"Permanent bounce: {reason}", msg_id),
                    )

            # 2. Suppression handling: deactivate subscription for permanent bounces or spam complaints
            if event_type in ("hard_bounce", "invalid_email", "spam", "unsubscribe") and email:
                res = conn.execute(
                    """
                    UPDATE subscriptions
                       SET is_active = false,
                           updated_at = now()
                     WHERE lower(email) = %s AND is_active = true
                    """,
                    (email,),
                )
                if res.rowcount > 0:
                    logger.info("brevo.subscription_suppressed", email=email, reason=event_type)

    return {"status": "ok", "event": event_type, "processed": True}
