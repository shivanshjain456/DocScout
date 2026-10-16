-- Migration 0046: High-Fidelity Table Lineage and Matrix Parser (FEAT-062)
-- Stores extracted structured tables, cell coordinates, and JSONB representations.

SET search_path = public;

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS table_data_json JSONB NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_table_data_json
    ON chunks USING gin (table_data_json)
    WHERE table_data_json IS NOT NULL;

CREATE TABLE IF NOT EXISTS extracted_tables (
    table_id VARCHAR(64) PRIMARY KEY,
    doc_id VARCHAR(128) NOT NULL,
    chunk_id UUID REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL DEFAULT 1,
    headers JSONB NOT NULL DEFAULT '[]'::jsonb,
    matrix JSONB NOT NULL DEFAULT '[]'::jsonb,
    markdown_repr TEXT NOT NULL,
    json_repr JSONB NOT NULL DEFAULT '{}'::jsonb,
    cell_coordinates JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_extracted_tables_doc_id
    ON extracted_tables (doc_id);

CREATE INDEX IF NOT EXISTS idx_extracted_tables_chunk_id
    ON extracted_tables (chunk_id);

CREATE INDEX IF NOT EXISTS idx_extracted_tables_page_number
    ON extracted_tables (page_number);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON extracted_tables TO docscout_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON extracted_tables TO docscout;
    END IF;
END $$;
