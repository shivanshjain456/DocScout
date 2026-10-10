"""The DocScout serving API.

Scope, stated up front because the omission is deliberate: this serves **retrieval with
citations**, not generated answers. There is no LLM in the request path and no API keys to
call one (U-1). An endpoint that returned prose here would have to invent it, and inventing
prose over regulatory text is the single failure this project is built to measure and
avoid. What it returns instead is the evidence  -  ranked passages with resolvable chunk ids
and character spans  -  which is exactly what the eval harness measures, so every number in
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
from app.api.auth0 import (
    UserIdentity,
    require_admin_user,
    require_authenticated_user,
)
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
    DigestDispatchResponse,
    DiscoveryTriggerRequest,
    DiscoveryTriggerResponse,
    DocumentResponse,
    LivenessResponse,
    OCRInspectionResponse,
    Passage,
    Provenance,
    ReadinessResponse,
    ResearchArtifactSummary,
    ResearchRequest,
    ResearchResponse,
    SearchRequest,
    SearchResponse,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    Timings,
    UnsubscribeResponse,
    UserInterestCreate,
    UserInterestResponse,
    UserProfileResponse,
    WebhookProcessResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.api.security import RATE_LIMIT_REQUESTS, load_keys, require_api_key
from app.config import database_url, sha256_file, staleness_budget_hours
from app.generate import GeneratedAnswer, get_generator
from app.generate.agent import (
    ResearchAgent,
    ensure_workspace,
    get_research_artifact,
    list_workspace_artifacts,
    save_research_artifact,
)
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
            title=hit.title if isinstance(getattr(hit, "title", None), str) else None,
            published_date=(
                hit.published_date
                if isinstance(getattr(hit, "published_date", None), str)
                else None
            ),
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


@app.get(
    "/v1/documents/{document_id}",
    response_model=DocumentResponse,
    tags=["documents"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "document not found"},
    },
)
def get_document(
    document_id: str,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> DocumentResponse:
    """Resolve authoritative document metadata, title, date and lineage (FR-14)."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document_id!r} not found (invalid UUID format)",
        ) from None

    state = request.app.state
    with state.pool.connection() as conn:
        row = conn.execute(
            """
            SELECT d.document_id::text,
                   d.canonical_url,
                   d.source,
                   d.authority,
                   d.title,
                   d.published_date::text,
                   d.detail_page,
                   d.created_at,
                   (SELECT count(*) FROM document_versions v WHERE v.document_id = d.document_id) AS version_count,
                   (SELECT v.version_id::text FROM document_versions v WHERE v.document_id = d.document_id AND v.is_current LIMIT 1) AS current_version_id,
                   (SELECT count(*) FROM chunks c WHERE c.document_id = d.document_id) AS chunk_count
              FROM documents d
             WHERE d.document_id = %s
            """,
            (doc_uuid,),
        ).fetchone()

    if row is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document_id} not found",
        )

    return DocumentResponse(
        document_id=str(row[0]),
        canonical_url=str(row[1]),
        source=str(row[2]),
        authority=str(row[3]) if row[3] is not None else str(row[2]),
        title=str(row[4]) if row[4] is not None else None,
        published_date=str(row[5]) if row[5] is not None else None,
        detail_page=str(row[6]) if row[6] is not None else None,
        created_at=row[7],
        version_count=as_int(row[8]),
        current_version_id=str(row[9]) if row[9] is not None else None,
        chunk_count=as_int(row[10]),
    )


