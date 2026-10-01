-- 0002: make chunks.chunk_id content-derived rather than clock-derived.
--
-- Why: chunk_id is the foreign key used by citations, gold-set items and raw eval outputs.
-- With DEFAULT uuidv7() the database mints a new identifier on every insert, so re-ingesting
-- byte-identical content produced 0 of 170 matching identifiers. That makes a past eval report
-- unverifiable, which breaks EVAL_PROTOCOL.md E-12 (the CI gate compares against the mean of the
-- last three baselines) and E-15 (a cited report must stay resolvable). See ADR-0005.
--
-- The default is DROPPED rather than replaced. There is no SQL expression for the new identifier:
-- it is uuid5(namespace, '<version sha256>:<char_start>:<char_end>'), computed by app/ingest/ids.py.
-- Leaving a working default in place would let a caller that forgets to supply the identifier
-- silently fall back to a non-reproducible one -- the exact failure this migration exists to end.
-- With no default, that mistake is a NOT NULL violation at the first insert.
--
-- documents.document_id and document_versions.version_id keep uuidv7(). They are internal surrogate
-- keys that are never published in a citation, so they keep the insert-locality benefit ADR-0004
-- recorded without carrying any reproducibility obligation.

ALTER TABLE chunks ALTER COLUMN chunk_id DROP DEFAULT;

COMMENT ON COLUMN chunks.chunk_id IS
    'Content-derived (ADR-0005): uuid5(CHUNK_ID_NAMESPACE, "<version sha256>:<char_start>:<char_end>"), '
    'supplied by app/ingest/ids.py. Stable across re-ingests and across machines; no database default '
    'exists on purpose, so a missing value fails loudly instead of becoming non-reproducible.';
