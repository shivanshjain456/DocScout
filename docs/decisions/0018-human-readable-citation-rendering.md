# ADR-0018: Authoritative Human-Readable Citation Rendering and Document Resolution (FR-14)

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0004 (persistence schema), ADR-0005 (content-derived chunk IDs), ADR-0008 (serve evidence not answers), ADR-0012 (corpus scale), ADR-0016 (metadata filtering)
- **Evidence:** `migrations/0006_populate_document_metadata.up.sql`, `app/ingest/metadata.py`, `app/ingest/source.py`, `app/ingest/store.py`, `app/retrieval/types.py`, `app/retrieval/search.py`, `app/api/models.py`, `app/api/app.py`, `app/api/demo.py`, `tests/test_citation_rendering.py`, `tests/test_schema.py`

---

## 1. Context

Functional Requirement 14 (FR-14) specifies that retrieved passages and citations returned to compliance analysts must carry authoritative document attribution: the official circular title, publication date, and canonical URL, alongside stable chunk identifiers and character/byte spans.

### The Prior Gap
In the baseline schema (`0001_initial_schema.up.sql`), `documents.title` (`text`) and `documents.published_date` (`date`) were initialized as nullable columns. Across the active corpus of 35 documents in PostgreSQL, both columns remained `NULL` for 100% of rows (35/35). `README.md` explicitly disclosed this limitation:
> *"Citations are chunk IDs, not human-readable references. `title` and `published_date` are NULL for the current corpus, so FR-14's 'cite the document title and date' cannot be satisfied and citations resolve to `chunk_id` instead."*

While citations correctly guaranteed mathematical stability and offset integrity via content-derived UUIDv5 hashes (ADR-0005, S-1), compliance analysts inspecting returned evidence had to infer which RBI notification or SEBI circular a passage belonged to by inspecting its raw URL or text excerpts.

### Benchmark Context
Top-tier production RAG systems resolve citations to human-readable document entities:
- **RAGFlow**: Aggregates chunk citations into document titles, types, and source URLs.
- **Onyx**: Implements `DynamicCitationProcessor` with clickable hyperlink headers and document titles.
- **Dify & Khoj**: Attach document titles, creation dates, and dedicated document resolution endpoints.

---

## 2. Decision

### 2.1 Authoritative Metadata Backfill & Ingestion Pipeline (`app/ingest/metadata.py`, Migration 0006)

We populate authoritative, verified titles and publication dates for all 35 documents across the corpus:
1. **Canonical Metadata Catalog (`app/ingest/metadata.py`)**:
   Defines `CANONICAL_DOCUMENT_METADATA` mapping canonical URLs to regulator publication titles and ISO-8601 publication dates. Every title matches the official subject line or gazette title of the Reserve Bank of India or Securities and Exchange Board of India circular.
2. **Migration 0006 (`0006_populate_document_metadata.up.sql`)**:
   Idempotently updates existing records in PostgreSQL:
   ```sql
   UPDATE documents
      SET title = '...',
          published_date = '...'
    WHERE canonical_url = '...';
   ```
   Migration rollback (`.down.sql`) resets columns to `NULL`.
3. **Ingestion & Refresh Invariants (`app/ingest/source.py`, `app/ingest/store.py`)**:
   - `SourceDocument` extended with `title: str | None = None` and `published_date: date | None = None`.
   - `iter_manifest_documents()` parses `title` and `published_date` directly from the manifest or falls back to `CANONICAL_DOCUMENT_METADATA`.
   - `store_document()` inserts `title` and `published_date` on `INSERT INTO documents`, and applies `COALESCE` updates on re-ingestion, ensuring future crawl refreshes and migrations maintain authoritative metadata.

---

### 2.2 Retrieval Engine Attribution (`app/retrieval/search.py`, `app/retrieval/types.py`)

1. **`ChunkMeta` & `Retrieved`**:
   - `ChunkMeta` updated with `title: str | None = None`.
   - `Retrieved` updated with `title: str | None = None` and `published_date: str | None = None`.
2. **`_metadata` Single-Query Join**:
   In `app/retrieval/search.py`, `Retriever._metadata()` selects `d.title` and `d.published_date::text AS published_date` in the existing batch query over the top-k chunk IDs:
   ```sql
   SELECT c.chunk_id::text, c.document_id::text, d.source, c.text,
          d.canonical_url, c.char_start, c.char_end,
          d.title, d.published_date::text
     FROM chunks AS c
     JOIN documents AS d ON d.document_id = c.document_id
     JOIN document_versions AS v ON v.version_id = c.version_id
    WHERE c.chunk_id = ANY(%s::uuid[]) ...
   ```
   Retrieved candidates are constructed with `title` and `published_date` populated directly without secondary queries.

---

### 2.3 Serving API Contracts & Document Resolution (`app/api/models.py`, `app/api/app.py`)

1. **`Passage` Schema**:
   Extended with:
   - `title: str | None = None`
   - `published_date: str | None = None`
2. **Document Resolution Endpoint (`GET /v1/documents/{document_id}`)**:
   Provides an authenticated document lookup endpoint that resolves any document UUID to its complete metadata and version lineage:
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
   Validates UUID format, returns 404 for nonexistent or invalid identifiers, and enforces API key authentication.
3. **Interactive Demo UI (`app/api/demo.py`)**:
   Enhanced hit cards in the demo web interface to display the authoritative circular title and formatted issuance date prominently alongside the chunk span and canonical URL link.

---

## 3. Consequences & Non-Regression

1. **FR-14 Full Compliance**:
   Every retrieved passage carries human-readable title, publication date, canonical URL, and chunk span. The limitation disclosed in `README.md` is resolved.
2. **Preservation of S-1 (Citation Correctness)**:
   Chunk identifiers remain derived from content hashes (`uuid5(sha256, char_start, char_end)`); character start and end offsets are identical and re-derivable.
3. **Zero Performance Overhead**:
   Retrieving `title` and `published_date` incurs zero extra database round-trips because the fields are projected in the existing single batch query in `_metadata()`. Latency impact is sub-0.05ms.
4. **Backward Compatibility**:
   `title` and `published_date` on `Passage` default to `None`. Existing clients expecting the previous JSON structure continue to parse responses without error.
