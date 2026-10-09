"""The DocScout serving API.

Scope, stated up front because the omission is deliberate: this serves **retrieval with
citations**, not generated answers. There is no LLM in the request path and no API keys to
call one (U-1). An endpoint that returned prose here would have to invent it, and inventing
prose over regulatory text is the single failure this project is built to measure and
avoid. What it returns instead is the evidence — ranked passages with resolvable chunk ids
and character spans — which is exactly what the eval harness measures, so every number in
the README describes this endpoint rather than a different code path.

Three things are load-bearing in the design:

* **Everything expensive loads once, at startup.** The embedding model takes ~13 s and the
  BM25 term table needs a full scan of `chunks`. Doing either per request would make the
  published p95 a measurement of initialisation. The lifespan handler pays both costs
  before the first request is accepted.
* **The database is reached through a pool.** FastAPI runs synchronous handlers in a worker
  thread pool, so a single shared `psycopg` connection would be used concurrently by
  several threads, which is not safe. One connection per request, returned on completion.
* **Failure is closed and quiet.** Missing auth configuration stops startup. Unexpected
  errors return a generic message with a correlation id; the detail goes to the log, not to
  the caller, because this runs on a public URL.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from psycopg_pool import ConnectionPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import demo, metrics
from app.api.audit import RetrievalAuditRecord, hash_query, record_retrieval_event
from app.api.cache import (
    DEFAULT_RESULT_TTL_SECONDS,
    TTLCache,
    register_invalidation_listener,
    trigger_corpus_invalidation,
    unregister_invalidation_listener,
)
from app.api.models import (
    CacheInvalidateRequest,
    CacheInvalidateResponse,
    Confidence,
    LivenessResponse,
    Passage,
    Provenance,
    ReadinessResponse,
    SearchRequest,
    SearchResponse,
    Timings,
)
from app.api.security import RATE_LIMIT_REQUESTS, load_keys, require_api_key
from app.config import database_url, sha256_file, staleness_budget_hours
from app.generate import GeneratedAnswer, get_generator
from app.ingest.chunk import CHUNK_OVERLAP, CHUNK_SIZE
from app.ingest.embed import EMBEDDING_DIM, MODEL_ID, Embedder
from app.ingest.store import get_sync_state
from app.observability import configure_logging, get_logger, normalise_request_id
from app.retrieval import SERVING_CONFIG, RetrievalConfig
from app.retrieval import Retriever as Retriever
from app.retrieval.lexical import BM25Index
from app.rowtypes import as_int

logger = get_logger("docscout.api")

REPO_ROOT = Path(__file__).resolve().parents[2]

# Bounded so memory is predictable on a 1.9 GiB host. 512 cached responses of at most 20
# passages is a few MB; the embedding cache is 512 float32 vectors of 384 dims, under 1 MB.
RESULT_CACHE_SIZE = 512
EMBEDDING_CACHE_SIZE = 512


@dataclass(frozen=True)
class CachedResult:
    """What the result cache stores: the parts of a response that do not vary per request.

    Typed rather than a dict so the cache cannot drift out of step with the response model.
    Timings are deliberately excluded -- they describe the request that is being served, and
    replaying a previous request's latency would be a fabricated measurement.
    """

    passages: list[Passage]
    confidence: Confidence
    provenance: Provenance
    answer: GeneratedAnswer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Pay every fixed cost before the first request is served."""
    configure_logging()
    app.state.started_at = time.monotonic()
    app.state.corpus_generation = 1
    app.state.bm25_needs_reload = False
    app.state.bm25_lock = Lock()
    metrics.CORPUS_GENERATION.set(1)

    app.state.api_keys = load_keys()  # raises, by design, if none are configured

    app.state.pool = ConnectionPool(
        database_url(),
        min_size=1,
        # Four is chosen against the hardware, not plucked: 2 vCPU means more than a
        # handful of concurrent retrievals queue on CPU anyway, and each idle connection
        # costs backend memory on a 1.9 GiB box.
        max_size=4,
        open=True,
        timeout=10.0,
    )

    embedder = Embedder()
    # Force the weights to load now. Encoding one throwaway string is the only honest way
    # to do it: the model is lazy and would otherwise load inside the first request.
    embedder.encode_query("warmup")
    app.state.embedder = embedder

    with app.state.pool.connection() as conn:
        app.state.bm25 = BM25Index(conn)
        row = conn.execute("SELECT count(*) FROM chunks").fetchone()
        app.state.corpus_chunks = as_int(row[0]) if row else 0

    app.state.result_cache = TTLCache[tuple[str, str, int, bool], CachedResult](
        maxsize=RESULT_CACHE_SIZE, ttl=DEFAULT_RESULT_TTL_SECONDS
    )
    app.state.embedding_cache = TTLCache[str, Any](maxsize=EMBEDDING_CACHE_SIZE, ttl=None)
    app.state.manifest_digest = sha256_file(REPO_ROOT / "corpus" / "raw" / "manifest.json")
    app.state.generator = get_generator()

    metrics.CORPUS_CHUNKS.set(app.state.corpus_chunks)

    def _on_corpus_invalidated(reason: str | None = None) -> None:
        cleared = len(app.state.result_cache)
        app.state.result_cache.clear()
        app.state.corpus_generation += 1
        app.state.bm25_needs_reload = True
        metrics.CORPUS_GENERATION.set(app.state.corpus_generation)
        metrics.CACHE_INVALIDATIONS.labels(reason or "unknown").inc()
        logger.info(
            "cache.invalidated",
            reason=reason,
            generation=app.state.corpus_generation,
            cleared_entries=cleared,
        )

    register_invalidation_listener(_on_corpus_invalidated)

    logger.info(
        "api.ready",
        corpus_chunks=app.state.corpus_chunks,
        corpus_generation=app.state.corpus_generation,
        embedding_model=MODEL_ID,
        api_keys=len(app.state.api_keys),
        rate_limit_per_minute=RATE_LIMIT_REQUESTS,
    )
    try:
        yield
    finally:
        unregister_invalidation_listener(_on_corpus_invalidated)
        app.state.pool.close()


