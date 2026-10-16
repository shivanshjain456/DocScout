-- 0013: relationship_filtering - taxonomy edges and relationship indexes (FEAT-008).
--
-- Why: Support filtering search retrieval by formal ontological relationships
-- (supersedes, requires, enables, complements, specializedBy) between regulatory
-- provisions, circulars, and taxonomy entities.

SET search_path = public;

CREATE TABLE IF NOT EXISTS taxonomy_edges (
    edge_id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node        text        NOT NULL,
    target_node        text        NOT NULL,
    relation_type      text        NOT NULL,
    chunk_id           uuid        REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    document_id        uuid        REFERENCES documents(document_id) ON DELETE CASCADE,
    is_synthetic       boolean     NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_taxonomy_edges_relation
        CHECK (relation_type IN ('supersedes', 'requires', 'enables', 'complements', 'specializedBy'))
);

COMMENT ON TABLE taxonomy_edges IS 'Directed semantic and ontological relationships between regulatory entities and provisions (FEAT-008).';
COMMENT ON COLUMN taxonomy_edges.relation_type IS 'Ontological relationship kind (supersedes, requires, enables, complements, specializedBy).';

-- Index for relationship-filtered queries (FEAT-008)
CREATE INDEX IF NOT EXISTS idx_taxonomy_edges_relation ON taxonomy_edges(relation_type);
CREATE INDEX IF NOT EXISTS idx_taxonomy_edges_chunk ON taxonomy_edges(chunk_id) WHERE chunk_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_taxonomy_edges_doc ON taxonomy_edges(document_id) WHERE document_id IS NOT NULL;

-- Optional relation_type column on circular_citations if not already present
ALTER TABLE circular_citations ADD COLUMN IF NOT EXISTS relation_type text DEFAULT 'supersedes';
CREATE INDEX IF NOT EXISTS idx_circular_citations_relation ON circular_citations(relation_type);

GRANT SELECT, INSERT, UPDATE ON taxonomy_edges TO docscout_app;
