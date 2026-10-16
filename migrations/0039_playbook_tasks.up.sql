-- Migration 0039: Role-Based Compliance Task Routing (FEAT-054)
-- Relational dispatch and task queue partitioning by statutory taxonomy role.

SET search_path = public;

CREATE TABLE IF NOT EXISTS playbook_tasks (
    task_id VARCHAR(64) NOT NULL,
    run_id UUID NOT NULL REFERENCES playbook_runs(run_id) ON DELETE CASCADE,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    playbook_id VARCHAR(64) NOT NULL REFERENCES playbook_templates(playbook_id) ON DELETE CASCADE,
    stage_number INT NOT NULL,
    role VARCHAR(64) NOT NULL CHECK (role IN ('developer', 'qa-engineer', 'sre', 'engineering-manager', 'compliance-officer')),
    title TEXT NOT NULL,
    term_reference VARCHAR(100) NOT NULL DEFAULT '',
    estimated_hours INT NOT NULL DEFAULT 8,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_playbook_tasks PRIMARY KEY (run_id, stage_number, task_id)
);

CREATE INDEX IF NOT EXISTS idx_playbook_tasks_run_role
    ON playbook_tasks (run_id, role);

CREATE INDEX IF NOT EXISTS idx_playbook_tasks_tenant
    ON playbook_tasks (tenant_id);

ALTER TABLE playbook_tasks ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'playbook_tasks' AND policyname = 'tenant_isolation_playbook_tasks'
    ) THEN
        CREATE POLICY tenant_isolation_playbook_tasks ON playbook_tasks
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON playbook_tasks TO docscout_app;
