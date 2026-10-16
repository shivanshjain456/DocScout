"""Logging configuration, request correlation, and high-cardinality telemetry (FEAT-100).

Provides:
1. Unified structlog pipeline with stdlib ProcessorFormatter integration.
2. JSON off a TTY, human-readable on one; DOCSCOUT_LOG_JSON override.
3. Automated redaction of sensitive credentials and cleartext customer query strings.
4. W3C Trace Context standard support (traceparent header parsing and minting).
5. High-cardinality query telemetry (request ID, trace ID, tenant ID, user ID, tokens, cost).
6. OpenTelemetry-compatible tracing span context manager.
7. Cost-per-query accounting calculating inference and compute costs.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import structlog

#: Event keys replaced with a placeholder before rendering. Matched case-insensitively as
#: substrings, so `x_api_key`, `DB_PASSWORD` and `authorization` are all caught.
SENSITIVE_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token", "authorization")

REDACTED = "[redacted]"

#: Inbound X-Request-ID values are echoed into every log record for the request, so they
#: are untrusted input to the log. Restricting the charset and length stops a caller
#: injecting newlines (forging log entries) or megabytes (filling the disk).
_REQUEST_ID_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

#: W3C Trace Context traceparent pattern: version-trace_id-parent_id-trace_flags
_W3C_TRACEPARENT_PATTERN = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

#: Library loggers quieted to WARNING. Chatty at INFO about work that is not the
#: application's: HTTP calls to the model hub, tokenizer downloads, connection churn.
THIRD_PARTY_QUIET = (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "urllib3",
    "filelock",
)

_configured = False


@dataclass(frozen=True)
class TelemetryConfig:
    """Configuration for OpenTelemetry tracing and cost-per-query telemetry."""

    export_otlp: bool = False
    cost_per_1k_tokens: float = 0.0001
    otlp_endpoint: str = "http://localhost:4317"
    service_name: str = "docscout-regulatory-search"


def telemetry_config() -> TelemetryConfig:
    """Return structured TelemetryConfig instance from environment."""
    from app.config import load_dotenv

    load_dotenv()
    export_otlp = os.environ.get("DOCSCOUT_EXPORT_OTLP", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    raw_cost = os.environ.get("DOCSCOUT_COST_PER_1K_TOKENS", "0.0001").strip()
    try:
        cost_per_1k = float(raw_cost)
    except ValueError:
        cost_per_1k = 0.0001
    endpoint = os.environ.get("DOCSCOUT_OTLP_ENDPOINT", "http://localhost:4317").strip()
    service = os.environ.get("DOCSCOUT_SERVICE_NAME", "docscout-regulatory-search").strip()
    return TelemetryConfig(
        export_otlp=export_otlp,
        cost_per_1k_tokens=cost_per_1k,
        otlp_endpoint=endpoint,
        service_name=service,
    )


def hash_query_text(query: str | None) -> str:
    """Generate cryptographic SHA-256 fingerprint for query without leaking text."""
    if not query:
        return "empty"
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def _redact_sensitive(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace credential-looking and cleartext query string values before rendering.

    Only strings and bytes are redacted. A credential is a string; a count, a flag and
    a duration are not. Cleartext queries are hashed to prevent proprietary text leakage.
    """
    for key, value in list(event_dict.items()):
        if not isinstance(value, (str, bytes)):
            continue
        lower_key = key.lower()
        if any(part in lower_key for part in SENSITIVE_KEY_PARTS):
            event_dict[key] = REDACTED
        elif lower_key in ("query_text", "user_query", "search_query", "raw_query"):
            val_str = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
            event_dict[key] = f"[redacted hash={hash_query_text(val_str)} len={len(val_str)}]"
    return event_dict


