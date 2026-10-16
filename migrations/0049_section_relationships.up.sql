-- Migration 0049: Annexure, Schedule & FAQ Relational Association (FEAT-066)
-- Preserves relational hierarchy between primary statutory directives and subsidiary technical annexures.

SET search_path = public;

CREATE TABLE IF NOT EXISTS document_sections (
    section_id UUID PRIMARY KEY DEFAULT uuidv7(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
    section_identifier VARCHAR(128) NOT NULL,
    section_title TEXT NOT NULL,
    section_type VARCHAR(32) NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    parent_section_id UUID REFERENCES document_sections(section_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_sections_doc_ver
    ON document_sections (document_id, version_id);

CREATE INDEX IF NOT EXISTS idx_document_sections_type
    ON document_sections (section_type);

CREATE INDEX IF NOT EXISTS idx_document_sections_parent
    ON document_sections (parent_section_id);

CREATE TABLE IF NOT EXISTS section_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT uuidv7(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
    parent_section_id UUID NOT NULL REFERENCES document_sections(section_id) ON DELETE CASCADE,
    child_section_id UUID NOT NULL REFERENCES document_sections(section_id) ON DELETE CASCADE,
    relationship_type VARCHAR(32) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_section_relationships UNIQUE (parent_section_id, child_section_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_section_relationships_doc_ver
    ON section_relationships (document_id, version_id);

CREATE INDEX IF NOT EXISTS idx_section_relationships_parent
    ON section_relationships (parent_section_id);

CREATE INDEX IF NOT EXISTS idx_section_relationships_child
    ON section_relationships (child_section_id);

CREATE INDEX IF NOT EXISTS idx_section_relationships_type
    ON section_relationships (relationship_type);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON document_sections TO docscout_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON section_relationships TO docscout_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON document_sections TO docscout;
        GRANT SELECT, INSERT, UPDATE, DELETE ON section_relationships TO docscout;
    END IF;
END $$;
