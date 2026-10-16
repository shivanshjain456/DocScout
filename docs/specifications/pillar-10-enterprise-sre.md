# Pillar 10 Specification: Enterprise Reliability, Security, Observability & Continuous Compliance
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-091: Automated Canary Analysis (ACA) Deployment Gate
- **Objective:** Implement automated canary analysis during production rollouts, routing 5% of production query traffic to canary pods and gating promotion on retrieval latency, error rate, and score drift.
- **In-scope behavior:** Comparing metric distributions between canary and baseline pods over a 15-minute evaluation window (Mann-Whitney U test on latency, Fisher's exact test on error rates); automatically triggering rollback if metrics deviate beyond threshold.
- **Excluded behavior:** Manual subjective human-in-the-loop sign-off without statistical validation.
- **Implementation boundaries:** `infra/canary/analysis.py`, `.github/workflows/deploy.yml`.
- **Integration points:** Kubernetes / Docker deployment rollout pipeline; Prometheus scraping hook.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`delivery-deployment-progressive-rollout`), `infra/canary/analysis.py`.
- **Supported inputs:** Canary Prometheus endpoint, baseline Prometheus endpoint, metric thresholds config.
- **Input validation rules:** Minimum 100 queries evaluated on canary pod before statistical analysis.
- **Output schema:** `CanaryDecision(promoted: bool, p_value: float, latency_delta_pct: float, error_rate_delta: float, rollback_triggered: bool)`.
- **Configuration schema:** `ACAConfig(eval_window_minutes: int = 15, max_allowed_latency_increase_pct: float = 5.0, max_error_rate: float = 0.001)`.
- **Default values:** `eval_window_minutes = 15`, `max_allowed_latency_increase_pct = 5.0`, `max_error_rate = 0.001`.
- **Dependencies:** Python `scipy.stats`, Prometheus API client.
- **Compatibility requirements:** Compatible with Kubernetes progressive delivery controllers (Argo Rollouts / Flagger).
- **Authorization rules:** Internal deployment infrastructure execution.
- **Data isolation rules:** Operates on anonymous infrastructure telemetry.
- **Error behavior:** If Prometheus is unreachable during canary evaluation, abort deployment and roll back (fail-safe).
- **Fallback behavior:** Automated rollback to last stable production revision.
- **Observability requirements:** Metric `docscout_canary_evaluations_total{decision}`, deployment audit log.
- **Performance limits:** Analysis execution completed in $\le 2.0\text{ seconds}$ per evaluation cycle.
- **Resource limits:** Memory footprint $\le 16\text{ MB}$.
- **Acceptance criteria:** Automatically aborts deployment and rolls back within 60 seconds if a simulated memory leak or 10ms latency regression is introduced in canary.
- **Evaluation dataset:** Simulated production deployment test suite with seeded performance regressions.
- **Evaluation baseline:** All-or-nothing deployments risking customer-facing outages.
- **Required improvement threshold:** 100% automated detection and rollback on regressed canary builds.
- **Regression limits:** Zero false-positive rollbacks on healthy canary deployments ($p > 0.05$).
- **Completion criteria:** Validated via automated deployment drill in `tests/test_canary_analysis.py`.

---

