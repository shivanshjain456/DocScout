# ADR-0075: Canary Token Provenance & Leakage Assertions (FEAT-084)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Application Security Team, Data Integrity & Assurance Guild, CI/CD Engineering
* **Informed:** Core Platform Engineers, Operations

---

## Context and Problem Statement

In regulated enterprise environments, retrieval-augmented intelligence systems frequently ingest synthetic benchmark circulars, test fixtures, and red-teaming canary artifacts. It is an absolute regulatory invariant that synthetic fixtures must never cross boundaries into production tenant search responses or contaminate legitimate statutory retrieval (ADR-0010, ADR-0024, G-EVAL-1).

Without continuous, cryptographic verification, silent indexing regressions or query filter bypasses could leak synthetic data into customer-facing regulatory answers, exposing fictitious clauses or confidential test artifacts.

FEAT-084 provides a cryptographic Canary Token Provenance & Leakage Assertion pipeline:
1. Plants high-entropy cryptographic canary tokens (`CANARY-<hex>`) into synthetic test circular fixtures.
2. Registers planted tokens in a relational ledger (`canary_tokens`).
3. Executes automated assertion sweeps across production retrieval outputs, verifying 100% non-emergence of canary tokens.
4. Fails closed (exit code 1) in automated CI security gates if any canary token is detected in production responses.

---

## Decision Drivers

1. **Mathematical Proof of Zero Contamination:**
   Verify that synthetic test circulars marked `is_synthetic = True` never leak into production responses (Leakage Rate = 0.000).
2. **High-Entropy Cryptographic Tokens:**
   Generate unique, collision-resistant tokens using `secrets.token_hex(16)` prefixed by `CANARY-`.
3. **Database Ledger & Tracking:**
   Create table `canary_tokens` tracking token string, fixture name, document ID, and planting timestamp.
4. **Automated Assertion Suite:**
   Implement `CanaryManager` in `app/evals/canary.py` and standalone verification runner `scripts/verify_canaries.py`.
5. **Observability & Telemetry:**
   Export Prometheus metrics:
   - `docscout_canary_audit_runs_total` (Counter)
   - `docscout_canary_leakage_detected` (Gauge)
6. **Strict CI Execution Budget:**
   Canary assertion suite completes in <= 5.0 seconds in CI, with zero runtime memory overhead on production serving queries.
7. **Typographical Invariant:** Strict ASCII typographical compliance across all documentation and code.

---

## Decision Outcome

We implement:
- `migrations/0052_canary_tokens.up.sql` and `migrations/0052_canary_tokens.down.sql`
- `app/evals/canary.py` with `CanaryConfig`, `CanaryToken`, `CanaryAuditReport`, and `CanaryManager`
- Standalone CLI `scripts/verify_canaries.py`
- Prometheus metrics in `app/api/metrics.py`
- Unit and integration tests in `tests/test_canary.py`

---

## Validation and Testing

1. Unit tests verifying cryptographic token generation, planting, and zero-leakage assertions.
2. Contamination detection test verifying immediate detection and fail-closed reporting when a canary token is injected into production results.
3. Database ledger schema verification and audit queries.
4. CI execution speed verified under 5.0 seconds.
