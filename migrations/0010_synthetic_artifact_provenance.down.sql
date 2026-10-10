-- Revert migration 0010: synthetic artifact classification

SET search_path = public;

DROP INDEX IF EXISTS idx_documents_is_synthetic;

ALTER TABLE documents
    DROP COLUMN IF EXISTS is_synthetic;
