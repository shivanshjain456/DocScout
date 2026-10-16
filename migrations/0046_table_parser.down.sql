-- Rollback Migration 0046: High-Fidelity Table Lineage and Matrix Parser (FEAT-062)

SET search_path = public;

DROP TABLE IF EXISTS extracted_tables;
DROP INDEX IF EXISTS idx_chunks_table_data_json;
ALTER TABLE chunks DROP COLUMN IF EXISTS table_data_json;