## FEAT-092: Error Budget Policy & Multi-Window Burn Rate Alerting
- **Objective:** Implement the taxonomy formula for 30-day error budgets (availability SLO 99.9%, latency p95 < 50ms) with multi-window burn rate alerts (1-hour 14.4x burn, 6-hour 6x burn) per Google SRE standards.
- **In-scope behavior:** Computing remaining error budget over rolling 30-day windows; evaluating short-window and long-window burn rates; triggering automated deployment freezes when budget drops below 10%.
- **Excluded behavior:** Overriding error budget freezes without formal VP of Engineering exception.
- **Implementation boundaries:** `app/api/error_budget.py`, `infra/prometheus/rules/alerts.yml`.
- **Integration points:** Prometheus alert rules; CI/CD deployment check `.github/workflows/deploy.yml`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`formulas` ["error-budget", "burn-rate"]), `app/api/error_budget.py`.
- **Supported inputs:** 30-day request counts, error counts, and latency percentiles from Prometheus.
- **Input validation rules:** Total requests $> 1,000$ in observation window.
- **Output schema:** `ErrorBudgetStatus(budget_remaining_pct: float, current_burn_rate_1h: float, current_burn_rate_6h: float, is_deployment_frozen: bool)`.
- **Configuration schema:** `SLOConfig(availability_target: float = 0.999, latency_p95_target_ms: float = 50.0, freeze_threshold_pct: float = 10.0)`.
- **Default values:** `availability_target = 0.999`, `latency_p95_target_ms = 50.0`, `freeze_threshold_pct = 10.0`.
- **Dependencies:** Prometheus alertmanager, Python math.
- **Compatibility requirements:** Conforms to standard SRE error budget alerting specifications.
- **Authorization rules:** Available to all internal monitoring scrapers.
- **Data isolation rules:** Aggregated operational metrics.
- **Error behavior:** If metric collection fails, assume budget is consumed and halt non-essential deployments.
- **Fallback behavior:** Fail-safe deployment freeze on monitoring blackout.
- **Observability requirements:** Gauge `docscout_error_budget_remaining_ratio`, alerts `DocScoutErrorBudgetRapidBurn`.
- **Performance limits:** Calculation execution $\le 1.0\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Successfully detects rapid error burns (14.4x) within 2 minutes of simulated outage, dispatching critical pager alarms.
- **Evaluation dataset:** 30-day simulated operational telemetry time series with synthetic outage spikes.
- **Evaluation baseline:** Point-in-time threshold alerts causing alert fatigue and missing slow budget drains.
- **Required improvement threshold:** 100% alert precision on budget-threatening incident patterns.
- **Regression limits:** Zero false pager alarms during normal traffic fluctuations.
- **Completion criteria:** Alert rules pass `promtool check rules` in CI.

---

## FEAT-093: Bulkhead Concurrency Isolation & Adaptive Load Shedding
- **Objective:** Implement thread and connection pool bulkheads separating user search requests from heavy background document ingestion and OCR jobs, with adaptive backpressure load shedding.
- **In-scope behavior:** Allocating dedicated DB connection pools (`search_pool`: 4 connections; `ingest_pool`: 2 connections); monitoring queue depths; shedding non-critical background jobs when search latency rises $>40\text{ ms}$; returning HTTP 429 / 503 with Retry-After.
- **Excluded behavior:** Allowing background ingestion batch jobs to exhaust database connections needed by real-time user searches.
- **Implementation boundaries:** `app/api/bulkhead.py`, `app/config.py`, `app/api/app.py`.
- **Integration points:** Database connection pool initialization in `app/api/app.py` lifespan; ASGI middleware.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`reliability-resilience-chaos`), `app/api/bulkhead.py`.
- **Supported inputs:** Incoming HTTP requests, background job queue requests.
- **Input validation rules:** Queue depth limits strictly enforced (max 50 waiting search requests).
- **Output schema:** Transparent pass-through or HTTP 503 / 429 with `Retry-After: 5` header.
- **Configuration schema:** `BulkheadConfig(search_pool_size: int = 4, ingest_pool_size: int = 2, max_search_queue: int = 50)`.
- **Default values:** `search_pool_size = 4`, `ingest_pool_size = 2`, `max_search_queue = 50`.
- **Dependencies:** `psycopg_pool.ConnectionPool`, Python `asyncio.Semaphore`.
- **Compatibility requirements:** Native Python 3.12 async execution.
- **Authorization rules:** Internal infrastructure component.
- **Data isolation rules:** Connection pools isolated by workload type.
- **Error behavior:** Connection pool exhaustion immediately triggers graceful load shedding rather than unhandled server crashes.
- **Fallback behavior:** Returns clean HTTP 503 with Retry-After header.
- **Observability requirements:** Gauge `docscout_bulkhead_active_connections{pool}`, counter `docscout_requests_shed_total{workload}`.
- **Performance limits:** Bulkhead acquisition overhead $\le 0.05\text{ ms}$.
- **Resource limits:** Hard cap on total database connections $\le 10$.
- **Acceptance criteria:** Real-time search p95 latency remains $\le 50\text{ ms}$ even during 100% saturation of background OCR ingestion jobs.
- **Evaluation dataset:** Locust / k6 load test simulating 50 concurrent search users while ingesting 500 pages of OCR PDFs.
- **Evaluation baseline:** Shared unpartitioned connection pool where bulk ingestion caused search timeouts and 500 errors.
- **Required improvement threshold:** Search availability = 100% under concurrent ingestion stress.
- **Regression limits:** Zero database connection leaks across 10,000 requests.
- **Completion criteria:** Load test verified in `loadtests/load_bulkhead.py`.

