-- DocScout 0010: synthetic artifact classification and grounded truth provenance.
--
-- Explicitly segregates synthetic evaluation fixtures (canary-001 and documents 21-34)
-- from authoritative regulatory evidence in production search, generation, and digests.

SET search_path = public;

-- 1. Add is_synthetic column to documents table
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS is_synthetic boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN documents.is_synthetic IS
    'True for synthetic test artifacts (canary-001, P0-3 eval fixtures). Excluded from production evidence and digests.';

-- 2. Mark synthetic injection canary and locally generated evaluation circulars
UPDATE documents
   SET is_synthetic = true
 WHERE source = 'SYNTHETIC'
    OR canonical_url LIKE 'synthetic://%'
    OR canonical_url LIKE '%NOTI280DIGITALLENDING2024.PDF'
    OR canonical_url LIKE '%NOTI281KYCUPDATION2024.PDF'
    OR canonical_url LIKE '%NOTI282CYBERSECURITY2024.PDF'
    OR canonical_url LIKE '%NOTI283NBFCSCALEBASED2024.PDF'
    OR canonical_url LIKE '%NOTI284PRIORITYSECTOR2024.PDF'
    OR canonical_url LIKE '%NOTI285COMPROMISESETTLE2024.PDF'
    OR canonical_url LIKE '%NOTI286GREENDEPOSITS2024.PDF'
    OR canonical_url LIKE '%NOTI287ITOUTSOURCING2024.PDF'
    OR canonical_url LIKE '%/sep-2026/1788%';


-- 3. Set http_status to NULL for synthetic fixtures since they were not fetched over HTTP from regulators
UPDATE document_versions
   SET http_status = NULL
 WHERE document_id IN (SELECT document_id FROM documents WHERE is_synthetic);

-- 4. Create index for fast filtering in production retrieval and digest queries
CREATE INDEX IF NOT EXISTS idx_documents_is_synthetic
    ON documents (is_synthetic);
