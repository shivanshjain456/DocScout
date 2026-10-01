#!/usr/bin/env python3
"""Apply DocScout's SQL migrations.

Deliberately not Alembic. Alembic requires SQLAlchemy, and this project talks to Postgres
through psycopg3 directly (`pyproject.toml`); adding an ORM and its migration engine to run
three CREATE TABLEs would add two large dependencies, change the locked dependency set that
verification V5 pins at 169 packages, and put a Python DSL between the author and the DDL for
a schema whose whole point is constraints that must be read exactly as written. Recorded in
ADR-0004.

What this does provide, because a migration runner without them is a liability:

- **Serialisation.** A session-level advisory lock, so two concurrent runs cannot interleave.
- **Tamper detection.** Each applied migration's SHA-256 is stored; editing a file after it
  has been applied is reported as drift rather than silently ignored.
- **Atomicity.** One transaction per migration. Postgres DDL is transactional, so a failure
  leaves no half-applied schema.
- **Honest status.** `status` reports pending, applied and drifted without changing anything.

Usage:
    uv run python scripts/migrate.py status
    uv run python scripts/migrate.py up
    uv run python scripts/migrate.py down --to 0
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"

# Arbitrary but stable, and hard-coded so it can never drift between versions of this
# script: it distinguishes DocScout's migration lock from any other advisory lock taken on
# the same database. Must fit in a signed 64-bit integer.
ADVISORY_LOCK_KEY = 7_314_825_190_112_233

FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up_path: Path
    down_path: Path
    checksum: str


def load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without adding a dependency.

    Only fills variables that are not already set, so a real environment always wins.
    """
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url() -> str:
    """Connection string for DDL.

    Prefers MIGRATION_DATABASE_URL (the table owner) over DATABASE_URL (the least-privilege
    application role). The split is the point: the role the service runs as has no DDL
    privilege and no DELETE, so it cannot alter or discard the schema it reads. Falling back
    to DATABASE_URL keeps a single-role setup working, where it will simply fail on the
    first CREATE TABLE rather than appear to succeed.
    """
    load_dotenv(REPO_ROOT / ".env")
    for name in ("MIGRATION_DATABASE_URL", "DATABASE_URL"):
        url = os.environ.get(name, "").strip()
        if url:
            return url
    raise SystemExit(
        "Neither MIGRATION_DATABASE_URL nor DATABASE_URL is set. Expected one in the "
        "environment or in .env (which is gitignored). Nothing was changed."
    )


def discover() -> list[Migration]:
    """Find migration pairs on disk, ordered by version."""
    if not MIGRATIONS_DIR.is_dir():
        raise SystemExit(f"no migrations directory at {MIGRATIONS_DIR}")

    ups: dict[int, tuple[str, Path]] = {}
    downs: dict[int, Path] = {}
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        match = FILENAME_RE.match(path.name)
        if not match:
            continue
        version, name, direction = int(match.group(1)), match.group(2), match.group(3)
        if direction == "up":
            ups[version] = (name, path)
        else:
            downs[version] = path

    migrations: list[Migration] = []
    for version in sorted(ups):
        name, up_path = ups[version]
        down_path = downs.get(version)
        if down_path is None:
            raise SystemExit(f"migration {version:04d}_{name} has no .down.sql; refusing to run")
        migrations.append(
            Migration(
                version=version,
                name=name,
                up_path=up_path,
                down_path=down_path,
                checksum=hashlib.sha256(up_path.read_bytes()).hexdigest(),
            )
        )
    return migrations


def ensure_tracking_table(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     integer     PRIMARY KEY,
            name        text        NOT NULL,
            checksum    char(64)    NOT NULL,
            applied_at  timestamptz NOT NULL DEFAULT now(),
            duration_ms integer     NOT NULL
        )
        """
    )
    conn.commit()


def applied_map(conn: psycopg.Connection[tuple[object, ...]]) -> dict[int, tuple[str, str]]:
    rows = conn.execute("SELECT version, name, checksum FROM schema_migrations").fetchall()
    return {int(str(r[0])): (str(r[1]), str(r[2])) for r in rows}


def cmd_status(conn: psycopg.Connection[tuple[object, ...]], migrations: list[Migration]) -> int:
    done = applied_map(conn)
    drift = 0
    print(f"{'ver':>4}  {'state':<9} {'name'}")
    print("  " + "-" * 56)
    for m in migrations:
        if m.version not in done:
            state = "pending"
        elif done[m.version][1] != m.checksum:
            state = "DRIFTED"
            drift += 1
        else:
            state = "applied"
        print(f"{m.version:>4}  {state:<9} {m.name}")
    orphans = sorted(set(done) - {m.version for m in migrations})
    for version in orphans:
        print(f"{version:>4}  ORPHAN    {done[version][0]} (applied, but no file on disk)")
        drift += 1
    pending = sum(1 for m in migrations if m.version not in done)
    print(f"\n  {len(done)} applied, {pending} pending, {drift} problem(s)")
    return 1 if drift else 0


def cmd_up(conn: psycopg.Connection[tuple[object, ...]], migrations: list[Migration]) -> int:
    done = applied_map(conn)
    for m in migrations:
        if m.version in done:
            if done[m.version][1] != m.checksum:
                print(
                    f"  REFUSING: {m.version:04d}_{m.name} was applied, but its file has "
                    f"changed since.\n  Applied checksum {done[m.version][1][:12]}…, "
                    f"on disk {m.checksum[:12]}…\n  Write a new migration instead of "
                    f"editing an applied one."
                )
                return 1
            continue
        sql = m.up_path.read_bytes()
        started = time.perf_counter()
        try:
            conn.execute(sql)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, duration_ms) "
                "VALUES (%s, %s, %s, %s)",
                (m.version, m.name, m.checksum, elapsed_ms),
            )
            conn.commit()
        except Exception as exc:  # report and stop; the transaction is already rolled back
            conn.rollback()
            print(f"  FAILED {m.version:04d}_{m.name}: {exc}")
            print("  transaction rolled back; no partial schema was left behind")
            return 1
        print(f"  applied {m.version:04d}_{m.name} ({elapsed_ms} ms)")
    print("  up to date")
    return 0


def cmd_down(
    conn: psycopg.Connection[tuple[object, ...]], migrations: list[Migration], target: int
) -> int:
    done = applied_map(conn)
    to_revert = [m for m in reversed(migrations) if m.version in done and m.version > target]
    if not to_revert:
        print(f"  nothing to revert above version {target}")
        return 0
    for m in to_revert:
        sql = m.down_path.read_bytes()
        try:
            conn.execute(sql)
            conn.execute("DELETE FROM schema_migrations WHERE version = %s", (m.version,))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"  FAILED reverting {m.version:04d}_{m.name}: {exc}")
            return 1
        print(f"  reverted {m.version:04d}_{m.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "up", "down"))
    parser.add_argument(
        "--to",
        type=int,
        default=None,
        help="for 'down': revert every migration above this version (e.g. --to 0)",
    )
    args = parser.parse_args()

    if args.command == "down" and args.to is None:
        print("  refusing to revert without an explicit --to (e.g. --to 0)")
        return 2

    migrations = discover()
    with psycopg.connect(database_url()) as conn:
        ensure_tracking_table(conn)
        # Serialise: a second runner blocks here rather than racing this one.
        conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        conn.commit()
        try:
            if args.command == "status":
                return cmd_status(conn, migrations)
            if args.command == "up":
                return cmd_up(conn, migrations)
            return cmd_down(conn, migrations, int(args.to or 0))
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
            conn.commit()


if __name__ == "__main__":
    sys.exit(main())
