# ADR-0064: Token-Budget Dynamic Context Packing (FEAT-073)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Retrieval Architecture Guild, Generation & LLM Team
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

Downstream Large Language Models operate under strict input token budgets. Prior to FEAT-073, DocScout presented evidence as a fixed top-k candidate list (e.g., top-5 or top-10 chunks). Because regulatory circular chunks vary significantly in length (ranging from short single-proviso amendments to lengthy multi-paragraph regulatory schedules), a static top-k strategy results in volatile token lengths: short chunks utilize as little as 35% of the allocated context budget, wasting valuable attention capacity, whereas clusters of long chunks exceed model prompt ceilings, causing crude runtime truncation or API errors.

FEAT-073 introduces a Token-Budget Dynamic Context Packing engine (`app/retrieval/context_packer.py`) that greedily packs retrieved passages to reach a targeted 95% token budget ceiling. Crucially, when packing a boundary chunk that would otherwise breach the token ceiling, the engine performs sentence-boundary trimming, preserving complete statutory sentences and discarding dangling sentence fragments.

---

## Decision Drivers

1. **Targeted Context Budget Utilization:** Fill prompt token windows to a targeted 95% ceiling (with >= 90% utilization achieved across variable budgets: 1024, 2048, 4096 tokens).
2. **Grammatical & Regulatory Sentence Integrity:** Avoid arbitrary token slicing across words or mid-clause phrases; trim boundary chunks strictly at terminal punctuation marks (`. `, `.\n`, `! `, `? `, `; `).
3. **Execution Latency Budget:** Maintain fast in-memory execution with p95 packing latency <= 0.8 ms using cached fast tokenization.
4. **Deterministic Ranking Retention:** Process and pack passages in strictly descending relevance order, keeping the most critical statutory provisions in context.
5. **Fail-Closed Fallback:** If unexpected parsing or tokenization exceptions arise, fall back gracefully to returning the top-3 untrimmed passages without request failure.
6. **Prometheus Observability:** Track token utilization via `docscout_context_token_utilization_ratio` gauge and packing runs via `docscout_context_packs_completed_total` counter.
7. **Typographical Compliance:** Strict ASCII typographical compliance with zero UTF-8 em-dashes.

---

## Considered Options

1. **Fixed Top-K Candidate Return (Status Quo Baseline):**
   * Return a fixed count of chunks (e.g. k=5) regardless of token volume.
   * *Drawbacks:* High token variance; either wastes up to 60% of LLM prompt budget or spills over context limits.
2. **Hard Token Truncation at Boundary:**
   * Cut off characters or tokens abruptly once the token count reaches max_tokens.
   * *Drawbacks:* Severely corrupts statutory clauses mid-sentence, introducing dangerous legal hallucinations or dangling clauses.
3. **Dynamic Token-Budget Packing with Sentence-Boundary Trimming (Chosen):**
   * Accumulate passages in relevance order until the target utilization ceiling is reached.
   * If the last chunk overflows the budget, trim it back to the last complete sentence boundary.
   * Discard overflow chunks beyond the budget ceiling.

---

## Decision Outcome

Adopt Option 3.

Implement:
1. `app/api/metrics.py`:
   * `CONTEXT_TOKEN_UTILIZATION_RATIO`: Gauge recording `total_tokens / max_tokens`.
   * `CONTEXT_PACKS_COMPLETED_TOTAL`: Counter labeled by status (`success`, `fallback`).
2. `app/retrieval/types.py`:
   * `PackedContext` dataclass: `packed_passages: list[Any]`, `total_tokens: int`, `utilization_ratio: float`, `truncated_boundary_chunk: bool`.
   * `ContextPackerConfig` dataclass: `max_tokens: int = 2048`, `target_utilization: float = 0.95`, `sentence_boundary_trim: bool = True`.
3. `app/retrieval/context_packer.py`:
   * `ContextPacker`:
     - Token counting via fast HuggingFace tokenizer or fallback character ratio.
     - `trim_to_sentence_boundary()` to preserve complete statutory clauses.
     - Greedy dynamic packing enforcing ceiling `int(max_tokens * target_utilization)`.
     - Fallback on error returning top-3 untrimmed passages with status logging.
4. `tests/test_context_packer.py`:
   * Comprehensive unit tests validating strict token ceiling compliance, sentence boundary integrity, >=90% utilization across 1024/2048/4096 budgets, p95 latency <= 0.8 ms, and metric emissions.

---

## Consequences

* Positive: Eliminates token budget waste and context spillover across diverse regulatory circular structures.
* Positive: Protects statutory interpretation integrity by prohibiting broken mid-sentence text fragments.
* Positive: Fast execution (sub-millisecond) ensures zero degradation of retrieval pipeline SLAs.
* Neutral: Some lower-ranking peripheral chunks are dropped when the primary high-scoring evidence exhausts the budget ceiling.
