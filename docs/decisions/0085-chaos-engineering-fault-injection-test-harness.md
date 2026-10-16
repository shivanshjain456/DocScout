# ADR-0085: Chaos Engineering Fault Injection Test Harness

## Context
High-availability enterprise regulatory intelligence engines must guarantee resilience and graceful degradation under real-world infrastructure failures: PostgreSQL connection timeouts, pgvector index crashes, external OCR.Space API dropouts, Redis/semantic cache outages, and memory spikes during heavy embedding runs. In unhardened architectures, transient socket drops or corrupted upstream responses cause unhandled tracebacks, hung event loops, or cascading pod restarts.

To ensure DocScout degrades gracefully (returning cached evidence, structured HTTP 503 retry guidance, or 422 validation details) without unhandled exceptions or zombie processes, we require an automated chaos engineering fault injection harness.

## Decision
1. Implement Chaos Engineering Fault Injection in `app/chaos.py`:
   - Configured via `ChaosConfig(max_fault_duration_ms: int = 5000)`.
   - Strict safety guard: Fault injection is active ONLY when `DOCSCOUT_CHAOS_TESTING=1`.
   - Context manager `inject_fault(fault_type, delay_ms, error_code, drop_rate)` supporting 10 fault types:
     - `db_timeout`: PostgreSQL socket timeout during search
     - `db_disconnect`: Database disconnect during active query
     - `pgvector_crash`: Vector index query failure with fallback
     - `ocr_timeout`: External OCR.Space network drop
     - `ocr_corrupt_payload`: Malformed / unexpected external JSON
     - `embedder_failure`: Embedding model transient failure / memory pressure
     - `cache_failure`: Redis cache outage with transparent in-memory fallback
     - `pool_exhaustion`: Database connection pool saturation triggering bulkhead load shedding
     - `latency_spike`: Bounded artificial network latency injection
     - `network_partition`: Transient DB partition with sub-500ms recovery time assertion
   - Structured observability logging: logs `chaos.fault_injected` and `chaos.fault_cleared` markers.
2. Update Serving API & Health Probes in `app/api/app.py`:
   - `/healthz` probe returns `status="degraded"` and reports active fault components when faults are active, returning to `status="ok"` immediately upon clearance.
   - Search handler catches `psycopg.OperationalError` gracefully and raises HTTP 503 with `Retry-After: 1` header instead of crashing.
3. Automated Chaos Test Suite in `tests/chaos/test_fault_injection.py`:
   - Executes all 10 fault injection scenarios.
   - Evaluates `ChaosTestReport`: asserts `faults_injected == 10`, `graceful_degradations == 10`, `unhandled_exceptions == 0`, and `passed == True`.
   - Asserts recovery time $\le 500\text{ ms}$ once network partition is cleared.
4. Add `make test-chaos` target to `Makefile`.

## Consequences
- **Positive:**
  - 100% graceful degradation: zero unhandled tracebacks or zombie processes during simulated DB or service failures.
  - Core recovery time $\le 500\text{ ms}$ once fault is cleared.
  - Safe hermetic test execution with zero impact on production binaries.
- **Neutral:**
  - When downstream database is unreachable, clients receive structured HTTP 503 with retry instructions rather than search results.
