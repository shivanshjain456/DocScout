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
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from psycopg_pool import ConnectionPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import demo, metrics
from app.api.cache import DEFAULT_RESULT_TTL_SECONDS, TTLCache
from app.api.models import (
    Confidence,
    HealthResponse,
    Passage,
    Provenance,
    SearchRequest,
    SearchResponse,
    Timings,
)
from app.api.security import RATE_LIMIT_REQUESTS, load_keys, require_api_key
from app.config import database_url, sha256_file
from app.ingest.chunk import CHUNK_OVERLAP, CHUNK_SIZE
from app.ingest.embed import EMBEDDING_DIM, MODEL_ID, Embedder
from app.observability import configure_logging, get_logger, normalise_request_id
from app.retrieval import SERVING_CONFIG, RetrievalConfig, Retriever
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Pay every fixed cost before the first request is served."""
    configure_logging()
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

    app.state.result_cache = TTLCache[tuple[str, str, int], CachedResult](
        maxsize=RESULT_CACHE_SIZE, ttl=DEFAULT_RESULT_TTL_SECONDS
    )
    app.state.embedding_cache = TTLCache[str, Any](maxsize=EMBEDDING_CACHE_SIZE, ttl=None)
    app.state.manifest_digest = sha256_file(REPO_ROOT / "corpus" / "raw" / "manifest.json")

    metrics.CORPUS_CHUNKS.set(app.state.corpus_chunks)
    logger.info(
        "api.ready",
        corpus_chunks=app.state.corpus_chunks,
        embedding_model=MODEL_ID,
        api_keys=len(app.state.api_keys),
        rate_limit_per_minute=RATE_LIMIT_REQUESTS,
    )
    try:
        yield
    finally:
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


@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz(request: Request) -> HealthResponse:
    """Liveness and readiness in one place, deliberately unauthenticated.

    A health check behind auth cannot be used by the thing that needs it most -- a load
    balancer -- and this endpoint reveals only counts and configuration names.
    """
    state = request.app.state
    database_ok = True
    chunks = state.corpus_chunks
    try:
        with state.pool.connection() as conn:
            row = conn.execute("SELECT count(*) FROM chunks").fetchone()
            chunks = as_int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 - health must report, never raise
        logger.warning("healthz.database_probe_failed", exc_info=True)
        database_ok = False

    return HealthResponse(
        status="ok" if database_ok and chunks > 0 else "degraded",
        database=database_ok,
        corpus_chunks=chunks,
        embedding_model=MODEL_ID,
        model_loaded=state.embedder is not None,
        cache={
            **state.result_cache.stats.as_dict(),
            "entries": len(state.result_cache),
        },
        rate_limit_per_minute=RATE_LIMIT_REQUESTS,
        single_process=True,
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
        )
    # Single-arm modes are the documented ADR-0006 ablation, reachable so the A/B can be
    # reproduced against the running service.
    return RetrievalConfig(
        name=f"{payload.mode}-only",
        mode=payload.mode,
        k_dense=SERVING_CONFIG.k_dense,
        k_lexical=SERVING_CONFIG.k_lexical,
        k_final=payload.k,
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
    """Retrieve the passages that answer a question, with checkable citations."""
    started = time.perf_counter()
    state = request.app.state
    cache_key = (payload.query, payload.mode, payload.k)

    cached: CachedResult | None = state.result_cache.get(cache_key) if payload.use_cache else None
    if cached is not None:
        metrics.CACHE_EVENTS.labels("hit").inc()
        total_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "search.cache_hit",
            key_fingerprint=fingerprint,
            mode=payload.mode,
            k=payload.k,
            duration_ms=round(total_ms, 2),
        )
        return SearchResponse(
            query=payload.query,
            mode=payload.mode,
            k=payload.k,
            passages=cached.passages,
            confidence=cached.confidence,
            provenance=cached.provenance,
            timings=Timings(total_ms=round(total_ms, 2), retrieval_ms=0.0, cache_hit=True),
        )

    # A bypassed cache is not a miss: counting it as one would make the hit ratio depend
    # on how often the benchmark runs rather than on how well the cache works.
    if payload.use_cache:
        metrics.CACHE_EVENTS.labels("miss").inc()

    config = _config_for(payload)
    retrieval_started = time.perf_counter()
    with state.pool.connection() as conn:
        retriever = Retriever(conn, embedder=state.embedder, bm25=state.bm25)
        hits = retriever.retrieve(payload.query, config)
        assessed = retriever.assess_confidence(payload.query, hits)
    retrieval_seconds = time.perf_counter() - retrieval_started
    metrics.RETRIEVAL_DURATION.labels(payload.mode).observe(retrieval_seconds)
    retrieval_ms = retrieval_seconds * 1000.0

    result = CachedResult(
        passages=[
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
        ],
        confidence=Confidence(**assessed.as_dict()),  # type: ignore[arg-type]
        provenance=Provenance(
            embedding_model=MODEL_ID,
            embedding_dim=EMBEDDING_DIM,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            corpus_manifest_digest=state.manifest_digest,
            corpus_chunks=state.corpus_chunks,
            retrieval=config.as_dict(),
        ),
    )
    if payload.use_cache:
        state.result_cache.put(cache_key, result)

    total_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "search.completed",
        key_fingerprint=fingerprint,
        mode=payload.mode,
        k=payload.k,
        duration_ms=round(total_ms, 2),
        retrieval_ms=round(retrieval_ms, 2),
        passages=len(result.passages),
    )
    return SearchResponse(
        query=payload.query,
        mode=payload.mode,
        k=payload.k,
        passages=result.passages,
        confidence=result.confidence,
        provenance=result.provenance,
        timings=Timings(
            total_ms=round(total_ms, 2), retrieval_ms=round(retrieval_ms, 2), cache_hit=False
        ),
    )
