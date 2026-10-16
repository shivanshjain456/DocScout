SET search_path = public;

DROP INDEX IF EXISTS idx_chunks_layer;
ALTER TABLE chunks DROP CONSTRAINT IF EXISTS ck_chunks_taxonomy_layer;
ALTER TABLE chunks DROP COLUMN IF EXISTS taxonomy_layer;
