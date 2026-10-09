#!/usr/bin/env bash
# DocScout Scheduled Corpus Refresh Runner — P0-2.
#
# Runs the corpus freshness check, manifest verification, and sync state update.
# Designed for periodic cron execution:
#   0 2 * * * cd /path/to/DocScout && ./scripts/run_corpus_refresh.sh >> /var/log/docscout-refresh.log 2>&1
#
# Usage:
#   ./scripts/run_corpus_refresh.sh [--check-live] [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
    # Load environment without exporting everything indiscriminately
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting DocScout corpus refresh..."
exec uv run python -m app.ingest refresh "$@"
