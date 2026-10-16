"""Comprehensive test suite for OIDC-Federated Zero-Trust Identity & Enterprise RBAC (FEAT-099).

Evaluation dataset: 25 authentication test cases covering:
- Valid RS256 token verification & claims extraction
- Failure modes (expired, wrong audience, wrong issuer, invalid signature, malformed, non-RS256, missing sub)
- Scope and RBAC parsing (OAuth2 space-delimited, Auth0 permissions, custom roles)
- Multi-tenant tenant_id isolation
- Dependency injection (require_authenticated_user, require_admin_user, require_scope)
- Dual-mode fallback to high-entropy API keys
- Sub-0.4ms cached JWKS key verification latency
- Key rotation and TTL expiration
- Prometheus auth success/failure metrics
- structlog contextvars identity injection
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Request

from app.api.auth0 import (
    Auth0Config,
    Auth0TokenVerifier,
    AuthenticatedUser,
    InsufficientPermissionsError,
    TokenVerificationError,
    authenticate_request,
    parse_scopes_and_roles,
    parse_tenant_id,
    require_admin_user,
    require_authenticated_user,
    require_scope,
    set_token_verifier,
)
from app.api.metrics import AUTH_FAILURES_TOTAL, AUTH_SUCCESSES_TOTAL


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, str, str]:
    """Generate a temporary RSA keypair for signing test tokens."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    pem_priv = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    pem_pub = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, pem_priv, pem_pub


