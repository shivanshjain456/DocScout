#!/bin/bash
# DEVIATION FROM BRIEF §4 (recorded in SETUP_REPORT → Known issues):
# The brief's 01-extensions.sql creates the app role with a literal '${DB_APP_PASSWORD}'.
# Postgres does NOT expand shell/env vars inside .sql files run by docker-entrypoint-initdb.d,
# so that would have created a role whose password is the literal string "${DB_APP_PASSWORD}".
# Role creation is therefore done here, in a .sh initdb hook, where the env var really expands.
set -euo pipefail

: "${DB_APP_PASSWORD:?DB_APP_PASSWORD must be set in the db service environment}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Least-privilege service role for the app (guardrail §1.4 / §1.5).
    -- No CREATEDB, no CREATEROLE, no SUPERUSER. Table grants are issued by migrations later.
    CREATE ROLE docscout_app LOGIN PASSWORD '${DB_APP_PASSWORD}';
    GRANT CONNECT ON DATABASE docscout TO docscout_app;
    GRANT USAGE ON SCHEMA public TO docscout_app;
EOSQL