---

## FEAT-094: Chaos Engineering Fault Injection Test Harness
- **Objective:** Automated resilience test harness simulating network partitions to PostgreSQL, temporary pgvector crashes, and OCR.Space API timeouts to verify graceful degradation.
- **In-scope behavior:** Injecting synthetic socket timeouts, database disconnects, and corrupted API payloads during automated test execution; verifying that DocScout degrades gracefully (returning cached results or structured errors) without unhandled exceptions.
- **Excluded behavior:** Running destructive chaos tests in production without blast-radius limits.
- **Implementation boundaries:** `tests/chaos/test_fault_injection.py`, `app/api/app.py`.
- **Integration points:** CI test suite; `make test-chaos`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`playbook.resilience`), `tests/chaos/test_fault_injection.py`.
- **Supported inputs:** Synthetic fault injection parameters (delay, drop rate, error code).
- **Input validation rules:** Fault injection active only when `DOCSCOUT_CHAOS_TESTING=1`.
- **Output schema:** `ChaosTestReport(faults_injected: int, graceful_degradations: int, unhandled_exceptions: int, passed: bool)`.
- **Configuration schema:** `ChaosConfig(max_fault_duration_ms: int = 5000)`.
- **Default values:** `max_fault_duration_ms = 5000`.
- **Dependencies:** Python `unittest.mock`, `pytest`, `pytest-asyncio`.
- **Compatibility requirements:** Fully hermetic test execution.
- **Authorization rules:** Test environment execution only.
- **Data isolation rules:** Chaos tests execute on temporary ephemeral test containers.
- **Error behavior:** Any unhandled 500 exception or uncontained crash fails the chaos test suite.
- **Fallback behavior:** Application returns structured degraded health status via `/healthz`.
- **Observability requirements:** Log structured chaos event marker in test output.
- **Performance limits:** Chaos suite execution $\le 30\text{ seconds}$ in CI.
- **Resource limits:** Zero impact on production binaries.
- **Acceptance criteria:** 100% graceful degradation: zero unhandled tracebacks or zombie processes during simulated DB failure.
- **Evaluation dataset:** 10 chaos fault injection scenarios (DB timeout, OCR drop, embedder crash, corrupt payload).
- **Evaluation baseline:** Unhandled exceptions and hung async event loops during simulated network faults.
- **Required improvement threshold:** 0 unhandled exceptions across all 10 chaos scenarios.
- **Regression limits:** Core recovery time $\le 500\text{ ms}$ once fault is cleared.
- **Completion criteria:** `tests/chaos/test_fault_injection.py` exits 0 in CI.

---

