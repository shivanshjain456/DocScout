# P2-2 Implementation Plan — Lightweight Knowledge-Graph over Regulatory Provisions

## 1. Task Definition & Failing Query Class

- **Task ID:** `P2-2`
- **Capability:** Lightweight entity graph over regulatory provisions (nodes: document, section/§, provision; edges: cites, amends, supersedes, implements) and graph-assisted hybrid retrieval.
- **Failing Query Class / Gap:**
  - *12 multi-hop items in `evals/gold/v1/gold.jsonl`* (e.g., `g-125`, `g-126`, `g-266`, `g-268`, `g-270`, `g-271`).
  - Example `g-268`: "What are the cooling-off periods mandated by the RBI for digital loans versus compromise settlements?" requires chunks from both `NOTI280DIGITALLENDING2024.PDF` and `NOTI285COMPROMISESETTLE2024.PDF`.
  - Example `g-266`: "Compare the cyber incident reporting deadline for banks under RBI guidelines with the material event disclosure timeline under SEBI LODR" requires joining distinct authority circulars.
  - *Root Cause:* Single-pass dense/lexical retrieval ranks candidates by lexical/vector similarity to the composite query. When one circular has stronger lexical overlap (e.g., digital lending mentions "cooling-off period" repeatedly), its chunks dominate top-5 or top-10 slots, starving the second circular needed for multi-hop synthesis. Grouped citation scoring alone cannot join provisions across documents.
  - *Requirement:* Build a minimal, span-grounded knowledge graph over regulatory provisions with hybrid graph traversal (`amends`, `supersedes`, `cites`, `implements`) for candidate expansion, with deterministic fallback to standard hybrid when no graph connections exist.

---

## 2. Sub-tasks Breakdown

### Sub-task 1: Migration `0007_knowledge_graph` (Schema & Permissions)
- **Scope:** Create `migrations/0007_knowledge_graph.up.sql` and `migrations/0007_knowledge_graph.down.sql`.
- **Inputs:** `migrations/0001_initial_schema.up.sql`, `migrations/0004_retrieval_audit_log.up.sql`.
- **Outputs:**
  - `graph_nodes` table: `(node_id, node_type, document_id, label, char_start, char_end, created_at)`.
  - `graph_edges` table: `(edge_id, source_node_id, target_node_id, relation, source_document_id, target_document_id, chunk_id, char_start, char_end, evidence_text, created_at)`.
  - Check constraints for node types (`document`, `section`, `provision`) and relations (`cites`, `amends`, `supersedes`, `implements`).
  - Foreign keys to `documents` and `chunks`.
  - Indices on source/target nodes, relations, and documents.
  - Explicit least-privilege `GRANT SELECT, INSERT, UPDATE ON graph_nodes, graph_edges TO docscout_app`.
- **Quality Bar:** Transactional DDL, reversible with matching down migration, strict constraints, fail-closed permissions.
- **Success Criteria:** `python scripts/migrate.py up` applies 0007 cleanly, `status` reports applied.

---

### Sub-task 2: Grounded Graph Extractor (`app/ingest/graph_extractor.py`)
- **Scope:** Extract provision nodes and directed edges from cleaned document text and known regulatory citations.
- **Inputs:** `app/ingest/clean.py`, `app/ingest/chunk.py`, `app/ingest/metadata.py`.
- **Outputs:** `app/ingest/graph_extractor.py` emitting `ExtractedNode` and `ExtractedEdge` objects.
- **Quality Bar:**
  - Zero ungrounded LLM hallucination: every node and edge must cite exact source character spans (`char_start`, `char_end`) within the document.
  - Extracts section/provision numbering (`§ \d+`, `Section \d+`, `Clause \d+`, `Paragraph \d+`, `\d+\.\d+`).
  - Extracts cross-circular citations and relations (`amends`, `supersedes`, `in partial modification of`, `cites`).
  - Matches edge spans to the covering `chunk_id` so graph traversal can immediately resolve retrievable text chunks.
- **Success Criteria:** Unit tests prove extracted nodes and edges match ground truth circular references with valid offsets.

---

### Sub-task 3: Ingestion Pipeline & Graph Persistence
- **Scope:** Wire graph extraction and persistence into `app/ingest/store.py` and `app/ingest/pipeline.py`.
- **Inputs:** `app/ingest/pipeline.py`, `app/ingest/store.py`, `migrations/0007_knowledge_graph.up.sql`.
- **Outputs:**
  - `store_graph_elements(conn, nodes, edges)` in `app/ingest/store.py`.
  - Ingestion runs populate the graph for all 35 documents.
  - Migration 0007 includes bootstrap logic so existing ingested documents have graph elements populated immediately.
- **Quality Bar:** Idempotent writes (`ON CONFLICT DO NOTHING`), preserving FR-7 invariants.
- **Success Criteria:** `SELECT count(*) FROM graph_nodes` > 0 and `SELECT count(*) FROM graph_edges` > 0 across the corpus.

