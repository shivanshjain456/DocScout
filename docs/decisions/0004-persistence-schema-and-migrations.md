# ADR-0004: Bind the data model  -  three tables in Postgres, applied by plain-SQL migrations

- **Status:** accepted
- **Date:** 2026-10-01
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Binds:** `docs/architecture/ARCHITECTURE.md` §4 (was PROPOSED, "needs an ADR before it binds") and the HNSW-over-IVFFlat row in §6 (was PROPOSED)
- **Related:** `SPEC.md` FR-2, FR-3, FR-4, FR-5, FR-7, FR-9 · ADR-0002 (`D = 384`, 512-token ceiling) · ADR-0003 (1,000-char chunks, offset-preserving cleaning) · `SECURITY.md` least privilege · U-10, U-11, U-12
- **Evidence:** `migrations/0001_initial_schema.up.sql` · `tests/test_schema.py` (19 tests) · `docs/setup/verify/m1-schema-migration.txt`

## Context

ADR-0002 fixed the vector dimension and ADR-0003 fixed chunk geometry, which were the two
decisions gating the schema. Nothing in M2 can start until `documents`, `document_versions` and
`chunks` exist, and `ARCHITECTURE.md` §4 explicitly withheld binding force from its own table
sketch until an ADR existed. This is that ADR, and the schema it describes is applied and tested
against the live pgvector 18.4 instance rather than proposed on paper.

The governing idea is that **a rule enforced only in prose eventually stops being true.** Seven
documents assert things about this data  -  that a superseded version is retained, that a citation
resolves to a byte range, that embeddings are normalised, that chunks never exceed 512 tokens.
Each of those is a sentence somebody can forget. Where a constraint can enforce such a rule at
the cost of one line of DDL, this schema spends the line.

## Decision

Three tables in the existing Postgres 18.4 + pgvector 0.8.2 instance, created by
`migrations/0001_initial_schema.up.sql` and applied by `scripts/migrate.py`.

### What the schema enforces, and the requirement each constraint serves

| Constraint | Enforces |
|---|---|
| `uq_versions_sha256`  -  **globally** unique | FR-5: identical bytes are one version, whichever URL served them |
| `uq_documents_canonical_url` | FR-5, URL half |
| `ck_versions_char_count CHECK (char_count >= 500)` | FR-3: the ~227-char SEBI detail-page failure mode is unstorable |
| `uq_versions_one_current`  -  partial unique index `WHERE is_current` | FR-4: at most one current version per document |
| `fk_chunks_version ... ON DELETE RESTRICT` | FR-4: history cannot be cascaded away |
| `fk_chunks_version (document_id, version_id)`  -  **composite** | FR-7: the denormalised `document_id` cannot disagree with the version's owner |
| `ck_chunks_span CHECK (char_start >= 0 AND char_end > char_start)` | FR-7: offsets are a real range |
| `ck_chunks_token_ceiling CHECK (token_count <= 512)` | ADR-0002: a chunk the encoder would silently truncate cannot be stored |
| `ck_chunks_unit_norm CHECK (abs(vector_norm(embedding) - 1.0) < 1e-4)` | ADR-0002: all embeddings are L2-normalised |
| `vector(384)` | ADR-0002: the dimension is a one-way door, now closed |
| `GRANT SELECT, INSERT, UPDATE`  -  **no DELETE** | FR-4 + `SECURITY.md`: the service lacks the privilege to discard history |

Each row above has a test in `tests/test_schema.py` that asserts the database *refuses* the
forbidden thing. Three of the constraints were additionally mutation-checked: dropping
`ck_chunks_token_ceiling`, `ck_chunks_unit_norm` or `uq_versions_sha256` inside a rolled-back
transaction makes the previously-rejected row insert successfully, which proves the constraint  -
not something incidental  -  is what does the work.

### Choices inside that decision

