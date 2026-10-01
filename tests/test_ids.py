"""Tests for content-derived chunk identifiers (ADR-0005).

These tests exist because the failure mode is silent. A wrong namespace, a reordered key or a
changed separator all still produce well-formed UUIDs; nothing raises, nothing looks broken,
and every previously committed citation simply stops resolving. So the identifier is pinned
here by known answer, not merely by self-consistency: a test that only checks
`chunk_id(x) == chunk_id(x)` would pass under every one of those mistakes.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest

from app.ingest.ids import CHUNK_ID_NAMESPACE, chunk_id

# A real (sha256, span) drawn from the ingested corpus, so the frozen expectations below are
# not merely internally consistent but match what the pipeline actually stores.
SAMPLE_SHA = "15f4cdf2950f1a25e8f80a4b2b979046ed5cfc0a42cd9cecc5a51fd22fdbb401"
SAMPLE_SPAN = (19, 951)
SAMPLE_ID = UUID("3a2b3d9d-69ba-5bd9-a9cd-1b5bb17e588b")


def test_namespace_matches_its_documented_derivation() -> None:
    """The pinned namespace must equal the derivation its docstring claims.

    The first draft of ADR-0005 shipped a hand-typed constant that did not match the formula
    written directly above it. Nothing failed: identifiers were still stable, still unique,
    still well-formed. Only the documentation was a lie, and documentation is the only thing
    that makes an opaque constant auditable.
    """
    assert CHUNK_ID_NAMESPACE == uuid.uuid5(
        uuid.NAMESPACE_URL, "https://docscout.invalid/chunk-id/v1"
    )


def test_known_answer_is_frozen() -> None:
    """A real corpus chunk hashes to a fixed, committed identifier.

    This is the test that actually protects committed citations. Change the namespace, the key
    order, the separator or the UUID version and this fails, which is the whole point.
    """
    assert chunk_id(SAMPLE_SHA, *SAMPLE_SPAN) == SAMPLE_ID


def test_identifier_is_a_version_5_uuid() -> None:
    assert chunk_id(SAMPLE_SHA, *SAMPLE_SPAN).version == 5


def test_identical_inputs_give_identical_identifiers() -> None:
    assert chunk_id(SAMPLE_SHA, 0, 100) == chunk_id(SAMPLE_SHA, 0, 100)


@pytest.mark.parametrize(
    ("label", "sha", "span"),
    [
        ("a different document", "b" * 64, (19, 951)),
        ("a shifted start", SAMPLE_SHA, (20, 951)),
        ("a shifted end", SAMPLE_SHA, (19, 952)),
    ],
)
def test_every_component_of_the_key_changes_the_identifier(
    label: str, sha: str, span: tuple[int, int]
) -> None:
    """Each part of the key must be load-bearing, or it is not part of the identity."""
    assert chunk_id(sha, *span) != SAMPLE_ID, label


def test_span_boundaries_cannot_be_confused_by_concatenation() -> None:
    """Spans (1, 234) and (12, 34) must not collide.

    Both are valid half-open spans, and a key built by concatenating the numbers without a
    separator would render both as "1234" and hand two different chunks the same primary key.
    The separator is what prevents it, and this test is what keeps the separator.
    """
    assert chunk_id(SAMPLE_SHA, 1, 234) != chunk_id(SAMPLE_SHA, 12, 34)


@pytest.mark.parametrize(
    ("label", "sha"),
    [
        ("too short", "abc"),
        ("uppercase", "A" * 64),
        ("non-hex", "z" * 64),
        ("empty", ""),
        ("64 hex plus whitespace", "a" * 64 + "\n"),
    ],
)
def test_malformed_hashes_are_rejected(label: str, sha: str) -> None:
    """A bad hash must raise, not produce a plausible identifier pointing at nothing."""
    with pytest.raises(ValueError, match="64 lowercase hex"):
        chunk_id(sha, 0, 100)


@pytest.mark.parametrize(
    ("label", "start", "end"),
    [
        ("reversed span", 100, 50),
        ("empty span", 50, 50),
        ("negative start", -1, 100),
    ],
)
def test_malformed_spans_are_rejected(label: str, start: int, end: int) -> None:
    with pytest.raises(ValueError):
        chunk_id(SAMPLE_SHA, start, end)


def test_stored_chunk_ids_match_the_pure_function(ingest_db: object) -> None:
    """Every row in the live database must agree with `chunk_id` recomputed from its own key.

    The unit tests above prove the function is stable; this proves the *ingester* uses it. A
    pipeline that computed identifiers some other way — or that let a database default slip
    back in — would pass every test above and still break every committed citation.
    """
    conn = ingest_db
    rows = conn.execute(  # type: ignore[attr-defined]
        """
        SELECT v.sha256, c.char_start, c.char_end, c.chunk_id
          FROM chunks c JOIN document_versions v USING (version_id)
        """
    ).fetchall()
    if not rows:
        pytest.skip("no chunks stored; run `make ingest` first")

    mismatches = [
        (sha, start, end, stored)
        for sha, start, end, stored in rows
        if chunk_id(sha, start, end) != stored
    ]
    assert not mismatches, f"{len(mismatches)} of {len(rows)} stored chunk_ids are not derivable"


def test_the_database_offers_no_default_for_chunk_id(ingest_db: object) -> None:
    """Migration 0002 must leave `chunks.chunk_id` with no default.

    If a default comes back, forgetting to supply the identifier stops being an error and
    starts being a silently non-reproducible row (ADR-0005).
    """
    conn = ingest_db
    row = conn.execute(  # type: ignore[attr-defined]
        """
        SELECT column_default FROM information_schema.columns
         WHERE table_name = 'chunks' AND column_name = 'chunk_id'
        """
    ).fetchone()
    assert row is not None, "chunks.chunk_id not found in information_schema"
    assert row[0] is None, f"chunk_id has regained a default: {row[0]!r}"
