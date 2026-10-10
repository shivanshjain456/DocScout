"""Brevo Transactional Email REST client (formerly Sendinblue) — ARCHITECTURE §3.1.

Implements email transmission adhering to Brevo v3 API standards:
1. Calls `POST https://api.brevo.com/v3/smtp/email` with header `api-key`.
2. Enforces daily free-plan ceiling (default 300 emails/day). Never silently ignores quota.
3. Formats recipient names, HTML/text multipart payloads, headers (List-Unsubscribe), and tags.
4. Bounded retries on transient network errors; fails fast on 4xx authorization or schema errors.
5. Surfaces provider status honestly: returns provider messageId on 201; preserves failure reasons.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from app.config import (
    brevo_api_key,
    brevo_api_url,
    brevo_daily_quota,
    brevo_sender_email,
    brevo_sender_name,
)
from app.digests.formatter import render_digest_html, render_digest_text
from app.digests.models import DigestPayload
from app.observability import get_logger

logger = get_logger("docscout.brevo")


@dataclass(frozen=True)
class BrevoSendResult:
    """Outcome of attempting to send one transactional email through Brevo."""

    success: bool
    status: str  # 'ACCEPTED' | 'QUOTA_EXCEEDED' | 'FAILED' | 'CONFIG_ERROR'
    message_id: str | None
    error_detail: str | None = None
    http_status: int | None = None
    attempts: int = 1


class BrevoTransactionalClient:
    """Production client for Brevo Transactional Email REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        daily_quota: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = (api_key or brevo_api_key()).strip()
        self.api_url = (api_url or brevo_api_url()).rstrip("/")
        self.sender_email = (sender_email or brevo_sender_email()).strip()
        self.sender_name = (sender_name or brevo_sender_name()).strip()
        self.daily_quota = daily_quota if daily_quota is not None else brevo_daily_quota()
        self.timeout = timeout

        self._daily_sends: int = 0
        self._current_date: date = datetime.now(UTC).date()

    def _check_quota(self) -> bool:
        """Check and update daily quota window."""
        today = datetime.now(UTC).date()
        if today != self._current_date:
            self._current_date = today
            self._daily_sends = 0

        return self._daily_sends < self.daily_quota

    def send_digest(self, payload: DigestPayload) -> BrevoSendResult:
        """Send a formatted regulatory digest email to an analyst."""
        if not self.api_key:
            return BrevoSendResult(
                success=False,
                status="CONFIG_ERROR",
                message_id=None,
                error_detail="BREVO_API_KEY is not configured",
            )

        if not self.sender_email:
            return BrevoSendResult(
                success=False,
                status="CONFIG_ERROR",
                message_id=None,
                error_detail="BREVO_SENDER_EMAIL is not configured",
            )

        if not self._check_quota():
            return BrevoSendResult(
                success=False,
                status="QUOTA_EXCEEDED",
                message_id=None,
                error_detail=(
                    f"Daily sending limit reached: {self._daily_sends}/{self.daily_quota} emails sent today. "
                    "Halting transmission to respect Brevo free tier quota."
                ),
            )

        html_content = render_digest_html(payload)
        text_content = render_digest_text(payload)

        url = f"{self.api_url}/smtp/email"
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {
            "sender": {
                "name": self.sender_name,
                "email": self.sender_email,
            },
            "to": [
                {
                    "email": payload.recipient_email,
                    "name": payload.recipient_name or "DocScout Analyst",
                }
            ],
            "subject": f"DocScout Regulatory Digest: {len(payload.items)} Newly Verified Circular(s)",
            "htmlContent": html_content,
            "textContent": text_content,
            "headers": {
                "List-Unsubscribe": f"<{payload.unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
            "tags": ["docscout-regulatory-digest", payload.frequency],
        }

        max_attempts = 3
        backoff = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=body, headers=headers)

                    # 201 Created is Brevo's success status
                    if resp.status_code == 201:
                        data = resp.json()
                        message_id = str(data.get("messageId", ""))
                        self._daily_sends += 1
                        logger.info(
                            "brevo.email_sent",
                            recipient=payload.recipient_email,
                            message_id=message_id,
                            items=len(payload.items),
                            attempt=attempt,
                        )
                        return BrevoSendResult(
                            success=True,
                            status="ACCEPTED",
                            message_id=message_id,
                            http_status=resp.status_code,
                            attempts=attempt,
                        )

                    # 400-403: configuration or schema failure; do not retry
                    if 400 <= resp.status_code < 500 and resp.status_code != 429:
                        err_text = resp.text[:300]
                        logger.warning(
                            "brevo.client_error",
                            status=resp.status_code,
                            detail=err_text,
                        )
                        return BrevoSendResult(
                            success=False,
                            status="FAILED",
                            message_id=None,
                            error_detail=f"Brevo HTTP {resp.status_code}: {err_text}",
                            http_status=resp.status_code,
                            attempts=attempt,
                        )

                    # 429 / 5xx: transient error, retry with backoff
                    if attempt < max_attempts:
                        time.sleep(backoff)
                        backoff *= 2.0
                        continue

                    return BrevoSendResult(
                        success=False,
                        status="FAILED",
                        message_id=None,
                        error_detail=f"Brevo server error HTTP {resp.status_code}: {resp.text[:300]}",
                        http_status=resp.status_code,
                        attempts=attempt,
                    )
            except Exception as exc:
                if attempt < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                return BrevoSendResult(
                    success=False,
                    status="FAILED",
                    message_id=None,
                    error_detail=f"Brevo network connection failure: {type(exc).__name__}: {exc}",
                    attempts=attempt,
                )

        return BrevoSendResult(
            success=False,
            status="FAILED",
            message_id=None,
            error_detail="Exceeded maximum delivery retry attempts",
            attempts=max_attempts,
        )