**Primary keys are `uuid` defaulted to `uuidv7()`**, native in Postgres 18. Time-ordered UUIDs
append at the right edge of the B-tree instead of scattering. Published PG18 benchmarks at 50M
rows report the v7 primary-key index ~26% smaller, leaf density ~90% versus ~71%, leaf
fragmentation ~0% versus ~50%, and ordered scans roughly 3× faster than `uuidv4`. Those numbers
are *external and at a scale this project will not reach soon*  -  they are not a measurement of
DocScout. The reason to take v7 anyway is that it costs nothing: it is the same 16 bytes, the
same API, one word different in the DDL. The accepted tradeoff is that a v7 value leaks its
creation time, which is harmless here  -  `chunk_id` appears in citations alongside `fetch_ts` and
a public `published_date`, so the ingestion timestamp is already disclosed deliberately.

**`chunks.tsv` is a `GENERATED ALWAYS ... STORED` column**, not a trigger and not an inline
expression. It cannot drift from `text`, and `GENERATED ALWAYS` rejects direct writes (tested).
The configuration is the literal `'english'` because the one-argument `to_tsvector` is only
STABLE, not IMMUTABLE, and is therefore rejected in a generated column  -  verified against the
engine. `coalesce` is mandatory: a NULL anywhere in the expression nulls the whole vector.

**`chunks.embedding_model` is stored per chunk** and `NOT NULL` with no default. ADR-0002 called
the dimension a one-way door; recording which model produced each vector is what makes a partial
re-embedding auditable instead of invisible.

**`embedding` is `NOT NULL`.** `ARCHITECTURE.md` §3.1 already specifies that a document's
chunks and embeddings are written in one transaction, so there is no legitimate window in which
a chunk exists without a vector. Allowing NULL would permit a chunk that is lexically
retrievable but invisible to the dense arm  -  a silent recall hole rather than a loud failure.

### Index: HNSW, cosine, pgvector defaults

`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`,
plus `GIN` on `tsv`. Three sub-choices, stated separately because they have different strengths
of evidence:

- **HNSW over IVFFlat** is decided on structure, not measurement. IVFFlat must be trained on
  data that already exists and rebuilt as the corpus grows; DocScout's ingestion is incremental
  by design (NFR-8 idempotent re-runs), so an index requiring a training corpus up front is the
  wrong shape. HNSW also degrades more gracefully at the small sizes this corpus will occupy
  first. **At the current scale the choice is unmeasurable**  -  a few hundred rows are faster to
  scan sequentially than to index, and any benchmark here would be theatre.
- **`vector_cosine_ops` over `vector_ip_ops`.** For unit vectors the two rank identically and
  inner product is marginally cheaper, so the speed argument favours `ip`. Cosine is chosen
  anyway because it is self-correcting: if normalisation ever regresses, cosine still ranks by
  angle, whereas inner product silently starts ranking by magnitude. The `ck_chunks_unit_norm`
  CHECK makes that regression unlikely, and the reported `ip` advantage (~18% on a 1M-row
  IVFFlat index) is immaterial against a corpus three orders of magnitude smaller. Robustness
  beats a speedup that cannot be observed here.
- **`m = 16`, `ef_construction = 64` are pgvector's defaults, deliberately.** There is no
  evidence in this project for any other value, and inventing one would be cargo-cult tuning.
  Index parameters and retrieval depths interact, so they must be swept together by U-10.

## Migration tooling: plain SQL, not Alembic

`scripts/migrate.py` reads numbered `.up.sql`/`.down.sql` pairs. Alembic was rejected because it
requires SQLAlchemy, and this project talks to Postgres through psycopg3 directly: adding an ORM
and a migration engine to run three `CREATE TABLE`s would add two large dependencies, change the
locked dependency set that verification V5 pins at 169 packages, and interpose a Python DSL
between the reader and DDL whose entire value is constraints that must be read exactly as
written.

What a hand-rolled runner must still provide, because one without them is a liability  -  all four
verified by running them:

