-- Migration 0041: Regulated Release Certification Pipeline (FEAT-056)
-- Cryptographically attested release certificates with GSN safety cases.

SET search_path = public;

CREATE TABLE IF NOT EXISTS release_certificates (
    certificate_id UUID PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    commit_sha VARCHAR(40) NOT NULL,
    build_id VARCHAR(128) NOT NULL,
    is_certified BOOLEAN NOT NULL DEFAULT FALSE,
    gsn_safety_case_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    signature_sha256 VARCHAR(64) NOT NULL,
    rejection_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    certified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_release_certificates_commit
    ON release_certificates (commit_sha);

CREATE INDEX IF NOT EXISTS idx_release_certificates_tenant
    ON release_certificates (tenant_id);

ALTER TABLE release_certificates ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'release_certificates' AND policyname = 'tenant_isolation_release_certificates'
    ) THEN
        CREATE POLICY tenant_isolation_release_certificates ON release_certificates
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON release_certificates TO docscout_app;
