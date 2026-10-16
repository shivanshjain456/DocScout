-- Migration 0036: Rollback playbook workflows (FEAT-051)

SET search_path = public;

DROP TABLE IF EXISTS playbook_runs CASCADE;
DROP TABLE IF EXISTS playbook_templates CASCADE;
