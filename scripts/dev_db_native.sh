#!/usr/bin/env bash
# Provision a local PostgreSQL 18 + pgvector instance WITHOUT Docker.
#
# Why this exists: docker-compose.yml is the documented way to run DocScout's datastore and
# remains the default. Some development environments cannot run Docker at all (no daemon, no
# privileged containers), and in those the whole project becomes unverifiable: no schema, no
# ingest, no eval numbers. This script is the fallback path, not a second source of truth.
#
# It is deliberately NOT a reimplementation of the compose stack. The role grants and the
# extension set live in infra/initdb/, and this script EXECUTES those same files, so the two
# paths cannot drift. If you change infra/initdb/, both Docker and native pick it up.
#
# Differences from the compose service, by design:
#   - The cluster is created by the Debian postgresql-common tooling, so its data directory,
#     logging and service management are the distribution's rather than the image's.
#   - The cluster lives outside the repository and is NOT persisted by any snapshot. Treat it
#     as disposable: `make ingest` rebuilds its contents in well under a minute.
#
# Idempotent: safe to re-run. It creates only what is missing and never drops anything.
#
# Usage:  ./scripts/dev_db_native.sh [--drop]
#         --drop  tear the docscout database down first (destructive, asks nothing)

set -euo pipefail

PG_VERSION=18
CLUSTER=main
DB_NAME=docscout
DB_OWNER=docscout
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INITDB_DIR="$REPO_ROOT/infra/initdb"

