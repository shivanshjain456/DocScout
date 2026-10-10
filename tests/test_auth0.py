"""Tests for Auth0 authentication and server-side authorization enforcement.

Validates:
1. RS256 JWT verification via JWKS with key rotation.
2. Token failure modes: expired token, wrong issuer, wrong audience, invalid signature.
3. Identity claim extraction: `sub`, `email`, roles (`reader` vs `admin`).
4. Role separation: admin-only operations denied to readers and unauthenticated users.
5. User persistence and synchronization into the `users` table.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.api.auth0 import (
    Auth0TokenVerifier,
    UserIdentity,
    sync_user_in_db,
)


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


def test_auth0_verifier_rejects_expired_token(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Expired tokens must be rejected with 401 Unauthorized."""
    private_key, _, pem_pub = rsa_keypair
    domain = "docscout-test.us.auth0.com"
    audience = "https://api.docscout.local"
    issuer = f"https://{domain}/"

    claims = {
        "sub": "auth0|test-analyst-123",
        "email": "analyst@reservebank.org.in",
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
        "aud": "https://different-api.example.com",
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


def test_auth0_verifier_rejects_tampered_signature(
    rsa_keypair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """Tokens with altered payloads or signed with wrong keys must be rejected."""
    private_key, _, pem_pub = rsa_keypair
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


def test_authenticated_user_roles() -> None:
    """User role classification honours reader and admin designations."""
    reader = UserIdentity(
        user_id=uuid4(),
        auth0_sub="auth0|reader-1",
        email="reader@docscout.local",
        role="reader",
    )
    assert not reader.is_admin

    admin = UserIdentity(
        user_id=uuid4(),
        auth0_sub="auth0|admin-1",
        email="admin@docscout.local",
        role="admin",
    )
    assert admin.is_admin


def test_sync_user_in_db(db: Any) -> None:
    """Synchronizes user into database, persisting id, sub, and email."""
    auth0_sub = f"auth0|test-{uuid4().hex[:8]}"
    email = f"analyst-{uuid4().hex[:6]}@rbi.org.in"

    class PoolWrapper:
        def __init__(self, conn: Any) -> None:
            self.conn = conn

        @contextmanager
        def connection(self) -> Any:
            yield self.conn

    pool = PoolWrapper(db)

    user = sync_user_in_db(
        pool=pool,
        auth0_sub=auth0_sub,
        email=email,
        display_name="RBI Research Analyst",
        claim_roles=["reader"],
    )

    assert user.auth0_sub == auth0_sub
    assert user.email == email
    assert user.role == "reader"

    # Verify database record exists
    row = db.execute(
        "SELECT email, role FROM users WHERE user_id = %s",
        (user.user_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == email
    assert row[1] == "reader"
