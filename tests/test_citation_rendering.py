"""Tests for human-readable citation rendering and document resolution (FR-14 / P1-5).

Verifies that retrieved passages carry authoritative regulator titles and publication
dates alongside stable chunk IDs and spans, and that GET /v1/documents/{id} resolves full
document metadata and lineage.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from app.ingest.source import iter_manifest_documents
from app.retrieval import SERVING_CONFIG, Retriever
from tests.conftest import auth

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_search_passages_contain_authoritative_title_and_published_date(
    client: TestClient,
) -> None:
    """Every passage returned by POST /v1/search must carry a title and published_date."""
    response = client.post(
        "/v1/search",
        json={"query": "What are the KYC requirements and periodic updation norms?"},
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()
    passages = data["passages"]
    assert len(passages) > 0

    for p in passages:
        assert p["title"] is not None
        assert isinstance(p["title"], str)
        assert len(p["title"]) > 5
        assert p["published_date"] is not None
        assert DATE_RE.match(p["published_date"])
        assert p["canonical_url"] is not None
        assert p["chunk_id"] is not None
        assert p["char_end"] > p["char_start"]


def test_citation_offsets_and_chunk_ids_remain_stable_s1(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """Existing chunk IDs, character spans and canonical URLs remain stable and accurate (S-1)."""
    response = client.post(
        "/v1/search",
        json={"query": "payment aggregator settlement window canary audit override"},
        headers=auth(),
    )
    assert response.status_code == 200
    passages = response.json()["passages"]
    canary_hits = [p for p in passages if p["canonical_url"] == "synthetic://canary-001"]
    assert len(canary_hits) > 0
    hit = canary_hits[0]

    assert (
        hit["title"] == "Settlement timelines for payment aggregators (synthetic canary document)"
    )
    assert hit["published_date"] == "2026-10-01"

    row = app_conn.execute(
        """
        SELECT c.char_start, c.char_end, c.text, d.title, d.published_date::text
          FROM chunks c
          JOIN documents d ON d.document_id = c.document_id
         WHERE c.chunk_id = %s::uuid
        """,
        (hit["chunk_id"],),
    ).fetchone()
    assert row is not None
    assert row[0] == hit["char_start"]
    assert row[1] == hit["char_end"]
    assert row[2] == hit["text"]
    assert row[3] == hit["title"]
    assert row[4] == hit["published_date"]


def test_get_document_endpoint_returns_200_with_full_metadata(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """GET /v1/documents/{document_id} resolves authoritative document metadata and version lineage."""
    doc_row = app_conn.execute(
        """
        SELECT document_id::text, canonical_url, source, authority, title, published_date::text
          FROM documents
         WHERE source = 'RBI' AND title IS NOT NULL
         LIMIT 1
        """
    ).fetchone()
    assert doc_row is not None
    doc_id, url, source, authority, title, pub_date = doc_row

    response = client.get(f"/v1/documents/{doc_id}", headers=auth())
    assert response.status_code == 200
    doc_data = response.json()

    assert doc_data["document_id"] == doc_id
    assert doc_data["canonical_url"] == url
    assert doc_data["source"] == source
    assert doc_data["authority"] == authority
    assert doc_data["title"] == title
    assert doc_data["published_date"] == pub_date
    assert doc_data["version_count"] >= 1
    assert doc_data["current_version_id"] is not None
    assert doc_data["chunk_count"] > 0
    assert doc_data["created_at"] is not None


def test_get_document_endpoint_requires_auth(client: TestClient) -> None:
    """GET /v1/documents/{document_id} rejects unauthenticated requests."""
    fake_id = str(uuid4())
    no_auth_res = client.get(f"/v1/documents/{fake_id}")
    assert no_auth_res.status_code == 401
    assert no_auth_res.headers["WWW-Authenticate"] == "X-API-Key"

    bad_auth_res = client.get(f"/v1/documents/{fake_id}", headers=auth("invalid-key"))
    assert bad_auth_res.status_code == 401


def test_get_document_endpoint_returns_404_on_unknown_or_invalid_id(
    client: TestClient,
) -> None:
    """GET /v1/documents/{document_id} returns 404 for nonexistent UUIDs and malformed IDs."""
    unknown_uuid = str(uuid4())
    res_unknown = client.get(f"/v1/documents/{unknown_uuid}", headers=auth())
    assert res_unknown.status_code == 404
    assert f"document {unknown_uuid} not found" in res_unknown.json()["detail"]

    res_invalid = client.get("/v1/documents/not-a-valid-uuid", headers=auth())
    assert res_invalid.status_code == 404
    assert "invalid UUID format" in res_invalid.json()["detail"]


def test_iter_manifest_documents_yields_titles_and_dates() -> None:
    """SourceDocument yielded from manifest iteration has title and date populated."""
    docs = list(iter_manifest_documents(limit=5))
    assert len(docs) == 5
    for doc in docs:
        assert doc.title is not None
        assert len(doc.title) > 0
        assert doc.published_date is not None


def test_retriever_populates_title_and_published_date(
    app_conn: psycopg.Connection[Any],
) -> None:
    """Retriever.retrieve directly populates title and published_date on Retrieved."""
    retriever = Retriever(app_conn)
    hits = retriever.retrieve("capital adequacy norms and risk weights", SERVING_CONFIG)
    assert len(hits) > 0
    for hit in hits:
        assert hit.title is not None
        assert hit.published_date is not None
        assert DATE_RE.match(hit.published_date)
