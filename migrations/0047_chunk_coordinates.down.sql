-- Rollback Migration 0047: Bidirectional Character-Exact Offset Traceability Matrix (FEAT-063)

SET search_path = public;

DROP TABLE IF EXISTS chunk_coordinates;
