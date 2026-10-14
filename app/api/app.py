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

import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi import Path as FastApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from psycopg_pool import ConnectionPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import demo, metrics
from app.api.admin_ontology import router as admin_ontology_router
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
from app.api.chat import router as chat_router
from app.api.models import (
    AdvanceStageRequest,
    AlgoAssessmentRequest,
    AlgoAssessmentResponse,
    AnnotatedFormulaResponse,
    AnnotateFormulaRequest,
    AntipatternBenchmarkResponse,
    AntipatternCatalogResponse,
    AntipatternFindingModel,
    AntipatternRuleModel,
    AuditRuleDefinitionModel,
    AuditRulesCatalogResponse,
    AuditSanityRequest,
    AuditSanityResponse,
    BatchRemediationRequest,
    BatchRemediationResponse,
    BoundaryCatalogResponse,
    BuildGraphRequest,
    CacheInvalidateRequest,
    CacheInvalidateResponse,
    CertifyReleaseRequest,
    CheckSupersessionRequest,
    CheckSupersessionResponse,
    CircularClauseModel,
    ClassifyScopeRequest,
    ClassifyScopeResponse,
    CompareClausePairRequest,
    CompareClausePairResponse,
    CompareFormulaVersionsRequest,
    CompareFormulaVersionsResponse,
    CompleteIncidentActionRequest,
    CompleteMilestoneRequest,
    Confidence,
    ConflictBenchmarkResponse,
    ConsistencyAnomalyModel,
    CriterionCheck,
    CrosswalkResponse,
    CryptographicInventoryBatch,
    DeclareIncidentRequest,
    DependencyGraphResponse,
    DeprecationCatalogResponse,
    DeprecationDetectionModel,
    DetectConflictsRequest,
    DetectConflictsResponse,
    DetectedConflictModel,
    DigestDispatchResponse,
    DiscoveryTriggerRequest,
    DiscoveryTriggerResponse,
    DispatchDeadlineAlertsRequest,
    DispatchDeadlineAlertsResponse,
    DocumentParametersResponse,
    DocumentResponse,
    DocumentStandardMentionsResponse,
    DORAAssessmentRequest,
    DORAComplianceReport,
    DORASystemsResponse,
    EvaluateGraphRequest,
    EvaluateGraphResponse,
    EvaluationTraceStep,
    ExitValidationResult,
    ExportEvidenceRequest,
    ExportResponse,
    ExtractDeadlinesRequest,
    ExtractDeadlinesResponse,
    ExtractParametersRequest,
    ExtractParametersResponse,
    ExtractStandardMentionsRequest,
    ExtractStandardMentionsResponse,
    FailedControlModel,
    FormulaCalcRequest,
    FormulaCalcResult,
    FormulaHistoryResponse,
    FormulaListResponse,
    FormulaVersionModel,
    GenerateRemediationRequest,
    GraphEdge,
    GraphEdgeModel,
    GraphNode,
    GraphNodeModel,
    GraphTemplateSummaryModel,
    HarmonizationReport,
    HarmonizeRequest,
    IncidentCrisisState,
    IntentClassification,
    LivenessResponse,
    MappedControl,
    MilestoneSummaryModel,
    NormalizedQuantityModel,
    NormalizeUnitsRequest,
    NormalizeUnitsResponse,
    ObservationStatusResponse,
    OCRInspectionResponse,
    Passage,
    PersonaListResponse,
    PersonaProfileResponse,
    PlaybookRunResponse,
    PlaybookTemplateSummary,
    PQCInventoryResponse,
    PQCReadinessReport,
    PQCScanRequest,
    PracticeRecommendationModel,
    PrerequisiteCheckRequest,
    PrerequisiteCheckResponse,
    PromoteStageRequest,
    Provenance,
    QuantityComparisonRequest,
    QuantityComparisonResponse,
    RatioValidationRequest,
    RatioValidationResponse,
    ReadinessResponse,
    RecordResilienceTestRequest,
    RecordResilienceTestResponse,
    RegulatoryDeadlineModel,
    ReleaseCertificate,
    RemediationCatalogResponse,
    RemediationPlanModel,
    ResearchArtifactSummary,
    ResearchRequest,
    ResearchResponse,
    ResolveFormulaVersionRequest,
    RoleTask,
    RoleTaskList,
    ScanAntipatternsRequest,
    ScanAntipatternsResponse,
    ScorecardRequest,
    ScorecardResponse,
    SearchRequest,
    SearchResponse,
    SimulationRequest,
    SimulationResponse,
    StageProgress,
    StageSummaryModel,
    StandardListResponse,
    StandardMentionResponse,
    StandardMetadata,
    StandardResponse,
    StandardsListResponse,
    StartPlaybookRequest,
    StatutoryDeprecationModel,
    StatutoryParameterModel,
    SubgraphResponse,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SuggestionResponse,
    SupersessionChainModel,
    SupersessionNodeModel,
    TelemetryBatch,
    TelemetryIngestResponse,
    Timings,
    TrackedFormulaSummaryModel,
    UnsubscribeResponse,
    UserInterestCreate,
    UserInterestResponse,
    UserProfileResponse,
    VendorRiskAuditRequest,
    VendorRiskReportResponse,
    WebhookProcessResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.api.security import RATE_LIMIT_REQUESTS, load_keys, require_api_key
from app.compliance.debt_register import router as compliance_debt_router
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
from app.retrieval.intent_router import get_default_intent_router
from app.retrieval.lexical import BM25Index
from app.retrieval.types import MetadataFilter
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
    intent: IntentClassification | None = None
    extracted_tags: list[str] = field(default_factory=list)
    normalized_query: str | None = None
    corrections_applied: dict[str, str] = field(default_factory=dict)
    persona: str | None = None
    persona_applied: PersonaProfileResponse | None = None


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
    app.state.intent_router = get_default_intent_router()

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

app.include_router(admin_ontology_router)
app.include_router(chat_router)
app.include_router(compliance_debt_router)


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


def _config_for(
    payload: SearchRequest,
) -> tuple[RetrievalConfig, PersonaProfileResponse | None]:
    """Build the retrieval configuration, keeping the serving default authoritative."""
    filt = payload.filter
    if filt is None and payload.relationship_filter is not None:
        filt = MetadataFilter(relationship_filter=payload.relationship_filter)
    elif filt is not None and payload.relationship_filter is not None:
        filt = filt.model_copy(update={"relationship_filter": payload.relationship_filter})

    if filt is None and payload.entity_vintage is not None:
        filt = MetadataFilter(entity_vintage=payload.entity_vintage)
    elif filt is not None and payload.entity_vintage is not None:
        filt = filt.model_copy(update={"entity_vintage": payload.entity_vintage})

    if filt is None and payload.as_of_date is not None:
        filt = MetadataFilter(as_of_date=payload.as_of_date)
    elif filt is not None and payload.as_of_date is not None:
        filt = filt.model_copy(update={"as_of_date": payload.as_of_date})

    if payload.mode == "hybrid":
        base_cfg = RetrievalConfig(
            name=SERVING_CONFIG.name,
            mode="hybrid",
            k_dense=SERVING_CONFIG.k_dense,
            k_lexical=SERVING_CONFIG.k_lexical,
            k_final=payload.k,
            rrf_k=SERVING_CONFIG.rrf_k,
            anchor_arm_top1=SERVING_CONFIG.anchor_arm_top1,
            filter=filt,
            expand_query=payload.expand_query,
            expansion_mode=payload.expansion_mode,
            relationship_filter=payload.relationship_filter,
            enable_centrality_boost=payload.enable_centrality_boost,
            centrality_weight=payload.centrality_weight,
            enable_disambiguation=payload.enable_disambiguation,
            difficulty_band=payload.difficulty_band,
            auto_constrain_tags=payload.auto_constrain_tags,
            enable_normalization=payload.enable_normalization,
        )
    else:
        # Single-arm modes are the documented ADR-0006 ablation, reachable so the A/B can be
        # reproduced against the running service.
        base_cfg = RetrievalConfig(
            name=f"{payload.mode}-only",
            mode=payload.mode,
            k_dense=SERVING_CONFIG.k_dense,
            k_lexical=SERVING_CONFIG.k_lexical,
            k_final=payload.k,
            filter=filt,
            expand_query=payload.expand_query,
            expansion_mode=payload.expansion_mode,
            relationship_filter=payload.relationship_filter,
            enable_centrality_boost=payload.enable_centrality_boost,
            centrality_weight=payload.centrality_weight,
            enable_disambiguation=payload.enable_disambiguation,
            difficulty_band=payload.difficulty_band,
            auto_constrain_tags=payload.auto_constrain_tags,
            enable_normalization=payload.enable_normalization,
        )

    if payload.persona:
        from app.retrieval.persona import get_default_persona_profiler

        profiler = get_default_persona_profiler()
        return profiler.apply_to_config(
            persona=payload.persona,
            base_config=base_cfg,
            explicit_difficulty=payload.difficulty_band,
            explicit_expansion=payload.expansion_mode,
            explicit_auto_tags=payload.auto_constrain_tags if payload.auto_constrain_tags else None,
        )

    return base_cfg, None


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
        payload.relationship_filter,
        payload.enable_centrality_boost,
        payload.centrality_weight,
        payload.enable_disambiguation,
        payload.enable_intent_routing,
        payload.difficulty_band,
        payload.auto_constrain_tags,
        payload.enable_normalization,
        payload.persona,
        payload.entity_vintage,
        payload.as_of_date.isoformat() if payload.as_of_date else None,
    )

    if payload.as_of_date is not None:
        metrics.TEMPORAL_QUERIES_TOTAL.inc()
        logger.info(
            "search.temporal_filter",
            as_of_date=payload.as_of_date.isoformat(),
            query=payload.query,
        )

    if payload.relationship_filter is not None:
        metrics.RELATIONSHIP_QUERIES_TOTAL.labels(relation=payload.relationship_filter).inc()
        logger.info(
            "search.relationship_filter",
            relationship_filter=payload.relationship_filter,
            query=payload.query,
        )

    if payload.filter is not None and payload.filter.standard is not None:
        metrics.STANDARD_CONSTRAINED_QUERIES_TOTAL.labels(standard=payload.filter.standard).inc()
        logger.info(
            "search.standard_filter",
            filter_standard=payload.filter.standard,
            query=payload.query,
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
        except Exception as exc:  # noqa: BLE001 - audit failure must never break search
            logger.warning("search.audit_event_failed", error=str(exc))
        logger.info(
            "search.cache_hit",
            key_fingerprint=fingerprint,
            mode=payload.mode,
            k=payload.k,
            filter=payload.filter.as_dict() if payload.filter else None,
            filter_standard=payload.filter.standard if payload.filter else None,
            difficulty_band=payload.difficulty_band,
            extracted_tags=cached.extracted_tags,
            duration_ms=round(total_ms, 2),
            persona=cached.persona,
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
            intent=cached.intent,
            extracted_tags=cached.extracted_tags,
            normalized_query=cached.normalized_query,
            corrections_applied=cached.corrections_applied,
            persona=cached.persona,
            persona_applied=cached.persona_applied,
        )

    # A bypassed cache is not a miss: counting it as one would make the hit ratio depend
    # on how often the benchmark runs rather than on how well the cache works.
    if payload.use_cache:
        metrics.CACHE_EVENTS.labels("miss").inc()

    config, persona_applied = _config_for(payload)
    if persona_applied is not None:
        metrics.PERSONA_QUERIES_TOTAL.labels(persona_id=persona_applied.id).inc()

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
            matching_relationships=hit.matching_relationships,
            centrality_boost=round(hit.centrality_boost, 6),
            difficulty_level=payload.difficulty_band,
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

    intent_classification: IntentClassification | None = None
    if payload.enable_intent_routing:
        intent_router = getattr(state, "intent_router", None)
        if not intent_router or not hasattr(intent_router, "classify"):
            intent_router = get_default_intent_router()
        res_intent = intent_router.classify(payload.query)
        if isinstance(res_intent, IntentClassification):
            intent_classification = res_intent

    extracted_tags: list[str] = []
    if len(payload.query.strip()) >= 3:
        try:
            tagger = getattr(state, "query_tagger", None)
            if not tagger or not hasattr(tagger, "extract_tags"):
                from app.retrieval.query_tagger import get_default_query_tagger

                tagger = get_default_query_tagger()
            extracted_tags = tagger.extract_tags(payload.query)
            tagger.record_metrics(extracted_tags)
        except Exception as exc:
            logger.warning("query_tagger_failed", error=str(exc))

    normalized_query_text: str | None = None
    corrections_applied: dict[str, str] = {}
    if payload.enable_normalization:
        try:
            from app.retrieval.normalizer import get_default_normalizer

            norm_res = get_default_normalizer().normalize(payload.query)
            if norm_res.corrections_applied:
                normalized_query_text = norm_res.normalized_query
                corrections_applied = norm_res.corrections_applied
        except Exception as exc:
            logger.warning("normalizer_failed", error=str(exc))

    result = CachedResult(
        passages=passages,
        confidence=confidence,
        provenance=provenance,
        answer=generated_answer,
        intent=intent_classification,
        extracted_tags=extracted_tags,
        normalized_query=normalized_query_text,
        corrections_applied=corrections_applied,
        persona=payload.persona,
        persona_applied=persona_applied,
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
    except Exception as exc:  # noqa: BLE001 - audit failure must never break search
        logger.warning("search.audit_event_failed", error=str(exc))
    logger.info(
        "search.completed",
        key_fingerprint=fingerprint,
        mode=payload.mode,
        k=payload.k,
        filter=payload.filter.as_dict() if payload.filter else None,
        filter_standard=payload.filter.standard if payload.filter else None,
        difficulty_band=payload.difficulty_band,
        extracted_tags=result.extracted_tags,
        duration_ms=round(total_ms, 2),
        retrieval_ms=round(retrieval_ms, 2),
        generation_ms=round(generation_ms, 2),
        passages=len(result.passages),
        generated_answer=generated_answer is not None,
        intent_id=intent_classification.intent_id if intent_classification else None,
        normalized_query=result.normalized_query,
        persona=payload.persona,
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
        intent=result.intent,
        extracted_tags=result.extracted_tags,
        normalized_query=result.normalized_query,
        corrections_applied=result.corrections_applied,
        persona=result.persona,
        persona_applied=result.persona_applied,
    )


@app.get(
    "/v1/search/personas",
    response_model=PersonaListResponse,
    tags=["search"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_personas(
    fingerprint: str = Depends(require_api_key),
) -> PersonaListResponse:
    """List available persona search profiles with their retrieval tuning configurations (FEAT-020)."""
    from app.retrieval.persona import get_default_persona_profiler

    profiles = get_default_persona_profiler().list_profiles()
    return PersonaListResponse(personas=profiles, total=len(profiles))


@app.get(
    "/v1/compliance/formulas",
    response_model=FormulaListResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_compliance_formulas(
    fingerprint: str = Depends(require_api_key),
) -> FormulaListResponse:
    """List 24 canonical taxonomy + statutory compliance formulas (FEAT-021)."""
    from app.compliance.formula_engine import get_default_formula_engine

    engine = get_default_formula_engine()
    formulas = engine.list_formulas()
    return FormulaListResponse(formulas=formulas, total=len(formulas))


@app.post(
    "/v1/compliance/calculate",
    response_model=FormulaCalcResult,
    tags=["compliance"],
    responses={
        400: {"description": "mathematical domain error or division by zero"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "unknown formula or missing input variable"},
        429: {"description": "rate limit exceeded"},
    },
)
def calculate_compliance_formula(
    payload: FormulaCalcRequest,
    fingerprint: str = Depends(require_api_key),
) -> FormulaCalcResult:
    """Safely parse and evaluate compliance mathematical formulas using AST evaluator (FEAT-021)."""
    from app.compliance.formula_engine import (
        MathDomainError,
        MissingVariableError,
        SecurityViolationError,
        UnknownFormulaError,
        get_default_formula_engine,
    )

    engine = get_default_formula_engine()
    calc_start = time.perf_counter()
    try:
        result = engine.calculate(
            formula_id=payload.formula_id,
            inputs=payload.inputs,
            custom_expression=payload.custom_expression,
            precision_decimal_places=payload.precision_decimal_places,
        )
    except UnknownFormulaError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except MissingVariableError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except (MathDomainError, SecurityViolationError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    calc_duration = time.perf_counter() - calc_start
    metrics.FORMULAS_CALCULATED_TOTAL.labels(formula_id=payload.formula_id).inc()
    metrics.FORMULA_CALC_LATENCY.labels(formula_id=payload.formula_id).observe(calc_duration)
    return result


@app.get(
    "/v1/compliance/boundaries",
    response_model=BoundaryCatalogResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_statutory_boundaries(
    regulator: str | None = None,
    category: str | None = None,
    entity_type: str | None = None,
    fingerprint: str = Depends(require_api_key),
) -> BoundaryCatalogResponse:
    """List 38 statutory boundary definitions and regulatory thresholds (FEAT-023)."""
    from app.compliance.boundary_validator import get_default_boundary_validator

    validator = get_default_boundary_validator()
    boundaries = validator.list_boundaries(
        regulator=regulator,
        category=category,
        entity_type=entity_type,
    )
    return BoundaryCatalogResponse(boundaries=boundaries, total=len(boundaries))


@app.post(
    "/v1/compliance/validate-ratios",
    response_model=RatioValidationResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "unknown ratio or invalid payload"},
        429: {"description": "rate limit exceeded"},
    },
)
@app.post(
    "/v1/compliance/validate",
    response_model=RatioValidationResponse,
    tags=["compliance"],
    include_in_schema=False,
)
def validate_statutory_ratios(
    payload: RatioValidationRequest,
    fingerprint: str = Depends(require_api_key),
) -> RatioValidationResponse:
    """Validate reported financial and operational ratios against statutory boundaries (FEAT-023)."""
    from app.compliance.boundary_validator import (
        UnknownRatioError,
        get_default_boundary_validator,
    )

    validator = get_default_boundary_validator()
    try:
        response = validator.validate_ratios(
            ratios=payload.ratios,
            entity_type=payload.entity_type,
            tolerance_percentage=payload.tolerance_percentage,
        )
    except UnknownRatioError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    metrics.VALIDATIONS_PERFORMED_TOTAL.labels(status=response.overall_status).inc()
    for finding in response.findings:
        if finding.status == "BREACH":
            metrics.BOUNDARY_BREACHES_TOTAL.labels(ratio_name=finding.ratio_name).inc()

    return response


@app.post(
    "/v1/compliance/simulate",
    response_model=SimulationResponse,
    tags=["compliance"],
    responses={
        400: {"description": "mathematical domain error during simulation"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "unknown formula or missing input variables"},
        429: {"description": "rate limit exceeded"},
    },
)
def simulate_compliance_sensitivity(
    payload: SimulationRequest,
    fingerprint: str = Depends(require_api_key),
) -> SimulationResponse:
    """Execute what-if sensitivity simulations, partial derivatives, and stress test curves (FEAT-024)."""
    from app.compliance.formula_engine import (
        MathDomainError,
        MissingVariableError,
        UnknownFormulaError,
    )
    from app.compliance.simulator import get_default_compliance_simulator

    simulator = get_default_compliance_simulator()
    sim_start = time.perf_counter()
    try:
        response = simulator.simulate(payload)
    except (UnknownFormulaError, MissingVariableError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except MathDomainError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    duration = time.perf_counter() - sim_start
    metrics.SIMULATION_REQUESTS_TOTAL.labels(formula_id=payload.formula_id).inc()
    metrics.SIMULATION_DURATION_SECONDS.labels(formula_id=payload.formula_id).observe(duration)

    return response


# ---------------------------------------------------------------------------
# Standard-Linked Formula Annotator Endpoints (FEAT-025)
# ---------------------------------------------------------------------------


@app.get(
    "/v1/compliance/standards",
    response_model=StandardListResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_regulatory_standards(
    domain: str | None = None,
    governing_body: str | None = None,
    query: str | None = None,
    fingerprint: str = Depends(require_api_key),
) -> StandardListResponse:
    """List 53+ international and statutory governance standards (FEAT-025)."""
    from app.compliance.standards_registry import get_default_standards_registry

    registry = get_default_standards_registry()
    if query:
        standards = registry.search_standards(query)
    else:
        standards = registry.list_standards(domain=domain, governing_body=governing_body)

    resp_items = [
        StandardResponse(
            id=s.id,
            name=s.name,
            governing_body=s.governing_body,
            domain=s.domain,
            jurisdiction=s.jurisdiction,
            category=s.category,
            description=s.description,
            official_reference_url=s.official_reference_url,
            note=s.note,
            aliases=s.aliases,
        )
        for s in standards
    ]
    return StandardListResponse(standards=resp_items, total=len(resp_items))


@app.get(
    "/v1/compliance/standards/{standard_id}",
    response_model=StandardResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "standard not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_regulatory_standard(
    standard_id: str,
    fingerprint: str = Depends(require_api_key),
) -> StandardResponse:
    """Retrieve specifications for a single regulatory standard (FEAT-025)."""
    from app.compliance.standards_registry import get_default_standards_registry

    registry = get_default_standards_registry()
    std = registry.get_standard(standard_id)
    if std is None:
        raise HTTPException(
            status_code=404,
            detail=f"Standard '{standard_id}' not found in registry.",
        )

    return StandardResponse(
        id=std.id,
        name=std.name,
        governing_body=std.governing_body,
        domain=std.domain,
        jurisdiction=std.jurisdiction,
        category=std.category,
        description=std.description,
        official_reference_url=std.official_reference_url,
        note=std.note,
        aliases=std.aliases,
    )


@app.get(
    "/v1/compliance/formulas/{formula_id}/standards",
    response_model=AnnotatedFormulaResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "formula not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_formula_standards(
    formula_id: str,
    fingerprint: str = Depends(require_api_key),
) -> AnnotatedFormulaResponse:
    """Retrieve standard lineage and governing body cross-link for a formula (FEAT-025)."""
    from app.compliance.formula_engine import get_default_formula_engine
    from app.ingest.standard_linker import get_default_standard_annotator

    engine = get_default_formula_engine()
    formula = engine.get_registered_formula(formula_id)
    if formula is None:
        raise HTTPException(
            status_code=404,
            detail=f"Formula '{formula_id}' not found.",
        )

    annotator = get_default_standard_annotator()
    annotated = annotator.annotate_formula(formula)

    return AnnotatedFormulaResponse(
        formula_id=annotated.formula_id,
        formula_name=annotated.formula_name,
        expression=annotated.expression,
        standard_id=annotated.standard_id,
        standard_name=annotated.standard_name,
        governing_body=annotated.governing_body,
        domain=annotated.domain,
        standard_citation=annotated.standard_citation,
        confidence=annotated.confidence,
        status=annotated.status,
        linked_clauses=annotated.linked_clauses,
    )


@app.post(
    "/v1/compliance/annotate-formula",
    response_model=AnnotatedFormulaResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid formula input"},
        429: {"description": "rate limit exceeded"},
    },
)
def annotate_formula_endpoint(
    payload: AnnotateFormulaRequest,
    fingerprint: str = Depends(require_api_key),
) -> AnnotatedFormulaResponse:
    """Cross-link arbitrary or extracted mathematical formulas to standards (FEAT-025)."""
    from app.ingest.standard_linker import (
        StandardFormulaAnnotator,
        StandardLinkerConfig,
    )

    annotator = StandardFormulaAnnotator(
        config=StandardLinkerConfig(strict_matching=payload.strict_matching)
    )

    formula_input = {
        "id": payload.formula_id or "",
        "name": payload.formula_name or "",
        "expression": payload.expression or "",
        "standard": payload.standard_hint,
    }
    annotated = annotator.annotate_formula(formula_input, standard_hint=payload.standard_hint)

    return AnnotatedFormulaResponse(
        formula_id=annotated.formula_id,
        formula_name=annotated.formula_name,
        expression=annotated.expression,
        standard_id=annotated.standard_id,
        standard_name=annotated.standard_name,
        governing_body=annotated.governing_body,
        domain=annotated.domain,
        standard_citation=annotated.standard_citation,
        confidence=annotated.confidence,
        status=annotated.status,
        linked_clauses=annotated.linked_clauses,
    )


@app.post(
    "/v1/compliance/extract-parameters",
    response_model=ExtractParametersResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def extract_statutory_parameters_endpoint(
    payload: ExtractParametersRequest,
    fingerprint: str = Depends(require_api_key),
) -> ExtractParametersResponse:
    """Extract quantitative statutory parameters (penalties, filing windows, thresholds) from circular text (FEAT-026)."""
    t0 = time.perf_counter()
    from app.ingest.numeric_extractor import NumericalRegulatoryEvidenceExtractor

    extractor = NumericalRegulatoryEvidenceExtractor()
    extracted = extractor.extract_from_text(
        text=payload.text,
        document_id=payload.document_id,
        version_id=payload.version_id,
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    metrics.STATUTORY_EXTRACTION_DURATION_SECONDS.observe(latency_ms / 1000.0)
    for p in extracted:
        metrics.STATUTORY_PARAMETERS_EXTRACTED_TOTAL.labels(
            parameter_type=p.parameter_type,
            normalized_unit=p.normalized_unit,
        ).inc()

    param_models = [
        StatutoryParameterModel(
            id=p.id,
            document_id=p.document_id,
            parameter_name=p.parameter_name,
            parameter_type=p.parameter_type,
            numeric_value=p.numeric_value,
            unit=p.unit,
            normalized_value=p.normalized_value,
            normalized_unit=p.normalized_unit,
            comparison_operator=p.comparison_operator,
            statutory_context=p.statutory_context,
            threshold_ceiling=p.threshold_ceiling,
            section_reference=p.section_reference,
            char_start=p.char_start,
            char_end=p.char_end,
            confidence_score=p.confidence_score,
        )
        for p in extracted
    ]

    types = sorted({p.parameter_type for p in extracted})

    return ExtractParametersResponse(
        document_id=payload.document_id,
        parameters=param_models,
        total_count=len(param_models),
        parameter_types=types,
        latency_ms=round(latency_ms, 3),
    )


@app.get(
    "/v1/compliance/documents/{document_id}/parameters",
    response_model=DocumentParametersResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "document not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_document_statutory_parameters(
    document_id: str,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> DocumentParametersResponse:
    """Retrieve extracted statutory quantitative parameters for a document (FEAT-026)."""
    state = request.app.state
    params: list[StatutoryParameterModel] = []
    has_db = getattr(state, "pool", None) is not None

    if has_db:
        try:
            with state.pool.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, document_id, parameter_name, parameter_type,
                           numeric_value, unit, normalized_value, normalized_unit,
                           comparison_operator, threshold_ceiling, statutory_context,
                           section_reference, char_start, char_end, confidence_score
                      FROM statutory_parameters
                     WHERE document_id = %s
                     ORDER BY char_start NULLS LAST
                    """,
                    (document_id,),
                ).fetchall()
                for r in rows:
                    params.append(
                        StatutoryParameterModel(
                            id=str(r[0]),
                            document_id=str(r[1]),
                            parameter_name=str(r[2]),
                            parameter_type=str(r[3]),
                            numeric_value=float(r[4]),
                            unit=str(r[5]),
                            normalized_value=float(r[6]),
                            normalized_unit=str(r[7]),
                            comparison_operator=str(r[8]),
                            threshold_ceiling=float(r[9]) if r[9] is not None else None,
                            statutory_context=str(r[10]),
                            section_reference=str(r[11]) if r[11] is not None else None,
                            char_start=int(r[12]) if r[12] is not None else None,
                            char_end=int(r[13]) if r[13] is not None else None,
                            confidence_score=float(r[14]),
                        )
                    )
        except Exception as exc:
            logger.warning("Database lookup for statutory parameters failed: %s", exc)

    return DocumentParametersResponse(
        document_id=document_id,
        parameters=params,
        total_count=len(params),
    )


@app.post(
    "/v1/compliance/audit-sanity",
    response_model=AuditSanityResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid audit request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def audit_mathematical_sanity_endpoint(
    payload: AuditSanityRequest,
    fingerprint: str = Depends(require_api_key),
) -> AuditSanityResponse:
    """Execute mathematical sanity and cross-footing consistency audit (FEAT-027)."""
    t0 = time.perf_counter()
    from app.compliance.consistency_auditor import (
        AuditSubmission,
        AuditTable,
        get_default_consistency_auditor,
    )

    auditor = get_default_consistency_auditor()
    tables = [
        AuditTable(
            title=t.title,
            headers=t.headers,
            rows=t.rows,
            row_labels=t.row_labels,
            has_row_totals=t.has_row_totals,
            has_col_totals=t.has_col_totals,
            tolerance=t.tolerance,
        )
        for t in payload.tables
    ]

    submission = AuditSubmission(
        document_id=payload.document_id,
        return_code=payload.return_code,
        declared_values=payload.declared_values,
        tables=tables,
        tolerance=payload.tolerance,
    )

    result = auditor.audit_submission(submission)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    metrics.CONSISTENCY_AUDIT_DURATION_SECONDS.observe(latency_ms / 1000.0)
    metrics.CONSISTENCY_AUDITS_TOTAL.labels(
        return_code=payload.return_code,
        status="valid" if result.is_valid else "invalid",
    ).inc()
    for a in result.anomalies:
        metrics.CONSISTENCY_ANOMALIES_DETECTED_TOTAL.labels(
            anomaly_type=a.anomaly_type.value,
            severity=a.severity.value,
        ).inc()

    anomaly_models = [
        ConsistencyAnomalyModel(
            anomaly_type=a.anomaly_type.value,
            severity=a.severity.value,
            rule_name=a.rule_name,
            message=a.message,
            location=a.location,
            reported_value=a.reported_value,
            expected_value=a.expected_value,
            discrepancy=a.discrepancy,
            tolerance=a.tolerance,
            remediation_hint=a.remediation_hint,
        )
        for a in result.anomalies
    ]

    return AuditSanityResponse(
        is_valid=result.is_valid,
        total_rules_checked=result.total_rules_checked,
        anomalies_count=result.anomalies_count,
        anomalies=anomaly_models,
        passed_checks=result.passed_checks,
        summary=result.summary,
        latency_ms=round(latency_ms, 3),
    )


@app.get(
    "/v1/compliance/audit-rules",
    response_model=AuditRulesCatalogResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_audit_rules_catalog_endpoint(
    fingerprint: str = Depends(require_api_key),
) -> AuditRulesCatalogResponse:
    """Catalog of standard mathematical sanity and cross-footing consistency rules (FEAT-027)."""
    from app.compliance.consistency_auditor import get_default_consistency_auditor

    auditor = get_default_consistency_auditor()
    raw_rules = auditor.get_rule_catalog()
    rule_models = [AuditRuleDefinitionModel(**r) for r in raw_rules]
    return AuditRulesCatalogResponse(
        rules=rule_models,
        total_count=len(rule_models),
    )


@app.post(
    "/v1/compliance/normalize-units",
    response_model=NormalizeUnitsResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def normalize_financial_units_endpoint(
    payload: NormalizeUnitsRequest,
    fingerprint: str = Depends(require_api_key),
) -> NormalizeUnitsResponse:
    """Normalize financial expressions across Indian and International scales (FEAT-028)."""
    t0 = time.perf_counter()
    from app.compliance.unit_normalizer import get_default_unit_normalizer

    normalizer = get_default_unit_normalizer()
    results: list[NormalizedQuantityModel] = []

    for expr in payload.expressions:
        norm = normalizer.parse(expr)
        metrics.UNIT_NORMALIZATIONS_TOTAL.labels(
            currency=norm.canonical_unit,
            scale=norm.scale_label,
        ).inc()
        results.append(
            NormalizedQuantityModel(
                raw_expression=norm.raw_expression,
                canonical_value=norm.canonical_value,
                canonical_unit=norm.canonical_unit,
                currency_symbol=norm.currency_symbol,
                scale_label=norm.scale_label,
                scale_multiplier=norm.scale_multiplier,
                indian_words=norm.indian_words,
                indian_numeric_formatted=norm.indian_numeric_formatted,
                international_words=norm.international_words,
                international_numeric_formatted=norm.international_numeric_formatted,
                bps_equivalent=norm.bps_equivalent,
                percent_equivalent=norm.percent_equivalent,
                synonym_representations=norm.synonym_representations,
                is_valid=norm.is_valid,
            )
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.UNIT_NORMALIZATION_DURATION_SECONDS.observe(latency_ms / 1000.0)

    return NormalizeUnitsResponse(
        results=results,
        total_count=len(results),
        latency_ms=round(latency_ms, 3),
    )


@app.post(
    "/v1/compliance/compare-quantities",
    response_model=QuantityComparisonResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def compare_financial_quantities_endpoint(
    payload: QuantityComparisonRequest,
    fingerprint: str = Depends(require_api_key),
) -> QuantityComparisonResponse:
    """Compare equivalence between two statutory or financial expressions (FEAT-028)."""
    t0 = time.perf_counter()
    from app.compliance.unit_normalizer import get_default_unit_normalizer

    normalizer = get_default_unit_normalizer()
    norm_a = normalizer.parse(payload.expression_a)
    norm_b = normalizer.parse(payload.expression_b)

    are_equiv = normalizer.are_equivalent(
        payload.expression_a,
        payload.expression_b,
        tolerance=payload.tolerance,
    )

    diff = abs(norm_a.canonical_value - norm_b.canonical_value)
    max_val = max(abs(norm_a.canonical_value), abs(norm_b.canonical_value))
    rel_diff = diff / max_val if max_val > 0 else 0.0

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.UNIT_EQUIVALENCE_CHECKS_TOTAL.labels(
        result="equivalent" if are_equiv else "mismatch"
    ).inc()

    model_a = NormalizedQuantityModel(
        raw_expression=norm_a.raw_expression,
        canonical_value=norm_a.canonical_value,
        canonical_unit=norm_a.canonical_unit,
        currency_symbol=norm_a.currency_symbol,
        scale_label=norm_a.scale_label,
        scale_multiplier=norm_a.scale_multiplier,
        indian_words=norm_a.indian_words,
        indian_numeric_formatted=norm_a.indian_numeric_formatted,
        international_words=norm_a.international_words,
        international_numeric_formatted=norm_a.international_numeric_formatted,
        bps_equivalent=norm_a.bps_equivalent,
        percent_equivalent=norm_a.percent_equivalent,
        synonym_representations=norm_a.synonym_representations,
        is_valid=norm_a.is_valid,
    )
    model_b = NormalizedQuantityModel(
        raw_expression=norm_b.raw_expression,
        canonical_value=norm_b.canonical_value,
        canonical_unit=norm_b.canonical_unit,
        currency_symbol=norm_b.currency_symbol,
        scale_label=norm_b.scale_label,
        scale_multiplier=norm_b.scale_multiplier,
        indian_words=norm_b.indian_words,
        indian_numeric_formatted=norm_b.indian_numeric_formatted,
        international_words=norm_b.international_words,
        international_numeric_formatted=norm_b.international_numeric_formatted,
        bps_equivalent=norm_b.bps_equivalent,
        percent_equivalent=norm_b.percent_equivalent,
        synonym_representations=norm_b.synonym_representations,
        is_valid=norm_b.is_valid,
    )

    return QuantityComparisonResponse(
        are_equivalent=are_equiv,
        quantity_a=model_a,
        quantity_b=model_b,
        absolute_difference=round(diff, 6),
        relative_difference=round(rel_diff, 6),
        tolerance=payload.tolerance,
        latency_ms=round(latency_ms, 3),
    )


# --- Formula Dependency Graph Builder (FEAT-029) ---


@app.get(
    "/v1/compliance/dependency-graphs/templates",
    response_model=list[GraphTemplateSummaryModel],
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_dependency_graph_templates_endpoint(
    fingerprint: str = Depends(require_api_key),
) -> list[GraphTemplateSummaryModel]:
    """List pre-configured statutory calculation DAG templates (FEAT-029)."""
    from app.compliance.dependency_graph import DependencyGraphBuilder

    templates = DependencyGraphBuilder.list_templates()
    return [
        GraphTemplateSummaryModel(
            template_id=t["template_id"],
            name=t["name"],
            domain=t["domain"],
            stages_count=t["stages_count"],
            target_variables=t["target_variables"],
            description=t["description"],
        )
        for t in templates
    ]


@app.get(
    "/v1/compliance/dependency-graphs/{graph_id}",
    response_model=DependencyGraphResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "graph not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_dependency_graph_endpoint(
    graph_id: str,
    fingerprint: str = Depends(require_api_key),
) -> DependencyGraphResponse:
    """Retrieve full structural DAG, topological ordering, and execution tiers (FEAT-029)."""
    from app.compliance.dependency_graph import get_graph

    try:
        graph = get_graph(graph_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Formula dependency graph '{graph_id}' not found.",
        ) from None

    nodes = {
        nid: GraphNodeModel(
            node_id=n.node_id,
            name=n.name,
            node_type=n.node_type.value,
            expression=n.expression,
            description=n.description,
            category=n.category,
            unit=n.unit,
            tier=n.tier,
            dependencies=n.dependencies,
        )
        for nid, n in graph.nodes.items()
    }
    edges = [
        GraphEdgeModel(
            source=e.source,
            target=e.target,
            parameter_name=e.parameter_name or e.source,
        )
        for e in graph.edges
    ]

    return DependencyGraphResponse(
        graph_id=graph.graph_id,
        name=graph.name,
        domain=graph.domain,
        description=graph.description,
        nodes=nodes,
        edges=edges,
        topological_order=graph.topological_order,
        execution_tiers=graph.execution_tiers,
        target_variables=graph.target_variables,
    )


@app.post(
    "/v1/compliance/dependency-graphs/build",
    response_model=DependencyGraphResponse,
    tags=["compliance"],
    responses={
        400: {"description": "circular dependency detected"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid formula structure"},
        429: {"description": "rate limit exceeded"},
    },
)
def build_dependency_graph_endpoint(
    payload: BuildGraphRequest,
    fingerprint: str = Depends(require_api_key),
) -> DependencyGraphResponse:
    """Construct directed acyclic graph from custom formula definitions (FEAT-029)."""
    t0 = time.perf_counter()
    from app.compliance.dependency_graph import (
        CircularDependencyError,
        DependencyGraphBuilder,
        register_graph,
    )

    formulas_data = [
        {
            "id": f.id,
            "name": f.name or f.id,
            "expression": f.expression,
            "description": f.description,
            "category": f.category,
            "unit": f.unit,
            "dependencies": f.dependencies,
        }
        for f in payload.formulas
    ]

    try:
        graph = DependencyGraphBuilder.build_from_formulas(
            formulas=formulas_data,
            graph_id=payload.graph_id,
            name=payload.name,
            domain=payload.domain,
            description=payload.description,
            target_variables=payload.target_variables,
        )
    except CircularDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    register_graph(graph)
    latency = time.perf_counter() - t0
    metrics.DEPENDENCY_GRAPHS_BUILT_TOTAL.labels(domain=payload.domain).inc()
    metrics.GRAPH_BUILD_DURATION_SECONDS.observe(latency)

    nodes = {
        nid: GraphNodeModel(
            node_id=n.node_id,
            name=n.name,
            node_type=n.node_type.value,
            expression=n.expression,
            description=n.description,
            category=n.category,
            unit=n.unit,
            tier=n.tier,
            dependencies=n.dependencies,
        )
        for nid, n in graph.nodes.items()
    }
    edges = [
        GraphEdgeModel(
            source=e.source,
            target=e.target,
            parameter_name=e.parameter_name or e.source,
        )
        for e in graph.edges
    ]

    return DependencyGraphResponse(
        graph_id=graph.graph_id,
        name=graph.name,
        domain=graph.domain,
        description=graph.description,
        nodes=nodes,
        edges=edges,
        topological_order=graph.topological_order,
        execution_tiers=graph.execution_tiers,
        target_variables=graph.target_variables,
    )


@app.post(
    "/v1/compliance/dependency-graphs/evaluate",
    response_model=EvaluateGraphResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "graph not found"},
        422: {"description": "invalid calculation inputs"},
        429: {"description": "rate limit exceeded"},
    },
)
def evaluate_dependency_graph_endpoint(
    payload: EvaluateGraphRequest,
    fingerprint: str = Depends(require_api_key),
) -> EvaluateGraphResponse:
    """Execute cascade calculation in strict topological order (FEAT-029)."""
    t0 = time.perf_counter()
    from app.compliance.dependency_graph import get_graph

    graph_key = payload.graph_id or payload.template_id
    if not graph_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Must provide either 'graph_id' or 'template_id'.",
        )

    try:
        graph = get_graph(graph_key)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Formula dependency graph '{graph_key}' not found.",
        ) from None

    eval_result = graph.evaluate_cascade(provided_inputs=payload.provided_inputs)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    stat = "success" if eval_result["is_complete"] else "incomplete"
    metrics.GRAPH_EVALUATIONS_TOTAL.labels(graph_id=graph_key, status=stat).inc()

    trace_steps = [
        EvaluationTraceStep(
            node_id=step["node_id"],
            node_type=step["node_type"],
            value=step.get("value"),
            status=step["status"],
            expression=step.get("expression"),
            tier=step.get("tier"),
            missing_prerequisites=step.get("missing_prerequisites"),
            error=step.get("error"),
        )
        for step in eval_result["trace"]
    ]

    return EvaluateGraphResponse(
        is_complete=eval_result["is_complete"],
        target_outputs=eval_result["target_outputs"],
        computed_values=eval_result["computed_values"],
        trace=trace_steps,
        missing_variables=eval_result["missing_variables"],
        latency_ms=round(latency_ms, 3),
    )


@app.post(
    "/v1/compliance/dependency-graphs/prerequisites",
    response_model=PrerequisiteCheckResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "graph not found"},
        422: {"description": "invalid request format"},
        429: {"description": "rate limit exceeded"},
    },
)
def check_graph_prerequisites_endpoint(
    payload: PrerequisiteCheckRequest,
    fingerprint: str = Depends(require_api_key),
) -> PrerequisiteCheckResponse:
    """Analyze prerequisite availability and calculation readiness for target metrics (FEAT-029)."""
    from app.compliance.dependency_graph import get_graph

    graph_key = payload.graph_id or payload.template_id
    if not graph_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Must provide either 'graph_id' or 'template_id'.",
        )

    try:
        graph = get_graph(graph_key)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Formula dependency graph '{graph_key}' not found.",
        ) from None

    check_res = graph.check_prerequisites(
        target_variables=payload.target_variables or graph.target_variables,
        provided_inputs=payload.provided_inputs,
    )

    return PrerequisiteCheckResponse(
        is_ready=check_res["is_ready"],
        target_variables=check_res["target_variables"],
        required_inputs_count=check_res["required_inputs_count"],
        provided_inputs=check_res["provided_inputs"],
        missing_inputs=check_res["missing_inputs"],
        completion_percentage=check_res["completion_percentage"],
        resolvable_intermediates=check_res["resolvable_intermediates"],
    )


# --- Historical Formula Evolution & Versioning (FEAT-030) ---


@app.get(
    "/v1/compliance/formulas/history/tracked",
    response_model=list[TrackedFormulaSummaryModel],
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_tracked_formula_histories_endpoint(
    fingerprint: str = Depends(require_api_key),
) -> list[TrackedFormulaSummaryModel]:
    """List summary of all formulas with historical regulatory version records (FEAT-030)."""
    from app.compliance.formula_evolution import get_default_formula_evolution_manager

    manager = get_default_formula_evolution_manager()
    summaries = manager.list_tracked_formulas()
    return [
        TrackedFormulaSummaryModel(
            formula_id=s["formula_id"],
            current_label=s["current_label"],
            regulatory_framework=s["regulatory_framework"],
            version_count=s["version_count"],
            earliest_effective=s["earliest_effective"],
            current_expression=s["current_expression"],
            current_thresholds=s["current_thresholds"],
        )
        for s in summaries
    ]


@app.get(
    "/v1/compliance/formulas/{formula_id}/history",
    response_model=FormulaHistoryResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "formula history not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_formula_history_endpoint(
    formula_id: str,
    fingerprint: str = Depends(require_api_key),
) -> FormulaHistoryResponse:
    """Retrieve full chronological evolution timeline of a regulatory formula (FEAT-030)."""
    from app.compliance.formula_evolution import get_default_formula_evolution_manager

    manager = get_default_formula_evolution_manager()
    try:
        history = manager.get_history(formula_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No historical formula records found for '{formula_id}'.",
        ) from None

    version_models = [
        FormulaVersionModel(
            id=v.id,
            formula_id=v.formula_id,
            version_label=v.version_label,
            regulatory_framework=v.regulatory_framework,
            effective_from=v.effective_from,
            effective_to=v.effective_to,
            expression=v.expression,
            eval_expression=v.eval_expression,
            variables=v.variables,
            thresholds=v.thresholds,
            circular_reference=v.circular_reference,
            change_summary=v.change_summary,
            is_currently_active=v.effective_to is None,
        )
        for v in history
    ]

    return FormulaHistoryResponse(
        formula_id=formula_id,
        total_versions=len(version_models),
        history=version_models,
    )


@app.post(
    "/v1/compliance/formulas/{formula_id}/resolve-version",
    response_model=FormulaVersionModel,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "formula not found"},
        422: {"description": "invalid date format"},
        429: {"description": "rate limit exceeded"},
    },
)
def resolve_formula_version_endpoint(
    formula_id: str,
    payload: ResolveFormulaVersionRequest,
    fingerprint: str = Depends(require_api_key),
) -> FormulaVersionModel:
    """Resolve point-in-time statutory formula definition for a specific effective date (FEAT-030)."""
    t0 = time.perf_counter()
    from app.compliance.formula_evolution import get_default_formula_evolution_manager

    manager = get_default_formula_evolution_manager()
    try:
        ver = manager.resolve_version(formula_id, payload.as_of_date)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Formula '{formula_id}' not found in historical registry.",
        ) from None
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date format: {val_err}",
        ) from val_err

    duration = time.perf_counter() - t0
    metrics.FORMULA_VERSIONS_RESOLVED_TOTAL.labels(formula_id=formula_id, status="resolved").inc()
    metrics.VERSION_RESOLUTION_DURATION_SECONDS.observe(duration)

    return FormulaVersionModel(
        id=ver.id,
        formula_id=ver.formula_id,
        version_label=ver.version_label,
        regulatory_framework=ver.regulatory_framework,
        effective_from=ver.effective_from,
        effective_to=ver.effective_to,
        expression=ver.expression,
        eval_expression=ver.eval_expression,
        variables=ver.variables,
        thresholds=ver.thresholds,
        circular_reference=ver.circular_reference,
        change_summary=ver.change_summary,
        is_currently_active=ver.effective_to is None,
    )


@app.post(
    "/v1/compliance/formulas/compare-versions",
    response_model=CompareFormulaVersionsResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "version not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def compare_formula_versions_endpoint(
    payload: CompareFormulaVersionsRequest,
    fingerprint: str = Depends(require_api_key),
) -> CompareFormulaVersionsResponse:
    """Compute structured semantic and mathematical diff between two formula versions (FEAT-030)."""
    from app.compliance.formula_evolution import get_default_formula_evolution_manager

    manager = get_default_formula_evolution_manager()
    try:
        diff = manager.compare_versions(payload.version_a_id, payload.version_b_id)
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err),
        ) from None

    metrics.FORMULA_VERSION_DIFFS_TOTAL.labels(change_type=diff.change_type.value).inc()

    return CompareFormulaVersionsResponse(
        formula_id=diff.formula_id,
        version_a_id=diff.version_a_id,
        version_b_id=diff.version_b_id,
        version_a_label=diff.version_a_label,
        version_b_label=diff.version_b_label,
        expression_changed=diff.expression_changed,
        expression_a=diff.expression_a,
        expression_b=diff.expression_b,
        variables_added=diff.variables_added,
        variables_removed=diff.variables_removed,
        variables_retained=diff.variables_retained,
        threshold_changes=diff.threshold_changes,
        change_type=diff.change_type.value,
        summary=diff.summary,
    )


# --- Statutory Deprecation & Supersession Engine (FEAT-031) ---


@app.get(
    "/v1/compliance/deprecations",
    response_model=DeprecationCatalogResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_statutory_deprecations_endpoint(
    regulator: str | None = None,
    status: str | None = None,
    subject_type: str | None = None,
    fingerprint: str = Depends(require_api_key),
) -> DeprecationCatalogResponse:
    """Retrieve catalog of superseded circulars, repealed guidelines, and deprecated practices (FEAT-031)."""
    from app.compliance.deprecation_engine import get_default_deprecation_engine

    engine = get_default_deprecation_engine()
    deprecations = engine.list_deprecations(
        regulator=regulator,
        status=status,
        subject_type=subject_type,
    )
    models = [StatutoryDeprecationModel(**d.to_dict()) for d in deprecations]
    unique_regulators = sorted(list({d.regulator for d in models}))

    return DeprecationCatalogResponse(
        deprecations=models,
        total_count=len(models),
        regulators=unique_regulators,
    )


@app.post(
    "/v1/compliance/check-supersession",
    response_model=CheckSupersessionResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def check_supersession_endpoint(
    payload: CheckSupersessionRequest,
    fingerprint: str = Depends(require_api_key),
) -> CheckSupersessionResponse:
    """Scan policy documents or audit texts for superseded circulars and outdated practices (FEAT-031)."""
    t0 = time.perf_counter()
    from app.compliance.deprecation_engine import get_default_deprecation_engine

    engine = get_default_deprecation_engine()
    detections = engine.scan_text(
        text=payload.text,
        as_of_date=payload.as_of_date,
        regulator_filter=payload.regulator,
    )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.DEPRECATION_SCAN_DURATION_SECONDS.observe(latency_ms / 1000.0)
    metrics.STATUTORY_DEPRECATIONS_CHECKED_TOTAL.labels(
        has_findings="yes" if detections else "no"
    ).inc()

    for det in detections:
        metrics.STATUTORY_DEPRECATIONS_DETECTED_TOTAL.labels(
            regulator=det.regulator,
            severity=det.severity,
        ).inc()

    crit_cnt = sum(1 for d in detections if d.severity == "CRITICAL")
    high_cnt = sum(1 for d in detections if d.severity == "HIGH")
    med_cnt = sum(1 for d in detections if d.severity == "MEDIUM")
    low_cnt = sum(1 for d in detections if d.severity == "LOW")

    recommended_actions: list[str] = []
    for d in detections:
        if d.replacement:
            reps = ", ".join(d.replacement)
            recommended_actions.append(f"Replace '{d.subject}' with: {reps}")

    detection_models = [DeprecationDetectionModel(**d.to_dict()) for d in detections]

    return CheckSupersessionResponse(
        detections=detection_models,
        total_flagged=len(detection_models),
        critical_count=crit_cnt,
        high_count=high_cnt,
        medium_count=med_cnt,
        low_count=low_cnt,
        is_compliant=len(detection_models) == 0,
        recommended_actions=recommended_actions,
        latency_ms=round(latency_ms, 3),
    )


@app.get(
    "/v1/compliance/supersession-chain/{instrument_id}",
    response_model=SupersessionChainModel,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "instrument not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_supersession_chain_endpoint(
    instrument_id: str,
    fingerprint: str = Depends(require_api_key),
) -> SupersessionChainModel:
    """Trace complete historical lineage from legacy circular to active authority (FEAT-031)."""
    from app.compliance.deprecation_engine import get_default_deprecation_engine

    engine = get_default_deprecation_engine()
    chain = engine.get_supersession_chain(instrument_id)
    metrics.SUPERSESSION_CHAINS_RESOLVED_TOTAL.labels(root_instrument=instrument_id[:32]).inc()

    node_models = [
        SupersessionNodeModel(
            instrument_id=n.instrument_id,
            title=n.title,
            regulator=n.regulator,
            status=n.status,
            effective_date=n.effective_date,
            is_currently_active=n.is_currently_active,
        )
        for n in chain.chain
    ]

    return SupersessionChainModel(
        root_instrument=chain.root_instrument,
        active_authority=chain.active_authority,
        depth=chain.depth,
        has_cycle=chain.has_cycle,
        chain=node_models,
    )


# --- Circular Clause Conflict Detector (FEAT-032) ---


@app.get(
    "/v1/compliance/conflicts/clauses",
    response_model=list[CircularClauseModel],
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_regulatory_clauses_endpoint(
    domain_category: str | None = None,
    fingerprint: str = Depends(require_api_key),
) -> list[CircularClauseModel]:
    """List registered circular clauses for conflict and contradiction inspection (FEAT-032)."""
    from app.compliance.clause_conflict import get_default_clause_conflict_detector

    detector = get_default_clause_conflict_detector()
    clauses = detector.list_clauses(domain_category=domain_category)
    return [CircularClauseModel(**c.to_dict()) for c in clauses]


@app.post(
    "/v1/compliance/detect-conflicts",
    response_model=DetectConflictsResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def detect_circular_conflicts_endpoint(
    payload: DetectConflictsRequest,
    fingerprint: str = Depends(require_api_key),
) -> DetectConflictsResponse:
    """Analyze regulatory clauses to identify inter-circular contradictions and ambiguities (FEAT-032)."""
    t0 = time.perf_counter()
    from app.compliance.clause_conflict import (
        CircularClause,
        ClauseModality,
        get_default_clause_conflict_detector,
    )

    detector = get_default_clause_conflict_detector()

    custom_clauses: list[CircularClause] | None = None
    if payload.clauses is not None:
        custom_clauses = []
        for c in payload.clauses:
            modality_val = ClauseModality.MANDATORY
            if c.modality.lower() in {"prohibited", "forbidden"}:
                modality_val = ClauseModality.PROHIBITED
            elif c.modality.lower() in {"permitted", "optional", "discretionary"}:
                modality_val = ClauseModality.PERMITTED

            custom_clauses.append(
                CircularClause(
                    id=c.id,
                    circular_id=c.circular_id,
                    circular_title=c.circular_title,
                    regulator=c.regulator,
                    section_reference=c.section_reference,
                    clause_text=c.clause_text,
                    domain_category=c.domain_category,
                    modality=modality_val,
                    parameter_name=c.parameter_name,
                    parameter_value=c.parameter_value,
                    parameter_unit=c.parameter_unit,
                    comparison_operator=c.comparison_operator,
                    effective_date=c.effective_date,
                    is_active=c.is_active,
                )
            )

    conflicts = detector.detect_conflicts(clauses=custom_clauses)
    if payload.domain_category:
        conflicts = [
            conf
            for conf in conflicts
            if conf.clause_a.domain_category.lower() == payload.domain_category.lower()
        ]

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.CONFLICT_SCAN_DURATION_SECONDS.observe(latency_ms / 1000.0)
    metrics.CIRCULAR_CONFLICTS_CHECKED_TOTAL.labels(
        has_conflicts="yes" if conflicts else "no"
    ).inc()

    for conf in conflicts:
        metrics.CIRCULAR_CONFLICTS_DETECTED_TOTAL.labels(
            conflict_type=conf.conflict_type.value,
            severity=conf.severity.value,
        ).inc()

    crit_cnt = sum(1 for c in conflicts if c.severity.value == "CRITICAL")
    high_cnt = sum(1 for c in conflicts if c.severity.value == "HIGH")
    med_cnt = sum(1 for c in conflicts if c.severity.value == "MEDIUM")
    affected_domains = sorted(list({c.clause_a.domain_category for c in conflicts}))

    conflict_models = [
        DetectedConflictModel(
            conflict_id=c.conflict_id,
            clause_a=CircularClauseModel(**c.clause_a.to_dict()),
            clause_b=CircularClauseModel(**c.clause_b.to_dict()),
            conflict_type=c.conflict_type.value,
            severity=c.severity.value,
            parameter_name=c.parameter_name,
            explanation=c.explanation,
            prescriptive_action=c.prescriptive_action,
        )
        for c in conflicts
    ]

    return DetectConflictsResponse(
        conflicts=conflict_models,
        total_conflicts=len(conflict_models),
        critical_count=crit_cnt,
        high_count=high_cnt,
        medium_count=med_cnt,
        has_conflicts=len(conflict_models) > 0,
        domains_affected=affected_domains,
        latency_ms=round(latency_ms, 3),
    )


@app.post(
    "/v1/compliance/compare-clause-pair",
    response_model=CompareClausePairResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def compare_clause_pair_endpoint(
    payload: CompareClausePairRequest,
    fingerprint: str = Depends(require_api_key),
) -> CompareClausePairResponse:
    """Perform pairwise conflict check between two specific regulatory clauses (FEAT-032)."""
    t0 = time.perf_counter()
    from app.compliance.clause_conflict import get_default_clause_conflict_detector

    detector = get_default_clause_conflict_detector()
    conflict = detector.scan_clause_pair(
        payload.clause_a.model_dump(),
        payload.clause_b.model_dump(),
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    conflict_model: DetectedConflictModel | None = None
    if conflict is not None:
        conflict_model = DetectedConflictModel(
            conflict_id=conflict.conflict_id,
            clause_a=CircularClauseModel(**conflict.clause_a.to_dict()),
            clause_b=CircularClauseModel(**conflict.clause_b.to_dict()),
            conflict_type=conflict.conflict_type.value,
            severity=conflict.severity.value,
            parameter_name=conflict.parameter_name,
            explanation=conflict.explanation,
            prescriptive_action=conflict.prescriptive_action,
        )

    return CompareClausePairResponse(
        conflict_detected=conflict is not None,
        conflict=conflict_model,
        latency_ms=round(latency_ms, 3),
    )


@app.get(
    "/v1/compliance/conflicts/benchmark",
    response_model=ConflictBenchmarkResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def evaluate_conflicts_benchmark_endpoint(
    fingerprint: str = Depends(require_api_key),
) -> ConflictBenchmarkResponse:
    """Execute synthetic contradiction test set benchmark evaluation (FEAT-032)."""
    from app.compliance.clause_conflict import get_default_clause_conflict_detector

    detector = get_default_clause_conflict_detector()
    bench = detector.evaluate_synthetic_benchmark()

    return ConflictBenchmarkResponse(
        total_conflicting_pairs=bench["total_conflicting_pairs"],
        detected_conflicts=bench["detected_conflicts"],
        detection_rate=bench["detection_rate"],
        total_non_conflicting_pairs=bench["total_non_conflicting_pairs"],
        false_positives=bench["false_positives"],
        precision=bench["precision"],
        benchmark_passed=bench["benchmark_passed"],
    )


# --- Regulatory & Technical Antipattern Scanner (FEAT-033) ---


@app.get(
    "/v1/compliance/antipatterns/catalog",
    response_model=AntipatternCatalogResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_antipatterns_catalog_endpoint(
    domain_category: str | None = None,
    severity: str | None = None,
    fingerprint: str = Depends(require_api_key),
) -> AntipatternCatalogResponse:
    """Retrieve catalog of all 30 canonical taxonomy antipatterns and replacements (FEAT-033)."""
    from app.compliance.antipattern_scanner import get_default_antipattern_scanner

    scanner = get_default_antipattern_scanner()
    rules = scanner.list_rules(domain_category=domain_category, severity=severity)
    models = [AntipatternRuleModel(**r.to_dict()) for r in rules]
    domains = sorted(list({r.domain_category for r in models}))

    return AntipatternCatalogResponse(
        rules=models,
        total_count=len(models),
        domains=domains,
    )


@app.post(
    "/v1/compliance/antipatterns/scan",
    response_model=ScanAntipatternsResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def scan_antipatterns_endpoint(
    payload: ScanAntipatternsRequest,
    fingerprint: str = Depends(require_api_key),
) -> ScanAntipatternsResponse:
    """Scan policy manuals or architecture documents against the 30 taxonomy antipatterns (FEAT-033)."""
    t0 = time.perf_counter()
    from app.compliance.antipattern_scanner import get_default_antipattern_scanner

    scanner = get_default_antipattern_scanner()
    scan_res = scanner.scan_document(
        text=payload.text,
        document_name=payload.document_name,
        severity_filter=payload.severity_filter,
    )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.ANTIPATTERN_SCAN_DURATION_SECONDS.observe(latency_ms / 1000.0)
    metrics.ANTIPATTERN_SCANS_TOTAL.labels(
        has_findings="yes" if scan_res["total_findings"] > 0 else "no"
    ).inc()

    for finding in scan_res["findings"]:
        metrics.ANTIPATTERNS_DETECTED_TOTAL.labels(
            domain=finding["domain_category"],
            severity=finding["severity"],
        ).inc()

    finding_models = [AntipatternFindingModel(**f) for f in scan_res["findings"]]

    return ScanAntipatternsResponse(
        document_name=scan_res["document_name"],
        findings=finding_models,
        total_findings=scan_res["total_findings"],
        critical_count=scan_res["critical_count"],
        high_count=scan_res["high_count"],
        medium_count=scan_res["medium_count"],
        overall_score=scan_res["overall_score"],
        affected_domains=scan_res["affected_domains"],
        is_healthy=scan_res["overall_score"] >= 90.0
        and scan_res["critical_count"] == 0
        and scan_res["high_count"] == 0,
        latency_ms=round(latency_ms, 3),
    )


@app.get(
    "/v1/compliance/antipatterns/benchmark",
    response_model=AntipatternBenchmarkResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def evaluate_antipatterns_benchmark_endpoint(
    fingerprint: str = Depends(require_api_key),
) -> AntipatternBenchmarkResponse:
    """Execute synthetic compliance manual antipattern detection benchmark (FEAT-033)."""
    from app.compliance.antipattern_scanner import get_default_antipattern_scanner

    scanner = get_default_antipattern_scanner()
    bench = scanner.evaluate_synthetic_benchmark()

    return AntipatternBenchmarkResponse(
        total_seeded_antipatterns=bench["total_seeded_antipatterns"],
        detected_antipatterns=bench["detected_antipatterns"],
        false_positives=bench["false_positives"],
        false_negatives=bench["false_negatives"],
        recall=bench["recall"],
        precision=bench["precision"],
        overall_score=bench["overall_score"],
        benchmark_passed=bench["benchmark_passed"],
    )


# --- "Instead-Of" Prescriptive Remediation Engine (FEAT-034) ---


@app.post(
    "/v1/compliance/remediation/plan",
    response_model=RemediationPlanModel,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def generate_remediation_plan_endpoint(
    payload: GenerateRemediationRequest,
    fingerprint: str = Depends(require_api_key),
) -> RemediationPlanModel:
    """Generate prescriptive alternative practices ('Instead-Of') for a flaw (FEAT-034)."""
    t0 = time.perf_counter()
    from app.compliance.remediation_engine import get_default_remediation_engine

    engine = get_default_remediation_engine()
    flaw_key = payload.flaw_id or payload.practice_or_subject
    if not flaw_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either flaw_id or practice_or_subject must be provided.",
        )

    plan = engine.get_remediation_by_flaw_id(
        flaw_key, include_steps=payload.include_implementation_steps
    )
    if not plan and payload.practice_or_subject:
        plan = engine.get_remediation_for_antipattern(
            payload.practice_or_subject, include_steps=payload.include_implementation_steps
        ) or engine.get_remediation_for_deprecation(
            payload.practice_or_subject, include_steps=payload.include_implementation_steps
        )

    if not plan:
        plan = engine.generate_remediation_for_finding(
            {"rule_id": flaw_key, "practice": flaw_key},
            include_steps=payload.include_implementation_steps,
        )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.REMEDIATION_LOOKUP_DURATION_SECONDS.observe(latency_ms / 1000.0)
    metrics.REMEDIATIONS_GENERATED_TOTAL.labels(
        flaw_type=plan.flaw_type,
        has_remediation="yes" if len(plan.recommended_practices) > 0 else "no",
    ).inc()

    recs = [PracticeRecommendationModel(**r.to_dict()) for r in plan.recommended_practices]
    return RemediationPlanModel(
        flaw_id=plan.flaw_id,
        flaw_type=plan.flaw_type,
        identified_flaw=plan.identified_flaw,
        consequence_or_reason=plan.consequence_or_reason,
        severity=plan.severity,
        recommended_practices=recs,
        guidance=plan.guidance,
        lookup_latency_ms=round(latency_ms, 3),
    )


@app.post(
    "/v1/compliance/remediation/batch",
    response_model=BatchRemediationResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def batch_remediation_endpoint(
    payload: BatchRemediationRequest,
    fingerprint: str = Depends(require_api_key),
) -> BatchRemediationResponse:
    """Generate prescriptive remediation plans for a batch of flaw IDs (FEAT-034)."""
    t0 = time.perf_counter()
    from app.compliance.remediation_engine import get_default_remediation_engine

    engine = get_default_remediation_engine()
    raw_findings = [{"rule_id": fid} for fid in payload.flaw_ids]
    report = engine.generate_remediation_report(
        raw_findings, include_steps=payload.include_implementation_steps
    )

    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.REMEDIATION_LOOKUP_DURATION_SECONDS.observe(latency_ms / 1000.0)
    for p in report.plans:
        metrics.REMEDIATIONS_GENERATED_TOTAL.labels(
            flaw_type=p.flaw_type,
            has_remediation="yes" if len(p.recommended_practices) > 0 else "no",
        ).inc()

    plan_models = []
    for p in report.plans:
        recs = [PracticeRecommendationModel(**r.to_dict()) for r in p.recommended_practices]
        plan_models.append(
            RemediationPlanModel(
                flaw_id=p.flaw_id,
                flaw_type=p.flaw_type,
                identified_flaw=p.identified_flaw,
                consequence_or_reason=p.consequence_or_reason,
                severity=p.severity,
                recommended_practices=recs,
                guidance=p.guidance,
                lookup_latency_ms=round(p.lookup_latency_ms, 3),
            )
        )

    return BatchRemediationResponse(
        total_findings=report.total_findings,
        remediated_findings=report.remediated_findings,
        plans=plan_models,
        unique_recommended_practices=report.unique_recommended_practices,
        latency_ms=round(latency_ms, 3),
    )


@app.get(
    "/v1/compliance/remediation/catalog",
    response_model=RemediationCatalogResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def remediation_catalog_endpoint(
    flaw_type: str | None = None,
    tier: int | None = None,
    fingerprint: str = Depends(require_api_key),
) -> RemediationCatalogResponse:
    """Retrieve full catalog of prescriptive alternative practices (FEAT-034)."""
    from app.compliance.remediation_engine import get_default_remediation_engine

    engine = get_default_remediation_engine()
    plans = engine.list_catalog(flaw_type=flaw_type, tier=tier)
    plan_models = []
    total_recs = 0
    for p in plans:
        recs = [PracticeRecommendationModel(**r.to_dict()) for r in p.recommended_practices]
        total_recs += len(recs)
        plan_models.append(
            RemediationPlanModel(
                flaw_id=p.flaw_id,
                flaw_type=p.flaw_type,
                identified_flaw=p.identified_flaw,
                consequence_or_reason=p.consequence_or_reason,
                severity=p.severity,
                recommended_practices=recs,
                guidance=p.guidance,
                lookup_latency_ms=round(p.lookup_latency_ms, 3),
            )
        )

    return RemediationCatalogResponse(
        total_plans=len(plan_models),
        total_practices_mapped=total_recs,
        plans=plan_models,
    )


# --- Sunset Clause & Mandatory Cutover Alerting (FEAT-035) ---


@app.post(
    "/v1/ingest/deadlines/extract",
    response_model=ExtractDeadlinesResponse,
    tags=["ingest"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def extract_deadlines_endpoint(
    payload: ExtractDeadlinesRequest,
    fingerprint: str = Depends(require_api_key),
) -> ExtractDeadlinesResponse:
    """Extract transition deadlines, cutover dates, and sunset clauses from circular text (FEAT-035)."""
    t0 = time.perf_counter()
    from datetime import date

    from app.ingest.deadline_extractor import DeadlineAlertConfig, DeadlineExtractor

    config = DeadlineAlertConfig(
        critical_threshold_days=payload.critical_threshold_days,
        warning_threshold_days=payload.warning_threshold_days,
    )
    extractor = DeadlineExtractor(config=config)

    ref_date = None
    if payload.reference_date:
        try:
            ref_date = date.fromisoformat(payload.reference_date)
        except ValueError as val_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid reference_date format; expected YYYY-MM-DD",
            ) from val_err

    try:
        deadlines = extractor.extract(
            text=payload.text,
            doc_id=payload.doc_id,
            reference_date=ref_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    deadline_models = [
        RegulatoryDeadlineModel(
            doc_id=d.doc_id,
            mandate_description=d.mandate_description,
            effective_date=d.effective_date.isoformat(),
            days_remaining=d.days_remaining,
            urgency_level=d.urgency_level,
            extracted_snippet=d.extracted_snippet,
            confidence=d.confidence,
        )
        for d in deadlines
    ]

    latency_ms = (time.perf_counter() - t0) * 1000.0
    return ExtractDeadlinesResponse(
        doc_id=payload.doc_id,
        total_deadlines=len(deadline_models),
        deadlines=deadline_models,
        latency_ms=round(latency_ms, 3),
    )


@app.post(
    "/v1/compliance/deadlines/dispatch-alerts",
    response_model=DispatchDeadlineAlertsResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def dispatch_deadline_alerts_endpoint(
    payload: DispatchDeadlineAlertsRequest,
    fingerprint: str = Depends(require_api_key),
) -> DispatchDeadlineAlertsResponse:
    """Dispatch countdown alerts for pending regulatory cutovers (FEAT-035)."""
    from datetime import date

    from app.digests.deadline_notifier import DeadlineNotifier
    from app.ingest.deadline_extractor import RegulatoryDeadline

    deadlines = [
        RegulatoryDeadline(
            doc_id=d.doc_id,
            mandate_description=d.mandate_description,
            effective_date=date.fromisoformat(d.effective_date),
            days_remaining=d.days_remaining,
            urgency_level=d.urgency_level,
            extracted_snippet=d.extracted_snippet,
            confidence=d.confidence,
        )
        for d in payload.deadlines
    ]

    pool = getattr(app.state, "pool", None)
    notifier = DeadlineNotifier(pool=pool)
    result = notifier.dispatch_alerts(
        deadlines=deadlines,
        recipients=payload.recipients,
        dry_run=payload.dry_run,
    )

    return DispatchDeadlineAlertsResponse(
        total_checked=result.total_checked,
        alerts_dispatched=result.alerts_dispatched,
        critical_count=result.critical_count,
        warning_count=result.warning_count,
        info_count=result.info_count,
        duration_ms=round(result.duration_ms, 3),
    )


# --- Grandfathering & Exemption Scope Engine (FEAT-036) ---


@app.post(
    "/v1/ingest/scope/classify",
    response_model=ClassifyScopeResponse,
    tags=["ingest"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def classify_scope_endpoint(
    payload: ClassifyScopeRequest,
    fingerprint: str = Depends(require_api_key),
) -> ClassifyScopeResponse:
    """Classify regulatory clause into applicability scope (FEAT-036)."""
    t0 = time.perf_counter()
    from app.ingest.scope_classifier import ScopeClassifier

    classifier = ScopeClassifier()
    try:
        res = classifier.classify(payload.text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    latency_ms = (time.perf_counter() - t0) * 1000.0
    return ClassifyScopeResponse(
        scope=res.scope,
        confidence=res.confidence,
        operative_condition=res.operative_condition,
        latency_ms=round(latency_ms, 3),
    )


# --- Regulatory Risk Scorecard Generator (FEAT-040) ---


@app.post(
    "/v1/compliance/scorecard",
    response_model=ScorecardResponse,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request input"},
        429: {"description": "rate limit exceeded"},
    },
)
def generate_regulatory_risk_scorecard(
    payload: ScorecardRequest,
    fingerprint: str = Depends(require_api_key),
) -> ScorecardResponse:
    """Generate executive regulatory risk scorecard from policy document dossier (FEAT-040)."""
    t0 = time.perf_counter()
    from app.compliance.scorecard import RegulatoryRiskScorecardEngine

    engine = RegulatoryRiskScorecardEngine()
    result = engine.generate_scorecard(
        policy_document_texts=payload.policy_document_texts,
        organization_type=payload.organization_type,
        include_pdf=payload.include_pdf,
        rubric_weights=payload.grading_rubric_weights,
    )

    metrics.SCORECARDS_GENERATED_TOTAL.labels(grade=result.overall_grade).inc()
    duration_s = time.perf_counter() - t0
    metrics.SCORECARD_DURATION_SECONDS.observe(duration_s)

    return ScorecardResponse(
        overall_grade=result.overall_grade,
        numerical_score=result.numerical_score,
        antipatterns_count=len(result.antipattern_findings),
        deprecations_count=len(result.deprecation_detections),
        standards_coverage_score=result.standards_coverage_score,
        critical_risks=result.critical_risks,
        remediation_timeline_days=result.remediation_timeline_days,
        markdown_report=result.markdown_report,
        pdf_content_base64=result.pdf_base64,
        latency_ms=round(duration_s * 1000.0, 3),
    )


# --- Multi-Jurisdiction Compliance Harmonizer (FEAT-043) ---


@app.post(
    "/v1/compliance/harmonize",
    response_model=HarmonizationReport,
    tags=["compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "unknown jurisdiction or invalid input"},
        429: {"description": "rate limit exceeded"},
    },
)
def harmonize_compliance_endpoint(
    payload: HarmonizeRequest,
    fingerprint: str = Depends(require_api_key),
) -> HarmonizationReport:
    """Execute multi-jurisdiction comparative regulatory analysis and statutory delta classification (FEAT-043)."""
    t0 = time.perf_counter()
    from app.compliance.harmonizer import get_default_compliance_harmonizer

    harmonizer = get_default_compliance_harmonizer()
    try:
        raw_result = harmonizer.harmonize(
            topic=payload.topic,
            jurisdiction_a=payload.jurisdiction_a,
            jurisdiction_b=payload.jurisdiction_b,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    metrics.HARMONIZATIONS_PERFORMED_TOTAL.labels(
        delta_classification=raw_result["delta_classification"],
        topic=raw_result["topic"],
    ).inc()
    duration_s = time.perf_counter() - t0
    metrics.HARMONIZATION_DURATION_SECONDS.observe(duration_s)

    return HarmonizationReport(
        topic=raw_result["topic"],
        jurisdiction_a=raw_result["jurisdiction_a"],
        jurisdiction_b=raw_result["jurisdiction_b"],
        delta_classification=raw_result["delta_classification"],
        comparative_analysis=raw_result["comparative_analysis"],
        localized_mandates=raw_result["localized_mandates"],
        confidence_score=raw_result["confidence_score"],
        statutory_citations=raw_result["statutory_citations"],
        latency_ms=round(duration_s * 1000.0, 3),
    )


@app.get(
    "/v1/search/suggestions",
    response_model=SuggestionResponse,
    tags=["search"],
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request"},
        429: {"description": "rate limit exceeded"},
    },
)
def search_suggestions(
    request: Request,
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=128,
            description="Query prefix or fragment to suggest completions for",
        ),
    ],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=50,
            description="Maximum suggestions to return",
        ),
    ] = 10,
    include_related: Annotated[
        bool,
        Query(
            description="Include related search queries synthesized from graph edges",
        ),
    ] = True,
    enable_normalization: Annotated[
        bool,
        Query(
            description="Apply typo-tolerant regulatory token normalization",
        ),
    ] = True,
    fingerprint: str = Depends(require_api_key),
) -> SuggestionResponse:
    """Provide real-time interactive search suggestions and deeper statutory inquiries (FEAT-019)."""
    state = request.app.state
    suggester = getattr(state, "suggester", None)
    if suggester is None or not hasattr(suggester, "suggest"):
        from app.retrieval.suggester import get_default_suggester

        suggester = get_default_suggester()
        state.suggester = suggester

    return suggester.suggest(
        query=q,
        limit=limit,
        include_related=include_related,
        enable_normalization=enable_normalization,
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


# --- Knowledge Graph Subgraph Projection (FEAT-004) ---


@app.get(
    "/v1/graph/subgraph/{doc_id}",
    response_model=SubgraphResponse,
    tags=["graph"],
    responses={
        401: {"description": "missing or invalid API key"},
        404: {"description": "document or concept not found"},
        422: {"description": "invalid parameters"},
    },
)
def get_subgraph_endpoint(
    doc_id: Annotated[str, FastApiPath(pattern=r"^doc-[a-z0-9\-]+$")],
    request: Request,
    depth: Annotated[int, Query(ge=1, le=2)] = 2,
    max_nodes: Annotated[int, Query(ge=5, le=50)] = 25,
    fingerprint: str = Depends(require_api_key),
) -> SubgraphResponse:
    """Extract and project a 2-hop concept subgraph around a regulatory document."""
    state = request.app.state

    # 1. Try querying PostgreSQL knowledge graph tables if database pool is available
    found_in_db = False
    db_nodes: list[GraphNode] = []
    db_edges: list[GraphEdge] = []

    if hasattr(state, "pool") and state.pool is not None:
        try:
            with state.pool.connection() as conn:
                row = conn.execute(
                    """
                    SELECT node_id, label, node_type
                      FROM graph_nodes
                     WHERE node_id = %s OR node_id = %s
                     LIMIT 1
                    """,
                    (doc_id, f"doc:{doc_id.removeprefix('doc-')}"),
                ).fetchone()

                if row is not None:
                    found_in_db = True
                    root_node_id = str(row[0])
                    root_label = str(row[1])
                    root_type = str(row[2])
                    db_nodes.append(
                        GraphNode(id=doc_id, label=root_label, domain="regulatory", level=root_type)
                    )

                    edge_rows = conn.execute(
                        """
                        SELECT source_node_id, target_node_id, relation
                          FROM graph_edges
                         WHERE source_node_id = %s OR target_node_id = %s
                         LIMIT %s
                        """,
                        (root_node_id, root_node_id, max_nodes),
                    ).fetchall()

                    seen_node_ids = {doc_id, root_node_id}
                    for e_src, e_tgt, rel in edge_rows:
                        db_edges.append(
                            GraphEdge(source=str(e_src), target=str(e_tgt), relation=str(rel))
                        )
                        seen_node_ids.add(str(e_src))
                        seen_node_ids.add(str(e_tgt))

                    if len(seen_node_ids) > 1:
                        other_ids = [
                            nid for nid in seen_node_ids if nid not in (doc_id, root_node_id)
                        ]
                        n_rows = conn.execute(
                            "SELECT node_id, label, node_type FROM graph_nodes WHERE node_id = ANY(%s) LIMIT %s",
                            (other_ids, max(0, max_nodes - len(db_nodes))),
                        ).fetchall()
                        for nid, nlbl, ntyp in n_rows:
                            db_nodes.append(
                                GraphNode(
                                    id=str(nid),
                                    label=str(nlbl),
                                    domain="regulatory",
                                    level=str(ntyp),
                                )
                            )
        except Exception:
            logger.warning("graph_subgraph_db_lookup_failed", doc_id=doc_id, exc_info=True)

    if found_in_db:
        return SubgraphResponse(nodes=db_nodes[:max_nodes], edges=db_edges, root_id=doc_id)

    # 2. Check canonical document seeds & statutory entities (FEAT-002 taxonomy hierarchy)
    from app.retrieval.entity_linker import STATUTORY_ENTITIES

    known_docs: dict[str, dict[str, Any]] = {
        "doc-noti280digitallending": {
            "label": "Digital Lending Guidelines (RBI/2022-23/111)",
            "entities": ["commercial_bank", "nbfc", "payment_system_operator"],
        },
        "doc-noti27401102026": {
            "label": "RBI Master Direction on IT Governance",
            "entities": ["commercial_bank", "nbfc"],
        },
        "doc-sebi-lodr": {
            "label": "SEBI Listing Obligations & Disclosure Requirements",
            "entities": ["sebi_market_intermediary"],
        },
    }

    doc_info = known_docs.get(doc_id)
    if doc_info is None:
        clean_name = doc_id.removeprefix("doc-").replace("-", "_")
        entity_match = next((e for e in STATUTORY_ENTITIES if e.entity_id == clean_name), None)
        if entity_match is not None:
            doc_info = {
                "label": entity_match.canonical_name,
                "entities": [entity_match.entity_id],
            }

    if doc_info is None:
        raise StarletteHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document or concept {doc_id!r} not found in knowledge graph",
        )

    nodes_map: dict[str, GraphNode] = {
        doc_id: GraphNode(
            id=doc_id, label=str(doc_info["label"]), domain="regulatory", level="statutory"
        ),
    }
    edges_list: list[GraphEdge] = []
    entity_dict = {e.entity_id: e for e in STATUTORY_ENTITIES}

    # Hop 1: Connect doc to linked entities
    for ent_id in doc_info["entities"]:
        ent = entity_dict.get(ent_id)
        if ent is not None and len(nodes_map) < max_nodes:
            nodes_map[ent.entity_id] = GraphNode(
                id=ent.entity_id, label=ent.canonical_name, domain="regulatory", level="entity"
            )
            edges_list.append(GraphEdge(source=doc_id, target=ent.entity_id, relation="governs"))

    # Hop 2: Connect entities to their parents / children if depth >= 2
    if depth >= 2:
        for ent_id in list(doc_info["entities"]):
            ent = entity_dict.get(ent_id)
            if ent is None:
                continue
            for ch_id in ent.child_ids:
                if len(nodes_map) >= max_nodes:
                    break
                ch = entity_dict.get(ch_id)
                if ch is not None:
                    if ch.entity_id not in nodes_map:
                        nodes_map[ch.entity_id] = GraphNode(
                            id=ch.entity_id,
                            label=ch.canonical_name,
                            domain="regulatory",
                            level="subclass",
                        )
                    edges_list.append(
                        GraphEdge(source=ent.entity_id, target=ch.entity_id, relation="subclass_of")
                    )
            for p_id in ent.parent_ids:
                if len(nodes_map) >= max_nodes:
                    break
                p = entity_dict.get(p_id)
                if p is not None:
                    if p.entity_id not in nodes_map:
                        nodes_map[p.entity_id] = GraphNode(
                            id=p.entity_id,
                            label=p.canonical_name,
                            domain="regulatory",
                            level="category",
                        )
                    edges_list.append(
                        GraphEdge(
                            source=p.entity_id, target=ent.entity_id, relation="super_category"
                        )
                    )

    return SubgraphResponse(
        nodes=list(nodes_map.values())[:max_nodes],
        edges=edges_list,
        root_id=doc_id,
    )


@app.get("/v1/taxonomy/dictionary")
def get_taxonomy_dictionary_endpoint(response: Response) -> dict[str, Any]:
    """Public taxonomy dictionary serving canonical terms, definitions, and anchors (FEAT-007)."""
    from app.retrieval.taxonomy_loader import get_taxonomy_dictionary

    response.headers["Cache-Control"] = "public, max-age=86400"
    return get_taxonomy_dictionary()


@app.get(
    "/v1/standards",
    response_model=StandardsListResponse,
    tags=["standards", "compliance"],
    responses={
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def list_standards_endpoint(
    domain: str | None = Query(default=None, description="Filter standards by domain category"),
    governing_body: str | None = Query(
        default=None, description="Filter standards by governing body"
    ),
    search: str | None = Query(
        default=None, description="Free-text search query across standards metadata"
    ),
    fingerprint: str = Depends(require_api_key),
) -> StandardsListResponse:
    """Query unified regulatory and technical standards registry (FEAT-041)."""
    from app.compliance.standards_registry import get_default_standards_registry

    t0 = time.perf_counter()
    reg = get_default_standards_registry()

    if search:
        stds = reg.search_standards(search)
        if domain:
            dom_norm = domain.strip().lower()
            stds = [s for s in stds if s.domain.lower() == dom_norm]
        if governing_body:
            gb_norm = governing_body.strip().lower()
            stds = [s for s in stds if s.governing_body.lower() == gb_norm]
    else:
        stds = reg.list_standards(domain=domain, governing_body=governing_body)

    results = [StandardMetadata(**s.to_metadata_dict()) for s in stds]
    duration_s = time.perf_counter() - t0
    metrics.STANDARDS_QUERY_DURATION_SECONDS.observe(duration_s)

    return StandardsListResponse(
        standards=results,
        total=len(results),
        domains=reg.get_domains(),
        governing_bodies=reg.get_governing_bodies(),
    )


@app.get(
    "/v1/standards/crosswalk",
    response_model=CrosswalkResponse,
    tags=["standards", "compliance"],
    responses={
        400: {"description": "invalid framework identifier or parameter format"},
        401: {"description": "missing or invalid API key"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_standards_crosswalk_endpoint(
    response: Response,
    source_framework: str = Query(..., description="Source standard or regulatory framework"),
    target_framework: str = Query(..., description="Target standard or regulatory framework"),
    control_id: str | None = Query(
        default=None, description="Optional control identifier to filter"
    ),
    fingerprint: str = Depends(require_api_key),
) -> CrosswalkResponse:
    """Establish bidirectional cross-framework control mapping matrix (FEAT-042)."""
    from app.compliance.control_mapper import get_default_control_mapper

    t0 = time.perf_counter()
    mapper = get_default_control_mapper()

    try:
        raw_result = mapper.get_crosswalk(
            source_framework=source_framework,
            target_framework=target_framework,
            control_id=control_id,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    canon_src = raw_result["source_framework"]
    canon_tgt = raw_result["target_framework"]

    metrics.CROSSWALK_QUERIES_TOTAL.labels(source=canon_src, target=canon_tgt).inc()
    duration_s = time.perf_counter() - t0
    metrics.CROSSWALK_QUERY_DURATION_SECONDS.observe(duration_s)

    response.headers["Cache-Control"] = "public, max-age=86400"

    return CrosswalkResponse(
        source_framework=raw_result["source_framework"],
        target_framework=raw_result["target_framework"],
        source_control=raw_result["source_control"],
        source_control_title=raw_result["source_control_title"],
        target_controls=[MappedControl(**tc) for tc in raw_result["target_controls"]],
        citation_spans=raw_result["citation_spans"],
        equivalence_summary=raw_result["equivalence_summary"],
        coverage_percentage=raw_result.get("coverage_percentage"),
        total_mappings=raw_result["total_mappings"],
        mappings=raw_result.get("mappings"),
    )


@app.get(
    "/v1/standards/{standard_id:path}",
    response_model=StandardMetadata,
    tags=["standards", "compliance"],
    responses={
        400: {"description": "invalid standard identifier format"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "standard not found"},
        429: {"description": "rate limit exceeded"},
    },
)
def get_standard_endpoint(
    standard_id: str,
    fingerprint: str = Depends(require_api_key),
) -> StandardMetadata:
    """Retrieve full authority metadata, control families, and statutory scope for a standard (FEAT-041)."""
    from app.compliance.standards_registry import get_default_standards_registry

    t0 = time.perf_counter()
    std_id_clean = standard_id.strip()

    # Input validation pattern per spec: ^[A-Z0-9\-\.\/ ]+$ (case-insensitive with syntax punctuation)
    if not re.match(r"^[a-zA-Z0-9\-\.\/:\(\)_, ]+$", std_id_clean):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Standard identifier '{standard_id}' contains invalid characters.",
        )

    reg = get_default_standards_registry()
    std = reg.get_standard(std_id_clean)

    if std is None:
        closest = [s.id for s in reg.search_standards(std_id_clean)[:5]]
        all_ids = reg.get_all_standard_ids()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://docscout.internal/errors/standard-not-found",
                "title": "Standard Not Found",
                "status": 404,
                "detail": f"Standard '{std_id_clean}' not found in unified authority registry.",
                "closest_matches": closest,
                "available_standards_sample": all_ids[:10],
                "total_available_standards": len(all_ids),
            },
        )

    metrics.STANDARDS_QUERIED_TOTAL.labels(standard_id=std.id).inc()
    duration_s = time.perf_counter() - t0
    metrics.STANDARDS_QUERY_DURATION_SECONDS.observe(duration_s)

    return StandardMetadata(**std.to_metadata_dict())


@app.post(
    "/v1/compliance/extract-standard-mentions",
    response_model=ExtractStandardMentionsResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Standard citations extracted with character spans"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def extract_standard_mentions(
    payload: ExtractStandardMentionsRequest,
    fingerprint: str = Depends(require_api_key),
) -> ExtractStandardMentionsResponse:
    """Extract external standard mentions and control hints from circular text (FEAT-046)."""
    from app.ingest.standard_mention_extractor import StandardMentionExtractor

    extractor = StandardMentionExtractor()
    mentions = extractor.extract(
        text=payload.text,
        doc_id=payload.document_id,
        chunk_id=payload.chunk_id,
    )

    response_mentions = [
        StandardMentionResponse(
            span=list(m.span),
            raw_text=m.raw_text,
            standard_id=m.standard_id,
            control_hint=m.control_hint,
            standard_name=m.standard_name,
            governing_body=m.governing_body,
        )
        for m in mentions
    ]

    return ExtractStandardMentionsResponse(
        mentions=response_mentions,
        total_count=len(response_mentions),
    )


@app.get(
    "/v1/documents/{document_id}/standard-mentions",
    response_model=DocumentStandardMentionsResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Persisted standard mentions for the document"},
        400: {"description": "invalid document UUID"},
        401: {"description": "missing or invalid API key"},
    },
)
async def get_document_standard_mentions(
    document_id: str,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> DocumentStandardMentionsResponse:
    """Retrieve persisted standard mentions for a specific document (FEAT-046)."""
    from app.ingest.standard_mention_extractor import fetch_mentions_for_document

    doc_uuid = document_id.strip()
    try:
        uuid.UUID(doc_uuid)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document UUID format: '{document_id}'",
        ) from err

    if hasattr(request.app.state, "pool") and request.app.state.pool is not None:
        with request.app.state.pool.connection() as conn:
            mentions = fetch_mentions_for_document(conn, doc_uuid)
    else:
        with psycopg.connect(database_url()) as conn:
            mentions = fetch_mentions_for_document(conn, doc_uuid)

    response_mentions = [
        StandardMentionResponse(
            span=list(m.span),
            raw_text=m.raw_text,
            standard_id=m.standard_id,
            control_hint=m.control_hint,
            standard_name=m.standard_name,
            governing_body=m.governing_body,
        )
        for m in mentions
    ]

    return DocumentStandardMentionsResponse(
        document_id=doc_uuid,
        mentions=response_mentions,
        total_count=len(response_mentions),
    )


@app.post(
    "/v1/compliance/export-evidence",
    response_model=ExportResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Signed audit evidence dossier compiled"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def export_audit_evidence(
    payload: ExportEvidenceRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> ExportResponse:
    """Compile and export statutory audit evidence package (FEAT-047)."""
    from app.compliance.exporter import get_default_audit_exporter

    exporter = get_default_audit_exporter()

    # Resolve passages from database if available
    if hasattr(request.app.state, "pool") and request.app.state.pool is not None:
        with request.app.state.pool.connection() as conn:
            passages = exporter.resolve_passages_from_db(conn, payload.passage_ids)
    else:
        try:
            with psycopg.connect(database_url()) as conn:
                passages = exporter.resolve_passages_from_db(conn, payload.passage_ids)
        except Exception:
            passages = exporter.resolve_passages_from_db(None, payload.passage_ids)  # type: ignore[arg-type]

    try:
        artifact = exporter.export_package(
            query=payload.query,
            passages=passages,
            format=payload.format,
            audit_reference_id=payload.audit_reference_id,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    return ExportResponse(
        download_url=artifact.download_url,
        file_sha256=artifact.file_sha256,
        expires_at=artifact.expires_at,
        items_included=artifact.items_included,
        format=artifact.format,
        audit_reference_id=artifact.audit_reference_id,
    )


@app.get(
    "/v1/compliance/export-download/{file_id}",
    tags=["Compliance"],
    responses={
        200: {"description": "Downloadable audit package binary stream"},
        404: {"description": "export package not found or expired"},
    },
)
async def download_audit_evidence_package(
    file_id: str,
    fingerprint: str = Depends(require_api_key),
) -> Response:
    """Download compiled statutory audit evidence dossier (FEAT-047)."""
    from app.compliance.exporter import get_default_audit_exporter

    exporter = get_default_audit_exporter()
    artifact = exporter.get_export_artifact(file_id)

    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "https://docscout.internal/errors/export-not-found",
                "title": "Export Package Not Found or Expired",
                "status": 404,
                "detail": f"Export dossier '{file_id}' does not exist or has exceeded its 60-minute retention window.",
            },
        )

    return Response(
        content=artifact.file_bytes,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-DocScout-SHA256": artifact.file_sha256,
            "X-DocScout-Audit-Ref": artifact.audit_reference_id,
        },
    )


@app.post(
    "/v1/compliance/telemetry/ingest",
    response_model=TelemetryIngestResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Continuous compliance telemetry batch ingested"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def ingest_compliance_telemetry(
    payload: TelemetryBatch,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> TelemetryIngestResponse:
    """Ingest continuous compliance telemetry events (FEAT-048)."""
    from app.compliance.observation_tracker import get_default_observation_tracker

    tracker = get_default_observation_tracker()
    events = payload.to_events()

    pool = getattr(request.app.state, "pool", None)
    try:
        if pool is not None:
            with pool.connection() as conn:
                event_ids = tracker.ingest_batch(events, conn=conn)
        else:
            try:
                with psycopg.connect(database_url()) as conn:
                    event_ids = tracker.ingest_batch(events, conn=conn)
            except Exception:
                event_ids = tracker.ingest_batch(events, conn=None)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    return TelemetryIngestResponse(
        accepted_count=len(event_ids),
        status="INGESTED",
        event_ids=event_ids,
    )


@app.get(
    "/v1/compliance/telemetry/window/{control_id}",
    response_model=ObservationStatusResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Continuous compliance observation window status"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def get_observation_window_status(
    control_id: str,
    request: Request,
    tenant_id: str = Query(default="default", max_length=100),
    window_days: int = Query(default=90, ge=1, le=365),
    fingerprint: str = Depends(require_api_key),
) -> ObservationStatusResponse:
    """Calculate rolling continuous compliance observation window status (FEAT-048)."""
    from app.compliance.observation_tracker import get_default_observation_tracker

    ctrl_id = control_id.strip()
    if not ctrl_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="control_id cannot be empty",
        )

    tracker = get_default_observation_tracker()
    pool = getattr(request.app.state, "pool", None)
    if pool is not None:
        with pool.connection() as conn:
            status_obj = tracker.get_observation_status(
                control_id=ctrl_id,
                tenant_id=tenant_id,
                window_days=window_days,
                conn=conn,
            )
    else:
        try:
            with psycopg.connect(database_url()) as conn:
                status_obj = tracker.get_observation_status(
                    control_id=ctrl_id,
                    tenant_id=tenant_id,
                    window_days=window_days,
                    conn=conn,
                )
        except Exception:
            status_obj = tracker.get_observation_status(
                control_id=ctrl_id,
                tenant_id=tenant_id,
                window_days=window_days,
                conn=None,
            )

    return ObservationStatusResponse(
        control_id=status_obj.control_id,
        tenant_id=status_obj.tenant_id,
        observation_window_days=status_obj.observation_window_days,
        compliance_percentage=status_obj.compliance_percentage,
        unbroken_streak_days=status_obj.unbroken_streak_days,
        total_observations=status_obj.total_observations,
        pass_count=status_obj.pass_count,
        fail_count=status_obj.fail_count,
        window_start=status_obj.window_start,
        window_end=status_obj.window_end,
        status=status_obj.status,
    )


@app.post(
    "/v1/compliance/vendor-audit",
    response_model=VendorRiskReportResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Vendor contract statutory compliance evaluated"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error or invalid contract text"},
    },
)
async def audit_vendor_contract(
    payload: VendorRiskAuditRequest,
    fingerprint: str = Depends(require_api_key),
) -> VendorRiskReportResponse:
    """Evaluate third-party vendor contract against RBI and SEBI outsourcing mandates (FEAT-049)."""
    from app.compliance.vendor_risk import get_default_vendor_risk_engine

    engine = get_default_vendor_risk_engine()
    try:
        report = engine.evaluate_contract(
            contract_text=payload.contract_text,
            vendor_type=payload.vendor_type,
            vendor_name=payload.vendor_name,
            strict_localization=payload.strict_localization,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    return report


@app.post(
    "/v1/compliance/algo-assessment",
    response_model=AlgoAssessmentResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Algorithmic and AI impact assessment completed"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error or invalid system specification"},
    },
)
async def assess_algorithmic_system(
    payload: AlgoAssessmentRequest,
    fingerprint: str = Depends(require_api_key),
) -> AlgoAssessmentResponse:
    """Evaluate algorithmic trading and AI systems against SEBI and RBI regulatory checklists (FEAT-050)."""
    t0 = time.perf_counter()
    from app.compliance.algo_impact import (
        AlgoImpactConfig,
        get_default_algorithmic_impact_engine,
    )

    engine = get_default_algorithmic_impact_engine()
    cfg = AlgoImpactConfig(
        strict_kill_switch_required=payload.strict_kill_switch_required,
    )
    try:
        res = engine.evaluate(
            system_name=payload.system_name,
            model_type=payload.model_type,
            system_spec_text=payload.system_spec_text,
            config=cfg,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(err),
        ) from err

    latency_sec = time.perf_counter() - t0
    metrics.ALGO_ASSESSMENT_DURATION_SECONDS.observe(latency_sec)
    metrics.ALGO_ASSESSMENTS_COMPLETED_TOTAL.labels(
        model_type=res.model_type,
        status=res.status,
    ).inc()

    return AlgoAssessmentResponse(
        system_name=res.system_name,
        model_type=res.model_type,
        conformity_score=res.conformity_score,
        status=res.status,
        passed_controls=res.passed_controls,
        failed_controls=[
            FailedControlModel(
                control_id=fc.control_id,
                title=fc.title,
                regulation_ref=fc.regulation_ref,
                remedy=fc.remedy,
            )
            for fc in res.failed_controls
        ],
        negative_flags=res.negative_flags,
        audit_certificate_id=res.audit_certificate_id,
        evaluated_at=res.evaluated_at,
        summary=res.summary,
    )


# --- Interactive Compliance Playbook Runtime (FEAT-051 & FEAT-052) ---


@app.get(
    "/v1/playbooks/templates",
    response_model=list[PlaybookTemplateSummary],
    tags=["Playbooks"],
    responses={
        200: {"description": "List all 12 statutory compliance playbooks"},
        401: {"description": "missing or invalid API key"},
    },
)
async def list_playbook_templates(
    fingerprint: str = Depends(require_api_key),
) -> list[PlaybookTemplateSummary]:
    """List the catalog of 12 statutory compliance playbook templates (FEAT-051)."""
    from app.workflows.engine import get_default_playbook_engine

    engine = get_default_playbook_engine()
    templates = engine.list_templates()
    return [
        PlaybookTemplateSummary(
            playbook_id=t.playbook_id,
            title=t.title,
            description=t.description,
            domain=t.domain,
            total_stages=t.total_stages,
            stages=[
                StageSummaryModel(
                    number=s.stage_number,
                    name=s.stage_name,
                    objective=s.description,
                    exit_criteria=s.exit_criteria,
                    milestones=[
                        MilestoneSummaryModel(
                            id=m.id,
                            title=m.title,
                            role=m.role,
                            mandatory=m.mandatory,
                            estimated_hours=m.estimated_hours,
                            completed=False,
                            notes="",
                        )
                        for m in s.milestones
                    ],
                )
                for s in t.stages
            ],
        )
        for t in templates
    ]


@app.post(
    "/v1/playbooks/start",
    response_model=PlaybookRunResponse,
    tags=["Playbooks"],
    responses={
        200: {"description": "Playbook workflow run successfully instantiated"},
        400: {"description": "Invalid playbook ID or configuration"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook template not found"},
    },
)
async def start_playbook_run(
    payload: StartPlaybookRequest,
    fingerprint: str = Depends(require_api_key),
) -> PlaybookRunResponse:
    """Instantiate a new interactive compliance playbook run for a tenant (FEAT-051)."""
    from app.workflows.engine import (
        PlaybookNotFoundError,
        get_default_playbook_engine,
    )

    engine = get_default_playbook_engine()
    try:
        run = engine.start_playbook(
            playbook_id=payload.playbook_id,
            tenant_id=payload.tenant_id,
            assigned_lead=payload.assigned_lead,
        )
    except PlaybookNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    metrics.PLAYBOOK_RUNS_STARTED_TOTAL.labels(playbook_id=payload.playbook_id).inc()
    tmpl = engine.get_template(payload.playbook_id)
    if tmpl:
        metrics.ACTIVE_PLAYBOOKS_COUNT.labels(domain=tmpl.domain).inc()

    return PlaybookRunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        playbook_id=run.playbook_id,
        title=run.title,
        assigned_lead=run.assigned_lead,
        current_stage=run.current_stage,
        total_stages=run.total_stages,
        status=run.status,
        stage_data=run.stage_data,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@app.get(
    "/v1/playbooks/runs/{run_id}",
    response_model=PlaybookRunResponse,
    tags=["Playbooks"],
    responses={
        200: {"description": "Playbook execution run status and stage details"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
async def get_playbook_run(
    run_id: str,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> PlaybookRunResponse:
    """Retrieve the active state, current stage, and milestones of a playbook run (FEAT-051)."""
    from app.workflows.engine import get_default_playbook_engine

    engine = get_default_playbook_engine()
    run = engine.get_run(run_id=run_id, tenant_id=tenant_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Playbook run {run_id} not found for tenant {tenant_id}",
        )

    return PlaybookRunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        playbook_id=run.playbook_id,
        title=run.title,
        assigned_lead=run.assigned_lead,
        current_stage=run.current_stage,
        total_stages=run.total_stages,
        status=run.status,
        stage_data=run.stage_data,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@app.post(
    "/v1/playbooks/runs/{run_id}/advance",
    response_model=PlaybookRunResponse,
    tags=["Playbooks"],
    responses={
        200: {"description": "Playbook successfully advanced to next stage"},
        400: {"description": "Invalid state transition or unsatisfied exit criteria"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
async def advance_playbook_stage(
    run_id: str,
    payload: AdvanceStageRequest,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> PlaybookRunResponse:
    """Promote playbook execution to the next sequential stage (FEAT-051)."""
    from app.workflows.engine import (
        InvalidStateTransitionError,
        PlaybookRunNotFoundError,
        get_default_playbook_engine,
    )

    engine = get_default_playbook_engine()
    try:
        run = engine.advance_stage(
            run_id=run_id,
            tenant_id=tenant_id,
            target_stage=payload.target_stage,
        )
        metrics.PLAYBOOK_STAGE_TRANSITIONS_TOTAL.labels(
            playbook_id=run.playbook_id,
            outcome="success",
        ).inc()
    except PlaybookRunNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except InvalidStateTransitionError as err:
        metrics.PLAYBOOK_STAGE_TRANSITIONS_TOTAL.labels(
            playbook_id="unknown",
            outcome="failure",
        ).inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    return PlaybookRunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        playbook_id=run.playbook_id,
        title=run.title,
        assigned_lead=run.assigned_lead,
        current_stage=run.current_stage,
        total_stages=run.total_stages,
        status=run.status,
        stage_data=run.stage_data,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@app.post(
    "/v1/playbooks/runs/{run_id}/milestones/{milestone_id}",
    response_model=StageProgress,
    tags=["Playbooks"],
    responses={
        200: {"description": "Milestone recorded and stage progress returned"},
        400: {"description": "Validation error or invalid stage"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run or milestone not found"},
    },
)
@app.post(
    "/v1/playbooks/{run_id}/milestones/{milestone_id}",
    response_model=StageProgress,
    tags=["Playbooks"],
    responses={
        200: {"description": "Milestone recorded and stage progress returned"},
        400: {"description": "Validation error or invalid stage"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run or milestone not found"},
    },
)
async def complete_playbook_milestone(
    run_id: str,
    milestone_id: str,
    payload: CompleteMilestoneRequest,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> StageProgress:
    """Mark a discrete milestone completed with optional grounding evidence (FEAT-051 & FEAT-052)."""
    from app.workflows.engine import (
        InvalidStateTransitionError,
        PlaybookRunNotFoundError,
    )
    from app.workflows.milestone_tracker import get_default_milestone_tracker

    tracker = get_default_milestone_tracker()
    try:
        res = tracker.record_milestone(
            run_id=run_id,
            milestone_id=milestone_id,
            tenant_id=tenant_id,
            evidence_doc_id=payload.evidence_doc_id,
            notes=payload.notes,
        )
        return StageProgress(
            stage_number=res.stage_number,
            stage_name=res.stage_name,
            total_milestones=res.total_milestones,
            completed_milestones=res.completed_milestones,
            completion_ratio=res.completion_ratio,
            exit_ready=res.exit_ready,
        )
    except PlaybookRunNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except (InvalidStateTransitionError, ValueError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err


@app.get(
    "/v1/playbooks/{run_id}/stages/{stage_number}/progress",
    response_model=StageProgress,
    tags=["Playbooks"],
    responses={
        200: {"description": "Stage completion metrics and exit readiness"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
@app.get(
    "/v1/playbooks/runs/{run_id}/stages/{stage_number}/progress",
    response_model=StageProgress,
    tags=["Playbooks"],
    responses={
        200: {"description": "Stage completion metrics and exit readiness"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
async def get_stage_progress(
    run_id: str,
    stage_number: int,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> StageProgress:
    """Get granular deliverable progress and exit readiness for a stage (FEAT-052)."""
    from app.workflows.engine import (
        InvalidStateTransitionError,
        PlaybookRunNotFoundError,
    )
    from app.workflows.milestone_tracker import get_default_milestone_tracker

    tracker = get_default_milestone_tracker()
    try:
        p = tracker.get_stage_progress(
            run_id=run_id,
            stage_number=stage_number,
            tenant_id=tenant_id,
        )
        return StageProgress(
            stage_number=p.stage_number,
            stage_name=p.stage_name,
            total_milestones=p.total_milestones,
            completed_milestones=p.completed_milestones,
            completion_ratio=p.completion_ratio,
            exit_ready=p.exit_ready,
        )
    except PlaybookRunNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except (InvalidStateTransitionError, ValueError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err


@app.get(
    "/v1/playbooks/{run_id}/progress",
    response_model=list[StageProgress],
    tags=["Playbooks"],
    responses={
        200: {"description": "Overall progression across all 4 stages"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
@app.get(
    "/v1/playbooks/runs/{run_id}/progress",
    response_model=list[StageProgress],
    tags=["Playbooks"],
    responses={
        200: {"description": "Overall progression across all 4 stages"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
async def list_playbook_progress(
    run_id: str,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> list[StageProgress]:
    """List progression across all 4 stages for a playbook run (FEAT-052)."""
    from app.workflows.engine import PlaybookRunNotFoundError
    from app.workflows.milestone_tracker import get_default_milestone_tracker

    tracker = get_default_milestone_tracker()
    try:
        items = tracker.list_stage_progress(run_id=run_id, tenant_id=tenant_id)
        return [
            StageProgress(
                stage_number=p.stage_number,
                stage_name=p.stage_name,
                total_milestones=p.total_milestones,
                completed_milestones=p.completed_milestones,
                completion_ratio=p.completion_ratio,
                exit_ready=p.exit_ready,
            )
            for p in items
        ]
    except PlaybookRunNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err


@app.get(
    "/v1/playbooks/runs",
    response_model=list[PlaybookRunResponse],
    tags=["Playbooks"],
    responses={
        200: {"description": "List all active and completed playbook runs"},
        401: {"description": "missing or invalid API key"},
    },
)
async def list_playbook_runs(
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status"),
    fingerprint: str = Depends(require_api_key),
) -> list[PlaybookRunResponse]:
    """List all playbook runs for a tenant (FEAT-051)."""
    from typing import cast

    from app.workflows.engine import RunStatus, get_default_playbook_engine

    engine = get_default_playbook_engine()
    validated_status = (
        cast(RunStatus, status_filter)
        if status_filter in ("ACTIVE", "BLOCKED", "COMPLETED")
        else None
    )
    runs = engine.list_runs(tenant_id=tenant_id, status=validated_status)
    return [
        PlaybookRunResponse(
            run_id=r.run_id,
            tenant_id=r.tenant_id,
            playbook_id=r.playbook_id,
            title=r.title,
            assigned_lead=r.assigned_lead,
            current_stage=r.current_stage,
            total_stages=r.total_stages,
            status=r.status,
            stage_data=r.stage_data,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in runs
    ]


@app.post(
    "/v1/playbooks/{run_id}/validate-exit",
    response_model=ExitValidationResult,
    tags=["Playbooks"],
    responses={
        200: {"description": "Exit criteria validation report"},
        400: {"description": "Invalid stage parameter"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
@app.post(
    "/v1/playbooks/runs/{run_id}/validate-exit",
    response_model=ExitValidationResult,
    tags=["Playbooks"],
    responses={
        200: {"description": "Exit criteria validation report"},
        400: {"description": "Invalid stage parameter"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
    },
)
async def validate_stage_exit_endpoint(
    run_id: str,
    stage: int | None = Query(
        default=None, description="Stage to validate (defaults to active stage)"
    ),
    override_justification: str | None = Query(
        default=None, description="Administrative override justification"
    ),
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> ExitValidationResult:
    """Evaluate stage exit criteria empirically against milestones and telemetry (FEAT-053)."""
    from app.workflows.engine import get_default_playbook_engine
    from app.workflows.exit_validator import get_default_exit_validator

    engine = get_default_playbook_engine()
    run = engine.get_run(run_id, tenant_id=tenant_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found."
        )

    target_stage = stage if stage is not None else run.current_stage
    validator = get_default_exit_validator()
    try:
        result = validator.validate_stage_exit(
            run_id=run.run_id,
            current_stage=target_stage,
            tenant_id=tenant_id,
            override_justification=override_justification,
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    return ExitValidationResult(
        can_advance=result.can_advance,
        exit_statement=result.exit_statement,
        checks_evaluated=[CriterionCheck(**c.to_dict()) for c in result.checks_evaluated],
        blocking_issues=result.blocking_issues,
        override_applied=result.override_applied,
        validation_id=result.validation_id,
    )


@app.post(
    "/v1/playbooks/{run_id}/promote",
    response_model=PlaybookRunResponse,
    tags=["Playbooks"],
    responses={
        200: {"description": "Playbook successfully promoted to next stage"},
        400: {"description": "Invalid stage or parameters"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
        412: {"description": "Stage exit criteria not satisfied; promotion blocked"},
    },
)
@app.post(
    "/v1/playbooks/runs/{run_id}/promote",
    response_model=PlaybookRunResponse,
    tags=["Playbooks"],
    responses={
        200: {"description": "Playbook successfully promoted to next stage"},
        400: {"description": "Invalid stage or parameters"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
        412: {"description": "Stage exit criteria not satisfied; promotion blocked"},
    },
)
async def promote_playbook_stage(
    run_id: str,
    payload: PromoteStageRequest,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> PlaybookRunResponse:
    """Empirically validates stage exit criteria and promotes stage if verified (FEAT-053)."""
    from app.workflows.engine import (
        InvalidStateTransitionError,
        PlaybookRunNotFoundError,
        get_default_playbook_engine,
    )
    from app.workflows.exit_validator import (
        ExitCriteriaPreconditionFailedError,
        get_default_exit_validator,
    )

    validator = get_default_exit_validator()
    try:
        val_result = validator.validate_stage_exit(
            run_id=run_id,
            current_stage=payload.current_stage,
            tenant_id=tenant_id,
            override_justification=payload.override_justification,
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    if not val_result.can_advance:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Stage exit criteria not satisfied: {'; '.join(val_result.blocking_issues)}",
        )

    engine = get_default_playbook_engine()
    try:
        run = engine.advance_stage(
            run_id=run_id,
            tenant_id=tenant_id,
            override_justification=payload.override_justification,
        )
        metrics.PLAYBOOK_STAGE_TRANSITIONS_TOTAL.labels(
            playbook_id=run.playbook_id,
            outcome="success",
        ).inc()
    except PlaybookRunNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except (ExitCriteriaPreconditionFailedError, InvalidStateTransitionError) as err:
        metrics.PLAYBOOK_STAGE_TRANSITIONS_TOTAL.labels(
            playbook_id="unknown",
            outcome="failure",
        ).inc()
        status_code = (
            status.HTTP_412_PRECONDITION_FAILED
            if isinstance(err, ExitCriteriaPreconditionFailedError)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(err),
        ) from err

    return PlaybookRunResponse(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        playbook_id=run.playbook_id,
        title=run.title,
        assigned_lead=run.assigned_lead,
        current_stage=run.current_stage,
        total_stages=run.total_stages,
        status=run.status,
        stage_data=run.stage_data,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@app.get(
    "/v1/playbooks/{run_id}/tasks",
    response_model=RoleTaskList,
    tags=["Playbooks"],
    responses={
        200: {"description": "Role-partitioned task checklist"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
        422: {"description": "Invalid taxonomy role specified"},
    },
)
@app.get(
    "/v1/playbooks/runs/{run_id}/tasks",
    response_model=RoleTaskList,
    tags=["Playbooks"],
    responses={
        200: {"description": "Role-partitioned task checklist"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Playbook run not found"},
        422: {"description": "Invalid taxonomy role specified"},
    },
)
async def get_playbook_tasks_by_role(
    run_id: str,
    role: str | None = Query(
        default=None,
        description="Taxonomy role filter ('developer', 'qa-engineer', 'sre', 'engineering-manager', 'compliance-officer')",
    ),
    stage: int | None = Query(default=None, ge=1, le=10, description="Stage number filter (1-4)"),
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> RoleTaskList:
    """Dispatches and filters playbook tasks by assigned taxonomy role (FEAT-054)."""
    from app.workflows.task_router import VALID_TAXONOMY_ROLES, get_default_task_router

    router = get_default_task_router()
    try:
        task_list = router.get_tasks_for_role(
            run_id=run_id,
            role=role,
            stage_number=stage,
            tenant_id=tenant_id,
        )
    except ValueError as err:
        err_msg = str(err)
        if "Invalid role" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid role '{role}'. Supported taxonomy roles: {sorted(VALID_TAXONOMY_ROLES)}",
            ) from err
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=err_msg,
        ) from err

    return RoleTaskList(
        role=task_list.role,
        pending_tasks=[RoleTask(**t.to_dict()) for t in task_list.pending_tasks],
        completed_tasks=[RoleTask(**t.to_dict()) for t in task_list.completed_tasks],
        total_estimated_hours=task_list.total_estimated_hours,
    )


# --- Regulatory Cyber Incident Response Playbook (FEAT-055) ---


@app.post(
    "/v1/incidents/declare",
    response_model=IncidentCrisisState,
    tags=["Incidents"],
    responses={
        200: {"description": "Crisis response initialized with statutory 6-hour reporting window"},
        400: {"description": "Validation error in discovery timestamp or summary"},
        401: {"description": "missing or invalid API key"},
    },
)
async def declare_incident_endpoint(
    payload: DeclareIncidentRequest,
    run_id: Annotated[UUID | None, Query(description="Optional associated playbook run ID")] = None,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> IncidentCrisisState:
    """Operationalizes cyber incident response, starts 6-hour regulatory countdown, and auto-generates statutory RBI disclosure draft (FEAT-055)."""
    from app.workflows.incident_playbook import (
        IncidentValidationError,
        get_default_incident_manager,
    )

    manager = get_default_incident_manager()
    try:
        return manager.declare_incident(
            request=payload,
            tenant_id=tenant_id,
            run_id=run_id,
        )
    except (IncidentValidationError, ValueError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err


@app.get(
    "/v1/incidents/{incident_id}/status",
    response_model=IncidentCrisisState,
    tags=["Incidents"],
    responses={
        200: {"description": "Real-time crisis state, minutes remaining, and disclosure template"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Incident not found"},
    },
)
async def get_incident_status_endpoint(
    incident_id: UUID,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> IncidentCrisisState:
    """Retrieve real-time regulatory crisis state, updated countdown timer, and statutory disclosure draft (FEAT-055)."""
    from app.workflows.incident_playbook import (
        IncidentNotFoundError,
        get_default_incident_manager,
    )

    manager = get_default_incident_manager()
    try:
        return manager.get_incident_status(incident_id=incident_id, tenant_id=tenant_id)
    except IncidentNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err


@app.post(
    "/v1/incidents/{incident_id}/actions/{action_id}/complete",
    response_model=IncidentCrisisState,
    tags=["Incidents"],
    responses={
        200: {"description": "Action item marked complete and crisis state updated"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Incident not found"},
    },
)
async def complete_incident_action_endpoint(
    incident_id: UUID,
    action_id: str,
    payload: CompleteIncidentActionRequest | None = None,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> IncidentCrisisState:
    """Mark a forensic evidence preservation or statutory reporting action item complete (FEAT-055)."""
    from app.workflows.incident_playbook import (
        IncidentNotFoundError,
        get_default_incident_manager,
    )

    manager = get_default_incident_manager()
    notes = payload.notes if payload else ""
    try:
        return manager.complete_action(
            incident_id=incident_id,
            action_id=action_id,
            tenant_id=tenant_id,
            notes=notes,
        )
    except IncidentNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err


@app.get(
    "/v1/incidents",
    response_model=list[IncidentCrisisState],
    tags=["Incidents"],
    responses={
        200: {"description": "List of active and historical cyber crisis incidents"},
        401: {"description": "missing or invalid API key"},
    },
)
async def list_incidents_endpoint(
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> list[IncidentCrisisState]:
    """List all active and historical cyber crisis incidents for a tenant (FEAT-055)."""
    from app.workflows.incident_playbook import get_default_incident_manager

    manager = get_default_incident_manager()
    return manager.list_incidents(tenant_id=tenant_id)


# --- Regulated Release Certification Pipeline (FEAT-056) ---


@app.post(
    "/v1/compliance/certify-release",
    response_model=ReleaseCertificate,
    tags=["Compliance"],
    responses={
        200: {"description": "Release verification evaluated and GSN safety case synthesized"},
        400: {"description": "Invalid report path or malformed test/coverage report"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "Validation error or quality gates failed in strict mode"},
    },
)
async def certify_release_endpoint(
    payload: CertifyReleaseRequest,
    enforce_strict: bool = Query(
        default=False,
        description="If true, returns HTTP 422 when release candidate fails certification",
    ),
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> ReleaseCertificate:
    """Operationalizes playbook.regulated-release, verifying test evidence, coverage, and mutation score (FEAT-056)."""
    from app.workflows.release_certifier import get_default_release_certifier

    certifier = get_default_release_certifier()
    try:
        cert = certifier.certify_release(
            request=payload,
            tenant_id=tenant_id,
        )
    except FileNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    if enforce_strict and not cert.is_certified:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Release certification rejected: {'; '.join(cert.rejection_reasons)}",
        )

    return cert


@app.get(
    "/v1/compliance/release-certificates/{certificate_id}",
    response_model=ReleaseCertificate,
    tags=["Compliance"],
    responses={
        200: {"description": "Signed release certificate and GSN safety case"},
        401: {"description": "missing or invalid API key"},
        404: {"description": "Release certificate not found"},
    },
)
async def get_release_certificate_endpoint(
    certificate_id: UUID,
    tenant_id: str = Query(default="default", description="Tenant isolation key"),
    fingerprint: str = Depends(require_api_key),
) -> ReleaseCertificate:
    """Retrieve cryptographically signed release certificate and GSN safety case (FEAT-056)."""
    from app.workflows.release_certifier import get_default_release_certifier

    certifier = get_default_release_certifier()
    cert = certifier.get_certificate(certificate_id=certificate_id, tenant_id=tenant_id)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release certificate '{certificate_id}' not found",
        )
    return cert


# --- Post-Quantum Cryptographic Migration Tracker (FEAT-057) ---


@app.post(
    "/v1/compliance/pqc/scan",
    response_model=PQCReadinessReport,
    tags=["Compliance"],
    responses={
        200: {"description": "PQC inventory scan completed and readiness report generated"},
        400: {"description": "invalid endpoint specifications"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def scan_pqc_inventory_endpoint(
    payload: PQCScanRequest,
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    fingerprint: str = Depends(require_api_key),
) -> PQCReadinessReport:
    """Operationalizes playbook.crypto-migration, classifying endpoint crypto profiles (FEAT-057)."""
    from app.compliance.pqc_tracker import (
        PQCConfig,
        get_default_pqc_tracker,
    )

    tracker = get_default_pqc_tracker()
    if tracker.config.flag_rsa_under_3072 != payload.flag_rsa_under_3072:
        from app.compliance.pqc_tracker import PQCTracker

        tracker = PQCTracker(config=PQCConfig(flag_rsa_under_3072=payload.flag_rsa_under_3072))

    batch = CryptographicInventoryBatch(endpoints=payload.endpoints)

    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return tracker.scan_inventory(batch=batch, tenant_id=tenant_id, conn=conn)
        except Exception as err:
            logger.debug("pqc.pool_connection_fallback", error=str(err))

    return tracker.scan_inventory(batch=batch, tenant_id=tenant_id, conn=None)


@app.get(
    "/v1/compliance/pqc/inventory",
    response_model=PQCInventoryResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Cryptographic asset inventory retrieved"},
        401: {"description": "missing or invalid API key"},
    },
)
async def get_pqc_inventory_endpoint(
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    limit: Annotated[int, Query(ge=1, le=1000, description="Max assets to return")] = 100,
    offset: Annotated[int, Query(ge=0, description="Pagination offset")] = 0,
    fingerprint: str = Depends(require_api_key),
) -> PQCInventoryResponse:
    """Retrieve paginated cryptographic asset inventory for the tenant (FEAT-057)."""
    from app.compliance.pqc_tracker import get_default_pqc_tracker

    tracker = get_default_pqc_tracker()
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return tracker.get_inventory(
                    tenant_id=tenant_id, limit=limit, offset=offset, conn=conn
                )
        except Exception as err:
            logger.debug("pqc.pool_connection_fallback", error=str(err))

    return tracker.get_inventory(tenant_id=tenant_id, limit=limit, offset=offset)


@app.get(
    "/v1/compliance/pqc/readiness",
    response_model=PQCReadinessReport,
    tags=["Compliance"],
    responses={
        200: {"description": "Institutional post-quantum readiness report"},
        401: {"description": "missing or invalid API key"},
    },
)
async def get_pqc_readiness_endpoint(
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    fingerprint: str = Depends(require_api_key),
) -> PQCReadinessReport:
    """Retrieve real-time post-quantum cryptographic readiness report and milestone status (FEAT-057)."""
    from app.compliance.pqc_tracker import get_default_pqc_tracker

    tracker = get_default_pqc_tracker()
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return tracker.get_readiness_report(tenant_id=tenant_id, conn=conn)
        except Exception as err:
            logger.debug("pqc.pool_connection_fallback", error=str(err))

    return tracker.get_readiness_report(tenant_id=tenant_id)


# --- Digital Operational Resilience (DORA) Framework Runner (FEAT-058) ---


@app.post(
    "/v1/compliance/dora/assess",
    response_model=DORAComplianceReport,
    tags=["Compliance"],
    responses={
        200: {"description": "DORA compliance evaluation across Pillars 1-5 completed"},
        400: {"description": "Invalid ICT system specifications"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def assess_dora_compliance_endpoint(
    payload: DORAAssessmentRequest,
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    fingerprint: str = Depends(require_api_key),
) -> DORAComplianceReport:
    """Operationalizes playbook.resilience, evaluating systems against DORA Pillars 1-5 (FEAT-058)."""
    from app.compliance.dora_runner import get_default_dora_runner

    runner = get_default_dora_runner()
    if payload.tenant_id != "default" and tenant_id == "default":
        tenant_id = payload.tenant_id
    elif tenant_id != payload.tenant_id:
        payload = payload.model_copy(update={"tenant_id": tenant_id})

    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return runner.assess_systems(request=payload, conn=conn)
        except Exception as err:
            logger.debug("dora.pool_connection_fallback", error=str(err))

    return runner.assess_systems(request=payload, conn=None)


@app.get(
    "/v1/compliance/dora/report",
    response_model=DORAComplianceReport,
    tags=["Compliance"],
    responses={
        200: {"description": "Institutional DORA readiness report"},
        401: {"description": "missing or invalid API key"},
    },
)
async def get_dora_report_endpoint(
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    fingerprint: str = Depends(require_api_key),
) -> DORAComplianceReport:
    """Retrieve real-time DORA operational resilience compliance report and scorecard (FEAT-058)."""
    from app.compliance.dora_runner import get_default_dora_runner

    runner = get_default_dora_runner()
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return runner.get_compliance_report(tenant_id=tenant_id, conn=conn)
        except Exception as err:
            logger.debug("dora.pool_connection_fallback", error=str(err))

    return runner.get_compliance_report(tenant_id=tenant_id)


@app.post(
    "/v1/compliance/dora/tests/record",
    response_model=RecordResilienceTestResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Resilience stress test evidence verified and recorded"},
        400: {"description": "Invalid test execution parameters"},
        401: {"description": "missing or invalid API key"},
        422: {"description": "validation error"},
    },
)
async def record_resilience_test_endpoint(
    payload: RecordResilienceTestRequest,
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    fingerprint: str = Depends(require_api_key),
) -> RecordResilienceTestResponse:
    """Record verified operational resilience stress test or TLPT execution (FEAT-058)."""
    from app.compliance.dora_runner import get_default_dora_runner

    runner = get_default_dora_runner()
    eff_tenant = payload.tenant_id if payload.tenant_id != "default" else tenant_id

    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return runner.record_test(request=payload, tenant_id=eff_tenant, conn=conn)
        except Exception as err:
            logger.debug("dora.pool_connection_fallback", error=str(err))

    return runner.record_test(request=payload, tenant_id=eff_tenant, conn=None)


@app.get(
    "/v1/compliance/dora/systems",
    response_model=DORASystemsResponse,
    tags=["Compliance"],
    responses={
        200: {"description": "Registered ICT systems retrieved"},
        401: {"description": "missing or invalid API key"},
    },
)
async def get_dora_systems_endpoint(
    tenant_id: Annotated[str, Query(description="Tenant isolation key")] = "default",
    fingerprint: str = Depends(require_api_key),
) -> DORASystemsResponse:
    """Retrieve registered ICT systems for the tenant under DORA (FEAT-058)."""
    from app.compliance.dora_runner import get_default_dora_runner

    runner = get_default_dora_runner()
    pool = getattr(app.state, "pool", None)
    if pool is not None:
        try:
            with pool.connection() as conn:
                return runner.get_systems(tenant_id=tenant_id, conn=conn)
        except Exception as err:
            logger.debug("dora.pool_connection_fallback", error=str(err))

    return runner.get_systems(tenant_id=tenant_id)
