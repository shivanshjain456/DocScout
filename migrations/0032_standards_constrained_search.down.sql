-- Migration 0032 Down: Drop indices and columns for FEAT-044

DROP INDEX IF EXISTS idx_crosswalk_standard_id;
DROP INDEX IF EXISTS idx_crosswalk_chunk_id;
DROP INDEX IF EXISTS idx_crosswalk_standard_chunk;

ALTER TABLE framework_control_crosswalk DROP COLUMN IF EXISTS chunk_id;
ALTER TABLE framework_control_crosswalk DROP COLUMN IF EXISTS standard_id;
