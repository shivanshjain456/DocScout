-- Migration 0032: Standards-Constrained Search & Control Crosswalk Foreign Keys for FEAT-044

-- Add standard_id and chunk_id columns to framework_control_crosswalk if they do not already exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'framework_control_crosswalk' AND column_name = 'standard_id'
    ) THEN
        ALTER TABLE framework_control_crosswalk
        ADD COLUMN standard_id VARCHAR(100) NULL REFERENCES standards_registry(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'framework_control_crosswalk' AND column_name = 'chunk_id'
    ) THEN
        ALTER TABLE framework_control_crosswalk
        ADD COLUMN chunk_id UUID NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE;
    END IF;
END $$;

-- Composite and single-column indices for sub-millisecond standard-constrained retrieval filtering
CREATE INDEX IF NOT EXISTS idx_crosswalk_standard_chunk ON framework_control_crosswalk(standard_id, chunk_id);
CREATE INDEX IF NOT EXISTS idx_crosswalk_chunk_id ON framework_control_crosswalk(chunk_id);
CREATE INDEX IF NOT EXISTS idx_crosswalk_standard_id ON framework_control_crosswalk(standard_id);

-- Explicit grants for the application runtime role
GRANT SELECT, INSERT, UPDATE, DELETE ON framework_control_crosswalk TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON standards_registry TO docscout_app;