app = FastAPI(
    title="DocScout",
    version="0.1.0",
    summary="Citation-grounded retrieval over RBI and SEBI regulatory circulars.",
    description=(
        "Returns the evidence, not a generated answer. Every passage carries a stable "
        "chunk id and character span so a citation can be checked against the source."
    ),
    lifespan=lifespan,
    # The interactive docs are the cheapest possible demo surface and leak nothing: the
    # schema is public, the data is public, and every data route is key-gated.
    docs_url="/docs",
    redoc_url=None,
)


@app.middleware("http")
async def correlate_and_log(request: Request, call_next: Any) -> Any:
    """Bind a correlation id for the request and emit exactly one access line.

    The id is bound into a contextvar rather than passed around, so every log record
    emitted anywhere while handling this request carries it without the call sites
    knowing. It is echoed on the response so a caller reporting a bad answer can quote
    something that joins to the logs.

    One line per request, after the fact, with the status and duration on it -- rather
    than a line on entry and another on exit, which doubles log volume and still needs a
    join to answer "how long did it take".
    """
    request_id = normalise_request_id(request.headers.get("X-Request-ID"))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id, method=request.method, path=request.url.path
    )
    request.state.request_id = request_id
    started = time.perf_counter()
    metrics.IN_FLIGHT.inc()
    try:
        try:
            response = await call_next(request)
        except Exception:
            # The 500 handler below renders the body; this records the timing and the
            # metric, then re-raises so that behaviour is unchanged.
            elapsed = time.perf_counter() - started
            # Routing has run by now, so the matched template is available even on failure.
            route = metrics.route_label(request.scope)
            metrics.REQUESTS.labels(request.method, route, "500").inc()
            metrics.REQUEST_DURATION.labels(request.method, route).observe(elapsed)
            logger.exception("http.request", status=500, duration_ms=round(elapsed * 1000, 2))
            raise
        elapsed = time.perf_counter() - started
        route = metrics.route_label(request.scope)
        metrics.REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        metrics.REQUEST_DURATION.labels(request.method, route).observe(elapsed)
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            metrics.RATE_LIMITED.inc()
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http.request", status=response.status_code, duration_ms=round(elapsed * 1000, 2)
        )
        return response
    finally:
        metrics.IN_FLIGHT.dec()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Uniform error bodies, with auth headers preserved."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 with the field problems, but without echoing the submitted values.

    Pydantic's default body includes `input`, which would reflect caller data straight back
    into a response and into any log that records it. The field and the rule are enough to
    fix a request.
    """
    problems = [
        {"field": ".".join(str(p) for p in err["loc"][1:]), "problem": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "invalid request", "problems": problems},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internals to a public URL; log them with a correlation id instead."""
    # Reuse the request's correlation id when the middleware set one, so the reference a
    # caller is given is the same string that appears in every log line for that request.
    correlation = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
    logger.exception("http.unhandled", correlation=correlation, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"internal error (reference {correlation})"},
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    """A self-contained demo page. No external assets, so it renders in a sandboxed frame."""
    return HTMLResponse(demo.PAGE)


