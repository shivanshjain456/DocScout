# P2-1 Implementation Plan — Retrieval-Port Adapter

## 1. Task Definition & Failing Query / Operability Gap

- **Task ID:** `P2-1`
- **Capability:** Retrieval-Port Abstraction (`VectorStore` / `RetrievalPort` interface with `pgvector` as the production adapter).
- **Failing Query Class / Operability Gap:**
  - *Coupling and fragility across 6+ files:* Currently, `pgvector` and raw `psycopg` SQL queries are tightly coupled directly into `app/retrieval/dense.py`, `app/retrieval/search.py` (which embeds inline SQL for chunk metadata joins), `app/ingest/embed.py`, and `app/retrieval/lexical.py`.
  - Swapping an embedding model (e.g., upgrading from BGE-small 384-d per ADR-0002) or targeting a specialized vector index (e.g. Qdrant, Milvus, or in-memory vector storage for fast local unit testing without PostgreSQL) currently requires invasive changes across the entire retrieval and fusion pipeline, rather than plugging into a clean interface.
  - Benchmarks RAGFlow (8 engines), Dify (30), and FastGPT (5) expose an adapter registry; DocScout currently hard-codes direct PostgreSQL table queries.
  - *Requirement:* Provide an interface over implementation: a clean `VectorStore` protocol in `app/retrieval/port.py`, where `PgVectorStore` is the sole production adapter. `Retriever` in `app/retrieval/search.py` must depend on `VectorStore`, not raw `psycopg` SQL. `RetrievalConfig` selects the adapter name. Config coherence enforces registry alignment.
  - *Metric Invariant:* Exact numerical preservation (`Δ recall@5 ≤ 0.002` across the 365 scored gold items; in fact byte-for-byte identical output for `pgvector`).

---

## 2. Sub-tasks Breakdown

### Sub-task 1: Define `VectorStore` Protocol and Data Containers in `app/retrieval/port.py`
- **Scope:** Define the protocol abstraction `VectorStore` and shared `ChunkRow` data model in a dedicated module `app/retrieval/port.py`.
- **Inputs:** `app/retrieval/types.py`, `app/retrieval/search.py` (`_ChunkRow`), `app/retrieval/dense.py`.
- **Outputs:** `app/retrieval/port.py` containing:
  - `ChunkRow` dataclass (promoted from private `_ChunkRow` in `search.py`).
  - `VectorStore` runtime-checkable `Protocol` with:
    - `search(query_vector: np.ndarray, k: int, filter: MetadataFilter | None = None) -> list[tuple[str, float]]`
    - `fetch_metadata(chunk_ids: list[str], is_current: bool | None = True) -> dict[str, ChunkRow]`
  - `ADAPTER_REGISTRY: dict[str, type[VectorStore]]` and `get_vector_store(name: str, conn: psycopg.Connection | None) -> VectorStore`.
- **Quality Bar:** Strict typing (`mypy` clean), runtime checkability (`@typing.runtime_checkable`), zero circular dependencies. No loss of metadata fields (`document_id`, `source`, `text`, `canonical_url`, `char_start`, `char_end`, `title`, `published_date`).
- **Success Criteria:** `from app.retrieval.port import VectorStore, ChunkRow, get_vector_store` imports cleanly and passes `mypy --strict`.
- **Assurance Gates:** `ruff check`, `mypy app`.
- **Risks & Non-goals:** Non-goal: building a complex multi-backend plugin zoo. Goal is one clean seam with `pgvector` as the sole production adapter.

---

### Sub-task 2: Implement `PgVectorStore` Production Adapter
- **Scope:** Implement `PgVectorStore` adhering to `VectorStore`, wrapping `psycopg` connection and delegating dense vector distance calculation and metadata fetching.
- **Inputs:** `app/retrieval/dense.py`, `app/retrieval/search.py` (`_metadata`), `app/retrieval/port.py`.
- **Outputs:** `PgVectorStore` class inside `app/retrieval/port.py` registered under `"pgvector"`.
- **Quality Bar:**
  - Preserves exact parameter binding, `vector_cosine_ops` (`<=>`), similarity math (`1.0 - distance`), and `MetadataFilter` SQL construction from `dense.py`.
  - Preserves parameterized `ANY(%s::uuid[])` and `is_current` filtering in `fetch_metadata`.
  - Maintains fail-closed error handling and connection safety.
- **Success Criteria:** Calling `store.search(...)` and `store.fetch_metadata(...)` on `PgVectorStore` yields exact identical data types and tuples as legacy functions.
- **Assurance Gates:** Unit tests in `tests/test_retrieval_port.py`.
- **Risks & Non-goals:** Do not alter the SQL query semantics or similarity computation.