@app.post(
    "/v1/research",
    response_model=ResearchResponse,
    tags=["research"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request"},
    },
)
def research_endpoint(
    payload: ResearchRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> ResearchResponse:
    """Execute the deterministic agentic research loop to produce a structured, citation-grounded report."""
    start_t = time.perf_counter()
    state = request.app.state
    with state.pool.connection() as conn:
        retriever = Retriever(conn, embedder=state.embedder, bm25=state.bm25)
        agent = ResearchAgent(retriever)
        artifact = agent.research(
            query=payload.query,
            workspace_id=payload.workspace_id,
            k=payload.k,
            mode=payload.mode,
            max_aspects=payload.max_aspects,
        )
        save_research_artifact(conn, artifact)

    dur_s = time.perf_counter() - start_t
    metrics.AGENT_RESEARCH_TOTAL.labels("success").inc()
    metrics.AGENT_RESEARCH_DURATION.observe(dur_s)

    logger.info(
        "research.completed",
        key_fingerprint=fingerprint,
        workspace_id=payload.workspace_id,
        aspects=payload.max_aspects,
        claims=len(artifact.citations),
        duration_ms=round(dur_s * 1000.0, 2),
        abstained=artifact.abstained,
        grounded=artifact.grounded,
    )

    return ResearchResponse(
        artifact=artifact,
        workspace_id=payload.workspace_id,
    )


@app.post(
    "/v1/workspaces",
    response_model=WorkspaceResponse,
    tags=["research"],
    responses={
        401: {"description": "missing or invalid API key"},
    },
)
def create_workspace_endpoint(
    payload: WorkspaceCreateRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> WorkspaceResponse:
    """Create or register a research workspace for persisting analyst reports."""
    ws_id = str(uuid.uuid4())
    state = request.app.state
    with state.pool.connection() as conn:
        ensure_workspace(conn, ws_id, name=payload.name)

    logger.info(
        "workspace.created", key_fingerprint=fingerprint, workspace_id=ws_id, name=payload.name
    )
    return WorkspaceResponse(
        workspace_id=ws_id,
        name=payload.name,
        created_at=datetime.now(UTC).isoformat(),
    )


@app.get(
    "/v1/workspaces/{workspace_id}/artifacts",
    response_model=list[ResearchArtifactSummary],
    tags=["research"],
    responses={
        401: {"description": "missing or invalid API key"},
    },
)
def list_artifacts_endpoint(
    workspace_id: str,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> list[ResearchArtifactSummary]:
    """List research artifacts saved in a specific workspace."""
    state = request.app.state
    with state.pool.connection() as conn:
        items = list_workspace_artifacts(conn, workspace_id)

    return [ResearchArtifactSummary(**item) for item in items]


@app.get(
    "/v1/research/artifacts/{artifact_id}",
    response_model=ResearchResponse,
    tags=["research"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "artifact not found"},
    },
)
def get_artifact_endpoint(
    artifact_id: str,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> ResearchResponse:
    """Retrieve a previously generated research artifact with full step execution trace."""
    try:
        _ = uuid.UUID(artifact_id)
    except ValueError:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"artifact {artifact_id!r} not found (invalid UUID format)",
        ) from None

    state = request.app.state
    with state.pool.connection() as conn:
        artifact = get_research_artifact(conn, artifact_id)

    if artifact is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"research artifact {artifact_id} not found",
        )

    return ResearchResponse(
        artifact=artifact,
        workspace_id=artifact.workspace_id,
    )


# --- Analyst Identity & Watchlists ---


@app.get(
    "/v1/user/me",
    response_model=UserProfileResponse,
    tags=["identity"],
)
def get_current_user_profile(
    user: UserIdentity = Depends(require_authenticated_user),
) -> UserProfileResponse:
    """Return profile and permissions for the currently authenticated Auth0 analyst."""
    return UserProfileResponse(
        user_id=str(user.user_id),
        auth0_sub=user.auth0_sub,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        is_service_key=user.is_service_key,
    )


@app.get(
    "/v1/user/interests",
    response_model=list[UserInterestResponse],
    tags=["identity"],
)
def list_user_interests(
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> list[UserInterestResponse]:
    """List saved research interests and watchlists for the authenticated analyst."""
    state = request.app.state
    with state.pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT interest_id::text, user_id::text, topic, regulator, keywords, created_at::text
              FROM user_interests
             WHERE user_id = %s
             ORDER BY created_at DESC
            """,
            (user.user_id,),
        ).fetchall()

    return [
        UserInterestResponse(
            interest_id=str(r[0]),
            user_id=str(r[1]),
            topic=str(r[2]),
            regulator=str(r[3]),
            keywords=list(r[4]) if r[4] else [],
            created_at=str(r[5]),
        )
        for r in rows
    ]


@app.post(
    "/v1/user/interests",
    response_model=UserInterestResponse,
    tags=["identity"],
)
def create_user_interest(
    payload: UserInterestCreate,
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> UserInterestResponse:
    """Save a regulatory topic or keyword watchlist under analyst identity."""
    state = request.app.state
    with state.pool.connection() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO user_interests (user_id, topic, regulator, keywords)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, topic, regulator) DO UPDATE SET
                    keywords = EXCLUDED.keywords
                RETURNING interest_id::text, user_id::text, topic, regulator, keywords, created_at::text
                """,
                (user.user_id, payload.topic, payload.regulator, payload.keywords),
            ).fetchone()

    if row is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to save research interest",
        )

    return UserInterestResponse(
        interest_id=str(row[0]),
        user_id=str(row[1]),
        topic=str(row[2]),
        regulator=str(row[3]),
        keywords=list(row[4]) if row[4] else [],
        created_at=str(row[5]),
    )


