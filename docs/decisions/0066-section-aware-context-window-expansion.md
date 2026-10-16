# ADR-0066: Section-Aware Context Window Expansion (FEAT-075)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Retrieval Architecture Guild, Legal Knowledge Engineering
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

Statutory circulars, Master Directions, and regulatory frameworks published by the Reserve Bank of India (RBI) and Securities and Exchange Board of India (SEBI) are structurally hierarchical. A single statutory section typically consists of an operative compliance mandate followed by sub-clauses, exceptions, and legal provisos (e.g., "Provided that...", "Provided further that...").

Standard chunking (even with token overlap) frequently splits operative rules from their qualifying provisos or sub-clause conditions. When a dense or lexical retriever hits a standalone proviso or penalty clause in isolation, the retrieved chunk lacks the operative rule or qualifying context. Presenting such isolated clauses to users or downstream Large Language Models risks legal misinterpretation, false-positive non-compliance alerts, and hallucinated interpretations.

FEAT-075 introduces the Section-Aware Context Window Expansion engine (`app/retrieval/section_expander.py`). When a retrieved passage represents a subsection, proviso, or specific clause, the expander queries adjacent sibling clauses within the same statutory section and stitches them into a unified, coherent context envelope while preserving the original chunk identifier as the primary citation anchor.

---

## Decision Drivers

1. **Context Completeness:** Automatically include preceding operative rules when retrieving qualifying provisos or penalty clauses (targeting Legal Context Completeness Score >= 0.94).
2. **Strict Section Boundary Isolation:** Expand exclusively within the same statutory section or regulation; strictly prevent bleeding across unrelated circular chapters or sections.
3. **Primary Citation Traceability:** Retain the original `core_chunk_id` as the primary citation anchor for provenance, verification, and audit purposes.
4. **Execution Latency Budget:** Sibling chunk fetch and stitch latency <= 2.5 ms (p95).
5. **Configurable Horizon:** Bounded sibling expansion ($1 \le \text{max\_sibling\_clauses} \le 4$, default 2).
6. **Graceful Fail-Closed Degradation:** If sibling clause lookup encounters unexpected errors or missing connections, return the core passage unexpanded without failing the query.
7. **Prometheus Observability:** Track expansions via `docscout_section_expansions_total` counter and `docscout_section_expansion_duration_seconds` histogram.
8. **Typographical Compliance:** Strict ASCII typographical compliance across all documentation and code.

---

## Considered Options

1. **Static Pre-Ingest Chunk Inflation:**
   * Create larger chunks at ingest time (e.g. 2,000+ tokens per chunk).
   * *Drawbacks:* Degrades dense embedding granularity; dilutes semantic similarity vectors; exceeds cross-encoder token ceilings (512 tokens).
2. **Naive Adjacent Offset Expansion (Window Slicing):**
   * Expand raw text by +/- N characters in the source document without checking section boundaries.
   * *Drawbacks:* Frequently bleeds across document section headings, schedules, and disparate legal chapters, corrupting legal context.
3. **Section-Aware Sibling Expansion via Clause Hierarchy (Chosen):**
   * Inspect the `clause_hierarchy`, `parent_chunk_id`, and `is_proviso` metadata of the core chunk.
   * Query database for immediately adjacent sibling clauses belonging to the same section.
   * Stitch preceding and following siblings in document sequence around the core chunk into an `ExpandedPassage`.

---

## Decision Outcome

Adopt Option 3.

### Implementation Specifics

1. **Data Model (`app/retrieval/section_expander.py`):**
   * `SiblingChunk`: Dataclass containing `chunk_id: str`, `text: str`, `char_start: int`, `char_end: int`, `clause_hierarchy: list[str]`, `is_proviso: bool`, `position: str` (`preceding` | `following`).
   * `ExpandedPassage`: Dataclass containing `core_chunk_id: str`, `expanded_text: str`, `sibling_chunks: list[SiblingChunk]`, `total_chars: int`, `preceding_count: int`, `following_count: int`, `section_title: str | None`.
2. **Expansion Engine (`app/retrieval/section_expander.py`):**
   * `SectionExpander`:
     - Input validation: validates `chunk_id` is a valid UUID, enforces $1 \le \text{max\_sibling\_clauses} \le 4$.
     - SQL query: queries sibling chunks for the same `document_id` where `char_start` is adjacent and `clause_hierarchy` matches the parent section root.
     - Sequential stitching: preserves document ordering (`[preceding...] + core + [following...]`).
     - Fail-safe fallback: returns unexpanded core passage on error.
3. **Observability (`app/api/metrics.py`):**
   * `SECTION_EXPANSIONS_TOTAL`: Counter labeled by status (`expanded`, `unexpanded`, `fallback`).
   * `SECTION_EXPANSION_DURATION_SECONDS`: Histogram measuring expansion execution duration.
4. **Configuration (`app/retrieval/types.py`):**
   * `RetrievalConfig.expand_section_context: bool = True`.
   * `RetrievalConfig.max_sibling_clauses: int = 2`.
5. **Testing (`tests/test_section_expander.py`):**
   * Unit tests covering basic expansion, proviso context preservation, section boundary isolation, input validation, DB error fallback, and latency SLA <= 2.5 ms.

---

## Consequences

* Positive: Resolves standalone proviso ambiguity by ensuring operative conditions accompany qualifying clauses.
* Positive: Keeps embeddings granular while supplying rich legal context to the prompt generation layer.
* Positive: Preserves exact citation anchors so auditability and verification remain 100% faithful.
* Neutral: Database query overhead of ~1-2 ms per expanded passage, well within the 2.5 ms p95 SLA.
