# ADR-0065: Arm-Anchored Fusion with Provenance Guarantees (FEAT-074)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Retrieval Architecture Guild, Compliance & Search Team
* **Informed:** Core Platform Engineers, Product Operations
* **Amends/Extends:** ADR-0007 (Reserve a seat for each arm's top hit)

---

## Context and Problem Statement

ADR-0007 established the principle of reserving a seat for each retrieval arm's top-1 hit to resolve the failure mode where rank-only reciprocal rank fusion (RRF) buried decisive lexical hits (such as gold item g-038) under consensus candidates. In regulatory compliance retrieval, questions frequently turn on exact alphanumeric statutory circular identifiers (e.g., "DOR.CRE.REC.No. 60/08.12.001/2023-24"), specific dates, or statutory clauses where the lexical arm is highly confident while dense semantic embeddings encounter noise.

However, prior to FEAT-074:
1. When cross-encoder reranking (FEAT-071), graph degree centrality boosting (FEAT-009), or regulatory authority weighting (FEAT-045) were enabled, post-rerank candidate sorting could score an arm leader below the `k_final` cutoff without explicit guarantees or provenance tracking.
2. Downstream consumers, UI clients, and the LLM generation layer had no structured provenance metadata to distinguish between chunks that survived naturally on consensus score and chunks that were explicitly anchored via seat reservation.
3. Observability lacked a dedicated Prometheus counter to measure how frequently arm leaders required anchoring in production queries across arms (`dense`, `lexical`, `graph`).

FEAT-074 formalizes and expands ADR-0007 into an Enterprise-grade arm-anchored fusion engine with end-to-end provenance guarantees, post-reranking retention invariants, and observability.

---

## Decision Drivers

1. **100% Retention of Exact Statutory Circular IDs:** Guarantee that exact statutory circular number queries retain Recall@1 = 1.000 regardless of dense semantic noise or cross-encoder scoring variance.
2. **Post-Rerank Seat Reservation:** Ensure arm leaders injected into the reranker candidate pool are preserved in the final top-k returned set even if model logits rank them below the cutoff.
3. **Structured Provenance Tracking:** Equip `Retrieved` (in `app/retrieval/types.py`) and `Passage` (in `app/api/models.py`) with explicit provenance flags: `is_arm_anchor: bool` and `anchored_arm: str | None`.
4. **Configuration Consistency:** Provide `RetrievalConfig.anchor_arm_leaders: bool = True` while maintaining seamless backward compatibility with `RetrievalConfig.anchor_arm_top1`.
5. **Observability:** Track arm anchor events via Prometheus counter `docscout_arm_leaders_anchored_total` with `arm_name` label.
6. **Execution Latency Budget:** Pure Python list surgery with execution overhead <= 0.05 ms.
7. **Typographical Compliance:** Strict ASCII typographical compliance with zero UTF-8 em-dashes.

---

## Considered Options

1. **Status Quo (Pre-Rerank RRF-Only Anchor Without Provenance):**
   * *Drawbacks:* Lacks post-rerank seat reservation; no provenance flags on `Retrieved`/`Passage`; zero Prometheus metric tracking for anchoring frequency.
2. **Score-Fabrication / Top-1 Forcing:**
   * Force low-scoring arm leaders unconditionally into Rank 1 by synthesizing artificial scores.
   * *Drawbacks:* Discarded by ADR-0007; fabricating scores corrupts calibration, overrides true consensus ranking, and destroys reproducibility.
3. **Arm-Anchored Fusion with Provenance Guarantees & Tail Eviction (Chosen):**
   * Identify top-1 candidate from each active retrieval arm (`dense`, `lexical`, and `graph`).
   * Inject arm leaders into candidate pools and check whether they survive in the final top-k set after all scoring and reranking passes.
   * If any arm leader fell below the top-k cutoff, evict candidates from the tail of the list to reserve a seat, preserving the leader with its genuine score and arm ranks.
   * Mark rescued items with `is_arm_anchor=True` and `anchored_arm=arm_name`.
   * Increment Prometheus counter `docscout_arm_leaders_anchored_total{arm_name}`.

---

## Decision Outcome

Adopt Option 3.

### Implementation Specifics

1. **Metrics (`app/api/metrics.py`):**
   * Define `ARM_LEADERS_ANCHORED_TOTAL = Counter("docscout_arm_leaders_anchored_total", "Total times an arm top-1 leader was anchored into final results", ["arm_name"])`.
2. **Value Types (`app/retrieval/types.py`):**
   * Update `Retrieved` with `is_arm_anchor: bool = False` and `anchored_arm: str | None = None`.
   * Update `RetrievalConfig` with `anchor_arm_leaders: bool | None = None`, synchronizing with `anchor_arm_top1` in `__post_init__` and serializing both in `as_dict()`.
3. **API Models (`app/api/models.py`):**
   * Update `Passage` with `is_arm_anchor: bool = False` and `anchored_arm: str | None = None`.
4. **Search and Anchoring Logic (`app/retrieval/search.py`):**
   * Enhance `_anchor_arm_leaders` to validate inputs (`k >= 1`, non-empty candidates), perform fast list surgery with tail eviction, record metric increments for missing arm leaders, and return provenance mappings.
   * Support both tuple representations (`top: list[tuple[str, float, dict[str, int]]]`) and `Candidate` objects (`list[Candidate]`).
   * Plumb provenance flags into `Retrieved` and `Passage` instantiations.
5. **Testing (`tests/test_arm_anchoring.py`):**
   * Unit tests verifying lexical leader preservation against dense noise, dense leader preservation against BM25 noise, graph arm leader anchoring, post-reranking retention, provenance flag assignment, Prometheus counter increments, input validation, and execution latency <= 0.05 ms.

---

## Consequences

* Positive: Exact statutory circular IDs are permanently protected against being lost during retrieval, reranking, and boosting phases.
* Positive: Downstream generation prompts and UI audit views clearly indicate which passages were secured via arm-anchoring guarantees.
* Positive: Zero extra memory footprint and sub-0.05 ms execution overhead.
* Neutral: When an arm leader is missing from the top-k set, the lowest-ranking candidate at index `k-1` is displaced to make room.