## FEAT-095: Hermetic Deterministic Test Fixtures with Seeded Randomness
- **Objective:** Enforce 100% reproducible test suites across all environments with clock injection (time-travel testing) and frozen random seeds, completely eliminating flaky CI test failures.
- **In-scope behavior:** Freezing PRNG seeds (`random.seed(0)`, `numpy.random.seed(0)`); injecting mockable system clocks via `Clock` protocol; providing hermetic in-memory vector store doubles; eliminating real network dependencies.
- **Excluded behavior:** Relying on unseeded random numbers or wall-clock timestamps in test assertions.
- **Implementation boundaries:** `app/testing/clock.py`, `tests/conftest.py`.
- **Integration points:** Pytest test harness across all 448+ test modules.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`environments-test-data-determinism`), `tests/conftest.py`.
- **Supported inputs:** Test execution parameters, fixed seed integer `seed: int = 0`.
- **Input validation rules:** Seed must be fixed constant.
- **Output schema:** Deterministic, byte-for-byte identical test execution logs across runs.
- **Configuration schema:** `TestingConfig(deterministic_seed: int = 0, frozen_time: str = "2026-10-10T12:00:00Z")`.
- **Default values:** `deterministic_seed = 0`, `frozen_time = "2026-10-10T12:00:00Z"`.
- **Dependencies:** `freezegun` / `time-machine`, Python standard library.
- **Compatibility requirements:** Compatible with all pytest plugins.
- **Authorization rules:** Internal developer test framework.
- **Data isolation rules:** Completely isolated per test function; zero cross-test state leakage.
- **Error behavior:** Test flakiness detection harness reruns failed tests 5 times to confirm genuine defect vs flakiness.
- **Fallback behavior:** Flaky tests automatically quarantined with diagnostic report.
- **Observability requirements:** Log seed and frozen timestamp in test suite header.
- **Performance limits:** Fixture setup overhead $\le 0.1\text{ ms}$ per test.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** 10 consecutive identical CI test runs produce 100% green results with zero flakiness.
- **Evaluation dataset:** All 448 project test cases in `tests/`.
- **Evaluation baseline:** Occasional timing-dependent flakiness on token rate limiter tests.
- **Required improvement threshold:** Flakiness rate = 0.000 across 100 test runs.
- **Regression limits:** Zero nondeterministic assertions permitted in codebase.
- **Completion criteria:** Flakiness audit passes in CI.

---

## FEAT-096: Mutation Score Ratcheting CI Gate
- **Objective:** Gating check in GitHub Actions enforcing that no pull request can lower DocScout's mutation testing score (currently baseline 78.4% across 278 mutants), preventing weak assertion-free tests.
- **In-scope behavior:** Executing mutation testing (`mutmut` or `cosmic-ray`) on modified code diffs; calculating mutation adequacy score; failing CI if surviving mutants are introduced or score drops below 78.4%.
- **Excluded behavior:** Running mutation testing across the entire monolithic codebase on every PR (which would take hours).
- **Implementation boundaries:** `scripts/diff_mutation.py`, `.github/workflows/ci.yml`.
- **Integration points:** Pull request quality check in GitHub Actions; `make test-mutation`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`antipatterns` ["Mutation Testing"], `formulas` ["mutation-score"]), `scripts/diff_mutation.py`.
- **Supported inputs:** Git diff against target branch, test suite execution command.
- **Input validation rules:** PR must modify at least one Python source file.
- **Output schema:** `MutationReport(mutants_generated: int, mutants_killed: int, mutants_survived: int, mutation_score: float, gate_passed: bool)`.
- **Configuration schema:** `MutationGateConfig(min_score: float = 0.784, diff_only: bool = True)`.
- **Default values:** `min_score = 0.784`, `diff_only = True`.
- **Dependencies:** `mutmut`, `pytest`.
- **Compatibility requirements:** Diff-based mutation testing to stay within 2-minute CI time budget.
- **Authorization rules:** GitHub Actions CI execution.
- **Data isolation rules:** Operates in ephemeral CI runner.
- **Error behavior:** Surviving mutant in modified diff fails CI check with annotated line diff.
- **Fallback behavior:** PR merge blocked until meaningful assertion tests are added to kill mutant.
- **Observability requirements:** Commit mutation report under `docs/verification/mutation-report.json`.
- **Performance limits:** Diff mutation testing executed in $\le 90\text{ seconds}$ in CI.
- **Resource limits:** Runner CPU utilization capped at 2 cores.
- **Acceptance criteria:** Rejects pull requests that contain assertion-free tests or untested code paths in modified lines.
- **Evaluation dataset:** 10 simulated PRs with seeded subtle logic mutations.
- **Evaluation baseline:** Baseline mutation score 78.4% across 278 mutants.
- **Required improvement threshold:** Ratchet policy: mutation score must never decrease ($\Delta \ge 0.000$).
- **Regression limits:** Gate fails if mutation score drops by even 0.1pp.
- **Completion criteria:** Passing mutation gate step in `.github/workflows/ci.yml`.

