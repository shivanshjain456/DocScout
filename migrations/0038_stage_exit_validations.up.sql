-- Migration 0038: Automated Stage Exit Criteria Validator (FEAT-053)
-- Relational audit trail and empirical verification records for playbook stage promotion gates.

SET search_path = public;

CREATE TABLE IF NOT EXISTS stage_exit_validations (
    validation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES playbook_runs(run_id) ON DELETE CASCADE,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    playbook_id VARCHAR(64) NOT NULL REFERENCES playbook_templates(playbook_id) ON DELETE CASCADE,
    stage_number INT NOT NULL,
    can_advance BOOLEAN NOT NULL,
    exit_statement TEXT NOT NULL,
    checks_evaluated JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocking_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    override_applied BOOLEAN NOT NULL DEFAULT FALSE,
    override_justification TEXT,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stage_exit_validations_run
    ON stage_exit_validations (run_id, stage_number);

CREATE INDEX IF NOT EXISTS idx_stage_exit_validations_tenant
    ON stage_exit_validations (tenant_id);

ALTER TABLE stage_exit_validations ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'stage_exit_validations' AND policyname = 'tenant_isolation_stage_exit_validations'
    ) THEN
        CREATE POLICY tenant_isolation_stage_exit_validations ON stage_exit_validations
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON stage_exit_validations TO docscout_app;
