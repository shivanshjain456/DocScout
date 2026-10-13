-- Migration 0031: Create framework_control_crosswalk table for FEAT-042

CREATE TABLE IF NOT EXISTS framework_control_crosswalk (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_framework VARCHAR(64) NOT NULL,
    source_control_id VARCHAR(64) NOT NULL,
    source_clause_title VARCHAR(255) NOT NULL,
    target_framework VARCHAR(64) NOT NULL,
    target_control_id VARCHAR(64) NOT NULL,
    target_clause_title VARCHAR(255) NOT NULL,
    equivalence_level VARCHAR(16) NOT NULL CHECK (equivalence_level IN ('EXACT', 'SUBSET', 'SUPERSET')),
    citation_spans JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crosswalk_source ON framework_control_crosswalk(source_framework, source_control_id);
CREATE INDEX IF NOT EXISTS idx_crosswalk_target ON framework_control_crosswalk(target_framework, target_control_id);
CREATE INDEX IF NOT EXISTS idx_crosswalk_pair ON framework_control_crosswalk(source_framework, target_framework);
