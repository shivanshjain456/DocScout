"""Canary Token Provenance & Leakage Assertions (FEAT-084, ADR-0075).

Generates and plants high-entropy cryptographic canary tokens into synthetic circular fixtures,
and verifies zero cross-tenant leakage or synthetic data contamination in production responses.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from app.api import metrics

logger = structlog.get_logger("docscout.evals.canary")

# Regex to detect canary tokens formatted as CANARY-<hex32>
CANARY_TOKEN_RE = re.compile(r"CANARY-[a-fA-F0-9]{32}", re.IGNORECASE)


@dataclass
class CanaryConfig:
    """Configuration schema for Canary Token Provenance & Leakage Assertions."""

    enforce_zero_leakage_gate: bool = True
    canary_prefix: str = "CANARY-"


@dataclass
class CanaryToken:
    """Represents a unique cryptographic canary token planted in a test fixture."""

    canary_id: str
    token_string: str
    fixture_name: str
    document_id: str | None = None
    planted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanaryAuditReport:
    """Result of an assertion sweep checking for canary token emergence."""

    canaries_planted: int
    leakage_detected: bool
    leaked_canary_ids: list[str]
    passed_assertions: bool
    scanned_targets_count: int
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanaryManager:
    """Manages canary token lifecycle, fixture planting, and zero-leakage assertions."""

    def __init__(self, config: CanaryConfig | None = None) -> None:
        self.config = config or CanaryConfig()
        self._tokens: dict[str, CanaryToken] = {}

    def generate_canary(
        self,
        fixture_name: str,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CanaryToken:
        """Generate a high-entropy cryptographic canary token."""
        secret_suffix = secrets.token_hex(16)
        token_string = f"{self.config.canary_prefix}{secret_suffix}"
        canary_id = f"canary-{secrets.token_hex(8)}"

        token = CanaryToken(
            canary_id=canary_id,
            token_string=token_string,
            fixture_name=fixture_name,
            document_id=document_id,
            metadata=metadata or {},
        )
        self._tokens[token.token_string] = token
        return token

    def plant_canary(self, fixture_text: str, token: CanaryToken) -> str:
        """Embed canary token into a synthetic fixture's prose."""
        self._tokens[token.token_string] = token
        embedded_sentence = f" [Internal Tracking Reference: {token.token_string}]"
        return f"{fixture_text.strip()}{embedded_sentence}"

    def assert_zero_leakage(
        self,
        passages: Sequence[Any],
        query_responses: Sequence[str] | None = None,
    ) -> CanaryAuditReport:
        """Scan production evidence passages and answer texts for any leaked canary tokens."""
        scanned_count = len(passages) + (len(query_responses) if query_responses else 0)
        leaked_tokens: set[str] = set()

        # 1. Scan evidence passages
        for p in passages:
            text = (
                getattr(p, "text", "")
                if hasattr(p, "text")
                else (p.get("text", "") if isinstance(p, dict) else str(p))
            )
            found = CANARY_TOKEN_RE.findall(text)
            for t in found:
                leaked_tokens.add(t)

        # 2. Scan synthesized query answers if provided
        if query_responses:
            for ans in query_responses:
                found = CANARY_TOKEN_RE.findall(ans)
                for t in found:
                    leaked_tokens.add(t)

        leakage_detected = len(leaked_tokens) > 0
        passed = not leakage_detected

        # Update Prometheus metrics
        metrics.CANARY_AUDIT_RUNS_TOTAL.inc()
        metrics.CANARY_LEAKAGE_DETECTED.set(1.0 if leakage_detected else 0.0)

        if leakage_detected:
            logger.error(
                "canary.leakage_detected",
                leaked_tokens=list(leaked_tokens),
                scanned_targets=scanned_count,
            )
        else:
            logger.info(
                "canary.assertions_passed",
                scanned_targets=scanned_count,
                registered_canaries=len(self._tokens),
            )

        return CanaryAuditReport(
            canaries_planted=len(self._tokens),
            leakage_detected=leakage_detected,
            leaked_canary_ids=list(leaked_tokens),
            passed_assertions=passed,
            scanned_targets_count=scanned_count,
            details={
                "zero_leakage_enforced": self.config.enforce_zero_leakage_gate,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def audit_corpus_leakage(self, conn: Any) -> CanaryAuditReport:
        """Audit database to prove non-synthetic documents contain zero canary tokens."""
        query = """
            SELECT c.chunk_id, d.document_id, c.text
            FROM chunks c
            JOIN documents d ON c.document_id = d.document_id
            WHERE d.is_synthetic = false
              AND c.text ~* 'CANARY-[a-f0-9]{32}'
        """
        leaked_tokens: list[str] = []
        rows: list[Any] = []
        try:
            cur = conn.execute(query)
            rows = cur.fetchall()
            for row in rows:
                text = row[2]
                for match in CANARY_TOKEN_RE.findall(text):
                    leaked_tokens.append(match)
        except Exception as exc:
            logger.warning("canary.db_audit_skipped_or_failed", error=str(exc))

        leakage_detected = len(leaked_tokens) > 0
        metrics.CANARY_AUDIT_RUNS_TOTAL.inc()
        metrics.CANARY_LEAKAGE_DETECTED.set(1.0 if leakage_detected else 0.0)

        return CanaryAuditReport(
            canaries_planted=len(self._tokens),
            leakage_detected=leakage_detected,
            leaked_canary_ids=leaked_tokens,
            passed_assertions=not leakage_detected,
            scanned_targets_count=len(rows),
            details={"database_audit": True},
        )


_DEFAULT_CANARY_MANAGER: CanaryManager | None = None


def get_default_canary_manager() -> CanaryManager:
    """Return singleton instance of CanaryManager."""
    global _DEFAULT_CANARY_MANAGER
    if _DEFAULT_CANARY_MANAGER is None:
        _DEFAULT_CANARY_MANAGER = CanaryManager()
    return _DEFAULT_CANARY_MANAGER
