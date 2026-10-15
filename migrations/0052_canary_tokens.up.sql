-- Migration 0052: Canary Token Provenance & Leakage Assertions (FEAT-084)
-- Tracks cryptographic canary strings planted in synthetic evaluation fixtures.

SET search_path = public;

CREATE TABLE IF NOT EXISTS canary_tokens (
    canary_id VARCHAR(64) PRIMARY KEY,
    token_string VARCHAR(128) NOT NULL UNIQUE,
    document_id UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    fixture_name VARCHAR(255) NOT NULL,
    planted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_canary_tokens_document_id
    ON canary_tokens (document_id);

CREATE INDEX IF NOT EXISTS idx_canary_tokens_token_string
    ON canary_tokens (token_string);

COMMENT ON TABLE canary_tokens IS 'Cryptographic canary strings planted in synthetic fixtures to assert zero production cross-tenant leakage.';
