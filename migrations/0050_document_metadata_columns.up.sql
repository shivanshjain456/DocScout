-- Migration 0050: Automated Regulatory Metadata & Notification ID Extraction (FEAT-069)
-- Adds structured metadata columns to documents for exact administrative filtering.

SET search_path = public;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS circular_no TEXT,
    ADD COLUMN IF NOT EXISTS issuing_department TEXT,
    ADD COLUMN IF NOT EXISTS subject TEXT,
    ADD COLUMN IF NOT EXISTS signoff_authority TEXT;

CREATE INDEX IF NOT EXISTS idx_documents_circular_no
    ON documents (circular_no);

CREATE INDEX IF NOT EXISTS idx_documents_issuing_department
    ON documents (issuing_department);

COMMENT ON COLUMN documents.circular_no IS 'Official regulatory notification or circular reference number (e.g., RBI/2026-27/273).';
COMMENT ON COLUMN documents.issuing_department IS 'Authoritative issuing department within regulator (e.g., Department of Regulation).';
COMMENT ON COLUMN documents.subject IS 'Authoritative subject line or directive caption.';
COMMENT ON COLUMN documents.signoff_authority IS 'Issuing officer and designation signing the regulatory instrument.';
