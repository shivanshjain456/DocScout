-- Revert Migration 0045: Hierarchical Structure-Aware Circular Chunking (FEAT-061)

SET search_path = public;

DROP INDEX IF EXISTS idx_chunks_chunk_type;
DROP INDEX IF EXISTS idx_chunks_is_proviso;
DROP INDEX IF EXISTS idx_chunks_parent_chunk_id;

ALTER TABLE chunks
    DROP COLUMN IF EXISTS chunk_type,
    DROP COLUMN IF EXISTS is_proviso,
    DROP COLUMN IF EXISTS clause_hierarchy,
    DROP COLUMN IF EXISTS parent_chunk_id;
