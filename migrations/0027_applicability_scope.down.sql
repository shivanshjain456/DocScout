-- Migration 0027 Down: Revert applicability_scope column (FEAT-036)

DROP INDEX IF EXISTS idx_chunks_applicability_scope;
ALTER TABLE chunks DROP COLUMN IF EXISTS applicability_scope;
