# ADR-0080: Real-Time Hallucination Telemetry & Prometheus Alarms (FEAT-089)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** SRE Team, AI Assurance Guild, Compliance Operations
* **Informed:** Core Platform Engineers, Operations

---

## Context and Problem Statement

In production regulatory retrieval and compliance evaluation, offline evaluation runs (e.g. batch gold set benchmarks) provide retrospective quality gates. However, in live production environments, operational serving traffic can encounter out-of-distribution queries, upstream document changes, or model degradation that lead to sudden spikes in ungrounded or hallucinated claims.

Without real-time observability into operational claim support ratios and abstention events, SREs and compliance officers only discover hallucination issues hours or days after serving ungrounded information to regulated financial institutions.

DocScout requires real-time, low-overhead Prometheus telemetry that tracks claim support ratios over a rolling 5-minute window, exposes standard OpenMetrics exposition at `GET /metrics`, and raises instantaneous alarms (threshold < 0.98) to alert SREs and compliance officers via PagerDuty/Slack before hallucination cascades impact customer trust.

---

## Decision Drivers

1. **Sub-Second Operational Observability:**
   Expose real-time Prometheus gauges and counters for:
   - `docscout_claim_support_ratio`: Rolling ratio of supported claims to total claims across served responses.
   - `docscout_abstention_events_total`: Cumulative counter of selective refusal and abstention gate events partitioned by confidence level (`LOW`, `MEDIUM`, `HIGH`).
   - `docscout_unsupported_claim_alerts`: Binary alert gauge (1 = firing, 0 = healthy) for SRE alert managers.
   - `docscout_unsupported_claim_alerts_total`: Cumulative counter of alarm transitions.
2. **Deterministic Alarm Gating (< 0.98 Threshold):**
   Evaluate sliding 5-minute (300-second) window. If supported claim ratio drops below 0.98 under production load, immediately fire critical alarm state (100% detection rate on seeded hallucination spikes).
3. **Ultra-Low Serving Latency Overhead:**
   Metric recording and rolling window calculation must execute in <= 0.02 ms (20 microseconds) per request, maintaining zero impact on core retrieval SLA (p95 < 3s).
4. **Bounded Memory Allocation:**
   Sliding window must use bounded memory (<= 2 MB) using fixed-capacity deque ring buffers.
5. **Fail-Open Invariant & Confidentiality Protection:**
   Metric recording must be fail-open (exceptions are logged and never fail search requests). Zero confidential query text or tenant identifiers in metric labels to preserve strict data isolation.
6. **Typographical Invariant:** Strict ASCII typographical compliance across all documentation and code.

---

## Decision Outcome

We implement:
- `app/config.py`:
  - `MetricsConfig` dataclass with `enable_ai_assurance_metrics: bool = True`, `hallucination_alarm_threshold: float = 0.98`, and `hallucination_alarm_window_seconds: float = 300.0`.
  - `metrics_config()` loader reading `DOCSCOUT_ENABLE_AI_ASSURANCE_METRICS` and `DOCSCOUT_HALLUCINATION_ALARM_THRESHOLD`.
- `app/api/metrics.py`:
  - Expose `CLAIM_SUPPORT_RATIO`, `UNSUPPORTED_CLAIM_ALERTS`, `UNSUPPORTED_CLAIM_ALERTS_TOTAL`, `TOTAL_CLAIMS_EVALUATED_TOTAL`.
  - `HallucinationTelemetryTracker`: Thread-safe sliding window ring buffer computing rolling claim support ratios, updating gauges, and transitioning alert states.
  - Fail-open public interface `record_claim_telemetry(supported_claims, total_claims)`.
  - Default initialization of gauges and labels ensuring immediate visibility on cold boot scraping.
- `app/api/models.py`:
  - `ClaimTelemetryRequest` and `ClaimTelemetryResponse` schemas.
- `app/api/app.py`:
  - `POST /v1/telemetry/claims` operational endpoint for reporting claim evaluation outcomes.
  - Wire `metrics.record_claim_telemetry()` into `/v1/search` post-generation faithfulness verification.
- `app/evals/faithfulness.py`:
  - Automatic feed from `FaithfulnessEvaluator.evaluate()` into `metrics.record_claim_telemetry()`.
- `tests/test_metrics.py`:
  - Full end-to-end verification covering Prometheus exposition, alarm trigger on 5% seeded unsupported claims (< 0.98), alarm recovery, API endpoint, sub-0.02ms latency benchmark, and fail-open resilience.

---

## Validation and Testing

1. Verified `GET /metrics` exports `docscout_claim_support_ratio`, `docscout_abstention_events_total`, and `docscout_unsupported_claim_alerts`.
2. Verified simulated production load with 5% seeded unsupported claims drives claim support ratio to 0.95 and fires 100% of alarms.
3. Verified subsequent healthy traffic restores claim support ratio >= 0.98 and automatically clears alarm state to 0.0.
4. Benchmarked 1,000 telemetry updates running in < 0.02 ms per update.
5. Verified fail-open error handling and absence of sensitive query strings in labels.
