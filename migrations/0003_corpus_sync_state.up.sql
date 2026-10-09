-- 0003: corpus_sync_state — durable regulatory freshness tracking (P0-2).
--
-- Why: RBI and SEBI amend and withdraw circulars continuously. Stale retrieval is the
-- primary catastrophic failure for regulatory RAG. Before this migration, the service had
-- no record of when the corpus was last checked or refreshed against the regulatory sources,
-- and /healthz could not distinguish a corpus refreshed today from one untouched for weeks.
--
-- This table stores a singleton row (id = 1) recording:
-- - `last_checked_at`: when the corpus manifest / sources were last verified or fetched
-- - `last_manifest_sha`: content hash of the corpus manifest at the time of check
-- - `check_status`: 'ok' | 'warning' | 'error' | 'manifest_changed'
-- - `documents_checked`, `documents_current`, `documents_superseded`: live version counts
-- - `details`: structured metadata from the refresh run
-- - `updated_at`: record modification timestamp
--
-- Enforces singleton cardinality at the database level: a check constraint `id = 1`
-- ensures exactly one current sync state exists, making reads sub-millisecond and atomic.

SET search_path = public;

CREATE TABLE corpus_sync_state (
    id                    integer     PRIMARY KEY DEFAULT 1,
    last_checked_at       timestamptz NOT NULL,
    last_manifest_sha     char(64),
    check_status          text        NOT NULL DEFAULT 'ok',
    documents_checked     integer     NOT NULL DEFAULT 0,
    documents_current     integer     NOT NULL DEFAULT 0,
    documents_superseded  integer     NOT NULL DEFAULT 0,
    details               jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_corpus_sync_state_single_row
        CHECK (id = 1),
    CONSTRAINT ck_corpus_sync_state_manifest_sha
        CHECK (last_manifest_sha IS NULL OR last_manifest_sha ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_corpus_sync_state_status
        CHECK (check_status IN ('ok', 'warning', 'error', 'manifest_changed')),
    CONSTRAINT ck_corpus_sync_state_counts
        CHECK (documents_checked >= 0 AND documents_current >= 0 AND documents_superseded >= 0)
);

COMMENT ON TABLE  corpus_sync_state IS 'Singleton operational sync and freshness state of the regulatory corpus (P0-2).';
COMMENT ON COLUMN corpus_sync_state.last_checked_at IS 'Timestamp of the most recent corpus refresh or verification run.';
COMMENT ON COLUMN corpus_sync_state.check_status IS 'ok | warning | error | manifest_changed';

-- Bootstrap initial row from existing corpus state so /healthz and /metrics immediately
-- reflect live counts without requiring a manual update.
INSERT INTO corpus_sync_state (
    id,
    last_checked_at,
    check_status,
    documents_checked,
    documents_current,
    documents_superseded,
    details,
    updated_at
)
SELECT
    1,
    COALESCE((SELECT max(fetch_ts) FROM document_versions), now()),
    'ok',
    (SELECT count(*) FROM documents),
    (SELECT count(*) FROM document_versions WHERE is_current),
    (SELECT count(*) FROM document_versions WHERE NOT is_current),
    '{"bootstrapped_by": "migration_0003"}'::jsonb,
    now()
ON CONFLICT (id) DO NOTHING;

-- Grant least-privilege permissions to the application role (docscout_app):
-- Read, insert, and update permitted; no DELETE.
GRANT SELECT, INSERT, UPDATE ON corpus_sync_state TO docscout_app;
