"""Durable retrieval audit logging for forensics and compliance (OWASP LLM09, P1-1).

Why: Before this module, queries were logged only to stdout via ephemeral log streams.
Forensic investigations ("what was retrieved for whom?", "did an attacker probe the index?")
could not be answered with certainty once log buffers rolled over.

Key properties:
1. **Query Privacy**: Query text is hashed with SHA-256 by default. Plaintext queries are
   NEVER stored in the audit table, preventing incidental PII or confidential queries from
   being exposed to auditors or DB inspectors.
2. **Credential Isolation**: Raw API keys are never stored. Only the truncated SHA-256
   `key_fingerprint` (12 hex characters) is stored.
3. **Append-Only Tamper Resistance**: The database role `docscout_app` has INSERT and SELECT
   privileges on `retrieval_audit_log`, but strictly NO DELETE and NO UPDATE privileges.
4. **Resilience**: Database audit recording never breaks user search; transient DB errors
   are captured, logged, counted in metrics, and optionally written to a JSONL file sink.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from app.api import metrics
from app.observability import get_logger

logger = get_logger("docscout.audit")

_FILE_LOCK = threading.Lock()
DEFAULT_AUDIT_RETENTION_DAYS = 90


@dataclass(frozen=True)
class RetrievalAuditRecord:
    """An immutable retrieval event record for forensic audit."""

    key_fingerprint: str
    query_hash: str
    mode: str
    k: int
    returned_chunk_ids: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    cache_hit: bool = False
    has_generated_answer: bool = False
    corpus_generation: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


def hash_query(query: str) -> str:
    """Return the SHA-256 hex digest of the normalized query text."""
    normalized = query.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def audit_file_path() -> Path | None:
    """Return configured file sink path from DOCSCOUT_AUDIT_LOG_FILE, if any."""
    raw = os.environ.get("DOCSCOUT_AUDIT_LOG_FILE", "").strip()
    return Path(raw) if raw else None


def append_file_audit(record: RetrievalAuditRecord, path: Path | None = None) -> None:
    """Append audit record to a JSONL file sink in a thread-safe manner."""
    target = path or audit_file_path()
    if target is None:
        return

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.as_dict()) + "\n"
        with _FILE_LOCK:
            with target.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:  # noqa: BLE001 - audit file sink must not crash caller
        logger.warning("audit.file_write_failed", path=str(target), exc_info=True)


def record_audit_to_db(conn: psycopg.Connection[Any], record: RetrievalAuditRecord) -> int | None:
    """Insert audit record into retrieval_audit_log table. Returns record id."""
    # Convert string chunk IDs to UUID instances for psycopg
    chunk_uuids = [UUID(cid) for cid in record.returned_chunk_ids]

    row = conn.execute(
        """
        INSERT INTO retrieval_audit_log (
            key_fingerprint,
            query_hash,
            mode,
            k,
            returned_chunk_ids,
            latency_ms,
            cache_hit,
            has_generated_answer,
            corpus_generation,
            timestamp
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            record.key_fingerprint,
            record.query_hash,
            record.mode,
            record.k,
            chunk_uuids,
            round(record.latency_ms, 2),
            record.cache_hit,
            record.has_generated_answer,
            record.corpus_generation,
            record.timestamp,
        ),
    ).fetchone()
    return int(row[0]) if row else None


def record_retrieval_event(pool: ConnectionPool | None, record: RetrievalAuditRecord) -> None:
    """Record retrieval audit event to database and optional file sink.

    Guarantees that audit recording errors NEVER propagate to or fail user requests.
    """
    # 1. Always attempt optional file sink if configured
    append_file_audit(record)

    # 2. Database sink
    if pool is None:
        metrics.RETRIEVAL_AUDITS.labels("error").inc()
        return

    try:
        with pool.connection() as conn:
            record_audit_to_db(conn, record)
        metrics.RETRIEVAL_AUDITS.labels("ok").inc()
    except Exception:  # noqa: BLE001 - audit failure must not fail user request
        metrics.RETRIEVAL_AUDITS.labels("error").inc()
        logger.warning(
            "audit.db_insert_failed",
            query_hash=record.query_hash,
            key_fingerprint=record.key_fingerprint,
            exc_info=True,
        )


def get_recent_audit_records(
    conn: psycopg.Connection[Any], limit: int = 20
) -> list[RetrievalAuditRecord]:
    """Retrieve recent audit records for testing and operational inspections."""
    rows = conn.execute(
        """
        SELECT
            key_fingerprint,
            query_hash,
            mode,
            k,
            returned_chunk_ids,
            latency_ms,
            cache_hit,
            has_generated_answer,
            corpus_generation,
            timestamp
        FROM retrieval_audit_log
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()

    records: list[RetrievalAuditRecord] = []
    for r in rows:
        c_ids = [str(u) for u in r[4]] if r[4] else []
        records.append(
            RetrievalAuditRecord(
                key_fingerprint=str(r[0]),
                query_hash=str(r[1]),
                mode=str(r[2]),
                k=int(r[3]),
                returned_chunk_ids=c_ids,
                latency_ms=float(r[5]),
                cache_hit=bool(r[6]),
                has_generated_answer=bool(r[7]),
                corpus_generation=int(r[8]),
                timestamp=r[9],
            )
        )
    return records