@app.get("/metrics", include_in_schema=False, tags=["ops"])
def prometheus_metrics() -> Response:
    """Prometheus exposition for the default registry.

    Unauthenticated, for the same reason `/healthz` is: the thing that needs it most is a
    scraper, and many cannot present a credential. It exposes aggregate counters only --
    no query text, no key fingerprints, no request ids -- so the disclosure is request
    volume and latency shape. On a public URL that is still information; a real deployment
    should bind this to an internal interface or firewall the path, which is the standard
    posture and is recorded in the README rather than left implicit.
    """
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.get("/healthz", response_model=LivenessResponse, tags=["ops"])
def healthz(request: Request) -> LivenessResponse:
    """Process liveness probe for orchestrators and balancers, unauthenticated.

    Reflects only internal process health and event loop responsiveness.
    Executes NO database or network I/O, ensuring that downstream database blips,
    migrations, or network hiccups never induce cascading pod restart loops.
    """
    state = request.app.state
    uptime = max(0.0, time.monotonic() - getattr(state, "started_at", time.monotonic()))
    return LivenessResponse(
        status="ok",
        uptime_seconds=round(uptime, 2),
        model_loaded=getattr(state, "embedder", None) is not None,
        single_process=True,
        corpus_generation=getattr(state, "corpus_generation", 1),
    )


@app.get(
    "/readyz",
    response_model=ReadinessResponse,
    tags=["ops"],
    responses={
        200: {"description": "Service is ready to serve traffic (ok or degraded/stale)"},
        503: {"description": "Service is unready (database unreachable or empty corpus)"},
    },
)
def readyz(request: Request, response: Response) -> ReadinessResponse:
    """Traffic readiness probe for load balancers and mesh routers, unauthenticated.

    Verifies pooled database connectivity, chunk count (> 0), embedding and lexical
    index readiness, and freshness budget status. Returns HTTP 503 if downstream
    dependencies prevent serving query traffic.
    """
    state = request.app.state
    database_ok = True
    chunks = 0
    sync_state = None
    bm25_ready = False

    try:
        with state.pool.connection() as conn:
            # Check if BM25 index needs reload
            if getattr(state, "bm25_needs_reload", False) is True:
                with getattr(state, "bm25_lock", Lock()):
                    if getattr(state, "bm25_needs_reload", False) is True:
                        state.bm25 = BM25Index(conn)
                        row = conn.execute("SELECT count(*) FROM chunks").fetchone()
                        state.corpus_chunks = as_int(row[0]) if row else 0
                        metrics.CORPUS_CHUNKS.set(state.corpus_chunks)
                        state.bm25_needs_reload = False

            row = conn.execute("SELECT count(*) FROM chunks").fetchone()
            chunks = as_int(row[0]) if row else 0
            state.corpus_chunks = chunks
            metrics.CORPUS_CHUNKS.set(chunks)
            sync_state = get_sync_state(conn)
            bm25_ready = getattr(state, "bm25", None) is not None
    except Exception:  # noqa: BLE001 - probe must report, never crash
        logger.warning("readyz.database_probe_failed", exc_info=True)
        database_ok = False

    # Check for external sync updates
    if sync_state is not None:
        if getattr(state, "last_seen_sync_updated_at", None) is None:
            state.last_seen_sync_updated_at = sync_state.updated_at
        elif sync_state.updated_at > state.last_seen_sync_updated_at:
            state.last_seen_sync_updated_at = sync_state.updated_at
            trigger_corpus_invalidation("external_sync_detected")

    budget = staleness_budget_hours()
    last_checked_at: datetime | None = None
    stale_hours: float | None = None
    is_stale = False

    if sync_state is not None:
        last_checked_at = sync_state.last_checked_at
        if last_checked_at.tzinfo is None:
            last_checked_at = last_checked_at.replace(tzinfo=UTC)
        stale_hours = max(0.0, (datetime.now(UTC) - last_checked_at).total_seconds() / 3600.0)
        is_stale = stale_hours > budget

        # Update Prometheus operational freshness gauges
        metrics.CORPUS_LAST_CHECKED.set(last_checked_at.timestamp())
        metrics.CORPUS_STALE_HOURS.set(stale_hours)
        metrics.CORPUS_STALENESS_BUDGET_HOURS.set(budget)
        metrics.CORPUS_IS_STALE.set(1.0 if is_stale else 0.0)
        metrics.CORPUS_VERSIONS_CURRENT.set(sync_state.documents_current)
        metrics.CORPUS_VERSIONS_SUPERSEDED.set(sync_state.documents_superseded)

    model_loaded = getattr(state, "embedder", None) is not None
    is_ready = database_ok and chunks > 0 and model_loaded and bm25_ready

    ready_status: Literal["ok", "degraded", "unready"]
    if not is_ready:
        ready_status = "unready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif is_stale:
        ready_status = "degraded"
        response.status_code = status.HTTP_200_OK
    else:
        ready_status = "ok"
        response.status_code = status.HTTP_200_OK

    return ReadinessResponse(
        status=ready_status,
        database=database_ok,
        corpus_chunks=chunks,
        embedding_model=MODEL_ID,
        model_loaded=model_loaded,
        bm25_ready=bm25_ready,
        cache={
            **state.result_cache.stats.as_dict(),
            "entries": len(state.result_cache),
        },
        rate_limit_per_minute=RATE_LIMIT_REQUESTS,
        single_process=True,
        corpus_generation=getattr(state, "corpus_generation", 1),
        last_checked_at=last_checked_at,
        stale_hours=round(stale_hours, 2) if stale_hours is not None else None,
        staleness_budget_hours=budget,
        is_stale=is_stale,
    )


