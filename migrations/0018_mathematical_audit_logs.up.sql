-- Migration 0018: Mathematical Audit Logs Table (FEAT-027)
-- Records mathematical sanity, cross-footing, and regulatory consistency audit events.

CREATE TABLE IF NOT EXISTS mathematical_audit_logs (
    id TEXT PRIMARY KEY,
    document_id TEXT,
    return_code TEXT NOT NULL DEFAULT 'GENERIC',
    is_valid BOOLEAN NOT NULL,
    rules_checked INTEGER NOT NULL DEFAULT 0,
    anomalies_count INTEGER NOT NULL DEFAULT 0,
    tolerance DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    anomalies JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_math_audit_doc_id ON mathematical_audit_logs(document_id);
CREATE INDEX IF NOT EXISTS idx_math_audit_is_valid ON mathematical_audit_logs(is_valid);
CREATE INDEX IF NOT EXISTS idx_math_audit_return_code ON mathematical_audit_logs(return_code);
CREATE INDEX IF NOT EXISTS idx_math_audit_created ON mathematical_audit_logs(created_at DESC);
