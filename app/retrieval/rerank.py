"""Cross-encoder candidate rerank ladder for fused candidates (FEAT-071).

What a reranker can and cannot do, stated first because it determines whether the latency
is worth paying. A reranker reorders a list it is given; it can never introduce a chunk
retrieval failed to return. On this corpus the serving configuration already reaches
recall@10 = 1.000 (ADR-0007), so a reranker cannot improve recall at depth 10 by
construction. Its entire possible contribution is at the top of the list, where recall@1
is 0.695 - that is the headroom, and that is what the ablation measures.

Why a cross-encoder rather than a second bi-encoder pass: the dense arm already embeds the
query and the passage independently, so a second independent embedding adds no information.
A cross-encoder reads query and passage together in one forward pass and can therefore
model term interaction - which is the only reason it is worth 100x the cost per pair.

Determinism matters here as much as anywhere else in this project. The model runs in
inference mode with a fixed batch size, and ties in the score are broken by the candidate's
pre-rerank position and then by chunk_id, so two runs of the same configuration produce
byte-identical ordering. A ranking that reshuffles between runs cannot support the 1pp
regression gate.

FEAT-071 introduces the Enterprise candidate rerank ladder:
- Clamped candidate pool size (max 64 candidates, default 50).
- Batched inference (batch size 16) with 512 token ceiling.
- Strict 40 ms timeout circuit breaker: trips on timeout or model exception, records
  metrics, and gracefully returns the pre-rerank RRF candidate ranking without disruption.
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from app.api.metrics import RERANK_CIRCUIT_BREAKER_TRIPS_TOTAL, RERANK_DURATION_SECONDS

if TYPE_CHECKING:  # pragma: no cover - import cost paid only when the reranker is used
    from sentence_transformers import CrossEncoder

logger = structlog.get_logger(__name__)

# The model named in ARCHITECTURE.md Section 3 and measured during Phase 0. Small on purpose: a
# 6-layer MiniLM is the largest cross-encoder that fits the latency budget on 2 vCPU.
MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Pairs scored per forward batch. 16 matched the per-pair cost of 32 in measurement while
# holding less memory, which matters on a 1.9 GiB host.
BATCH_SIZE = 16

# Hard cap on the tokens the cross-encoder reads per pair.
MAX_LENGTH = 512

# Maximum candidate pool size (FEAT-071)
MAX_POOL_SIZE = 64

# Default circuit breaker timeout in milliseconds
DEFAULT_TIMEOUT_MS = 40


class RerankError(RuntimeError):
    """The reranker could not produce a usable ordering."""


@dataclass(frozen=True)
class Candidate:
    """Minimal view of a retrieved chunk. Keeps this module independent of Retrieved."""

    chunk_id: str
    text: str


class CrossEncoderReranker:
    """Scores (query, passage) pairs and returns a new ordering with circuit breaker protection.

    Loaded lazily and intended to be constructed once per process: the weights take about
    eleven seconds to load, which would dominate any per-request measurement.
    """

    def __init__(
        self,
        model_id: str = MODEL_ID,
        *,
        batch_size: int = BATCH_SIZE,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.model_id = model_id
        self.batch_size = batch_size
        self.timeout_ms = timeout_ms
        self._model: CrossEncoder | None = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self.last_circuit_breaker_tripped: bool = False

    def _load(self) -> CrossEncoder:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_id, device="cpu", max_length=MAX_LENGTH)
        return self._model

    def warm(self) -> None:
        """Force the weights to load now.

        Called at server startup for the same reason the embedder is: a model that loads
        inside the first request makes that request's latency a measurement of disk I/O.
        """
        self._load().predict(
            [("warmup query", "warmup passage")],
            batch_size=1,
            show_progress_bar=False,
        )

    def score(
        self,
        query: str,
        candidates: list[Candidate],
        *,
        batch_size: int | None = None,
        **kwargs: Any,
    ) -> list[float]:
        """Relevance scores, one per candidate, in the order given."""
        if not candidates:
            return []
        effective_query = query.strip() if query else ""
        if not effective_query:
            raise ValueError("Query string cannot be empty for reranking")

        # Clamp pool size to maximum 64 per FEAT-071
        pool = candidates[:MAX_POOL_SIZE]
        effective_batch = batch_size if batch_size is not None else self.batch_size

        pairs = [(effective_query, candidate.text) for candidate in pool]
        raw = self._load().predict(pairs, batch_size=effective_batch, show_progress_bar=False)
        scores = [float(value) for value in raw]
        if len(scores) != len(pool):
            raise RerankError(f"reranker returned {len(scores)} scores for {len(pool)} candidates")
        return scores

    def _run_score(
        self,
        query: str,
        candidates: list[Candidate],
        batch_size: int,
    ) -> list[float]:
        """Helper to invoke score with batch_size fallback if subclass does not accept it."""
        try:
            return self.score(query, candidates, batch_size=batch_size)
        except TypeError:
            return self.score(query, candidates)

    def order(
        self,
        query: str,
        candidates: list[Candidate],
        *,
        batch_size: int | None = None,
        timeout_ms: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[int, float]]:
        """Return (original_index, score) sorted best first under circuit breaker protection.

        Returning indices rather than rebuilt objects keeps this module free of any
        dependency on the retrieval result type, and lets the caller carry through fields
        the reranker knows nothing about.

        Ties break on the original index and then chunk_id, ensuring 100% deterministic,
        reproducible ranking.

        If inference exceeds the timeout budget or encounters a model failure, the circuit
        breaker trips, increments docscout_rerank_circuit_breaker_trips_total, logs a
        warning, and returns the pre-rerank candidate ordering without query failure.
        """
        self.last_circuit_breaker_tripped = False
        if not candidates:
            return []
        effective_query = query.strip() if query else ""
        if not effective_query:
            raise ValueError("Query string cannot be empty for reranking")

        pool = candidates[:MAX_POOL_SIZE]
        effective_batch = batch_size if batch_size is not None else self.batch_size
        effective_timeout_ms = timeout_ms if timeout_ms is not None else self.timeout_ms
        timeout_sec = effective_timeout_ms / 1000.0

        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="reranker"
            )

        t0 = time.perf_counter()
        try:
            future = self._executor.submit(
                self._run_score,
                effective_query,
                pool,
                effective_batch,
            )
            scores = future.result(timeout=timeout_sec)
            elapsed = time.perf_counter() - t0
            RERANK_DURATION_SECONDS.observe(elapsed)

            indexed = [(idx, scores[idx], pool[idx].chunk_id) for idx in range(len(scores))]
            indexed.sort(key=lambda item: (-item[1], item[0], item[2]))
            return [(idx, score) for idx, score, _ in indexed]

        except concurrent.futures.TimeoutError:
            self.last_circuit_breaker_tripped = True
            RERANK_CIRCUIT_BREAKER_TRIPS_TOTAL.inc()
            elapsed = time.perf_counter() - t0
            RERANK_DURATION_SECONDS.observe(elapsed)
            logger.warning(
                "Cross-encoder rerank circuit breaker tripped: timeout exceeded",
                timeout_ms=effective_timeout_ms,
                elapsed_ms=round(elapsed * 1000.0, 2),
                candidate_count=len(pool),
                query_prefix=effective_query[:60],
            )
            return [(i, float(-i)) for i in range(len(pool))]

        except Exception as exc:
            self.last_circuit_breaker_tripped = True
            RERANK_CIRCUIT_BREAKER_TRIPS_TOTAL.inc()
            elapsed = time.perf_counter() - t0
            RERANK_DURATION_SECONDS.observe(elapsed)
            logger.warning(
                "Cross-encoder rerank circuit breaker tripped: model inference failure",
                error=str(exc),
                elapsed_ms=round(elapsed * 1000.0, 2),
                candidate_count=len(pool),
                query_prefix=effective_query[:60],
            )
            return [(i, float(-i)) for i in range(len(pool))]
