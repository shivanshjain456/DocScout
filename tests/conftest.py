"""Shared database fixtures.

Both the schema tests and the ingestion tests need the same two connections — the owner,
which can create and drop things, and the least-privilege application role the service
actually runs as. Keeping one definition here means a change to how the suite reaches the
database cannot leave two files disagreeing about it.

Every fixture **skips** rather than fails when the database is unreachable or unmigrated.
A developer without Docker running should still get a useful signal from the pure-logic
tests instead of a wall of connection errors.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pgvector.psycopg import register_vector

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    """Fill os.environ from .env without overriding anything already set."""
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url(*names: str) -> str | None:
    """First non-empty value among `names`, after loading .env."""
    load_dotenv()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def connect_or_skip(url: str | None) -> psycopg.Connection[Any]:
    if not url:
        pytest.skip("no database URL configured")
    try:
        return psycopg.connect(url, connect_timeout=5)
    except psycopg.OperationalError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database not reachable: {exc}")


@pytest.fixture(scope="session")
def owner_conn() -> Iterator[psycopg.Connection[Any]]:
    """The migration/owner role. Skips if the schema has not been applied."""
    conn = connect_or_skip(database_url("MIGRATION_DATABASE_URL", "DATABASE_URL"))
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


@pytest.fixture(scope="session")
def app_conn() -> Iterator[psycopg.Connection[Any]]:
    """The least-privilege application role (`docscout_app`)."""
    url = database_url("DATABASE_URL")
    if not url or "docscout_app" not in url:
        pytest.skip("DATABASE_URL is not the least-privilege application role")
    conn = connect_or_skip(url)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def ingest_db(app_conn: psycopg.Connection[Any]) -> Iterator[psycopg.Connection[Any]]:
    """The least-privilege role, in a transaction that is always rolled back.

    Shared by the ingestion and identifier suites. Running these as `docscout_app` rather
    than as the owner is deliberate: it proves the write path needs only SELECT/INSERT/UPDATE,
    instead of proving it works with more privilege than production grants it.
    """
    register_vector(app_conn)
    with app_conn.transaction(force_rollback=True):
        yield app_conn
