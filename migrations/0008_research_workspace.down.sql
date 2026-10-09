-- 0008: rollback research_workspace tables (P2-3).
SET search_path = public;

DROP TABLE IF EXISTS research_artifacts CASCADE;
DROP TABLE IF EXISTS workspaces CASCADE;
