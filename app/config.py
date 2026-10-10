"""Shared runtime configuration for the DocScout application packages.

`scripts/migrate.py` deliberately carries its own copy of the dotenv loader rather than
importing this module. The migration runner must work when `app/` is broken  -  that is
precisely when a schema change is most likely to be needed  -  so coupling an operational
tool to the application package would be the wrong trade. The duplication is ten lines and
is noted in both places.
"""

from __future__ import annotations

import hashlib
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
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
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
    default to fall back from  -  it is the only correct one here.
    """
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and run `make setup`."
        )
    return url


def api_keys() -> frozenset[str]:
    """Accepted API keys for the serving layer, from `DOCSCOUT_API_KEY`.

    Comma-separated so a key can be rotated without downtime: add the new one, redeploy,
    drop the old one. Returning a frozenset rather than a single string is what makes that
    overlap possible, and it costs nothing when there is only one key.

    Empty is NOT silently permissive. An API whose auth disables itself when a variable is
    missing is the classic deploy-time hole -- it looks healthy, serves everything, and
    nothing in the logs says why. `app.api` refuses to start instead.

    The values are never logged. `key_fingerprint()` exists so that requests can be
    attributed without writing a credential to disk.
    """
    load_dotenv()
    raw = os.environ.get("DOCSCOUT_API_KEY", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def key_fingerprint(key: str) -> str:
    """A short, non-reversible label for a key, safe to log.

    Truncated SHA-256. Not a secret, not enough to brute force a 24-byte key, and enough to
    tell two callers apart in an access log.
    """
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def sha256_file(path: Path) -> str:
    """Digest of a file, or the literal "absent" when it is not there.

    Shared by the eval runner and the API because both publish provenance and both must
    describe a missing artifact the same way. Returning a sentinel rather than raising is
    deliberate: provenance is metadata about a run, and a run should not fail because an
    optional input is absent -- it should say so.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


DEFAULT_STALENESS_BUDGET_HOURS: float = 168.0  # 7 days


def staleness_budget_hours() -> float:
    """The allowed staleness window in hours before /healthz reports degraded (P0-2).

    Configured via `DOCSCOUT_STALENESS_BUDGET_HOURS` or `STALENESS_BUDGET_HOURS`. Defaults
    to 168 hours (7 days) for the weekly regulatory publishing cycle.
    """
    load_dotenv()
    for name in ("DOCSCOUT_STALENESS_BUDGET_HOURS", "STALENESS_BUDGET_HOURS"):
        raw = os.environ.get(name, "").strip()
        if raw:
            try:
                val = float(raw)
                if val > 0:
                    return val
            except ValueError:
                pass
    return DEFAULT_STALENESS_BUDGET_HOURS


DEFAULT_EXTRACTOR_MODE: str = "auto"


def extractor_mode() -> str:
    """The configured PDF extractor mode ('auto', 'fast', 'pypdf', 'deep', 'docling', 'mineru').

    Controlled by DOCSCOUT_EXTRACTOR env var. Default is 'auto' (fast-path pypdf with
    fidelity check that escalates to deep fallback).
    """
    load_dotenv()
    val = os.environ.get("DOCSCOUT_EXTRACTOR", "").strip().lower()
    return (
        val
        if val in {"auto", "fast", "pypdf", "deep", "docling", "mineru"}
        else DEFAULT_EXTRACTOR_MODE
    )


# --- Auth0 OAuth 2.0 / OIDC Configuration ---


def auth0_domain() -> str:
    """Auth0 tenant domain (e.g., 'docscout.us.auth0.com')."""
    load_dotenv()
    return os.environ.get("AUTH0_DOMAIN", "").strip()


def auth0_audience() -> str:
    """Auth0 API audience identifier (e.g., 'https://api.docscout.local')."""
    load_dotenv()
    return os.environ.get("AUTH0_AUDIENCE", "https://api.docscout.local").strip()


def auth0_client_id() -> str:
    """Auth0 client application ID."""
    load_dotenv()
    return os.environ.get("AUTH0_CLIENT_ID", "").strip()


def auth0_client_secret() -> str:
    """Auth0 client secret (backend only, never shipped to browser)."""
    load_dotenv()
    return os.environ.get("AUTH0_CLIENT_SECRET", "").strip()


def auth0_issuer() -> str:
    """Auth0 OIDC token issuer URL."""
    domain = auth0_domain()
    if not domain:
        return ""
    base = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    return base.rstrip("/") + "/"