@app.delete(
    "/v1/user/interests/{interest_id}",
    tags=["identity"],
)
def delete_user_interest(
    interest_id: str,
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> dict[str, str]:
    """Delete a saved watchlist item, strictly bounded to user ownership."""
    try:
        int_uuid = uuid.UUID(interest_id)
    except ValueError:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"interest {interest_id!r} not found",
        ) from None

    state = request.app.state
    with state.pool.connection() as conn:
        with conn.transaction():
            res = conn.execute(
                "DELETE FROM user_interests WHERE interest_id = %s AND user_id = %s",
                (int_uuid, user.user_id),
            )
            if res.rowcount == 0:
                raise StarletteHTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"interest {interest_id} not found or not owned by user",
                )

    return {"status": "deleted", "interest_id": interest_id}


# --- Brevo Subscriptions & Regulatory Digests ---


@app.get(
    "/v1/subscriptions",
    response_model=SubscriptionResponse,
    tags=["digests"],
)
def get_subscription_endpoint(
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> SubscriptionResponse:
    """Retrieve regulatory digest subscription and topic preferences for current analyst."""
    from app.config import docscout_base_url
    from app.digests.engine import DigestEngine

    state = request.app.state
    engine = DigestEngine(state.pool)
    sub = engine.get_user_subscription(user.user_id)
    if sub is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no active subscription found for user",
        )

    base = docscout_base_url()
    unsub_url = f"{base}/v1/subscriptions/unsubscribe?token={sub.unsubscribe_token}"

    return SubscriptionResponse(
        subscription_id=str(sub.subscription_id),
        user_id=str(sub.user_id),
        email=sub.email,
        frequency=sub.frequency,
        is_active=sub.is_active,
        topics=sub.topics,
        regulators=sub.regulators,
        consent_ts=sub.consent_ts.isoformat() if sub.consent_ts else "",
        unsubscribe_url=unsub_url,
    )


@app.post(
    "/v1/subscriptions",
    response_model=SubscriptionResponse,
    tags=["digests"],
)
def create_subscription_endpoint(
    payload: SubscriptionCreateRequest,
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> SubscriptionResponse:
    """Create or update a topic-based digest subscription with explicit consent."""
    if not payload.consent:
        raise StarletteHTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Explicit user consent (consent=true) is required to receive regulatory digests.",
        )

    from app.config import docscout_base_url
    from app.digests.engine import DigestEngine

    state = request.app.state
    client_ip = request.client.host if request.client else None
    engine = DigestEngine(state.pool)
    sub = engine.upsert_subscription(
        user_id=user.user_id,
        email=user.email,
        frequency=payload.frequency,
        topics=payload.topics,
        regulators=payload.regulators,
        consent_ip=client_ip,
        is_active=True,
    )

    base = docscout_base_url()
    unsub_url = f"{base}/v1/subscriptions/unsubscribe?token={sub.unsubscribe_token}"

    return SubscriptionResponse(
        subscription_id=str(sub.subscription_id),
        user_id=str(sub.user_id),
        email=sub.email,
        frequency=sub.frequency,
        is_active=sub.is_active,
        topics=sub.topics,
        regulators=sub.regulators,
        consent_ts=sub.consent_ts.isoformat() if sub.consent_ts else "",
        unsubscribe_url=unsub_url,
    )


