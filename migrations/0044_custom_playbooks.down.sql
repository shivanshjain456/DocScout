-- Migration 0044 Down: Custom Enterprise Compliance Playbook Builder (FEAT-060)

SET search_path = public;

DROP TABLE IF EXISTS custom_playbook_templates CASCADE;
