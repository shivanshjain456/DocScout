"""Post-Quantum Cryptographic Migration Tracker (FEAT-057).

Operationalizes playbook.crypto-migration by scanning and inventorying enterprise endpoint
cryptographic parameters, distinguishing between classical, hybrid, and FIPS-standardized
post-quantum algorithms, and measuring Harvest-Now-Decrypt-Later (HNDL) vulnerability exposure.

Standards referenced:
- NIST FIPS 203: ML-KEM (Module-Lattice-Based Key-Encapsulation Mechanism)
- NIST FIPS 204: ML-DSA (Module-Lattice-Based Digital Signature Algorithm)
- NIST FIPS 205: SLH-DSA (Stateless Hash-Based Digital Signature Algorithm)
- NIST SP 800-208: Stateful Hash-Based Signature Schemes (LMS/XMSS)
- NIST SP 800-57: Cryptographic Key Management Recommendations
- RBI Cyber Security Framework: Annexure on Cryptographic Controls
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog

from app.api.metrics import PQC_ASSETS_INVENTORIED_TOTAL, PQC_READINESS_SCORE
from app.api.models import (
    CryptoAssetItem,
    CryptographicInventoryBatch,
    EndpointCryptoSpec,
    PQCInventoryResponse,
    PQCReadinessReport,
)

logger = structlog.get_logger(__name__)

DEPRECATED_PROTOCOLS: frozenset[str] = frozenset(
    {"SSLV2", "SSLV3", "TLSV1.0", "TLSV1", "TLSV1.1", "TLS 1.0", "TLS 1.1"}
)

DEPRECATED_CIPHER_KEYWORDS: tuple[str, ...] = (
    "RC4",
    "3DES",
    "DES",
    "MD5",
    "EXPORT",
    "EXP_",
    "_EXP",
    "NULL",
    "ANON",
    "ADH",
    "AECDH",
)

CBC_CIPHER_SUBSTRINGS: tuple[str, ...] = (
    "CBC",
    "AES128_SHA",
    "AES256_SHA",
)

HYBRID_PATTERNS: tuple[str, ...] = (
    "X25519KYBER",
    "X25519_KYBER",
    "X25519MLKEM",
    "X25519_MLKEM",
    "SECP256R1KYBER",
    "SECP256R1_KYBER",
    "SECP256R1MLKEM",
    "SECP256R1_MLKEM",
    "KYBER768DRAFT00",
    "ECDHE_MLKEM",
    "KYBER768_RSA",
    "MLKEM768_RSA",
)

PQC_PRIMITIVES: tuple[str, ...] = (
    "ML-KEM",
    "MLKEM",
    "KYBER",
    "ML-DSA",
    "MLDSA",
    "DILITHIUM",
    "SLH-DSA",
    "SLHDSA",
    "SPHINCS",
    "FIPS203",
    "FIPS204",
    "FIPS205",
    "LMS",
    "XMSS",
)

CLASSICAL_SAFE_SUITES: frozenset[str] = frozenset(
    {
        "TLS_AES_256_GCM_SHA384",
        "TLS_AES_128_GCM_SHA256",
        "TLS_CHACHA20_POLY1305_SHA256",
        "ECDHE_ECDSA_AES256_GCM_SHA384",
        "ECDHE_RSA_AES256_GCM_SHA384",
        "ECDHE_ECDSA_AES128_GCM_SHA256",
        "ECDHE_RSA_AES128_GCM_SHA256",
        "ECDHE_ECDSA_CHACHA20_POLY1305_SHA256",
        "ECDHE_RSA_CHACHA20_POLY1305_SHA256",
        "DHE_RSA_AES256_GCM_SHA384",
        "DHE_RSA_AES128_GCM_SHA256",
        "ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
        "ECDHE_RSA_WITH_AES_256_GCM_SHA384",
        "ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
        "ECDHE_RSA_WITH_AES_128_GCM_SHA256",
        "ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
        "ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
    }
)


@dataclass(frozen=True)
class PQCConfig:
    """Configuration for Post-Quantum Cryptographic Migration Tracker."""

    flag_rsa_under_3072: bool = True
    fallback_dir: str = ".docscout_pqc_cache"
    persist_fallback: bool = False


def anonymize_hostname(hostname: str) -> str:
    """Compute deterministic SHA-256 privacy digest for sensitive server names."""
    return hashlib.sha256(hostname.strip().lower().encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=8192)
def _classify_cached(
    tls_norm: str,
    cipher_norm: str,
    group_norm: str,
    sig_norm: str,
    cert_key_size: int | None,
    is_expired: bool,
    expiry_iso: str | None,
    raw_tls: str,
    raw_cipher: str,
    raw_sig: str,
    flag_rsa_under_3072: bool,
) -> tuple[str, bool, str | None, str | None, str]:

    # 1. Check deprecated protocol versions (SSLv2/SSLv3/TLS 1.0/TLS 1.1)
    if tls_norm in DEPRECATED_PROTOCOLS:
        return (
            "CLASSICAL_DEPRECATED",
            True,
            None,
            f"Deprecated protocol version {raw_tls}",
            "Upgrade immediately to TLS 1.3 or modern TLS 1.2 with AEAD ciphers",
        )

    # 2. Check expired certificates
    if is_expired:
        return (
            "CLASSICAL_DEPRECATED",
            True,
            None,
            f"Certificate expired on {expiry_iso}",
            "Renew certificate immediately with quantum-safe or strong hybrid algorithm",
        )

    # 3. Check deprecated certificate signature digests (MD5 / SHA1)
    if "MD5" in sig_norm or "SHA1" in sig_norm:
        return (
            "CLASSICAL_DEPRECATED",
            True,
            None,
            f"Cryptographically broken signature digest {raw_sig}",
            "Replace certificate with ML-DSA (FIPS 204) or SHA-256+ signature",
        )

    # 4. Check weak key sizes
    if cert_key_size is not None:
        if "RSA" in sig_norm:
            if cert_key_size < 2048:
                return (
                    "CLASSICAL_DEPRECATED",
                    True,
                    None,
                    f"Insecure RSA key size {cert_key_size} < 2048 bits",
                    "Upgrade RSA key to >= 3072 bits or migrate to ML-DSA (FIPS 204)",
                )
            if flag_rsa_under_3072 and cert_key_size < 3072:
                return (
                    "CLASSICAL_DEPRECATED",
                    True,
                    None,
                    f"RSA key size {cert_key_size} under 3072 bits flagged per NIST SP 800-57 guidelines",
                    "Migrate to ML-DSA (FIPS 204) or upgrade RSA key length to >= 3072 bits",
                )
        elif ("ECDSA" in sig_norm or "EC" in sig_norm) and cert_key_size < 256:
            return (
                "CLASSICAL_DEPRECATED",
                True,
                None,
                f"Insecure EC key size {cert_key_size} < 256 bits",
                "Upgrade to P-256 / P-384 or migrate to ML-DSA (FIPS 204)",
            )

    # 5. Check deprecated cipher suites (RC4, 3DES, DES, EXPORT, NULL, ANON)
    for kw in DEPRECATED_CIPHER_KEYWORDS:
        if kw in cipher_norm:
            return (
                "CLASSICAL_DEPRECATED",
                True,
                None,
                f"Insecure cipher component '{kw}' in {raw_cipher}",
                "Deprecate legacy cipher suite immediately and deploy TLS 1.3",
            )

    # 6. Check vulnerable CBC mode ciphers in TLS 1.2
    for cbc_sub in CBC_CIPHER_SUBSTRINGS:
        if (
            cbc_sub in cipher_norm
            and not cipher_norm.endswith("GCM_SHA384")
            and not cipher_norm.endswith("GCM_SHA256")
        ):
            return (
                "CLASSICAL_DEPRECATED",
                True,
                None,
                f"Vulnerable CBC mode or legacy SHA-1 cipher {raw_cipher}",
                "Migrate to AES-GCM or ChaCha20-Poly1305 AEAD ciphers",
            )

    # 7. Check static RSA key exchange (lack of forward secrecy)
    if cipher_norm.startswith("TLS_RSA_WITH_") or cipher_norm.startswith("RSA_WITH_"):
        return (
            "CLASSICAL_DEPRECATED",
            True,
            None,
            f"Static RSA key exchange lacking forward secrecy in {raw_cipher}",
            "Deploy Ephemeral Diffie-Hellman (ECDHE) or Hybrid Post-Quantum Key Encapsulation",
        )

    # 8. Check Hybrid Post-Quantum Key Exchange
    is_hybrid = False
    for pat in HYBRID_PATTERNS:
        if pat in cipher_norm or pat in group_norm:
            is_hybrid = True
            break

    # Also check combined indicators (e.g. key_exchange_group combining x25519/p256 and kyber/mlkem)
    if not is_hybrid and group_norm:
        has_classical_kem = any(c in group_norm for c in ("X25519", "P256", "SECP256R1", "ECDHE"))
        has_pqc_kem = any(p in group_norm for p in ("KYBER", "MLKEM", "ML_KEM"))
        if has_classical_kem and has_pqc_kem:
            is_hybrid = True

    if is_hybrid:
        algo_name = (
            "Hybrid X25519 + FIPS 203 (ML-KEM-768)"
            if "768" in (cipher_norm + group_norm)
            else "Hybrid Classical + NIST PQC"
        )
        return (
            "HYBRID",
            False,
            algo_name,
            None,
            "Hybrid post-quantum key encapsulation protects against Harvest-Now-Decrypt-Later attacks",
        )

    # 9. Check Pure Post-Quantum Ready (FIPS 203 / FIPS 204 / FIPS 205 / SP 800-208)
    has_pqc_cipher = any(p in cipher_norm for p in PQC_PRIMITIVES)
    has_pqc_group = any(p in group_norm for p in PQC_PRIMITIVES)
    has_pqc_sig = any(p in sig_norm for p in PQC_PRIMITIVES)

    if (has_pqc_cipher or has_pqc_group or has_pqc_sig) and not is_hybrid:
        # Verify it does not rely on classical unencapsulated key exchanges
        has_classical_part = any(
            c in group_norm for c in ("X25519", "P256", "SECP", "ECDHE", "DHE", "RSA")
        )
        if not has_classical_part:
            if "MLKEM" in (cipher_norm + group_norm) or "KYBER" in (cipher_norm + group_norm):
                pqc_name = "FIPS 203 (ML-KEM)"
            elif "MLDSA" in sig_norm or "DILITHIUM" in sig_norm:
                pqc_name = "FIPS 204 (ML-DSA)"
            elif "SLHDSA" in sig_norm or "SPHINCS" in sig_norm:
                pqc_name = "FIPS 205 (SLH-DSA)"
            elif "LMS" in sig_norm or "XMSS" in sig_norm:
                pqc_name = "NIST SP 800-208 (LMS/XMSS)"
            else:
                pqc_name = "NIST Post-Quantum Cryptography Standard"

            return (
                "PQC_READY",
                False,
                pqc_name,
                None,
                "Endpoint fully quantum-resilient under standardized NIST PQC specifications",
            )

    # 10. Check Classical Safe (Strong modern AEAD suites, ECDHE/DHE, RSA >= 3072 / ECDSA >= 256)
    if cipher_norm in CLASSICAL_SAFE_SUITES or (
        any(prefix in cipher_norm for prefix in ("ECDHE_", "DHE_", "TLS_"))
        and any(aead in cipher_norm for aead in ("GCM", "POLY1305", "CCM"))
    ):
        return (
            "CLASSICAL_SAFE",
            True,
            None,
            None,
            "Upgrade key exchange to Hybrid ML-KEM (FIPS 203) to mitigate Harvest-Now-Decrypt-Later vulnerability",
        )

    # 11. Unknown / Non-standard cipher suite
    return (
        "UNKNOWN_AUDIT_REQUIRED",
        True,
        None,
        f"UNKNOWN_AUDIT_REQUIRED: Cipher suite '{raw_cipher}' not recognized in standard IANA registry",
        "Conduct manual cryptographic audit for non-standard or proprietary cipher suite",
    )


def classify_endpoint_crypto(
    spec: EndpointCryptoSpec,
    config: PQCConfig,
) -> tuple[str, bool, str | None, str | None, str]:
    """Classify endpoint cryptographic profile into regulatory PQC taxonomy."""
    today = date.today()
    is_expired = spec.cert_expiry is not None and spec.cert_expiry < today
    expiry_iso = spec.cert_expiry.isoformat() if spec.cert_expiry else None
    return _classify_cached(
        spec.tls_version.strip().upper(),
        spec.cipher_suite.strip().upper().replace("-", "_"),
        spec.key_exchange_group.strip().upper().replace("-", "_")
        if spec.key_exchange_group
        else "",
        spec.cert_signature_algo.strip().upper().replace("-", "_"),
        spec.cert_key_size,
        is_expired,
        expiry_iso,
        spec.tls_version,
        spec.cipher_suite,
        spec.cert_signature_algo,
        config.flag_rsa_under_3072,
    )


class PQCTracker:
    """Post-Quantum Cryptographic Migration Tracker."""

    def __init__(self, config: PQCConfig | None = None) -> None:
        self.config = config or PQCConfig()
        self._inventory: dict[str, dict[UUID, CryptoAssetItem]] = {}

    def evaluate_endpoints(
        self, endpoints: list[EndpointCryptoSpec]
    ) -> list[tuple[str, bool, str | None, str | None, str]]:
        """High-speed pure evaluation of endpoint cryptographic configurations."""
        return [classify_endpoint_crypto(spec, self.config) for spec in endpoints]

    def scan_inventory(
        self,
        batch: CryptographicInventoryBatch,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> PQCReadinessReport:
        """Scan a batch of endpoint cryptographic configurations and generate a readiness report."""
        assets: list[CryptoAssetItem] = []
        now = datetime.now(UTC)
        class_counts: dict[str, int] = {}

        for spec in batch.endpoints:
            cls_name, hndl_vuln, pqc_algo, warning, rec_action = classify_endpoint_crypto(
                spec, self.config
            )

            asset = CryptoAssetItem(
                asset_id=uuid4(),
                tenant_id=tenant_id,
                hostname=spec.hostname,
                hostname_hash=anonymize_hostname(spec.hostname),
                tls_version=spec.tls_version,
                cipher_suite=spec.cipher_suite,
                cert_signature_algo=spec.cert_signature_algo,
                cert_key_size=spec.cert_key_size,
                cert_expiry=spec.cert_expiry,
                classification=cls_name,  # type: ignore[arg-type]
                hndl_vulnerable=hndl_vuln,
                quantum_safe_algo=pqc_algo,
                warning=warning,
                recommended_action=rec_action,
                scanned_at=now,
            )
            assets.append(asset)
            class_key = cls_name.lower()
            class_counts[class_key] = class_counts.get(class_key, 0) + 1

        # Record batched Prometheus metrics
        for cls_key, count in class_counts.items():
            try:
                PQC_ASSETS_INVENTORIED_TOTAL.labels(classification=cls_key).inc(count)
            except Exception as err:
                logger.debug("pqc.metric_counter_error", error=str(err))

        total_assets = len(assets)
        quantum_vulnerable_count = sum(1 for a in assets if a.hndl_vulnerable)
        pqc_ready_count = sum(1 for a in assets if a.classification == "PQC_READY")
        hybrid_count = sum(1 for a in assets if a.classification == "HYBRID")
        deprecated_count = sum(1 for a in assets if a.classification == "CLASSICAL_DEPRECATED")
        unknown_count = sum(1 for a in assets if a.classification == "UNKNOWN_AUDIT_REQUIRED")

        hndl_exposure_score = (
            round(quantum_vulnerable_count / total_assets, 4) if total_assets > 0 else 0.0
        )
        readiness_score = (
            round(((pqc_ready_count + hybrid_count * 0.75) / total_assets) * 100.0, 2)
            if total_assets > 0
            else 0.0
        )

        milestone: Literal[
            "PHASE_1_INVENTORY", "PHASE_2_HYBRID_TRANSITION", "PHASE_3_QUANTUM_RESILIENT"
        ]
        if readiness_score >= 80.0 and deprecated_count == 0:
            milestone = "PHASE_3_QUANTUM_RESILIENT"
        elif readiness_score >= 30.0:
            milestone = "PHASE_2_HYBRID_TRANSITION"
        else:
            milestone = "PHASE_1_INVENTORY"

        # Record readiness score metric
        try:
            PQC_READINESS_SCORE.labels(tenant_id=tenant_id).set(readiness_score)
        except Exception as err:
            logger.debug("pqc.metric_gauge_error", error=str(err))

        # Store in-memory
        if tenant_id not in self._inventory:
            self._inventory[tenant_id] = {}
        for a in assets:
            self._inventory[tenant_id][a.asset_id] = a

        # Persist to database if connection available, or fallback if configured
        if conn is not None:
            self._persist_to_db(assets, tenant_id=tenant_id, conn=conn)
        elif self.config.persist_fallback:
            self._write_fallback(assets, tenant_id=tenant_id)

        report = PQCReadinessReport(
            total_assets=total_assets,
            quantum_vulnerable_count=quantum_vulnerable_count,
            pqc_ready_count=pqc_ready_count,
            hybrid_count=hybrid_count,
            deprecated_count=deprecated_count,
            unknown_count=unknown_count,
            hndl_exposure_score=hndl_exposure_score,
            readiness_score=readiness_score,
            migration_milestone=milestone,
            assets=assets,
            evaluated_at=now,
        )

        logger.info(
            "pqc.scan_completed",
            tenant_id=tenant_id,
            total_assets=total_assets,
            hndl_exposure_score=hndl_exposure_score,
            readiness_score=readiness_score,
            milestone=milestone,
        )

        return report

    def get_inventory(
        self,
        tenant_id: str = "default",
        limit: int = 100,
        offset: int = 0,
        conn: Any = None,
    ) -> PQCInventoryResponse:
        """Retrieve paginated cryptographic assets for a given tenant."""
        if conn is not None:
            db_assets = self._load_from_db(tenant_id, limit=limit, offset=offset, conn=conn)
            if db_assets is not None:
                return PQCInventoryResponse(
                    tenant_id=tenant_id,
                    total_count=len(db_assets),
                    assets=db_assets,
                )

        tenant_map = self._inventory.get(tenant_id, {})
        all_assets = list(tenant_map.values())
        paginated = all_assets[offset : offset + limit]

        return PQCInventoryResponse(
            tenant_id=tenant_id,
            total_count=len(all_assets),
            assets=paginated,
        )

    def get_readiness_report(
        self,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> PQCReadinessReport:
        """Calculate and return the current institutional readiness report."""
        tenant_map = self._inventory.get(tenant_id, {})
        assets = list(tenant_map.values())

        if not assets and conn is not None:
            db_assets = self._load_from_db(tenant_id, limit=1000, offset=0, conn=conn)
            if db_assets:
                assets = db_assets

        total_assets = len(assets)
        quantum_vulnerable_count = sum(1 for a in assets if a.hndl_vulnerable)
        pqc_ready_count = sum(1 for a in assets if a.classification == "PQC_READY")
        hybrid_count = sum(1 for a in assets if a.classification == "HYBRID")
        deprecated_count = sum(1 for a in assets if a.classification == "CLASSICAL_DEPRECATED")
        unknown_count = sum(1 for a in assets if a.classification == "UNKNOWN_AUDIT_REQUIRED")

        hndl_exposure_score = (
            round(quantum_vulnerable_count / total_assets, 4) if total_assets > 0 else 0.0
        )
        readiness_score = (
            round(((pqc_ready_count + hybrid_count * 0.75) / total_assets) * 100.0, 2)
            if total_assets > 0
            else 0.0
        )

        milestone: Literal[
            "PHASE_1_INVENTORY", "PHASE_2_HYBRID_TRANSITION", "PHASE_3_QUANTUM_RESILIENT"
        ]
        if readiness_score >= 80.0 and deprecated_count == 0:
            milestone = "PHASE_3_QUANTUM_RESILIENT"
        elif readiness_score >= 30.0:
            milestone = "PHASE_2_HYBRID_TRANSITION"
        else:
            milestone = "PHASE_1_INVENTORY"

        return PQCReadinessReport(
            total_assets=total_assets,
            quantum_vulnerable_count=quantum_vulnerable_count,
            pqc_ready_count=pqc_ready_count,
            hybrid_count=hybrid_count,
            deprecated_count=deprecated_count,
            unknown_count=unknown_count,
            hndl_exposure_score=hndl_exposure_score,
            readiness_score=readiness_score,
            migration_milestone=milestone,
            assets=assets,
            evaluated_at=datetime.now(UTC),
        )

    def _persist_to_db(self, assets: list[CryptoAssetItem], tenant_id: str, conn: Any) -> None:
        """Persist crypto assets to PostgreSQL table pqc_crypto_assets."""
        try:
            for a in assets:
                meta = {
                    "warning": a.warning,
                    "recommended_action": a.recommended_action,
                }
                conn.execute(
                    """
                    INSERT INTO pqc_crypto_assets (
                        asset_id, tenant_id, hostname, hostname_hash, tls_version,
                        cipher_suite, cert_signature_algo, cert_key_size, cert_expiry,
                        classification, hndl_vulnerable, quantum_safe_algo, scanned_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (asset_id) DO NOTHING
                    """,
                    (
                        a.asset_id,
                        tenant_id,
                        a.hostname,
                        a.hostname_hash,
                        a.tls_version,
                        a.cipher_suite,
                        a.cert_signature_algo,
                        a.cert_key_size,
                        a.cert_expiry,
                        a.classification,
                        a.hndl_vulnerable,
                        a.quantum_safe_algo,
                        a.scanned_at,
                        json.dumps(meta),
                    ),
                )
        except Exception as err:
            logger.warning("pqc.db_persist_failed", error=str(err))

    def _load_from_db(
        self, tenant_id: str, limit: int, offset: int, conn: Any
    ) -> list[CryptoAssetItem] | None:
        """Load cryptographic assets from PostgreSQL."""
        try:
            rows = conn.execute(
                """
                SELECT asset_id, tenant_id, hostname, hostname_hash, tls_version,
                       cipher_suite, cert_signature_algo, cert_key_size, cert_expiry,
                       classification, hndl_vulnerable, quantum_safe_algo, scanned_at, metadata
                FROM pqc_crypto_assets
                WHERE tenant_id = %s
                ORDER BY scanned_at DESC
                LIMIT %s OFFSET %s
                """,
                (tenant_id, limit, offset),
            ).fetchall()

            loaded: list[CryptoAssetItem] = []
            for r in rows:
                meta = r[13] if isinstance(r[13], dict) else json.loads(r[13]) if r[13] else {}
                item = CryptoAssetItem(
                    asset_id=r[0],
                    tenant_id=r[1],
                    hostname=r[2],
                    hostname_hash=r[3],
                    tls_version=r[4],
                    cipher_suite=r[5],
                    cert_signature_algo=r[6],
                    cert_key_size=r[7],
                    cert_expiry=r[8],
                    classification=r[9],
                    hndl_vulnerable=r[10],
                    quantum_safe_algo=r[11],
                    warning=meta.get("warning"),
                    recommended_action=meta.get("recommended_action", ""),
                    scanned_at=r[12],
                )
                loaded.append(item)
                if tenant_id not in self._inventory:
                    self._inventory[tenant_id] = {}
                self._inventory[tenant_id][item.asset_id] = item
            return loaded
        except Exception as err:
            logger.warning("pqc.db_load_failed", error=str(err))
            return None

    def _write_fallback(self, assets: list[CryptoAssetItem], tenant_id: str) -> None:
        """Write backup JSON cache when database is unavailable."""
        try:
            path = Path(self.config.fallback_dir)
            path.mkdir(parents=True, exist_ok=True)
            cache_file = path / f"pqc_{tenant_id}.json"
            data = [a.model_dump(mode="json") for a in assets]
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as err:
            logger.warning("pqc.fallback_write_failed", error=str(err))


_GLOBAL_PQC_TRACKER: PQCTracker | None = None


def get_default_pqc_tracker() -> PQCTracker:
    """Return singleton PQCTracker instance."""
    global _GLOBAL_PQC_TRACKER
    if _GLOBAL_PQC_TRACKER is None:
        _GLOBAL_PQC_TRACKER = PQCTracker()
    return _GLOBAL_PQC_TRACKER
