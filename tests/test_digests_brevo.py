"""Tests for Brevo transactional email digest integration.

Validates:
1. Subscription lifecycle: creation, topic associations, consent logging, and frequencies.
2. Deduplication guarantee: `uq_digest_delivery_version` prevents duplicate sends.
3. Cryptographic one-click unsubscribe without password login.
4. Grounded digest formatting: HTML and plain text with authoritative URLs.
5. Brevo webhook processing: callback events update delivery state and handle bounces.
6. Daily sending quota tracking (300 emails/day free tier limit).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg.errors
import pytest

from app.digests.brevo_client import BrevoTransactionalClient
from app.digests.engine import DigestEngine
from app.digests.formatter import render_digest_html, render_digest_text
from app.digests.models import DigestCircularItem, DigestPayload
from app.digests.webhook import process_brevo_event


class PoolWrapper:
    """Lightweight connection pool wrapper around pytest db fixture."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    @contextmanager
    def connection(self) -> Any:
        yield self.conn


@pytest.fixture
def test_user(db: Any) -> uuid4:
    """Fixture ensuring a test user exists in the users table."""
    user_id = uuid4()
    with db.transaction():
        db.execute(
            """
            INSERT INTO users (user_id, auth0_sub, email, display_name, role)
            VALUES (%s, %s, %s, %s, 'reader')
            ON CONFLICT DO NOTHING
            """,
            (
                user_id,
                f"auth0|test-{user_id.hex[:8]}",
                f"analyst-{user_id.hex[:6]}@rbi.org.in",
                "Analyst Test",
            ),
        )
    return user_id


