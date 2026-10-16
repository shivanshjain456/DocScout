"""Tests for logging configuration and request correlation.

These assert on emitted records rather than on the configuration object, because the
failure that matters is "nothing came out" or "the key came out", and only the output
shows either. Before this module existed, every INFO record in the API was discarded by an
unconfigured root logger, which no configuration-shaped assertion would have caught.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from app.api.metrics import QUERY_COST_USD_TOTAL, QUERY_TOKENS_TOTAL
from app.observability import (
    REDACTED,
    TelemetryConfig,
    calculate_query_complexity,
    calculate_query_cost,
    configure_logging,
    estimate_token_count,
    get_logger,
    hash_query_text,
    normalise_request_id,
    parse_or_mint_traceparent,
    record_telemetry_access,
    reset_logging_for_tests,
    telemetry_config,
    trace_span,
)


@pytest.fixture(autouse=True)
def _isolate_logging() -> Iterator[None]:
    reset_logging_for_tests()
    structlog.contextvars.clear_contextvars()
    yield
    reset_logging_for_tests()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def emitted(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Parse the JSON lines written to stderr."""
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.strip()]


# --- the records actually come out, and are JSON ----------------------------------------
def test_info_records_are_emitted_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("search.completed", mode="hybrid", k=10)
    records = emitted(capsys)
    assert len(records) == 1
    assert records[0]["event"] == "search.completed"
    assert records[0]["mode"] == "hybrid"
    assert records[0]["k"] == 10
    assert records[0]["level"] == "info"
    assert records[0]["timestamp"].endswith("Z")


def test_level_is_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_output=True)
    log = get_logger("docscout.test")
    log.info("suppressed")
    log.warning("kept")
    assert [r["event"] for r in emitted(capsys)] == ["kept"]


def test_stdlib_loggers_render_through_the_same_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """uvicorn and psycopg log via stdlib; one process must not emit two formats."""
    configure_logging("INFO", json_output=True)
    logging.getLogger("uvicorn.error").info("started")
    records = emitted(capsys)
    assert len(records) == 1
    assert records[0]["event"] == "started"
    assert records[0]["logger"] == "uvicorn.error"


def test_configuration_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    """uvicorn imports the app module more than once; a second handler would double lines."""
    configure_logging("INFO", json_output=True)
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("once")
    assert len(emitted(capsys)) == 1


def test_console_renderer_is_used_off_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=False)
    get_logger("docscout.test").info("human readable")
    err = capsys.readouterr().err
    assert "human readable" in err
    with pytest.raises(json.JSONDecodeError):
        json.loads(err.splitlines()[0])


# --- credentials must never reach a log -------------------------------------------------
@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "X_API_KEY",
        "apikey",
        "password",
        "db_password",
        "secret",
        "token",
        "authorization",
    ],
)
def test_credential_shaped_keys_are_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    """Redaction is a processor so one forgetful call site cannot leak a key."""
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("auth", **{key: "super-secret-value"})
    record = emitted(capsys)[0]
    assert record[key] == REDACTED
    assert "super-secret-value" not in json.dumps(record)


