"""Prometheus instrumentation for the serving API.

RED  -  Rate, Errors, Duration  -  is the framework for a request-driven service, so those
three are what the HTTP metrics here measure. Two RAG-specific signals are added because
they are the ones that actually explain this service's latency: the cache hit ratio and
the per-mode retrieval time.

Cardinality is the thing that kills a Prometheus deployment, so every label here was
enumerated before it was added:

* ``route`` is the **matched route template** (``/v1/search``), never ``request.url.path``.
  Raw paths are the most common cardinality explosion in HTTP services; for this API they
  would be bounded anyway, but a future path parameter would silently turn one series into
  one per value. Unmatched requests collapse to the literal ``"unmatched"`` rather than
  echoing whatever a scanner probed, which would otherwise be an attacker-controlled label.
* ``method`` is bounded by HTTP itself.
* ``status`` is the full code rather than a class. The enumeration is small and known  -
  200, 401, 422, 429, 500  -  and the distinction between 401 and 429 is exactly what an
  operator needs. Collapsing both to ``4xx`` would hide a rate-limited caller behind an
  unauthenticated one.
* ``mode`` is the three values of the retrieval mode literal.

Nothing per-request is a label. Query text, API keys, key fingerprints and request ids are
all absent by construction: that detail belongs in the structured log, which carries the
request id, and the two are joined there rather than in the time-series database.

Bucket boundaries are taken from measurements of this service rather than from a default
ladder, because `histogram_quantile` interpolates inside a bucket and a p95 that lands in a
5s–10s bucket is a meaningless number. Measured on 2 vCPU: cache hit p95 2.11 ms, cold p95
48.11 ms. NFR-1's budget is p95 < 3 s. Buckets are therefore dense below 100 ms, where the
real distribution lives, and place an exact boundary at 3 s so SLO compliance is a bucket
ratio rather than an interpolation.

The default registry is used, which also exposes the ``process_*`` and ``python_*``
collectors. That is correct for one worker and wrong for several  -  a multi-process
deployment needs ``PROMETHEUS_MULTIPROC_DIR``  -  and matches the ``single_process: true``
that ``/healthz`` already reports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

#: Latency buckets in seconds, sized to the measured distribution and the NFR-1 budget.
#: 0.001-0.005 covers cache hits, 0.01-0.1 covers cold retrieval, 3.0 is the SLO boundary,
#: and 10.0 catches a pathological tail without inventing resolution that does not exist.
LATENCY_BUCKETS = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    3.0,
    10.0,
)

#: Label value used when a request matched no route, so a scanner probing random paths
#: cannot create one time series per probe.
UNMATCHED_ROUTE = "unmatched"

REQUESTS = Counter(
    "docscout_http_requests_total",
    "HTTP requests handled, by route, method and status code.",
    ("method", "route", "status"),
)

REQUEST_DURATION = Histogram(
    "docscout_http_request_duration_seconds",
    "End-to-end HTTP request duration in seconds.",
    ("method", "route"),
    buckets=LATENCY_BUCKETS,
)

IN_FLIGHT = Gauge(
    "docscout_http_requests_in_flight",
    "Requests currently being handled. Saturation signal for a single worker.",
)

RETRIEVAL_DURATION = Histogram(
    "docscout_retrieval_duration_seconds",
    "Retrieval time in seconds, excluding HTTP overhead, by mode.",
    ("mode",),
    buckets=LATENCY_BUCKETS,
)

CACHE_EVENTS = Counter(
    "docscout_cache_events_total",
    "Result-cache lookups by outcome. hit/(hit+miss) is the hit ratio.",
    ("result",),
)

RATE_LIMITED = Counter(
    "docscout_rate_limited_total",
    "Requests rejected by the per-key rate limiter.",
)

CORPUS_CHUNKS = Gauge(
    "docscout_corpus_chunks",
    "Chunks currently retrievable, i.e. belonging to a current document version.",
)

CORPUS_LAST_CHECKED = Gauge(
    "docscout_corpus_last_checked_timestamp_seconds",
    "Unix timestamp when the regulatory corpus was last checked or refreshed.",
)

CORPUS_STALE_HOURS = Gauge(
    "docscout_corpus_stale_hours",
    "Hours elapsed since the regulatory corpus was last checked or refreshed.",
)

CORPUS_STALENESS_BUDGET_HOURS = Gauge(
    "docscout_corpus_staleness_budget_hours",
    "Configured staleness budget in hours before corpus health is degraded.",
)

CORPUS_IS_STALE = Gauge(
    "docscout_corpus_is_stale",
    "1 if elapsed stale hours exceeds the staleness budget, 0 otherwise.",
)

CORPUS_VERSIONS_CURRENT = Gauge(
    "docscout_corpus_versions_current",
    "Count of currently active document versions in the corpus.",
)

CORPUS_VERSIONS_SUPERSEDED = Gauge(
    "docscout_corpus_versions_superseded",
    "Count of superseded document versions retained in the corpus (FR-4).",
)

MANIFEST_CHANGED = Counter(
    "docscout_manifest_changed_total",
    "Count of detected manifest or document changes during corpus refresh.",
)

CACHE_INVALIDATIONS = Counter(
    "docscout_cache_invalidations_total",
    "Count of cache invalidation events triggered on supersession or admin action.",
    ("reason",),
)

AGENT_RESEARCH_TOTAL = Counter(
    "docscout_agent_research_total",
    "Research requests executed by the agent loop.",
    ("status",),
)

AGENT_RESEARCH_DURATION = Histogram(
    "docscout_agent_research_duration_seconds",
    "End-to-end research agent execution time in seconds.",
    buckets=LATENCY_BUCKETS,
)

CORPUS_GENERATION = Gauge(
    "docscout_corpus_generation",
    "Monotonically increasing corpus generation counter for the in-memory cache and indices.",
)

RETRIEVAL_AUDITS = Counter(
    "docscout_retrieval_audits_total",
    "Count of durable retrieval audit log entries recorded.",
    ("status",),
)


def route_label(request_scope: Mapping[str, Any]) -> str:
    """The matched route template, or a fixed placeholder.

    Starlette puts the matched ``APIRoute`` in the ASGI scope once routing has run. Its
    ``path`` is the template (``/v1/search``), which is what keeps this label bounded.

    Typed as a Mapping rather than a dict because that is what the ASGI scope actually is;
    narrowing it to dict made mypy reject every real call site.
    """
    route = request_scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


def render() -> tuple[bytes, str]:
    """Serialise the default registry. Returns (body, content type)."""
    return generate_latest(), CONTENT_TYPE_LATEST