@app.delete(
    "/v1/subscriptions",
    tags=["digests"],
)
def deactivate_subscription_endpoint(
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> dict[str, str]:
    """Disable digest notifications for the current analyst."""
    state = request.app.state
    with state.pool.connection() as conn:
        with conn.transaction():
            conn.execute(
                "UPDATE subscriptions SET is_active = false, updated_at = now() WHERE user_id = %s",
                (user.user_id,),
            )
    return {"status": "deactivated"}


@app.get(
    "/v1/subscriptions/unsubscribe",
    response_model=UnsubscribeResponse,
    tags=["digests"],
)
def one_click_unsubscribe(
    token: str,
    request: Request,
) -> UnsubscribeResponse:
    """One-click unsubscribe endpoint accessible directly from digest email headers and footers."""
    from app.digests.engine import DigestEngine

    state = request.app.state
    engine = DigestEngine(state.pool)
    success = engine.unsubscribe_by_token(token)
    if not success:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unsubscribe token is invalid or subscription is already disabled",
        )

    return UnsubscribeResponse(
        status="ok",
        detail="Successfully unsubscribed from DocScout regulatory alert digests.",
    )


@app.post(
    "/v1/admin/digests/dispatch",
    response_model=DigestDispatchResponse,
    tags=["admin"],
)
def dispatch_digests_endpoint(
    request: Request,
    frequency: str = "weekly",
    since_hours: float = 168.0,
    admin: UserIdentity = Depends(require_admin_user),
) -> DigestDispatchResponse:
    """Admin endpoint: trigger grounded regulatory digest compilation and Brevo transmission."""
    from app.digests.engine import DigestEngine

    state = request.app.state
    engine = DigestEngine(state.pool)
    valid_freq = "weekly" if frequency not in ("immediate", "daily", "weekly") else frequency
    count = engine.process_pending_digests(frequency=valid_freq, since_hours=since_hours)  # type: ignore[arg-type]

    return DigestDispatchResponse(
        status="ok",
        frequency=valid_freq,
        dispatched_notifications=count,
    )


@app.post(
    "/v1/webhooks/brevo",
    response_model=WebhookProcessResponse,
    tags=["webhooks"],
)
async def brevo_webhook_endpoint(
    request: Request,
    secret: str | None = None,
) -> WebhookProcessResponse:
    """Handle Brevo transactional delivery callbacks (delivered, bounced, spam)."""
    from app.digests.webhook import process_brevo_event, verify_webhook_secret

    if not verify_webhook_secret(request, secret):
        raise StarletteHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing webhook authentication secret",
        )

    try:
        body = await request.json()
    except Exception as exc:
        raise StarletteHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid JSON payload: {exc}",
        ) from exc

    state = request.app.state
    res = process_brevo_event(state.pool, body if isinstance(body, dict) else {})
    return WebhookProcessResponse(
        status=res.get("status", "ok"),
        event=res.get("event", "unknown"),
        processed=bool(res.get("processed", True)),
    )


# --- OCR.Space Inspection & Fallback ---


