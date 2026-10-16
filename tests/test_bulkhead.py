"""Tests for Bulkhead Concurrency Isolation & Adaptive Load Shedding (FEAT-093)."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import pytest
from prometheus_client import generate_latest
from starlette.responses import Response

from app.api.bulkhead import (
    VALID_POOLS,
    BulkheadConfig,
    BulkheadManager,
    determine_pool,
    get_bulkhead_manager,
    get_bulkhead_telemetry,
    set_bulkhead_manager,
)
from app.api.middleware import BulkheadMiddleware


def test_determine_pool_by_path() -> None:
    """Verify route-based pool classification."""
    assert determine_pool("/v1/search") == "query"
    assert determine_pool("/v1/chat") == "query"
    assert determine_pool("/v1/documents/item") == "query"
    assert determine_pool("/v1/ingest/file") == "ingest"
    assert determine_pool("/v1/corpus/refresh") == "ingest"
    assert determine_pool("/v1/eval/retrieval") == "eval"
    assert determine_pool("/v1/benchmark/run") == "eval"
    assert determine_pool("/v1/unknown") == "internal"
    assert determine_pool("/healthz") == "internal"


def test_determine_pool_by_header() -> None:
    """Verify X-Pool header override."""
    assert determine_pool("/v1/unknown", {"X-Pool": "query"}) == "query"
    assert determine_pool("/v1/search", {"X-Pool": "ingest"}) == "ingest"
    assert determine_pool("/v1/search", {"x-pool": "eval"}) == "eval"
    # Invalid pool falls back to path
    assert determine_pool("/v1/search", {"X-Pool": "invalid"}) == "query"


def test_bulkhead_telemetry() -> None:
    """Verify telemetry snapshot across all pools."""
    telemetry = get_bulkhead_telemetry()
    for pool in VALID_POOLS:
        assert pool in telemetry
        entry = telemetry[pool]
        assert "active" in entry
        assert "limit" in entry
        assert "queued" in entry
        assert "queue_capacity" in entry
        assert "avg_service_time_ms" in entry


def test_check_admission_under_limit() -> None:
    """Verify immediate admission when active < limit and no queue."""
    manager = BulkheadManager()
    admission = manager.check_admission("query")
    assert admission.admitted is True
    assert admission.pool == "query"
    assert admission.queue_depth == 0
    assert admission.estimated_wait_ms == 0.0


def test_check_admission_queue_saturation_shed() -> None:
    """Verify load shedding when queue capacity is saturated."""
    cfg = BulkheadConfig(
        pool_limits={"eval": 2},
        queue_multipliers={"eval": 1},  # max_queue = 2 * 1 = 2
    )
    manager = BulkheadManager(cfg)
    manager._active["eval"] = 2
    manager._queued["eval"] = 2  # queue capacity reached

    admission = manager.check_admission("eval")
    assert admission.admitted is False
    assert "queue saturated" in (admission.rejection_reason or "")


def test_check_admission_littles_law_latency_shed() -> None:
    """Verify adaptive load shedding when estimated wait exceeds SLA."""
    # limit=2, default service time=50ms -> W = (Q+1)*50/2
    # If Q=9 -> W = 10 * 50 / 2 = 250ms > 200ms SLA
    cfg = BulkheadConfig(
        pool_limits={"query": 2},
        default_service_time_ms=50.0,
        max_queue_wait_ms=200.0,
        queue_multipliers={"query": 10},
    )
    manager = BulkheadManager(cfg)
    manager._active["query"] = 2
    manager._queued["query"] = 9

    admission = manager.check_admission("query", priority="normal", tenant_tier="growth")
    assert admission.admitted is False
    assert "exceeds" in (admission.rejection_reason or "")
    assert "SLA limit" in (admission.rejection_reason or "")


def test_check_admission_priority_tier_threshold() -> None:
    """Verify lower tier / low priority requests get shed at stricter 100ms threshold."""
    # limit=2, service time=25ms -> W = (Q+1)*25/2
    # If Q=9 -> W = 10 * 25 / 2 = 125ms
    # 125ms < 200ms (growth tier passes), but 125ms > 100ms (starter tier shed)
    cfg = BulkheadConfig(
        pool_limits={"query": 2},
        default_service_time_ms=25.0,
        max_queue_wait_ms=200.0,
        queue_multipliers={"query": 10},
    )
    manager = BulkheadManager(cfg)
    manager._active["query"] = 2
    manager._queued["query"] = 9

    # Growth tier passes
    growth_adm = manager.check_admission("query", priority="normal", tenant_tier="growth")
    assert growth_adm.admitted is True

    # Starter tier gets shed at 100ms threshold
    starter_adm = manager.check_admission("query", priority="normal", tenant_tier="starter")
    assert starter_adm.admitted is False
    assert "exceeds 100.0ms SLA limit" in (starter_adm.rejection_reason or "")


@pytest.mark.asyncio
async def test_bulkhead_manager_acquire_and_release() -> None:
    """Verify async acquisition and release lifecycle."""
    manager = BulkheadManager()
    assert manager.get_active("query") == 0

    async with manager.acquire("query") as admission:
        assert admission.admitted is True
        assert manager.get_active("query") == 1

    assert manager.get_active("query") == 0


@pytest.mark.asyncio
async def test_bulkhead_middleware_passthrough() -> None:
    """Verify middleware passes through admitted requests and attaches headers."""
    orig_manager = get_bulkhead_manager()
    test_manager = BulkheadManager()
    set_bulkhead_manager(test_manager)

    try:

        async def dummy_app(scope: Any, receive: Any, send: Any) -> None:
            response = Response("OK", status_code=200)
            await response(scope, receive, send)

        middleware = BulkheadMiddleware(dummy_app, manager=test_manager)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/search",
            "headers": [(b"host", b"localhost")],
        }

        sent_messages: list[MutableMapping[str, Any]] = []

        async def mock_send(msg: MutableMapping[str, Any]) -> None:
            sent_messages.append(msg)

        async def mock_receive() -> dict[str, Any]:
            return {"type": "http.request"}

        await middleware(scope, mock_receive, mock_send)

        # Check response start has status 200 and X-Bulkhead-Pool header
        resp_start = next(m for m in sent_messages if m["type"] == "http.response.start")
        assert resp_start["status"] == 200
        headers_dict = dict(resp_start["headers"])
        assert headers_dict[b"x-bulkhead-pool"] == b"query"
    finally:
        set_bulkhead_manager(orig_manager)


@pytest.mark.asyncio
async def test_bulkhead_middleware_excluded_paths() -> None:
    """Verify excluded paths bypass bulkhead entirely."""
    test_manager = BulkheadManager(BulkheadConfig(pool_limits={"internal": 0}))

    async def dummy_app(scope: Any, receive: Any, send: Any) -> None:
        response = Response("HEALTHY", status_code=200)
        await response(scope, receive, send)

    middleware = BulkheadMiddleware(dummy_app, manager=test_manager)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/healthz",
        "headers": [(b"host", b"localhost")],
    }

    sent_messages: list[MutableMapping[str, Any]] = []

    async def mock_send(msg: MutableMapping[str, Any]) -> None:
        sent_messages.append(msg)

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request"}

    await middleware(scope, mock_receive, mock_send)

    resp_start = next(m for m in sent_messages if m["type"] == "http.response.start")
    assert resp_start["status"] == 200
    headers_dict = dict(resp_start["headers"])
    # Excluded path should not have X-Bulkhead-Pool added
    assert b"x-bulkhead-pool" not in headers_dict


@pytest.mark.asyncio
async def test_bulkhead_middleware_rejection_429() -> None:
    """Verify middleware emits 429 with Retry-After when shed."""
    # Saturated config
    cfg = BulkheadConfig(
        pool_limits={"eval": 1},
        queue_multipliers={"eval": 0},  # max_queue = 0
    )
    test_manager = BulkheadManager(cfg)
    test_manager._active["eval"] = 1  # saturated

    async def dummy_app(scope: Any, receive: Any, send: Any) -> None:
        response = Response("OK", status_code=200)
        await response(scope, receive, send)

    middleware = BulkheadMiddleware(dummy_app, manager=test_manager)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/eval/run",
        "headers": [(b"host", b"localhost")],
    }

    sent_messages: list[MutableMapping[str, Any]] = []

    async def mock_send(msg: MutableMapping[str, Any]) -> None:
        sent_messages.append(msg)

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request"}

    await middleware(scope, mock_receive, mock_send)

    resp_start = next(m for m in sent_messages if m["type"] == "http.response.start")
    assert resp_start["status"] == 429
    headers_dict = dict(resp_start["headers"])
    assert headers_dict[b"retry-after"] == b"1"
    assert headers_dict[b"x-bulkhead-pool"] == b"eval"


def test_bulkhead_prometheus_export() -> None:
    """Verify Prometheus metrics export bulkhead gauges and counters."""
    output = generate_latest().decode("utf-8")
    assert "docscout_bulkhead_active_concurrency" in output
    assert "docscout_bulkhead_queue_depth" in output
    assert "docscout_bulkhead_shed_requests_total" in output
