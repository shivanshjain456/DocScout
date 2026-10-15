# ADR-0063: Lost-in-the-Middle Context Reordering (FEAT-072)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Retrieval Architecture Guild, AI Assurance Team
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

Downstream Large Language Models (LLMs) and transformer-based generation pipelines exhibit substantial attention degradation when relevant evidence is situated in the middle of long input contexts, a phenomenon empirically characterized as the "lost-in-the-middle" effect (Liu et al., 2023). When DocScout retrieves multi-passage evidence across complex circulars, presenting chunks in monotonic descending relevance order places the lowest-scoring evidence at the prompt tail, but buries moderately high-scoring candidates (e.g., ranks 2 through 5) directly in the middle of the context window where LLM retrieval accuracy and claim extraction recall degrade by up to 22%.

FEAT-072 introduces a deterministic Lost-in-the-Middle Context Reordering engine (`app/retrieval/context_reorder.py`) that restructures retrieved candidate passages into an alternating boundary distribution (U-shaped relevance profile) prior to generation or presentation, ensuring that the highest-ranking statutory evidence is positioned at the attention boundaries (the prompt start and end) while preserving chunk integrity, provenance markers, and ranking scores.

---

## Decision Drivers

1. **Downstream Retrieval and Extraction Utilization:** Maximize transformer attention utilization by placing prime evidence at the start and end of the context window, improving downstream statutory claim extraction recall by >= 8.5 pp.
2. **Deterministic Alternating Boundary Placement:** Systematically place Rank 1 at index 0, Rank 2 at index N-1, Rank 3 at index 1, Rank 4 at index N-2, and so forth, creating a balanced U-shaped relevance curve.
3. **Immutability and Provenance Preservation:** Maintain strictly monotonic preservation of chunk IDs, text bytes, citation offsets, and underlying retrieval relevance scores without mutation or loss.
4. **Positional Presentation Metadata:** Record `presentation_rank` (1-indexed sequence position 1..N) while retaining original retrieval `rank` and score attributes.
5. **Negligible Latency Overhead:** Enforce pure in-memory standard library list manipulation with execution latency <= 0.05 ms for 10 passages.
6. **Graceful Fail-Safe Fallback:** If unexpected exceptions occur during reordering, fall back cleanly to standard descending score order without interrupting search availability.
7. **Configurability and Observability:** Provide `RetrievalConfig.enable_lost_in_middle_reordering` (default True) and log structured search metadata when reordering is applied.
8. **Typographical Compliance:** Strict ASCII typographical compliance with zero UTF-8 em-dashes across all files.

---

## Considered Options

1. **Monolithic Descending Order (Status Quo Baseline):**
   * Leave retrieved passages ordered strictly by score descending (1, 2, 3, ..., N).
   * *Drawbacks:* Middle-tier passages (ranks 2-5) suffer from transformer attention degradation, reducing claim synthesis accuracy.
2. **Reverse Ascending Order:**
   * Place least relevant items first and most relevant items last.
   * *Drawbacks:* Truncation risk at prompt start, violates user expectations in direct presentation modes.
3. **Alternating Boundary Reordering (U-Shaped Distribution, Chosen):**
   * Distribute sorted candidates alternately between left and right boundary pointers.
   * Update `presentation_rank` metadata while preserving original `rank` and `score`.
   * Fast, deterministic, zero external dependencies, <= 0.05 ms overhead.

---

## Decision Outcome

Adopt Option 3.

Implement:
1. `app/retrieval/types.py`:
   * Extend `RetrievalConfig` with `enable_lost_in_middle_reordering: bool = True`.
   * Add `"enable_lost_in_middle_reordering": self.enable_lost_in_middle_reordering` to `as_dict()`.
   * Add `presentation_rank: int | None = None` to `Retrieved`.
2. `app/api/models.py`:
   * Add `presentation_rank: int | None = None` to `Passage`.
3. `app/retrieval/context_reorder.py`:
   * Implement `reorder_context(passages: Sequence[T]) -> list[T]`.
   * Handle edge cases (empty list, 1 or 2 items) as no-op identity transformations.
   * Distribute items: Rank 1 at index 0, Rank 2 at index N-1, Rank 3 at index 1, Rank 4 at index N-2, etc.
   * Attach `presentation_rank` (1-indexed) using non-mutating copy / replace semantics.
   * Enforce fail-safe exception handling returning original ordering on failure.
4. `app/retrieval/search.py`:
   * Apply `reorder_context` in `Retriever.retrieve()` immediately before returning results if `config.enable_lost_in_middle_reordering` is active.
   * Log `context_reordering_applied` with structured metadata.
5. `tests/test_context_reorder.py`:
   * Comprehensive unit tests covering alternating boundary distribution, edge cases (0, 1, 2 items), provenance preservation, latency benchmark (<= 0.05 ms), and retriever integration.

---

## Consequences

* Positive: Counteracts transformer attention decay, improving downstream LLM answer faithfulness and citation accuracy.
* Positive: Zero disruption to score values, original ranks, or chunk offsets.
* Positive: Negligible latency impact (<0.01 ms typical on CPU).
* Neutral: API and UI consumers inspecting results in list order will observe the U-shaped presentation sequence with `presentation_rank` indicating display sequence and `rank` indicating original relevance rank.
