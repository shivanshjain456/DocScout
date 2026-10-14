-- Migration 0043: Digital Operational Resilience (DORA) Framework Runner (FEAT-058)
-- Tables for ICT systems inventory, operational resilience stress testing, and third-party risk tracking.

SET search_path = public;

CREATE TABLE IF NOT EXISTS dora_systems (
    system_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    name VARCHAR(255) NOT NULL,
    criticality VARCHAR(32) NOT NULL DEFAULT 'MEDIUM',
    is_third_party BOOLEAN NOT NULL DEFAULT FALSE,
    third_party_provider VARCHAR(255),
    is_critical_third_party BOOLEAN NOT NULL DEFAULT FALSE,
    has_exit_strategy BOOLEAN NOT NULL DEFAULT FALSE,
    last_tlpt_date DATE,
    rto_minutes INT,
    rpo_minutes INT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (system_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_dora_systems_tenant_criticality
    ON dora_systems (tenant_id, criticality);

CREATE TABLE IF NOT EXISTS resilience_tests (
    test_id UUID PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    system_id VARCHAR(128) NOT NULL,
    test_type VARCHAR(64) NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_hash VARCHAR(64) NOT NULL,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_resilience_tests_tenant_time
    ON resilience_tests (tenant_id, executed_at);

ALTER TABLE dora_systems ENABLE ROW LEVEL SECURITY;
ALTER TABLE resilience_tests ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'dora_systems' AND policyname = 'tenant_isolation_dora_systems'
    ) THEN
        CREATE POLICY tenant_isolation_dora_systems ON dora_systems
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'resilience_tests' AND policyname = 'tenant_isolation_resilience_tests'
    ) THEN
        CREATE POLICY tenant_isolation_resilience_tests ON resilience_tests
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON dora_systems TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON resilience_tests TO docscout_app;
