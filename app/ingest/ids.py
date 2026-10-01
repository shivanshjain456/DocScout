"""Content-derived identifiers for chunks.

A `chunk_id` is the foreign key that every citation, every gold-set item and every raw eval
output points at. It therefore has to mean the same thing on two machines, in two clones of
this repository, and before and after a re-ingest. The database default it replaces —
`uuidv7()` — guarantees the opposite: it mints a fresh identifier from the clock on every
insert, so re-ingesting byte-identical content produced 0 of 170 matching identifiers
(`docs/decisions/evidence/adr-0005-chunk-id-stability.txt`).

The obvious alternative, keeping `uuidv7()` and regenerating the gold set's citation IDs
after each ingest, was rejected: it makes a *past* eval report unverifiable, because the
identifiers in its raw output no longer resolve to anything. `EVAL_PROTOCOL.md` E-12 gates CI
on the mean of the last three baselines, so historical reports must stay auditable, and E-15
requires cited reports to survive. See ADR-0005.

The identity of a chunk is "this character range of this version of this document". The key
is therefore the version's payload hash plus the half-open character span, and deliberately
NOT the ordinal (which renumbers when the geometry changes) and NOT the chunker parameters
(two configurations that agree on a span agree on the chunk, and should say so).
"""

from __future__ import annotations

import re
from uuid import UUID, uuid5

# A fixed, documented namespace. Derived once from a URL under the project's own name so the
# constant itself is reproducible rather than arbitrary:
#     uuid5(uuid.NAMESPACE_URL, "https://docscout.invalid/chunk-id/v1")
# Changing this value re-identifies every chunk in the corpus and invalidates every committed
# citation, so it is pinned here and covered by a test (ADR-0005).
CHUNK_ID_NAMESPACE = UUID("4ffde409-1928-580a-9538-dfcee3b580f2")

# The schema's ck_versions_sha256_format constraint, enforced here too so a malformed hash
# fails at the point it would otherwise silently produce a plausible-looking identifier.
# Matched with `fullmatch`, NOT `match` against r"^...$": in Python `$` also matches just
# before a trailing newline, so "<64 hex>\n" passed and hashed to a different identifier than
# the same hash without it. A sha256 read from a file with `read()` rather than `.strip()`
# would have silently produced unresolvable citations.
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def chunk_id(version_sha256: str, char_start: int, char_end: int) -> UUID:
    """Return the stable identifier for one chunk of one document version.

    `version_sha256` is `document_versions.sha256`: the hash of the raw fetched payload, which
    FR-5 already treats as the identity of a version. `char_start`/`char_end` are the
    half-open span into that version's canonical extracted text, as stored on `chunks`.

    Raises `ValueError` rather than returning a wrong-but-valid UUID, because every failure
    mode here is silent: a bad hash or a reversed span still produces a well-formed
    identifier that simply points at nothing.
    """
    if not _SHA256_RE.fullmatch(version_sha256):
        raise ValueError(
            f"version_sha256 must be 64 lowercase hex characters, got {version_sha256!r}"
        )
    if char_start < 0:
        raise ValueError(f"char_start must be non-negative, got {char_start}")
    if char_end <= char_start:
        raise ValueError(f"char_end must exceed char_start, got [{char_start}, {char_end})")

    return uuid5(CHUNK_ID_NAMESPACE, f"{version_sha256}:{char_start}:{char_end}")
