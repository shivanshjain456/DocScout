"""Tests for Ingestion-Scale Harness — ADR-0023.

Verifies:
1. TokenBucketLimiter & DomainRateGovernor: burst, steady replenishment, domain isolation.
2. Adaptive shrink_retry: automatic batch bisection on batch ceiling, backoff on 429, fatal error handling.
3. ChunkEmbeddingCache & CachedEmbedder: LRU eviction, exact vector caching, hit/miss telemetry.
4. IngestionStateMachine: lifecycle transitions, state serialization, checkpoint resumption.
5. ConcurrentIngestionHarness: multi-worker execution (1, 4, 8), telemetry calculation, and NFR-8 idempotency.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.ingest.embed import EMBEDDING_DIM, Embedder
from app.ingest.harness import (
    CachedEmbedder,
    ChunkEmbeddingCache,
    ConcurrentIngestionHarness,
    DomainRateConfig,
    DomainRateGovernor,
    IngestionStateMachine,
    TaskState,
    TokenBucket,
    shrink_retry,
)
from app.ingest.source import SourceDocument

# --------------------------------------------------------------------------------------
# Helpers & Stubs
# --------------------------------------------------------------------------------------


class StubEmbedder(Embedder):
    """Deterministic fast embedder for harness tests."""

    def __init__(self) -> None:
        super().__init__(model_id="stub-embedder-384")
        self.call_count = 0

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        self.call_count += 1
        out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            out[row] = vector / np.linalg.norm(vector)
        return out


def make_synthetic_doc(idx: int, text: str | None = None) -> SourceDocument:
    body = text or (
        f"Reserve Bank of India regulatory circular doc-{idx} on capital adequacy and risk weights. "
        * 30
    )
    content = body.encode("utf-8")
    return SourceDocument(
        url=f"https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx?Id={9000 + idx}",
        source="RBI",
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        media_type="text/plain",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=None,
        authority="Reserve Bank of India",
        is_injection_canary=False,
    )


# --------------------------------------------------------------------------------------
# 1. Rate Limiting & Domain Governor
# --------------------------------------------------------------------------------------


def test_token_bucket_consumption_and_burst() -> None:
    bucket = TokenBucket(rate=10.0, capacity=5.0)
    assert bucket.available == pytest.approx(5.0, abs=0.1)

    # Immediate consumption of burst
    waited = bucket.consume(3.0, wait=False)
    assert waited == 0.0
    assert bucket.available == pytest.approx(2.0, abs=0.1)

    # Non-blocking refusal when asking for more than remaining
    refused = bucket.consume(10.0, wait=False)
    assert refused == -1.0


def test_domain_rate_governor_isolation() -> None:
    governor = DomainRateGovernor(
        {
            "fast_domain": DomainRateConfig(requests_per_second=100.0),
            "slow_domain": DomainRateConfig(requests_per_second=1.0, request_burst=1.0),
        }
    )

    # Slow domain consumes its 1 token
    w1 = governor.acquire("slow_domain", requests=1, wait=False)
    assert w1 == 0.0

    # Slow domain is now empty (non-blocking returns -1)
    w2 = governor.acquire("slow_domain", requests=1, wait=False)
    assert w2 == -1.0

    # Fast domain is completely unaffected
    w3 = governor.acquire("fast_domain", requests=1, wait=False)
    assert w3 == 0.0

    # Test throttle signal on slow domain
    governor.record_throttle("slow_domain", backoff_seconds=0.1)
    stats = governor.stats()
    assert stats["slow_domain"]["throttled"] is True
    assert stats["fast_domain"]["throttled"] is False


# --------------------------------------------------------------------------------------
# 2. Adaptive Shrink-Retry
# --------------------------------------------------------------------------------------


def test_shrink_retry_bisection_on_batch_ceiling() -> None:
    call_log: list[int] = []
    shrink_events: list[tuple[int, int]] = []

    def mock_batch_worker(batch: list[str]) -> list[str]:
        call_log.append(len(batch))
        if len(batch) > 4:
            raise RuntimeError("batch size too large: maximum allowed batch is 4")
        return [f"processed:{item}" for item in batch]

    items = [f"item_{i}" for i in range(10)]
    results = shrink_retry(
        items,
        mock_batch_worker,
        on_shrink=lambda old, new: shrink_events.append((old, new)),
        jitter=0.001,
    )

    assert len(results) == 10
    assert results == [f"processed:item_{i}" for i in range(10)]
    # Initial batch size 10 was split: 10 -> (5, 5) -> (2, 3), etc.
    assert len(shrink_events) >= 1
    assert max(call_log) <= 10
    # Every accepted batch was <= 4
    accepted_batches = [sz for sz in call_log if sz <= 4]
    assert sum(accepted_batches) == 10


def test_shrink_retry_backoff_on_429() -> None:
    attempts = 0

    def flaky_service(batch: list[str]) -> list[str]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("HTTP 429 Too Many Requests: rate limit exceeded")
        return [f"ok:{batch[0]}"]

    res = shrink_retry(
        ["single_item"],
        flaky_service,
        max_retries=4,
        initial_backoff=0.01,
        jitter=0.001,
    )
    assert res == ["ok:single_item"]
    assert attempts == 3


def test_shrink_retry_raises_non_retryable_error() -> None:
    def broken_service(batch: list[str]) -> list[str]:
        raise ValueError("Invalid unicode characters in payload")

    with pytest.raises(ValueError, match="Invalid unicode"):
        shrink_retry(["test"], broken_service)


# --------------------------------------------------------------------------------------
# 3. Chunk Embedding Cache & Cached Embedder
# --------------------------------------------------------------------------------------


def test_chunk_embedding_cache_lru_and_stats() -> None:
    cache = ChunkEmbeddingCache(capacity=3)
    model = "test-model"

    vec1 = np.ones(EMBEDDING_DIM, dtype=np.float32)
    vec2 = np.ones(EMBEDDING_DIM, dtype=np.float32) * 2
    vec3 = np.ones(EMBEDDING_DIM, dtype=np.float32) * 3
    vec4 = np.ones(EMBEDDING_DIM, dtype=np.float32) * 4

    cache.put_batch(model, ["c1", "c2", "c3"], np.vstack([vec1, vec2, vec3]))
    assert cache.stats()["size"] == 3
    assert cache.stats()["evictions"] == 0

    # Cache hit on c1 (moves c1 to MRU)
    res_c1 = cache.get(model, "c1")
    assert res_c1 is not None
    assert np.array_equal(res_c1, vec1)

    # Insert c4 -> should evict LRU (c2, because c1 was accessed)
    cache.put_batch(model, ["c4"], np.vstack([vec4]))
    assert cache.stats()["size"] == 3
    assert cache.stats()["evictions"] == 1

    assert cache.get(model, "c2") is None  # evicted
    assert cache.get(model, "c1") is not None  # preserved
    assert cache.get(model, "c3") is not None  # preserved
    assert cache.get(model, "c4") is not None  # preserved


def test_cached_embedder_eliminates_redundant_calls() -> None:
    base = StubEmbedder()
    cache = ChunkEmbeddingCache(capacity=100)
    cached_embedder = CachedEmbedder(base, cache=cache)

    passages = [
        "Paragraph A on Basel III",
        "Paragraph B on Tier 1 capital",
        "Paragraph C on Net Stable Funding",
    ]

    # First pass: cold cache
    out1 = cached_embedder.encode_passages(passages)
    assert base.call_count == 1
    assert cache.stats()["hits"] == 0
    assert cache.stats()["misses"] == 3

    # Second pass: identical passages -> 100% cache hit, 0 additional calls to base
    out2 = cached_embedder.encode_passages(passages)
    assert base.call_count == 1
    assert cache.stats()["hits"] == 3
    assert np.allclose(out1, out2)

    # Mixed pass: 2 cached + 1 new
    mixed = [
        "Paragraph A on Basel III",
        "Brand new paragraph D",
        "Paragraph C on Net Stable Funding",
    ]
    out3 = cached_embedder.encode_passages(mixed)
    assert base.call_count == 2
    assert cache.stats()["hits"] == 5
    assert cache.stats()["misses"] == 4
    assert np.allclose(out3[0], out1[0])
    assert np.allclose(out3[2], out1[2])


# --------------------------------------------------------------------------------------
# 4. Ingestion Task State Machine & Checkpoints
# --------------------------------------------------------------------------------------


def test_state_machine_checkpoint_and_resume(tmp_path: Path) -> None:
    sm = IngestionStateMachine()

    task1 = sm.register("https://rbi.org.in/doc1", "sha_111")
    task2 = sm.register("https://rbi.org.in/doc2", "sha_222")

    sm.transition(task1.task_id, TaskState.CHUNKING, clean_chars=1200)
    sm.transition(
        task1.task_id, TaskState.COMPLETED, chunks_count=5, stage_name="index", stage_ms=45
    )

    sm.transition(task2.task_id, TaskState.EXTRACTING)
    sm.transition(task2.task_id, TaskState.FAILED, error="ShortExtractionError: 12 chars")

    ckpt_path = tmp_path / "checkpoint.json"
    sm.save_checkpoint(ckpt_path)
    assert ckpt_path.is_file()

    # Create fresh state machine and reload
    sm_restored = IngestionStateMachine()
    sm_restored.load_checkpoint_file(ckpt_path)

    t1_restored = sm_restored.get_task(task1.task_id)
    assert t1_restored is not None
    assert t1_restored.state == TaskState.COMPLETED
    assert t1_restored.chunks_count == 5
    assert t1_restored.stage_timings_ms.get("index") == 45

    t2_restored = sm_restored.get_task(task2.task_id)
    assert t2_restored is not None
    assert t2_restored.state == TaskState.FAILED
    assert "ShortExtractionError" in (t2_restored.error or "")

    # Resumables include only non-terminal / failed tasks
    resumable = sm_restored.resumable_tasks()
    assert len(resumable) == 1
    assert resumable[0].task_id == task2.task_id


# --------------------------------------------------------------------------------------
# 5. Concurrent Ingestion Harness & Telemetry
# --------------------------------------------------------------------------------------


def test_concurrent_harness_multi_worker_dry_run() -> None:
    docs = [make_synthetic_doc(i) for i in range(12)]
    embedder = StubEmbedder()

    harness = ConcurrentIngestionHarness(concurrency=4)
    results, telemetry = harness.run(docs, embedder, dry_run=True)

    assert len(results) == 12
    assert all(r.status == "ok" for r in results)
    assert telemetry.total_documents == 12
    assert telemetry.completed == 12
    assert telemetry.failed == 0
    assert telemetry.docs_per_second > 0.0
    assert telemetry.chunks_per_second > 0.0
    assert telemetry.p50_latency_ms >= 0.0
    assert telemetry.p95_latency_ms >= 0.0


def test_concurrent_harness_idempotency_nfr8(ingest_db: Any) -> None:
    """NFR-8 invariant: identical document content is skipped on second pass."""
    doc = make_synthetic_doc(42)
    embedder = StubEmbedder()

    harness = ConcurrentIngestionHarness(concurrency=1)

    # First run: writes to database
    res1, tel1 = harness.run([doc], embedder, conn_or_factory=ingest_db, dry_run=False)
    assert len(res1) == 1
    assert res1[0].status == "ok"
    assert res1[0].action in {"inserted", "superseded"}
    assert tel1.completed == 1
    assert tel1.skipped == 0

    # Second run: must hit NFR-8 fast-path and skip unchanged
    res2, tel2 = harness.run([doc], embedder, conn_or_factory=ingest_db, dry_run=False)
    assert len(res2) == 1
    assert res2[0].status == "ok"
    assert res2[0].action == "skipped_unchanged"
    assert tel2.completed == 0
    assert tel2.skipped == 1
