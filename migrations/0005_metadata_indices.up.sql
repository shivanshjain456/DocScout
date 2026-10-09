-- 0005: metadata_indices — indices for metadata filtering over documents and versions (P1-2).
--
-- Why: P1-2 introduces in-query metadata filtering over regulatory source (RBI vs SEBI),
-- publication and fetch dates, and version currency. Without indices on documents and
-- versions, multi-condition metadata predicates fall back to sequential scans as the
-- corpus scales.
--
-- Supported filter patterns:
-- 1. Authority filtering (documents.source): idx_documents_source
-- 2. Publication date filtering (documents.published_date): idx_documents_published_date
-- 3. Composite authority + date filtering: idx_documents_source_published_date
-- 4. Version fetch date filtering (document_versions.fetch_ts): idx_document_versions_fetch_ts
-- 5. Version currency (document_versions.is_current): idx_document_versions_current

SET search_path = public;

CREATE INDEX IF NOT EXISTS idx_documents_source
    ON documents (source);

CREATE INDEX IF NOT EXISTS idx_documents_published_date
    ON documents (published_date);

CREATE INDEX IF NOT EXISTS idx_documents_source_published_date
    ON documents (source, published_date);

CREATE INDEX IF NOT EXISTS idx_document_versions_fetch_ts
    ON document_versions (fetch_ts);

CREATE INDEX IF NOT EXISTS idx_document_versions_current
    ON document_versions (is_current);

COMMENT ON INDEX idx_documents_source IS 'Accelerates source authority filtering (P1-2).';
COMMENT ON INDEX idx_documents_published_date IS 'Accelerates circular date window filtering (P1-2).';
COMMENT ON INDEX idx_documents_source_published_date IS 'Accelerates combined authority and date range filtering (P1-2).';
COMMENT ON INDEX idx_document_versions_fetch_ts IS 'Accelerates version fetch timestamp filtering (P1-2).';
COMMENT ON INDEX idx_document_versions_current IS 'Accelerates version status filtering (P1-2).';
