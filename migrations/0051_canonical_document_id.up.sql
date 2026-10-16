-- Migration 0051: Duplicate & Reprint Deduplication Engine (FEAT-070)
-- Adds canonical_document_id, text_sha256, and minhash_signature to documents.

SET search_path = public;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS canonical_document_id UUID REFERENCES documents(document_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS text_sha256 VARCHAR(64),
    ADD COLUMN IF NOT EXISTS minhash_signature BIGINT[];

CREATE INDEX IF NOT EXISTS idx_documents_canonical_document_id
    ON documents (canonical_document_id);

CREATE INDEX IF NOT EXISTS idx_documents_text_sha256
    ON documents (text_sha256);

COMMENT ON COLUMN documents.canonical_document_id IS 'Points to canonical document if this document is an exact reprint or near-duplicate.';
COMMENT ON COLUMN documents.text_sha256 IS 'SHA-256 hash of cleaned extracted text for exact duplicate detection.';
COMMENT ON COLUMN documents.minhash_signature IS 'MinHash LSH signature array for near-duplicate circular and gazette detection.';
