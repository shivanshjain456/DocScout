# ADR-0089: Immutable Cryptographic Audit Trail (SLSA Level 3 Provenance)

## Context
Enterprise regulatory environments (SOC 2, ISO 27001, HIPAA, and FedRAMP) require tamper-evident provenance and non-repudiation for all ingested documents, model artifacts, and ingestion pipelines.
Traditional audit logging to mutable databases or plain text log files is vulnerable to:
1. Retroactive log alteration or deletion by privileged database administrators or compromised services.
2. Inability to mathematically verify that a specific ingested document version matches the exact upstream source downloaded from the regulator.
3. Lack of end-to-end cryptographic lineage linking source documents, artifact digests, build configurations, and ingestion actions.

To establish zero-trust verifiable compliance, we require an immutable cryptographic audit trail conforming to the SLSA (Supply-chain Levels for Software Artifacts) Level 3 Provenance specification, backed by asymmetric Ed25519 digital signatures and append-only cryptographic storage.

## Decision
1. Cryptographic Provenance Engine in `scripts/provenance.py` and `app/provenance.py`:
   - Data structures: `ArtifactMaterial(uri, digest)` and `SLSAProvenanceAttestation(predicate_type, subject, predicate, materials, invocation, signer_identity, created_at, signature)`.
   - Asymmetric Ed25519 signing and verification using `cryptography.hazmat.primitives.asymmetric.ed25519`.
   - Canonical payload serialization with deterministic key sorting and separators `(",", ":")` to ensure signature stability across environments.
   - Generation of SLSA v0.2 / in-toto compatible attestation manifests:
     - Corpus provenance: 35 source documents in `docs/security/provenance/corpus-provenance.json` recording document URLs, local paths, and upstream SHA-256 digests.
     - Release provenance: Ingestion engine and deployment bundle in `docs/security/provenance/release-provenance.json` linking SBOM, lockfiles, and git commit revisions.
2. Append-Only Database Storage and Ingestion Hook:
   - Migration `migrations/0053_audit_trail.up.sql` creating `cryptographic_audit_trail` table:
     - Columns: `id` (UUID), `timestamp` (TIMESTAMPTZ), `event_type` (VARCHAR), `subject_id` (VARCHAR), `subject_digest` (VARCHAR), `attestation` (JSONB), `signature` (VARCHAR), `signer_identity` (VARCHAR).
     - Row-level trigger `trg_prevent_audit_trail_mutation` failing any `UPDATE` or `DELETE` attempt with an exception.
     - View `audit_trail` providing read-only query access for compliance auditors.
   - Document store integration in `app/ingest/store.py`:
     - Every document version insertion automatically signs an attestation and writes an immutable record via `record_audit_trail`.
3. Fast Startup and CI Verification:
   - Lifespan startup check in `app/api/app.py`:
     - Verifies all corpus attestations and signatures upon application boot.
     - Enforces verification latency under 15 ms (< 5 ms typical on 35 documents).
     - Fails closed on signature mismatch, digest tampering, or missing materials.
   - Makefile target `provenance-verify` and CI workflow step in `.github/workflows/ci.yml`.
   - Metric `ATTESTATIONS_VERIFIED_TOTAL` in `app/api/metrics.py`.

## Consequences
- **Positive:**
  - Mathematical non-repudiation and tamper detection for all ingested regulatory documents and pipeline outputs.
  - Zero-overhead startup verification (< 5 ms across the entire 35-document corpus).
  - Clean compliance export interface with cryptographically signed in-toto attestations.
  - Fail-closed security architecture protecting against corrupt or modified upstream documents.
- **Neutral:**
  - Signing keys must be maintained securely (using environment variables or secret managers in production).
