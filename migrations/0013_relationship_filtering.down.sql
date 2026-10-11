SET search_path = public;

DROP INDEX IF EXISTS idx_circular_citations_relation;
ALTER TABLE circular_citations DROP COLUMN IF EXISTS relation_type;

DROP TABLE IF EXISTS taxonomy_edges CASCADE;
