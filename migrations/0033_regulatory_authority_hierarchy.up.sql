-- Migration 0033: Regulatory Authority Hierarchy Resolver (FEAT-045)
-- Encodes statutory legal precedence:
-- Tier 1: ACT (1.25x)
-- Tier 2: MASTER_DIRECTION (1.15x)
-- Tier 3: CIRCULAR (1.05x)
-- Tier 4: GUIDELINE (1.00x)
-- Tier 5: FAQ (0.85x)

SET search_path = public;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS document_class VARCHAR(50) NULL,
    ADD COLUMN IF NOT EXISTS authority_tier SMALLINT NULL;

-- Backfill existing documents based on title heuristics if not set
UPDATE documents
SET document_class = CASE
    WHEN title ILIKE '%Act%' OR title ILIKE '%Constitution%' THEN 'ACT'
    WHEN title ILIKE '%Master Direction%' THEN 'MASTER_DIRECTION'
    WHEN title ILIKE '%FAQ%' OR title ILIKE '%Frequently Asked Questions%' OR title ILIKE '%Press Release%' THEN 'FAQ'
    WHEN title ILIKE '%Guideline%' OR title ILIKE '%Framework%' THEN 'GUIDELINE'
    ELSE 'CIRCULAR'
END,
authority_tier = CASE
    WHEN title ILIKE '%Act%' OR title ILIKE '%Constitution%' THEN 1
    WHEN title ILIKE '%Master Direction%' THEN 2
    WHEN title ILIKE '%FAQ%' OR title ILIKE '%Frequently Asked Questions%' OR title ILIKE '%Press Release%' THEN 5
    WHEN title ILIKE '%Guideline%' OR title ILIKE '%Framework%' THEN 4
    ELSE 3
END
WHERE document_class IS NULL;

-- Enforce constraints
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_document_class'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT ck_documents_document_class
            CHECK (document_class IS NULL OR document_class IN ('ACT', 'MASTER_DIRECTION', 'CIRCULAR', 'GUIDELINE', 'FAQ'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_documents_authority_tier'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT ck_documents_authority_tier
            CHECK (authority_tier IS NULL OR (authority_tier >= 1 AND authority_tier <= 5));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_documents_authority_tier ON documents (authority_tier);
CREATE INDEX IF NOT EXISTS idx_documents_document_class ON documents (document_class);

GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO docscout_app;
