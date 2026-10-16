-- Migration 0043 Down: Digital Operational Resilience (DORA) Framework Runner (FEAT-058)

SET search_path = public;

DROP TABLE IF EXISTS resilience_tests CASCADE;
DROP TABLE IF EXISTS dora_systems CASCADE;
