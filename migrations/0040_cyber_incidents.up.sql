-- Migration 0040: Regulatory Cyber Incident Response Playbook (FEAT-055)
-- High-availability persistence for banking cyber incidents with statutory 6-hour reporting deadlines.

SET search_path = public;

CREATE TABLE IF NOT EXISTS cyber_incidents (
    incident_id UUID PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    run_id UUID REFERENCES playbook_runs(run_id) ON DELETE SET NULL,
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('SEV1', 'SEV2')),
    summary TEXT NOT NULL,
    systems_impacted JSONB NOT NULL DEFAULT '[]'::jsonb,
    discovery_timestamp TIMESTAMPTZ NOT NULL,
    statutory_reporting_deadline TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DECLARED' CHECK (status IN ('DECLARED', 'CONTAINED', 'REPORTED', 'RESOLVED')),
    required_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    actions_completed JSONB NOT NULL DEFAULT '[]'::jsonb,
    disclosure_draft TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cyber_incidents_tenant
    ON cyber_incidents (tenant_id);

CREATE INDEX IF NOT EXISTS idx_cyber_incidents_status_deadline
    ON cyber_incidents (status, statutory_reporting_deadline);

ALTER TABLE cyber_incidents ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'cyber_incidents' AND policyname = 'tenant_isolation_cyber_incidents'
    ) THEN
        CREATE POLICY tenant_isolation_cyber_incidents ON cyber_incidents
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON cyber_incidents TO docscout_app;