say() { printf '  %-28s %s\n' "$1" "${2-}"; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

# --- preconditions -------------------------------------------------------------------------
[[ -f "$REPO_ROOT/.env" ]] || die ".env not found at $REPO_ROOT/.env (copy .env.example and fill it)"

# Read the two passwords without sourcing .env, so a stray line in that file cannot execute.
read_env() { sed -n "s/^$1=//p" "$REPO_ROOT/.env" | head -1; }
DB_PASSWORD="$(read_env DB_PASSWORD)"
DB_APP_PASSWORD="$(read_env DB_APP_PASSWORD)"
[[ -n "$DB_PASSWORD" ]]     || die "DB_PASSWORD is empty in .env"
[[ -n "$DB_APP_PASSWORD" ]] || die "DB_APP_PASSWORD is empty in .env"

# --- packages ------------------------------------------------------------------------------
# Debian trixie ships PostgreSQL 17, not 18, and no pgvector for 18, so the PostgreSQL Global
# Development Group (pgdg) repository is required. We install rather than die: this sandbox is
# rebuilt from a bare image on every session, and a database you must hand-install is a
# database that silently stops being verified. Idempotent -- apt is a no-op when satisfied.
ensure_packages() {
  local need=()
  command -v pg_lsclusters >/dev/null || need+=("postgresql-$PG_VERSION")
  [[ -f "/usr/share/postgresql/$PG_VERSION/extension/vector.control" ]] \
    || need+=("postgresql-$PG_VERSION-pgvector")
  [[ ${#need[@]} -eq 0 ]] && { say "packages" "postgresql-$PG_VERSION + pgvector already present"; return 0; }

  say "installing" "${need[*]} (from pgdg)"
  if [[ ! -f /etc/apt/sources.list.d/pgdg.list ]]; then
    sudo install -d -m 0755 /usr/share/postgresql-common/pgdg 2>/dev/null || true
    sudo curl -fsSL -o /usr/share/keyrings/pgdg.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      || die "could not fetch the pgdg signing key (no network?)"
    # shellcheck disable=SC2154
    echo "deb [signed-by=/usr/share/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
      | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null
  fi
  sudo apt-get update -qq >/dev/null 2>&1 || die "apt-get update failed"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null 2>&1 \
    || die "apt-get install ${need[*]} failed"

  command -v pg_lsclusters >/dev/null || die "postgresql-common still missing after install"
  [[ -f "/usr/share/postgresql/$PG_VERSION/extension/vector.control" ]] \
    || die "pgvector still missing for PG $PG_VERSION after install"
}
ensure_packages

# psql must be on PATH for infra/initdb/02-app-role.sh, which calls it directly.
export PATH="/usr/lib/postgresql/$PG_VERSION/bin:$PATH"

# --- cluster -------------------------------------------------------------------------------
if ! pg_lsclusters -h | awk '{print $1"/"$2}' | grep -qx "$PG_VERSION/$CLUSTER"; then
  say "creating cluster" "$PG_VERSION/$CLUSTER"
  sudo pg_createcluster "$PG_VERSION" "$CLUSTER" >/dev/null
fi

if [[ "$(pg_lsclusters -h | awk -v v="$PG_VERSION" -v c="$CLUSTER" '$1==v && $2==c {print $4}')" != "online" ]]; then
  say "starting cluster" "$PG_VERSION/$CLUSTER"
  sudo pg_ctlcluster "$PG_VERSION" "$CLUSTER" start
fi

# Wait for readiness rather than assuming the start was instantaneous.
for _ in $(seq 1 30); do
  sudo -u postgres pg_isready -q && break
  sleep 1
done
sudo -u postgres pg_isready -q || die "cluster did not become ready"
say "cluster" "online on port $(pg_lsclusters -h | awk -v v="$PG_VERSION" -v c="$CLUSTER" '$1==v && $2==c {print $3}')"

as_super() { sudo -u postgres psql -v ON_ERROR_STOP=1 -qAt "$@"; }

if [[ "${1-}" == "--drop" ]]; then
  say "dropping database" "$DB_NAME"
  as_super -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE);" >/dev/null
fi

# --- owner role ------------------------------------------------------------------------------
# Mirrors POSTGRES_USER in docker-compose.yml, which the official image creates as the cluster
# superuser. The least-privilege boundary in DocScout is docscout_app (created below by
# infra/initdb/02-app-role.sh), not this role; migrations need CREATE EXTENSION, which pgvector
# does not expose as a trusted extension.
if [[ "$(as_super -c "SELECT 1 FROM pg_roles WHERE rolname='$DB_OWNER'")" != "1" ]]; then
  say "creating role" "$DB_OWNER (superuser, mirrors POSTGRES_USER)"
  as_super -c "CREATE ROLE $DB_OWNER LOGIN SUPERUSER PASSWORD '$DB_PASSWORD';" >/dev/null
else
  # Keep the password in step with .env; a rotated secret should not silently fail to connect.
  as_super -c "ALTER ROLE $DB_OWNER PASSWORD '$DB_PASSWORD';" >/dev/null
  say "role exists" "$DB_OWNER (password re-synced from .env)"
fi

if [[ "$(as_super -c "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" != "1" ]]; then
  say "creating database" "$DB_NAME owned by $DB_OWNER"
  as_super -c "CREATE DATABASE $DB_NAME OWNER $DB_OWNER;" >/dev/null
else
  say "database exists" "$DB_NAME"
fi

# --- initdb hooks: the single source of truth, executed verbatim -------------------------------
# The postgres OS user cannot read files under a user home directory, so stage copies somewhere
# world-readable. Copies, not reimplementations: infra/initdb/ stays the only definition.
STAGE="$(mktemp -d /tmp/docscout-initdb.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
cp "$INITDB_DIR"/* "$STAGE"/
chmod 755 "$STAGE"; chmod 644 "$STAGE"/*.sql; chmod 755 "$STAGE"/*.sh

say "applying" "infra/initdb/01-extensions.sql"
sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" -f "$STAGE/01-extensions.sql"

if [[ "$(as_super -d "$DB_NAME" -c "SELECT 1 FROM pg_roles WHERE rolname='docscout_app'")" == "1" ]]; then
  say "app role exists" "docscout_app (02-app-role.sh skipped; it is CREATE-only)"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" \
    -c "ALTER ROLE docscout_app PASSWORD '$DB_APP_PASSWORD';"
else
  say "applying" "infra/initdb/02-app-role.sh"
  # The hook is written for the Docker entrypoint, which runs it as the postgres OS user with
  # these variables set and psql already authenticated by peer. Reproduce that contract exactly
  # instead of copying its SQL here, so the two provisioning paths cannot diverge.
  sudo -u postgres env \
    POSTGRES_USER=postgres POSTGRES_DB="$DB_NAME" DB_APP_PASSWORD="$DB_APP_PASSWORD" \
    PATH="$PATH" bash "$STAGE/02-app-role.sh"
fi

# --- verify by connecting, over TCP, as both roles exactly as the application will -------------
check_conn() {
  local label="$1" url="$2"
  local out
  if out="$(PGCONNECT_TIMEOUT=5 psql -qAt "$url" -c "SELECT current_user||' @ '||current_database()" 2>&1)"; then
    say "$label" "$out"
  else
    die "$label could not connect: $out"
  fi
}
check_conn "owner connection" "$(read_env MIGRATION_DATABASE_URL)"
check_conn "app connection"   "$(read_env DATABASE_URL)"

say "pgvector" "$(as_super -d "$DB_NAME" -c "SELECT extversion FROM pg_extension WHERE extname='vector'")"
say "server" "$(as_super -c 'SHOW server_version')"
echo
echo "  Ready. Next: make migrate && make ingest"
