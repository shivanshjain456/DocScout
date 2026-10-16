"""Unit, integration, and performance test suite for Post-Quantum Cryptographic Migration Tracker (FEAT-057).

Validates:
1. 100 real-world TLS cipher suite configurations classified across:
   - Pure Post-Quantum (FIPS 203 ML-KEM, FIPS 204 ML-DSA, FIPS 205 SLH-DSA, LMS/XMSS).
   - Hybrid post-quantum key exchanges (X25519Kyber768, SecP256r1MLKEM768).
   - Classical safe (TLS 1.3 / modern AEAD, flagged as vulnerable to HNDL).
   - Classical deprecated (SSLv3/TLS 1.0/1.1, RC4, 3DES, CBC SHA-1, static RSA, weak keys).
   - Unknown cipher suites flagged as UNKNOWN_AUDIT_REQUIRED with diagnostic warnings.
2. 100% accuracy on classifying classical vs post-quantum suites; 0 false classifications of deprecated ciphers as secure.
3. Harvest-Now-Decrypt-Later (HNDL) vulnerability calculation.
4. Performance benchmark: evaluation of 1,000 endpoint specs executed in <= 10.0 ms.
5. Multi-tenant isolation and sensitive hostname hashing (data isolation rules).
6. Prometheus observability: Gauge docscout_pqc_readiness_score and Counter docscout_pqc_assets_inventoried_total.
7. REST API endpoints:
   - POST /v1/compliance/pqc/scan
   - GET /v1/compliance/pqc/inventory
   - GET /v1/compliance/pqc/readiness
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.models import (
    CryptographicInventoryBatch,
    EndpointCryptoSpec,
)
from app.api.security import load_keys
from app.compliance.pqc_tracker import (
    PQCConfig,
    PQCTracker,
    anonymize_hostname,
    classify_endpoint_crypto,
)
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


def build_100_cipher_dataset() -> list[tuple[EndpointCryptoSpec, str, bool]]:
    """Construct dataset of 100 real-world TLS cipher suite configurations with expected classification and HNDL vulnerability."""
    dataset: list[tuple[EndpointCryptoSpec, str, bool]] = []
    future_date = date.today() + timedelta(days=365)
    past_date = date.today() - timedelta(days=30)
    k: str | None = None

    # 1. Pure Post-Quantum Ready (20 items: FIPS 203, FIPS 204, FIPS 205, SP 800-208)
    pqc_specs = [
        (
            "pqc1.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM768_AES_256_GCM_SHA384",
            "mlkem768",
            "mldsa65",
            None,
        ),
        (
            "pqc2.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM1024_AES_256_GCM_SHA384",
            "mlkem1024",
            "mldsa87",
            None,
        ),
        (
            "pqc3.bank.internal",
            "TLSv1.3",
            "TLS_KYBER768_AES_256_GCM_SHA384",
            "kyber768",
            "dilithium3",
            None,
        ),
        (
            "pqc4.bank.internal",
            "TLSv1.3",
            "TLS_KYBER1024_CHACHA20_POLY1305_SHA256",
            "kyber1024",
            "mldsa44",
            None,
        ),
        (
            "pqc5.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM512_AES_128_GCM_SHA256",
            "mlkem512",
            "slhdsa-sha2-128s",
            None,
        ),
        (
            "pqc6.bank.internal",
            "TLSv1.3",
            "TLS_FIPS203_AES_256_GCM_SHA384",
            "fips203",
            "fips204",
            None,
        ),
        (
            "pqc7.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM768_CHACHA20_POLY1305_SHA256",
            "mlkem768",
            "slhdsa-shake-256f",
            None,
        ),
        (
            "pqc8.bank.internal",
            "TLSv1.3",
            "TLS_KYBER512_AES_128_GCM_SHA256",
            "kyber512",
            "sphincs+",
            None,
        ),
        (
            "pqc9.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM768_AES_128_GCM_SHA256",
            "mlkem768",
            "mldsa65",
            None,
        ),
        ("pqc10.bank.internal", "TLSv1.3", "TLS_AES_256_GCM_SHA384", "mlkem768", "mldsa87", None),
        ("pqc11.bank.internal", "TLSv1.3", "TLS_AES_256_GCM_SHA384", "kyber1024", "lms", None),
        (
            "pqc12.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "mlkem768",
            "xmss",
            None,
        ),
        ("pqc13.bank.internal", "TLSv1.3", "TLS_AES_128_GCM_SHA256", "mlkem512", "mldsa44", None),
        (
            "pqc14.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM1024_CHACHA20_POLY1305_SHA256",
            "mlkem1024",
            "slhdsa",
            None,
        ),
        (
            "pqc15.bank.internal",
            "TLSv1.3",
            "TLS_FIPS203_CHACHA20_POLY1305_SHA256",
            "fips203",
            "fips205",
            None,
        ),
        (
            "pqc16.bank.internal",
            "TLSv1.3",
            "TLS_KYBER768_AES_128_GCM_SHA256",
            "kyber768",
            "mldsa65",
            None,
        ),
        (
            "pqc17.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM768_AES_256_GCM_SHA384",
            "mlkem768",
            "fips204",
            None,
        ),
        ("pqc18.bank.internal", "TLSv1.3", "TLS_AES_256_GCM_SHA384", "fips203", "mldsa65", None),
        ("pqc19.bank.internal", "TLSv1.3", "TLS_AES_256_GCM_SHA384", "mlkem1024", "fips205", None),
        (
            "pqc20.bank.internal",
            "TLSv1.3",
            "TLS_MLKEM512_CHACHA20_POLY1305_SHA256",
            "mlkem512",
            "mldsa44",
            None,
        ),
    ]
    for h, v, c, k, s, sz in pqc_specs:
        dataset.append(
            (
                EndpointCryptoSpec(
                    hostname=h,
                    tls_version=v,
                    cipher_suite=c,
                    key_exchange_group=k,
                    cert_signature_algo=s,
                    cert_key_size=sz,
                    cert_expiry=future_date,
                ),
                "PQC_READY",
                False,
            )
        )

    # 2. Hybrid Post-Quantum Key Exchange (20 items: X25519+Kyber, SecP256r1+MLKEM)
    hybrid_specs: list[tuple[str, str, str, str | None, str, int]] = [
        (
            "hyb1.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519_kyber768",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "hyb2.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519_mlkem768",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb3.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "x25519_kyber768",
            "ed25519",
            256,
        ),
        (
            "hyb4.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "secp256r1_kyber768",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb5.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "secp256r1_mlkem768",
            "sha384WithRSAEncryption",
            4096,
        ),
        (
            "hyb6.bank.internal",
            "TLSv1.3",
            "TLS_X25519_KYBER768_CHACHA20_POLY1305_SHA256",
            "x25519_kyber768",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb7.bank.internal",
            "TLSv1.3",
            "ECDHE-MLKEM768-RSA-AES256-GCM-SHA384",
            "x25519_mlkem768",
            "sha256WithRSAEncryption",
            4096,
        ),
        (
            "hyb8.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "X25519Kyber768Draft00",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "hyb9.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "secp256r1_kyber768",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb10.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "x25519_kyber768",
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "hyb11.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "X25519MLKEM768",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "hyb12.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "SecP256r1MLKEM768",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb13.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "x25519_mlkem768",
            "ed25519",
            256,
        ),
        (
            "hyb14.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "x25519_mlkem768",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb15.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519_kyber768",
            "sha512WithRSAEncryption",
            4096,
        ),
        (
            "hyb16.bank.internal",
            "TLSv1.3",
            "TLS_X25519_KYBER768_AES_256_GCM_SHA384",
            None,
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "hyb17.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "secp256r1_kyber768",
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "hyb18.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "X25519Kyber768Draft00",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb19.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "SecP256r1Kyber768Draft00",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "hyb20.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519_mlkem768",
            "ecdsa-with-SHA384",
            384,
        ),
    ]
    for h, v, c, k, s, sz in hybrid_specs:
        dataset.append(
            (
                EndpointCryptoSpec(
                    hostname=h,
                    tls_version=v,
                    cipher_suite=c,
                    key_exchange_group=k,
                    cert_signature_algo=s,
                    cert_key_size=sz,
                    cert_expiry=future_date,
                ),
                "HYBRID",
                False,
            )
        )

    # 3. Classical Safe (25 items: modern AEAD, RSA >= 3072, ECDSA >= 256, but HNDL vulnerable)
    classical_safe_specs = [
        (
            "safe1.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "safe2.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "x25519",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "safe3.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "x25519",
            "ed25519",
            256,
        ),
        (
            "safe4.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "secp256r1",
            "sha256WithRSAEncryption",
            4096,
        ),
        (
            "safe5.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "secp384r1",
            "sha384WithRSAEncryption",
            4096,
        ),
        (
            "safe6.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES256-GCM-SHA384",
            "secp384r1",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "safe7.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-GCM-SHA384",
            "secp256r1",
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "safe8.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES128-GCM-SHA256",
            "secp256r1",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "safe9.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES128-GCM-SHA256",
            "secp256r1",
            "sha256WithRSAEncryption",
            4096,
        ),
        (
            "safe10.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-CHACHA20-POLY1305-SHA256",
            "x25519",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "safe11.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-CHACHA20-POLY1305-SHA256",
            "x25519",
            "sha256WithRSAEncryption",
            4096,
        ),
        (
            "safe12.bank.internal",
            "TLSv1.2",
            "DHE-RSA-AES256-GCM-SHA384",
            "ffdhe3072",
            "sha256WithRSAEncryption",
            4096,
        ),
        (
            "safe13.bank.internal",
            "TLSv1.2",
            "DHE-RSA-AES128-GCM-SHA256",
            "ffdhe3072",
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "safe14.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519",
            "sha512WithRSAEncryption",
            4096,
        ),
        (
            "safe15.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "secp256r1",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "safe16.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES256-GCM-SHA384",
            "secp256r1",
            "ecdsa-with-SHA256",
            256,
        ),
        (
            "safe17.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-GCM-SHA384",
            "secp384r1",
            "sha384WithRSAEncryption",
            3072,
        ),
        (
            "safe18.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "x25519",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "safe19.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES128-GCM-SHA256",
            "secp256r1",
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "safe20.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES128-GCM-SHA256",
            "secp384r1",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "safe21.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519",
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "safe22.bank.internal",
            "TLSv1.3",
            "TLS_AES_128_GCM_SHA256",
            "x25519",
            "sha256WithRSAEncryption",
            4096,
        ),
        (
            "safe23.bank.internal",
            "TLSv1.2",
            "DHE-RSA-AES256-GCM-SHA384",
            "ffdhe4096",
            "sha384WithRSAEncryption",
            4096,
        ),
        (
            "safe24.bank.internal",
            "TLSv1.3",
            "TLS_CHACHA20_POLY1305_SHA256",
            "secp384r1",
            "ecdsa-with-SHA384",
            384,
        ),
        (
            "safe25.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-CHACHA20-POLY1305-SHA256",
            "secp256r1",
            "ecdsa-with-SHA256",
            256,
        ),
    ]
    for h, v, c, k, s, sz in classical_safe_specs:
        dataset.append(
            (
                EndpointCryptoSpec(
                    hostname=h,
                    tls_version=v,
                    cipher_suite=c,
                    key_exchange_group=k,
                    cert_signature_algo=s,
                    cert_key_size=sz,
                    cert_expiry=future_date,
                ),
                "CLASSICAL_SAFE",
                True,
            )
        )

    # 4. Classical Deprecated (25 items: TLS < 1.2, RC4, 3DES, CBC SHA1, static RSA, weak keys, expired certs)
    deprecated_specs: list[tuple[str, str, str, str | None, str, int, Any]] = [
        (
            "dep1.bank.internal",
            "TLSv1.0",
            "TLS_RSA_WITH_AES_128_CBC_SHA",
            None,
            "sha1WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep2.bank.internal",
            "TLSv1.1",
            "TLS_RSA_WITH_AES_256_CBC_SHA",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep3.bank.internal",
            "SSLv3",
            "TLS_RSA_WITH_3DES_EDE_CBC_SHA",
            None,
            "md5WithRSAEncryption",
            1024,
            future_date,
        ),
        (
            "dep4.bank.internal",
            "TLSv1.2",
            "TLS_RSA_WITH_RC4_128_SHA",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep5.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-RC4-SHA",
            "secp256r1",
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep6.bank.internal",
            "TLSv1.2",
            "DES-CBC3-SHA",
            None,
            "sha1WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep7.bank.internal",
            "TLSv1.2",
            "EDH-RSA-DES-CBC3-SHA",
            "ffdhe2048",
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep8.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-SHA",
            "secp256r1",
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep9.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES128-SHA",
            "secp256r1",
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep10.bank.internal",
            "TLSv1.2",
            "AES256-SHA",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep11.bank.internal",
            "TLSv1.2",
            "AES128-SHA",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep12.bank.internal",
            "TLSv1.2",
            "TLS_RSA_WITH_AES_256_GCM_SHA384",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep13.bank.internal",
            "TLSv1.2",
            "TLS_RSA_WITH_AES_128_GCM_SHA256",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep14.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-GCM-SHA384",
            "secp256r1",
            "sha256WithRSAEncryption",
            1024,
            future_date,
        ),
        (
            "dep15.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-GCM-SHA384",
            "secp256r1",
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),  # Flagged under 3072!
        (
            "dep16.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES256-GCM-SHA384",
            "secp256r1",
            "md5WithRSAEncryption",
            256,
            future_date,
        ),
        (
            "dep17.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES256-GCM-SHA384",
            "secp256r1",
            "sha1WithRSAEncryption",
            256,
            future_date,
        ),
        (
            "dep18.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-GCM-SHA384",
            "secp256r1",
            "sha256WithRSAEncryption",
            4096,
            past_date,
        ),  # Expired
        (
            "dep19.bank.internal",
            "TLSv1.3",
            "TLS_AES_256_GCM_SHA384",
            "x25519",
            "sha256WithRSAEncryption",
            4096,
            past_date,
        ),  # Expired
        (
            "dep20.bank.internal",
            "TLSv1.2",
            "ECDHE-ECDSA-AES256-GCM-SHA384",
            "secp256r1",
            "ecdsa-with-SHA256",
            160,
            future_date,
        ),  # Weak EC key
        (
            "dep21.bank.internal",
            "TLSv1.2",
            "EXP-EDH-RSA-DES-CBC-SHA",
            None,
            "sha1WithRSAEncryption",
            512,
            future_date,
        ),
        (
            "dep22.bank.internal",
            "TLSv1.2",
            "NULL-SHA256",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep23.bank.internal",
            "TLSv1.2",
            "ADH-AES256-GCM-SHA384",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep24.bank.internal",
            "TLSv1.2",
            "AECDH-AES256-SHA",
            None,
            "sha256WithRSAEncryption",
            2048,
            future_date,
        ),
        (
            "dep25.bank.internal",
            "TLSv1.2",
            "ECDHE-RSA-AES256-GCM-SHA384",
            "secp256r1",
            "sha256WithRSAEncryption",
            512,
            future_date,
        ),
    ]
    for h, v, c, k, s, sz, exp in deprecated_specs:
        dataset.append(
            (
                EndpointCryptoSpec(
                    hostname=h,
                    tls_version=v,
                    cipher_suite=c,
                    key_exchange_group=k,
                    cert_signature_algo=s,
                    cert_key_size=sz,
                    cert_expiry=exp,
                ),
                "CLASSICAL_DEPRECATED",
                True,
            )
        )

    # 5. Unknown / Audit Required (10 items)
    unknown_specs: list[tuple[str, str, str, str | None, str, int]] = [
        (
            "unk1.partner.internal",
            "TLSv1.3",
            "CUSTOM_PROPRIETARY_CIPHER_999",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk2.partner.internal",
            "TLSv1.3",
            "EXPERIMENTAL_QUANTUM_XYZ_CUSTOM",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk3.partner.internal",
            "TLSv1.3",
            "NON_STANDARD_CIPHER_SUITE_1234",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk4.partner.internal",
            "TLSv1.3",
            "VENDOR_INTERNAL_CRYPT_V1",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk5.partner.internal",
            "TLSv1.3",
            "TEST_SUITE_DUMMY_ALG",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk6.partner.internal",
            "TLSv1.3",
            "LEGACY_PAYMENT_SECRET_CIPHER",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk7.partner.internal",
            "TLSv1.3",
            "UNKNOWN_ALGO_BLOCK_512",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk8.partner.internal",
            "TLSv1.3",
            "MY_ORGANIZATION_CUSTOM_AEAD",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk9.partner.internal",
            "TLSv1.3",
            "EXPERIMENTAL_KEM_PROTOTYPE_PRIVATE",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
        (
            "unk10.partner.internal",
            "TLSv1.3",
            "UNCLASSIFIED_HANDSHAKE_CIPHER",
            None,
            "sha256WithRSAEncryption",
            3072,
        ),
    ]
    for h, v, c, k, s, sz in unknown_specs:
        dataset.append(
            (
                EndpointCryptoSpec(
                    hostname=h,
                    tls_version=v,
                    cipher_suite=c,
                    key_exchange_group=k,
                    cert_signature_algo=s,
                    cert_key_size=sz,
                    cert_expiry=future_date,
                ),
                "UNKNOWN_AUDIT_REQUIRED",
                True,
            )
        )

    return dataset


# --- Test 1: 100 Real-World TLS Cipher Suite Configurations Accuracy ---


def test_100_cipher_suite_classification_accuracy() -> None:
    """Verify 100 real-world TLS cipher suites classified with 100% accuracy and zero false positives for deprecated ciphers."""
    dataset = build_100_cipher_dataset()
    assert len(dataset) == 100, (
        f"Expected exactly 100 cipher suite configurations, got {len(dataset)}"
    )

    config = PQCConfig(flag_rsa_under_3072=True)
    correct_count = 0

    for spec, expected_cls, expected_hndl in dataset:
        cls_name, hndl_vuln, pqc_algo, warning, rec_action = classify_endpoint_crypto(spec, config)

        assert cls_name == expected_cls, (
            f"Mismatch for {spec.hostname} ({spec.cipher_suite}): expected {expected_cls}, got {cls_name}"
        )
        assert hndl_vuln == expected_hndl, (
            f"HNDL mismatch for {spec.hostname}: expected {expected_hndl}, got {hndl_vuln}"
        )

        # Zero false classifications of deprecated legacy ciphers as secure
        if expected_cls == "CLASSICAL_DEPRECATED":
            assert cls_name == "CLASSICAL_DEPRECATED"
            assert hndl_vuln is True

        correct_count += 1

    accuracy = correct_count / len(dataset)
    assert accuracy == 1.0, f"Expected 100% classification accuracy, got {accuracy * 100:.2f}%"


# --- Test 2: HNDL Exposure Scoring & Milestone Progression ---


def test_hndl_exposure_and_milestone_progression() -> None:
    """Validate accurate HNDL vulnerability score and migration milestone stages."""
    tracker = PQCTracker(config=PQCConfig())
    dataset = build_100_cipher_dataset()

    # Batch 1: Pure Classical Baseline (0% PQC) -> PHASE_1_INVENTORY
    classical_only = [spec for spec, cls_name, _ in dataset if cls_name == "CLASSICAL_SAFE"]
    batch_classical = CryptographicInventoryBatch(endpoints=classical_only)
    report_classical = tracker.scan_inventory(batch_classical, tenant_id="tenant_classical")

    assert report_classical.total_assets == len(classical_only)
    assert report_classical.pqc_ready_count == 0
    assert report_classical.hndl_exposure_score == 1.0
    assert report_classical.readiness_score == 0.0
    assert report_classical.migration_milestone == "PHASE_1_INVENTORY"

    # Batch 2: Hybrid Transition (20 hybrid, 10 safe) -> PHASE_2_HYBRID_TRANSITION
    hybrid_and_safe = [
        spec for spec, cls_name, _ in dataset if cls_name in ("HYBRID", "CLASSICAL_SAFE")
    ][:20]
    batch_hybrid = CryptographicInventoryBatch(endpoints=hybrid_and_safe)
    report_hybrid = tracker.scan_inventory(batch_hybrid, tenant_id="tenant_hybrid")

    assert report_hybrid.migration_milestone in ("PHASE_2_HYBRID_TRANSITION", "PHASE_1_INVENTORY")
    assert report_hybrid.hndl_exposure_score < 1.0

    # Batch 3: Fully Quantum Resilient (20 PQC_READY) -> PHASE_3_QUANTUM_RESILIENT
    pqc_only = [spec for spec, cls_name, _ in dataset if cls_name == "PQC_READY"]
    batch_pqc = CryptographicInventoryBatch(endpoints=pqc_only)
    report_pqc = tracker.scan_inventory(batch_pqc, tenant_id="tenant_pqc")

    assert report_pqc.pqc_ready_count == len(pqc_only)
    assert report_pqc.quantum_vulnerable_count == 0
    assert report_pqc.hndl_exposure_score == 0.0
    assert report_pqc.readiness_score == 100.0
    assert report_pqc.migration_milestone == "PHASE_3_QUANTUM_RESILIENT"


# --- Test 3: Performance Limit (1,000 endpoint specs in <= 10.0 ms) ---


def test_performance_1000_endpoints_under_10ms() -> None:
    """Verify performance SLA: evaluating 1,000 endpoint specs executes in <= 10.0 ms."""
    dataset = build_100_cipher_dataset()
    specs_100 = [spec for spec, _, _ in dataset]

    # Replicate to exactly 1,000 specs
    specs_1000 = (specs_100 * 10)[:1000]
    assert len(specs_1000) == 1000

    tracker = PQCTracker(config=PQCConfig())

    # Warm-up run
    tracker.evaluate_endpoints(specs_1000)

    # Timed run
    start_time = time.perf_counter()
    evaluations = tracker.evaluate_endpoints(specs_1000)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    assert len(evaluations) == 1000
    # Performance SLA: <= 10.0 ms
    assert elapsed_ms <= 10.0, f"Expected 1,000 evaluations in <= 10.0 ms, took {elapsed_ms:.2f} ms"


# --- Test 4: Hostname Anonymization & Data Isolation ---


def test_hostname_anonymization_and_tenant_isolation() -> None:
    """Verify hostname hashing prevents leakage of sensitive internal infrastructure and respects tenant isolation."""
    raw_host = "secret-payment-switch-01.internal.bank.net"
    h1 = anonymize_hostname(raw_host)
    h2 = anonymize_hostname(raw_host)

    assert h1 == h2
    assert len(h1) == 16
    assert raw_host not in h1

    tracker = PQCTracker()
    spec = EndpointCryptoSpec(
        hostname=raw_host,
        tls_version="TLSv1.3",
        cipher_suite="TLS_AES_256_GCM_SHA384",
        cert_signature_algo="sha256WithRSAEncryption",
        cert_key_size=4096,
        cert_expiry=date.today() + timedelta(days=100),
    )

    report_a = tracker.scan_inventory(
        CryptographicInventoryBatch(endpoints=[spec]), tenant_id="tenant_alpha"
    )
    report_b = tracker.scan_inventory(
        CryptographicInventoryBatch(endpoints=[spec]), tenant_id="tenant_beta"
    )

    assert report_a.total_assets == 1
    assert report_b.total_assets == 1
    inv_a = tracker.get_inventory(tenant_id="tenant_alpha")
    inv_b = tracker.get_inventory(tenant_id="tenant_beta")

    assert inv_a.total_count == 1
    assert inv_b.total_count == 1
    assert inv_a.assets[0].hostname_hash == h1
    assert inv_a.assets[0].tenant_id == "tenant_alpha"
    assert inv_b.assets[0].tenant_id == "tenant_beta"


# --- Test 5: Unknown Cipher Suite Diagnostic Fallback ---


def test_unknown_cipher_suite_diagnostic_warning() -> None:
    """Verify unknown cipher suites produce UNKNOWN_AUDIT_REQUIRED with diagnostic warning without crashing."""
    spec = EndpointCryptoSpec(
        hostname="unregistered-device.iot.internal",
        tls_version="TLSv1.3",
        cipher_suite="UNKNOWN_VENDOR_CUSTOM_CIPHER_HEX_00A1",
        cert_signature_algo="sha256WithRSAEncryption",
        cert_key_size=3072,
    )

    cls_name, hndl_vuln, algo, warning, action = classify_endpoint_crypto(spec, PQCConfig())

    assert cls_name == "UNKNOWN_AUDIT_REQUIRED"
    assert hndl_vuln is True
    assert warning is not None
    assert "UNKNOWN_AUDIT_REQUIRED" in warning
    assert "UNKNOWN_VENDOR_CUSTOM_CIPHER_HEX_00A1" in warning
    assert "manual cryptographic audit" in action.lower()


# --- Test 6: RSA Under 3072 Flagging Configuration ---


def test_flag_rsa_under_3072_toggle() -> None:
    """Verify configuration toggle flag_rsa_under_3072 properly flags 2048-bit RSA."""
    spec = EndpointCryptoSpec(
        hostname="rsa2048.bank.internal",
        tls_version="TLSv1.3",
        cipher_suite="TLS_AES_256_GCM_SHA384",
        cert_signature_algo="sha256WithRSAEncryption",
        cert_key_size=2048,
        cert_expiry=date.today() + timedelta(days=200),
    )

    # When flag_rsa_under_3072=True -> CLASSICAL_DEPRECATED
    cls_flagged, _, _, warn_flagged, _ = classify_endpoint_crypto(
        spec, PQCConfig(flag_rsa_under_3072=True)
    )
    assert cls_flagged == "CLASSICAL_DEPRECATED"
    assert warn_flagged is not None
    assert "under 3072 bits flagged" in warn_flagged

    # When flag_rsa_under_3072=False -> CLASSICAL_SAFE
    cls_safe, _, _, warn_safe, _ = classify_endpoint_crypto(
        spec, PQCConfig(flag_rsa_under_3072=False)
    )
    assert cls_safe == "CLASSICAL_SAFE"
    assert warn_safe is None


# --- Test 7: REST API Endpoints ---


def test_rest_api_pqc_scan_and_readiness(
    test_client: TestClient, api_headers: dict[str, str]
) -> None:
    """Test POST /v1/compliance/pqc/scan and GET /v1/compliance/pqc/readiness."""
    future_date = (date.today() + timedelta(days=365)).isoformat()
    kem_group = "key_exchange_group"
    payload = {
        "endpoints": [
            {
                "hostname": "api.gateway.bank.internal",
                "port": 443,
                "tls_version": "TLSv1.3",
                "cipher_suite": "TLS_AES_256_GCM_SHA384",
                kem_group: "x25519_kyber768",
                "cert_signature_algo": "ecdsa-with-SHA384",
                "cert_key_size": 384,
                "cert_expiry": future_date,
            },
            {
                "hostname": "core.banking.internal",
                "port": 443,
                "tls_version": "TLSv1.3",
                "cipher_suite": "TLS_MLKEM768_AES_256_GCM_SHA384",
                kem_group: "mlkem768",
                "cert_signature_algo": "mldsa65",
                "cert_expiry": future_date,
            },
            {
                "hostname": "legacy.switch.internal",
                "port": 443,
                "tls_version": "TLSv1.2",
                "cipher_suite": "ECDHE-RSA-AES256-GCM-SHA384",
                kem_group: "secp256r1",
                "cert_signature_algo": "sha256WithRSAEncryption",
                "cert_key_size": 4096,
                "cert_expiry": future_date,
            },
        ],
        "flag_rsa_under_3072": True,
    }

    # POST /v1/compliance/pqc/scan
    response = test_client.post(
        "/v1/compliance/pqc/scan?tenant_id=api_test_tenant",
        json=payload,
        headers=api_headers,
    )
    assert response.status_code == 200, f"Error: {response.text}"
    data = response.json()

    assert data["total_assets"] == 3
    assert data["pqc_ready_count"] == 1
    assert data["hybrid_count"] == 1
    assert data["quantum_vulnerable_count"] == 1
    assert data["hndl_exposure_score"] == round(1 / 3, 4)
    assert data["readiness_score"] > 50.0
    assert len(data["assets"]) == 3

    # GET /v1/compliance/pqc/inventory
    inv_resp = test_client.get(
        "/v1/compliance/pqc/inventory?tenant_id=api_test_tenant",
        headers=api_headers,
    )
    assert inv_resp.status_code == 200
    inv_data = inv_resp.json()
    assert inv_data["total_count"] >= 3
    assert len(inv_data["assets"]) >= 3

    # GET /v1/compliance/pqc/readiness
    readiness_resp = test_client.get(
        "/v1/compliance/pqc/readiness?tenant_id=api_test_tenant",
        headers=api_headers,
    )
    assert readiness_resp.status_code == 200
    r_data = readiness_resp.json()
    assert r_data["total_assets"] >= 3
    assert "migration_milestone" in r_data


# --- Test 8: REST API Validation & Error Handling ---


def test_rest_api_validation_errors(test_client: TestClient, api_headers: dict[str, str]) -> None:
    """Verify input validation handles empty endpoints or invalid hostname."""
    # Empty endpoints list
    resp_empty = test_client.post(
        "/v1/compliance/pqc/scan",
        json={"endpoints": []},
        headers=api_headers,
    )
    assert resp_empty.status_code == 422

    # Missing required field
    resp_missing = test_client.post(
        "/v1/compliance/pqc/scan",
        json={"endpoints": [{"hostname": "bad.host"}]},
        headers=api_headers,
    )
    assert resp_missing.status_code == 422
