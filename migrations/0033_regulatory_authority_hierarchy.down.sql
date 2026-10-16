-- Migration 0033: Revert Regulatory Authority Hierarchy Resolver (FEAT-045)

SET search_path = public;

DROP INDEX IF EXISTS idx_documents_document_class;
DROP INDEX IF EXISTS idx_documents_authority_tier;

ALTER TABLE documents DROP CONSTRAINT IF EXISTS ck_documents_authority_tier;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS ck_documents_document_class;

ALTER TABLE documents DROP COLUMN IF EXISTS authority_tier;
ALTER TABLE documents DROP COLUMN IF EXISTS document_class;
