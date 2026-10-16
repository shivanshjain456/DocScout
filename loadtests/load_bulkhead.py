"""Load test verifying Bulkhead Concurrency Isolation under background stress (FEAT-093).

Simulates 50 concurrent search query clients while saturating background ingestion
jobs, verifying search availability remains 100% and p95 search latency <= 50ms.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.api.bulkhead import BulkheadConfig, BulkheadManager
from app.api.middleware import BulkheadMiddleware


async def search_endpoint(request: Request) -> Response:
    # Simulate realistic fast vector search / retrieval query (5-15ms)
    await asyncio.sleep(0.010)
    return JSONResponse({"results": ["doc-1", "doc-2"], "count": 2})


async def ingest_endpoint(request: Request) -> Response:
    # Simulate heavy background OCR / chunking job (100-200ms)
    await asyncio.sleep(0.100)
    return JSONResponse({"ingested_pages": 50, "status": "completed"})


def create_test_app(manager: BulkheadManager) -> Starlette:
    routes = [
        Route("/v1/search", search_endpoint, methods=["GET", "POST"]),
        Route("/v1/ingest", ingest_endpoint, methods=["POST"]),
    ]
    return Starlette(
        routes=routes,
        middleware=[Middleware(BulkheadMiddleware, manager=manager)],
    )


async def run_bulkhead_load_test() -> dict[str, Any]:
    """Execute concurrent search query and ingestion load test."""
    config = BulkheadConfig(
        pool_limits={"query": 50, "ingest": 4, "eval": 2, "internal": 10},
        default_service_time_ms=10.0,
        max_queue_wait_ms=200.0,
    )
    manager = BulkheadManager(config)
    app = create_test_app(manager)

    search_latencies: list[float] = []
    search_successes = 0
    search_failures = 0

    ingest_successes = 0
    ingest_shed = 0

    async def client_request(path: str, headers: dict[str, str]) -> tuple[int, float]:
        scope = {
            "type": "http",
            "method": "POST" if "ingest" in path else "GET",
            "path": path,
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }

        response_status = 500
        t0 = time.perf_counter()

        async def send(msg: dict[str, Any]) -> None:
            nonlocal response_status
            if msg["type"] == "http.response.start":
                response_status = msg["status"]

        async def receive() -> dict[str, Any]:
            return {"type": "http.request"}

        await app(scope, receive, send)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return response_status, elapsed_ms

    async def search_worker(worker_id: int) -> None:
        nonlocal search_successes, search_failures
        # Each search worker executes 10 sequential queries
        for _ in range(10):
            status, latency = await client_request("/v1/search", {"X-Pool": "query"})
            if status == 200:
                search_successes += 1
                search_latencies.append(latency)
            else:
                search_failures += 1
            await asyncio.sleep(0.005)

    async def ingest_worker(worker_id: int) -> None:
        nonlocal ingest_successes, ingest_shed
        # Continuous heavy ingestion attempts to saturate ingest pool
        for _ in range(5):
            status, _ = await client_request("/v1/ingest", {"X-Pool": "ingest"})
            if status == 200:
                ingest_successes += 1
            elif status == 429:
                ingest_shed += 1
            await asyncio.sleep(0.010)

    # Launch 50 concurrent search workers and 20 concurrent ingestion workers
    search_tasks = [asyncio.create_task(search_worker(i)) for i in range(50)]
    ingest_tasks = [asyncio.create_task(ingest_worker(i)) for i in range(20)]

    await asyncio.gather(*search_tasks, *ingest_tasks)

    # Compute statistics
    search_latencies.sort()
    total_searches = search_successes + search_failures
    availability = (search_successes / total_searches * 100.0) if total_searches else 0.0
    p50_ms = statistics.median(search_latencies) if search_latencies else 0.0
    p95_idx = int(len(search_latencies) * 0.95)
    p95_ms = search_latencies[p95_idx] if search_latencies else 0.0

    report = {
        "total_searches": total_searches,
        "search_successes": search_successes,
        "search_failures": search_failures,
        "search_availability_pct": availability,
        "search_p50_latency_ms": round(p50_ms, 2),
        "search_p95_latency_ms": round(p95_ms, 2),
        "ingest_successes": ingest_successes,
        "ingest_shed": ingest_shed,
    }
    return report


def main() -> None:
    print("[FEAT-093] Executing Bulkhead Concurrency Isolation Load Test...")
    report = asyncio.run(run_bulkhead_load_test())
    print(f"Results: {report}")

    if report["search_availability_pct"] != 100.0:
        raise RuntimeError(
            f"Search availability failed: {report['search_availability_pct']}% < 100%"
        )
    if report["search_p95_latency_ms"] > 50.0:
        raise RuntimeError(
            f"Search p95 latency regressed: {report['search_p95_latency_ms']}ms > 50ms"
        )
    print("[PASS] FEAT-093 Bulkhead Load Test Passed: 100% availability, p95 <= 50ms.")


if __name__ == "__main__":
    main()
