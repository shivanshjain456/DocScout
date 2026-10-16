"""Public interface for SLSA Level 3 Cryptographic Provenance (FEAT-098)."""

from __future__ import annotations

from scripts.provenance import (
    ArtifactMaterial,
    ProvenanceConfig,
    SLSAProvenanceAttestation,
    generate_provenance_attestation,
    record_audit_trail,
    verify_startup_provenance,
)

__all__ = [
    "ArtifactMaterial",
    "ProvenanceConfig",
    "SLSAProvenanceAttestation",
    "generate_provenance_attestation",
    "record_audit_trail",
    "verify_startup_provenance",
]
