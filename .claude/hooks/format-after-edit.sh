#!/usr/bin/env bash
# PostToolUse(Edit|Write) hook — format and autofix Python files, quietly.
# Never blocks the agent: failures are reported on stderr and exit 0.
set -uo pipefail

INPUT="$(cat)"
FILE="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"

case "$FILE" in
  *.py) ;;
  *) exit 0 ;;
esac

[ -f "$FILE" ] || exit 0

if ! uv run ruff format "$FILE" >/dev/null 2>&1; then
  echo "format-after-edit: ruff format failed on $FILE" >&2
fi
if ! uv run ruff check --fix "$FILE" >/dev/null 2>&1; then
  echo "format-after-edit: ruff check --fix left unresolved findings in $FILE" >&2
fi

exit 0
