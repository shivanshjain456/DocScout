-- Migration 0035: Rollback compliance_telemetry_events (FEAT-048)

SET search_path = public;

DROP TABLE IF EXISTS compliance_telemetry_events CASCADE;
