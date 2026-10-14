-- Rollback Migration 0041: Regulated Release Certification Pipeline (FEAT-056)

SET search_path = public;

DROP TABLE IF EXISTS release_certificates CASCADE;