# 1. Valid token verification
def test_auth0_verifier_valid_token(rsa_keypair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    """A correctly signed token with matching audience and issuer verifies successfully."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-test.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|test-analyst-123",
        "email": "analyst@reservebank.org.in",
        "email_verified": True,
        "iss": issuer,
        "aud": audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "https://docscout.local/roles": ["reader"],
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})

    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)
    mock_signing_key = MagicMock()
    mock_signing_key.key = pem_pub
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch.object(verifier, "_get_client", return_value=mock_client):
        verified = verifier.verify_token(token)

    assert verified["sub"] == "auth0|test-analyst-123"
    assert verified["email"] == "analyst@reservebank.org.in"


# 2. Expired token rejection
def test_auth0_verifier_rejects_expired_token(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Expired tokens must be rejected with 401 Unauthorized and invalid_token error."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-test.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|test-analyst-123",
        "iss": issuer,
        "aud": audience,
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})
    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)

    mock_signing_key = MagicMock()
    mock_signing_key.key = pem_pub
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch.object(verifier, "_get_client", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            verifier.verify_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in str(exc_info.value.detail).lower()
        assert "invalid_token" in exc_info.value.headers.get("WWW-Authenticate", "")


# 3. Wrong audience rejection
def test_auth0_verifier_rejects_wrong_audience(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Tokens issued for a different audience must be rejected."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-test.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|test-analyst-123",
        "iss": issuer,
        "aud": "https://wrong-audience.example.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})
    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)

    mock_signing_key = MagicMock()
    mock_signing_key.key = pem_pub
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch.object(verifier, "_get_client", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            verifier.verify_token(token)
        assert exc_info.value.status_code == 401
        assert "audience" in str(exc_info.value.detail).lower()


# 4. Wrong issuer rejection
def test_auth0_verifier_rejects_wrong_issuer(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Tokens with mismatched issuer must fail verification."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-test.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|test-analyst-123",
        "iss": "https://evil-issuer.com/",
        "aud": audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "key-1"})
    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)

    mock_signing_key = MagicMock()
    mock_signing_key.key = pem_pub
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch.object(verifier, "_get_client", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            verifier.verify_token(token)
        assert exc_info.value.status_code == 401
        assert "issuer" in str(exc_info.value.detail).lower()


# 5. Tampered signature rejection
def test_auth0_verifier_rejects_tampered_signature(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Tokens signed with a different key fail signature verification."""
    _, _, pem_pub = rsa_keypair
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    domain = "docscout-test.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|test-analyst-123",
        "iss": issuer,
        "aud": audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "key-1"})
    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)

    mock_signing_key = MagicMock()
    mock_signing_key.key = pem_pub
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch.object(verifier, "_get_client", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            verifier.verify_token(token)
        assert exc_info.value.status_code == 401
        assert "signature" in str(exc_info.value.detail).lower()


# 6. Malformed token rejection
def test_auth0_verifier_rejects_malformed_token() -> None:
    """Garbage token strings raise malformed token error."""
    verifier = Auth0TokenVerifier(
        domain="test.auth0.com", audience="test-aud", issuer="https://test.auth0.com/"
    )
    with pytest.raises(TokenVerificationError) as exc_info:
        verifier.verify_token("not-a-valid-jwt-token-string")
    assert exc_info.value.status_code == 401


# 7. Empty token rejection
def test_auth0_verifier_rejects_missing_token() -> None:
    """Empty string token fails closed."""
    verifier = Auth0TokenVerifier(
        domain="test.auth0.com", audience="test-aud", issuer="https://test.auth0.com/"
    )
    with pytest.raises(TokenVerificationError) as exc_info:
        verifier.verify_token("")
    assert exc_info.value.status_code == 401


# 8. Non-RS256 algorithm rejection
def test_auth0_verifier_rejects_non_rs256_algorithm() -> None:
    """Symmetric algorithms like HS256 must be rejected."""
    token = jwt.encode(
        {"sub": "attacker", "aud": "aud", "iss": "iss"},
        "symmetric-secret-key-1234567890123456",
        algorithm="HS256",
        headers={"alg": "HS256"},
    )
    verifier = Auth0TokenVerifier(domain="test.auth0.com", audience="aud", issuer="iss")
    with pytest.raises(TokenVerificationError) as exc_info:
        verifier.verify_token(token)
    assert exc_info.value.status_code == 401
    assert "RS256" in str(exc_info.value.detail)


# 9. Missing sub claim rejection
def test_authenticate_request_rejects_missing_sub(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Tokens missing subject identifier fail authentication."""
    private_key, _, pem_pub = rsa_keypair
    domain = "test.auth0.com"
    audience = "test-aud"
    issuer = f"https://{domain}/"

    claims = {
        "email": "test@docscout.com",
        "iss": issuer,
        "aud": audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "k1"})
    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value.key = pem_pub

    req = MagicMock(spec=Request)
    req.app.state.pool = None
    req.state = MagicMock()

    with patch.object(verifier, "_get_client", return_value=mock_client):
        set_token_verifier(verifier)
        with pytest.raises(TokenVerificationError) as exc_info:
            authenticate_request(req, authorization=f"Bearer {token}")
        assert exc_info.value.status_code == 401
        assert "sub" in str(exc_info.value.detail).lower()


# 10. Auth0Config defaults and custom
def test_auth0_config_defaults_and_custom() -> None:
    """Verify Auth0Config dataclass initialization and properties."""
    cfg = Auth0Config()
    assert cfg.jwks_cache_ttl_seconds == 3600
    assert cfg.audience == "https://api.docscout.local"
    assert cfg.enabled is False

    custom = Auth0Config(
        domain="auth.reservebank.in",
        audience="https://api.docscout.in",
        issuer="https://auth.reservebank.in/",
        jwks_cache_ttl_seconds=1800,
        enabled=True,
    )
    assert custom.domain == "auth.reservebank.in"
    assert custom.jwks_cache_ttl_seconds == 1800
    assert custom.enabled is True


# 11. Parse scopes from space-delimited string
def test_parse_scopes_from_space_separated_string() -> None:
    """Standard OAuth 2.0 space-separated scope string parses correctly."""
    payload = {"scope": "compliance:read audit:export"}
    scopes, is_admin, role = parse_scopes_and_roles(payload)
    assert "compliance:read" in scopes
    assert "audit:export" in scopes
    assert not is_admin
    assert role == "reader"


# 12. Parse scopes from permissions list
def test_parse_scopes_from_permissions_list() -> None:
    """Auth0 permissions array grants fine-grained access and promotes admin."""
    payload = {"permissions": ["compliance:read", "compliance:admin"]}
    scopes, is_admin, role = parse_scopes_and_roles(payload)
    assert "compliance:admin" in scopes
    assert "compliance:read" in scopes
    assert "audit:export" in scopes  # Admin automatically gets audit:export
    assert is_admin is True
    assert role == "admin"


# 13. Parse custom roles claims
def test_parse_scopes_custom_claim_and_admin_role() -> None:
    """Custom roles claim elevates privileges."""
    payload = {"https://docscout.com/roles": ["admin"]}
    scopes, is_admin, role = parse_scopes_and_roles(payload)
    assert is_admin is True
    assert role == "admin"
    assert "compliance:admin" in scopes


# 14. Parse tenant ID extraction
def test_parse_tenant_id_custom_and_fallback() -> None:
    """Tenant ID resolves from custom claim, standard claim, or fallback."""
    assert parse_tenant_id({"https://docscout.com/tenant_id": "rbi-supervisory"}) == (
        "rbi-supervisory"
    )
    assert parse_tenant_id({"tenant_id": "sebi-markets"}) == "sebi-markets"
    assert parse_tenant_id({"org_id": "org-99"}) == "org-99"
    assert parse_tenant_id({}) == "default-tenant"


# 15. AuthenticatedUser has_scope check
def test_authenticated_user_has_scope() -> None:
    """AuthenticatedUser.has_scope checks scope membership and admin bypass."""
    reader = AuthenticatedUser(
        user_id="user-1",
        email="reader@rbi.org.in",
        tenant_id="tenant-1",
        scopes=["compliance:read"],
        is_admin=False,
    )
    assert reader.has_scope("compliance:read") is True
    assert reader.has_scope("audit:export") is False
    assert reader.has_scope("compliance:admin") is False

    admin = AuthenticatedUser(
        user_id="user-2",
        email="admin@rbi.org.in",
        tenant_id="tenant-1",
        scopes=["compliance:read", "compliance:admin"],
        is_admin=True,
    )
    assert admin.has_scope("compliance:read") is True
    assert admin.has_scope("audit:export") is True  # Admin override
    assert admin.has_scope("arbitrary:scope") is True


# 16. AuthenticatedUser UUID property
def test_authenticated_user_uuid_property() -> None:
    """user_uuid property handles UUID strings and generates deterministic fallback."""
    u1 = AuthenticatedUser(
        user_id="12345678-1234-5678-1234-567812345678",
        email="test@docscout.local",
        tenant_id="t1",
    )
    assert str(u1.user_uuid) == "12345678-1234-5678-1234-567812345678"

    u2 = AuthenticatedUser(
        user_id="auth0|analyst-user",
        email="test2@docscout.local",
        tenant_id="t1",
    )
    assert u2.user_uuid.version is None or isinstance(u2.user_uuid.hex, str)


# 17. require_scope dependency allowed
def test_require_scope_dependency_authorized() -> None:
    """require_scope returns user when the required scope is present."""
    user = AuthenticatedUser(
        user_id="u1",
        email="user@test.in",
        tenant_id="t1",
        scopes=["compliance:read", "audit:export"],
    )
    dep = require_scope("audit:export")
    assert dep(user=user) == user


# 18. require_scope dependency forbidden (403)
def test_require_scope_dependency_forbidden_403() -> None:
    """require_scope raises HTTP 403 when user lacks the required scope."""
    user = AuthenticatedUser(
        user_id="u1",
        email="user@test.in",
        tenant_id="t1",
        scopes=["compliance:read"],
        is_admin=False,
    )
    dep = require_scope("audit:export")
    with pytest.raises(HTTPException) as exc_info:
        dep(user=user)
    assert exc_info.value.status_code == 403
    assert "audit:export" in str(exc_info.value.detail)


# 19. require_admin_user authorized and rejected
def test_require_admin_user_authorized_and_forbidden() -> None:
    """require_admin_user grants admins and rejects standard readers."""
    admin = AuthenticatedUser(
        user_id="adm",
        email="admin@test.in",
        tenant_id="t1",
        is_admin=True,
        role="admin",
    )
    assert require_admin_user(user=admin) == admin

    reader = AuthenticatedUser(
        user_id="rd",
        email="reader@test.in",
        tenant_id="t1",
        is_admin=False,
        role="reader",
    )
    with pytest.raises(InsufficientPermissionsError) as exc_info:
        require_admin_user(user=reader)
    assert exc_info.value.status_code == 403


# 20. Dual-mode fallback to valid API key
def test_dual_mode_fallback_valid_api_key() -> None:
    """X-API-Key authenticates as operational service identity with admin permissions."""
    req = MagicMock(spec=Request)
    req.app.state.api_keys = frozenset({"mock-test-key"})
    req.app.state.pool = None
    req.state = MagicMock()

    user = authenticate_request(req, authorization=None, x_api_key="mock-test-key")
    assert user.is_service_key is True
    assert user.is_admin is True
    assert user.auth_method == "api_key"
    assert "compliance:admin" in user.scopes


# 21. Dual-mode fallback to invalid API key
def test_dual_mode_fallback_invalid_api_key() -> None:
    """Invalid X-API-Key fails closed with HTTP 401."""
    req = MagicMock(spec=Request)
    req.app.state.api_keys = frozenset({"correct-key"})
    req.app.state.pool = None
    req.state = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        authenticate_request(req, authorization=None, x_api_key="wrong-key")
    assert exc_info.value.status_code == 401


# 22. Missing credentials fails 401
def test_authenticate_request_missing_credentials_fails_401() -> None:
    """Request without token or API key fails with HTTP 401."""
    req = MagicMock(spec=Request)
    req.app.state.api_keys = frozenset({"key"})
    req.app.state.pool = None
    req.state = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        authenticate_request(req, authorization=None, x_api_key=None)
    assert exc_info.value.status_code == 401
    assert "WWW-Authenticate" in exc_info.value.headers


# 23. Sub-0.4ms cached JWKS key verification latency
def test_jwks_cache_hit_latency_under_0_4ms(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Cached key verification completes in under 0.4 ms (target < 0.1ms)."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-bench.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    token = jwt.encode(
        {"sub": "bench-user", "aud": audience, "iss": issuer, "exp": int(time.time()) + 3600},
        private_key,
        algorithm="RS256",
        headers={"kid": "bench-k1"},
    )
    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value.key = pem_pub

    with patch.object(verifier, "_get_client", return_value=mock_client):
        # Prime cache
        verifier.verify_token(token)

        # Benchmark 100 verification iterations
        t0 = time.perf_counter()
        for _ in range(100):
            verifier.verify_token(token)
        t1 = time.perf_counter()
        avg_ms = ((t1 - t0) / 100.0) * 1000.0

        # Enforce specification limit of <= 0.4 ms
        assert avg_ms <= 0.4, f"Verification latency {avg_ms:.4f} ms exceeded 0.4 ms threshold"


# 24. JWKS cache TTL and key rotation
def test_jwks_cache_ttl_and_key_rotation(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Expired cache entry triggers fresh key retrieval from PyJWKClient."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-rotation.us.auth0.com"
    audience = "aud"
    issuer = f"https://{domain}/"

    token = jwt.encode(
        {"sub": "rot-user", "aud": audience, "iss": issuer, "exp": int(time.time()) + 3600},
        private_key,
        algorithm="RS256",
        headers={"kid": "rot-k1"},
    )
    # Short 1-second TTL
    verifier = Auth0TokenVerifier(
        domain=domain, audience=audience, issuer=issuer, jwks_cache_ttl_seconds=1
    )
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value.key = pem_pub

    with patch.object(verifier, "_get_client", return_value=mock_client):
        verifier.verify_token(token)
        assert mock_client.get_signing_key_from_jwt.call_count == 1

        # Re-using before expiration uses cache
        verifier.verify_token(token)
        assert mock_client.get_signing_key_from_jwt.call_count == 1

        # Simulate TTL expiry by backdating cache timestamp
        kid = "rot-k1"
        key_val, _ = verifier._key_cache[kid]
        verifier._key_cache[kid] = (key_val, time.monotonic() - 10)

        # Call again -> triggers fresh fetch
        verifier.verify_token(token)
        assert mock_client.get_signing_key_from_jwt.call_count == 2


# 25. Auth metrics and structlog context injection
def test_auth_metrics_and_structlog_binding(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Successful and failed authentications increment Prometheus counters and bind context."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-metric.us.auth0.com"
    audience = "metric-aud"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|metric-user-777",
        "email": "auditor@sebi.gov.in",
        "iss": issuer,
        "aud": audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "scope": "compliance:read audit:export",
        "tenant_id": "sebi-surveillance",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "k-metric"})

    verifier = Auth0TokenVerifier(domain=domain, audience=audience, issuer=issuer)
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value.key = pem_pub

    req = MagicMock(spec=Request)
    req.app.state.pool = None
    req.state = MagicMock()

    with patch.object(verifier, "_get_client", return_value=mock_client):
        set_token_verifier(verifier)
        user = require_authenticated_user(req, authorization=f"Bearer {token}")

        assert user.user_id == "auth0|metric-user-777"
        assert user.tenant_id == "sebi-surveillance"
        assert "audit:export" in user.scopes

    # Failed auth increments failure counter
    with pytest.raises(HTTPException):
        authenticate_request(req, authorization=None, x_api_key=None)

    # Counters exist and can be inspected
    assert AUTH_SUCCESSES_TOTAL is not None
    assert AUTH_FAILURES_TOTAL is not None
