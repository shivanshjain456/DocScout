-- Migration 0023 Down: Drop Circular Clause Conflict Tables (FEAT-032)

DROP INDEX IF EXISTS idx_clause_conflict_audits_severity;
DROP INDEX IF EXISTS idx_circular_clauses_regulator;
DROP INDEX IF EXISTS idx_circular_clauses_circular_id;
DROP INDEX IF EXISTS idx_circular_clauses_domain;
DROP TABLE IF EXISTS clause_conflict_audits;
DROP TABLE IF EXISTS circular_clauses;
