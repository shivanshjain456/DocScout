"""Schema tests: every one of these asserts a requirement, not an implementation detail.

The schema created by `migrations/0001_initial_schema.up.sql` is built on the principle that
a rule enforced only in prose eventually stops being true. These tests check that the
database actually refuses the things the specification forbids — so if a future migration
relaxes a constraint, a requirement fails loudly instead of quietly.

Each test names the requirement it covers. They need the compose database to be up and
migrated; they skip (never fail) when it is not reachable, so the suite stays runnable in an
environment without Postgres.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus" / "raw"
EMBED_DIM = 384
TOKEN_CEILING = 512


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _load_dotenv() -> None:
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _url(*names: str) -> str | None:
    _load_dotenv()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _connect(url: str | None) -> psycopg.Connection[Any]:
    if not url:
        pytest.skip("no database URL configured")
    try:
        return psycopg.connect(url, connect_timeout=5)
    except psycopg.OperationalError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database not reachable: {exc}")


def unit_vector(seed: int, dim: int = EMBED_DIM) -> str:
    """A deterministic L2-normalised vector in pgvector's text form."""
    values = [((seed * 37 + i * 11) % 1000) / 1000.0 - 0.5 for i in range(dim)]
    norm = sum(v * v for v in values) ** 0.5
    return "[" + ",".join(f"{v / norm:.9f}" for v in values) + "]"


def chunk_with_offsets(
    text: str, size: int = 1000, overlap: int = 150
) -> list[tuple[int, int, str]]:
    """ADR-0003 geometry: fixed 1,000 chars, 150 overlap, whitespace boundaries.

    Offsets bracket the *stored* text exactly, which is what FR-7 means by "offsets
    re-extract to the stored text". Trimming the text without moving the offsets with it is
    the obvious way to get this subtly wrong.
    """
    out: list[tuple[int, int, str]] = []
    step = size - overlap
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", pos + step, end)
            if cut > pos:
                end = cut
        window = text[pos:end]
        lead = len(window) - len(window.lstrip())
        body = window.strip()
        if body:
            out.append((pos + lead, pos + lead + len(body), body))
        if end <= pos:
            break
        pos += step
    return out


def seed_document(
    conn: psycopg.Connection[Any],
    *,
    url: str,
    sha: str,
    char_count: int = 1200,
    source: str = "RBI",
) -> tuple[str, str]:
    """Insert one document + one current version. Returns (document_id, version_id)."""
    doc_id = conn.execute(
        "INSERT INTO documents (canonical_url, source, title) VALUES (%s, %s, %s) "
        "RETURNING document_id",
        (url, source, "Test circular"),
    ).fetchone()
    assert doc_id is not None
    version_id = conn.execute(
        "INSERT INTO document_versions "
        "(document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count) "
        "VALUES (%s, %s, now(), 200, 1000, 1, 'pypdf', %s) RETURNING version_id",
        (doc_id[0], sha, char_count),
    ).fetchone()
    assert version_id is not None
    return str(doc_id[0]), str(version_id[0])


def insert_chunk(
    conn: psycopg.Connection[Any],
    doc_id: str,
    version_id: str,
    *,
    ordinal: int = 0,
    text: str = "A chunk of regulatory text about KYC norms.",
    char_start: int = 0,
    char_end: int | None = None,
    token_count: int = 12,
    embedding: str | None = None,
) -> str:
    row = conn.execute(
        "INSERT INTO chunks (document_id, version_id, ordinal, text, char_start, char_end, "
        "token_count, embedding_model, embedding) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING chunk_id",
        (
            doc_id,
            version_id,
            ordinal,
            text,
            char_start,
            char_end if char_end is not None else char_start + len(text),
            token_count,
            "BAAI/bge-small-en-v1.5",
            embedding or unit_vector(ordinal + 1),
        ),
    ).fetchone()
    assert row is not None
    return str(row[0])


