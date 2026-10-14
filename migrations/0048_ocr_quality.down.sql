-- Migration 0048 Down: Revert OCR quality columns from ocr_extractions

SET search_path = public;

DROP INDEX IF EXISTS idx_ocr_extractions_degraded;

ALTER TABLE ocr_extractions
    DROP COLUMN IF EXISTS preprocessing_applied,
    DROP COLUMN IF EXISTS is_degraded,
    DROP COLUMN IF EXISTS confidence;
