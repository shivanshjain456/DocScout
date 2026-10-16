# ADR-0047: Regulated Release Certification Pipeline (FEAT-056)

## Status
Accepted

## Context
Deploying software updates to mission-critical financial switches, real-time payment rails, and regulatory reporting gateways requires formal evidence that the release candidate satisfies strict safety, security, and verification thresholds. In conventional deployments, releases proceed on subjective approval tickets or manual email sign-offs that lack tamper-proof audit trails, verifiable test evidence, and formal safety cases. Financial regulations (including RBI guidelines on Change Management and SEBI cybersecurity frameworks) require explicit verification records and safety cases prior to promoting binaries to production environments.

DocScout requires an automated release certification pipeline operationalizing `playbook.regulated-release`. The pipeline must evaluate CI test artifacts (JUnit XML / JSON), structural test coverage reports (Cobertura / coverage.py), mutation analysis scores, and SAST findings. It must synthesize a formal Safety Case in Goal Structuring Notation (GSN) and issue a cryptographically signed Release Certificate before deployment can proceed.

## Decision
1. **Database Persistence (`migrations/0041_release_certificates.up.sql`)**:
   - Create `release_certificates` table recording `certificate_id` (UUID PK), `tenant_id`, `commit_sha` (40-char hex), `build_id`, `is_certified` (BOOLEAN), `gsn_safety_case_json` (JSONB), `signature_sha256` (64-char hex digest), `rejection_reasons` (JSONB array), and `certified_at` (TIMESTAMPTZ).
   - Enable multi-tenant Row-Level Security (RLS) and index on `(commit_sha)` and `(tenant_id)`.
   - Grant full DML permissions to `docscout_app`.

2. **Release Certifier Engine (`app/workflows/release_certifier.py`)**:
   - `ReleaseCertConfig`: Configures certification thresholds (`min_mutation_score: float = 0.78`, `min_coverage: float = 0.85`, `require_slsa_level_3: bool = True`).
   - `CertifyReleaseRequest`: Validates `commit_sha` (strict 40-character hexadecimal string), `build_id`, `test_report_path`, `coverage_report_path`, and optional `mutation_report_path` / `sast_report_path`.
   - `ReleaseCertificate`: Output schema capturing `certificate_id`, `commit_sha`, `is_certified`, `gsn_safety_case_json`, `signature_sha256`, and `certified_at`.
   - Goal Structuring Notation (GSN) Generator: Synthesizes top-level safety goal $G_1$, strategy $S_1$, decomposed sub-goals ($G_{1.1}$ tests, $G_{1.2}$ coverage, $G_{1.3}$ mutation, $G_{1.4}$ security), context references ($C_1$), and concrete solution evidence ($Sn_1 \dots Sn_4$).
   - Cryptographic Attestation: Computes deterministic SHA-256 digest over normalized GSN safety case payload, generating verifiable institutional signature.
   - Execution performance bounded to <= 1.5 seconds and memory <= 32 MB.

3. **CLI Script (`scripts/certify_release.py`)**:
   - Executable entry point for CI/CD runners (e.g. GitHub Actions `.github/workflows/deploy.yml`).
   - Exits with status code 0 on certification success and status code 1 on verification failure, halting deployment pipelines immediately.

4. **REST API Extensions (`app/api/app.py`)**:
   - `POST /v1/compliance/certify-release`: Public serving API allowing programmatic certification requests from build systems and release controllers.
   - Rejects unverified commits with HTTP 422 if quality gates fail, returning detailed rejection reasons in response payload.

5. **Observability (`app/api/metrics.py`)**:
   - Counter `docscout_releases_certified_total{status}` recording release certification outcomes (`approved`, `rejected`).
   - Structured JSON logging via structlog with full build telemetry.

## Consequences
- Eliminates unverified or untested deployments to core financial switches 100% of the time.
- Produces verifiable, auditable GSN Safety Cases satisfying regulatory change management requirements.
- Lightweight execution (<= 1.5s) avoids introducing build pipeline bottlenecks.