def configure_logging(level: str | None = None, *, json_output: bool | None = None) -> None:
    """Configure structlog and the stdlib root logger as one pipeline.

    Idempotent: uvicorn imports the application module and may trigger this more than once,
    and adding a second handler would duplicate every line.
    """
    global _configured
    if _configured:
        return

    resolved_level = (level or os.environ.get("DOCSCOUT_LOG_LEVEL") or "INFO").upper()
    if json_output is None:
        override = os.environ.get("DOCSCOUT_LOG_JSON", "").strip().lower()
        if override in {"1", "true", "yes"}:
            json_output = True
        elif override in {"0", "false", "no"}:
            json_output = False
        else:
            json_output = not sys.stderr.isatty()

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    for name in THIRD_PARTY_QUIET:
        logging.getLogger(name).setLevel(
            max(logging.WARNING, logging.getLevelNamesMapping().get(resolved_level, logging.INFO))
        )

    _configured = True


def reset_logging_for_tests() -> None:
    """Allow a test to reconfigure. Not used by application code."""
    global _configured
    _configured = False


def normalise_request_id(raw: str | None) -> str:
    """Return a safe correlation id, minting one when the caller supplied nothing usable."""
    if raw and _REQUEST_ID_SAFE.match(raw):
        return raw
    return uuid.uuid4().hex[:16]


def parse_or_mint_traceparent(raw: str | None) -> tuple[str, str, str, str]:
    """Parse inbound W3C traceparent header or mint a fresh compliant tuple.

    Returns:
        (trace_id, span_id, trace_flags, traceparent_header)
    """
    if raw:
        cleaned = raw.strip().lower()
        m = _W3C_TRACEPARENT_PATTERN.match(cleaned)
        if m:
            trace_id, _parent_span, flags = m.groups()
            span_id = uuid.uuid4().hex[:16]
            return trace_id, span_id, flags, f"00-{trace_id}-{span_id}-{flags}"

    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    flags = "01"
    return trace_id, span_id, flags, f"00-{trace_id}-{span_id}-{flags}"


def estimate_token_count(text: str | None, base_tokens: int = 10) -> int:
    """Estimate token count from query or passage text using whitespace heuristic."""
    if not text:
        return base_tokens
    words = len(text.split())
    return max(base_tokens, int(words * 1.33) + 1)


def calculate_query_cost(tokens: int, cost_per_1k_tokens: float = 0.0001) -> float:
    """Calculate model inference and compute cost in USD."""
    return round((max(0, tokens) / 1000.0) * cost_per_1k_tokens, 8)


def calculate_query_complexity(
    tokens: int, retrieved_chunks: int = 0, duration_ms: float = 0.0
) -> float:
    """Calculate multidimensional query complexity score."""
    return round(float(tokens) * 1.0 + float(retrieved_chunks) * 2.5 + (duration_ms / 10.0), 2)


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Create an OpenTelemetry-compatible span with duration tracking and W3C context."""
    span_id = uuid.uuid4().hex[:16]
    start_time = time.monotonic()
    span_info: dict[str, Any] = {
        "name": name,
        "span_id": span_id,
        "trace_id": trace_id or uuid.uuid4().hex,
        "attributes": dict(attributes or {}),
        "start_time": start_time,
    }
    try:
        yield span_info
    finally:
        elapsed_ms = (time.monotonic() - start_time) * 1000.0
        span_info["duration_ms"] = round(elapsed_ms, 3)


def record_telemetry_access(
    logger: Any,
    status_code: int,
    duration_ms: float,
    tenant_id: str,
    user_id: str,
    tokens: int,
    cost_usd: float,
    cache_outcome: str,
    query_complexity: float,
    trace_id: str,
    span_id: str,
) -> None:
    """Emit structured JSON access log and record Prometheus RED/cost metrics."""
    logger.info(
        "http.access",
        status=status_code,
        duration_ms=duration_ms,
        tenant_id=tenant_id,
        user_id=user_id,
        tokens=tokens,
        cost_usd=cost_usd,
        cache_outcome=cache_outcome,
        query_complexity=query_complexity,
        trace_id=trace_id,
        span_id=span_id,
    )
    try:
        from app.api.metrics import QUERY_COST_USD_TOTAL, QUERY_TOKENS_TOTAL

        QUERY_COST_USD_TOTAL.labels(tenant_id=tenant_id, cache_outcome=cache_outcome).inc(cost_usd)
        QUERY_TOKENS_TOTAL.labels(tenant_id=tenant_id, cache_outcome=cache_outcome).inc(tokens)
    except Exception as exc:
        logger.debug("telemetry.metrics_error", error=str(exc))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
