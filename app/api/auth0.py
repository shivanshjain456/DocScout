"""Auth0 OAuth 2.0 / OpenID Connect authentication and server-side RBAC (FEAT-099).

Enforces analyst identity and least-privilege role boundaries:
1. Validates JWT Bearer tokens signed with RS256 using Auth0 JSON Web Key Sets (JWKS).
2. Supports key rotation dynamically by querying `https://{AUTH0_DOMAIN}/.well-known/jwks.json`.
3. Validates issuer, audience, lifetime (exp, nbf, iat), and signature.
4. Derives user identity strictly from validated token claims (`sub`, `email`, tenant, scopes).
5. Synchronizes analyst profiles into PostgreSQL `users` table upon authenticated request.
6. Enforces strict RBAC (`compliance:read`, `compliance:admin`, `audit:export`) across endpoints.
7. Preserves backward-compatible dual-mode API-key authentication for CLI and service automation.
8. Exposes Prometheus metrics `docscout_auth_successes_total` and `docscout_auth_failures_total`.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient, PyJWKClientError

from app.api.metrics import AUTH_FAILURES_TOTAL, AUTH_SUCCESSES_TOTAL
from app.api.security import rate_limiter
from app.config import (
    Auth0Config as Auth0Config,
)
from app.config import (
    auth0_admin_emails,
    auth0_admin_roles,
    auth0_audience,
    auth0_config,
    auth0_domain,
    auth0_issuer,
    key_fingerprint,
)
from app.observability import get_logger

logger = get_logger("docscout.auth0")


def _record_failure(reason: str) -> None:
    """Safely increment the authentication failure metric."""
    try:
        AUTH_FAILURES_TOTAL.labels(reason=reason).inc()
    except Exception as exc:
        logger.debug("auth.failure_metric_error", reason=reason, error=str(exc))


def _record_success(scope: str) -> None:
    """Safely increment the authentication success metric."""
    try:
        AUTH_SUCCESSES_TOTAL.labels(scope=scope).inc()
    except Exception as exc:
        logger.debug("auth.success_metric_error", scope=scope, error=str(exc))


def _bind_context(identity: AuthenticatedUser) -> None:
    """Safely inject identity claims into structlog request context."""
    try:
        import structlog.contextvars

        structlog.contextvars.bind_contextvars(
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            auth_method=identity.auth_method,
        )
    except Exception as exc:
        logger.debug("auth.contextvars_bind_error", error=str(exc))


def _try_parse_pem_public_key(key_val: Any) -> Any:
    """Pre-parse PEM string/bytes into RSA public key object to eliminate repeated parse overhead."""
    if isinstance(key_val, str) and "BEGIN" in key_val:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        try:
            return load_pem_public_key(key_val.encode("utf-8"))
        except Exception as exc:
            logger.debug("auth.pem_parse_str_fallback", error=str(exc))
            return key_val
    elif isinstance(key_val, bytes) and b"BEGIN" in key_val:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        try:
            return load_pem_public_key(key_val)
        except Exception as exc:
            logger.debug("auth.pem_parse_bytes_fallback", error=str(exc))
            return key_val
    return key_val


@dataclass
class AuthenticatedUser:
    """Authenticated analyst or service workload identity and RBAC permissions."""

    user_id: str
    email: str
    tenant_id: str = "default-tenant"
    scopes: list[str] = field(default_factory=list)
    is_admin: bool = False
    role: str = "reader"
    auth0_sub: str = ""
    display_name: str | None = None
    is_service_key: bool = False
    auth_method: str = "oidc"  # 'oidc' | 'api_key'

    def has_scope(self, scope: str) -> bool:
        """Check whether user holds the requested scope or administrative override."""
        return self.is_admin or scope in self.scopes or "admin" in self.scopes

    @property
    def user_uuid(self) -> UUID:
        """Parse or derive a valid UUID representation of the user ID."""
        try:
            return UUID(self.user_id)
        except ValueError:
            import hashlib

            h = hashlib.sha256(self.user_id.encode("utf-8")).digest()[:16]
            return UUID(bytes=h)


# Backward compatibility alias
UserIdentity = AuthenticatedUser


class TokenVerificationError(HTTPException):
    """Raised when token validation fails. Preserves WWW-Authenticate headers."""

    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_401_UNAUTHORIZED,
        headers: dict[str, str] | None = None,
    ) -> None:
        auth_headers = headers or {"WWW-Authenticate": 'Bearer error="invalid_token"'}
        super().__init__(
            status_code=status_code,
            detail=detail,
            headers=auth_headers,
        )


class InsufficientPermissionsError(HTTPException):
    """Raised when an authenticated user lacks required privileges (403 Forbidden)."""

    def __init__(self, detail: str = "administrative privilege required") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def parse_scopes_and_roles(payload: dict[str, Any]) -> tuple[list[str], bool, str]:
    """Extract fine-grained scopes, admin flag, and display role from JWT claims."""
    extracted_scopes: set[str] = set()

    # 1. Standard OAuth2 space-delimited scope string
    raw_scope = payload.get("scope")
    if isinstance(raw_scope, str):
        for s in raw_scope.split():
            clean = s.strip()
            if clean:
                extracted_scopes.add(clean)

    # 2. Auth0 API permissions array
    raw_permissions = payload.get("permissions")
    if isinstance(raw_permissions, list):
        for p in raw_permissions:
            if isinstance(p, str) and p.strip():
                extracted_scopes.add(p.strip())

    # 3. Custom roles or custom scopes claims
    for claim_key in (
        "https://docscout.com/scopes",
        "https://docscout.local/scopes",
        "https://docscout.com/roles",
        "https://docscout.local/roles",
        "roles",
    ):
        val = payload.get(claim_key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    extracted_scopes.add(item.strip())
        elif isinstance(val, str) and val.strip():
            extracted_scopes.add(val.strip())

    admin_roles = auth0_admin_roles()
    admin_emails = auth0_admin_emails()
    email = str(payload.get("email") or payload.get("https://docscout.local/email") or "").lower()

    is_admin = (
        "admin" in extracted_scopes
        or "compliance:admin" in extracted_scopes
        or bool(payload.get("is_admin"))
        or any(r in extracted_scopes for r in admin_roles)
        or (bool(email) and email in admin_emails)
    )

    if is_admin:
        extracted_scopes.add("compliance:admin")
        extracted_scopes.add("compliance:read")
        extracted_scopes.add("audit:export")
        role = "admin"
    else:
        extracted_scopes.add("compliance:read")
        role = "reader"

    return sorted(extracted_scopes), is_admin, role


def parse_tenant_id(payload: dict[str, Any]) -> str:
    """Extract tenant identifier from enterprise claims, defaulting safely."""
    for key in (
        "https://docscout.com/tenant_id",
        "https://docscout.local/tenant_id",
        "tenant_id",
        "org_id",
        "organization_id",
    ):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "default-tenant"


class Auth0TokenVerifier:
    """RS256 JWT verifier with cached JWKS retrieval and key rotation support."""

    def __init__(
        self,
        domain: str | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        jwks_cache_ttl_seconds: int = 3600,
        config: Auth0Config | None = None,
    ) -> None:
        cfg = config or auth0_config()
        self.domain = (domain or cfg.domain or auth0_domain()).strip()
        self.audience = (audience or cfg.audience or auth0_audience()).strip()
        self.issuer = (issuer or cfg.issuer or auth0_issuer()).strip()
        self.jwks_cache_ttl_seconds = jwks_cache_ttl_seconds or cfg.jwks_cache_ttl_seconds

        self._jwks_client: PyJWKClient | None = None
        self._key_cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._jwks_url: str = ""
        if self.domain:
            host = self.domain if self.domain.startswith("http") else f"https://{self.domain}"
            self._jwks_url = f"{host.rstrip('/')}/.well-known/jwks.json"

    def _get_client(self) -> PyJWKClient:
        with self._lock:
            if self._jwks_client is None:
                if not self._jwks_url:
                    raise TokenVerificationError("Auth0 domain is not configured")
                self._jwks_client = PyJWKClient(
                    self._jwks_url,
                    cache_jwk_set=True,
                    cache_keys=True,
                    lifespan=float(self.jwks_cache_ttl_seconds),
                )
            return self._jwks_client

    def _resolve_signing_key(self, token: str, header: dict[str, Any] | None = None) -> Any:
        """Resolve signing key from in-memory cache (< 0.05ms) or PyJWKClient."""
        now = time.monotonic()
        try:
            unverified_header = header or jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
        except Exception as exc:
            _record_failure("malformed_token")
            raise TokenVerificationError(f"malformed token header: {exc}") from exc

        if kid:
            with self._lock:
                cached = self._key_cache.get(kid)
                if cached:
                    key_obj, expiry = cached
                    if now < expiry:
                        return key_obj

        client = self._get_client()
        try:
            signing_key = client.get_signing_key_from_jwt(token)
            key_val = _try_parse_pem_public_key(signing_key.key)
            if kid:
                with self._lock:
                    self._key_cache[kid] = (key_val, now + self.jwks_cache_ttl_seconds)
            return key_val
        except Exception as exc:
            _record_failure("jwks_resolution_error")
            raise TokenVerificationError(f"unable to resolve signing key: {exc}") from exc

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify an RS256 token against Auth0 JWKS and return claims payload."""
        if not token:
            _record_failure("missing_token")
            raise TokenVerificationError("missing bearer token")

        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg")
            if alg != "RS256":
                _record_failure("invalid_algorithm")
                raise TokenVerificationError(f"unsupported algorithm '{alg}'; RS256 required")

            key_val = self._resolve_signing_key(token, header=header)
            payload: dict[str, Any] = jwt.decode(
                token,
                key_val,
                algorithms=["RS256"],
                audience=self.audience if self.audience else None,
                issuer=self.issuer if self.issuer else None,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": bool(self.audience),
                    "verify_iss": bool(self.issuer),
                },
            )
            return payload
        except jwt.ExpiredSignatureError as exc:
            _record_failure("expired_token")
            raise TokenVerificationError(
                "token has expired",
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="invalid_token", error_description="The token has expired"'
                    )
                },
            ) from exc
        except jwt.InvalidAudienceError as exc:
            _record_failure("invalid_audience")
            raise TokenVerificationError(
                "token audience does not match configured audience"
            ) from exc
        except jwt.InvalidIssuerError as exc:
            _record_failure("invalid_issuer")
            raise TokenVerificationError("token issuer does not match configured issuer") from exc
        except jwt.InvalidSignatureError as exc:
            _record_failure("invalid_signature")
            raise TokenVerificationError("invalid token signature") from exc
        except (PyJWKClientError, jwt.PyJWTError) as exc:
            _record_failure("invalid_token")
            raise TokenVerificationError(f"invalid bearer token: {exc}") from exc


