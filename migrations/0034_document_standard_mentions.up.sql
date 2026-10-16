-- Migration 0034: ISO/NIST Clause Cross-Citation Hyperlinking (FEAT-046)
-- Creates relational storage for external standard entity mentions and control citations.

SET search_path = public;

CREATE TABLE IF NOT EXISTS document_standard_mentions (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_id UUID NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    standard_id VARCHAR(100) NOT NULL REFERENCES standards_registry(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    char_start INT NOT NULL,
    char_end INT NOT NULL,
    control_hint VARCHAR(100) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT ck_std_mentions_span CHECK (char_start >= 0 AND char_end > char_start),
    CONSTRAINT ck_std_mentions_text CHECK (length(raw_text) > 0)
);

CREATE INDEX IF NOT EXISTS idx_std_mentions_doc ON document_standard_mentions (document_id);
CREATE INDEX IF NOT EXISTS idx_std_mentions_chunk ON document_standard_mentions (chunk_id);
CREATE INDEX IF NOT EXISTS idx_std_mentions_standard ON document_standard_mentions (standard_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON document_standard_mentions TO docscout_app;
