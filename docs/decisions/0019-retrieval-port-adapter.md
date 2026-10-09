# ADR-0019: Retrieval-Port Abstraction and Adapter Registry

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** Principal Engineer
- **Related:** ADR-0002 (embedding model & dimension), ADR-0006 (hybrid retrieval), ADR-0016 (metadata filtering)

## Context

Prior to this decision, the retrieval pipeline was tightly coupled to PostgreSQL and the `pgvector` extension across multiple files (`app/retrieval/dense.py`, `app/retrieval/search.py`, `app/retrieval/lexical.py`, and `app/ingest/embed.py`). Specifically:
1. `app/retrieval/search.py` executed raw PostgreSQL SQL queries for hydrating chunk display metadata (`title`, `published_date`, `canonical_url`, byte spans) with parameterized `ANY(%s::uuid[])` joins against `documents` and `document_versions`.
2. Dense retrieval directly called `dense.search(self._conn, ...)` with a concrete `psycopg.Connection`.
3. To test retrieval logic, run ablations, or evaluate vector store changes (e.g. evaluating alternative vector indexing or upgrading embedding dimensions per ADR-0002), engineers had to modify 6+ files across `app/retrieval/` with no seam.
4. Fast testing without a live PostgreSQL daemon was impossible because `Retriever` could not execute without an active database connection.
5. In comparative benchmark audits, advanced systems like RAGFlow (8 engines), Dify (30 vector databases), and FastGPT (5 engines) expose vector store adapter registries, whereas DocScout hard-coded PostgreSQL queries.

## Decision

We will introduce a minimal, typed **Retrieval-Port abstraction** (`app/retrieval/port.py`) adhering to the principle of *interface over implementation*, while maintaining `pgvector` as the sole production adapter:

1. **`VectorStore` Protocol:**
   A runtime-checkable `@runtime_checkable` Python Protocol in `app/retrieval/port.py` specifying:
   - `search(query_vector: np.ndarray, k: int, filter: MetadataFilter | None) -> list[tuple[str, float]]`
   - `fetch_metadata(chunk_ids: list[str], is_current: bool | None) -> dict[str, ChunkRow]`
2. **`PgVectorStore` Production Adapter:**
   Wraps the active database connection and delegates dense cosine distance queries (`vector_cosine_ops` `<=>`) and chunk metadata joins, encapsulating all pgvector SQL within the datastore boundary.
3. **Decoupled `Retriever`:**
   `Retriever` depends strictly on `VectorStore`, not raw `psycopg` SQL. When initialized without an explicit adapter, it resolves the adapter configured in `RetrievalConfig.vector_store_adapter` (defaulting to `"pgvector"`).
4. **Adapter Registry & Config Coherence:**
   An adapter registry `ADAPTER_REGISTRY` in `app/retrieval/port.py` and `config/retrieval.json` declaring `"active_vector_store": "pgvector"`. Enforced by `tests/test_config_coherence.py` to ensure config and code never drift.
5. **Exact Metric Invariance:**
   Retaining `PgVectorStore` as the production adapter guarantees byte-for-byte numerical identity: `hybrid-rrf` through the port yields identical rankings, scores, and arm attributions as the direct SQL implementation (`Δ recall@5 = 0.000` across all 365 scored gold items).

## Consequences

### Positive
- **Operability Seam:** Alternative vector engines or in-memory vector stores can be plugged in by implementing `VectorStore` and registering in `ADAPTER_REGISTRY` with 0 edits to `search.py`, `fusion.py`, or API layers.
- **Fast DB-less Testing:** Pure retrieval, fusion, reranking, and confidence assessment tests can run with in-memory vector store doubles without requiring a PostgreSQL daemon.
- **Encapsulation:** SQL table joins for chunk metadata are cleanly encapsulated in the storage adapter rather than embedded in the middle of search choreography.
- **Config Coherence:** `config/retrieval.json` provides explicit runtime declaration matching benchmark expectations.

### Tradeoffs & Maintenance
- One additional module (`app/retrieval/port.py`) to maintain.
- Adding a new vector store requires implementing both `search` and `fetch_metadata`.

## Rejected alternatives

### Full Multi-Database Matrix (Qdrant, Milvus, Chroma, Weaviate)
- **What it is:** Implementing 4–8 concrete vector store drivers simultaneously with Docker Compose profiles.
- **Why it was plausible:** Matches the superficial feature checklists of RAGFlow and Dify.
- **Why rejected:** Violates DocScout's core principle of "one system done well" (§6). DocScout's value lies in operational rigor, verified reproducibility, and exact citation grounding, not a zoo of half-tested database connectors that add dependency bloat.
- **Revisit condition:** If a regulatory compliance customer explicitly mandates deployment on an existing enterprise vector database cluster (e.g., Milvus or Qdrant).

### LangChain / LlamaIndex VectorStore Abstractions
- **What it is:** Adopting `langchain-core` or `llama-index` vector store base classes.
- **Why it was plausible:** Standard third-party ecosystem interface.
- **Why rejected:** Heavy transitive dependencies (200+ packages), loss of strict typing and deterministic error handling, and inability to enforce DocScout's fine-grained SQL invariants (e.g. `vector_cosine_ops`, transactional version currency `is_current`, parameterized composite metadata filtering).
- **Revisit condition:** Never. Standard library `typing.Protocol` provides zero-dependency typing without framework lock-in.

### Status Quo (Direct SQL in `search.py` without seam)
- **What it is:** Keeping direct SQL queries hard-coded in `search.py` and deferring the port indefinitely.
- **Why it was plausible:** DocScout only runs on PostgreSQL today, so abstraction was previously deferred.
- **Why rejected:** As the corpus and gold set grow, the inability to test retrieval in isolation and the tight coupling across 6+ files when evaluating embedding upgrades represents a genuine operability bottleneck.