| Property | Mechanism | Verified |
|---|---|---|
| Serialisation | session-level advisory lock | concurrent runs block rather than interleave |
| Atomicity | one transaction per migration | a failure leaves no partial schema |
| Tamper detection | SHA-256 of each applied file | editing an applied migration reports `DRIFTED` and `up` refuses, exit 1 |
| Reversibility | required `.down.sql` per migration | `down --to 0` then `up` round-trips; suite green afterwards |

`down` refuses to run without an explicit `--to` (exit 2). The runner connects as
`MIGRATION_DATABASE_URL` (the owner) rather than `DATABASE_URL` (the application role), so the
role the service runs as has neither DDL nor DELETE privilege.

## Deltas from ARCHITECTURE.md §4  -  reality wins, written down

1. **`sha256` is globally unique, not `UNIQUE (document_id, sha256)` as §4 proposed.** The
   per-document form permits one payload to be stored under two documents, which is precisely
   the case FR-5's acceptance test forbids. The weaker constraint would have passed review and
   failed the requirement.
2. **`chunks` carries `document_id` as well as `version_id`.** §4 listed only `version_id`, but
   FR-7 says a chunk attaches *`document_id`, version and offsets*. It is denormalised for
   single-row citation resolution and made safe by the composite foreign key.
3. **`token_count` and `embedding_model` are new columns**, not in §4. They exist to enforce
   ADR-0002's token ceiling and to make re-embedding auditable.
4. **`http_status` and `pages` are nullable, and `source` admits `SYNTHETIC`.** The real
   `corpus/raw/manifest.json` contains the injection canary with no HTTP status and no page
   count. A CHECK of `('RBI','SEBI')` would have made the canary unstorable  -  and
   `EVAL_PROTOCOL.md` requires at least one canary in the gold set.

## Consequences

- **M1 item 5 is done** and `ARCHITECTURE.md` §4 moves from PROPOSED to VERIFIED. M2 ingestion
  is unblocked: its contract is now a table definition rather than a paragraph.
- **The ingest chunker inherits a precise obligation.** FR-7's property test passes only if
  `char_start`/`char_end` bracket the *stored* text exactly. Trimming whitespace from a chunk
  without advancing its start offset is the natural way to get this wrong, and the test catches
  it on both synthetic text and real corpus documents.
- **A migration can no longer be edited after it is applied.** Drift is reported and `up`
  refuses; changes require a new numbered migration.
- **Operational trigger  -  HNSW build memory.** `maintenance_work_mem` is 64 MB on this host. By
  ADR-0002's sizing the HNSW index is ~37 MB at 10k chunks, so builds fit today; past roughly
  15–20k chunks the build will spill to disk and slow sharply unless it is raised. Separately,
  the index here is created on an empty table; for a large initial bulk load the faster pattern
  is to drop the HNSW index, load, and recreate it.
- **The datastore ADR owed by §6 is still owed.** Postgres-and-pgvector-over-Elasticsearch-or-a-
  dedicated-vector-DB is recorded there as SPECIFIED with its rationale, and applying this
  schema deepens the commitment, but the rejected alternatives have not been argued in an ADR
  and this document does not pretend to have done it.
- **U-12 (supersession between different documents) is untouched.** `is_current` models
  supersession *within* one document only. A master circular replacing earlier ones has no
  representation here, by design, pending that decision.
- **U-11 (tables) is untouched.** `chunks.text` is flat text; nothing models a table cell.

## Amendment, 2026-10-02  -  `is_current` was modelled but never enforced in retrieval

This ADR gave `document_versions` an `is_current` flag and a partial unique index
guaranteeing one current version per document, and FR-4 made retention a guarantee: the
application role holds no DELETE, so a superseded version's chunks necessarily remain in
`chunks`. `store.py` demotes the previous version correctly on supersession.

Nothing in the retrieval path honoured it. `dense.py`, `lexical.py` and the metadata
hydration in `search.py` all selected from `chunks` with no join to `document_versions`,
so the moment a circular was amended its superseded text stayed retrievable and would be
served as though in force. Measured before the fix, by marking one version superseded in a
rolled-back transaction: **all ten of its chunks remained in the top ten**.

