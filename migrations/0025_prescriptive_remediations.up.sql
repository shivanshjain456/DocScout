-- Migration 0025: "Instead-Of" Prescriptive Remediation Engine (FEAT-034)
-- Maps compliance antipatterns and deprecated practices to sanctioned,
-- compliant alternative practices and actionable implementation steps.

CREATE TABLE IF NOT EXISTS prescriptive_remediations (
    id TEXT PRIMARY KEY,
    flaw_type TEXT NOT NULL,
    flaw_id TEXT NOT NULL,
    flaw_title TEXT NOT NULL,
    replacement_term_id TEXT NOT NULL,
    replacement_term_name TEXT NOT NULL,
    tier INT NOT NULL DEFAULT 1,
    definition TEXT NOT NULL,
    value_justification TEXT NOT NULL,
    implementation_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    gate_criteria TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS remediation_audit_logs (
    id TEXT PRIMARY KEY,
    flaw_id TEXT NOT NULL,
    flaw_type TEXT NOT NULL,
    remediations_count INT NOT NULL DEFAULT 0,
    requested_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prescriptive_remediations_flaw_id ON prescriptive_remediations(flaw_id);
CREATE INDEX IF NOT EXISTS idx_prescriptive_remediations_flaw_type ON prescriptive_remediations(flaw_type);
CREATE INDEX IF NOT EXISTS idx_prescriptive_remediations_term_id ON prescriptive_remediations(replacement_term_id);
CREATE INDEX IF NOT EXISTS idx_remediation_audit_logs_flaw ON remediation_audit_logs(flaw_id);
