-- Migration 0029: Active Circular Temporal Filtering / Point-in-Time Search (FEAT-039)
-- Adds superseded_date and temporal B-tree indices to support retroactive statutory audits.

SET search_path = public;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS superseded_date date;

CREATE INDEX IF NOT EXISTS idx_documents_published_date ON documents(published_date);
CREATE INDEX IF NOT EXISTS idx_documents_superseded_date ON documents(superseded_date);
