-- Migration 0037 Down: Drop playbook_milestones table

SET search_path = public;

DROP TABLE IF EXISTS playbook_milestones CASCADE;
