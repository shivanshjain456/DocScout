-- Migration 0045: Hierarchical Structure-Aware Circular Chunking (FEAT-061)
-- Stores parent-child chunk links, statutory clause hierarchies, and proviso flags.

SET search_path = public;

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS parent_chunk_id UUID REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS clause_hierarchy TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS is_proviso BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(64) NOT NULL DEFAULT 'standard';

CREATE INDEX IF NOT EXISTS idx_chunks_parent_chunk_id
    ON chunks (parent_chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunks_is_proviso
    ON chunks (is_proviso) WHERE is_proviso = TRUE;

CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type
    ON chunks (chunk_type);
