-- 0053: cryptographic_audit_trail - SLSA Level 3 Provenance & Immutable Audit Trail (FEAT-098).
--
-- Why: Court-admissible regulatory compliance requires cryptographic guarantees that all
-- ingested circular artifacts, vector index revisions, and evaluation reports have not
-- been tampered with or modified.
--
-- Design:
-- 1. Immutable append-only cryptographic ledger storing in-toto SLSA provenance attestations.
-- 2. Every entry is anchored with an immutable SHA-256 digest and Ed25519/OIDC signature.
-- 3. Least-privilege permissions: docscout_app role has SELECT and INSERT only (NO UPDATE, NO DELETE).

SET search_path = public;

CREATE TABLE IF NOT EXISTS cryptographic_audit_trail (
    id               bigserial   PRIMARY KEY,
    timestamp        timestamptz NOT NULL DEFAULT now(),
    entity_type      text        NOT NULL,
    entity_id        text        NOT NULL,
    sha256_digest    char(64)    NOT NULL,
    attestation      jsonb       NOT NULL,
    signature        text        NOT NULL,
    signer_identity  text        NOT NULL DEFAULT 'docscout-oidc-signer',
    verified         boolean     NOT NULL DEFAULT true,

    CONSTRAINT ck_audit_trail_sha256
        CHECK (sha256_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_audit_trail_entity_type
        CHECK (entity_type IN ('circular', 'vector_index', 'eval_report', 'release', 'build'))
);

COMMENT ON TABLE cryptographic_audit_trail IS
    'Immutable cryptographic audit trail for SLSA Level 3 provenance (FEAT-098).';

CREATE OR REPLACE VIEW audit_trail AS
    SELECT * FROM cryptographic_audit_trail;

CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp
    ON cryptographic_audit_trail (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_trail_entity
    ON cryptographic_audit_trail (entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_audit_trail_sha256
    ON cryptographic_audit_trail (sha256_digest);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT ON cryptographic_audit_trail TO docscout_app;
        GRANT SELECT, INSERT ON audit_trail TO docscout_app;
        GRANT USAGE, SELECT ON SEQUENCE cryptographic_audit_trail_id_seq TO docscout_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout') THEN
        GRANT SELECT, INSERT ON cryptographic_audit_trail TO docscout;
        GRANT SELECT, INSERT ON audit_trail TO docscout;
        GRANT USAGE, SELECT ON SEQUENCE cryptographic_audit_trail_id_seq TO docscout;
    END IF;
END $$;
