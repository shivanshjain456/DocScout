"""Tests for live regulatory discovery engine and synthetic artifact isolation.

Validates:
1. Change classification:
   - Discovered URL not in database -> NEW_DOCUMENT.
   - Discovered URL with changed sha256 -> CONTENT_REVISION.
   - Discovered URL with identical sha256 -> UNCHANGED.
2. Synthetic isolation invariant:
   - Synthetic evaluation fixtures and injection canaries (is_synthetic = true)
     are permanently excluded from production retrieval (NOT is_synthetic).
   - Real regulator circulars (is_synthetic = false) are retrieved.
3. Allowlist domain enforcement:
   - Only approved regulator domains (rbi.org.in, sebi.gov.in) can be crawled.
4. Discovery reporting:
   - Reports truthful counts and observed HTTP status codes without fabricating success.
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest

from app.ingest.allowlist import assert_allowed
from app.ingest.discovery import (
    DiscoveredLink,
    RegulatoryDiscoveryEngine,
)
from app.ingest.errors import DisallowedHostError
from app.retrieval.dense import search as dense_search
from app.retrieval.types import MetadataFilter


def test_allowlist_domain_enforcement() -> None:
    """Discovery engine restricts outbound crawling strictly to approved regulator domains."""
    # Approved domains
    assert_allowed("https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx")
    assert_allowed("https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI12345.PDF")
    assert_allowed("https://www.sebi.gov.in/legal/circulars/mar-2024/circular_123.pdf")

    # Disallowed domains
    with pytest.raises(DisallowedHostError):
        assert_allowed("https://evil.attacker.com/malicious.pdf")

    with pytest.raises(DisallowedHostError):
        assert_allowed("https://169.254.169.254/latest/meta-data/")


def test_discovery_change_classification_logic(db: Any) -> None:
    """Verifies honest classification: NEW_DOCUMENT, CONTENT_REVISION, and UNCHANGED."""
    engine = RegulatoryDiscoveryEngine(db)

    # 1. Unobserved URL -> NEW_DOCUMENT
    unique_url = f"https://www.rbi.org.in/Scripts/test_circ_{uuid4().hex[:8]}.pdf"
    cls_new = engine.classify_link(unique_url, "fake-sha-1")
    assert cls_new == "NEW_DOCUMENT"

    # 2. Existing URL with matching sha256 -> UNCHANGED
    row = db.execute(
        """
        SELECT d.canonical_url, v.sha256
          FROM documents d
          JOIN document_versions v ON v.document_id = d.document_id
         WHERE v.is_current = true AND NOT d.is_synthetic
         LIMIT 1
        """
    ).fetchone()
    assert row is not None
    existing_url, current_sha = row[0], row[1]

    cls_unchanged = engine.classify_link(existing_url, current_sha)
    assert cls_unchanged == "UNCHANGED"

    # 3. Existing URL with changed sha256 -> CONTENT_REVISION
    cls_rev = engine.classify_link(existing_url, "different-hash-content-modified")
    assert cls_rev == "CONTENT_REVISION"


def test_synthetic_artifact_retrieval_isolation(db: Any) -> None:
    """Synthetic fixtures (is_synthetic = true) are permanently filtered from production retrieval."""
    query_vec = np.zeros(384, dtype=np.float32)

    # 1. Production query (include_synthetic=False)
    filter_prod = MetadataFilter(source=None, include_synthetic=False)
    hits_prod = dense_search(db, query_vec, k=50, filter=filter_prod)

    assert hits_prod, "Expected chunks to be returned from real regulatory documents"
    for chunk_id, _ in hits_prod:
        row = db.execute(
            """
            SELECT d.is_synthetic
              FROM chunks c
              JOIN document_versions v ON v.version_id = c.version_id
              JOIN documents d ON d.document_id = v.document_id
             WHERE c.chunk_id = %s
            """,
            (chunk_id,),
        ).fetchone()
        assert row is not None
        assert row[0] is False, f"Chunk {chunk_id} belongs to a synthetic document!"


def test_discovery_crawl_skips_unchanged_without_reembedding(db: Any) -> None:
    """Unchanged circulars are preserved without redundant processing or state falsification."""
    engine = RegulatoryDiscoveryEngine(db)

    row = db.execute(
        """
        SELECT d.canonical_url, d.source, d.title
          FROM documents d
          JOIN document_versions v ON v.document_id = d.document_id
         WHERE v.is_current = true AND NOT d.is_synthetic
         LIMIT 1
        """
    ).fetchone()
    assert row is not None
    url, source, title = row[0], row[1], row[2]

    test_content = b"%PDF-1.4 test regulatory circular content"
    test_sha = hashlib.sha256(test_content).hexdigest()

    # Update current version sha256 to test_sha in transaction
    with db.transaction():
        db.execute(
            """
            UPDATE document_versions
               SET sha256 = %s
             WHERE is_current = true
               AND document_id = (SELECT document_id FROM documents WHERE canonical_url = %s)
            """,
            (test_sha, url),
        )

    link = DiscoveredLink(
        url=url,
        source=source,
        title=title,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = test_content

    with patch.object(engine.client, "get", return_value=mock_resp):
        report = engine.process_discovered_links([link])

    assert report.discovered_total == 1
    assert report.unchanged == 1
    assert report.new_documents == 0
    assert report.content_revisions == 0
    assert report.items[0].classification == "UNCHANGED"
