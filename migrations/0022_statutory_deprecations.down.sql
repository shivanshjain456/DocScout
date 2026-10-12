-- Migration 0022 Down: Drop Statutory Deprecations Table (FEAT-031)

DROP INDEX IF EXISTS idx_statutory_deprecations_superseded_by;
DROP INDEX IF EXISTS idx_statutory_deprecations_status;
DROP INDEX IF EXISTS idx_statutory_deprecations_regulator;
DROP INDEX IF EXISTS idx_statutory_deprecations_subject;
DROP TABLE IF EXISTS statutory_deprecations;
