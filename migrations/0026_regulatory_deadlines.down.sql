-- Migration 0026 Down: Revert Regulatory Deadlines (FEAT-035)

DROP TABLE IF EXISTS deadline_alert_history;
DROP TABLE IF EXISTS regulatory_deadlines;
