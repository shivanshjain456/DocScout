-- Revert 0002: restore the clock-derived default on chunks.chunk_id.
--
-- This does NOT rewrite existing rows. Chunks already stored keep their content-derived
-- identifiers; only newly inserted rows would revert to uuidv7(). A database that has been
-- down-migrated therefore holds a mix of stable and unstable identifiers, which is precisely
-- the state ADR-0005 rejects -- re-ingest from empty after reverting.

ALTER TABLE chunks ALTER COLUMN chunk_id SET DEFAULT uuidv7();

COMMENT ON COLUMN chunks.chunk_id IS NULL;
