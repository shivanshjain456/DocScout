# ADR-0038: Audit Evidence Package Exporter (FEAT-047)

## Status
Accepted

## Context
Compliance officers and internal statutory auditors frequently require court-admissible, tamper-evident packages bundling retrieved regulatory circular clauses, citations, control mappings, and provenance metadata. Prior to this feature, evidence gathering required manual copy-pasting of clauses, leaving no cryptographic chain of custody or verification hashes for statutory review (RBI, SEBI, Basel III audits).

## Decision
1. **Audit Evidence Exporter Engine (`app/compliance/exporter.py`)**:
   - Implements multi-format dossier export: PDF (ISO 19005-1 compliant vector encoding), ZIP archive with immutable clause text and machine-readable `manifest.json`, and structured Markdown.
   - Generates SHA-256 cryptographic provenance digests for every cited clause and a master package digest.
   - Supports HMAC-SHA256 digital signature stamp for cryptographic non-repudiation.
   - Automatic expiry handling with lifecycle purging of temporary export artifacts after 60 minutes.

2. **API Endpoints (`app/api/app.py`)**:
   - `POST /v1/compliance/export-evidence`: validates $1 \le \text{len}(passage_ids) \le 50$, compiles dossier, and registers temporary download token.
   - `GET /v1/compliance/export-download/{file_id}`: serves downloadable binary package with streaming response and integrity headers (`X-DocScout-SHA256`).

3. **Observability**:
   - Counter `docscout_audit_packages_exported_total{format}`.
   - Histogram `docscout_audit_package_export_duration_seconds`.

4. **Interactive UI (`ui/src/components/ExportModal.tsx`)**:
   - Modal interface in React console enabling format selection (PDF, ZIP, Markdown), audit reference tagging, and immediate download.

## Consequences
- 100% reproducible and verifiable audit trails with byte-level SHA-256 provenance hashes.
- Zero disk accumulation of stale files via automatic TTL eviction.
- Under 3.0 seconds generation budget for 50-clause audit packages.