For a tool over RBI and SEBI circulars  -  documents that are amended and withdrawn as a
matter of routine, and whose withdrawal the gold set already asks about  -  this is the worst
failure mode available, and it was latent only because every ingested document currently
has exactly one version.

All three retrieval paths now join `document_versions` and filter on `is_current`. The
lexical arm excludes at **index build** rather than after scoring, because superseded terms
left in the table distort document frequency and average document length, which changes the
score of every *current* chunk  -  a subtler fault than returning the wrong row.

Retention is unaffected: the rows stay, they are simply not retrievable. A test asserts
both halves.

**Scaling note.** The dense filter is a post-filter on a column the HNSW index does not
cover, so at corpus scale pgvector may over-fetch to fill k. At 170 chunks the planner
chooses a sequential scan regardless. The remedy when that stops being true is
`hnsw.iterative_scan = relaxed_order`, or denormalising `is_current` onto `chunks` so a
partial index can carry it  -  not removing the predicate.

## Rejected alternatives

### A. Alembic / SQLAlchemy migrations

The default choice in the Python ecosystem, and genuinely better once a project has an ORM,
branching migration history, or autogeneration against declarative models. DocScout has none of
those: no ORM, one linear migration history, and a schema whose value is in constraints that
autogeneration does not produce. The cost is two heavyweight dependencies and a change to the
dependency set that V5 verifies. Revisit if the project adopts SQLAlchemy for the application
layer  -  at that point the asymmetry reverses.

### B. `bigint` identity primary keys

Smaller (8 bytes) and the fastest option for insert locality. Rejected because `chunk_id` is a
public identifier: it is returned in every citation (`SPEC.md` §4.3) and stored in evaluation
reports that must stay resolvable across re-ingestion. Sequential integers would make corpus
size and ingestion order inferable from an API response, and would collide if chunks were ever
generated outside a single database. UUIDv7 keeps most of the locality benefit at 16 bytes.

### C. `gen_random_uuid()` (UUIDv4)

The pre-PG18 default. Rejected for index locality with no compensating benefit: the only thing
v4 buys over v7 is hiding creation time, which this corpus does not need  -  the documents are
public and their fetch timestamps are stored in the adjacent column.

### D. A separate `embeddings` table, one row per chunk per model

More flexible: it would allow several embedding models to coexist and make re-embedding a pure
insert. Rejected as premature. ADR-0002 closed the model choice and U-1 blocks any hosted
alternative, so there is no second model to hold; the flexibility would be paid for now in every
join on the hot retrieval path. `chunks.embedding_model` records which model produced each
vector, which is the part of that flexibility actually needed today. Revisit if U-1 unblocks and
a second embedder becomes real.

### E. IVFFlat

Faster to build and smaller in memory, which matters at scale. Rejected because it requires
training data to exist before the index is created and re-training as the corpus grows, which
fits badly with incremental ingestion  -  and because its advantages appear at corpus sizes far
beyond the present one, where the choice would be made on measurement rather than, as now,
on shape.

### F. Trigger-maintained `tsv` instead of a generated column

The pre-PostgreSQL-12 pattern, still common. Rejected: a trigger can be dropped or can diverge
from the column it maintains, and it does not prevent a direct write of a bogus vector. A
generated column cannot drift and refuses direct writes, which the test suite confirms. The one
case that would force a trigger  -  a per-row language configuration  -  does not arise, because
ADR-0003 blanks non-Latin text at ingest and the corpus is English-dominant.

### G. Enforcing the requirements only in application code

The alternative that needs stating, because it is what usually happens. Validation in the
ingestion path is easier to write, easier to give a good error message, and easier to change.
It is also invisible to anything that does not go through that path  -  a backfill script, a
manual `psql` fix during an incident, a second service added later. FR-4's retention guarantee
in particular is one that a stressed operator at 2am would otherwise be able to violate with a
single `DELETE`. These constraints are cheap, and they hold regardless of who is writing.