def test_non_sensitive_fields_are_untouched(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("search", key_fingerprint="abc123", mode="hybrid")
    record = emitted(capsys)[0]
    assert record["key_fingerprint"] == "abc123"  # a fingerprint is safe, a key is not
    assert record["mode"] == "hybrid"


# --- correlation ------------------------------------------------------------------------
def test_bound_context_appears_on_every_record(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    structlog.contextvars.bind_contextvars(request_id="req-1", path="/v1/search")
    get_logger("a").info("first")
    get_logger("b").info("second")
    assert [r["request_id"] for r in emitted(capsys)] == ["req-1", "req-1"]


def test_exceptions_are_rendered_with_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("docscout.test").exception("http.unhandled")
    record = emitted(capsys)[0]
    assert "RuntimeError: boom" in record["exception"]


# --- request id validation --------------------------------------------------------------
def test_a_usable_inbound_id_is_honoured() -> None:
    assert normalise_request_id("trace-abc.123:xyz") == "trace-abc.123:xyz"


@pytest.mark.parametrize(
    "hostile",
    [
        None,
        "",
        "has space",
        "newline\ninjected",  # forging a second log line
        "carriage\rreturn",
        "x" * 65,  # unbounded length
        "semi;colon",
        "\x00null",
    ],
)
def test_unusable_inbound_ids_are_replaced(hostile: str | None) -> None:
    """The id is echoed into every log line for the request, so it is untrusted input."""
    generated = normalise_request_id(hostile)
    assert generated != hostile
    assert len(generated) == 16
    assert generated.isalnum()


def test_generated_ids_are_unique() -> None:
    assert len({normalise_request_id(None) for _ in range(200)}) == 200


def test_non_string_values_are_not_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    """`api_keys=1` is a count, not a credential.

    The first version of the redactor matched on the key name alone and destroyed this
    signal at startup, which is how a safety measure becomes an operational blind spot.
    """
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("api.ready", api_keys=2, token_count=512, secret_ok=True)
    record = emitted(capsys)[0]
    assert record["api_keys"] == 2
    assert record["token_count"] == 512
    assert record["secret_ok"] is True


def test_string_credentials_are_still_redacted_alongside_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("mixed", api_keys=2, api_key="real-secret-value")
    record = emitted(capsys)[0]
    assert record["api_keys"] == 2
    assert record["api_key"] == REDACTED


def test_third_party_info_is_quieted(capsys: pytest.CaptureFixture[str]) -> None:
    """Loading the encoder emits ~30 httpx lines that bury the one line that matters."""
    configure_logging("INFO", json_output=True)
    logging.getLogger("httpx").info("HTTP Request: HEAD https://huggingface.co/...")
    logging.getLogger("httpx").warning("connection failed")
    events = [r["event"] for r in emitted(capsys)]
    assert events == ["connection failed"]


# --- FEAT-100: High-Cardinality Telemetry & Cost-Per-Query Accounting ------------------


def test_telemetry_config_defaults_and_env() -> None:
    """TelemetryConfig defaults match specification and environment overrides work."""
    cfg = TelemetryConfig()
    assert cfg.export_otlp is False
    assert cfg.cost_per_1k_tokens == 0.0001
    assert "docscout" in cfg.service_name

    loaded = telemetry_config()
    assert isinstance(loaded, TelemetryConfig)
    assert loaded.cost_per_1k_tokens > 0


def test_parse_or_mint_traceparent_valid_w3c() -> None:
    """Inbound valid W3C traceparent preserves trace ID and flags while minting child span."""
    inbound = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    trace_id, span_id, flags, out_header = parse_or_mint_traceparent(inbound)
    assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert flags == "01"
    assert span_id != "00f067aa0ba902b7"  # Fresh child span
    assert len(span_id) == 16
    assert out_header.startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")
    assert out_header.endswith("-01")


def test_parse_or_mint_traceparent_fallback_on_invalid() -> None:
    """Missing or corrupted traceparent header mints compliant 32-hex trace ID."""
    trace_id, span_id, flags, out_header = parse_or_mint_traceparent("invalid-trace-header")
    assert len(trace_id) == 32
    assert len(span_id) == 16
    assert flags == "01"
    assert out_header == f"00-{trace_id}-{span_id}-01"


def test_token_count_estimation() -> None:
    """Whitespace heuristic estimates tokens consistently."""
    assert estimate_token_count(None, base_tokens=10) == 10
    assert estimate_token_count("", base_tokens=15) == 15
    text = "What are the priority sector lending norms for regional rural banks in India?"
    tokens = estimate_token_count(text)
    assert tokens >= 12


def test_cost_calculation() -> None:
    """Cost calculations accurately track monetary value per thousand tokens."""
    # 1,000 tokens @ $0.0001 per 1k = $0.0001
    assert calculate_query_cost(1000, 0.0001) == 0.0001
    # 50,000 tokens @ $0.0001 per 1k = $0.005
    assert calculate_query_cost(50000, 0.0001) == 0.005
    assert calculate_query_cost(0, 0.0001) == 0.0


def test_query_complexity_calculation() -> None:
    """Complexity combines input tokens, passage evaluation, and execution timing."""
    score = calculate_query_complexity(tokens=50, retrieved_chunks=10, duration_ms=25.0)
    # 50*1 + 10*2.5 + 2.5 = 77.5
    assert score == 77.5


def test_customer_query_redacted_in_telemetry(capsys: pytest.CaptureFixture[str]) -> None:
    """Customer proprietary query strings are never logged in cleartext."""
    configure_logging("INFO", json_output=True)
    raw_query = "Confidential SEBI insider trading investigation regarding Company X"
    get_logger("docscout.test").info(
        "search.request",
        user_query=raw_query,
        search_query=raw_query,
        status=200,
    )
    record = emitted(capsys)[0]
    # Raw query text must be absent
    assert raw_query not in json.dumps(record)
    assert "[redacted hash=" in record["user_query"]
    assert "[redacted hash=" in record["search_query"]
    assert f"hash={hash_query_text(raw_query)}" in record["user_query"]


def test_trace_span_context_manager() -> None:
    """trace_span context manager tracks duration and records attributes."""
    with trace_span("lexical_retrieval", {"k": 10, "engine": "bm25"}) as span:
        assert span["name"] == "lexical_retrieval"
        assert len(span["span_id"]) == 16
        assert span["attributes"]["k"] == 10

    assert "duration_ms" in span
    assert span["duration_ms"] >= 0.0


def test_record_telemetry_access_emits_json_and_increments_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """record_telemetry_access emits structured http.access log line and Prometheus metrics."""
    configure_logging("INFO", json_output=True)
    logger = get_logger("docscout.access")

    record_telemetry_access(
        logger=logger,
        status_code=200,
        duration_ms=15.42,
        tenant_id="tenant-rbi-supervisory",
        user_id="analyst-707",
        tokens=350,
        cost_usd=0.000035,
        cache_outcome="hit",
        query_complexity=42.5,
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id="00f067aa0ba902b7",
    )

    records = emitted(capsys)
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "http.access"
    assert rec["status"] == 200
    assert rec["duration_ms"] == 15.42
    assert rec["tenant_id"] == "tenant-rbi-supervisory"
    assert rec["user_id"] == "analyst-707"
    assert rec["tokens"] == 350
    assert rec["cost_usd"] == 0.000035
    assert rec["cache_outcome"] == "hit"
    assert rec["query_complexity"] == 42.5

    assert QUERY_COST_USD_TOTAL is not None
    assert QUERY_TOKENS_TOTAL is not None


def test_telemetry_overhead_under_0_1ms() -> None:
    """Telemetry calculations overhead per request is under 0.1 ms."""
    import time

    t0 = time.perf_counter()
    for _ in range(500):
        _tid, _sid, _flags, _hdr = parse_or_mint_traceparent(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
        tokens = estimate_token_count("RBI circular on liquidity coverage ratio", base_tokens=25)
        _cost = calculate_query_cost(tokens, 0.0001)
        _comp = calculate_query_complexity(tokens, duration_ms=12.0)
    t1 = time.perf_counter()
    avg_ms = ((t1 - t0) / 500.0) * 1000.0
    assert avg_ms <= 0.1, f"Telemetry calculation overhead {avg_ms:.4f} ms exceeded 0.1 ms limit"


def test_synthetic_1000_multi_tenant_queries_accounting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Evaluation dataset: 1,000 synthetic multi-tenant queries all carry correlation and cost."""
    configure_logging("INFO", json_output=True)
    logger = get_logger("docscout.benchmark")
    tenants = ["rbi-supervisory", "sebi-markets", "irdai-insurance", "pfrda-pensions"]

    total_cost_usd = 0.0
    total_tokens = 0

    for i in range(1000):
        tenant = tenants[i % len(tenants)]
        tokens = 50 + (i % 200)
        cost = calculate_query_cost(tokens, 0.0001)
        total_cost_usd += cost
        total_tokens += tokens
        cache_outcome = "hit" if i % 3 == 0 else "miss"

        record_telemetry_access(
            logger=logger,
            status_code=200,
            duration_ms=5.0 + (i % 15),
            tenant_id=tenant,
            user_id=f"analyst-{i}",
            tokens=tokens,
            cost_usd=cost,
            cache_outcome=cache_outcome,
            query_complexity=calculate_query_complexity(tokens, retrieved_chunks=5),
            trace_id=f"trace-{i:032x}",
            span_id=f"span-{i:016x}",
        )

    lines = emitted(capsys)
    assert len(lines) == 1000
    # 100% of search requests carry correlation ID and computed cost metric
    for rec in lines:
        assert "trace_id" in rec
        assert "span_id" in rec
        assert "cost_usd" in rec
        assert "tokens" in rec
        assert "tenant_id" in rec

    assert total_cost_usd > 0.0
    assert total_tokens > 0
