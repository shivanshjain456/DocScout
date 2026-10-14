-- Migration 0036: Interactive Compliance Playbook Runtime (FEAT-051)
-- Operationalizes the 12 structured playbooks as active state-machine compliance workflows.

SET search_path = public;

CREATE TABLE IF NOT EXISTS playbook_templates (
    playbook_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    domain VARCHAR(64) NOT NULL,
    total_stages INT NOT NULL DEFAULT 4,
    stages_definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS playbook_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    playbook_id VARCHAR(64) NOT NULL REFERENCES playbook_templates(playbook_id) ON DELETE CASCADE,
    assigned_lead VARCHAR(255) NOT NULL,
    current_stage INT NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'BLOCKED', 'COMPLETED')),
    stage_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_tenant
    ON playbook_runs (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_playbook_runs_playbook
    ON playbook_runs (playbook_id);

ALTER TABLE playbook_runs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'playbook_runs' AND policyname = 'tenant_isolation_playbook_runs'
    ) THEN
        CREATE POLICY tenant_isolation_playbook_runs ON playbook_runs
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON playbook_templates TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON playbook_runs TO docscout_app;
