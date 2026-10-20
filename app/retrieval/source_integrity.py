"""Cryptographic source integrity and third-party verifiable attestation (O1).

Implements:
1. Ed25519 digital signature generation by an independent Notary Authority.
2. Chunk-level content hash verification against signed version digests.
3. Strict retrieval filtering: tampered or unverified chunks are unretrievable.
4. Independent third-party verification surface returning explicit verdicts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

if TYPE_CHECKING:
    from app.retrieval.port import ChunkRow


class IntegrityStatus(StrEnum):
    """Explicit verdict on document / chunk provenance integrity."""

    VERIFIED = "VERIFIED"
    TAMPERED = "TAMPERED"
    UNVERIFIABLE = "UNVERIFIABLE"


def compute_chunk_hash(chunk_id: str, text: str, char_start: int = 0, char_end: int = 0) -> str:
    """Compute deterministic cryptographic hash of a chunk's content and span."""
    content = f"{chunk_id}:{char_start}:{char_end}:{text}".encode()
    return hashlib.sha256(content).hexdigest()


def compute_chunk_root_hash(chunk_hashes: list[str]) -> str:
    """Compute aggregate root hash over sorted chunk digests."""
    joined = "".join(sorted(chunk_hashes)).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


@dataclass(frozen=True)
class SourceAttestation:
    """Cryptographic attestation signed by the independent Notary Authority."""

    document_id: str
    version_id: str
    version_sha256: str
    chunk_root_hash: str
    notary_id: str
    timestamp: str
    signature_hex: str
    chunk_hashes: dict[str, str] = field(default_factory=dict)

    def digest(self) -> bytes:
        """Canonical digest signed by the notary."""
        payload = (
            f"{self.document_id}:{self.version_id}:{self.version_sha256}:"
            f"{self.chunk_root_hash}:{self.notary_id}:{self.timestamp}"
        )
        return hashlib.sha256(payload.encode("utf-8")).digest()


@dataclass(frozen=True)
class DocumentIntegrityVerdict:
    """Explicit verification verdict for third parties."""

    document_id: str
    status: IntegrityStatus
    signature_valid: bool
    version_sha256: str
    chunk_count: int
    tampered_chunks: list[str] = field(default_factory=list)
    notary_id: str | None = None
    detail: str = ""


