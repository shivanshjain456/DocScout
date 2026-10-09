"""Integration tests for P0-5: Cache invalidation on supersession & liveness/readiness split.

Verifies:
1. When a document version is superseded (Action.SUPERSEDED), in-memory result caches
   are immediately purged and generation counter is incremented.
2. Subsequent queries never return passages from superseded versions (version.is_current = false).
3. BM25 term index reloads to index new content and drop superseded content.
4. GET /healthz (liveness probe) never performs DB I/O and returns 200 even under DB failure.
5. GET /readyz (readiness probe) validates pool connection and chunks, returning 503 on DB failure.
6. POST /v1/admin/cache/invalidate clears cache and reloads indices on operator request.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.security import load_keys
from app.config import database_url
from app.ingest.embed import Embedder
from app.ingest.pipeline import prepare_document
from app.ingest.source import SourceDocument
from app.ingest.store import Action, store_document
from app.ingest.store import connect as connect_store


@pytest.fixture
def auth_headers() -> dict[str, str]:
    keys = load_keys()
    first_key = next(iter(keys))
    return {"X-API-Key": first_key}


@pytest.fixture
def db_conn() -> Generator[psycopg.Connection[Any], None, None]:
    conn = connect_store(database_url())
    try:
        yield conn
    finally:
        conn.close()


def test_cache_invalidation_on_supersession_lifecycle(
    client: TestClient,
    auth_headers: dict[str, str],
    db_conn: psycopg.Connection[Any],
    owner_conn: psycopg.Connection[Any],
) -> None:
    """A superseded document version must immediately purge result_cache and never serve stale chunks."""
    # 1. Choose an existing document to supersede
    row = db_conn.execute(
        """
        SELECT d.document_id, d.canonical_url, d.source, d.authority, d.detail_page,
               v.version_id, v.sha256
          FROM documents d
          JOIN document_versions v ON d.document_id = v.document_id
         WHERE v.is_current
         LIMIT 1
        """
    ).fetchone()
    assert row is not None, "Corpus must have at least one current document"

    doc_id, url, source, authority, detail_page, orig_v_id, _ = (
        row[0],
        str(row[1]),
        str(row[2]),
        str(row[3]),
        row[4],
        row[5],
        str(row[6]),
    )

    query = "What is the regulatory framework and operational requirement?"

    # 2. Query 1: Cold search (cache miss)
    resp1 = client.post(
        "/v1/search",
        json={"query": query, "mode": "hybrid", "k": 5, "use_cache": True},
        headers=auth_headers,
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["timings"]["cache_hit"] is False
    gen1 = data1["provenance"]["corpus_generation"]

    # 3. Query 2: Warm search (cache hit)
    resp2 = client.post(
        "/v1/search",
        json={"query": query, "mode": "hybrid", "k": 5, "use_cache": True},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["timings"]["cache_hit"] is True
    assert data2["provenance"]["corpus_generation"] == gen1

    # 4. Now supersede the document with an amended version containing distinct text
    unique_suffix = uuid.uuid4().hex
    amended_text = (
        f"AMENDMENT CIRCULAR {unique_suffix}: Comprehensive regulatory framework update.\n"
        "All regulated entities must maintain an aggregate liquidity buffer of sixty percent.\n"
        "Special terms: zebrabuffercushion supersedes previous norms. " * 8
    )
    amended_bytes = amended_text.encode("utf-8")
    amended_sha = hashlib.sha256(amended_bytes).hexdigest()

    amended_source_doc = SourceDocument(
        url=url,
        source=source,
        sha256=amended_sha,
        content=amended_bytes,
        media_type="text/plain",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=detail_page,
        authority=authority,
        is_injection_canary=False,
    )

    embedder = Embedder()
    prepared = prepare_document(amended_source_doc, embedder)

    new_v_id: Any = None
    try:
        # Store superseding version
        outcome = store_document(db_conn, prepared)
        assert outcome.action == Action.SUPERSEDED
        new_v_id = outcome.version_id

        # Verify database state: old version is demoted, new version is current
        v_check = db_conn.execute(
            """
            SELECT version_id, is_current
              FROM document_versions
             WHERE document_id = %s
             ORDER BY is_current DESC
            """,
            (doc_id,),
        ).fetchall()
        assert len(v_check) >= 2
        current_versions = [v[0] for v in v_check if v[1] is True]
        assert current_versions == [new_v_id], "Only the new version must be current"

        # 5. Query 3: Immediate search after supersession
        # Cache must have been purged: cache_hit must be False, generation must have incremented
        resp3 = client.post(
            "/v1/search",
            json={"query": query, "mode": "hybrid", "k": 5, "use_cache": True},
            headers=auth_headers,
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["timings"]["cache_hit"] is False, (
            "Cache must be invalidated immediately upon supersession"
        )
        assert data3["provenance"]["corpus_generation"] > gen1

        # Assert no returned passage belongs to the demoted version
        for passage in data3["passages"]:
            pass_v = db_conn.execute(
                "SELECT version_id FROM chunks WHERE chunk_id = %s",
                (passage["chunk_id"],),
            ).fetchone()
            if pass_v is not None:
                assert pass_v[0] != orig_v_id, (
                    f"Chunk {passage['chunk_id']} from superseded version was served!"
                )

        # 6. BM25 search for the unique amendment term "zebrabuffercushion"
        resp_bm25 = client.post(
            "/v1/search",
            json={"query": "zebrabuffercushion", "mode": "bm25", "k": 3, "use_cache": True},
            headers=auth_headers,
        )
        assert resp_bm25.status_code == 200
        bm25_data = resp_bm25.json()
        assert len(bm25_data["passages"]) > 0
        assert "zebrabuffercushion" in bm25_data["passages"][0]["text"]

    finally:
        # Teardown: Clean up amended version using owner connection (with DELETE privilege)
        if new_v_id is not None:
            owner_conn.execute("DELETE FROM chunks WHERE version_id = %s", (new_v_id,))
            owner_conn.execute("DELETE FROM document_versions WHERE version_id = %s", (new_v_id,))
            owner_conn.commit()
        owner_conn.execute(
            "UPDATE document_versions SET is_current = true WHERE version_id = %s",
            (orig_v_id,),
        )
        owner_conn.commit()
        # Invalidate app cache after cleanup
        client.post(
            "/v1/admin/cache/invalidate",
            json={"reason": "test_cleanup"},
            headers=auth_headers,
        )


def test_liveness_healthz_vs_readiness_readyz_split(
    client: TestClient,
) -> None:
    """GET /healthz is a pure liveness probe (no DB I/O); GET /readyz validates DB pool."""
    # 1. Normal state: both healthy
    health_res = client.get("/healthz")
    assert health_res.status_code == 200
    health_data = health_res.json()
    assert health_data["status"] == "ok"
    assert health_data["model_loaded"] is True
    assert health_data["uptime_seconds"] >= 0.0
    assert health_data["corpus_generation"] >= 1

    ready_res = client.get("/readyz")
    assert ready_res.status_code == 200
    ready_data = ready_res.json()
    assert ready_data["status"] == "ok"
    assert ready_data["database"] is True
    assert ready_data["corpus_chunks"] > 0
    assert ready_data["bm25_ready"] is True

    # 2. Simulate downstream database outage by mocking connection pool
    mock_pool = MagicMock()
    mock_pool.connection.side_effect = psycopg.OperationalError("connection refused to db:5432")

    orig_pool = app.state.pool
    app.state.pool = mock_pool
    try:
        # Liveness probe MUST stay 200 OK (pod must NOT be killed/restarted)
        live_res = client.get("/healthz")
        assert live_res.status_code == 200
        assert live_res.json()["status"] == "ok"

        # Readiness probe MUST return 503 SERVICE UNAVAILABLE (traffic blocked)
        unready_res = client.get("/readyz")
        assert unready_res.status_code == 503
        unready_data = unready_res.json()
        assert unready_data["status"] == "unready"
        assert unready_data["database"] is False
    finally:
        app.state.pool = orig_pool

    # After restoration, readiness recovers to 200 OK
    recovered_res = client.get("/readyz")
    assert recovered_res.status_code == 200
    assert recovered_res.json()["status"] == "ok"


def test_admin_cache_invalidate_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /v1/admin/cache/invalidate clears cached queries and increments generation."""
    # 1. Populate cache with a search query
    query = "What is the requirement for payment aggregators escrow accounts?"
    client.post(
        "/v1/search",
        json={"query": query, "mode": "hybrid", "k": 5, "use_cache": True},
        headers=auth_headers,
    )

    # 2. Check unauthenticated rejection
    unauth = client.post("/v1/admin/cache/invalidate", json={"reason": "ops_check"})
    assert unauth.status_code == 401

    # 3. Authenticated invalidation call
    inv_res = client.post(
        "/v1/admin/cache/invalidate",
        json={"reason": "scheduled_cron"},
        headers=auth_headers,
    )
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert inv_data["status"] == "ok"
    assert inv_data["entries_cleared"] >= 1
    assert inv_data["new_generation"] > inv_data["previous_generation"]
    assert inv_data["corpus_chunks"] > 0

    # 4. Same query is now a cache miss
    subsequent = client.post(
        "/v1/search",
        json={"query": query, "mode": "hybrid", "k": 5, "use_cache": True},
        headers=auth_headers,
    )
    assert subsequent.status_code == 200
    assert subsequent.json()["timings"]["cache_hit"] is False


def test_inflight_request_skips_caching_if_generation_moves(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-flight request started before invalidation must not poison the cache afterwards."""
    query = "What are the rules regarding liquidity risk management?"

    # Clear cache first
    client.post("/v1/admin/cache/invalidate", json={"reason": "pre_test"}, headers=auth_headers)

    # Monkeypatch encode_query so that while the query is in flight, generation moves
    orig_encode = app.state.embedder.encode_query

    def interrupting_encode(q: str) -> Any:
        app.state.corpus_generation += 1
        return orig_encode(q)

    monkeypatch.setattr(app.state.embedder, "encode_query", interrupting_encode)

    # Execute search
    res = client.post(
        "/v1/search",
        json={"query": query, "mode": "dense", "k": 5, "use_cache": True},
        headers=auth_headers,
    )
    assert res.status_code == 200

    # Ensure the entry was NOT saved into cache because generation moved
    cache_key = (query, "dense", 5, False)
    assert app.state.result_cache.get(cache_key) is None
