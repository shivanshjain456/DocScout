-- Migration 0024 Down: Drop Antipattern Registry Tables (FEAT-033)

DROP INDEX IF EXISTS idx_antipattern_scan_audits_score;
DROP INDEX IF EXISTS idx_antipattern_definitions_severity;
DROP INDEX IF EXISTS idx_antipattern_definitions_domain;
DROP TABLE IF EXISTS antipattern_scan_audits;
DROP TABLE IF EXISTS antipattern_definitions;
