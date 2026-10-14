# ADR-0057: Annexure, Schedule & FAQ Relational Association (FEAT-066)

* **Status:** Accepted
* **Date:** 2026-10-14
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Document Intelligence Working Group, Search & Retrieval Team
* **Informed:** Product Management, Enterprise Compliance Architecture

---

## Context and Problem Statement

Indian financial regulatory documents (RBI Master Directions, SEBI Master Circulars, MCA Rules) follow a strict structural hierarchy: high-level statutory obligations and prohibitions reside in the main circular body, while substantive execution instructions, standard reporting forms, capital computation procedures, and interpretive clarifications reside in subsidiary annexures, schedules, appendices, and Frequently Asked Questions (FAQs).

Prior to FEAT-066, chunking and embedding pipelines processed document bodies as disconnected linear sequences. When an enterprise compliance officer queried a directive in the main circular, relevant procedural guidelines and reporting mandates located within "Annexure I" or "Schedule A" failed to surface in the top retrieval candidates because lexical and dense embedding scores diluted cross-section topical relevance. Conversely, merging massive 50-page technical annexures into single monolithic parent chunks destroyed retrieval precision and violated the 512-token budget invariant (FEAT-061).

The system requires an automated relational hierarchy parser that detects subsidiary annexures, schedules, appendices, and FAQs, establishes persistent foreign-key relational links in the database, and provides cross-section retrieval expansion without disrupting primary circular ranking.

---

## Decision Drivers

1. **Substantive Procedural Guidance:** Ensure procedural rules in technical annexures are discoverable alongside primary obligations (target: cross-section retrieval recall +18 pp).
2. **Token Economy and Precision:** Avoid monolithic chunk merging; keep retrievable chunks atomic and structurally bound.
3. **High-Performance Ingestion:** Execute relational linking in under 1.0 ms per document during ingestion.
4. **Relational Traceability:** Maintain persistent parent-child relations (`document_sections` and `section_relationships`) indexed per document version.
5. **Zero Em-Dash Policy:** Strict ASCII compliance across all documentation and codebase artifacts.

---

## Considered Options

1. **Monolithic Ingestion Merging:** Concatenate annexure clauses directly into main directive parent chunks.
   * *Drawback:* Catastrophically violates token budgets (exceeding 512 tokens), introduces noisy context, and degrades primary BM25 scoring.
2. **Flat Unlinked Indexing (Status Quo):** Index annexures as generic disconnected chunks without relational knowledge.
   * *Drawback:* Isolated retrieval misses critical compliance forms and computational templates located in annexures.
3. **Structured Relational Association & Expansion (Chosen):** Parse structural section headers during ingestion, persist parent-child links in relational tables, and provide relational graph traversal for retrieval candidate expansion.

---

## Decision Outcome

Adopt Option 3. Implement `AnnexureLinker` in `app/ingest/annexure_linker.py` supported by PostgreSQL migration 0049 (`document_sections` and `section_relationships`).

### Architectural Highlights

1. **Structural Pattern Detection:**
   * **Annexures:** Regex capturing `Annexure [0-9IVXLCDM]+|[A-Z]`, `Annex`, and Roman/alphabetic numbering.
   * **Schedules:** Regex capturing `Schedule [0-9IVXLCDM]+|[A-Z]`.
   * **FAQs:** Regex capturing `Frequently Asked Questions`, `FAQs`, `Clarificatory FAQs`.
   * **Appendices:** Regex capturing `Appendix [0-9IVXLCDM]+|[A-Z]`.
2. **Relational Link Model:**
   * Every document establishes a root `MAIN` section spanning the primary regulatory body.
   * Each detected subsidiary section establishes a directed `SectionRelationship` (`parent_section_id -> child_section_id`) with typed association (`ANNEXURE`, `SCHEDULE`, `FAQ`, `APPENDIX`).
3. **Relational Search Expansion:**
   * When top retrieval hits reside in a parent directive, `AnnexureLinker` expands candidates by fetching relational child annexures, guaranteeing procedural context reaches synthesized answers.
4. **Metrics and Observability:**
   * Prometheus metric `docscout_annexures_linked_total{type}` monitors linked components across all regulatory corpora.

---

## Consequences

### Positive
* **Complete Compliance Picture:** Compliance officers querying circular clauses immediately receive referenced reporting schedules and procedural steps.
* **Strict Invariant Adherence:** Does not alter chunk character offsets; zero interference with citation provenance (FEAT-063).
* **Minimal Ingestion Overhead:** Deterministic regex parsing executes in < 0.5 ms per document, easily beating the 1.0 ms SLA.

### Negative
* Requires additional database queries during hierarchical retrieval expansion, mitigated by composite indices on `(document_id, version_id)` and `parent_section_id`.
