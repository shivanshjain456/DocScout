"""Tests for FEAT-098: Immutable Cryptographic Audit Trail (SLSA Level 3 Provenance)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.provenance import (
    DEFAULT_MANIFEST,
    DEFAULT_PUBKEY_BYTES,
    ArtifactMaterial,
    ProvenanceConfig,
    SLSAProvenanceAttestation,
    compute_file_sha256,
    generate_corpus_provenance,
    generate_provenance_attestation,
    generate_release_provenance,
    record_audit_trail,
    verify_startup_provenance,
)


def test_attestation_signing_and_verification() -> None:
    """Verify SLSA attestation signs canonically and verifies successfully."""
    material = ArtifactMaterial(
        uri="corpus/raw/test-doc.pdf",
        digest={"sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    )
    att = generate_provenance_attestation(
        subject={"name": "https://example.com/test-doc.pdf", "digest": material.digest},
        materials=[material],
        invocation={"builder": "test-runner"},
    )

    assert att.signature != ""
    assert att.verify(DEFAULT_PUBKEY_BYTES) is True


def test_attestation_tampered_payload_fails_verification() -> None:
    """Altering subject or materials after signing invalidates cryptographic signature."""
    material = ArtifactMaterial(
        uri="corpus/raw/doc.pdf",
        digest={"sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
    )
    att = generate_provenance_attestation(
        subject={"name": "https://example.com/doc.pdf", "digest": material.digest},
        materials=[material],
    )
    assert att.verify(DEFAULT_PUBKEY_BYTES) is True

    # Tamper with subject
    att.subject["name"] = "https://example.com/tampered.pdf"
    assert att.verify(DEFAULT_PUBKEY_BYTES) is False


def test_attestation_corrupted_signature_fails() -> None:
    """Corrupted base64 signature bytes fail closed."""
    att = SLSAProvenanceAttestation(
        subject={"name": "test"},
        signature="bm90LWEtdmFsaWQtc2lnbmF0dXJl",  # not a valid ed25519 signature
    )
    assert att.verify(DEFAULT_PUBKEY_BYTES) is False


def test_file_sha256_computation(tmp_path: Path) -> None:
    """Compute exact SHA-256 for a test artifact."""
    f = tmp_path / "sample.bin"
    f.write_bytes(b"docscout regulatory evidence payload")
    digest = compute_file_sha256(f)
    assert len(digest) == 64
    assert digest == "d5465df27673b18f40e405dff76f56e51764de07931718d7f83e1fe3ddc35d78"


def test_corpus_provenance_generation_and_full_verification(tmp_path: Path) -> None:
    """Generate provenance for all 35 documents and verify signatures."""
    attestations = generate_corpus_provenance(DEFAULT_MANIFEST, output_dir=tmp_path)
    assert len(attestations) == 35

    # Verify every attestation signature
    for att in attestations:
        assert att.verify(DEFAULT_PUBKEY_BYTES) is True
        assert "sha256" in att.subject["digest"]
        assert len(att.materials) >= 1


def test_release_provenance_generation(tmp_path: Path) -> None:
    """Generate and verify release bundle attestation covering SBOM and lockfile."""
    att = generate_release_provenance(output_dir=tmp_path)
    assert att.verify(DEFAULT_PUBKEY_BYTES) is True
    assert att.subject["name"] == "docscout-release-bundle"


def test_signature_verification_latency_under_15ms(tmp_path: Path) -> None:
    """Cryptographic signature verification takes <= 15 ms, meeting latency limit."""
    att = generate_provenance_attestation(
        subject={"name": "benchmark"},
        materials=[ArtifactMaterial(uri="a", digest={"sha256": "0" * 64})],
    )
    t0 = time.perf_counter()
    for _ in range(10):
        verified = att.verify(DEFAULT_PUBKEY_BYTES)
        assert verified is True
    t1 = time.perf_counter()
    per_op_ms = ((t1 - t0) / 10.0) * 1000.0
    assert per_op_ms < 1.0  # Typically < 0.1 ms


def test_startup_provenance_tampered_file_halts(tmp_path: Path) -> None:
    """Tampering with an artifact file digest raises RuntimeError (fails closed)."""
    # Create fake manifest and fake file
    fake_file = tmp_path / "fake.txt"
    fake_file.write_bytes(b"authentic bytes")
    fake_sha = compute_file_sha256(fake_file)

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "url": "https://example.com/fake",
                        "local_path": str(fake_file.relative_to(tmp_path)),
                        "sha256": fake_sha,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    prov_dir = tmp_path / "prov"
    generate_corpus_provenance(manifest_file, output_dir=prov_dir)
    generate_release_provenance(output_dir=prov_dir)

    # Now tamper with fake_file
    fake_file.write_bytes(b"tampered malicious bytes")

    config = ProvenanceConfig(
        verify_signatures_at_startup=True,
        provenance_dir=prov_dir,
        manifest_path=manifest_file,
    )
    with pytest.raises(RuntimeError, match="Integrity violation"):
        verify_startup_provenance(config)


def test_startup_provenance_invalid_signature_halts(tmp_path: Path) -> None:
    """Attestation with invalid signature raises RuntimeError."""
    prov_dir = tmp_path / "prov"
    prov_dir.mkdir(parents=True)
    bad_att = [
        {
            "schema_version": "https://slsa.dev/provenance/v1",
            "builder": "attacker",
            "subject": {"name": "corrupt"},
            "materials": [],
            "signature": "aW52YWxpZA==",
        }
    ]
    (prov_dir / "corpus-provenance.json").write_text(json.dumps(bad_att), encoding="utf-8")
    (prov_dir / "release-provenance.json").write_text(json.dumps(bad_att[0]), encoding="utf-8")

    config = ProvenanceConfig(provenance_dir=prov_dir)
    with pytest.raises(RuntimeError, match="signature verification failed"):
        verify_startup_provenance(config)


def test_record_audit_trail_executes_insert() -> None:
    """Verify record_audit_trail invokes database INSERT with expected schema."""
    conn = MagicMock()
    att = generate_provenance_attestation(
        subject={"name": "test"},
        materials=[],
    )
    record_audit_trail(
        conn,
        entity_type="circular",
        entity_id="test-id",
        sha256_digest="a" * 64,
        attestation=att,
    )
    assert conn.execute.called
    call_args = conn.execute.call_args[0]
    assert "INSERT INTO cryptographic_audit_trail" in call_args[0]
    assert call_args[1][0] == "circular"
    assert call_args[1][1] == "test-id"
    assert call_args[1][2] == "a" * 64


def test_full_corpus_startup_provenance_passes() -> None:
    """Full repository startup verification succeeds against committed corpus assets."""
    config = ProvenanceConfig(verify_signatures_at_startup=True)
    assert verify_startup_provenance(config) is True
