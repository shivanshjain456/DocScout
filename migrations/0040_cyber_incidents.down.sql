-- Rollback Migration 0040: Regulatory Cyber Incident Response Playbook (FEAT-055)

SET search_path = public;

DROP TABLE IF EXISTS cyber_incidents CASCADE;
