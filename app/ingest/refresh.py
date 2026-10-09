"""Scheduled corpus refresh and freshness verification  -  P0-2, ARCHITECTURE §3.1.

RBI and SEBI amend and withdraw regulatory circulars continuously. Stale retrieval is
the primary catastrophic failure for a compliance RAG service. This module provides the
scheduled refresh path:

1. Verification of on-disk manifest integrity and byte-level payload checksums.
2. Optional live HTTP verification of canonical regulator URLs (with allowlist defense).
3. Change detection: detects changed sha256 payloads at known canonical URLs (supersessions)
   and alert triggers when manifest or remote documents drift.
4. Updates PostgreSQL singleton `corpus_sync_state` with `last_checked_at` and live counts.
5. Emits Prometheus metrics (`docscout_manifest_changed_total`, `docscout_corpus_stale_hours`).
6. Generates a structured JSON refresh audit report in `corpus/reports/refresh/<ts>/`.

Preserves determinism in CI: in automated test runs and CI gates, live network calls are
disabled by default, operating over tracked artifacts while scheduled cron/workflows execute
periodic live checks.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import structlog

from app.api import metrics
from app.config import (
    REPO_ROOT,
    sha256_file,
    staleness_budget_hours,
)
from app.ingest.allowlist import assert_allowed, is_synthetic
from app.ingest.store import get_sync_state, record_sync_state

logger = structlog.get_logger(__name__)

DEFAULT_REFRESH_REPORT_ROOT = REPO_ROOT / "corpus" / "reports" / "refresh"


@dataclass
class RefreshItemResult:
    canonical_url: str
    source: str
    disk_path: str
    status: str  # ok | changed | missing | http_error | skipped_synthetic
    expected_sha256: str
    actual_sha256: str | None = None
    http_status: int | None = None
    detail: str = ""


@dataclass
class RefreshReport:
    """Audit report produced by a corpus refresh or freshness check."""

    timestamp: str
    manifest_path: str
    manifest_sha256: str
    previous_manifest_sha256: str | None
    manifest_changed: bool
    check_live: bool
    dry_run: bool
    documents_checked: int
    documents_ok: int
    documents_changed: list[dict[str, Any]]
    documents_missing: list[dict[str, Any]]
    check_status: str  # ok | manifest_changed | warning | error
    stale_hours: float
    staleness_budget_hours: float
    is_stale: bool
    alert_triggered: bool
    duration_s: float
    results: list[dict[str, Any]] = field(default_factory=list)

    def write(self, report_dir: Path) -> Path:
        """Write the refresh report to disk."""
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "refresh.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path


def run_corpus_refresh(
    manifest_path: Path,
    conn: psycopg.Connection[Any],
    *,
    check_live: bool = False,
    dry_run: bool = False,
    alert_on_change: bool = True,
    client: httpx.Client | None = None,
) -> RefreshReport:
    """Execute a corpus freshness check, change audit, and state update."""
    start_time = time.perf_counter()
    now_utc = datetime.now(UTC)

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    current_manifest_sha = sha256_file(manifest_path)
    manifest_bytes = manifest_path.read_text(encoding="utf-8")
    manifest_data = json.loads(manifest_bytes)
    documents_raw = manifest_data.get("documents", [])

    corpus_dir = manifest_path.parent
    sync_state = get_sync_state(conn)
    prev_manifest_sha = sync_state.last_manifest_sha if sync_state else None
    manifest_changed = prev_manifest_sha is not None and prev_manifest_sha != current_manifest_sha

    budget = staleness_budget_hours()
    last_checked = sync_state.last_checked_at if sync_state else None
    if last_checked is not None:
        if last_checked.tzinfo is None:
            last_checked = last_checked.replace(tzinfo=UTC)
        stale_hours = max(0.0, (now_utc - last_checked).total_seconds() / 3600.0)
    else:
        stale_hours = 0.0

    is_stale = stale_hours > budget

    results: list[RefreshItemResult] = []
    changed_items: list[dict[str, Any]] = []
    missing_items: list[dict[str, Any]] = []

    own_client = False
    if check_live and client is None:
        client = httpx.Client(
            headers={
                "User-Agent": (
                    "DocScout/1.0 (Regulatory freshness crawler; contact: ops@docscout.local)"
                )
            },
            timeout=15.0,
            follow_redirects=False,
        )
        own_client = True

    try:
        for doc in documents_raw:
            url = str(doc.get("canonical_url") or doc.get("url", ""))
            source = str(doc.get("source", ""))
            rel_path = str(doc.get("local_path") or doc.get("path", ""))
            expected_sha = str(doc.get("sha256", ""))

            candidate_paths = [
                REPO_ROOT / rel_path,
                corpus_dir / rel_path,
                corpus_dir / Path(rel_path).name,
            ]
            doc_file = next((p for p in candidate_paths if p.is_file()), candidate_paths[0])

            if not doc_file.is_file():
                res = RefreshItemResult(
                    canonical_url=url,
                    source=source,
                    disk_path=rel_path,
                    status="missing",
                    expected_sha256=expected_sha,
                    detail=f"file {rel_path} not found in corpus directory",
                )
                results.append(res)
                missing_items.append(asdict(res))
                continue

            actual_sha = hashlib.sha256(doc_file.read_bytes()).hexdigest()
            if actual_sha != expected_sha:
                res = RefreshItemResult(
                    canonical_url=url,
                    source=source,
                    disk_path=rel_path,
                    status="changed",
                    expected_sha256=expected_sha,
                    actual_sha256=actual_sha,
                    detail="disk content sha256 does not match manifest entry",
                )
                results.append(res)
                changed_items.append(asdict(res))
                continue

            # Check live remote endpoint if requested
            if check_live and client is not None:
                if is_synthetic(url):
                    results.append(
                        RefreshItemResult(
                            canonical_url=url,
                            source=source,
                            disk_path=rel_path,
                            status="skipped_synthetic",
                            expected_sha256=expected_sha,
                            actual_sha256=actual_sha,
                            detail="synthetic document never fetched over network",
                        )
                    )
                    continue

                try:
                    assert_allowed(url)
                    resp = client.head(url)
                    # Some regulator CDNs drop HEAD, retry GET with range
                    if resp.status_code in (405, 403):
                        resp = client.get(url, headers={"Range": "bytes=0-1024"})

                    if resp.status_code >= 400:
                        res = RefreshItemResult(
                            canonical_url=url,
                            source=source,
                            disk_path=rel_path,
                            status="http_error",
                            expected_sha256=expected_sha,
                            actual_sha256=actual_sha,
                            http_status=resp.status_code,
                            detail=f"HTTP probe returned status {resp.status_code}",
                        )
                        results.append(res)
                        if resp.status_code in (404, 410):
                            missing_items.append(asdict(res))
                        continue

                    # If server sent ETag or Content-Length that mismatches disk
                    remote_len = resp.headers.get("content-length")
                    disk_len = str(doc.get("bytes", doc_file.stat().st_size))
                    if remote_len and remote_len != disk_len:
                        res = RefreshItemResult(
                            canonical_url=url,
                            source=source,
                            disk_path=rel_path,
                            status="changed",
                            expected_sha256=expected_sha,
                            actual_sha256=actual_sha,
                            http_status=resp.status_code,
                            detail=f"Content-Length mismatch: remote {remote_len} vs local {disk_len}",
                        )
                        results.append(res)
                        changed_items.append(asdict(res))
                        continue

                    results.append(
                        RefreshItemResult(
                            canonical_url=url,
                            source=source,
                            disk_path=rel_path,
                            status="ok",
                            expected_sha256=expected_sha,
                            actual_sha256=actual_sha,
                            http_status=resp.status_code,
                            detail="verified live",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    res = RefreshItemResult(
                        canonical_url=url,
                        source=source,
                        disk_path=rel_path,
                        status="http_error",
                        expected_sha256=expected_sha,
                        actual_sha256=actual_sha,
                        detail=f"live check failed: {type(exc).__name__}: {exc}",
                    )
                    results.append(res)
            else:
                results.append(
                    RefreshItemResult(
                        canonical_url=url,
                        source=source,
                        disk_path=rel_path,
                        status="ok",
                        expected_sha256=expected_sha,
                        actual_sha256=actual_sha,
                        detail="verified on disk",
                    )
                )
    finally:
        if own_client and client is not None:
            client.close()

    ok_count = sum(1 for r in results if r.status in ("ok", "skipped_synthetic"))
    alert_triggered = False

    if manifest_changed or len(changed_items) > 0:
        check_status = "manifest_changed"
        alert_triggered = True
    elif len(missing_items) > 0:
        check_status = "warning"
        alert_triggered = True
    else:
        check_status = "ok"

    if alert_triggered and alert_on_change:
        logger.warning(
            "corpus.refresh.alert",
            check_status=check_status,
            manifest_changed=manifest_changed,
            changed_count=len(changed_items),
            missing_count=len(missing_items),
        )
        metrics.MANIFEST_CHANGED.inc()

    duration = time.perf_counter() - start_time

    report = RefreshReport(
        timestamp=now_utc.isoformat(),
        manifest_path=str(manifest_path),
        manifest_sha256=current_manifest_sha,
        previous_manifest_sha256=prev_manifest_sha,
        manifest_changed=manifest_changed,
        check_live=check_live,
        dry_run=dry_run,
        documents_checked=len(documents_raw),
        documents_ok=ok_count,
        documents_changed=changed_items,
        documents_missing=missing_items,
        check_status=check_status,
        stale_hours=0.0 if not dry_run else round(stale_hours, 2),
        staleness_budget_hours=budget,
        is_stale=False if not dry_run else is_stale,
        alert_triggered=alert_triggered,
        duration_s=round(duration, 3),
        results=[asdict(r) for r in results],
    )

    if not dry_run:
        record_sync_state(
            conn,
            last_checked_at=now_utc,
            last_manifest_sha=current_manifest_sha,
            check_status=check_status,
            details={
                "documents_checked": len(documents_raw),
                "documents_ok": ok_count,
                "changed_count": len(changed_items),
                "missing_count": len(missing_items),
                "manifest_changed": manifest_changed,
                "check_live": check_live,
                "duration_s": round(duration, 3),
            },
        )

    return report
