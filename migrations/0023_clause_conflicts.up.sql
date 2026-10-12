-- Migration 0023: Circular Clause Conflict Detector (FEAT-032)
-- Stores regulatory clause definitions, quantitative parameters, modality mandates,
-- and detected inter-circular conflicts and statutory ambiguities.

CREATE TABLE IF NOT EXISTS circular_clauses (
    id TEXT PRIMARY KEY,
    circular_id TEXT NOT NULL,
    circular_title TEXT NOT NULL,
    regulator TEXT NOT NULL DEFAULT 'RBI',
    section_reference TEXT NOT NULL,
    clause_text TEXT NOT NULL,
    domain_category TEXT NOT NULL,
    modality TEXT NOT NULL DEFAULT 'MANDATORY',
    parameter_name TEXT,
    parameter_value DOUBLE PRECISION,
    parameter_unit TEXT,
    comparison_operator TEXT,
    effective_date DATE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clause_conflict_audits (
    id TEXT PRIMARY KEY,
    clause_a_id TEXT NOT NULL,
    clause_b_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    parameter_name TEXT,
    explanation TEXT NOT NULL,
    prescriptive_action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_circular_clauses_domain ON circular_clauses(domain_category);
CREATE INDEX IF NOT EXISTS idx_circular_clauses_circular_id ON circular_clauses(circular_id);
CREATE INDEX IF NOT EXISTS idx_circular_clauses_regulator ON circular_clauses(regulator);
CREATE INDEX IF NOT EXISTS idx_clause_conflict_audits_severity ON clause_conflict_audits(severity);
