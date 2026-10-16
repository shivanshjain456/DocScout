-- Migration 0030: Add control families, control count, and circular mappings to standards_registry for FEAT-041

ALTER TABLE standards_registry
ADD COLUMN IF NOT EXISTS control_families JSONB NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS control_count INT NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS mapped_circulars_count INT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_standards_control_families_gin
ON standards_registry USING GIN (control_families);
