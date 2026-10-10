"""Auth0 OAuth 2.0 / OpenID Connect authentication and server-side RBAC.

Enforces analyst identity and least-privilege role boundaries:
1. Validates JWT Bearer tokens signed with RS256 using Auth0 JSON Web Key Sets (JWKS).
2. Supports key rotation dynamically by querying `https://{AUTH0_DOMAIN}/.well-known/jwks.json`.
3. Validates issuer, audience, lifetime (exp, nbf), and signature.
4. Derives user identity strictly from validated token claims (`sub`, `email`, custom role claims).
5. Synchronizes analyst profiles into PostgreSQL `users` table upon authenticated request.
6. Enforces strict reader vs administrator authorization boundaries on sensitive operations.
7. Preserves backward-compatible API-key authentication for CLI and service automation,
   mapping configured keys to explicit service identities.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient, PyJWKClientError

from app.api.security import (
    rate_limiter,
)
from app.config import (
    auth0_admin_emails,
    auth0_admin_roles,
    auth0_audience,
    auth0_domain,
    auth0_issuer,
    key_fingerprint,
)
from app.observability import get_logger

logger = get_logger("docscout.auth0")


@dataclass(frozen=True)
class UserIdentity:
    """Authenticated analyst identity and role permissions."""

    user_id: UUID
    auth0_sub: str
    email: str
    role: str  # 'reader' | 'admin'
    display_name: str | None = None
    is_service_key: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class TokenVerificationError(HTTPException):
    """Raised when token validation fails. Preserves WWW-Authenticate headers."""

    def __init__(self, detail: str, status_code: int = status.HTTP_401_UNAUTHORIZED) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail,
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )


class InsufficientPermissionsError(HTTPException):
    """Raised when an authenticated user lacks required privileges (403 Forbidden)."""

    def __init__(self, detail: str = "administrative privilege required") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class Auth0TokenVerifier:
    """RS256 JWT verifier with cached JWKS retrieval and key rotation support."""

    def __init__(
        self,
        domain: str | None = None,
        audience: str | None = None,
        issuer: str | None = None,
    ) -> None:
        self.domain = (domain or auth0_domain()).strip()
        self.audience = (audience or auth0_audience()).strip()
        self.issuer = (issuer or auth0_issuer()).strip()
        self._jwks_client: PyJWKClient | None = None
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
                # PyJWKClient supports caching and key refresh on unknown kid
                self._jwks_client = PyJWKClient(self._jwks_url, cache_jwk_set=True, lifespan=3600)
            return self._jwks_client

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify an RS256 token against Auth0 JWKS and return claims payload."""
        if not token:
            raise TokenVerificationError("missing bearer token")

        try:
            client = self._get_client()
            signing_key = client.get_signing_key_from_jwt(token)
            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
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
            raise TokenVerificationError("token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenVerificationError(
                "token audience does not match configured audience"
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenVerificationError("token issuer does not match configured issuer") from exc
        except (PyJWKClientError, jwt.PyJWTError) as exc:
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
) -> UserIdentity:
    """Synchronize user record in PostgreSQL and return UserIdentity."""
    admin_emails = auth0_admin_emails()
    admin_roles = auth0_admin_roles()

    has_admin_claim = False
    if claim_roles:
        has_admin_claim = any(r.lower() in admin_roles for r in claim_roles)

    is_admin = has_admin_claim or (email.lower() in admin_emails)
    assigned_role = "admin" if is_admin else "reader"

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
                user_id = UUID(str(row[0]))
                existing_role = str(row[3])
                # Promote to admin if email or claim now grants it
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
                        (final_role, display_name, user_id),
                    )
                return UserIdentity(
                    user_id=user_id,
                    auth0_sub=auth0_sub,
                    email=str(row[2]),
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
                (auth0_sub, email, display_name, assigned_role),
            ).fetchone()

            if inserted is None:
                raise RuntimeError("failed to insert user")

            return UserIdentity(
                user_id=UUID(str(inserted[0])),
                auth0_sub=str(inserted[1]),
                email=str(inserted[2]),
                role=str(inserted[3]),
                display_name=str(inserted[4]) if inserted[4] else None,
            )


def authenticate_request(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> UserIdentity:
    """Authenticate incoming HTTP request via Auth0 Bearer token or fallback API Key."""
    # 1. Bearer Token path (Auth0 OAuth 2.0 / OIDC)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        verifier = get_token_verifier()
        payload = verifier.verify_token(token)

        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            raise TokenVerificationError("token missing sub claim")

        email = payload.get("email") or payload.get("https://docscout.local/email")
        if not email or not isinstance(email, str):
            email = f"{sub}@auth0.user"

        display_name = (
            payload.get("name")
            or payload.get("nickname")
            or payload.get("https://docscout.local/name")
        )

        roles: list[str] = []
        raw_roles = (
            payload.get("https://docscout.local/roles")
            or payload.get("roles")
            or payload.get("permissions")
        )
        if isinstance(raw_roles, list):
            roles = [str(r) for r in raw_roles]

        pool = getattr(request.app.state, "pool", None)
        if pool is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database connection pool not available",
            )

        identity = sync_user_in_db(
            pool=pool,
            auth0_sub=sub,
            email=email,
            display_name=str(display_name) if display_name else None,
            claim_roles=roles,
        )

        # Apply rate limiting per user subject
        allowed, remaining, retry_after = rate_limiter.check(f"user:{identity.auth0_sub}")
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        request.state.rate_limit_remaining = remaining
        request.state.user = identity
        return identity

    # 2. Backward compatibility: X-API-Key or Bearer <api_key>
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

        # Service identity for automated systems / test harness
        service_sub = f"system:api-key:{fingerprint}"
        pool = getattr(request.app.state, "pool", None)
        if pool is not None:
            identity = sync_user_in_db(
                pool=pool,
                auth0_sub=service_sub,
                email=f"service-{fingerprint}@docscout.internal",
                display_name=f"Service Key ({fingerprint})",
                claim_roles=["admin"],  # Service key holds operational admin capability
            )
            identity = UserIdentity(
                user_id=identity.user_id,
                auth0_sub=identity.auth0_sub,
                email=identity.email,
                role=identity.role,
                display_name=identity.display_name,
                is_service_key=True,
            )
        else:
            # Fallback when database is disconnected (e.g. mock probe)
            identity = UserIdentity(
                user_id=UUID("00000000-0000-0000-0000-000000000000"),
                auth0_sub=service_sub,
                email=f"service-{fingerprint}@docscout.internal",
                role="admin",
                display_name=f"Service Key ({fingerprint})",
                is_service_key=True,
            )

        request.state.user = identity
        return identity

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing Authorization Bearer token or X-API-Key header",
        headers={"WWW-Authenticate": "Bearer, X-API-Key"},
    )


def require_authenticated_user(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> UserIdentity:
    """Dependency: Require a valid Auth0 analyst identity or authorized service key."""
    return authenticate_request(request, authorization, x_api_key)


def require_admin_user(
    user: UserIdentity = Depends(require_authenticated_user),
) -> UserIdentity:
    """Dependency: Enforce administrator privileges on protected operational endpoints."""
    if not user.is_admin:
        raise InsufficientPermissionsError(
            f"user {user.email} (sub: {user.auth0_sub}) has role '{user.role}'; 'admin' required"
        )
    return user
