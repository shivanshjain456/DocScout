-- Migration 0017: Statutory Parameters and Numerical Evidence Extractor for FEAT-026

CREATE TABLE IF NOT EXISTS statutory_parameters (
    id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL,
    version_id VARCHAR(64) NULL,
    parameter_name VARCHAR(255) NOT NULL,
    parameter_type VARCHAR(100) NOT NULL,
    numeric_value DOUBLE PRECISION NOT NULL,
    unit VARCHAR(50) NOT NULL,
    normalized_value DOUBLE PRECISION NOT NULL,
    normalized_unit VARCHAR(50) NOT NULL,
    comparison_operator VARCHAR(20) NOT NULL DEFAULT 'eq',
    threshold_ceiling DOUBLE PRECISION NULL,
    statutory_context TEXT NOT NULL,
    section_reference VARCHAR(150) NULL,
    char_start INTEGER NULL,
    char_end INTEGER NULL,
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_statutory_parameters_doc ON statutory_parameters(document_id);
CREATE INDEX IF NOT EXISTS idx_statutory_parameters_type ON statutory_parameters(parameter_type);
CREATE INDEX IF NOT EXISTS idx_statutory_parameters_norm_unit ON statutory_parameters(normalized_unit);
CREATE INDEX IF NOT EXISTS idx_statutory_parameters_norm_val ON statutory_parameters(normalized_value);
