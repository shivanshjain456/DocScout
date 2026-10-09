# Plan: P1-5 — Human-Readable Citation Rendering (FR-14)

## Context and Problem Statement
- **FR-14 Requirement**:
  - The specification and functional requirements (FR-14) state that citations returned to analysts must include human-readable document attribution: the document title, published date, and canonical URL, alongside stable chunk identifiers and exact character/byte spans.
- **Current Deficit**:
  - `migrations/0001_initial_schema.up.sql` created `documents (title text, published_date date)` as nullable columns.
  - Across the active corpus of 35 documents in PostgreSQL (`documents` table), `title` and `published_date` are currently `NULL` for 100% of rows (35/35).
  - `README.md` explicitly discloses:
    > "Citations are chunk IDs, not human-readable references. `title` and `published_date` are NULL for the current corpus, so FR-14's 'cite the document title and date' cannot be satisfied and citations resolve to `chunk_id` instead."
  - API response model `Passage` currently lacks `title` and `published_date` fields.
  - There is no dedicated document lookup endpoint (`GET /v1/documents/{id}`) to resolve a `document_id` to its full metadata, canonical URL, and version lineage.
- **Benchmark Comparators**:
  - RAGFlow aggregates cited chunks to document titles and URLs; Onyx provides hyperlink citation processors; Khoj and Dify attach document-level titles and publication timestamps.
- **Goal**:
  1. Authoritatively populate `title` and `published_date` across all 35 documents in `corpus/raw/manifest.json`.
  2. Create Migration `0006_populate_document_metadata.up.sql` (and `.down.sql`) to idempotently backfill `documents.title` and `documents.published_date` in PostgreSQL.
  3. Update `app/ingest/source.py` (`SourceDocument`) and `app/ingest/store.py` (`store_document`) so that subsequent ingests and refreshes preserve and update document titles and dates.
  4. Expose `title: str | None` and `published_date: str | None` on `Retrieved` in `app/retrieval/types.py` and `Passage` in `app/api/models.py`.
  5. Implement `GET /v1/documents/{document_id}` in `app/api/app.py` returning `DocumentResponse` with full provenance, authority, title, date, chunk count, and URL.
  6. Enhance the web demo in `app/api/demo.py` to render titles and dates prominently on each hit card.
  7. Author ADR-0018 (`docs/decisions/0018-human-readable-citation-rendering.md`) and update `README.md` Limitations to document the fulfillment of FR-14.
  8. Add comprehensive tests in `tests/test_citation_rendering.py` and schema tests in `tests/test_schema.py`.

---

## Technical Design

### 1. Authoritative Document Metadata
All 35 documents in `corpus/raw/manifest.json` have verified regulator titles and publication dates:
- `canary-001` (Synthetic): `"Settlement timelines for payment aggregators (synthetic canary document)"`, `2026-10-01`
- `01-10` (RBI 2026 notifications): Extracted from official notification headers and subjects.
- `11-20` (SEBI 2026 circulars): Extracted from official SEBI circular titles and subjects.
- `21-28` (RBI 2024 Master Directions & Frameworks): Extracted from official Reserve Bank directions.
- `29-34` (SEBI 2024 Master Circulars & Regulations): Extracted from official SEBI Master Circulars.

### 2. Migration `0006_populate_document_metadata`
- `migrations/0006_populate_document_metadata.up.sql`:
  - Executes batch `UPDATE documents SET title = ..., published_date = ... WHERE canonical_url = ...` for all 35 canonical URLs.
  - Ensures existing 35 documents have non-null authoritative metadata.
- `migrations/0006_populate_document_metadata.down.sql`:
  - Sets `UPDATE documents SET title = NULL, published_date = NULL;`.

### 3. Ingestion Pipeline Updating
- `app/ingest/source.py`:
  - `SourceDocument` gets `title: str | None = None` and `published_date: date | None = None`.
  - `iter_manifest_documents`: Parses `title` and `published_date` (as `date.fromisoformat`) from manifest records.
- `app/ingest/store.py`:
  - `store_document`:
    - Inserts `title` and `published_date` on `INSERT INTO documents`.
    - Updates `title` and `published_date` on `UPDATE documents` if already present.

### 4. Retrieval & Search Engine
- `app/retrieval/types.py`:
  - `ChunkMeta`: Add `title: str | None = None`.
  - `Retrieved`: Add `title: str | None = None` and `published_date: str | None = None`.
- `app/retrieval/search.py`:
  - `_ChunkRow`: Add `title` and `published_date`.
  - `_metadata`: Fetch `d.title, d.published_date::text AS published_date` in SQL SELECT.
  - `retrieve`: Map `row.title` and `row.published_date` into `Retrieved`.

### 5. API Models & Endpoints
- `app/api/models.py`:
  - `Passage`: Add `title: str | None = None` and `published_date: str | None = None`.
  - `DocumentResponse`:
    ```python
    class DocumentResponse(BaseModel):
        document_id: str
        canonical_url: str
        source: str
        authority: str
        title: str | None = None
        published_date: str | None = None
        detail_page: str | None = None
        version_count: int = 1
        current_version_id: str | None = None
        chunk_count: int = 0
        created_at: datetime | None = None
    ```
- `app/api/app.py`:
  - In `search()`: Pass `title=hit.title, published_date=hit.published_date` to `Passage`.
  - Add `GET /v1/documents/{document_id}`:
    - Queries `documents` joined with `document_versions` and `chunks`.
    - Returns `DocumentResponse`.
    - Validates UUID syntax, returns 404 on not found.
    - Requires API key authentication.
- `app/api/demo.py`:
  - Hit cards render `p.title` and `p.published_date` when present.

### 6. Verification & Quality Gates
- `tests/test_citation_rendering.py`:
  - Verify every passage in `POST /v1/search` has non-empty `title` and valid `published_date`.
  - Verify `GET /v1/documents/{document_id}` returns 200 with full metadata for existing documents.
  - Verify `GET /v1/documents/{invalid_id}` returns 404.
  - Verify chunk offset and byte stability (S-1) remains unaffected.
- Run complete test suite (`pytest`), linter (`ruff`), type checker (`mypy`), and regression gate (`eval-gate`).
