-- Migration 0021: Formula Versions & Historical Evolution (FEAT-030)
-- Tracks regulatory formula changes, variable additions/deletions, threshold revisions,
-- and point-in-time effective date windows across regulatory circular revisions.

CREATE TABLE IF NOT EXISTS formula_versions (
    id TEXT PRIMARY KEY,
    formula_id TEXT NOT NULL,
    version_label TEXT NOT NULL,
    regulatory_framework TEXT NOT NULL DEFAULT 'RBI',
    effective_from DATE NOT NULL,
    effective_to DATE,
    expression TEXT NOT NULL,
    eval_expression TEXT NOT NULL,
    variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    circular_reference TEXT,
    change_summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_formula_versions_formula_id ON formula_versions(formula_id);
CREATE INDEX IF NOT EXISTS idx_formula_versions_effective_dates ON formula_versions(effective_from, effective_to);
