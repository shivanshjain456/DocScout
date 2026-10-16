-- Migration 0016: Standards Registry & Formula Foreign Key Linkage for FEAT-025

CREATE TABLE IF NOT EXISTS standards_registry (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    governing_body VARCHAR(100) NOT NULL,
    domain VARCHAR(100) NOT NULL,
    jurisdiction VARCHAR(50) NOT NULL DEFAULT 'global',
    category VARCHAR(100) NOT NULL DEFAULT 'technical',
    description TEXT NULL,
    official_reference_url VARCHAR(500) NULL,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_standards_registry_domain ON standards_registry(domain);
CREATE INDEX IF NOT EXISTS idx_standards_registry_body ON standards_registry(governing_body);
CREATE INDEX IF NOT EXISTS idx_standards_registry_category ON standards_registry(category);

-- Add standard_id foreign key to document_formulas
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'document_formulas' AND column_name = 'standard_id'
    ) THEN
        ALTER TABLE document_formulas
        ADD COLUMN standard_id VARCHAR(100) NULL REFERENCES standards_registry(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_document_formulas_standard_id ON document_formulas(standard_id);
