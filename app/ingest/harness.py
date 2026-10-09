"""Ingestion-scale harness — ADR-0023.

Production-grade ingestion scaling primitives for regulatory document corpora:
1. TokenBucketLimiter & DomainRateGovernor: Leaky/token bucket rate limiting with domain isolation
   (e.g. embedding API token limits vs regulator source HTTP fetch limits).
2. Adaptive shrink_retry: Handles 429s and token context ceilings via automatic bisection
   and jittered exponential backoff.
3. ChunkEmbeddingCache: Bounded in-memory LRU cache keyed by SHA-256 of (model_id, chunk_text)
   eliminating redundant embedding computation on unchanged chunks across corpus refreshes.
4. IngestionStateMachine: Checkpointed lifecycle tracking (QUEUED -> EXTRACTING -> CHUNKING ->
   EMBEDDING -> INDEXING -> COMPLETED/FAILED) with resumption from interrupted runs.
5. ConcurrentIngestionHarness: Multi-worker parallel ingestion preserving NFR-8 idempotency,
   measuring throughput (docs/sec, chunks/sec, tokens/sec) and latency percentiles.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
import psycopg
import structlog

from app.ingest.embed import EMBEDDING_DIM, Embedder
from app.ingest.errors import ExtractionError, ShortExtractionError
from app.ingest.pipeline import (
    DocumentResult,
    _result_from_outcome,
    chunk_source_document,
)
from app.ingest.scanner import ScanFinding, evaluate_scan_policy
from app.ingest.source import SourceDocument
from app.ingest.store import (
    Action,
    PreparedDocument,
    store_document,
    version_exists,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


# ======================================================================================
# 1. Rate Limiting & Domain Governor
# ======================================================================================


class TokenBucket:
    """Thread-safe token bucket rate limiter with burst capacity."""

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = max(0.001, float(rate))
        self.capacity = max(0.001, float(capacity if capacity is not None else rate))
        self.tokens = self.capacity
        self.last_update = time.perf_counter()
        self._lock = threading.RLock()

    def consume(self, amount: float = 1.0, wait: bool = True) -> float:
        """Consume `amount` tokens. If `wait` is True, sleeps until tokens are available.

        Returns the number of seconds waited.
        """
        if amount <= 0:
            return 0.0

        waited = 0.0
        while True:
            with self._lock:
                now = time.perf_counter()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

                # Expand capacity if a single batch request exceeds initial burst ceiling
                if amount > self.capacity:
                    self.capacity = amount

                if self.tokens >= amount:
                    self.tokens -= amount
                    return waited

                if not wait:
                    return -1.0

                deficit = amount - self.tokens
                sleep_needed = deficit / self.rate

            # Sleep outside the lock so other threads can evaluate progress
            time.sleep(sleep_needed)
            waited += sleep_needed

    @property
    def available(self) -> float:
        with self._lock:
            now = time.perf_counter()
            elapsed = now - self.last_update
            return min(self.capacity, self.tokens + elapsed * self.rate)


@dataclass
class DomainRateConfig:
    requests_per_second: float = 50.0
    tokens_per_second: float | None = 10_000.0
    request_burst: float | None = None
    token_burst: float | None = None


class DomainRateGovernor:
    """Manages isolated rate limiters across external service domains."""

    def __init__(self, configs: dict[str, DomainRateConfig] | None = None) -> None:
        self._lock = threading.RLock()
        self._configs: dict[str, DomainRateConfig] = configs or {}
        self._request_buckets: dict[str, TokenBucket] = {}
        self._token_buckets: dict[str, TokenBucket] = {}
        self._throttle_until: dict[str, float] = {}

        for domain, cfg in self._configs.items():
            self._init_domain(domain, cfg)

    def _init_domain(self, domain: str, cfg: DomainRateConfig) -> None:
        self._request_buckets[domain] = TokenBucket(
            rate=cfg.requests_per_second, capacity=cfg.request_burst or cfg.requests_per_second
        )
        if cfg.tokens_per_second is not None:
            self._token_buckets[domain] = TokenBucket(
                rate=cfg.tokens_per_second, capacity=cfg.token_burst or cfg.tokens_per_second
            )

    def configure_domain(self, domain: str, config: DomainRateConfig) -> None:
        with self._lock:
            self._configs[domain] = config
            self._init_domain(domain, config)

    def acquire(self, domain: str, requests: int = 1, tokens: int = 0, wait: bool = True) -> float:
        """Acquire requests and tokens for a domain.

        Returns total seconds waited.
        """
        with self._lock:
            if domain not in self._configs:
                self.configure_domain(domain, DomainRateConfig())
            req_bucket = self._request_buckets[domain]
            tok_bucket = self._token_buckets.get(domain)
            throttle_end = self._throttle_until.get(domain, 0.0)

        waited = 0.0
        now = time.perf_counter()
        if throttle_end > now:
            pause = throttle_end - now
            if wait:
                time.sleep(pause)
                waited += pause
            else:
                return -1.0

        r_wait = req_bucket.consume(float(requests), wait=wait)
        if r_wait < 0:
            return -1.0
        waited += r_wait

        if tok_bucket and tokens > 0:
            t_wait = tok_bucket.consume(float(tokens), wait=wait)
            if t_wait < 0:
                return -1.0
            waited += t_wait

        return waited

    def record_throttle(self, domain: str, backoff_seconds: float = 1.0) -> None:
        """Record upstream 429 throttle signal, enforcing domain pause."""
        with self._lock:
            self._throttle_until[domain] = time.perf_counter() + backoff_seconds
        logger.warning("harness.rate_governor_throttled", domain=domain, backoff_s=backoff_seconds)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {}
            for domain in self._configs:
                req_b = self._request_buckets[domain]
                tok_b = self._token_buckets.get(domain)
                out[domain] = {
                    "requests_available": round(req_b.available, 2),
                    "tokens_available": round(tok_b.available, 2) if tok_b else None,
                    "throttled": self._throttle_until.get(domain, 0.0) > time.perf_counter(),
                }
            return out


# ======================================================================================
# 2. Adaptive Shrink-Retry Mechanism
# ======================================================================================


def is_default_retryable_error(exc: Exception) -> bool:
    """Classify 429s and token context length / batch size ceiling errors."""
    msg = str(exc).lower()
    return any(
        signal in msg
        for signal in (
            "429",
            "too many requests",
            "rate limit",
            "context length",
            "maximum sequence length",
            "batch size too large",
            "payload too large",
            "413",
            "out of memory",
            "oom",
        )
    )


def shrink_retry[T, R](
    items: Sequence[T],
    func: Callable[[list[T]], list[R]],
    *,
    max_retries: int = 5,
    initial_backoff: float = 0.05,
    backoff_factor: float = 2.0,
    jitter: float = 0.05,
    is_retryable_error: Callable[[Exception], bool] | None = None,
    on_shrink: Callable[[int, int], None] | None = None,
) -> list[R]:
    """Execute batch function with automatic bisection and exponential jitter backoff.

    If `func(items)` fails with a retryable error and len(items) > 1, bisects into
    two halves, recursively processing each. When len(items) == 1, retries with backoff.
    """
    if not items:
        return []

    item_list = list(items)
    retryable_fn = is_retryable_error or is_default_retryable_error

    try:
        return func(item_list)
    except Exception as exc:
        if not retryable_fn(exc):
            raise

        if len(item_list) > 1:
            mid = len(item_list) // 2
            if on_shrink:
                on_shrink(len(item_list), mid)
            logger.info("harness.shrink_retry_bisection", total=len(item_list), left=mid)
            if jitter > 0:
                time.sleep(random.uniform(0, jitter))  # noqa: S311

            left_res = shrink_retry(
                item_list[:mid],
                func,
                max_retries=max_retries,
                initial_backoff=initial_backoff,
                backoff_factor=backoff_factor,
                jitter=jitter,
                is_retryable_error=retryable_fn,
                on_shrink=on_shrink,
            )
            right_res = shrink_retry(
                item_list[mid:],
                func,
                max_retries=max_retries,
                initial_backoff=initial_backoff,
                backoff_factor=backoff_factor,
                jitter=jitter,
                is_retryable_error=retryable_fn,
                on_shrink=on_shrink,
            )
            return left_res + right_res

        # len(items) == 1: single item retry loop
        last_exc: Exception = exc
        for attempt in range(max_retries):
            delay = (initial_backoff * (backoff_factor**attempt)) + random.uniform(0, jitter)  # noqa: S311
            time.sleep(delay)
            try:
                return func(item_list)
            except Exception as single_exc:
                if not retryable_fn(single_exc):
                    raise
                last_exc = single_exc
        raise last_exc from exc


# ======================================================================================
# 3. Bounded LRU Chunk Embedding Cache
# ======================================================================================


class ChunkEmbeddingCache:
    """Thread-safe bounded in-memory LRU cache for passage chunk embeddings."""

    def __init__(self, capacity: int = 10_000) -> None:
        self.capacity = max(1, capacity)
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @staticmethod
    def _make_key(model_id: str, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{model_id}:{digest}"

    def get(self, model_id: str, text: str) -> np.ndarray | None:
        key = self._make_key(model_id, text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self.hits += 1
                return self._cache[key]
            self.misses += 1
            return None

    def get_batch(
        self, model_id: str, texts: list[str]
    ) -> tuple[dict[int, np.ndarray], list[int], list[str]]:
        """Look up multiple texts.

        Returns (cached_vectors_by_index, missing_indices, missing_texts).
        """
        cached: dict[int, np.ndarray] = {}
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        with self._lock:
            for idx, text in enumerate(texts):
                key = self._make_key(model_id, text)
                if key in self._cache:
                    self._cache.move_to_end(key)
                    self.hits += 1
                    cached[idx] = self._cache[key]
                else:
                    self.misses += 1
                    missing_indices.append(idx)
                    missing_texts.append(text)

        return cached, missing_indices, missing_texts

    def put_batch(self, model_id: str, texts: list[str], vectors: np.ndarray) -> None:
        """Store computed vectors in LRU cache."""
        with self._lock:
            for text, vector in zip(texts, vectors, strict=True):
                key = self._make_key(model_id, text)
                if key in self._cache:
                    self._cache.move_to_end(key)
                    self._cache[key] = vector
                else:
                    if len(self._cache) >= self.capacity:
                        self._cache.popitem(last=False)
                        self.evictions += 1
                    self._cache[key] = vector

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            ratio = (self.hits / total) if total > 0 else 0.0
            return {
                "capacity": self.capacity,
                "size": len(self._cache),
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "hit_ratio": round(ratio, 4),
            }


class CachedEmbedder(Embedder):
    """Wraps an Embedder with ChunkEmbeddingCache, rate governor, and adaptive shrink-retry."""

    def __init__(
        self,
        base_embedder: Embedder,
        cache: ChunkEmbeddingCache | None = None,
        governor: DomainRateGovernor | None = None,
    ) -> None:
        super().__init__(model_id=base_embedder.model_id, batch_size=base_embedder.batch_size)
        self.base_embedder = base_embedder
        self.cache = cache or ChunkEmbeddingCache()
        self.governor = governor
        self.shrink_events = 0

    def count_tokens(self, text: str) -> int:
        return self.base_embedder.count_tokens(text)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        cached_dict, missing_indices, missing_texts = self.cache.get_batch(self.model_id, texts)

        if not missing_texts:
            # 100% cache hit
            return np.vstack([cached_dict[i] for i in range(len(texts))])

        # Acquire token/request budget if rate governor is present
        if self.governor:
            est_tokens = sum(max(1, len(t) // 4) for t in missing_texts)
            self.governor.acquire("embedding", requests=1, tokens=est_tokens, wait=True)

        def _on_shrink(old_sz: int, new_sz: int) -> None:
            self.shrink_events += 1

        def _encode_batch(batch: list[str]) -> list[np.ndarray]:
            res = self.base_embedder.encode_passages(batch)
            return [res[i] for i in range(len(batch))]

        new_vectors_list = shrink_retry(
            missing_texts,
            _encode_batch,
            max_retries=4,
            on_shrink=_on_shrink,
        )
        new_vectors = np.asarray(new_vectors_list, dtype=np.float32)

        # Populate cache with newly computed embeddings
        self.cache.put_batch(self.model_id, missing_texts, new_vectors)

        # Merge cached and new into final array in original order
        for idx, vec in zip(missing_indices, new_vectors, strict=True):
            cached_dict[idx] = vec

        return np.vstack([cached_dict[i] for i in range(len(texts))])

    def encode_query(self, text: str) -> np.ndarray:
        # Search queries do not hit passage LRU cache
        return self.base_embedder.encode_query(text)


# ======================================================================================
# 4. Ingestion Task State Machine & Resumption
# ======================================================================================


class TaskState(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    QUARANTINED = "quarantined"
    FAILED = "failed"


@dataclass
class TaskRecord:
    task_id: str
    url: str
    sha256: str
    state: TaskState = TaskState.QUEUED
    action: str | None = None
    chunks_count: int = 0
    clean_chars: int = 0
    error: str | None = None
    stage_timings_ms: dict[str, int] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class IngestionStateMachine:
    """Manages document task states with checkpointing and recovery."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()

    def register(self, url: str, sha256: str) -> TaskRecord:
        task_id = hashlib.sha256(f"{url}:{sha256}".encode()).hexdigest()[:16]
        with self._lock:
            rec = TaskRecord(task_id=task_id, url=url, sha256=sha256)
            self._tasks[task_id] = rec
            return rec

    def transition(
        self,
        task_id: str,
        state: TaskState,
        *,
        action: str | None = None,
        chunks_count: int | None = None,
        clean_chars: int | None = None,
        error: str | None = None,
        stage_name: str | None = None,
        stage_ms: int | None = None,
    ) -> None:
        with self._lock:
            rec = self._tasks[task_id]
            rec.state = state
            if action is not None:
                rec.action = action
            if chunks_count is not None:
                rec.chunks_count = chunks_count
            if clean_chars is not None:
                rec.clean_chars = clean_chars
            if error is not None:
                rec.error = error
            if stage_name and stage_ms is not None:
                rec.stage_timings_ms[stage_name] = stage_ms
            rec.updated_at = datetime.now(UTC).isoformat()

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def export_checkpoint(self) -> dict[str, Any]:
        with self._lock:
            return {
                "checkpointed_at": datetime.now(UTC).isoformat(),
                "tasks": {tid: asdict(rec) for tid, rec in self._tasks.items()},
            }

    def save_checkpoint(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.export_checkpoint(), indent=2), encoding="utf-8")

    def load_checkpoint(self, data: dict[str, Any]) -> None:
        with self._lock:
            tasks_data = data.get("tasks", {})
            for tid, raw in tasks_data.items():
                self._tasks[tid] = TaskRecord(
                    task_id=raw["task_id"],
                    url=raw["url"],
                    sha256=raw["sha256"],
                    state=TaskState(raw["state"]),
                    action=raw.get("action"),
                    chunks_count=raw.get("chunks_count", 0),
                    clean_chars=raw.get("clean_chars", 0),
                    error=raw.get("error"),
                    stage_timings_ms=raw.get("stage_timings_ms", {}),
                    updated_at=raw.get("updated_at", datetime.now(UTC).isoformat()),
                )

    def load_checkpoint_file(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.load_checkpoint(data)

    def resumable_tasks(self) -> list[TaskRecord]:
        with self._lock:
            return [
                rec
                for rec in self._tasks.values()
                if rec.state not in {TaskState.COMPLETED, TaskState.SKIPPED, TaskState.QUARANTINED}
            ]


# ======================================================================================
# 5. Concurrent Ingestion Harness & Telemetry
# ======================================================================================


@dataclass
class HarnessTelemetry:
    total_documents: int
    completed: int
    skipped: int
    quarantined: int
    failed: int
    total_chunks: int
    total_tokens: int
    cache_hits: int
    cache_misses: int
    cache_hit_ratio: float
    batch_shrink_events: int
    duration_seconds: float
    docs_per_second: float
    chunks_per_second: float
    tokens_per_second: float
    p50_latency_ms: float
    p95_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_documents": self.total_documents,
            "completed": self.completed,
            "skipped": self.skipped,
            "quarantined": self.quarantined,
            "failed": self.failed,
            "total_chunks": self.total_chunks,
            "total_tokens": self.total_tokens,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_ratio": self.cache_hit_ratio,
            "batch_shrink_events": self.batch_shrink_events,
            "duration_seconds": round(self.duration_seconds, 3),
            "docs_per_second": round(self.docs_per_second, 2),
            "chunks_per_second": round(self.chunks_per_second, 2),
            "tokens_per_second": round(self.tokens_per_second, 2),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
        }


