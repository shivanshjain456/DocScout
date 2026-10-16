-- Migration 0035: Continuous Compliance Observation Window Tracker (FEAT-048)
-- Replaces point-in-time penetration testing with continuous compliance telemetry logging.

SET search_path = public;

CREATE TABLE IF NOT EXISTS compliance_telemetry_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    control_id VARCHAR(100) NOT NULL,
    observation_timestamp TIMESTAMPTZ NOT NULL,
    check_result VARCHAR(10) NOT NULL CHECK (check_result IN ('PASS', 'FAIL')),
    evidence_hash CHAR(64) NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT ck_telemetry_evidence_hash CHECK (length(evidence_hash) = 64)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_tenant_control_time
    ON compliance_telemetry_events (tenant_id, control_id, observation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_telemetry_observation_time
    ON compliance_telemetry_events (observation_timestamp);

CREATE INDEX IF NOT EXISTS idx_telemetry_control_result
    ON compliance_telemetry_events (control_id, check_result);

ALTER TABLE compliance_telemetry_events ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'compliance_telemetry_events' AND policyname = 'tenant_isolation_compliance_telemetry'
    ) THEN
        CREATE POLICY tenant_isolation_compliance_telemetry ON compliance_telemetry_events
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON compliance_telemetry_events TO docscout_app;
