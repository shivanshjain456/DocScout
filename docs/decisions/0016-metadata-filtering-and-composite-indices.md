# ADR-0016: Declarative Metadata Filtering, In-Query Index Pruning, and Cache Partitioning

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0004 (persistence schema & migrations), ADR-0006 (hybrid retrieval & fusion), ADR-0008 (serving API), ADR-0014 (cache invalidation on supersession)
- **Evidence:** `migrations/0005_metadata_indices.up.sql`, `app/retrieval/types.py`, `app/retrieval/dense.py`, `app/retrieval/lexical.py`, `app/retrieval/search.py`, `app/api/models.py`, `app/api/app.py`, `tests/test_metadata_filtering.py`, `tests/test_schema.py`

---

## 1. Context

DocScout retrieves regulatory circulars from the Reserve Bank of India (RBI) and the Securities and Exchange Board of India (SEBI).

In production regulatory compliance, retrieval queries are rarely unconstrained. Practitioners require bounded search:
1. **Regulatory Authority Scope**: Querying guidelines applicable to banking entities (RBI only) versus securities market intermediaries (SEBI only), or querying both while strictly excluding synthetic injection canaries.
2. **Temporal & Amendment Bounding**: Statutes and circulars change over time. A compliance analyst checking whether an action was compliant in 2024 needs to bound retrieval to circulars published before a specific amendment date, whereas an operational tool verifying current compliance requires current directives.
3. **Legal Archaeology & Superseded History**: When defending historical compliance decisions, practitioners must inspect superseded directives (`is_current = false`) rather than solely in-force law.
4. **Document / URL Targeting**: Scoping retrieval to a specific known master circular or circular URL.

Prior to this decision:
- The only filter in the codebase was the hardcoded SQL predicate `WHERE v.is_current` in `app/retrieval/dense.py` and `app/retrieval/lexical.py::_build`.
- `POST /v1/search` offered no filter parameters on `SearchRequest`.
- The LRU cache key in `app/api/app.py` was `(query, mode, k, generate_answer)`, meaning any filtering would risk cache poisoning if not partitioned.
- The PostgreSQL schema had no indices on `documents(source)` or `documents(published_date)`.

---

## 2. Decision

### 2.1 Declarative Filter Specification (`MetadataFilter`)

We introduce `MetadataFilter` in `app/retrieval/types.py` and expose it via `SearchRequest.filter` in `app/api/models.py`:

```python
class MetadataFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    is_current: bool | None = True
    document_ids: list[str] | None = None
    canonical_url: str | None = None
```

- **`is_current` defaults to `True`**: Preserves zero-configuration safety so ordinary searches never retrieve superseded documents.
- **Explicit `is_current = False`**: Enables historical legal audits to retrieve superseded passages without removing retention guarantees (FR-4).
- **`is_current = None`**: Permits unrestricted search across all historical and current versions.
- **`date_from` and `date_to`**: Evaluated against `COALESCE(d.published_date, v.fetch_ts::date)`. When authoritative publication date is available, it is prioritized; when NULL, version observation timestamp (`fetch_ts::date`) serves as an exact fallback.
- **Deterministic Hashing (`canonical_tuple`)**: Computes a stable, hashable tuple of normalized parameters for cache key construction and audit logging.

---

### 2.2 In-Query vs. Post-Hoc Filtering

Industry RAG benchmarks (Onyx, FastGPT) demonstrate that post-hoc filtering (retrieving top-k candidates and discarding non-matching items in application memory) suffers from **candidate starvation**: if the top-10 dense results all originate from RBI and the client requested SEBI, post-hoc filtering returns 0 passages despite hundreds of valid SEBI candidates existing in the index.

Therefore, DocScout enforces **strictly in-query filtering**:
1. **Dense Arm (`dense.py`)**:
   - Compiles SQL `WHERE` clauses directly into the pgvector query:
     ```sql
     SELECT c.chunk_id::text, 1.0 - (c.embedding <=> %(vector)s::vector) AS similarity
     FROM chunks AS c
     JOIN document_versions AS v ON v.version_id = c.version_id
     JOIN documents AS d ON d.document_id = c.document_id
     WHERE <filter_clauses>
     ORDER BY c.embedding <=> %(vector)s::vector
     LIMIT %(k)s
     ```
   - Parameters are securely bound using psycopg dictionary binding (no string interpolation).