@app.get(
    "/v1/documents/{document_id}/ocr",
    response_model=OCRInspectionResponse,
    tags=["documents"],
)
def get_document_ocr(
    document_id: str,
    request: Request,
    user: UserIdentity = Depends(require_authenticated_user),
) -> OCRInspectionResponse:
    """Inspect OCR.Space processing status and extracted text cache for a document."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document_id!r} not found",
        ) from None

    state = request.app.state
    with state.pool.connection() as conn:
        row = conn.execute(
            """
            SELECT v.sha256, o.status, o.engine, o.pages_processed, o.extracted_text,
                   o.error_detail, o.latency_ms
              FROM documents d
              JOIN document_versions v ON d.document_id = v.document_id AND v.is_current
              LEFT JOIN ocr_extractions o ON o.sha256 = v.sha256
             WHERE d.document_id = %s
            """,
            (doc_uuid,),
        ).fetchone()

    if row is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document_id} not found",
        )

    sha = str(row[0])
    ocr_status = str(row[1]) if row[1] else "NOT_PROCESSED"
    engine = str(row[2]) if row[2] else "none"
    pages = int(row[3] or 0)
    text = str(row[4] or "")
    err = str(row[5]) if row[5] else None
    lat = float(row[6] or 0.0)

    from app.ingest.clean import clean_char_count

    return OCRInspectionResponse(
        sha256=sha,
        status=ocr_status,
        engine=engine,
        pages_processed=pages,
        clean_char_count=clean_char_count(text),
        extracted_text_sample=text[:300],
        latency_ms=lat,
        error_detail=err,
        cached=row[1] is not None,
    )


@app.post(
    "/v1/documents/{document_id}/ocr",
    response_model=OCRInspectionResponse,
    tags=["admin"],
)
def trigger_document_ocr(
    document_id: str,
    request: Request,
    admin: UserIdentity = Depends(require_admin_user),
) -> OCRInspectionResponse:
    """Admin endpoint: trigger bounded OCR.Space extraction for an eligible document."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document_id!r} not found",
        ) from None

    state = request.app.state
    with state.pool.connection() as conn:
        row = conn.execute(
            """
            SELECT d.canonical_url, v.sha256
              FROM documents d
              JOIN document_versions v ON d.document_id = v.document_id AND v.is_current
             WHERE d.document_id = %s
            """,
            (doc_uuid,),
        ).fetchone()

    if row is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document {document_id} not found",
        )

    sha = str(row[1])

    # Fetch on-disk or local PDF payload
    from app.config import REPO_ROOT
    from app.ingest.clean import clean_char_count
    from app.ingest.ocr_space import OCRSpaceClient

    pdf_path = None
    for p in (REPO_ROOT / "corpus" / "raw").glob("*.PDF"):
        if sha[:12] in p.name:
            pdf_path = p
            break
    if not pdf_path:
        for p in (REPO_ROOT / "corpus" / "raw").glob("*.pdf"):
            if sha[:12] in p.name:
                pdf_path = p
                break

    if not pdf_path or not pdf_path.exists():
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"raw PDF artifact for document {document_id} not available on disk",
        )

    pdf_bytes = pdf_path.read_bytes()
    with state.pool.connection() as conn:
        client = OCRSpaceClient()
        res = client.parse_pdf(pdf_bytes, conn)

    return OCRInspectionResponse(
        sha256=res.sha256,
        status=res.status,
        engine=res.engine,
        pages_processed=res.pages_processed,
        clean_char_count=clean_char_count(res.extracted_text),
        extracted_text_sample=res.extracted_text[:300],
        latency_ms=res.latency_ms,
        error_detail=res.error_detail,
        cached=res.cached,
    )


# --- Regulatory Discovery ---


@app.post(
    "/v1/admin/discovery/run",
    response_model=DiscoveryTriggerResponse,
    tags=["admin"],
)
def run_discovery_endpoint(
    payload: DiscoveryTriggerRequest,
    request: Request,
    admin: UserIdentity = Depends(require_admin_user),
) -> DiscoveryTriggerResponse:
    """Admin endpoint: trigger live discovery crawl of newly published RBI/SEBI circulars."""
    from app.ingest.discovery import RegulatoryDiscoveryEngine

    state = request.app.state
    with state.pool.connection() as conn:
        engine = RegulatoryDiscoveryEngine(conn)
        report = engine.run_discovery(
            rbi_limit=payload.rbi_limit,
            sebi_limit=payload.sebi_limit,
            dry_run=payload.dry_run,
        )

    return DiscoveryTriggerResponse(
        status="ok",
        discovered_total=report.discovered_total,
        new_documents=report.new_documents,
        content_revisions=report.content_revisions,
        unchanged=report.unchanged,
        failed=report.failed,
        items=[
            {
                "url": it.url,
                "source": it.source,
                "classification": it.classification,
                "http_status": it.http_status,
                "sha256": it.sha256,
                "detail": it.detail,
                "document_id": it.document_id,
                "version_id": it.version_id,
            }
            for it in report.items
        ],
    )
