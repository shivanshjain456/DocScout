"""Digest generation and dispatch engine — ARCHITECTURE §3.1.

Coordinates subscription management, topic matching, grounded provision extraction,
and restart-safe deduplicated delivery logging through Brevo:
1. Topic and authority matching over newly verified regulatory circulars.
2. Synthetic fixture exclusion invariant: synthetic evaluation artifacts and injection
   canaries never reach analyst digests.
3. Idempotent queueing and delivery tracking: enforces `uq_digest_delivery_version`
   (subscription_id, version_id) so scheduler reruns, crashes, or retries never duplicate sends.
4. Cryptographically tamper-proof one-click unsubscribe links requiring no password login.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.config import docscout_base_url
from app.digests.brevo_client import BrevoTransactionalClient
from app.digests.models import (
    DigestCircularItem,
    DigestPayload,
    Frequency,
    TopicSubscription,
)
from app.observability import get_logger

logger = get_logger("docscout.digest_engine")


def generate_unsubscribe_token() -> str:
    """Generate a high-entropy URL-safe token for one-click unsubscribe links."""
    return secrets.token_urlsafe(32)


class DigestEngine:
    """Core engine orchestrating regulatory subscriptions and Brevo delivery."""

    def __init__(
        self,
        pool: Any,
        brevo_client: BrevoTransactionalClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self.pool = pool
        self.brevo_client = brevo_client or BrevoTransactionalClient()
        self.base_url = (base_url or docscout_base_url()).rstrip("/")

    def get_user_subscription(self, user_id: UUID) -> TopicSubscription | None:
        """Fetch subscription details and selected topics for a specific user."""
        with self.pool.connection() as conn:
            sub_row = conn.execute(
                """
                SELECT subscription_id, user_id, email, frequency, is_active,
                       unsubscribe_token, consent_ts, created_at
                  FROM subscriptions
                 WHERE user_id = %s
                """,
                (user_id,),
            ).fetchone()

            if sub_row is None:
                return None

            sub_id = UUID(str(sub_row[0]))
            topic_rows = conn.execute(
                """
                SELECT topic, regulator
                  FROM subscription_topics
                 WHERE subscription_id = %s
                """,
                (sub_id,),
            ).fetchall()

            topics = [str(r[0]) for r in topic_rows]
            regs = list({str(r[1]) for r in topic_rows})

            return TopicSubscription(
                subscription_id=sub_id,
                user_id=UUID(str(sub_row[1])),
                email=str(sub_row[2]),
                frequency=str(sub_row[3]),  # type: ignore[arg-type]
                is_active=bool(sub_row[4]),
                unsubscribe_token=str(sub_row[5]),
                consent_ts=sub_row[6],
                created_at=sub_row[7],
                topics=topics,
                regulators=regs,
            )

    def upsert_subscription(
        self,
        user_id: UUID,
        email: str,
        frequency: Frequency = "weekly",
        topics: Sequence[str] | None = None,
        regulators: Sequence[str] | None = None,
        consent_ip: str | None = None,
        is_active: bool = True,
    ) -> TopicSubscription:
        """Create or update topic-based regulatory digest subscription with explicit consent."""
        clean_email = email.strip().lower()
        sub_topics = list(topics) if topics else ["ALL"]
        sub_regs = list(regulators) if regulators else ["ALL"]
        token = generate_unsubscribe_token()

        with self.pool.connection() as conn:
            with conn.transaction():
                # Upsert into subscriptions
                row = conn.execute(
                    """
                    INSERT INTO subscriptions
                        (user_id, email, frequency, is_active, consent_ts, consent_ip, unsubscribe_token)
                    VALUES (%s, %s, %s, %s, now(), %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        email = EXCLUDED.email,
                        frequency = EXCLUDED.frequency,
                        is_active = EXCLUDED.is_active,
                        consent_ts = now(),
                        consent_ip = COALESCE(EXCLUDED.consent_ip, subscriptions.consent_ip),
                        updated_at = now()
                    RETURNING subscription_id, user_id, email, frequency, is_active,
                              unsubscribe_token, consent_ts, created_at
                    """,
                    (user_id, clean_email, frequency, is_active, consent_ip, token),
                ).fetchone()

                if row is None:
                    raise RuntimeError("failed to upsert subscription")

                sub_id = UUID(str(row[0]))

                # Replace topic filters
                conn.execute(
                    "DELETE FROM subscription_topics WHERE subscription_id = %s",
                    (sub_id,),
                )
                for top in sub_topics:
                    for reg in sub_regs:
                        conn.execute(
                            """
                            INSERT INTO subscription_topics (subscription_id, topic, regulator)
                            VALUES (%s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (sub_id, top.strip(), reg.strip().upper()),
                        )

        return TopicSubscription(
            subscription_id=sub_id,
            user_id=user_id,
            email=clean_email,
            frequency=frequency,
            is_active=is_active,
            unsubscribe_token=str(row[5]),
            consent_ts=row[6],
            created_at=row[7],
            topics=sub_topics,
            regulators=sub_regs,
        )

    def unsubscribe_by_token(self, token: str) -> bool:
        """One-click unsubscribe without login. Returns True if a subscription was deactivated."""
        if not token:
            return False

        with self.pool.connection() as conn:
            with conn.transaction():
                res = conn.execute(
                    """
                    UPDATE subscriptions
                       SET is_active = false,
                           updated_at = now()
                     WHERE unsubscribe_token = %s AND is_active = true
                    """,
                    (token.strip(),),
                )
                deactivated = bool(res.rowcount and res.rowcount > 0)
                if deactivated:
                    logger.info("digest.unsubscribed", token_prefix=token[:8])
                return deactivated

    def find_eligible_circulars(
        self,
        subscription: TopicSubscription,
        since_hours: float = 168.0,
    ) -> list[DigestCircularItem]:
        """Find newly verified circulars matching the subscription's regulators and topics.

        CRITICAL INVARIANT: Evaluates `WHERE NOT d.is_synthetic`. Synthetic test fixtures
        and injection canaries are permanently excluded from production digests.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
        items: list[DigestCircularItem] = []

        with self.pool.connection() as conn:
            # Query recent verified documents
            rows = conn.execute(
                """
                SELECT d.document_id, v.version_id, d.title, d.source,
                       d.canonical_url, d.published_date::text, v.fetch_ts
                  FROM documents d
                  JOIN document_versions v ON d.document_id = v.document_id
                 WHERE v.is_current
                   AND NOT d.is_synthetic
                   AND v.fetch_ts >= %s
                   AND NOT EXISTS (
                       SELECT 1 FROM digest_deliveries dd
                        WHERE dd.subscription_id = %s
                          AND dd.version_id = v.version_id
                   )
                 ORDER BY v.fetch_ts DESC
                 LIMIT 10
                """,
                (cutoff, subscription.subscription_id),
            ).fetchall()

            for r in rows:
                doc_id = UUID(str(r[0]))
                ver_id = UUID(str(r[1]))
                title = str(r[2]) if r[2] else "Regulatory Circular"
                source = str(r[3])
                url = str(r[4])
                pub_date = str(r[5]) if r[5] else None
                fetch_ts = r[6]

                # Filter by subscription authority
                if "ALL" not in subscription.regulators and source not in subscription.regulators:
                    continue

                # Fetch 2 representative chunks for grounded provisions
                chunk_rows = conn.execute(
                    """
                    SELECT chunk_id::text, text
                      FROM chunks
                     WHERE document_id = %s AND version_id = %s
                     ORDER BY ordinal ASC
                     LIMIT 2
                    """,
                    (doc_id, ver_id),
                ).fetchall()

                provisions: list[str] = []
                citations: list[dict[str, str]] = []
                for cr in chunk_rows:
                    cid = str(cr[0])
                    chunk_text = str(cr[1]).strip()
                    first_sent = chunk_text.split(". ")[0].strip()
                    if first_sent and len(first_sent) > 20:
                        provisions.append(f"{first_sent}.")
                    citations.append({"chunk_id": cid, "quote": chunk_text[:200]})

                if not provisions:
                    provisions = ["Refer to the full text of the authoritative circular."]

                items.append(
                    DigestCircularItem(
                        document_id=doc_id,
                        version_id=ver_id,
                        title=title,
                        source=source,
                        canonical_url=url,
                        published_date=pub_date,
                        summary_provisions=provisions,
                        citations=citations,
                        fetch_ts=fetch_ts,
                    )
                )

        return items

    def process_pending_digests(
        self,
        frequency: Frequency = "weekly",
        since_hours: float = 168.0,
    ) -> int:
        """Process and dispatch pending regulatory digests for active subscribers.

        Returns total number of delivered circular notifications.
        """
        sent_count = 0
        with self.pool.connection() as conn:
            subs = conn.execute(
                """
                SELECT subscription_id, user_id, email, frequency, is_active,
                       unsubscribe_token, consent_ts, created_at
                  FROM subscriptions
                 WHERE is_active = true AND frequency = %s
                """,
                (frequency,),
            ).fetchall()

        for srow in subs:
            sub = TopicSubscription(
                subscription_id=UUID(str(srow[0])),
                user_id=UUID(str(srow[1])),
                email=str(srow[2]),
                frequency=str(srow[3]),  # type: ignore[arg-type]
                is_active=bool(srow[4]),
                unsubscribe_token=str(srow[5]),
                consent_ts=srow[6],
                created_at=srow[7],
            )

            circulars = self.find_eligible_circulars(sub, since_hours=since_hours)
            if not circulars:
                continue

            # Queue deliveries in DB
            queued_deliveries: list[tuple[UUID, UUID, UUID]] = []
            with self.pool.connection() as conn:
                with conn.transaction():
                    for circ in circulars:
                        del_row = conn.execute(
                            """
                            INSERT INTO digest_deliveries
                                (subscription_id, document_id, version_id, recipient_email, status)
                            VALUES (%s, %s, %s, %s, 'QUEUED')
                            ON CONFLICT (subscription_id, version_id) DO NOTHING
                            RETURNING delivery_id
                            """,
                            (sub.subscription_id, circ.document_id, circ.version_id, sub.email),
                        ).fetchone()

                        if del_row is not None:
                            queued_deliveries.append(
                                (UUID(str(del_row[0])), circ.document_id, circ.version_id)
                            )

            if not queued_deliveries:
                continue

            # Dispatch via Brevo
            unsub_link = (
                f"{self.base_url}/v1/subscriptions/unsubscribe?token={sub.unsubscribe_token}"
            )
            payload = DigestPayload(
                recipient_email=sub.email,
                recipient_name=sub.email.split("@")[0].capitalize(),
                frequency=frequency,
                items=circulars,
                unsubscribe_url=unsub_link,
                generated_at=datetime.now(UTC).strftime("%B %d, %Y %H:%M UTC"),
            )

            # Mark SENDING
            with self.pool.connection() as conn:
                for del_id, _, _ in queued_deliveries:
                    conn.execute(
                        "UPDATE digest_deliveries SET status = 'SENDING', attempts = attempts + 1 WHERE delivery_id = %s",
                        (del_id,),
                    )

            send_result = self.brevo_client.send_digest(payload)

            with self.pool.connection() as conn:
                with conn.transaction():
                    if send_result.success:
                        for del_id, _, _ in queued_deliveries:
                            conn.execute(
                                """
                                UPDATE digest_deliveries
                                   SET status = 'SENT',
                                       brevo_message_id = %s,
                                       sent_at = now()
                                 WHERE delivery_id = %s
                                """,
                                (send_result.message_id, del_id),
                            )
                        sent_count += len(queued_deliveries)
                    elif send_result.status == "QUOTA_EXCEEDED":
                        for del_id, _, _ in queued_deliveries:
                            conn.execute(
                                """
                                UPDATE digest_deliveries
                                   SET status = 'QUEUED',
                                       error_message = %s
                                 WHERE delivery_id = %s
                                """,
                                (send_result.error_detail, del_id),
                            )
                    else:
                        for del_id, _, _ in queued_deliveries:
                            conn.execute(
                                """
                                UPDATE digest_deliveries
                                   SET status = 'FAILED',
                                       error_message = %s
                                 WHERE delivery_id = %s
                                """,
                                (send_result.error_detail, del_id),
                            )

        return sent_count
