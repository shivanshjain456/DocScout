"""API-key authentication and a per-key request budget.

Why a shared secret rather than OAuth or JWT: the demo has exactly one kind of caller and
no user identity to model. A JWT would add a signing key, an expiry policy and a refresh
path to protect a read-only search endpoint over public regulatory documents. The threat
being defended against is an open endpoint on a public URL burning CPU, not impersonation.

Three properties this file exists to guarantee:

* Comparison is constant time. `==` on a secret leaks its prefix through timing, and an
  endpoint on a public URL is exactly where that becomes reachable.
* A missing key configuration fails closed, loudly, at startup. Auth that switches itself
  off when an environment variable is absent is the deploy hole that looks healthy.
* The key itself never reaches a log, a trace or an error body. Only a truncated SHA-256
  fingerprint, which is enough to tell two callers apart and not enough to replay.
"""

from __future__ import annotations

import os
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

from fastapi import Header, HTTPException, Request, status

from app.config import api_keys, key_fingerprint


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back on anything unusable.

    A malformed limit must not crash the service or, worse, be read as zero and refuse
    every request. An unreadable value is a configuration mistake, not a reason to take
    the API down, so it is logged by the caller and the default stands.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Requests allowed per key per window. The endpoint runs a CPU-bound retrieval path on a
# 2 vCPU box, so this protects the demo from a single caller rather than implementing a
# commercial quota. Configurable because the benchmark has to exceed it deliberately, and
# because the right number depends on the host -- but it is a conscious override, not an
# off switch: there is no value that disables the limiter.
RATE_LIMIT_REQUESTS = _positive_int_env("DOCSCOUT_RATE_LIMIT_PER_MINUTE", 60)
RATE_LIMIT_WINDOW_SECONDS = 60.0


class AuthConfigurationError(RuntimeError):
    """No API keys configured. Raised at startup, never per request."""


@dataclass
class RateLimiter:
    """A sliding-window limiter, in process and deliberately so.

    In-process means it does not survive a restart and does not coordinate across workers.
    Both are acceptable here and neither is hidden: this is one process serving a demo. A
    multi-worker deployment needs Redis, and the moment that is true this class should be
    replaced rather than quietly trusted -- which is why the limit is reported in /healthz,
    so the discrepancy is visible rather than theoretical.

    A sliding window rather than a fixed one because a fixed window lets a caller send
    2x the limit across a boundary instant, which on a 2 vCPU box is the difference
    between a slow response and a timeout.
    """

    limit: int = RATE_LIMIT_REQUESTS
    window: float = RATE_LIMIT_WINDOW_SECONDS
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def check(self, identity: str, *, now: float | None = None) -> tuple[bool, int, float]:
        """Record a request. Returns (allowed, remaining, seconds until reset)."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits.setdefault(identity, deque())
            cutoff = moment - self.window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = bucket[0] + self.window - moment
                return False, 0, max(retry_after, 0.0)
            bucket.append(moment)
            return True, self.limit - len(bucket), self.window

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Module-level so every request shares one window. Rebound by tests.
rate_limiter = RateLimiter()


def load_keys() -> frozenset[str]:
    """Read the configured keys, refusing to run without any.

    Called once during startup so the failure is a crash at boot rather than a surprise on
    the first request, by which time the service is already reachable.
    """
    keys = api_keys()
    if not keys:
        raise AuthConfigurationError(
            "DOCSCOUT_API_KEY is empty. The API will not start without at least one key: "
            "an unauthenticated public endpoint is not a safe default. Generate one with "
            "`openssl rand -hex 24` and put it in .env (see .env.example)."
        )
    return keys


def _match(candidate: str, keys: frozenset[str]) -> str | None:
    """Constant-time membership test.

    Every configured key is compared even after a match, so the work done does not depend
    on which key matched or on how many keys precede it.
    """
    found: str | None = None
    for key in keys:
        if secrets.compare_digest(candidate, key):
            found = key
    return found


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency: authenticate, rate limit, and return the key fingerprint.

    Returns the fingerprint rather than the key so that nothing downstream -- a handler, a
    log line, an exception -- can accidentally hold the credential.
    """
    keys: frozenset[str] = request.app.state.api_keys
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-API-Key header",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    matched = _match(x_api_key, keys)
    if matched is None:
        # Deliberately identical to the missing-key message in shape and status: a
        # different response for "wrong key" than for "no key" tells a prober that a key
        # was well-formed, and the fingerprint of a rejected key is not logged either.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    fingerprint = key_fingerprint(matched)
    allowed, remaining, retry_after = rate_limiter.check(fingerprint)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"rate limit exceeded: {RATE_LIMIT_REQUESTS} requests per "
                f"{int(RATE_LIMIT_WINDOW_SECONDS)}s"
            ),
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    request.state.rate_limit_remaining = remaining
    return fingerprint
