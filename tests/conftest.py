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


# ---------------------------------------------------------------------------------------
# Serving API fixtures
#
# Shared here rather than in one test module because two suites now drive the API --
# tests/test_api.py and tests/test_metrics.py -- and importing a fixture across test
# modules shadows the parameter of the same name in every test that uses it.
# ---------------------------------------------------------------------------------------

# Composed from repeated characters on purpose. A realistic-looking random string here is
# indistinguishable from a leaked credential to a secret scanner -- gitleaks flagged an
# earlier version at entropy 4.45 -- and the right response is to make the fixture
# obviously fake rather than to blunt the scanner with an allowlist entry.
PRIMARY_KEY = "unit-test-key-" + "a" * 24
ROTATION_KEY = "unit-test-key-" + "b" * 24


def auth(key: str = PRIMARY_KEY) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture(scope="module")
def client(app_conn: psycopg.Connection[Any]) -> Iterator[Any]:
    """A live app, with the real database and the real embedding model.

    Module-scoped because the lifespan loads the encoder (~13 s) and builds the BM25 term
    table; paying that per test would make the suite unusable. Skips rather than fails when
    the corpus is absent, matching the rest of the suite.

    Keys are injected through the environment: `config.load_dotenv` uses `setdefault`, so a
    real environment variable always wins, which keeps the suite hermetic and means it
    never depends on, or reveals, the operator's actual key.
    """
    from fastapi.testclient import TestClient

    row = app_conn.execute("SELECT count(*) FROM chunks").fetchone()
    if not row or int(row[0]) == 0:  # pragma: no cover - environment guard
        pytest.skip("corpus not ingested; run `make ingest`")

    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    from app.api.app import app as fastapi_app

    with TestClient(fastapi_app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _fresh_rate_limiter() -> Iterator[None]:
    """The limiter is process-global; without this one test's burst fails the next."""
    from app.api import security

    security.rate_limiter.reset()
    yield
    security.rate_limiter.reset()