@contextmanager
def rejects(conn: psycopg.Connection[Any], exc_type: type[Exception]) -> Iterator[None]:
    """Assert the enclosed statement is rejected, without poisoning the outer transaction.

    A failed statement aborts its transaction, so every later statement in the same test
    would fail too. Running the expectation inside a nested transaction (a SAVEPOINT) rolls
    back only the failure and lets the test carry on asserting.
    """
    with pytest.raises(exc_type), conn.transaction():
        yield


def sha(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def owner_conn() -> Iterator[psycopg.Connection[Any]]:
    conn = _connect(_url("MIGRATION_DATABASE_URL", "DATABASE_URL"))
    try:
        applied = conn.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='chunks'"
        ).fetchone()
        if not applied or int(str(applied[0])) == 0:
            pytest.skip("schema not migrated; run `make migrate`")
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db(owner_conn: psycopg.Connection[Any]) -> Iterator[psycopg.Connection[Any]]:
    """Each test runs in a transaction that is always rolled back."""
    with owner_conn.transaction(force_rollback=True):
        yield owner_conn


# --------------------------------------------------------------------------------------
# the migration itself
# --------------------------------------------------------------------------------------
def test_migration_recorded_and_file_unchanged(owner_conn: psycopg.Connection[Any]) -> None:
    """The applied checksum still matches the file, so the schema on disk is the one running."""
    row = owner_conn.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = 1"
    ).fetchone()
    assert row is not None, "migration 0001 is not recorded as applied"
    on_disk = hashlib.sha256(
        (REPO_ROOT / "migrations" / "0001_initial_schema.up.sql").read_bytes()
    ).hexdigest()
    assert row[1] == on_disk, "0001 was edited after being applied; write a new migration"


# --------------------------------------------------------------------------------------
# FR-4 — supersession retains history and keeps chunk IDs resolvable
# --------------------------------------------------------------------------------------
def test_fr4_superseded_version_is_retained_and_chunk_ids_still_resolve(
    db: psycopg.Connection[Any],
) -> None:
    doc_id, v1 = seed_document(db, url="https://rbi.example/circ/1", sha=sha(1))
    old_chunk = insert_chunk(db, doc_id, v1, ordinal=0, text="Original text of the circular.")

    # A changed sha256 at a known URL creates a NEW version, not an update.
    db.execute("UPDATE document_versions SET is_current = false WHERE version_id = %s", (v1,))
    v2 = db.execute(
        "INSERT INTO document_versions "
        "(document_id, sha256, fetch_ts, http_status, bytes, pages, extractor, char_count, "
        " is_current) VALUES (%s, %s, now(), 200, 1100, 1, 'pypdf', 1300, true) "
        "RETURNING version_id",
        (doc_id, sha(2)),
    ).fetchone()
    assert v2 is not None
    new_chunk = insert_chunk(db, doc_id, str(v2[0]), ordinal=0, text="Revised text.")

    versions = db.execute(
        "SELECT count(*) FROM document_versions WHERE document_id = %s", (doc_id,)
    ).fetchone()
    assert versions is not None and int(str(versions[0])) == 2, "superseded version was lost"

    resolved = db.execute(
        "SELECT c.text, c.version_id, dv.is_current FROM chunks c "
        "JOIN document_versions dv USING (version_id) WHERE c.chunk_id = %s",
        (old_chunk,),
    ).fetchone()
    assert resolved is not None, "old chunk_id no longer resolves after supersession (FR-4)"
    assert resolved[0] == "Original text of the circular."
    assert resolved[2] is False
    assert old_chunk != new_chunk


def test_fr4_only_one_current_version_per_document(db: psycopg.Connection[Any]) -> None:
    doc_id, _ = seed_document(db, url="https://rbi.example/circ/2", sha=sha(3))
    with rejects(db, psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO document_versions "
            "(document_id, sha256, fetch_ts, bytes, extractor, char_count, is_current) "
            "VALUES (%s, %s, now(), 10, 'pypdf', 900, true)",
            (doc_id, sha(4)),
        )