class ConcurrentIngestionHarness:
    """Scalable ingestion harness coordinating concurrency, caching, and back-pressure."""

    def __init__(
        self,
        concurrency: int = 4,
        *,
        governor: DomainRateGovernor | None = None,
        cache: ChunkEmbeddingCache | None = None,
        state_machine: IngestionStateMachine | None = None,
    ) -> None:
        self.concurrency = max(1, concurrency)
        self.governor = governor or DomainRateGovernor()
        self.cache = cache or ChunkEmbeddingCache()
        self.state_machine = state_machine or IngestionStateMachine()

    def process_single_document(
        self,
        document: SourceDocument,
        embedder: CachedEmbedder,
        conn: psycopg.Connection[Any] | None,
        *,
        dry_run: bool = False,
    ) -> DocumentResult:
        """Process one document through the staged harness pipeline."""
        t_start = time.perf_counter()
        task = self.state_machine.register(document.url, document.sha256)

        # Stage 1: NFR-8 fast-path check against Postgres
        if conn is not None and version_exists(conn, document.sha256):
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            self.state_machine.transition(
                task.task_id,
                TaskState.SKIPPED,
                action=str(Action.SKIPPED_UNCHANGED),
                stage_name="check_hash",
                stage_ms=elapsed_ms,
            )
            return DocumentResult(
                url=document.url,
                source=document.source,
                status="ok",
                action=str(Action.SKIPPED_UNCHANGED),
                elapsed_ms=elapsed_ms,
                detail="content hash already stored; no work performed",
            )

        # Stage 2: Extract & Chunk
        t_extract = time.perf_counter()
        self.state_machine.transition(task.task_id, TaskState.EXTRACTING)
        try:
            cut = chunk_source_document(document, embedder.count_tokens)
        except (ExtractionError, ShortExtractionError) as exc:
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            self.state_machine.transition(
                task.task_id,
                TaskState.FAILED,
                error=str(exc),
                stage_name="extract",
                stage_ms=elapsed_ms,
            )
            return DocumentResult(
                url=document.url,
                source=document.source,
                status="failed",
                elapsed_ms=elapsed_ms,
                detail=f"{type(exc).__name__}: {exc}",
            )

        extract_ms = int((time.perf_counter() - t_extract) * 1000)
        self.state_machine.transition(
            task.task_id,
            TaskState.CHUNKING,
            clean_chars=cut.clean_chars,
            stage_name="extract_and_chunk",
            stage_ms=extract_ms,
        )

        # Stage 3: Guard / Quarantine check
        scan_objects = [
            ScanFinding(
                category=f["category"],
                rule_id=f["rule_id"],
                description=f["description"],
                char_start=f["char_start"],
                char_end=f["char_end"],
                sample_masked=f["sample_masked"],
                severity=f["severity"],
                detail=f.get("detail", ""),
            )
            for f in cut.secret_findings + cut.pii_findings
        ]
        _, is_quarantined = evaluate_scan_policy(scan_objects)
        if is_quarantined:
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            self.state_machine.transition(
                task.task_id,
                TaskState.QUARANTINED,
                action=str(Action.QUARANTINED),
                stage_name="scan",
                stage_ms=elapsed_ms,
            )
            return DocumentResult(
                url=document.url,
                source=document.source,
                status="quarantined",
                action=str(Action.QUARANTINED),
                chunks=0,
                char_count=len(cut.text),
                clean_chars=cut.clean_chars,
                pages=cut.pages,
                extractor=cut.extractor,
                secret_findings=cut.secret_findings,
                pii_findings=cut.pii_findings,
                elapsed_ms=elapsed_ms,
                detail=f"quarantined by policy: {len(cut.secret_findings)} secret findings",
            )

        # Stage 4: Embed via CachedEmbedder
        t_embed = time.perf_counter()
        self.state_machine.transition(task.task_id, TaskState.EMBEDDING)
        chunk_texts = [c.text for c in cut.chunks]
        embeddings = embedder.encode_passages(chunk_texts)
        embed_ms = int((time.perf_counter() - t_embed) * 1000)
        self.state_machine.transition(
            task.task_id,
            TaskState.INDEXING,
            chunks_count=len(cut.chunks),
            stage_name="embed",
            stage_ms=embed_ms,
        )

        prepared = PreparedDocument(
            document=document,
            text=cut.text,
            char_count=len(cut.text),
            clean_chars=cut.clean_chars,
            invisible_removed=cut.invisible_removed,
            pages=cut.pages,
            extractor=cut.extractor,
            chunks=cut.chunks,
            embeddings=embeddings,
            embedding_model=embedder.model_id,
            secret_findings=cut.secret_findings,
            pii_findings=cut.pii_findings,
        )

        # Stage 5: Store / Indexing
        t_index = time.perf_counter()
        if dry_run or conn is None:
            tokens = [c.token_count for c in prepared.chunks]
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            self.state_machine.transition(
                task.task_id,
                TaskState.COMPLETED,
                action="dry_run",
                stage_name="index",
                stage_ms=int((time.perf_counter() - t_index) * 1000),
            )
            return DocumentResult(
                url=document.url,
                source=document.source,
                status="ok",
                action="dry_run",
                chunks=len(prepared.chunks),
                char_count=prepared.char_count,
                clean_chars=prepared.clean_chars,
                pages=prepared.pages,
                extractor=prepared.extractor,
                token_min=min(tokens) if tokens else 0,
                token_mean=round(sum(tokens) / len(tokens), 1) if tokens else 0.0,
                token_max=max(tokens) if tokens else 0,
                invisible_removed=prepared.invisible_removed,
                secret_findings=prepared.secret_findings,
                pii_findings=prepared.pii_findings,
                elapsed_ms=elapsed_ms,
                detail="dry run: nothing written",
            )

        outcome = store_document(conn, prepared)
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        self.state_machine.transition(
            task.task_id,
            TaskState.COMPLETED,
            action=str(outcome.action),
            stage_name="index",
            stage_ms=int((time.perf_counter() - t_index) * 1000),
        )
        return _result_from_outcome(document, prepared, outcome, elapsed_ms)

    def run(
        self,
        documents: Sequence[SourceDocument],
        embedder: Embedder,
        conn_or_factory: psycopg.Connection[Any]
        | Callable[[], psycopg.Connection[Any]]
        | None = None,
        *,
        dry_run: bool = False,
    ) -> tuple[list[DocumentResult], HarnessTelemetry]:
        """Execute parallel ingestion across documents."""
        from concurrent.futures import ThreadPoolExecutor

        cached_embedder = (
            embedder
            if isinstance(embedder, CachedEmbedder)
            else CachedEmbedder(embedder, cache=self.cache, governor=self.governor)
        )

        results: list[DocumentResult] = []
        latencies_ms: list[int] = []
        t0 = time.perf_counter()

        def _worker(doc: SourceDocument) -> DocumentResult:
            # Handle connection lifecycle per worker
            c: psycopg.Connection[Any] | None = None
            should_close = False
            if callable(conn_or_factory):
                c = conn_or_factory()
                should_close = True
            elif isinstance(conn_or_factory, psycopg.Connection):
                c = conn_or_factory

            try:
                res = self.process_single_document(doc, cached_embedder, c, dry_run=dry_run)
                return res
            finally:
                if should_close and c is not None:
                    c.close()

        if self.concurrency == 1:
            for doc in documents:
                r = _worker(doc)
                results.append(r)
                latencies_ms.append(r.elapsed_ms)
        else:
            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                for r in executor.map(_worker, documents):
                    results.append(r)
                    latencies_ms.append(r.elapsed_ms)

        duration = max(0.001, time.perf_counter() - t0)
        c_stats = self.cache.stats()

        total_chunks = sum(r.chunks for r in results)
        total_tokens = sum(
            int(r.token_mean * r.chunks) for r in results if r.token_mean and r.chunks
        )
        completed = sum(
            1 for r in results if r.status == "ok" and r.action != str(Action.SKIPPED_UNCHANGED)
        )
        skipped = sum(1 for r in results if r.action == str(Action.SKIPPED_UNCHANGED))
        quarantined = sum(1 for r in results if r.status == "quarantined")
        failed = sum(1 for r in results if r.status == "failed")

        latencies_sorted = sorted(latencies_ms) if latencies_ms else [0]
        p50 = float(latencies_sorted[len(latencies_sorted) // 2])
        p95_idx = min(len(latencies_sorted) - 1, int(len(latencies_sorted) * 0.95))
        p95 = float(latencies_sorted[p95_idx])

        telemetry = HarnessTelemetry(
            total_documents=len(documents),
            completed=completed,
            skipped=skipped,
            quarantined=quarantined,
            failed=failed,
            total_chunks=total_chunks,
            total_tokens=total_tokens,
            cache_hits=c_stats["hits"],
            cache_misses=c_stats["misses"],
            cache_hit_ratio=c_stats["hit_ratio"],
            batch_shrink_events=cached_embedder.shrink_events,
            duration_seconds=duration,
            docs_per_second=len(documents) / duration,
            chunks_per_second=total_chunks / duration,
            tokens_per_second=total_tokens / duration,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
        )

        return results, telemetry
