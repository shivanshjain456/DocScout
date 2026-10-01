# ADR-0005: Derive `chunk_id` from content, so a citation means the same thing twice

- **Status:** accepted
- **Date:** 2026-10-01
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Amends:** ADR-0004, which chose `uuidv7()` for all three primary keys. That choice stands for `documents.document_id` and `document_versions.version_id` and is reversed for `chunks.chunk_id` only.
- **Related:** `EVAL_PROTOCOL.md` §2.1 (`required_citation_chunk_ids`), E-7 (chunk-ID stability), E-12 (CI gate over the last three baselines), E-13/E-15 (run artifacts must stay resolvable) · `SPEC.md` FR-4, FR-5, FR-7, FR-14 · ADR-0003 (chunk geometry)
- **Evidence:** `docs/decisions/evidence/adr-0005-chunk-id-stability.txt` · `migrations/0002_chunk_id_content_derived.up.sql` · `app/ingest/ids.py` · `tests/test_ids.py`

## Context

`EVAL_PROTOCOL.md` §2.1 makes `required_citation_chunk_ids` a field of every gold-set item, and
E-7 already warns that gold items break when the chunker changes. The warning understates the
problem. Under schema 0001 the gold set breaks when **nothing** changes.

`chunks.chunk_id` was `uuid PRIMARY KEY DEFAULT uuidv7()`, so the database minted an identifier
from the clock at insert time. Ingesting the same 21 documents into an empty database twice
produced **0 of 170 matching identifiers** — identical bytes, identical extracted text, identical
character spans, 170 different primary keys. The measurement is in the evidence file.

Three things depend on that identifier and all three were quietly broken:

1. **The gold set.** It is described as the crown-jewel committed artifact. Committing 120 items
   whose citation IDs stop resolving the next time anyone re-ingests makes it a liability.
2. **Past eval reports.** E-12 fails CI on a regression against *the mean of the last three
   baselines*, and E-15 requires a cited report to stay resolvable. A raw output naming chunk
   `01a0f888-…` is unauditable once that row no longer exists.
3. **The quickstart.** Artifact (2) of the project's priorities is a sub-ten-minute one-command
   start. A newcomer who clones, ingests and runs the evals must get the committed gold set's
   citations resolving against *their* database, not a re-resolution step they have to discover.

This was found by trying to author the gold set and asking what its foreign keys point at.

## Decision

**`chunk_id = uuid5(CHUNK_ID_NAMESPACE, "<version sha256>:<char_start>:<char_end>")`**, computed
in `app/ingest/ids.py` and supplied by the ingester. Migration 0002 **drops** the column default.

The key is the identity of the thing: *this character range of this version of this document*.
The version hash is already FR-5's definition of a version's identity, and the half-open span is
already what FR-7 requires to be re-derivable. Nothing else is needed to say which chunk this is.

| Property | Consequence |
|---|---|
| Same content, any machine, any re-ingest | Same identifier — 170/170 verified across two cold ingests, on a different engine version than the one that produced the M2 evidence |
| Two chunk geometries that agree on a span | Agree on the identifier, which is correct: it is the same text of the same document |
| Any geometry change that moves a boundary | New identifier, so E-7's re-pinning requirement becomes a loud failure instead of a silent re-point to different text |
| Ordinal deliberately excluded | Ordinals renumber when geometry changes even for chunks whose text is untouched |
| Chunker parameters deliberately excluded | Including them would churn identifiers on a tokenizer swap that moved no boundary |

**The default is dropped, not replaced.** There is no SQL expression for this value, and leaving
`uuidv7()` in place as a fallback would let a caller that forgets to supply the identifier
silently reintroduce exactly the defect being fixed. With no default, that mistake is a
`NOT NULL` violation on the first insert. The down migration restores the default and says in
its own comment that a reverted database must be re-ingested from empty, because the alternative
is a table holding a mix of stable and unstable identifiers.

`documents.document_id` and `document_versions.version_id` keep `uuidv7()`. They are internal
surrogate keys, never published in a citation, and so carry ADR-0004's insert-locality benefit
without any reproducibility obligation.

## Consequences

**What this costs.** ADR-0004 chose `uuidv7()` partly on credativ's 50-million-row benchmark:
inserts 1:46 against 20:39, primary-key index 1,504 MB against 1,981 MB, leaf fragmentation 0
against 50%. A v5 identifier is random, so `chunks` gives those up. At the measured corpus — 170
chunks, and a target in the low tens of thousands — the effect is unmeasurable, and the ingest
is a 41-second batch job run from a CLI, not a latency-sensitive write path. If `chunks` ever
reaches a scale where index locality on insert matters, the honest fix is a separate
monotonic surrogate key with `chunk_id` kept as the published identifier, not a return to
unstable citations. **This is a judgement about scale, and the scale is recorded so the
judgement can be rechecked rather than inherited.**