def auth0_admin_roles() -> frozenset[str]:
    """Roles in Auth0 custom claims granting admin permissions in DocScout."""
    return frozenset({"admin", "administrator"})


def auth0_admin_emails() -> frozenset[str]:
    """Whitelisted email addresses granted automatic administrator role."""
    load_dotenv()
    raw = os.environ.get("DOCSCOUT_ADMIN_EMAILS", "")
    return frozenset(email.strip().lower() for email in raw.split(",") if email.strip())


# --- Brevo Transactional Email Configuration ---

DEFAULT_BREVO_API_URL = "https://api.brevo.com/v3"
DEFAULT_BREVO_DAILY_QUOTA = 300


def brevo_api_key() -> str:
    """Brevo transactional API key (formerly Sendinblue)."""
    load_dotenv()
    return os.environ.get("BREVO_API_KEY", "").strip()


def brevo_api_url() -> str:
    """Base URL for Brevo v3 REST API."""
    load_dotenv()
    return os.environ.get("BREVO_API_URL", DEFAULT_BREVO_API_URL).strip()


def brevo_sender_email() -> str:
    """Verified sender email for regulatory digests."""
    load_dotenv()
    return os.environ.get("BREVO_SENDER_EMAIL", "alerts@docscout.local").strip()


def brevo_sender_name() -> str:
    """Display name for regulatory digest sender."""
    load_dotenv()
    return os.environ.get("BREVO_SENDER_NAME", "DocScout Regulatory Alerts").strip()


def brevo_webhook_secret() -> str:
    """Shared secret token to verify incoming Brevo webhook delivery callbacks."""
    load_dotenv()
    return os.environ.get("BREVO_WEBHOOK_SECRET", "").strip()


def brevo_daily_quota() -> int:
    """Daily sending ceiling on Brevo free plan (default 300 emails/day)."""
    load_dotenv()
    raw = os.environ.get("BREVO_DAILY_QUOTA", "").strip()
    try:
        val = int(raw)
        return val if val > 0 else DEFAULT_BREVO_DAILY_QUOTA
    except ValueError:
        return DEFAULT_BREVO_DAILY_QUOTA


# --- OCR.Space Configuration ---

DEFAULT_OCR_SPACE_URL = "https://api.ocr.space/parse/image"
DEFAULT_OCR_SPACE_MAX_BYTES = 1_048_576  # 1 MB free plan ceiling
DEFAULT_OCR_SPACE_MAX_PAGES = 3  # 3 pages free plan ceiling
DEFAULT_OCR_SPACE_DAILY_QUOTA = 500  # 500 requests/day free tier ceiling


def ocr_space_api_key() -> str:
    """OCR.Space API key (free tier key or configured key)."""
    load_dotenv()
    return os.environ.get("OCR_SPACE_API_KEY", "").strip()


def ocr_space_url() -> str:
    """OCR.Space parsing endpoint."""
    load_dotenv()
    return os.environ.get("OCR_SPACE_URL", DEFAULT_OCR_SPACE_URL).strip()


def ocr_space_max_bytes() -> int:
    """Maximum eligible file size for OCR.Space free tier in bytes."""
    return DEFAULT_OCR_SPACE_MAX_BYTES


def ocr_space_max_pages() -> int:
    """Maximum eligible page count for OCR.Space free tier."""
    return DEFAULT_OCR_SPACE_MAX_PAGES


def ocr_space_daily_quota() -> int:
    """Daily request limit for OCR.Space free tier."""
    return DEFAULT_OCR_SPACE_DAILY_QUOTA


# --- Analyst Preferences & Unsubscribe Security ---


def docscout_base_url() -> str:
    """Public base URL of the DocScout service for generating unsubscribe links."""
    load_dotenv()
    return os.environ.get("DOCSCOUT_BASE_URL", "http://localhost:8000").rstrip("/")


def docscout_unsubscribe_secret() -> str:
    """Secret used for generating and validating tamper-proof unsubscribe tokens."""
    load_dotenv()
    val = os.environ.get("DOCSCOUT_UNSUBSCRIBE_SECRET", "").strip()
    if val:
        return val
    # Fallback to key derived from database password or API key to preserve stability across restarts
    raw = os.environ.get("DOCSCOUT_API_KEY", "docscout-default-secret")
    return hashlib.sha256(f"unsubscribe:{raw}".encode()).hexdigest()
