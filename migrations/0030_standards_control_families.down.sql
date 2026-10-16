-- Migration 0030 rollback

DROP INDEX IF EXISTS idx_standards_control_families_gin;

ALTER TABLE standards_registry
DROP COLUMN IF EXISTS mapped_circulars_count,
DROP COLUMN IF EXISTS control_count,
DROP COLUMN IF EXISTS control_families;
