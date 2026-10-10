"""Data models for regulatory subscriptions, digests, and delivery records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

DeliveryStatus = Literal[
    "QUEUED", "SENDING", "SENT", "DELIVERED", "FAILED", "BOUNCED", "SUPPRESSED"
]
Frequency = Literal["immediate", "daily", "weekly"]
Regulator = Literal["RBI", "SEBI", "ALL"]


@dataclass(frozen=True)
class TopicSubscription:
    """An analyst's regulatory alert subscription."""

    subscription_id: UUID
    user_id: UUID
    email: str
    frequency: Frequency
    is_active: bool
    unsubscribe_token: str
    topics: list[str] = field(default_factory=list)
    regulators: list[str] = field(default_factory=list)
    consent_ts: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class DigestCircularItem:
    """One regulatory circular item included in a digest."""

    document_id: UUID
    version_id: UUID
    title: str
    source: str  # RBI | SEBI
    canonical_url: str
    published_date: str | None
    summary_provisions: list[str]
    citations: list[dict[str, str]]
    fetch_ts: datetime | None = None


@dataclass(frozen=True)
class DigestPayload:
    """Complete content rendered and dispatched in an analyst digest email."""

    recipient_email: str
    recipient_name: str
    frequency: Frequency
    items: list[DigestCircularItem]
    unsubscribe_url: str
    generated_at: str


@dataclass(frozen=True)
class DeliveryRecord:
    """State of an individual digest delivery attempt."""

    delivery_id: UUID
    subscription_id: UUID
    document_id: UUID
    version_id: UUID
    recipient_email: str
    status: DeliveryStatus
    attempts: int
    brevo_message_id: str | None = None
    error_message: str | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
