-- Migration 0050 rollback: Automated Regulatory Metadata & Notification ID Extraction (FEAT-069)

SET search_path = public;

DROP INDEX IF EXISTS idx_documents_issuing_department;
DROP INDEX IF EXISTS idx_documents_circular_no;

ALTER TABLE documents
    DROP COLUMN IF EXISTS signoff_authority,
    DROP COLUMN IF EXISTS subject,
    DROP COLUMN IF EXISTS issuing_department,
    DROP COLUMN IF EXISTS circular_no;
