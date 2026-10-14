-- Migration 0037: 4-Stage Progressive Milestone Tracker (FEAT-052)
-- Relational tracking of discrete compliance deliverables and evidence grounding per playbook stage.

SET search_path = public;

CREATE TABLE IF NOT EXISTS playbook_milestones (
    milestone_record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES playbook_runs(run_id) ON DELETE CASCADE,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    playbook_id VARCHAR(64) NOT NULL REFERENCES playbook_templates(playbook_id) ON DELETE CASCADE,
    stage_number INT NOT NULL,
    milestone_id VARCHAR(64) NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT TRUE,
    evidence_doc_id VARCHAR(255),
    notes TEXT NOT NULL DEFAULT '',
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_run_stage_milestone UNIQUE (run_id, stage_number, milestone_id)
);

CREATE INDEX IF NOT EXISTS idx_playbook_milestones_run
    ON playbook_milestones (run_id, stage_number);

CREATE INDEX IF NOT EXISTS idx_playbook_milestones_tenant
    ON playbook_milestones (tenant_id);

ALTER TABLE playbook_milestones ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'playbook_milestones' AND policyname = 'tenant_isolation_playbook_milestones'
    ) THEN
        CREATE POLICY tenant_isolation_playbook_milestones ON playbook_milestones
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON playbook_milestones TO docscout_app;
