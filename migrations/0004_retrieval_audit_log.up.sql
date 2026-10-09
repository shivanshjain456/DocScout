-- 0004: retrieval_audit_log — durable, append-only retrieval forensics (P1-1, OWASP LLM09).
--
-- Why: Before this migration, queries were logged only to stdout via ephemeral log streams.
-- Forensic questions ("what was retrieved for whom?", "did an attacker probe the index?")
-- could not be answered with certainty once log buffers rolled over.
--
-- Privacy & Security design:
-- 1. Query Privacy: Query text is NEVER stored by default. Only its SHA-256 digest
--    (`query_hash`) is recorded, preventing incidental PII or sensitive query leaks.
-- 2. Credential Isolation: Raw API keys are NEVER stored. Only the truncated SHA-256
--    fingerprint (`key_fingerprint`) is recorded, matching `app/api/security.py`.
-- 3. Append-Only Integrity: The application role (`docscout_app`) is granted SELECT and INSERT,
--    but strictly denied UPDATE, DELETE, and TRUNCATE. An attacker compromising the
--    serving layer cannot rewrite history or cover tracks.
-- 4. Audit Completeness: Tracks timestamp, key fingerprint, query hash, retrieval mode,
--    requested limit k, ordered array of returned chunk_ids, latency, cache hit status,
--    whether answer generation was performed, and corpus generation.

SET search_path = public;

CREATE TABLE retrieval_audit_log (
    id                    bigserial   PRIMARY KEY,
    timestamp             timestamptz NOT NULL DEFAULT now(),
    key_fingerprint       varchar(16) NOT NULL,
    query_hash            char(64)    NOT NULL,
    mode                  text        NOT NULL,
    k                     integer     NOT NULL,
    returned_chunk_ids    uuid[]      NOT NULL DEFAULT '{}',
    latency_ms            numeric(10, 2) NOT NULL,
    cache_hit             boolean     NOT NULL DEFAULT false,
    has_generated_answer  boolean     NOT NULL DEFAULT false,
    corpus_generation     integer     NOT NULL DEFAULT 1,

    CONSTRAINT ck_retrieval_audit_log_query_hash
        CHECK (query_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_retrieval_audit_log_mode
        CHECK (mode IN ('hybrid', 'dense', 'bm25')),
    CONSTRAINT ck_retrieval_audit_log_k
        CHECK (k > 0 AND k <= 100),
    CONSTRAINT ck_retrieval_audit_log_latency
        CHECK (latency_ms >= 0)
);

COMMENT ON TABLE  retrieval_audit_log IS 'Append-only forensic audit log of retrieval events (P1-1, OWASP LLM09).';
COMMENT ON COLUMN retrieval_audit_log.key_fingerprint IS 'Truncated SHA-256 fingerprint of the client API key; never the raw secret.';
COMMENT ON COLUMN retrieval_audit_log.query_hash IS 'SHA-256 hex digest of the normalized query text; plaintext is never stored.';
COMMENT ON COLUMN retrieval_audit_log.returned_chunk_ids IS 'Ordered list of chunk UUIDs served to the client.';

CREATE INDEX idx_retrieval_audit_log_timestamp
    ON retrieval_audit_log (timestamp DESC);

CREATE INDEX idx_retrieval_audit_log_key_timestamp
    ON retrieval_audit_log (key_fingerprint, timestamp DESC);

CREATE INDEX idx_retrieval_audit_log_query_hash
    ON retrieval_audit_log (query_hash);

-- Grant least-privilege permissions to the application role (docscout_app):
-- INSERT and SELECT permitted; NO UPDATE, NO DELETE, NO TRUNCATE.
GRANT SELECT, INSERT ON retrieval_audit_log TO docscout_app;
GRANT USAGE, SELECT ON SEQUENCE retrieval_audit_log_id_seq TO docscout_app;