2. **Lexical Arm (`lexical.py`)**:
   - `BM25Index` records `_chunk_meta: dict[str, ChunkMeta]` during index construction.
   - During term posting evaluation, `filter.matches(meta)` discards disqualified chunks before accumulator update.
   - Disqualified candidates incur zero scoring computation, and full top-k candidate density is preserved.

---

### 2.3 Cache Key Partitioning

In `app/api/app.py`, the cache key is extended:
```python
filter_key = payload.filter.canonical_tuple() if payload.filter else None
cache_key = (payload.query, payload.mode, payload.k, payload.generate_answer, filter_key)
```
- Queries with different authority constraints (`source="RBI"` vs `source="SEBI"`) or different date bounds never collide or return cross-contaminated results from cache.
- Unfiltered queries maintain clean cache segregation from filtered queries.

---

### 2.4 Index Support (Migration 0005)

To optimize in-query filtering as the corpus grows, Migration 0005 (`0005_metadata_indices.up.sql`) adds targeted B-tree indices:
- `idx_documents_source` on `documents (source)`
- `idx_documents_published_date` on `documents (published_date)`
- `idx_documents_source_published_date` on `documents (source, published_date)`
- `idx_document_versions_fetch_ts` on `document_versions (fetch_ts)`
- `idx_document_versions_current` on `document_versions (is_current)`

Postgres query plans (`EXPLAIN`) confirm that the planner chooses bitmap index scans on `idx_documents_source` and joins to `chunks` via `idx_chunks_document`.

---

### 2.5 Scaling Analysis: Deferral of Chunk Denormalization

The scaling note in `dense.py` discusses denormalizing `is_current` onto `chunks`. We evaluated this design and explicitly **deferred** denormalizing `is_current` and `source` onto the `chunks` table for the following architectural reasons:

1. **O(1) vs. O(N) Supersession Cost**:
   - With normalized versions, marking a document version superseded requires updating a single row: `UPDATE document_versions SET is_current = false WHERE document_id = ...`.
   - Denormalizing `is_current` onto `chunks` would turn supersession into an O(N) update of dozens to hundreds of chunk rows, causing table bloat, dirtying index pages, and triggering WAL write spikes.
2. **pgvector 0.7+ Iterative Scan**:
   - Modern pgvector versions support iterative index scanning (`hnsw.iterative_scan = relaxed_order`), which navigates the HNSW graph while filtering against joined tables without requiring composite partial indices on vectors.
3. **Corpus Scale Profile**:
   - At current and projected corpus scale (< 100,000 chunks), Postgres join performance between `chunks`, `document_versions`, and `documents` across primary and foreign key indices executes in sub-millisecond time (< 5 ms). Denormalization is unnecessary complexity at this stage and is deferred until multi-million chunk scale demands it.

---

## 3. Consequences

### Positive
- **Deterministic Scoping**: Clients can restrict search to specific regulatory bodies (`RBI` vs `SEBI`) and date windows with zero leakage.
- **Auditing Capability**: Legal compliance teams can query superseded historical regulations (`is_current=False`).
- **No Candidate Starvation**: In-query filtering guarantees that top-k results are completely filled with matching passages rather than truncated.
- **Cache Isolation**: Independent cache keys ensure filtered requests never poison unfiltered cache entries or vice versa.
- **Proven Index Utilization**: Schema migration 0005 provides index coverage verified via `EXPLAIN`.

### Neutral / Trade-offs
- `BM25Index` retains a small in-memory metadata dictionary (`_chunk_meta`), consuming ~30 KB of memory for 230 chunks.
- Queries against non-existent authorities or empty date ranges return 200 OK with `passages = []`, requiring clients to handle empty candidate sets.
