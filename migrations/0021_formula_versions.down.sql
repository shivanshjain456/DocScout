-- Migration 0021 Down: Drop Formula Versions Table (FEAT-030)

DROP INDEX IF EXISTS idx_formula_versions_effective_dates;
DROP INDEX IF EXISTS idx_formula_versions_formula_id;
DROP TABLE IF EXISTS formula_versions;
