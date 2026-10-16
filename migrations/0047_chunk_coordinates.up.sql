-- Migration 0047: Bidirectional Character-Exact Offset Traceability Matrix (FEAT-063)
-- Stores physical PDF bounding boxes (72 DPI) mapped to character offsets.

SET search_path = public;

CREATE TABLE IF NOT EXISTS chunk_coordinates (
    id BIGSERIAL PRIMARY KEY,
    chunk_id UUID REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL DEFAULT 1,
    x0 DOUBLE PRECISION NOT NULL,
    y0 DOUBLE PRECISION NOT NULL,
    x1 DOUBLE PRECISION NOT NULL,
    y1 DOUBLE PRECISION NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunk_coordinates_chunk_id
    ON chunk_coordinates (chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunk_coordinates_page
    ON chunk_coordinates (page_number);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON chunk_coordinates TO docscout_app;
        GRANT USAGE, SELECT ON SEQUENCE chunk_coordinates_id_seq TO docscout_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON chunk_coordinates TO docscout;
        GRANT USAGE, SELECT ON SEQUENCE chunk_coordinates_id_seq TO docscout;
    END IF;
END $$;
