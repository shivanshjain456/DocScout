-- Migration 0025 Down: Revert Prescriptive Remediation Engine (FEAT-034)

DROP TABLE IF EXISTS remediation_audit_logs;
DROP TABLE IF EXISTS prescriptive_remediations;
