-- Migration 0016 down: Drop standards registry and FK column

DROP INDEX IF EXISTS idx_document_formulas_standard_id;
ALTER TABLE IF EXISTS document_formulas DROP COLUMN IF EXISTS standard_id;
DROP TABLE IF EXISTS standards_registry CASCADE;