---

## FEAT-097: Differential / Patch Coverage Gating (100% Diff Coverage)
- **Objective:** Enforce 100% test coverage on modified lines in pull requests instead of tracking blunt whole-repository statement coverage, preventing coverage gaming.
- **In-scope behavior:** Analyzing `git diff` against target branch; mapping changed executable lines; asserting that every single modified line is executed and asserted in pytest; failing PR if diff coverage $< 100\%$.
- **Excluded behavior:** Demanding 100% whole-repo coverage that incentivizes low-value test bloat.
- **Implementation boundaries:** `scripts/diff_coverage.py`, `.github/workflows/ci.yml`.
- **Integration points:** CI `quality` job in GitHub Actions.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`antipatterns` ["Statement Coverage"]), `scripts/diff_coverage.py`.
- **Supported inputs:** Coverage XML report (`coverage.xml`), Git diff stream.
- **Input validation rules:** Python source lines modified in PR.
- **Output schema:** `DiffCoverageResult(lines_modified: int, lines_covered: int, diff_coverage_pct: float, uncovered_lines: list[int], passed: bool)`.
- **Configuration schema:** `DiffCoverageConfig(required_percentage: float = 100.0)`.
- **Default values:** `required_percentage = 100.0`.
- **Dependencies:** `coverage.py`, `diff-cover`.
- **Compatibility requirements:** Standard Cobertura coverage XML parsing.
- **Authorization rules:** GitHub Actions pull request gate.
- **Data isolation rules:** Ephemeral CI runner execution.
- **Error behavior:** Any uncovered executable line in git diff fails the check with annotated line references in GitHub PR comments.
- **Fallback behavior:** PR merge blocked until missing unit tests are committed.
- **Observability requirements:** Coverage summary posted as GitHub PR check annotation.
- **Performance limits:** Diff coverage calculation $\le 3.0\text{ seconds}$ in CI.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Enforces 100% test execution over all new or modified code without requiring legacy module rewrites.
- **Evaluation dataset:** 20 pull request diffs.
- **Evaluation baseline:** Whole-repo statement coverage target allowing uncovered bug additions.
- **Required improvement threshold:** 100% diff coverage strictly enforced on every PR.
- **Regression limits:** Zero exceptions for production code modules.
- **Completion criteria:** Gate passes in CI quality workflow.

---

