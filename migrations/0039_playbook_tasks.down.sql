-- Rollback Migration 0039: Role-Based Compliance Task Routing (FEAT-054)

SET search_path = public;

DROP TABLE IF EXISTS playbook_tasks CASCADE;
