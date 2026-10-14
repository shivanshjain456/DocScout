-- Migration 0044: Custom Enterprise Compliance Playbook Builder (FEAT-060)
-- Storage for tenant-authored custom compliance playbooks and multi-stage workflows.

SET search_path = public;

CREATE TABLE IF NOT EXISTS custom_playbook_templates (
    template_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    name VARCHAR(255) NOT NULL,
    goal TEXT NOT NULL,
    domain VARCHAR(128) NOT NULL DEFAULT 'custom',
    stages JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (template_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_custom_playbook_templates_tenant_created
    ON custom_playbook_templates (tenant_id, created_at DESC);

ALTER TABLE custom_playbook_templates ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'custom_playbook_templates' AND policyname = 'tenant_isolation_custom_playbook_templates'
    ) THEN
        CREATE POLICY tenant_isolation_custom_playbook_templates ON custom_playbook_templates
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON custom_playbook_templates TO docscout_app;
