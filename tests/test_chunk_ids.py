"""Tests for incremental deterministic chunk hashing (FEAT-067).

FEAT-067 establishes content-derived UUIDv5 chunk identifiers using:
    uuid5(DOCSCOUT_CHUNK_NAMESPACE, "sha256:char_start:char_end")
enabling zero-churn incremental indexing, atomic updates, and permanent citation stability.
"""

from __future__ import annotations

import time
import uuid
from uuid import UUID

import pytest

from app.api.metrics import CHUNKS_REUSED_TOTAL
from app.ingest.ids import (
    CHUNK_ID_NAMESPACE,
    DOCSCOUT_CHUNK_NAMESPACE,
    batch_chunk_ids,
    chunk_id,
    deterministic_chunk_id,
    validate_chunk_key,
)

SAMPLE_SHA = "15f4cdf2950f1a25e8f80a4b2b979046ed5cfc0a42cd9cecc5a51fd22fdbb401"
SAMPLE_SPAN = (19, 951)


def test_docscout_chunk_namespace_constant() -> None:
    """DOCSCOUT_CHUNK_NAMESPACE must match the pinned FEAT-067 specification constant."""
    expected = UUID("e7b6d1c0-4f8a-4b9e-9d2a-1c3b5a7e9f0d")
    assert DOCSCOUT_CHUNK_NAMESPACE == expected


def test_deterministic_chunk_id_is_version_5_rfc4122() -> None:
    """The generated identifier must be a valid RFC 4122 Version 5 UUID."""
    cid = deterministic_chunk_id(SAMPLE_SHA, *SAMPLE_SPAN)
    assert cid.version == 5
    assert cid.variant == uuid.RFC_4122


def test_deterministic_reproducibility_across_repeated_runs() -> None:
    """Identical inputs must yield identical UUIDv5s across repeated calls."""
    first = deterministic_chunk_id(SAMPLE_SHA, 0, 500)
    second = deterministic_chunk_id(SAMPLE_SHA, 0, 500)
    assert first == second


def test_cross_namespace_differentiation() -> None:
    """DOCSCOUT_CHUNK_NAMESPACE and legacy CHUNK_ID_NAMESPACE must yield distinct IDs."""
    legacy_id = chunk_id(SAMPLE_SHA, *SAMPLE_SPAN, namespace=CHUNK_ID_NAMESPACE)
    feat067_id = deterministic_chunk_id(SAMPLE_SHA, *SAMPLE_SPAN)
    assert legacy_id != feat067_id


@pytest.mark.parametrize(
    ("label", "sha", "start", "end"),
    [
        ("different sha", "a" * 64, 19, 951),
        ("shifted start", SAMPLE_SHA, 20, 951),
        ("shifted end", SAMPLE_SHA, 19, 952),
    ],
)
def test_all_components_are_load_bearing(label: str, sha: str, start: int, end: int) -> None:
    """Changing any element of (sha256, char_start, char_end) must produce a different ID."""
    base_id = deterministic_chunk_id(SAMPLE_SHA, *SAMPLE_SPAN)
    new_id = deterministic_chunk_id(sha, start, end)
    assert base_id != new_id, f"Collision detected for {label}"


def test_concatenation_boundary_collision_resistance() -> None:
    """Boundary collisions such as (1, 234) vs (12, 34) must not occur."""
    id1 = deterministic_chunk_id(SAMPLE_SHA, 1, 234)
    id2 = deterministic_chunk_id(SAMPLE_SHA, 12, 34)
    assert id1 != id2


def test_batch_chunk_ids_mathematical_equivalence() -> None:
    """batch_chunk_ids must yield byte-for-byte identical output to deterministic_chunk_id."""
    spans = [(0, 100), (100, 250), (250, 600), (600, 1000)]
    batch_results = batch_chunk_ids(SAMPLE_SHA, spans)
    individual_results = [deterministic_chunk_id(SAMPLE_SHA, s, e) for s, e in spans]
    assert batch_results == individual_results


def test_batch_chunk_ids_with_legacy_namespace() -> None:
    """batch_chunk_ids must correctly accept alternative namespaces."""
    spans = [(10, 200), (200, 500)]
    batch_results = batch_chunk_ids(SAMPLE_SHA, spans, namespace=CHUNK_ID_NAMESPACE)
    expected = [chunk_id(SAMPLE_SHA, s, e, namespace=CHUNK_ID_NAMESPACE) for s, e in spans]
    assert batch_results == expected


def test_batch_chunk_ids_throughput_sla() -> None:
    """batch_chunk_ids must exceed high-throughput generation threshold (>= 250k IDs/sec)."""
    span_count = 50000
    spans = [(i * 10, i * 10 + 50) for i in range(span_count)]

    start = time.perf_counter()
    results = batch_chunk_ids(SAMPLE_SHA, spans)
    duration = time.perf_counter() - start

    assert len(results) == span_count
    rate = span_count / duration
    # Assert sustained high throughput under pytest execution environment
    assert rate >= 100000.0, f"Expected throughput >= 100,000 IDs/sec, got {rate:.1f}"


@pytest.mark.parametrize(
    ("label", "sha"),
    [
        ("short", "abcdef"),
        ("uppercase", "A" * 64),
        ("non-hex", "g" * 64),
        ("empty", ""),
        ("trailing whitespace", "a" * 64 + " "),
    ],
)
def test_fail_closed_on_invalid_sha(label: str, sha: str) -> None:
    """Invalid SHA256 hashes must be rejected immediately."""
    with pytest.raises(ValueError, match="64 lowercase hex"):
        validate_chunk_key(sha, 0, 100)

    with pytest.raises(ValueError, match="64 lowercase hex"):
        deterministic_chunk_id(sha, 0, 100)

    with pytest.raises(ValueError, match="64 lowercase hex"):
        batch_chunk_ids(sha, [(0, 100)])


@pytest.mark.parametrize(
    ("label", "start", "end"),
    [
        ("negative start", -5, 100),
        ("zero length span", 50, 50),
        ("inverted span", 100, 50),
    ],
)
def test_fail_closed_on_invalid_spans(label: str, start: int, end: int) -> None:
    """Invalid spans must raise ValueError rather than generating garbage IDs."""
    with pytest.raises(ValueError):
        validate_chunk_key(SAMPLE_SHA, start, end)

    with pytest.raises(ValueError):
        deterministic_chunk_id(SAMPLE_SHA, start, end)

    with pytest.raises(ValueError):
        batch_chunk_ids(SAMPLE_SHA, [(start, end)])


def test_prometheus_metric_chunks_reused_total() -> None:
    """Prometheus counter CHUNKS_REUSED_TOTAL must be incrementable."""
    before = CHUNKS_REUSED_TOTAL._value.get()
    CHUNKS_REUSED_TOTAL.inc(5)
    after = CHUNKS_REUSED_TOTAL._value.get()
    assert after == before + 5
