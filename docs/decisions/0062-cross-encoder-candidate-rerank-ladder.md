# ADR-0062: Cross-Encoder Candidate Rerank Ladder (FEAT-071)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Retrieval Architecture Guild, Enterprise SRE Team
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

DocScout's hybrid reciprocal rank fusion (RRF) pipeline combines lexical BM25 and dense bi-encoder embeddings to achieve complete evidence recall at depth 10 across the RBI and SEBI statutory corpus (ADR-0006, ADR-0007). However, bi-encoder embeddings encode queries and statutory passages independently, preventing deep cross-term attention. This limits rank-1 precision and nDCG when resolving complex statutory clauses, negative exemptions, and proviso qualifications.

Cross-encoder models (e.g., 6-layer `ms-marco-MiniLM-L-6-v2`) jointly attend across query and passage tokens in a single forward pass, providing high discriminative power. However, as documented in ADR-0009, unconstrained cross-encoder scoring can introduce prohibitive latency spikes (>2.5 seconds at top-20 on 2 vCPU environments) and risks displacing evidence chunks if pool sizes are unbounded.

FEAT-071 introduces a production-hardened Cross-Encoder Candidate Rerank Ladder that bounds candidate pools, enforces batched inference, integrates a fail-closed 40 ms timeout circuit breaker, and preserves deterministic fallback ordering without risking retrieval availability.

---

## Decision Drivers

1. **Precision & nDCG Headroom:** Improve precision@1 and nDCG@5 on complex regulatory queries through joint cross-attention over fused candidates.
2. **Strict Latency Budget & Bounded Execution:** Clamp candidate pool size to a maximum of 64 items (default 50) and score in batches of 16 to maintain sub-40 ms inference latency on multi-core CPU.
3. **Fail-Closed Circuit Breaker:** Enforce an immutable 40 ms timeout circuit breaker. If inference exceeds the latency budget or the model encounters a runtime exception, the circuit breaker trips and gracefully returns the pre-rerank RRF candidate order without query failure.
4. **Arm-Leader Preservation:** Retain ADR-0007 invariants by guaranteeing that each retrieval arm's top hit is included in the candidate pool.
5. **Deterministic Ordering:** Break score ties using pre-rerank index and chunk ID, ensuring 100% byte-identical reproducibility across runs.
6. **Observability:** Track rerank latency via `docscout_rerank_duration_seconds` and circuit breaker trips via `docscout_rerank_circuit_breaker_trips_total`.
7. **Typographical Compliance:** Strict ASCII typographical compliance across all documentation and code.

---

## Considered Options

1. **Always-On Heavy Cross-Encoder (12-Layer / Large):**
   * Deploy larger 12-layer or 24-layer cross-encoders for all queries.
   * *Drawbacks:* Latency per pair exceeds 30 ms, causing p95 retrieval latency to violate the 50 ms budget by 5x-10x on CPU.
2. **Unconstrained CPU Reranker Without Circuit Breaker (ADR-0009 Baseline):**
   * Run cross-encoder over variable pool sizes without strict timeout guarding.
   * *Drawbacks:* Susceptible to CPU starvation, tail latency blowouts, and query drops during traffic spikes.
3. **Latency-Budgeted Candidate Rerank Ladder with 40 ms Circuit Breaker (Chosen):**
   * Pool clamped to min(k, 64) fused candidates with arm leaders unioned.
   * Batched CPU inference with batch size 16 and max token length 512.
   * Thread-isolated 40 ms timeout circuit breaker with graceful pre-rerank fallback.
   * Full Prometheus observability tracking duration and trip counts.

---

## Decision Outcome

Adopt Option 3.

Implement:
1. `app/api/metrics.py`:
   * `RERANK_DURATION_SECONDS`: Prometheus histogram with buckets from 5 ms to 100 ms.
   * `RERANK_CIRCUIT_BREAKER_TRIPS_TOTAL`: Prometheus counter tracking circuit breaker activations.
2. `app/retrieval/types.py`:
   * Extend `RetrievalConfig` with `rerank_batch_size: int = 16`, `rerank_timeout_ms: int = 40`, and clamp `rerank_top_n` to a maximum ceiling of 64.
3. `app/retrieval/rerank.py`:
   * Implement `CrossEncoderReranker.order()` with `concurrent.futures` timeout execution.
   * On timeout (>40 ms) or model failure, trip circuit breaker, increment metric, log warning with correlation ID, and return pre-rerank candidate ordering.
   * Enforce deterministic tie-breaking on `(-score, original_index, chunk_id)`.
   * Input validation: clamp passage texts to 512 tokens / max length, handle empty query or candidates gracefully.
4. `app/retrieval/search.py`:
   * Ensure `Retriever._rerank()` clamps pool to 64 candidates, unions arm leaders, passes batch size and timeout from config, and seamlessly applies reordered candidates.
5. `tests/test_rerank.py`:
   * Unit tests for pool clamping, timeout circuit breaker trips, model failure fallbacks, Prometheus metrics, and deterministic tie-breaking.

---

## Consequences

* Positive: Enhances statutory query ranking precision with joint cross-attention while strictly capping latency risk.
* Positive: Zero query failure risk due to automated fail-closed circuit breaker fallback to RRF fusion.
* Positive: High observability into reranking duration and circuit breaker health.
* Neutral: CPU compute remains bounded at <= 64 candidate pairs per query.