## FEAT-098: Immutable Cryptographic Audit Trail (SLSA Level 3 Provenance)
- **Objective:** Cryptographically sign all ingested circular artifacts, vector index revisions, and evaluation reports using SHA-256 digests and OIDC-backed signing, providing court-admissible audit proof.
- **In-scope behavior:** Generating in-toto compliant provenance attestations; signing with GitHub OIDC cosign keyless infrastructure; verifying attestations at application startup; storing immutable audit log records.
- **Excluded behavior:** Storing unhashed or unsigned modifications in production database.
- **Implementation boundaries:** `scripts/provenance.py`, `app/ingest/store.py`, `migrations/0009_audit_trail.up.sql`.
- **Integration points:** CI build pipeline; document ingestion commit hook; application startup health check.
- **Source-of-truth files:** `scripts/provenance.py`, `docs/security/sbom.cdx.json`.
- **Supported inputs:** Build artifacts, database migration files, ingested circular byte arrays.
- **Input validation rules:** All signed artifacts must have verified SHA-256 digests.
- **Output schema:** `SLSAProvenanceAttestation(schema_version: str, builder: str, materials: list[ArtifactMaterial], invocation: dict, signature: str)`.
- **Configuration schema:** `ProvenanceConfig(verify_signatures_at_startup: bool = True)`.
- **Default values:** `verify_signatures_at_startup = True`.
- **Dependencies:** `cryptography`, `sigstore` / `cosign`.
- **Compatibility requirements:** Conforms to SLSA Level 3 build provenance specification.
- **Authorization rules:** Internal automated release and ingestion pipeline.
- **Data isolation rules:** Attestation signatures public; tamper-evident append-only ledger.
- **Error behavior:** If an ingested artifact's hash fails cryptographic verification, application startup halts immediately.
- **Fallback behavior:** Fail-closed startup failure on integrity violation.
- **Observability requirements:** Metric `docscout_attestations_verified_total`, startup audit log.
- **Performance limits:** Signature verification $\le 15\text{ ms}$ at startup.
- **Resource limits:** Zero runtime memory overhead.
- **Acceptance criteria:** Complete, unbroken cryptographic provenance chain from raw RBI PDF to serving vector chunk to evaluation report.
- **Evaluation dataset:** All 35 corpus documents and locked release artifacts.
- **Evaluation baseline:** Unsigned local builds susceptible to untracked manual tampering.
- **Required improvement threshold:** 100% cryptographic verification of production assets.
- **Regression limits:** Zero unverified code or data permitted into production serving.
- **Completion criteria:** Provenance attestation verified in `.github/workflows/ci.yml`.

---

## FEAT-099: OIDC-Federated Zero-Trust Identity & Enterprise RBAC
- **Objective:** Auth0 RS256 JWKS JWT authentication integrated with fine-grained role-based access control (`compliance:read`, `compliance:admin`, `audit:export`) and ephemeral workload identity.
- **In-scope behavior:** Validating JWT tokens using PyJWKClient with local key caching and rotation; extracting user scopes and tenant claims; enforcing route-level permissions; mapping identity to structlog audit contexts.
- **Excluded behavior:** Storing plain API keys or passwords in application source code.
- **Implementation boundaries:** `app/api/auth0.py`, `app/api/security.py`, `app/api/app.py`.
- **Integration points:** FastAPI dependency injection `require_authenticated_user` and `require_admin_user` across all 14 endpoints.
- **Source-of-truth files:** `app/api/auth0.py`, `app/config.py`.
- **Supported inputs:** HTTP `Authorization: Bearer <JWT>` header, `X-API-Key` header.
- **Input validation rules:** Valid RS256 signature, unexpired (`exp > now()`), issuer matches `AUTH0_ISSUER`, audience matches `AUTH0_AUDIENCE`.
- **Output schema:** `AuthenticatedUser(user_id: str, email: str, tenant_id: str, scopes: list[str], is_admin: bool)`.
- **Configuration schema:** `Auth0Config(domain: str, audience: str, issuer: str, jwks_cache_ttl_seconds: int = 3600)`.
- **Default values:** `jwks_cache_ttl_seconds = 3600`.
- **Dependencies:** `PyJWT` with cryptography backend, `httpx` for JWKS fetching.
- **Compatibility requirements:** Resolves G-1 AuthN/Z and G-MYPY-1 type safety debt.
- **Authorization rules:** Route-level dependency injection enforcing required scopes.
- **Data isolation rules:** User session claims directly constrain tenant database queries.
- **Error behavior:** Expired token returns HTTP 401 with `WWW-Authenticate: Bearer error="invalid_token"`; insufficient scope returns HTTP 403.
- **Fallback behavior:** Supports dual-mode authentication (Auth0 JWT or high-entropy API key).
- **Observability requirements:** Counter `docscout_auth_successes_total{scope}`, `docscout_auth_failures_total{reason}`.
- **Performance limits:** Token validation latency $\le 0.4\text{ ms}$ (cached JWKS).
- **Resource limits:** Memory allocation $\le 1\text{ MB}$ for JWKS key cache.
- **Acceptance criteria:** Enforces strict zero-trust RBAC across 100% of sensitive compliance and administration endpoints.
- **Evaluation dataset:** 25 authentication test cases in `tests/test_auth0.py` covering expired, malformed, and valid tokens.
- **Evaluation baseline:** Static API-key-only authentication without user identity or RBAC.
- **Required improvement threshold:** 100% test coverage and strict mypy compliance over `app/api/auth0.py`.
- **Regression limits:** Zero unauthorized access to administrative or audit export endpoints.
- **Completion criteria:** Passes `tests/test_auth0.py` and mypy strict type check.

