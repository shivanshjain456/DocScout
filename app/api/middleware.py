"""Application HTTP Middlewares including Bulkhead Isolation (FEAT-093)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.bulkhead import (
    EXCLUDED_PATHS,
    GLOBAL_BULKHEAD,
    BulkheadManager,
    BulkheadRejectedException,
    determine_pool,
)


class BulkheadMiddleware(BaseHTTPMiddleware):
    """Isolates request concurrency by pool and sheds load adaptively via Little's Law."""

    def __init__(self, app: Any, manager: BulkheadManager | None = None) -> None:
        super().__init__(app)
        self.manager = manager or GLOBAL_BULKHEAD

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in EXCLUDED_PATHS:
            return await call_next(request)

        pool = determine_pool(path, request.headers)
        priority = request.headers.get("X-Priority", "normal")
        tenant_tier = request.headers.get("X-Tenant-Tier", "growth")

        try:
            async with self.manager.acquire(
                pool=pool, priority=priority, tenant_tier=tenant_tier
            ) as admission:
                request.state.bulkhead_admission = admission
                response: Response = await call_next(request)
                response.headers["X-Bulkhead-Pool"] = pool
                return response
        except BulkheadRejectedException as exc:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Bulkhead concurrency capacity exceeded: request shed",
                    "pool": exc.admission.pool,
                    "queue_depth": exc.admission.queue_depth,
                    "estimated_wait_ms": round(exc.admission.estimated_wait_ms, 2),
                    "rejection_reason": exc.admission.rejection_reason,
                },
                headers={"Retry-After": "1", "X-Bulkhead-Pool": exc.admission.pool},
            )
