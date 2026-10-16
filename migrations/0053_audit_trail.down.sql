-- 0053 down: rollback cryptographic_audit_trail and audit_trail view.

SET search_path = public;

DROP VIEW IF EXISTS audit_trail CASCADE;
DROP TABLE IF EXISTS cryptographic_audit_trail CASCADE;