**What this buys beyond the gold set.** The identifier is now computable from the corpus alone,
with no database: `uuid5(ns, f"{sha256}:{start}:{end}")` where the hash comes from the tracked
`corpus/raw/manifest.json`. The gold-set linter therefore validates committed citation IDs
without a running Postgres, and a citation in a bug report still resolves after a redeploy.

**What still breaks, honestly.** A new *version* of a document gets a new hash and therefore new
chunk IDs for every chunk, including text that did not change. That is intended — FR-4 requires
old chunk IDs to stay resolvable, and they do, because the old version's rows are retained and
`ON DELETE RESTRICT` prevents their removal. A citation names the version it was made against.

**The namespace constant is load-bearing.** Changing `CHUNK_ID_NAMESPACE` re-identifies every
chunk in the corpus and invalidates every committed citation. It is pinned in code, derived
reproducibly as `uuid5(NAMESPACE_URL, "https://docscout.invalid/chunk-id/v1")`, and a test
asserts both the derivation and a frozen known-answer vector — a first draft of this ADR shipped
a hand-typed constant that did not match its own documented derivation, which the test now makes
impossible.

## Rejected alternatives

### A. Keep `uuidv7()` and regenerate the gold set's citation IDs after every ingest

The smallest change, and it was the first plan. Rejected because it fixes the gold set and
leaves the reports broken. E-12 compares against the last three baselines and E-15 requires
cited reports to resolve; under this option the raw outputs of run *N−3* name identifiers that
no longer exist, so the gate's history can never be audited — only trusted. It also pushes a
mandatory re-resolution step into the quickstart, where every added step is a place to lose a
reader. "Regenerate it" also quietly assumes the regeneration is correct, which is the thing a
stable identifier would have let us check.

### B. Gold items cite `(canonical_url, char_start, char_end)` and never use `chunk_id`

Genuinely attractive: span citations are chunker-independent, so a chunk-size A/B could reuse
one gold set unchanged, and scoring becomes a span-overlap test. Rejected for now because it
changes what the system is measured on. `EVAL_PROTOCOL.md` §2.1 specifies chunk IDs, the API
returns chunk IDs (FR-14), and an overlap-based scorer needs its own threshold — how much
overlap counts as a hit — which is a new tunable knob invented at the exact moment the project
needs its numbers to be boring and defensible. Content-derived IDs deliver most of the benefit
with no new knob: the span *is* the key, so the mapping from span to ID is a pure function
available to any future span-based scorer. **If the chunk-size A/B in `EVAL_PROTOCOL.md` §8.1
turns out to need one gold set across geometries, this becomes the right answer and the
migration path is already open** — re-resolve spans to IDs per configuration.

### C. A monotonic integer or a `(version_id, ordinal)` composite key

Compact, naturally ordered, and the classic relational choice. Rejected on two counts. A
sequence is assigned at insert, so it is as unstable as `uuidv7()`. The composite is stable only
while ordinals are, and ordinals renumber whenever chunk geometry shifts — the very event E-7 is
about. A composite key also makes a citation a pair rather than an opaque token, which pushes
the join into every API response, log line and bug report that wants to name a chunk.

### D. Hash the chunk *text* instead of the span

`sha256(chunk_text)` is appealingly direct and is what a content-addressed store would do.
Rejected because the corpus contains repeated text: boilerplate headers, standard annexures and
the overlap region that ADR-0003 deliberately duplicates between adjacent chunks. Two distinct
chunks can share text, and a primary key collision would surface as a `UniqueViolation` during
ingest of a perfectly valid document. The span disambiguates them by construction.

### E. Put the chunker parameters into the key

Considered seriously, because it makes a geometry change provably re-identify everything and so
enforces E-7 maximally. Rejected because it over-fires: swapping the embedding model changes the
tokenizer and therefore the parameter set, which would churn every identifier even where no
chunk boundary moved. The span already changes whenever a boundary changes, which is the event
that actually matters, and it stays quiet when nothing moves.

### F. Do nothing until the gold set is written, then decide

The status-quo option. Rejected because the cost of this change rises monotonically with the
number of committed artifacts that reference chunk IDs. Today the correct count of affected
committed citations is zero, so the migration is a dropped default and a pure function. After
120 gold items and three baseline reports it is a data migration plus a re-pinning exercise plus
an invalidated history. This is the cheapest moment this decision will ever have.
