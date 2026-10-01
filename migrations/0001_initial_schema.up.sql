-- DocScout 0001: documents, document_versions, chunks.
--
-- Implements ARCHITECTURE.md §4 and binds it (ADR-0004). The design principle here is that
-- the schema enforces the specification wherever a constraint can do so cheaply, because a
-- rule that lives only in prose is a rule that silently stops being true. Each constraint
-- below names the requirement it enforces.
--
-- The `vector` type lives in the public schema (infra/initdb/01-extensions.sql). Any session
-- that narrows search_path away from public will fail to resolve it.

SET search_path = public;

-- ---------------------------------------------------------------------------------------
-- documents — one logical circular, stable across reissues.
-- ---------------------------------------------------------------------------------------
CREATE TABLE documents (
    document_id    uuid        PRIMARY KEY DEFAULT uuidv7(),
    canonical_url  text        NOT NULL,
    source         text        NOT NULL,
    title          text,
    authority      text,
    published_date date,
    detail_page    text,
    created_at     timestamptz NOT NULL DEFAULT now(),

    -- FR-5: de-duplication is by content hash first, then canonical URL. The URL half of
    -- that rule is enforced here; the content half is on document_versions.sha256.
    CONSTRAINT uq_documents_canonical_url UNIQUE (canonical_url),

    -- CORPUS_SPEC.md §2 host allowlist. SYNTHETIC is the injection canary, which is a real
    -- row because EVAL_PROTOCOL.md requires at least one canary in the gold set.
    CONSTRAINT ck_documents_source CHECK (source IN ('RBI', 'SEBI', 'SYNTHETIC'))
);

COMMENT ON TABLE  documents IS 'One logical regulatory circular, stable across reissues (ARCHITECTURE.md §4).';
COMMENT ON COLUMN documents.source IS 'RBI | SEBI | SYNTHETIC (injection canary).';

-- ---------------------------------------------------------------------------------------
-- document_versions — one observed byte-state of a document.
-- ---------------------------------------------------------------------------------------
CREATE TABLE document_versions (
    version_id   uuid        PRIMARY KEY DEFAULT uuidv7(),
    document_id  uuid        NOT NULL,
    sha256       char(64)    NOT NULL,
    fetch_ts     timestamptz NOT NULL,
    http_status  integer,
    bytes        integer     NOT NULL,
    pages        integer,
    extractor    text        NOT NULL,
    char_count   integer     NOT NULL,
    is_current   boolean     NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),

    -- FR-4: a superseded version MUST be retained. RESTRICT (not CASCADE) means deleting a
    -- document cannot silently take its history with it.
    CONSTRAINT fk_versions_document FOREIGN KEY (document_id)
        REFERENCES documents (document_id) ON DELETE RESTRICT,

    -- FR-5, content half: identical bytes are the same version no matter which URL served
    -- them. This is deliberately GLOBAL, not UNIQUE (document_id, sha256) as ARCHITECTURE.md
    -- §4 proposed -- the per-document form would happily store one payload under two
    -- documents, which is exactly the case FR-5's test forbids. Delta recorded in ADR-0004.
    CONSTRAINT uq_versions_sha256 UNIQUE (sha256),

    -- Target for the composite foreign key from chunks. Redundant with the primary key, but
    -- required so chunks can reference (document_id, version_id) as a pair.
    CONSTRAINT uq_versions_doc_version UNIQUE (document_id, version_id),

    CONSTRAINT ck_versions_sha256_hex   CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_versions_bytes        CHECK (bytes > 0),
    CONSTRAINT ck_versions_pages        CHECK (pages IS NULL OR pages > 0),
    CONSTRAINT ck_versions_http_status  CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),

    -- FR-3: a document extracting < 500 clean characters MUST be rejected, not ingested.
    CONSTRAINT ck_versions_char_count   CHECK (char_count >= 500)
);

-- FR-4: at most one current version per document. A partial unique index is the only way to
-- say "exactly one row may be true" without a trigger.
CREATE UNIQUE INDEX uq_versions_one_current
    ON document_versions (document_id)
    WHERE is_current;

