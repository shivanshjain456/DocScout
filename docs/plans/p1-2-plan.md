# Plan: P1-2  -  Metadata Filtering Beyond `is_current`

## Context and Problem Statement
- **Retrieval & Filtering Need (§3.6)**:
  - Compliance analysts and regulatory researchers do not query regulatory text in a vacuum: questions are bounded by regulatory authority (RBI vs SEBI), issuance date windows (e.g. pre-2025 vs post-2025 directives), circular status (in-force vs historical/superseded), or specific circular IDs/URLs.
  - Prior to this task, the only filter in DocScout was the hard-coded `WHERE v.is_current` predicate in `dense.py` and `lexical.py::_build`.
  - The API had no filter parameters on `SearchRequest`, the cache was keyed only on `(query, mode, k, generate_answer)`, and the schema lacked indices on `source` and `published_date`.
  - Without an in-query filter DSL, date-bounded or authority-bounded queries either require post-hoc filtering (which truncates `k` and throws away valid results) or leak irrelevant regulatory bodies.
- **Goal**:
  1. Define a clean, robust, type-safe `MetadataFilter` DSL supporting:
     - `source`: single authority (`"RBI"`) or multi-authority (`["RBI", "SEBI"]`)
     - `date_from` / `date_to`: date boundaries applied against `COALESCE(d.published_date, v.fetch_ts::date)`
     - `is_current`: boolean (defaults to `True` for current in-force law; `False` enables legal archaeology into superseded circulars; `None` searches all versions)
     - `document_ids`: list of document UUIDs
     - `canonical_url`: exact canonical URL
  2. Implement in-query SQL filtering in `dense.py` using secure parameter binding.
  3. Implement in-index filtering in `BM25Index` (`lexical.py`) during scoring so non-matching chunks consume zero compute.
  4. Extend `RetrievalConfig` and `Retriever` in `search.py` to route filter parameters across both arms.
  5. Update `SearchRequest` in `app/api/models.py` and extend `result_cache` key in `app/api/app.py` to `(query, mode, k, generate_answer, filter.canonical_tuple() if filter else None)`.
  6. Create Migration 0005 (`migrations/0005_metadata_indices.up.sql` and `.down.sql`) adding indices on `documents(source)`, `documents(published_date)`, `document_versions(fetch_ts)`, and `document_versions(is_current)`.
  7. Author ADR-0016 documenting the design, in-query vs post-hoc guarantees, cache partitioning, and the scaling analysis on pgvector index filtering.
  8. Write a comprehensive test suite in `tests/test_metadata_filtering.py` verifying index usage via `EXPLAIN`, source/date/status filtering, and cache isolation.

---

## Technical Design

### 1. Filter Model (`app/retrieval/types.py` & `app/api/models.py`)
```python
class MetadataFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    is_current: bool | None = True
    document_ids: list[str] | None = None
    canonical_url: str | None = None

    def canonical_tuple(self) -> tuple[Any, ...]: ...
    def matches(self, meta: ChunkMeta | None) -> bool: ...
```

### 2. In-Query Dense Filtering (`app/retrieval/dense.py`)
- Base SQL:
  ```sql
  SELECT c.chunk_id::text, 1.0 - (c.embedding <=> %(vector)s::vector) AS similarity
  FROM chunks AS c
  JOIN document_versions AS v ON v.version_id = c.version_id
  JOIN documents AS d ON d.document_id = c.document_id
  WHERE <conditions>
  ORDER BY c.embedding <=> %(vector)s::vector
  LIMIT %(k)s
  ```
- Conditions built dynamically with strict parameter binding (no string concatenation of user values).
- If `is_current is True`, enforces `v.is_current = true`. If `False`, `v.is_current = false`.
- If `source` is provided, filters `d.source = %(source)s` or `d.source = ANY(%(sources)s)`.
- If `date_from` / `date_to` are provided, filters on `COALESCE(d.published_date, v.fetch_ts::date)`.
- If `document_ids` is provided, filters on `c.document_id = ANY(%(doc_ids)s::uuid[])`.

### 3. In-Index Lexical Filtering (`app/retrieval/lexical.py`)
- `BM25Index._build` captures `_chunk_meta: dict[str, ChunkMeta]`.
- When scoring terms in `search()`, chunks not matching `filter.matches(meta)` are skipped before score accumulation.
- Preserves corpus IDF stability for the current collection while enabling exact metadata constraints.

### 4. Cache Partitioning (`app/api/app.py`)
- Cache key:
  `cache_key = (payload.query, payload.mode, payload.k, payload.generate_answer, payload.filter.canonical_tuple() if payload.filter else None)`
- Ensures query results for different filters are cached independently and cannot contaminate one another.

### 5. Migration 0005 (`migrations/0005_metadata_indices.up.sql`)
- Adds:
  - `idx_documents_source` ON `documents (source)`
  - `idx_documents_published_date` ON `documents (published_date)`
  - `idx_documents_source_published_date` ON `documents (source, published_date)`
  - `idx_document_versions_fetch_ts` ON `document_versions (fetch_ts)`
  - `idx_document_versions_current` ON `document_versions (is_current)`

---

## Verification & Quality Gates
1. Run `python scripts/migrate.py up` and verify migration applies cleanly.
2. Verify rollback via `python scripts/migrate.py down --to 4` and re-apply `python scripts/migrate.py up`.
3. Test suite `tests/test_metadata_filtering.py`:
   - Authority filtering (RBI vs SEBI).
   - Date range filtering (pre-amendment vs post-amendment).
   - Historical circular retrieval (`is_current=False`).
   - `EXPLAIN` query plan verification proving index usage.
   - Cache key isolation between filtered and unfiltered queries.
   - FastAPI `POST /v1/search` end-to-end integration with filter payload.
4. Schema tests in `tests/test_schema.py` for Migration 0005 indices.
5. All full suite tests (466+) pass with zero regressions.
6. `ruff check`, `ruff format`, `mypy`, and `./scripts/gate.py` cleanly pass.
