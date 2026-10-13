-- Migration 0029 Down: Active Circular Temporal Filtering / Point-in-Time Search (FEAT-039)

SET search_path = public;

DROP INDEX IF EXISTS idx_documents_superseded_date;
DROP INDEX IF EXISTS idx_documents_published_date;

ALTER TABLE documents
    DROP COLUMN IF EXISTS superseded_date;
