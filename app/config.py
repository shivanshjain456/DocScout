"""Shared runtime configuration for the DocScout application packages.

`scripts/migrate.py` deliberately carries its own copy of the dotenv loader rather than
importing this module. The migration runner must work when `app/` is broken — that is
precisely when a schema change is most likely to be needed — so coupling an operational
tool to the application package would be the wrong trade. The duplication is ten lines and
is noted in both places.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOTENV = REPO_ROOT / ".env"


def load_dotenv(path: Path | None = None) -> None:
    """Populate os.environ from a .env file without adding a dependency.

    Only fills variables that are not already set, so a real environment always wins.
    """
    dotenv = DEFAULT_DOTENV if path is None else path
    if not dotenv.is_file():
        return
    for raw in dotenv.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url() -> str:
    """Connection string for application data access (DML).

    This is deliberately `DATABASE_URL` and never `MIGRATION_DATABASE_URL`. The former
    names `docscout_app`, which holds SELECT/INSERT/UPDATE and has neither DELETE nor DDL
    (migration 0001). Ingestion running as the owner would quietly give the pipeline the
    privilege to drop the retention guarantee FR-4 depends on, so the weaker role is not a
    default to fall back from — it is the only correct one here.
    """
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and run `make setup`."
        )
    return url