---

### Sub-task 4: Graph-Assisted Hybrid Retriever (`app/retrieval/graph.py`)
- **Scope:** Implement graph traversal and candidate expansion in `app/retrieval/graph.py` and wire `mode="graph-hybrid"` into `app/retrieval/search.py`.
- **Inputs:** `app/retrieval/port.py`, `app/retrieval/search.py`, `app/retrieval/types.py`.
- **Outputs:**
  - `app/retrieval/graph.py`: `GraphRetriever` / `traverse_graph_neighbors(conn, seed_chunk_ids, max_hops=1, relations=...)`.
  - `RetrievalConfig`: supports `mode: Literal["dense", "bm25", "hybrid", "graph-hybrid"]`.
  - `Retriever.retrieve()`: when `graph-hybrid`, performs vector/lexical seed retrieval, executes graph traversal for connected provisions, merges expanded chunks, and fuses ranks via RRF.
  - Deterministic fallback: if graph yields 0 neighbors, output equals standard `hybrid`.
  - Latency tracking: records traversal duration.
- **Quality Bar:**
  - Bounded traversal: `max_hops <= 2`, parameterized queries with bounded limits.
  - Deterministic tie-breaking by chunk ID.
  - Zero regression on existing dense/bm25/hybrid modes.
- **Success Criteria:** `Retriever.retrieve(query, RetrievalConfig(mode="graph-hybrid"))` executes successfully, retrieves connected cross-document chunks on multi-hop questions.

---

### Sub-task 5: Unit & Contract Tests in `tests/test_knowledge_graph.py`
- **Scope:** Dedicated test suite validating:
  1. Migration 0007 schema constraints, check constraints, foreign keys, and rollbacks.
  2. Span-grounding invariant: every extracted edge has `text[char_start:char_end]` matching evidence text.
  3. Graph traversal returns correct 1-hop and 2-hop connected provisions.
  4. `graph-hybrid` retrieval finds both circulars for multi-hop queries (`g-268`, `g-266`).
  5. Fallback behavior: queries with 0 graph matches behave identically to standard `hybrid`.
- **Inputs:** `tests/test_knowledge_graph.py`, `app/retrieval/graph.py`.
- **Outputs:** `tests/test_knowledge_graph.py`.
- **Quality Bar:** 100% test pass rate, strict typing, clean ruff/mypy.
- **Success Criteria:** `pytest tests/test_knowledge_graph.py` passes all tests.

---

### Sub-task 6: ADR-0020 Documentation
- **Scope:** Write `docs/decisions/0020-knowledge-graph-regulatory-provisions.md`.
- **Contents:**
  - Context & multi-hop gap in regulatory compliance queries.
  - Decision: Lightweight provision graph with exact span provenance and hybrid expansion over `cites`/`amends`/`supersedes`.
  - Rejected alternative: Full LightRAG dual-level community summarization (rejected as premature until basic join proves value; avoids LLM cost and ungrounded hallucinations).
  - Measurement and non-regression evidence.
- **Outputs:** `docs/decisions/0020-knowledge-graph-regulatory-provisions.md`.

---

### Sub-task 7: Assurance Gates, Full Suite Verification, and Remote Push
- **Scope:** Run full test suite, quality checks (`ruff`, `mypy`), pre-commit hooks, commit atomically, push to remote, and verify green GitHub Actions CI.
- **Success Criteria:** All 5 CI jobs green on remote push.

---

## 3. Execution & Verification Record

- **Sub-task 1 (Schema & Permissions):** Applied `migrations/0007_knowledge_graph.up.sql` via `python scripts/migrate.py up`. `graph_nodes` and `graph_edges` created with types, check constraints, foreign keys, and `docscout_app` permissions.
- **Sub-task 2 (Graph Extractor):** Implemented `app/ingest/graph_extractor.py` extracting grounded nodes and edges with exact `char_start` and `char_end` spans.
- **Sub-task 3 (Ingest Pipeline & Persistence):** Added `store_graph_elements` and `populate_corpus_knowledge_graph` in `app/ingest/store.py` and wired into `app/ingest/pipeline.py`.
- **Sub-task 4 (Graph-Assisted Retrieval):** Implemented `app/retrieval/graph.py` with `traverse_graph_neighbors` and wired `mode="graph-hybrid"` into `app/retrieval/search.py` with reciprocal rank fusion and automatic fallback.
- **Sub-task 5 (Test Suite):** `tests/test_knowledge_graph.py` executed: 5/5 passed. Full test suite executed: 525+ passed (0 failures).
- **Sub-task 6 (ADR-0020):** Committed `docs/decisions/0020-knowledge-graph-regulatory-provisions.md` documenting architecture, span grounding, and rejected alternatives (Full LightRAG / MS GraphRAG, external Neo4j, query-time LLM generation).
- **Sub-task 7 (Lint, Typing & Gates):** `ruff check .` clean, `ruff format --check .` clean (233 files), `mypy app tests` clean (88 source files).