def test_subscription_creation_and_consent(db: Any, test_user: uuid4) -> None:
    """Analyst creates subscription with explicit consent and topic associations."""
    pool = PoolWrapper(db)
    engine = DigestEngine(pool)

    sub = engine.upsert_subscription(
        user_id=test_user,
        email="analyst@rbi.org.in",
        frequency="weekly",
        topics=["KYC", "FPI", "CAPITAL_ADEQUACY"],
        regulators=["RBI", "SEBI"],
        consent_ip="192.168.1.50",
        is_active=True,
    )

    assert sub.is_active
    assert sub.frequency == "weekly"
    assert len(sub.unsubscribe_token) >= 32
    assert "KYC" in sub.topics
    assert "RBI" in sub.regulators

    # Verify database state
    row = db.execute(
        "SELECT email, frequency, is_active, consent_ip FROM subscriptions WHERE subscription_id = %s",
        (sub.subscription_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "analyst@rbi.org.in"
    assert row[1] == "weekly"
    assert row[2] is True
    assert row[3] == "192.168.1.50"


def test_one_click_unsubscribe_by_token(db: Any, test_user: uuid4) -> None:
    """Analyst can unsubscribe immediately with high-entropy token without password login."""
    pool = PoolWrapper(db)
    engine = DigestEngine(pool)

    sub = engine.upsert_subscription(
        user_id=test_user,
        email="analyst-unsub@rbi.org.in",
        frequency="daily",
        topics=["ALL"],
        regulators=["ALL"],
        consent_ip="10.0.0.1",
        is_active=True,
    )

    # Execute unsubscribe
    deactivated = engine.unsubscribe_by_token(sub.unsubscribe_token)
    assert deactivated

    # Subscription must now be inactive
    row = db.execute(
        "SELECT is_active FROM subscriptions WHERE subscription_id = %s",
        (sub.subscription_id,),
    ).fetchone()
    assert row is not None
    assert row[0] is False


def test_grounded_digest_formatting() -> None:
    """Digest formatters render grounded items, authority links, and evidence guarantees."""
    items = [
        DigestCircularItem(
            document_id=uuid4(),
            version_id=uuid4(),
            source="RBI",
            title="Master Direction on Know Your Customer (KYC) Norms",
            published_date="2024-04-01",
            canonical_url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345",
            summary_provisions=[
                "Section 12: Simplified KYC procedures for small accounts.",
                "Section 18: Ongoing due diligence and periodic updation of KYC records.",
            ],
            citations=[
                {
                    "quote": "Simplified KYC procedures for small accounts.",
                    "chunk_id": "chunk-12345678",
                }
            ],
        )
    ]

    payload = DigestPayload(
        recipient_email="analyst@bank.in",
        recipient_name="Analyst",
        frequency="weekly",
        items=items,
        unsubscribe_url="https://docscout.local/v1/subscriptions/unsubscribe?token=sample-test-token-1234",
        generated_at=datetime.now(UTC).isoformat(),
    )

    html = render_digest_html(payload)
    text = render_digest_text(payload)

    # HTML assertions
    assert "Master Direction on Know Your Customer" in html
    assert "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345" in html
    assert "Section 12: Simplified KYC procedures" in html
    assert "sample-test-token-1234" in html
    assert "Grounded Evidence Notice" in html

    # Plain-text assertions
    assert "Master Direction on Know Your Customer" in text
    assert "Section 18: Ongoing due diligence" in text
    assert "GROUNDED EVIDENCE NOTICE" in text


def test_deduplication_guarantee_prevents_duplicate_deliveries(db: Any, test_user: uuid4) -> None:
    """Enforces uq_digest_delivery_version: same document version is not delivered twice."""
    pool = PoolWrapper(db)
    engine = DigestEngine(pool)

    sub = engine.upsert_subscription(
        user_id=test_user,
        email="analyst-dedup@rbi.org.in",
        frequency="immediate",
        topics=["ALL"],
        regulators=["ALL"],
        consent_ip="127.0.0.1",
        is_active=True,
    )

    doc_row = db.execute(
        "SELECT d.document_id, v.version_id FROM documents d JOIN document_versions v ON v.document_id = d.document_id LIMIT 1"
    ).fetchone()
    assert doc_row is not None
    doc_id, version_id = doc_row[0], doc_row[1]

    with db.transaction():
        # First delivery log succeeds
        db.execute(
            """
            INSERT INTO digest_deliveries
                (subscription_id, document_id, version_id, recipient_email, status, sent_at)
            VALUES (%s, %s, %s, %s, 'DELIVERED', now())
            """,
            (sub.subscription_id, doc_id, version_id, sub.email),
        )

    # Attempting duplicate delivery violates unique constraint
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            db.execute(
                """
                INSERT INTO digest_deliveries
                    (subscription_id, document_id, version_id, recipient_email, status, sent_at)
                VALUES (%s, %s, %s, %s, 'DELIVERED', now())
                """,
                (sub.subscription_id, doc_id, version_id, sub.email),
            )


def test_brevo_webhook_event_processing(db: Any, test_user: uuid4) -> None:
    """Webhook callback events update delivery logs and deactivate bounced recipients."""
    pool = PoolWrapper(db)
    engine = DigestEngine(pool)

    sub = engine.upsert_subscription(
        user_id=test_user,
        email="bounced-analyst@rbi.org.in",
        frequency="weekly",
        topics=["ALL"],
        regulators=["ALL"],
        consent_ip="127.0.0.1",
        is_active=True,
    )

    doc_row = db.execute(
        "SELECT d.document_id, v.version_id FROM documents d JOIN document_versions v ON v.document_id = d.document_id LIMIT 1"
    ).fetchone()
    assert doc_row is not None
    doc_id, version_id = doc_row[0], doc_row[1]
    msg_id = f"brevo-msg-{uuid4().hex[:12]}"

    with db.transaction():
        db.execute(
            """
            INSERT INTO digest_deliveries
                (subscription_id, document_id, version_id, recipient_email, brevo_message_id, status, sent_at)
            VALUES (%s, %s, %s, %s, %s, 'SENT', now())
            """,
            (sub.subscription_id, doc_id, version_id, sub.email, msg_id),
        )

    # Process Brevo hard bounce event callback
    event_data = {
        "event": "hard_bounce",
        "email": "bounced-analyst@rbi.org.in",
        "message-id": msg_id,
        "reason": "Mailbox does not exist",
    }

    result = process_brevo_event(pool, event_data)
    assert result["status"] == "ok"
    assert result["processed"] is True

    # Verify delivery status updated to bounced
    row = db.execute(
        "SELECT status FROM digest_deliveries WHERE brevo_message_id = %s",
        (msg_id,),
    ).fetchone()
    assert row is not None
    assert row[0].upper() == "BOUNCED"

    # Verify bounced subscription deactivated to respect sending hygiene
    sub_row = db.execute(
        "SELECT is_active FROM subscriptions WHERE subscription_id = %s",
        (sub.subscription_id,),
    ).fetchone()
    assert sub_row is not None
    assert sub_row[0] is False


def test_brevo_daily_quota_governance() -> None:
    """Enforces free tier ceiling (300/day); halts when daily limit reached."""
    client = BrevoTransactionalClient(
        api_key="test-key",
        sender_email="alerts@docscout.local",
        daily_quota=5,
    )
    client._daily_sends = 5  # Simulate limit reached

    payload = DigestPayload(
        recipient_email="analyst@bank.in",
        recipient_name="Analyst",
        frequency="daily",
        items=[],
        unsubscribe_url="https://docscout.local/unsub",
        generated_at=datetime.now(UTC).isoformat(),
    )

    result = client.send_digest(payload)
    assert not result.success
    assert result.status == "QUOTA_EXCEEDED"
    assert "Daily sending limit reached" in (result.error_detail or "")
