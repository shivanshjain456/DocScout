-- Rollback Migration 0038: Automated Stage Exit Criteria Validator (FEAT-053)

SET search_path = public;

DROP TABLE IF EXISTS stage_exit_validations CASCADE;
