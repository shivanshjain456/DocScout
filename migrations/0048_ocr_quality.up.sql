-- Migration 0048: OCR Degradation & Confidence Scoring Pipeline (FEAT-064)
-- Adds confidence scoring and image pre-processing metadata to ocr_extractions.

SET search_path = public;

ALTER TABLE ocr_extractions
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NULL,
    ADD COLUMN IF NOT EXISTS is_degraded BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS preprocessing_applied JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_ocr_extractions_degraded
    ON ocr_extractions (is_degraded, confidence);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ocr_extractions TO docscout_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ocr_extractions TO docscout;
    END IF;
END $$;
