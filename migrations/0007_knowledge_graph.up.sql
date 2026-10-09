-- 0007: knowledge_graph — lightweight entity graph over regulatory provisions (P2-2).
--
-- Why: Multi-hop compliance queries (e.g. cross-circular provision joins) fail under
-- single-pass lexical/vector retrieval because grouped citation scoring cannot join
-- provisions across documents. This migration stores an entity graph over provisions:
-- - `graph_nodes`: document, section, and provision entities with document provenance.
-- - `graph_edges`: grounded relationships ('cites', 'amends', 'supersedes', 'implements')
--   with character offset spans and chunk references.

SET search_path = public;

CREATE TABLE graph_nodes (
    node_id               text        PRIMARY KEY,
    node_type             text        NOT NULL,
    document_id           uuid        NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    label                 text        NOT NULL,
    char_start            integer     NOT NULL DEFAULT 0,
    char_end              integer     NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_graph_nodes_type
        CHECK (node_type IN ('document', 'section', 'provision')),
    CONSTRAINT ck_graph_nodes_offsets
        CHECK (char_start >= 0 AND char_end >= char_start)
);

COMMENT ON TABLE  graph_nodes IS 'Regulatory provision and document entity nodes (P2-2).';
COMMENT ON COLUMN graph_nodes.node_id IS 'Unique stable node identifier (e.g. doc:<uuid> or prov:<uuid>:<sec>).';
COMMENT ON COLUMN graph_nodes.node_type IS 'Entity type: document | section | provision.';

CREATE TABLE graph_edges (
    edge_id               uuid        PRIMARY KEY,
    source_node_id        text        NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
    target_node_id        text        NOT NULL REFERENCES graph_nodes(node_id) ON DELETE CASCADE,
    relation              text        NOT NULL,
    source_document_id    uuid        NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    target_document_id    uuid        REFERENCES documents(document_id) ON DELETE SET NULL,
    chunk_id              uuid        REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    char_start            integer     NOT NULL DEFAULT 0,
    char_end              integer     NOT NULL DEFAULT 0,
    evidence_text         text        NOT NULL DEFAULT '',
    created_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_graph_edges_relation
        CHECK (relation IN ('cites', 'amends', 'supersedes', 'implements', 'references')),
    CONSTRAINT ck_graph_edges_offsets
        CHECK (char_start >= 0 AND char_end >= char_start)
);

COMMENT ON TABLE  graph_edges IS 'Directed regulatory relationships between provisions and circulars (P2-2).';
COMMENT ON COLUMN graph_edges.relation IS 'Relationship type: cites | amends | supersedes | implements | references.';
COMMENT ON COLUMN graph_edges.evidence_text IS 'Exact textual passage expressing the relationship in the source document.';

-- Indices for rapid bidirectional graph traversal and chunk joins:
CREATE INDEX idx_graph_nodes_doc ON graph_nodes(document_id);
CREATE INDEX idx_graph_nodes_type ON graph_nodes(node_type);
CREATE INDEX idx_graph_edges_src ON graph_edges(source_node_id, relation);
CREATE INDEX idx_graph_edges_tgt ON graph_edges(target_node_id, relation);
CREATE INDEX idx_graph_edges_chunk ON graph_edges(chunk_id) WHERE chunk_id IS NOT NULL;
CREATE INDEX idx_graph_edges_src_doc ON graph_edges(source_document_id);
CREATE INDEX idx_graph_edges_tgt_doc ON graph_edges(target_document_id) WHERE target_document_id IS NOT NULL;

-- Initial bootstrap: create document-level nodes for all existing documents
INSERT INTO graph_nodes (node_id, node_type, document_id, label, char_start, char_end, created_at)
SELECT
    'doc:' || document_id::text,
    'document',
    document_id,
    COALESCE(title, source || ' Document ' || document_id::text),
    0,
    0,
    now()
FROM documents
ON CONFLICT (node_id) DO NOTHING;

-- Grant least-privilege permissions to docscout_app role (read/insert/update; no DELETE):
GRANT SELECT, INSERT, UPDATE ON graph_nodes TO docscout_app;
GRANT SELECT, INSERT, UPDATE ON graph_edges TO docscout_app;