def _config_for(payload: SearchRequest) -> RetrievalConfig:
    """Build the retrieval configuration, keeping the serving default authoritative."""
    if payload.mode == "hybrid":
        return RetrievalConfig(
            name=SERVING_CONFIG.name,
            mode="hybrid",
            k_dense=SERVING_CONFIG.k_dense,
            k_lexical=SERVING_CONFIG.k_lexical,
            k_final=payload.k,
            rrf_k=SERVING_CONFIG.rrf_k,
            anchor_arm_top1=SERVING_CONFIG.anchor_arm_top1,
            filter=payload.filter,
            expand_query=payload.expand_query,
            expansion_mode=payload.expansion_mode,
        )
    # Single-arm modes are the documented ADR-0006 ablation, reachable so the A/B can be
    # reproduced against the running service.
    return RetrievalConfig(
        name=f"{payload.mode}-only",
        mode=payload.mode,
        k_dense=SERVING_CONFIG.k_dense,
        k_lexical=SERVING_CONFIG.k_lexical,
        k_final=payload.k,
        filter=payload.filter,
        expand_query=payload.expand_query,
        expansion_mode=payload.expansion_mode,
    )


@app.post(
    "/v1/search",
    response_model=SearchResponse,
    tags=["search"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request"},
        429: {"description": "rate limit exceeded"},
    },
)
def search(
    payload: SearchRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> SearchResponse:
    """Retrieve the passages that answer a question, with checkable citations,
    and optional citation-grounded answer generation sitting behind them."""
    started = time.perf_counter()
    state = request.app.state
    req_generation = getattr(state, "corpus_generation", 1)
    filter_key = payload.filter.canonical_tuple() if payload.filter else None
    cache_key = (
        payload.query,
        payload.mode,
        payload.k,
        payload.generate_answer,
        filter_key,
        payload.expand_query,
        payload.expansion_mode,
    )

    cached: CachedResult | None = state.result_cache.get(cache_key) if payload.use_cache else None
    if cached is not None:
        metrics.CACHE_EVENTS.labels("hit").inc()
        total_ms = (time.perf_counter() - started) * 1000.0
        try:
            record_retrieval_event(
                getattr(state, "pool", None),
                RetrievalAuditRecord(
                    key_fingerprint=fingerprint,
                    query_hash=hash_query(payload.query),
                    mode=payload.mode,
                    k=payload.k,
                    returned_chunk_ids=[p.chunk_id for p in cached.passages],
                    latency_ms=total_ms,
                    cache_hit=True,
                    has_generated_answer=cached.answer is not None,
                    corpus_generation=req_generation,
                ),
            )
        except Exception:  # noqa: BLE001 - audit failure must never break search
            logger.warning("search.audit_event_failed", exc_info=True)
        logger.info(
            "search.cache_hit",
            key_fingerprint=fingerprint,
            mode=payload.mode,
            k=payload.k,
            filter=payload.filter.as_dict() if payload.filter else None,
            duration_ms=round(total_ms, 2),
        )
        return SearchResponse(
            query=payload.query,
            mode=payload.mode,
            k=payload.k,
            passages=cached.passages,
            confidence=cached.confidence,
            provenance=cached.provenance,
            timings=Timings(
                total_ms=round(total_ms, 2),
                retrieval_ms=0.0,
                generation_ms=0.0,
                cache_hit=True,
            ),
            answer=cached.answer,
            filter=payload.filter,
        )

    # A bypassed cache is not a miss: counting it as one would make the hit ratio depend
    # on how often the benchmark runs rather than on how well the cache works.
    if payload.use_cache:
        metrics.CACHE_EVENTS.labels("miss").inc()

    config = _config_for(payload)
    retrieval_started = time.perf_counter()
    with state.pool.connection() as conn:
        if getattr(state, "bm25_needs_reload", False) is True:
            with getattr(state, "bm25_lock", Lock()):
                if getattr(state, "bm25_needs_reload", False) is True:
                    state.bm25 = BM25Index(conn)
                    row = conn.execute("SELECT count(*) FROM chunks").fetchone()
                    state.corpus_chunks = as_int(row[0]) if row else 0
                    metrics.CORPUS_CHUNKS.set(state.corpus_chunks)
                    state.bm25_needs_reload = False
                    logger.info(
                        "bm25.reloaded",
                        corpus_chunks=state.corpus_chunks,
                        generation=state.corpus_generation,
                    )
        retriever = Retriever(conn, embedder=state.embedder, bm25=state.bm25)
        hits = retriever.retrieve(payload.query, config)
        assessed = retriever.assess_confidence(payload.query, hits)
    retrieval_seconds = time.perf_counter() - retrieval_started
    metrics.RETRIEVAL_DURATION.labels(payload.mode).observe(retrieval_seconds)
    retrieval_ms = retrieval_seconds * 1000.0

    passages = [
        Passage(
            rank=hit.rank,
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            source=hit.source,
            canonical_url=hit.canonical_url,
            score=round(hit.score, 6),
            arm_ranks=hit.arm_ranks,
            char_start=hit.char_start,
            char_end=hit.char_end,
            text=hit.text,
        )
        for hit in hits
    ]
    confidence = Confidence(**assessed.as_dict())  # type: ignore[arg-type]
    provenance = Provenance(
        embedding_model=MODEL_ID,
        embedding_dim=EMBEDDING_DIM,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        corpus_manifest_digest=state.manifest_digest,
        corpus_chunks=state.corpus_chunks,
        retrieval=config.as_dict(),
        corpus_generation=(
            state.corpus_generation
            if isinstance(getattr(state, "corpus_generation", None), int)
            else 1
        ),
    )

    generated_answer: GeneratedAnswer | None = None
    generation_ms = 0.0
    if payload.generate_answer:
        gen_start = time.perf_counter()
        generator = getattr(state, "generator", None) or get_generator()
        generated_answer = generator.generate(payload.query, passages)
        generation_ms = (time.perf_counter() - gen_start) * 1000.0

    result = CachedResult(
        passages=passages,
        confidence=confidence,
        provenance=provenance,
        answer=generated_answer,
    )
    if payload.use_cache:
        # Check that generation hasn't moved while request was in flight
        if getattr(state, "corpus_generation", 1) == req_generation:
            state.result_cache.put(cache_key, result)
        else:
            logger.info(
                "search.cache_skip_stale_generation",
                req_generation=req_generation,
                current_generation=getattr(state, "corpus_generation", 1),
            )

    total_ms = (time.perf_counter() - started) * 1000.0
    try:
        record_retrieval_event(
            getattr(state, "pool", None),
            RetrievalAuditRecord(
                key_fingerprint=fingerprint,
                query_hash=hash_query(payload.query),
                mode=payload.mode,
                k=payload.k,
                returned_chunk_ids=[p.chunk_id for p in result.passages],
                latency_ms=total_ms,
                cache_hit=False,
                has_generated_answer=generated_answer is not None,
                corpus_generation=req_generation,
            ),
        )
    except Exception:  # noqa: BLE001 - audit failure must never break search
        logger.warning("search.audit_event_failed", exc_info=True)
    logger.info(
        "search.completed",
        key_fingerprint=fingerprint,
        mode=payload.mode,
        k=payload.k,
        filter=payload.filter.as_dict() if payload.filter else None,
        duration_ms=round(total_ms, 2),
        retrieval_ms=round(retrieval_ms, 2),
        generation_ms=round(generation_ms, 2),
        passages=len(result.passages),
        generated_answer=generated_answer is not None,
    )
    return SearchResponse(
        query=payload.query,
        mode=payload.mode,
        k=payload.k,
        passages=result.passages,
        confidence=result.confidence,
        provenance=result.provenance,
        timings=Timings(
            total_ms=round(total_ms, 2),
            retrieval_ms=round(retrieval_ms, 2),
            generation_ms=round(generation_ms, 2),
            cache_hit=False,
        ),
        answer=result.answer,
        filter=payload.filter,
    )


@app.post(
    "/v1/answer",
    response_model=SearchResponse,
    tags=["generation"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request"},
        429: {"description": "rate limit exceeded"},
    },
)
def answer_endpoint(
    payload: SearchRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> SearchResponse:
    """Retrieve passages and construct a citation-grounded answer sitting behind them."""
    req = payload.model_copy(update={"generate_answer": True})
    return search(req, request, fingerprint)


@app.post(
    "/v1/chat",
    response_model=SearchResponse,
    tags=["generation"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request"},
        429: {"description": "rate limit exceeded"},
    },
)
def chat_endpoint(
    payload: SearchRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> SearchResponse:
    """Chat-compatible endpoint returning citation-grounded answers behind retrieved passages."""
    req = payload.model_copy(update={"generate_answer": True})
    return search(req, request, fingerprint)


@app.post(
    "/v1/admin/cache/invalidate",
    response_model=CacheInvalidateResponse,
    tags=["admin"],
    responses={
        401: {"description": "missing or invalid API key"},
    },
)
def admin_invalidate_cache(
    payload: CacheInvalidateRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> CacheInvalidateResponse:
    """Explicitly invalidate the in-memory result cache and reload BM25 index.

    Used by ingestion pipelines, operators, or external cron tasks to immediately
    evict cached queries and rescan active chunks from PostgreSQL.
    """
    state = request.app.state
    prev_gen = getattr(state, "corpus_generation", 1)
    cleared = len(state.result_cache)
    state.result_cache.clear()
    state.corpus_generation = prev_gen + 1
    state.bm25_needs_reload = True
    metrics.CORPUS_GENERATION.set(state.corpus_generation)
    metrics.CACHE_INVALIDATIONS.labels(payload.reason).inc()

    with state.pool.connection() as conn:
        with getattr(state, "bm25_lock", Lock()):
            state.bm25 = BM25Index(conn)
            row = conn.execute("SELECT count(*) FROM chunks").fetchone()
            state.corpus_chunks = as_int(row[0]) if row else 0
            metrics.CORPUS_CHUNKS.set(state.corpus_chunks)
            state.bm25_needs_reload = False

    logger.info(
        "admin.cache_invalidated",
        key_fingerprint=fingerprint,
        reason=payload.reason,
        previous_generation=prev_gen,
        new_generation=state.corpus_generation,
        entries_cleared=cleared,
        corpus_chunks=state.corpus_chunks,
    )
    return CacheInvalidateResponse(
        status="ok",
        previous_generation=prev_gen,
        new_generation=state.corpus_generation,
        entries_cleared=cleared,
        corpus_chunks=state.corpus_chunks,
    )
