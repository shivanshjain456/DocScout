-- Migration 0024: Regulatory & Technical Antipattern Registry (FEAT-033)
-- Stores 30 canonical taxonomy antipatterns, organizational risk scores,
-- and automated compliance manual scan audit logs.

CREATE TABLE IF NOT EXISTS antipattern_definitions (
    id TEXT PRIMARY KEY,
    practice TEXT NOT NULL,
    antipattern_title TEXT NOT NULL,
    consequence TEXT NOT NULL,
    instead_replacements JSONB NOT NULL DEFAULT '[]'::jsonb,
    domain_category TEXT NOT NULL DEFAULT 'testing',
    severity TEXT NOT NULL DEFAULT 'HIGH',
    detection_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS antipattern_scan_audits (
    id TEXT PRIMARY KEY,
    document_name TEXT NOT NULL,
    findings_count INT NOT NULL DEFAULT 0,
    critical_count INT NOT NULL DEFAULT 0,
    high_count INT NOT NULL DEFAULT 0,
    overall_score DOUBLE PRECISION NOT NULL DEFAULT 100.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_antipattern_definitions_domain ON antipattern_definitions(domain_category);
CREATE INDEX IF NOT EXISTS idx_antipattern_definitions_severity ON antipattern_definitions(severity);
CREATE INDEX IF NOT EXISTS idx_antipattern_scan_audits_score ON antipattern_scan_audits(overall_score);
