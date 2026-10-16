-- Migration 0051 rollback: Duplicate & Reprint Deduplication Engine (FEAT-070)

SET search_path = public;

DROP INDEX IF EXISTS idx_documents_text_sha256;
DROP INDEX IF EXISTS idx_documents_canonical_document_id;

ALTER TABLE documents
    DROP COLUMN IF EXISTS minhash_signature,
    DROP COLUMN IF EXISTS text_sha256,
    DROP COLUMN IF EXISTS canonical_document_id;
