-- Reverse of 0001_initial_schema.up.sql.
--
-- Dropped child-first. CASCADE is deliberately NOT used: if something outside this
-- migration has come to depend on these tables, the rollback should fail loudly rather
-- than quietly destroy it.

SET search_path = public;

REVOKE ALL ON chunks            FROM docscout_app;
REVOKE ALL ON document_versions FROM docscout_app;
REVOKE ALL ON documents         FROM docscout_app;

DROP TABLE chunks;
DROP TABLE document_versions;
DROP TABLE documents;
