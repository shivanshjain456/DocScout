-- Migration 0034: Rollback document_standard_mentions (FEAT-046)

SET search_path = public;

DROP TABLE IF EXISTS document_standard_mentions CASCADE;