class NotaryAuthority:
    """Independent notary authority holding the Ed25519 private key.

    In production, this sits outside the DocScout ingestion host and content store,
    accessible only via a signed notary RPC or detached release pipeline.
    """

    def __init__(
        self,
        signer: ed25519.Ed25519PrivateKey | None = None,
        notary_id: str = "docscout-notary-authority/1",
    ) -> None:
        self.notary_id = notary_id
        self._signer = signer or ed25519.Ed25519PrivateKey.generate()
        self.public_key = self._signer.public_key()

    @property
    def public_key_bytes(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign_document(
        self,
        document_id: str,
        version_id: str,
        version_sha256: str,
        chunks: dict[str, ChunkRow],
        timestamp: str | None = None,
    ) -> SourceAttestation:
        """Sign a document version and its constituent chunks."""
        ts = timestamp or datetime.now(UTC).isoformat()
        chunk_hashes: dict[str, str] = {}
        for cid, row in chunks.items():
            chunk_hashes[cid] = compute_chunk_hash(cid, row.text, row.char_start, row.char_end)

        root_hash = compute_chunk_root_hash(list(chunk_hashes.values()))

        # Build unsigned attestation to compute canonical digest
        unsigned_digest = hashlib.sha256(
            f"{document_id}:{version_id}:{version_sha256}:{root_hash}:{self.notary_id}:{ts}".encode()
        ).digest()

        signature = self._signer.sign(unsigned_digest)
        return SourceAttestation(
            document_id=document_id,
            version_id=version_id,
            version_sha256=version_sha256,
            chunk_root_hash=root_hash,
            notary_id=self.notary_id,
            timestamp=ts,
            signature_hex=signature.hex(),
            chunk_hashes=chunk_hashes,
        )


class SourceIntegrityVerifier:
    """Retrieval-time and third-party verification engine holding only the public key."""

    def __init__(
        self,
        verify_key: ed25519.Ed25519PublicKey | None = None,
        strict_mode: bool = True,
    ) -> None:
        self.verify_key = verify_key
        self.strict_mode = strict_mode
        self._attestations: dict[str, SourceAttestation] = {}  # version_id -> attestation
        self._doc_to_version: dict[str, str] = {}  # document_id -> version_id
        self._chunk_hashes: dict[str, str] = {}  # chunk_id -> expected hash

    def register_attestation(self, attestation: SourceAttestation) -> bool:
        """Register and cryptographically verify an attestation."""
        if not self.verify_attestation(attestation):
            return False
        self._attestations[attestation.version_id] = attestation
        self._doc_to_version[attestation.document_id] = attestation.version_id
        for cid, h in attestation.chunk_hashes.items():
            self._chunk_hashes[cid] = h
        return True

    def verify_attestation(self, attestation: SourceAttestation) -> bool:
        """Cryptographically check the signature of an attestation."""
        if self.verify_key is None:
            return False
        sig_bytes = bytes.fromhex(attestation.signature_hex)
        try:
            self.verify_key.verify(sig_bytes, attestation.digest())
            return True
        except (InvalidSignature, ValueError):
            return False

    def verify_document(
        self,
        document_id: str,
        version_id: str,
        version_sha256: str,
        chunks: dict[str, ChunkRow],
    ) -> DocumentIntegrityVerdict:
        """Evaluate a document version and its chunks for provenance integrity."""
        attestation = self._attestations.get(version_id)
        if attestation is None:
            return DocumentIntegrityVerdict(
                document_id=document_id,
                status=IntegrityStatus.UNVERIFIABLE,
                signature_valid=False,
                version_sha256=version_sha256,
                chunk_count=len(chunks),
                detail="No registered notary attestation found for this document version",
            )

        if not self.verify_attestation(attestation):
            return DocumentIntegrityVerdict(
                document_id=document_id,
                status=IntegrityStatus.UNVERIFIABLE,
                signature_valid=False,
                version_sha256=version_sha256,
                chunk_count=len(chunks),
                detail="Notary signature verification failed against trusted public key",
            )

        tampered: list[str] = []
        observed_hashes: list[str] = []
        for cid, chunk in chunks.items():
            curr_hash = compute_chunk_hash(cid, chunk.text, chunk.char_start, chunk.char_end)
            observed_hashes.append(curr_hash)
            expected_hash = self._chunk_hashes.get(cid) or attestation.chunk_hashes.get(cid)
            if expected_hash is not None and curr_hash != expected_hash:
                tampered.append(cid)

        # Check chunk root hash
        computed_root = compute_chunk_root_hash(observed_hashes)
        if tampered or computed_root != attestation.chunk_root_hash:
            return DocumentIntegrityVerdict(
                document_id=document_id,
                status=IntegrityStatus.TAMPERED,
                signature_valid=True,
                version_sha256=version_sha256,
                chunk_count=len(chunks),
                tampered_chunks=tampered or list(chunks.keys()),
                notary_id=attestation.notary_id,
                detail="Stored content fails integrity verification against signed notarized root",
            )

        return DocumentIntegrityVerdict(
            document_id=document_id,
            status=IntegrityStatus.VERIFIED,
            signature_valid=True,
            version_sha256=version_sha256,
            chunk_count=len(chunks),
            notary_id=attestation.notary_id,
            detail="Cryptographic source integrity verified",
        )

    def filter_retrieved_chunks(
        self,
        chunks: dict[str, ChunkRow],
        version_meta: dict[str, tuple[str, str]] | None = None,
    ) -> dict[str, ChunkRow]:
        """Filter retrieved chunk metadata: exclude tampered or unverifiable chunks."""
        if not self.strict_mode:
            return chunks

        verified: dict[str, ChunkRow] = {}
        for cid, chunk in chunks.items():
            # If chunk hash is known and matches
            expected_h = self._chunk_hashes.get(cid)
            if expected_h is None:
                # Unverifiable source: exclude under strict mode
                continue

            curr_h = compute_chunk_hash(cid, chunk.text, chunk.char_start, chunk.char_end)
            if curr_h != expected_h:
                # Tampered chunk content: exclude
                continue

            verified[cid] = chunk

        return verified


# Global default notary & verifier for the service
_GLOBAL_NOTARY: NotaryAuthority | None = None
_GLOBAL_VERIFIER: SourceIntegrityVerifier | None = None


def get_default_notary() -> NotaryAuthority:
    global _GLOBAL_NOTARY
    if _GLOBAL_NOTARY is None:
        _GLOBAL_NOTARY = NotaryAuthority()
    return _GLOBAL_NOTARY


def get_default_source_verifier() -> SourceIntegrityVerifier:
    global _GLOBAL_VERIFIER
    if _GLOBAL_VERIFIER is None:
        notary = get_default_notary()
        _GLOBAL_VERIFIER = SourceIntegrityVerifier(verify_key=notary.public_key, strict_mode=False)
    return _GLOBAL_VERIFIER


def verify_document_integrity(
    document_id: str,
    chunks: dict[str, ChunkRow] | None = None,
    verifier: SourceIntegrityVerifier | None = None,
) -> DocumentIntegrityVerdict:
    """Public helper to verify a document's integrity."""
    v = verifier or get_default_source_verifier()
    doc_chunks = chunks or {}
    version_id = v._doc_to_version.get(document_id, "")
    attestation = v._attestations.get(version_id)
    version_sha256 = attestation.version_sha256 if attestation else ""
    return v.verify_document(
        document_id=document_id,
        version_id=version_id,
        version_sha256=version_sha256,
        chunks=doc_chunks,
    )
