-- Migration 0014: Staged ontology candidates table and review queue for FEAT-010

CREATE TABLE IF NOT EXISTS ontology_staging (
    candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    term VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    definition TEXT NOT NULL,
    domain VARCHAR(100) NOT NULL DEFAULT 'physical-and-regulated',
    domain_name VARCHAR(255) NOT NULL DEFAULT 'Physical & Regulated Systems',
    source_document_id UUID NULL,
    source_title VARCHAR(500) NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    confidence FLOAT NOT NULL DEFAULT 0.90,
    frequency INT NOT NULL DEFAULT 1,
    char_start INT NOT NULL DEFAULT 0,
    char_end INT NOT NULL DEFAULT 0,
    proposed_edges JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by VARCHAR(255) NULL,
    reviewer_notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    reviewed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_ontology_staging_status ON ontology_staging(status);
CREATE INDEX IF NOT EXISTS idx_ontology_staging_slug ON ontology_staging(slug);
CREATE INDEX IF NOT EXISTS idx_ontology_staging_source_doc ON ontology_staging(source_document_id);
