-- Migration 0022: Statutory Deprecations & Circular Supersessions (FEAT-031)
-- Tracks superseded circulars, repealed guidelines, and deprecated practices,
-- including circular supersession chains, sunset dates, and grandfathering clauses.

CREATE TABLE IF NOT EXISTS statutory_deprecations (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    subject_type TEXT NOT NULL DEFAULT 'circular',
    regulator TEXT NOT NULL DEFAULT 'RBI',
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    superseded_by TEXT,
    effective_date DATE NOT NULL,
    sunset_date DATE,
    grandfathering_clause TEXT,
    replacement JSONB NOT NULL DEFAULT '[]'::jsonb,
    guidance TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'HIGH',
    citation_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_statutory_deprecations_subject ON statutory_deprecations(subject);
CREATE INDEX IF NOT EXISTS idx_statutory_deprecations_regulator ON statutory_deprecations(regulator);
CREATE INDEX IF NOT EXISTS idx_statutory_deprecations_status ON statutory_deprecations(status);
CREATE INDEX IF NOT EXISTS idx_statutory_deprecations_superseded_by ON statutory_deprecations(superseded_by);
