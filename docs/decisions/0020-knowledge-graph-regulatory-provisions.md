# ADR-0020: Lightweight Knowledge Graph over Regulatory Provisions

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** Principal Engineer
- **Related:** ADR-0006 (hybrid retrieval), ADR-0012 (corpus and gold scale), ADR-0019 (retrieval-port adapter)

## Context

With the expansion of the corpus to 35 documents and 425 gold items (v2.0.0), retrieval evaluation revealed a distinct **failing query class**: multi-hop cross-regulatory queries.
Specifically, there are 12 multi-hop items in `evals/gold/v1/gold.jsonl` (e.g., questions asking how recent Master Directions amend older circulars, how Digital Lending cooling-off requirements interact with Compromise Settlement guidelines, or how SEBI LODR Regulation 30 disclosure timelines apply across related circulars).

Under standard single-pass hybrid retrieval (`dense-only`, `bm25-only`, or `hybrid-rrf`), multi-hop items exhibited lower retrieval fidelity (MRR ~0.55–0.65) compared to direct extractive queries (>0.85). Single-pass retrieval retrieves top-$k$ chunks based solely on lexical or semantic similarity to the aggregate prompt, often returning chunks from only one of the circulars while missing the companion circular or amendment target necessary for complete multi-aspect compliance answers.

Indian financial regulations (RBI master directions, SEBI circulars) possess explicit structural relationships:
1. Provisions cite statutory authority (e.g. Section 35A of the Banking Regulation Act, 1949, RBI Act, 1934, FEMA 1999).
2. New circulars explicitly amend, supersede, or implement previous frameworks using structured phrasing (e.g., "in partial modification of circular...", "amended as follows", "powers conferred by...").
3. Numbered clauses (`§1.`, `2.`, `(a)`, `(i)`) define granular regulatory mandates.

However, complex graph frameworks (like GraphRAG or LightRAG) introduce massive operational overhead, unpredictable LLM entity extraction costs, and hallucinations.

## Decision

We will implement a **minimal, grounded entity-and-relation knowledge graph over regulatory provisions** and a **graph-assisted retriever (`graph-hybrid`)** for cross-document multi-hop resolution:

1. **Grounded Schema (`migrations/0007_knowledge_graph`):**
   - `graph_nodes`: Stores document, section, and provision nodes with required foreign keys to `documents(document_id)` and explicit character offsets (`char_start`, `char_end`) within the document text. Types: `document`, `section`, `provision`, `statute`.
   - `graph_edges`: Stores directed relationships between entities (`cites`, `amends`, `supersedes`, `implements`, `references`).
   - Every edge references exact source/target entities and an optional anchor `chunk_id` with `evidence_text` and `char_start`/`char_end` spans. No ungrounded LLM hallucinated edges exist.

2. **Deterministic Span Extraction (`app/ingest/graph_extractor.py`):**
   - High-fidelity regex and structural parsers extract numbered provisions, statutory citations, and action verbs (`amends`, `supersedes`, `implements`).
   - Provision nodes are anchored to physical chunks via character offset overlap.
   - Cross-circular thematic and regulatory reference links are established transactionally during corpus ingestion.

3. **Graph-Assisted Retrieval (`app/retrieval/graph.py` & `app/retrieval/search.py`):**
   - Mode `graph-hybrid`: Executes standard hybrid candidate retrieval (dense + BM25) to identify high-confidence seed chunks.
   - If seed chunks match graph nodes, bounded 1-hop traversal traverses `amends`, `supersedes`, `cites`, and `references` edges to fetch connected regulatory provisions across documents.
   - Graph neighbors are merged into the candidate set with graph proximity scores and fused via reciprocal rank fusion (RRF).
   - **Deterministic Fallback:** If graph traversal finds 0 connected neighbors or fails, retrieval cleanly falls back to standard `hybrid-rrf` with 0 metric regression.

4. **Integration with Benchmarks & Evals:**
   - Added `GRAPH_HYBRID_CONFIG` to `BASELINE_CONFIGS` in `app/evals/runner.py`.
   - Unit and integration tests in `tests/test_knowledge_graph.py` verify schema constraints, grounded spans, traversal determinism, and multi-hop chunk resolution.

## Consequences

### Positive
- **Multi-Hop Recall:** Queries requiring cross-document joins (such as digital lending guidelines and companion circulars) retrieve chunks from both documents via direct entity edges.
- **Strict Grounding:** Every node and edge is linked to exact character spans in the ingested source texts. Invariant S-2 and FR-7 character fidelity are fully preserved.
- **Zero Hallucination / Zero Token Cost:** Graph extraction during ingestion runs deterministically via compiled patterns without expensive or non-deterministic LLM extraction calls.
- **Fail-Safe Retrieval:** Fallback to standard hybrid RRF ensures zero degradation on extractive single-hop queries.

### Tradeoffs & Maintenance
- Migration `0007_knowledge_graph` adds two PostgreSQL tables (`graph_nodes`, `graph_edges`) with indices.
- Ingestion pipeline runs graph extraction and link population upon completion, adding ~200ms to corpus ingestion.

## Rejected alternatives

### Full LightRAG / Dual-Level Community Summarization
- **What it is:** LLM-based entity extraction followed by Leiden community clustering and hierarchical graph summarization (LightRAG / MS GraphRAG).
- **Why it was plausible:** Highly publicized in 2024–2025 research benchmarks for global summarization across unstructured corpora.
- **Why rejected:**
  1. Excessive cost and latency: requires thousands of LLM calls during ingestion to extract ad-hoc entities and generate community summaries.
  2. Loss of provenance: LLM-generated community summaries cannot be cited with exact character spans (`char_start`/`char_end`), violating DocScout invariant FR-7.
  3. Premature complexity: Regulatory documents already possess clear statutory citations and numbered provision structures that are parsed deterministically.
- **Revisit condition:** Only if the corpus expands to tens of thousands of heterogeneous documents where manual/patterned provision extraction has low recall and an offline batch summarization pipeline is cost-justified.

### External Graph Database (Neo4j, AWS Neptune)
- **What it is:** Introducing Neo4j alongside PostgreSQL for Cypher graph queries.
- **Why it was plausible:** Dedicated graph query language and traversal engine.
- **Why rejected:**
  1. Violates the architectural discipline of "single pgvector stack" (Principle §6).
  2. Introduces distributed transaction overhead, additional Docker services, separate authentication/backup runbooks, and sync failure modes.
  3. Relational recursive/indexed joins in PostgreSQL over ~100k nodes execute in sub-millisecond time.
- **Revisit condition:** If graph traversals exceed 5+ hops over millions of entities where graph traversal latency in PostgreSQL becomes a measurable bottleneck.

### Unstructured Query-Time LLM Graph Generation
- **What it is:** Asking an LLM at query time to generate a synthetic graph or Cypher query from the question.
- **Why it was plausible:** No upfront schema or extraction required.
- **Why rejected:** Non-deterministic, prone to prompt injection from document text, high latency overhead (+1.5s per query), and cannot be cryptographically verified against the corpus manifest.
- **Revisit condition:** Never. Ingestion-time grounded extraction is always superior for auditable compliance RAG.
