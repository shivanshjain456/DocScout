-- Migration 0042: Post-Quantum Cryptographic Migration Tracker (FEAT-057)
-- Cryptographic asset inventory and HNDL vulnerability tracking.

SET search_path = public;

CREATE TABLE IF NOT EXISTS pqc_crypto_assets (
    asset_id UUID PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    hostname VARCHAR(255) NOT NULL,
    hostname_hash VARCHAR(64) NOT NULL,
    tls_version VARCHAR(32) NOT NULL,
    cipher_suite VARCHAR(128) NOT NULL,
    cert_signature_algo VARCHAR(128) NOT NULL,
    cert_key_size INT,
    cert_expiry DATE,
    classification VARCHAR(32) NOT NULL,
    hndl_vulnerable BOOLEAN NOT NULL DEFAULT TRUE,
    quantum_safe_algo VARCHAR(128),
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pqc_crypto_assets_tenant
    ON pqc_crypto_assets (tenant_id);

CREATE INDEX IF NOT EXISTS idx_pqc_crypto_assets_classification
    ON pqc_crypto_assets (classification);

CREATE INDEX IF NOT EXISTS idx_pqc_crypto_assets_scanned_at
    ON pqc_crypto_assets (scanned_at);

ALTER TABLE pqc_crypto_assets ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pqc_crypto_assets' AND policyname = 'tenant_isolation_pqc_crypto_assets'
    ) THEN
        CREATE POLICY tenant_isolation_pqc_crypto_assets ON pqc_crypto_assets
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.current_tenant_id', true), ''), tenant_id));
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON pqc_crypto_assets TO docscout_app;