COMMENT ON TABLE  document_versions IS 'One observed byte-state of a document; a changed sha256 at a known URL is a new row (FR-4).';
COMMENT ON COLUMN document_versions.sha256 IS 'Globally unique: identical bytes are one version regardless of URL (FR-5).';

-- ---------------------------------------------------------------------------------------
-- chunks — the retrievable unit.
-- ---------------------------------------------------------------------------------------
CREATE TABLE chunks (
    chunk_id        uuid        PRIMARY KEY DEFAULT uuidv7(),
    document_id     uuid        NOT NULL,
    version_id      uuid        NOT NULL,
    ordinal         integer     NOT NULL,
    text            text        NOT NULL,
    char_start      integer     NOT NULL,
    char_end        integer     NOT NULL,
    token_count     integer     NOT NULL,
    embedding_model text        NOT NULL,
    embedding       vector(384) NOT NULL,
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED,
    created_at      timestamptz NOT NULL DEFAULT now(),

    -- FR-7: a citation must resolve to a byte range in a SPECIFIC document version.
    -- document_id is denormalised so a citation is a single-row read, and the composite
    -- foreign key makes it impossible for that copy to disagree with the version's owner.
    CONSTRAINT fk_chunks_version FOREIGN KEY (document_id, version_id)
        REFERENCES document_versions (document_id, version_id) ON DELETE RESTRICT,

    CONSTRAINT uq_chunks_version_ordinal UNIQUE (version_id, ordinal),

    CONSTRAINT ck_chunks_ordinal CHECK (ordinal >= 0),
    CONSTRAINT ck_chunks_span    CHECK (char_start >= 0 AND char_end > char_start),
    CONSTRAINT ck_chunks_text    CHECK (length(text) > 0),

    -- ADR-0002: the embedder's context window is 512 tokens. A chunk above that is silently
    -- truncated by the encoder, leaving char_end claiming coverage of text the vector never
    -- saw. ADR-0003 requires ingest to hard-split instead; this makes the failure loud.
    CONSTRAINT ck_chunks_token_ceiling CHECK (token_count > 0 AND token_count <= 512),

    -- ADR-0002: all embeddings are L2-normalised. Tolerance is 1e-4 because float32 round
    -- trips land near 1.00000004, so a tighter bound would reject correct vectors.
    CONSTRAINT ck_chunks_unit_norm CHECK (abs(vector_norm(embedding) - 1.0) < 1e-4)
);

-- Dense arm (ARCHITECTURE.md §3.2). m and ef_construction are pgvector's defaults, held
-- deliberately until U-10 sweeps retrieval depths and index parameters together (ADR-0004).
CREATE INDEX idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Lexical arm (ARCHITECTURE.md §3.2). Queries MUST reference the tsv column itself; an
-- inline to_tsvector(...) in the predicate is a different expression and will not use this.
CREATE INDEX idx_chunks_tsv_gin ON chunks USING gin (tsv);

-- Citation resolution and per-document joins. (version_id is already covered as the leading
-- column of uq_chunks_version_ordinal.)
CREATE INDEX idx_chunks_document ON chunks (document_id);

COMMENT ON TABLE  chunks IS 'Retrievable span of one document version; geometry fixed by ADR-0003, D=384 by ADR-0002.';
COMMENT ON COLUMN chunks.embedding_model IS 'Model identity per chunk, so a re-embedding is auditable (ADR-0002 one-way door).';
COMMENT ON COLUMN chunks.tsv IS 'Generated, STORED. Config literal ''english'' is required: the 1-arg to_tsvector is only STABLE.';

-- ---------------------------------------------------------------------------------------
-- Least-privilege grants (infra/initdb/02-app-role.sh defers table grants to migrations).
-- ---------------------------------------------------------------------------------------
-- No DELETE, by design: FR-4 requires superseded versions and their chunks to be retained,
-- so the application role is not given the privilege needed to violate it. Removing corpus
-- data is an administrative act performed as the owner, not something the service can do.
GRANT SELECT, INSERT, UPDATE ON documents          TO docscout_app;
GRANT SELECT, INSERT, UPDATE ON document_versions  TO docscout_app;
GRANT SELECT, INSERT, UPDATE ON chunks             TO docscout_app;
