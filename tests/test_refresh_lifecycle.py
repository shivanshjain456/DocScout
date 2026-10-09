"""Comprehensive test suite for corpus refresh, freshness signals, and supersession lifecycle — P0-2.

Tests the five pillars of P0-2:
1. Scheduled corpus refresh updates singleton `corpus_sync_state` with audit provenance.
2. Alerting triggers when manifest or document hashes drift.
3. Operator freshness signal: `GET /healthz` and `GET /metrics` surface `stale_hours`
   and degrade status when staleness exceeds the configured budget.
4. Supersession lifecycle: a changed `sha256` at a known `canonical_url` (g-038 circular class)
   demotes the previous version (`is_current = false`), guarantees retention of old chunks (FR-4),
   and ensures retrieval excludes superseded content.
5. Truncate-and-rebuild procedure: validates the documented `TRUNCATE ... CASCADE` disaster recovery
   and re-embedding pathway.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from fastapi.testclient import TestClient
from pgvector.psycopg import register_vector

from app.api import metrics
from app.config import DEFAULT_STALENESS_BUDGET_HOURS
from app.ingest.chunk import chunk_document
from app.ingest.embed import EMBEDDING_DIM, Embedder
from app.ingest.pipeline import run_ingest, verify_stored_chunks
from app.ingest.refresh import run_corpus_refresh
from app.ingest.source import DEFAULT_MANIFEST, SourceDocument, iter_manifest_documents
from app.ingest.store import (
    Action,
    PreparedDocument,
    get_sync_state,
    record_sync_state,
    row_counts,
    store_document,
)
from app.retrieval import RetrievalConfig, Retriever


def _unit_embedding() -> np.ndarray:
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vec[0] = 1.0
    return vec


# --------------------------------------------------------------------------------------
# 1. Freshness tracking and sync state
# --------------------------------------------------------------------------------------
def test_refresh_records_sync_state_and_updates_timestamp(
    app_conn: psycopg.Connection[Any],
) -> None:
    """A refresh run audits manifest files and updates corpus_sync_state."""
    report = run_corpus_refresh(DEFAULT_MANIFEST, app_conn, check_live=False, dry_run=False)

    assert report.check_status in ("ok", "manifest_changed")
    assert report.documents_checked == 35
    assert report.documents_ok == 35
    assert report.stale_hours <= 0.1
    assert report.is_stale is False

    sync = get_sync_state(app_conn)
    assert sync is not None
    assert sync.documents_checked == 35
    assert sync.documents_current >= 35
    assert sync.check_status in ("ok", "manifest_changed")
    assert sync.last_manifest_sha == report.manifest_sha256
    app_conn.commit()


def test_refresh_detects_and_alerts_on_manifest_hash_change(
    app_conn: psycopg.Connection[Any],
    tmp_path: Path,
) -> None:
    """Drift between recorded manifest sha and actual manifest triggers an alert and metric."""
    # Write a copy of the manifest with modified metadata
    manifest_copy = tmp_path / "manifest.json"
    manifest_data = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest_data["generated_at"] = "2026-10-09T00:00:00Z"
    manifest_copy.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Seed sync state with a different fake previous hash
    record_sync_state(
        app_conn,
        last_checked_at=datetime.now(UTC),
        last_manifest_sha="0" * 64,
        check_status="ok",
    )

    before_metric = metrics.MANIFEST_CHANGED._value.get()  # noqa: SLF001

    report = run_corpus_refresh(manifest_copy, app_conn, check_live=False, alert_on_change=True)

    assert report.manifest_changed is True
    assert report.check_status == "manifest_changed"
    assert report.alert_triggered is True

    after_metric = metrics.MANIFEST_CHANGED._value.get()  # noqa: SLF001
    assert after_metric == before_metric + 1
    app_conn.commit()


# --------------------------------------------------------------------------------------
# 2. Staleness budgeting and API degradation
# --------------------------------------------------------------------------------------
def test_healthz_and_metrics_reflect_freshness_signals(client: TestClient) -> None:
    """GET /readyz and /metrics surface stale_hours, staleness_budget, and gauges."""
    res = client.get("/readyz")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] in ("ok", "degraded")
    assert data["last_checked_at"] is not None
    assert isinstance(data["stale_hours"], float)
    assert data["staleness_budget_hours"] == DEFAULT_STALENESS_BUDGET_HOURS

    # Verify Prometheus exposition
    metrics_text = client.get("/metrics").text
    assert "docscout_corpus_last_checked_timestamp_seconds" in metrics_text
    assert "docscout_corpus_stale_hours" in metrics_text
    assert "docscout_corpus_staleness_budget_hours" in metrics_text
    assert "docscout_corpus_is_stale" in metrics_text


def test_healthz_degrades_when_corpus_exceeds_staleness_budget(
    client: TestClient,
    owner_conn: psycopg.Connection[Any],
) -> None:
    """If last_checked_at is older than the staleness budget, /readyz reports degraded."""
    stale_time = datetime.now(UTC) - timedelta(hours=250)

    # Artificially set an old last_checked_at and COMMIT immediately so connection pool does not block
    owner_conn.execute(
        "UPDATE corpus_sync_state SET last_checked_at = %s WHERE id = 1",
        (stale_time,),
    )
    owner_conn.commit()

    try:
        res = client.get("/readyz")
        data = res.json()

        assert data["status"] == "degraded", "readyz must report degraded when corpus is stale"
        assert data["is_stale"] is True
        assert data["stale_hours"] >= 249.0
        assert data["database"] is True
        assert data["corpus_chunks"] > 0

        # Liveness check /healthz remains OK even when readiness is degraded
        liveness = client.get("/healthz").json()
        assert liveness["status"] == "ok", (
            "healthz liveness probe must remain ok during stale state"
        )

        # Verify metric gauge reflects stale state
        metrics_res = client.get("/metrics").text
        assert "docscout_corpus_is_stale 1.0" in metrics_res

    finally:
        # Restore fresh state and commit
        owner_conn.execute(
            "UPDATE corpus_sync_state SET last_checked_at = now() WHERE id = 1",
        )
        owner_conn.commit()

    recovered = client.get("/readyz").json()
    assert recovered["status"] == "ok"
    assert recovered["is_stale"] is False


# --------------------------------------------------------------------------------------
# 3. Supersession lifecycle (g-038 circular update class)
# --------------------------------------------------------------------------------------
def test_supersession_lifecycle_at_known_url(
    owner_conn: psycopg.Connection[Any],
    app_conn: psycopg.Connection[Any],
) -> None:
    """A changed sha256 at a known canonical URL demotes old version, retains chunks, and updates retrieval."""
    register_vector(app_conn)
    register_vector(owner_conn)

    test_url = "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/LIFECYCLE-TEST-001.PDF"
    old_sha = "1" * 64
    new_sha = "2" * 64

    boilerplate = (
        " Reserve Bank of India Department of Currency Management Master Circular on Cash Handling "
        "and Security Protocols at Currency Chests across all scheduled commercial banks. "
        "All authorized banking institutions must ensure compliance with security infrastructure standards, "
        "access control logs, vault biometric systems, physical armored transport requirements, "
        "and periodic regulatory auditing by central supervisory authorities. Failure to adhere to "
        "these directives shall attract penalties under Section 47A of the Banking Regulation Act, 1949."
    )
    old_text = (
        "Entities shall maintain CCTV recordings of all currency chest cash handling "
        "operations for a minimum period of ninety calendar days under circular 2014." + boilerplate
    )
    new_text = (
        "Entities shall maintain CCTV recordings of all currency chest cash handling "
        "operations for a minimum period of one hundred and eighty calendar days under circular 2026."
        + boilerplate
    )

    clean_chunks_old = chunk_document(old_text, lambda s: len(s) // 4)
    clean_chunks_new = chunk_document(new_text, lambda s: len(s) // 4)

    doc_id: Any = None
    try:
        # Ingest Version 1
        doc_v1 = SourceDocument(
            url=test_url,
            source="RBI",
            sha256=old_sha,
            content=old_text.encode("utf-8"),
            media_type="application/pdf",
            fetch_ts=datetime.now(UTC) - timedelta(days=30),
            http_status=200,
            detail_page=None,
            authority="Reserve Bank of India",
            is_injection_canary=False,
        )
        prep_v1 = PreparedDocument(
            document=doc_v1,
            text=old_text,
            char_count=len(old_text),
            clean_chars=len(old_text),
            pages=1,
            extractor="pypdf",
            chunks=clean_chunks_old,
            embeddings=np.array([_unit_embedding() for _ in clean_chunks_old]),
            embedding_model="test",
        )

        outcome_1 = store_document(app_conn, prep_v1)
        assert outcome_1.action == Action.INSERTED
        assert outcome_1.document_id is not None
        doc_id = outcome_1.document_id
        app_conn.commit()

        # Verify Version 1 is current
        v1_row = owner_conn.execute(
            "SELECT version_id, is_current FROM document_versions WHERE document_id = %s",
            (str(doc_id),),
        ).fetchone()
        assert v1_row is not None
        v1_id, v1_is_current = v1_row[0], v1_row[1]
        assert v1_is_current is True

        # Ingest Version 2 (amendment / supersession at same canonical URL)
        doc_v2 = SourceDocument(
            url=test_url,
            source="RBI",
            sha256=new_sha,
            content=new_text.encode("utf-8"),
            media_type="application/pdf",
            fetch_ts=datetime.now(UTC),
            http_status=200,
            detail_page=None,
            authority="Reserve Bank of India",
            is_injection_canary=False,
        )
        prep_v2 = PreparedDocument(
            document=doc_v2,
            text=new_text,
            char_count=len(new_text),
            clean_chars=len(new_text),
            pages=1,
            extractor="pypdf",
            chunks=clean_chunks_new,
            embeddings=np.array([_unit_embedding() for _ in clean_chunks_new]),
            embedding_model="test",
        )

        outcome_2 = store_document(app_conn, prep_v2)
        assert outcome_2.action == Action.SUPERSEDED
        assert outcome_2.document_id == doc_id
        app_conn.commit()

        # Verify database state after supersession:
        # 1. Version 1 is demoted to is_current = false
        # 2. Version 2 is inserted with is_current = true
        # 3. Old chunks are still in database (FR-4 retention guarantee)
        v_rows = owner_conn.execute(
            "SELECT version_id, sha256, is_current FROM document_versions WHERE document_id = %s ORDER BY created_at ASC",
            (str(doc_id),),
        ).fetchall()
        assert len(v_rows) == 2
        assert v_rows[0][0] == v1_id and v_rows[0][2] is False
        assert v_rows[1][1] == new_sha and v_rows[1][2] is True

        chunks_count = owner_conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = %s",
            (str(doc_id),),
        ).fetchone()
        assert chunks_count is not None
        assert chunks_count[0] == len(clean_chunks_old) + len(clean_chunks_new)

        # Test retrieval excludes superseded chunks
        retriever = Retriever(app_conn)
        config = RetrievalConfig(name="bm25-test", mode="bm25", k_dense=5, k_lexical=5, k_final=5)
        results = retriever.retrieve("CCTV recordings currency chest cash handling", config=config)

        retrieved_texts = [p.text for p in results]
        # Current text is retrievable
        assert any("one hundred and eighty calendar days" in t for t in retrieved_texts)
        # Superseded text is strictly not retrievable
        assert not any("ninety calendar days" in t for t in retrieved_texts)

    finally:
        # Clean up test rows and commit
        if doc_id is not None:
            owner_conn.execute("DELETE FROM chunks WHERE document_id = %s", (str(doc_id),))
            owner_conn.execute(
                "DELETE FROM document_versions WHERE document_id = %s", (str(doc_id),)
            )
            owner_conn.execute("DELETE FROM documents WHERE document_id = %s", (str(doc_id),))
            owner_conn.commit()


# --------------------------------------------------------------------------------------
# 4. Disaster recovery and re-embedding truncate procedure
# --------------------------------------------------------------------------------------
def test_documented_truncate_rebuild_procedure(
    owner_conn: psycopg.Connection[Any],
    app_conn: psycopg.Connection[Any],
) -> None:
    """Tests the exact TRUNCATE ... CASCADE procedure from README.md lines 530-545."""
    counts_before = row_counts(app_conn)
    assert counts_before["documents"] == 35
    assert counts_before["chunks"] == 230
    app_conn.rollback()

    # Execute TRUNCATE as owner and commit immediately
    owner_conn.execute("TRUNCATE chunks, document_versions, documents CASCADE")
    owner_conn.commit()

    counts_truncated = row_counts(app_conn)
    assert counts_truncated["documents"] == 0
    assert counts_truncated["chunks"] == 0
    app_conn.rollback()

    # Re-ingest corpus from manifest using the real production pipeline
    embedder = Embedder()
    docs = list(iter_manifest_documents(DEFAULT_MANIFEST))
    assert len(docs) == 35
    report = run_ingest(docs, app_conn, embedder)
    assert report.totals["failed"] == 0
    assert report.totals["chunks_written"] == 230
    app_conn.commit()

    # Verify FR-7 offsets roundtrip
    verification = verify_stored_chunks(docs, app_conn)
    assert verification.missing_versions == []
    assert verification.offset_mismatches == []

    # Verify row counts restored
    counts_after = row_counts(app_conn)
    assert counts_after["documents"] == 35
    assert counts_after["chunks"] == 230
    app_conn.commit()
