-- Migration 0028: Enterprise Compliance Debt Register (FEAT-038)
-- Tracks active compliance exceptions, deprecated procedures, and remediation target dates.

CREATE TABLE IF NOT EXISTS compliance_debt_register (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    practice_name TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'HIGH',
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_REMEDIATION', 'RESOLVED')),
    owner_email TEXT NOT NULL,
    target_date DATE NOT NULL,
    justification TEXT NOT NULL,
    deprecation_id TEXT,
    antipattern_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_debt_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    debt_item_id UUID NOT NULL REFERENCES compliance_debt_register(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    actor_email TEXT NOT NULL,
    transition_notes TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_compliance_debt_tenant_status ON compliance_debt_register(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_compliance_debt_target_date ON compliance_debt_register(target_date);
CREATE INDEX IF NOT EXISTS idx_compliance_debt_deprecation ON compliance_debt_register(deprecation_id);
CREATE INDEX IF NOT EXISTS idx_compliance_debt_antipattern ON compliance_debt_register(antipattern_id);
CREATE INDEX IF NOT EXISTS idx_compliance_debt_audit_item ON compliance_debt_audit_log(debt_item_id);

ALTER TABLE compliance_debt_register ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'compliance_debt_register' AND policyname = 'tenant_isolation_compliance_debt'
    ) THEN
        CREATE POLICY tenant_isolation_compliance_debt ON compliance_debt_register
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;