def test_fr4_version_with_chunks_cannot_be_deleted(db: psycopg.Connection[Any]) -> None:
    """Retention is structural: the FK is RESTRICT, so history cannot be cascaded away."""
    doc_id, v1 = seed_document(db, url="https://rbi.example/circ/3", sha=sha(5))
    insert_chunk(db, doc_id, v1)
    # RESTRICT raises RestrictViolation (SQLSTATE 23001); NO ACTION would instead raise
    # ForeignKeyViolation (23503). Asserting the precise class is what proves the FK is
    # RESTRICT rather than merely deferred.
    with rejects(db, psycopg.errors.RestrictViolation):
        db.execute("DELETE FROM document_versions WHERE version_id = %s", (v1,))


# --------------------------------------------------------------------------------------
# FR-5 — de-duplication by content hash first, then canonical URL
# --------------------------------------------------------------------------------------
def test_fr5_identical_bytes_cannot_be_stored_twice(db: psycopg.Connection[Any]) -> None:
    """One payload fetched from two URLs must not become two stored versions."""
    _, _ = seed_document(db, url="https://rbi.example/a", sha=sha(10))
    other_doc = db.execute(
        "INSERT INTO documents (canonical_url, source) VALUES (%s, 'RBI') RETURNING document_id",
        ("https://rbi.example/b",),
    ).fetchone()
    assert other_doc is not None
    with rejects(db, psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO document_versions "
            "(document_id, sha256, fetch_ts, bytes, extractor, char_count) "
            "VALUES (%s, %s, now(), 10, 'pypdf', 900)",
            (other_doc[0], sha(10)),
        )


def test_fr5_canonical_url_is_unique(db: psycopg.Connection[Any]) -> None:
    seed_document(db, url="https://rbi.example/dup", sha=sha(11))
    with rejects(db, psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO documents (canonical_url, source) VALUES (%s, 'RBI')",
            ("https://rbi.example/dup",),
        )


# --------------------------------------------------------------------------------------
# FR-7 — offsets resolve to a byte range in a specific document version
# --------------------------------------------------------------------------------------
def test_fr7_chunk_cannot_belong_to_a_version_of_another_document(
    db: psycopg.Connection[Any],
) -> None:
    """The denormalised document_id cannot disagree with the version's owner."""
    doc_a, version_a = seed_document(db, url="https://rbi.example/x", sha=sha(20))
    doc_b, _ = seed_document(db, url="https://rbi.example/y", sha=sha(21))
    with rejects(db, psycopg.errors.ForeignKeyViolation):
        insert_chunk(db, doc_b, version_a)


