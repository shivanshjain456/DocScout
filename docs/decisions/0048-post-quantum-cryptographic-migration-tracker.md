# ADR-0048: Post-Quantum Cryptographic Migration Tracker (FEAT-057)

## Status
Accepted

## Context
Quantum computing advancements pose an existential threat to classical public-key cryptography (RSA, DSA, ECDSA, ECDH) through Shor's algorithm. Adversaries and nation-state actors are currently executing Harvest-Now-Decrypt-Later (HNDL) attacks: intercepting and archiving encrypted enterprise communications and sensitive financial payloads today, with the explicit strategy of decrypting them once Cryptographically Relevant Quantum Computers (CRQCs) become viable.

Financial regulatory frameworks (including RBI guidelines on Cyber Security, NIST Post-Quantum Cryptography standards FIPS 203/204/205, and BIS Project Leap recommendations) mandate that regulated financial entities inventory cryptographic assets, measure quantum vulnerability exposure, and operationalize migration pathways toward quantum-safe algorithms.

DocScout requires an automated Post-Quantum Cryptographic Migration Tracker operationalizing `playbook.crypto-migration`. The tracker must scan and classify enterprise endpoint cryptographic specifications, calculate institutional HNDL vulnerability exposure, distinguish between classical, hybrid, and FIPS-standardized post-quantum cipher suites, track migration milestones, and enforce tenant-isolated audit persistence.

## Decision
1. **Database Schema (`migrations/0042_pqc_assets.up.sql`)**:
   - Create `pqc_crypto_assets` table tracking `asset_id` (UUID PK), `tenant_id` (VARCHAR), `hostname` (VARCHAR), `hostname_hash` (VARCHAR), `tls_version` (VARCHAR), `cipher_suite` (VARCHAR), `cert_signature_algo` (VARCHAR), `cert_key_size` (INT), `cert_expiry` (DATE), `classification` (VARCHAR), `hndl_vulnerable` (BOOLEAN), `quantum_safe_algo` (VARCHAR), `scanned_at` (TIMESTAMPTZ), and `metadata` (JSONB).
   - Configure multi-tenant Row-Level Security (RLS) isolating inventory per tenant.
   - Hash sensitive hostnames to guarantee data privacy and zero sensitive infrastructure leakage.
   - Index on `(tenant_id, scanned_at)` and `(classification)`.
   - Grant full DML permissions to `docscout_app`.

2. **Core PQC Engine (`app/compliance/pqc_tracker.py`)**:
   - `PQCConfig`: Configures migration policy thresholds (`flag_rsa_under_3072: bool = True`, `strict_hndl_cutoff_year: int = 2030`).
   - Cipher Suite Classifier: Pure Python classification engine evaluating TLS versions, key exchange groups, cipher suites, signature algorithms, and key lengths:
     - `PQC_READY`: NIST FIPS 203 (ML-KEM), FIPS 204 (ML-DSA), FIPS 205 (SLH-DSA), NIST SP 800-208 (LMS/XMSS).
     - `HYBRID`: Post-quantum + classical hybrid key exchanges (e.g. X25519Kyber768Draft00, SecP256r1MLKEM768).
     - `CLASSICAL_SAFE`: Strong classical ciphers (TLS 1.2+, AES-GCM, ECDHE, RSA >= 3072), secure against classical cryptanalysis but exposed to HNDL.
     - `CLASSICAL_DEPRECATED`: Insecure/deprecated ciphers (SSLv3, TLS 1.0/1.1, RC4, 3DES, CBC mode with SHA1, RSA < 2048, or expired certificates).
     - `UNKNOWN_AUDIT_REQUIRED`: Unrecognized or custom cipher suites flagged for manual audit with diagnostic warnings.
   - HNDL Exposure Scoring: Computes ratio of endpoints vulnerable to interception and future quantum decryption.
   - Readiness Scoring: Computes institutional post-quantum readiness score ($0.0 \dots 100.0\%$).
   - Milestone Progression: Maps readiness into `PHASE_1_INVENTORY`, `PHASE_2_HYBRID_TRANSITION`, or `PHASE_3_QUANTUM_RESILIENT`.
   - Performance: Evaluates 1,000 endpoint specs in <= 10.0 ms with <= 4 MB memory allocation.

3. **REST API Extensions (`app/api/app.py`)**:
   - `POST /v1/compliance/pqc/scan`: Ingests batches of endpoint crypto specs, persists inventory, updates metrics, and returns comprehensive readiness reports.
   - `GET /v1/compliance/pqc/inventory`: Retrieves paginated cryptographic asset inventories for the authenticated tenant.
   - `GET /v1/compliance/pqc/readiness`: Returns current institutional readiness score, milestone status, and HNDL exposure summary.

4. **Observability (`app/api/metrics.py`)**:
   - Gauge `docscout_pqc_readiness_score{tenant_id}`: Current post-quantum readiness score percentage.
   - Counter `docscout_pqc_assets_inventoried_total{classification}`: Total assets processed by classification.

5. **Console UI Component (`ui/src/components/PQCConsole.tsx`)**:
   - Visual dashboard presenting readiness gauges, HNDL risk meters, asset inventory table with classification badges, and migration milestone progression.

## Consequences
- Enables financial institutions to systematically inventory cryptographic assets and eliminate HNDL blind spots.
- Enforces multi-tenant isolation and hostname privacy through cryptographic hashing.
- Ultra-low latency (<= 10.0 ms for 1,000 endpoints) allows integration into automated CI/CD and deployment scanners without latency degradation.
