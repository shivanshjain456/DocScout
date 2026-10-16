-- Migration 0049 Down: Revert section relationships (FEAT-066)

SET search_path = public;

DROP TABLE IF EXISTS section_relationships CASCADE;
DROP TABLE IF EXISTS document_sections CASCADE;