# Global verifier instance (can be swapped in unit tests)
_global_verifier = Auth0TokenVerifier()


def get_token_verifier() -> Auth0TokenVerifier:
    return _global_verifier


def set_token_verifier(verifier: Auth0TokenVerifier) -> None:
    global _global_verifier
    _global_verifier = verifier


def sync_user_in_db(
    pool: Any,
    auth0_sub: str,
    email: str,
    display_name: str | None = None,
    claim_roles: list[str] | None = None,
    tenant_id: str = "default-tenant",
) -> AuthenticatedUser:
    """Synchronize user record in PostgreSQL and return AuthenticatedUser."""
    scopes, is_admin, role = parse_scopes_and_roles(
        {
            "email": email,
            "roles": claim_roles or [],
            "tenant_id": tenant_id,
        }
    )

    with pool.connection() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                SELECT user_id, auth0_sub, email, role, display_name
                  FROM users
                 WHERE auth0_sub = %s
                """,
                (auth0_sub,),
            ).fetchone()

            if row is not None:
                user_id = str(row[0])
                existing_role = str(row[3])
                final_role = "admin" if (is_admin or existing_role == "admin") else "reader"
                if final_role != existing_role or (display_name and display_name != row[4]):
                    conn.execute(
                        """
                        UPDATE users
                           SET role = %s,
                               display_name = COALESCE(%s, display_name),
                               updated_at = now()
                         WHERE user_id = %s
                        """,
                        (final_role, display_name, UUID(user_id)),
                    )
                return AuthenticatedUser(
                    user_id=user_id,
                    auth0_sub=auth0_sub,
                    email=str(row[2]),
                    tenant_id=tenant_id,
                    scopes=scopes,
                    is_admin=(final_role == "admin"),
                    role=final_role,
                    display_name=str(row[4]) if row[4] else display_name,
                )

            # Insert new analyst profile
            inserted = conn.execute(
                """
                INSERT INTO users (auth0_sub, email, display_name, role)
                VALUES (%s, %s, %s, %s)
                RETURNING user_id, auth0_sub, email, role, display_name
                """,
                (auth0_sub, email, display_name, role),
            ).fetchone()

            if inserted is None:
                raise RuntimeError("failed to insert user")

            return AuthenticatedUser(
                user_id=str(inserted[0]),
                auth0_sub=str(inserted[1]),
                email=str(inserted[2]),
                tenant_id=tenant_id,
                scopes=scopes,
                is_admin=is_admin,
                role=str(inserted[3]),
                display_name=str(inserted[4]) if inserted[4] else None,
            )


def authenticate_request(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> AuthenticatedUser:
    """Authenticate incoming HTTP request via Auth0 Bearer token or fallback API Key."""
    # 1. Bearer Token path (Auth0 OAuth 2.0 / OIDC)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        verifier = get_token_verifier()
        payload = verifier.verify_token(token)

        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            _record_failure("missing_sub")
            raise TokenVerificationError("token missing sub claim")

        email = payload.get("email") or payload.get("https://docscout.local/email")
        if not email or not isinstance(email, str):
            email = f"{sub}@auth0.user"

        display_name = (
            payload.get("name")
            or payload.get("nickname")
            or payload.get("https://docscout.local/name")
        )

        tenant_id = parse_tenant_id(payload)
        scopes, is_admin, role = parse_scopes_and_roles(payload)

        pool = getattr(request.app.state, "pool", None)
        if pool is not None:
            identity = sync_user_in_db(
                pool=pool,
                auth0_sub=sub,
                email=email,
                display_name=str(display_name) if display_name else None,
                claim_roles=scopes,
                tenant_id=tenant_id,
            )
        else:
            identity = AuthenticatedUser(
                user_id=sub,
                auth0_sub=sub,
                email=email,
                tenant_id=tenant_id,
                scopes=scopes,
                is_admin=is_admin,
                role=role,
                display_name=str(display_name) if display_name else None,
                auth_method="oidc",
            )

        # Rate limiting per user subject
        allowed, remaining, retry_after = rate_limiter.check(f"user:{identity.auth0_sub}")
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        request.state.rate_limit_remaining = remaining
        request.state.user = identity
        request.state.tenant_id = identity.tenant_id

        _bind_context(identity)

        for s in identity.scopes:
            _record_success(s)

        return identity

    # 2. Backward compatibility fallback: X-API-Key or Bearer <api_key>
    candidate_key: str | None = x_api_key
    if not candidate_key and authorization and not authorization.startswith("Bearer "):
        candidate_key = authorization.strip()

    if candidate_key:
        keys: frozenset[str] = getattr(request.app.state, "api_keys", frozenset())
        matched: str | None = None
        for key in keys:
            if secrets.compare_digest(candidate_key, key):
                matched = key
                break

        if matched is None:
            _record_failure("invalid_api_key")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid API key or bearer token",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token", X-API-Key'},
            )

        fingerprint = key_fingerprint(matched)
        allowed, remaining, retry_after = rate_limiter.check(fingerprint)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        request.state.rate_limit_remaining = remaining

        service_sub = f"system:api-key:{fingerprint}"
        admin_scopes = ["compliance:read", "compliance:admin", "audit:export"]
        pool = getattr(request.app.state, "pool", None)
        if pool is not None:
            identity = sync_user_in_db(
                pool=pool,
                auth0_sub=service_sub,
                email=f"service-{fingerprint}@docscout.internal",
                display_name=f"Service Key ({fingerprint})",
                claim_roles=["admin"],
                tenant_id="default-tenant",
            )
            identity = AuthenticatedUser(
                user_id=identity.user_id,
                auth0_sub=identity.auth0_sub,
                email=identity.email,
                tenant_id="default-tenant",
                scopes=admin_scopes,
                is_admin=True,
                role="admin",
                display_name=identity.display_name,
                is_service_key=True,
                auth_method="api_key",
            )
        else:
            identity = AuthenticatedUser(
                user_id=f"service-{fingerprint[:8]}",
                auth0_sub=service_sub,
                email=f"service-{fingerprint[:8]}@docscout.internal",
                tenant_id="default-tenant",
                scopes=admin_scopes,
                is_admin=True,
                role="admin",
                display_name=f"Service Key ({fingerprint[:8]})",
                is_service_key=True,
                auth_method="api_key",
            )

        request.state.user = identity
        request.state.tenant_id = identity.tenant_id

        _bind_context(identity)
        _record_success("api_key")

        return identity

    _record_failure("missing_token")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing Authorization Bearer token or X-API-Key header",
        headers={"WWW-Authenticate": "Bearer, X-API-Key"},
    )


def require_authenticated_user(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> AuthenticatedUser:
    """Dependency: Require a valid Auth0 analyst identity or authorized service key."""
    return authenticate_request(request, authorization, x_api_key)


def require_admin_user(
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUser:
    """Dependency: Enforce administrator privileges on protected operational endpoints."""
    if not user.is_admin:
        _record_failure("insufficient_scope")
        raise InsufficientPermissionsError(
            f"user {user.email} (sub: {user.auth0_sub}) has role '{user.role}'; 'admin' required"
        )
    return user


def require_scope(required_scope: str) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Dependency factory: Enforce required RBAC scope on route."""

    def _scope_dependency(
        user: AuthenticatedUser = Depends(require_authenticated_user),
    ) -> AuthenticatedUser:
        if not user.has_scope(required_scope):
            _record_failure("insufficient_scope")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: insufficient permissions, required scope '{required_scope}'",
            )
        return user

    return _scope_dependency