def test_fr7_offsets_reextract_to_stored_text_synthetic(db: psycopg.Connection[Any]) -> None:
    source = (
        "The Reserve Bank of India has reviewed the extant guidelines on know your customer "
        "norms. 2. Accordingly, regulated entities shall put in place a board approved policy. "
        "3. These directions are issued under section 35A of the Banking Regulation Act, 1949. "
    ) * 6
    doc_id, version_id = seed_document(
        db, url="https://rbi.example/offsets", sha=sha(30), char_count=len(source)
    )
    spans = chunk_with_offsets(source)
    assert len(spans) >= 2, "fixture too small to exercise chunking"
    for ordinal, (start, end, body) in enumerate(spans):
        insert_chunk(
            db,
            doc_id,
            version_id,
            ordinal=ordinal,
            text=body,
            char_start=start,
            char_end=end,
            token_count=min(TOKEN_CEILING, max(1, len(body) // 4)),
        )
    rows = db.execute(
        "SELECT char_start, char_end, text FROM chunks WHERE version_id = %s ORDER BY ordinal",
        (version_id,),
    ).fetchall()
    assert len(rows) == len(spans)
    for start, end, text in rows:
        assert source[int(str(start)) : int(str(end))] == text, (
            f"offsets [{start},{end}) do not re-extract to the stored chunk text (FR-7)"
        )


@pytest.mark.skipif(
    not list(CORPUS_DIR.glob("*.txt")), reason="extracted corpus not present on this machine"
)
def test_fr7_offsets_reextract_on_real_corpus_documents(db: psycopg.Connection[Any]) -> None:
    """The same property, on real RBI/SEBI text with real ADR-0003 geometry."""
    files = sorted(CORPUS_DIR.glob("*.txt"))[:3]
    checked = 0
    for n, path in enumerate(files):
        source = path.read_text(encoding="utf-8", errors="replace")
        if len(source) < 500:
            continue
        doc_id, version_id = seed_document(
            db,
            url=f"https://rbi.example/real/{n}",
            sha=sha(100 + n),
            char_count=len(source),
        )
        for ordinal, (start, end, body) in enumerate(chunk_with_offsets(source)):
            insert_chunk(
                db,
                doc_id,
                version_id,
                ordinal=ordinal,
                text=body,
                char_start=start,
                char_end=end,
                token_count=min(TOKEN_CEILING, max(1, len(body) // 4)),
            )
            checked += 1
        rows = db.execute(
            "SELECT char_start, char_end, text FROM chunks WHERE version_id = %s", (version_id,)
        ).fetchall()
        for start, end, text in rows:
            assert source[int(str(start)) : int(str(end))] == text
    assert checked > 0, "no real corpus chunks were exercised"


# --------------------------------------------------------------------------------------
# FR-3 — documents below the extraction floor are rejected
# --------------------------------------------------------------------------------------
def test_fr3_short_extraction_is_rejected(db: psycopg.Connection[Any]) -> None:
    """The SEBI detail-page failure mode (~227 chars) must not be storable."""
    doc = db.execute(
        "INSERT INTO documents (canonical_url, source) VALUES "
        "('https://sebi.example/detail', 'SEBI') RETURNING document_id"
    ).fetchone()
    assert doc is not None
    with rejects(db, psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO document_versions "
            "(document_id, sha256, fetch_ts, bytes, extractor, char_count) "
            "VALUES (%s, %s, now(), 500, 'trafilatura', 227)",
            (doc[0], sha(40)),
        )


# --------------------------------------------------------------------------------------
# ADR-0002 / ADR-0003 — the decisions are enforced by the database, not by convention
# --------------------------------------------------------------------------------------
def test_adr0002_embedding_dimension_is_fixed_at_384(db: psycopg.Connection[Any]) -> None:
    doc_id, version_id = seed_document(db, url="https://rbi.example/dim", sha=sha(50))
    with rejects(db, psycopg.errors.DataException):
        insert_chunk(db, doc_id, version_id, embedding="[1,0,0]")


def test_adr0002_embeddings_must_be_l2_normalised(db: psycopg.Connection[Any]) -> None:
    doc_id, version_id = seed_document(db, url="https://rbi.example/norm", sha=sha(51))
    unnormalised = "[" + ",".join(["0.9"] * EMBED_DIM) + "]"
    with rejects(db, psycopg.errors.CheckViolation):
        insert_chunk(db, doc_id, version_id, embedding=unnormalised)


def test_adr0003_token_ceiling_is_enforced(db: psycopg.Connection[Any]) -> None:
    """A chunk the encoder would silently truncate must not be storable."""
    doc_id, version_id = seed_document(db, url="https://rbi.example/tok", sha=sha(52))
    with rejects(db, psycopg.errors.CheckViolation):
        insert_chunk(db, doc_id, version_id, token_count=TOKEN_CEILING + 1)
    # ...and the boundary value itself is accepted, so the bound is <=, not <.
    insert_chunk(db, doc_id, version_id, ordinal=1, token_count=TOKEN_CEILING)


def test_tsv_is_generated_and_not_writable(db: psycopg.Connection[Any]) -> None:
    doc_id, version_id = seed_document(db, url="https://rbi.example/tsv", sha=sha(53))
    insert_chunk(db, doc_id, version_id, text="The Bank issued revised directions on KYC.")
    row = db.execute(
        "SELECT tsv @@ websearch_to_tsquery('english', 'issue direction') FROM chunks "
        "WHERE version_id = %s",
        (version_id,),
    ).fetchone()
    assert row is not None and row[0] is True, "English stemming is not being applied to tsv"
    with rejects(db, psycopg.errors.GeneratedAlways):
        db.execute(
            "INSERT INTO chunks (document_id, version_id, ordinal, text, char_start, char_end, "
            "token_count, embedding_model, embedding, tsv) "
            "VALUES (%s, %s, 99, 'x', 0, 1, 1, 'm', %s, 'fake'::tsvector)",
            (doc_id, version_id, unit_vector(9)),
        )


# --------------------------------------------------------------------------------------
# FR-9 — both retrieval arms are usable against this schema
# --------------------------------------------------------------------------------------
def test_fr9_both_retrieval_arms_return_the_seeded_chunk(db: psycopg.Connection[Any]) -> None:
    doc_id, version_id = seed_document(db, url="https://rbi.example/arms", sha=sha(60))
    target = insert_chunk(
        db, doc_id, version_id, ordinal=0, text="Guidelines on digital lending by banks."
    )
    insert_chunk(db, doc_id, version_id, ordinal=1, text="Unrelated text about stamp duty.")

    lexical = db.execute(
        "SELECT chunk_id FROM chunks WHERE version_id = %s "
        "AND tsv @@ websearch_to_tsquery('english', 'digital lending') ",
        (version_id,),
    ).fetchall()
    assert [str(r[0]) for r in lexical] == [target], "lexical arm did not isolate the chunk"

    dense = db.execute(
        "SELECT chunk_id FROM chunks WHERE version_id = %s ORDER BY embedding <=> %s LIMIT 1",
        (version_id, unit_vector(1)),
    ).fetchall()
    assert len(dense) == 1, "dense arm returned nothing"


def test_hnsw_and_gin_indexes_exist_with_expected_configuration(
    owner_conn: psycopg.Connection[Any],
) -> None:
    rows = owner_conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE tablename = 'chunks' AND indexname IN "
        "('idx_chunks_embedding_hnsw','idx_chunks_tsv_gin')"
    ).fetchall()
    defs = {str(r[0]): str(r[1]) for r in rows}
    assert "idx_chunks_embedding_hnsw" in defs, "dense arm has no HNSW index"
    assert "hnsw" in defs["idx_chunks_embedding_hnsw"]
    assert "vector_cosine_ops" in defs["idx_chunks_embedding_hnsw"]
    assert re.search(r"m\s*=\s*'?16", defs["idx_chunks_embedding_hnsw"])
    assert "idx_chunks_tsv_gin" in defs, "lexical arm has no GIN index"
    assert "gin" in defs["idx_chunks_tsv_gin"]


# --------------------------------------------------------------------------------------
# SECURITY.md — least privilege is a property of the role, not a promise
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def app_conn() -> Iterator[psycopg.Connection[Any]]:
    url = _url("DATABASE_URL")
    if not url or "docscout_app" not in url:
        pytest.skip("DATABASE_URL is not the least-privilege application role")
    conn = _connect(url)
    try:
        yield conn
    finally:
        conn.close()


def test_application_role_cannot_delete_corpus_data(app_conn: psycopg.Connection[Any]) -> None:
    """FR-4 retention is enforced by privilege: the service cannot discard history."""
    with app_conn.transaction(force_rollback=True):
        for table in ("chunks", "document_versions", "documents"):
            with rejects(app_conn, psycopg.errors.InsufficientPrivilege):
                app_conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names


def test_application_role_cannot_change_the_schema(app_conn: psycopg.Connection[Any]) -> None:
    with rejects(app_conn, psycopg.errors.InsufficientPrivilege):
        app_conn.execute("CREATE TABLE should_not_exist (id int)")


def test_application_role_can_read_and_write_rows(app_conn: psycopg.Connection[Any]) -> None:
    with app_conn.transaction(force_rollback=True):
        row = app_conn.execute(
            "INSERT INTO documents (canonical_url, source) VALUES "
            "('https://rbi.example/app-role', 'RBI') RETURNING document_id"
        ).fetchone()
        assert row is not None, "application role cannot insert, which breaks ingestion"