---

## FEAT-100: High-Cardinality Telemetry & Cost-Per-Query Accounting
- **Objective:** Structured structlog logging and OpenTelemetry tracing tracking request ID, tenant ID, query complexity, embedding token cost, and cache outcome for precise enterprise cost accounting.
- **In-scope behavior:** Injecting trace and span IDs; calculating compute and model token cost per request; emitting structured JSON access logs with correlation IDs; exporting OpenTelemetry traces to collector.
- **Excluded behavior:** Logging customer search query strings or proprietary text in cleartext telemetry.
- **Implementation boundaries:** `app/observability.py`, `app/api/metrics.py`, `app/api/app.py`.
- **Integration points:** ASGI middleware in `app/api/app.py`; structlog processors.
- **Source-of-truth files:** `app/observability.py`, `app/api/metrics.py`.
- **Supported inputs:** Incoming HTTP request context, token counts, execution timings.
- **Input validation rules:** Sensitive fields (tokens, passwords, API keys) automatically redacted via `_redact_sensitive`.
- **Output schema:** Single structured JSON log line per HTTP request + OpenTelemetry OTLP trace span.
- **Configuration schema:** `TelemetryConfig(export_otlp: bool = False, cost_per_1k_tokens: float = 0.0001)`.
- **Default values:** `export_otlp = False`, `cost_per_1k_tokens = 0.0001`.
- **Dependencies:** `structlog`, `opentelemetry-api`, `opentelemetry-sdk`.
- **Compatibility requirements:** Conforms to W3C Trace Context standard (`traceparent` header).
- **Authorization rules:** Internal observability pipeline.
- **Data isolation rules:** Strictly redacts sensitive credentials and query contents.
- **Error behavior:** Logging or tracing error never interrupts primary request processing (fail-safe).
- **Fallback behavior:** Standard stdlib logging fallback.
- **Observability requirements:** Emits structured JSON logs to stdout; Prometheus RED metrics.
- **Performance limits:** Logging and tracing middleware overhead $\le 0.1\text{ ms}$ per request.
- **Resource limits:** Zero unbounded memory accumulation.
- **Acceptance criteria:** Enables finance and engineering teams to accurately audit infrastructure cost per department, user, and query type.
- **Evaluation dataset:** 1,000 synthetic multi-tenant queries.
- **Evaluation baseline:** Unstructured text logging lacking correlation IDs or cost metrics.
- **Required improvement threshold:** 100% of search requests carry correlation ID and computed cost metric.
- **Regression limits:** Zero secret leakage in structured log output.
- **Completion criteria:** Observability tests pass in `tests/test_observability.py`.
