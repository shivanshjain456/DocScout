-- 0011: circular_citations - explicit circular citation lineage graph (FEAT-005).
--
-- Why: Formal cross-document statutory references (e.g. 'DBOD.No.BP.BC...',
-- 'RBI/2022-23/111') must be extracted and resolved to construct an explicit
-- regulatory lineage and citation lineage graph.

SET search_path = public;

CREATE TABLE circular_citations (
    citation_id           uuid        PRIMARY KEY,
    source_document_id    uuid        NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    target_circular_no    text        NOT NULL,
    target_document_id    uuid        REFERENCES documents(document_id) ON DELETE SET NULL,
    raw_citation_span     text        NOT NULL,
    char_start            integer     NOT NULL DEFAULT 0,
    char_end              integer     NOT NULL DEFAULT 0,
    is_synthetic          boolean     NOT NULL DEFAULT false,
    created_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_circular_citations_offsets
        CHECK (char_start >= 0 AND char_end >= char_start)
);

COMMENT ON TABLE circular_citations IS 'Formal statutory circular citations and cross-references (FEAT-005).';
COMMENT ON COLUMN circular_citations.target_circular_no IS 'Canonical cited statutory circular number identifier.';
COMMENT ON COLUMN circular_citations.raw_citation_span IS 'Exact raw citation text excerpt from source document.';

CREATE INDEX idx_circular_citations_src ON circular_citations(source_document_id);
CREATE INDEX idx_circular_citations_target_doc ON circular_citations(target_document_id) WHERE target_document_id IS NOT NULL;
CREATE INDEX idx_circular_citations_no ON circular_citations(target_circular_no);

GRANT SELECT, INSERT, UPDATE ON circular_citations TO docscout_app;
