-- Migration 0027: Grandfathering & Exemption Scope Engine (FEAT-036)
-- Adds applicability_scope column to chunks table to distinguish universal,
-- grandfathered, and new-entrant provisions.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS applicability_scope TEXT NOT NULL DEFAULT 'ALL';
CREATE INDEX IF NOT EXISTS idx_chunks_applicability_scope ON chunks(applicability_scope);