---

### Sub-task 3: Refactor `Retriever` to Depend on `VectorStore` Interface
- **Scope:** Update `app/retrieval/search.py` so `Retriever` accepts `vector_store: VectorStore | None = None`. If not provided, it resolves the adapter using `RetrievalConfig.vector_store_adapter` (defaulting to `"pgvector"`) via `get_vector_store(config.vector_store_adapter, self._conn)`.
- **Inputs:** `app/retrieval/search.py`, `app/retrieval/types.py`, `app/retrieval/port.py`.
- **Outputs:**
  - `app/retrieval/types.py`: `RetrievalConfig` gains `vector_store_adapter: str = "pgvector"`.
  - `app/retrieval/search.py`: `Retriever` calls `self._vector_store.search(...)` and `self._vector_store.fetch_metadata(...)`. Inline SQL queries removed from `search.py`.
- **Quality Bar:**
  - `Retriever` can be instantiated and executed with an in-memory test double of `VectorStore` with zero PostgreSQL connection required.
  - Backwards-compatibility preserved for existing callers (`Retriever(conn)` continues to work seamlessly).
- **Success Criteria:** `Retriever(conn).retrieve(...)` produces byte-for-byte identical results to baseline.
- **Assurance Gates:** Full pytest suite (`tests/test_api_search.py`, `tests/test_api_answer.py`, `tests/test_metadata_filtering.py`, `tests/test_query_expansion.py`).

---

### Sub-task 4: Registry Configuration & Coherence Tests
- **Scope:** Add `config/retrieval.json` declaring the active adapter registry (`pgvector`), and extend `tests/test_config_coherence.py` to assert coherence between `config/retrieval.json` and `app/retrieval/port.py`.
- **Inputs:** `config/retrieval.json`, `app/retrieval/port.py`, `tests/test_config_coherence.py`.
- **Outputs:**
  - `config/retrieval.json` specifying `"active_vector_store": "pgvector"`, `"available_vector_stores": ["pgvector"]`.
  - New test in `tests/test_config_coherence.py` verifying that every configured store is registered in `app/retrieval/port.py`.
- **Quality Bar:** Falsifiable assertion: adding an unregistered store or removing `pgvector` fails the build immediately.
- **Success Criteria:** `pytest tests/test_config_coherence.py` passes cleanly.

---

### Sub-task 5: Dedicated Unit & Contract Tests in `tests/test_retrieval_port.py`
- **Scope:** Comprehensive test suite validating:
  1. `VectorStore` Protocol conformance.
  2. In-memory `VectorStore` adapter proving complete decoupling from PostgreSQL (retrieval runs without DB).
  3. `PgVectorStore` adapter output equivalence with direct `dense.search`.
  4. Registry lookup and error handling for unknown adapter names.
  5. Deterministic equivalence of `hybrid-rrf` via port vs direct baseline.
- **Inputs:** `app/retrieval/port.py`, `app/retrieval/search.py`, `tests/test_retrieval_port.py`.
- **Outputs:** `tests/test_retrieval_port.py`.
- **Quality Bar:** 100% branch coverage on `app/retrieval/port.py`.
- **Success Criteria:** All tests in `tests/test_retrieval_port.py` pass.

---

### Sub-task 6: ADR-0019 Documentation
- **Scope:** Write `docs/decisions/0019-retrieval-port-adapter.md` documenting:
  - Context and operability gap (file coupling on vector store implementation).
  - Decision: Interface over implementation via `VectorStore` Protocol and adapter registry, retaining `pgvector` as the single production adapter.
  - Rejected alternatives:
    - Leaky third-party framework abstractions (LangChain, LlamaIndex VectorStores).
    - Premature multi-database matrix (running 5 vector databases simultaneously).
    - Direct SQL coupling without seam.
  - Non-regression proof and verification evidence.
- **Inputs:** Architectural trade-offs, benchmark analysis (RAGFlow, Dify, FastGPT).
- **Outputs:** `docs/decisions/0019-retrieval-port-adapter.md`.

---

### Sub-task 7: Full Verification Gates & Metric Non-Regression
- **Scope:** Run full test suite, code quality checks (`ruff`, `mypy`), and verify retrieval regression gate.
- **Inputs:** `make test`, `ruff check`, `mypy app tests`.
- **Success Criteria:**
  - `ruff check + format --check` clean.
  - `mypy app tests` clean.
  - Full `pytest -q` clean.
  - No change in retrieval rankings or scores (`Δ recall@5 = 0.000`).
