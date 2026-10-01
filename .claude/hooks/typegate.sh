#!/usr/bin/env bash
# Stop hook — end-of-session quality gate.
# Reports a pass/fail summary. Does NOT block the human (exit 0 always), but a red gate means
# no new task may start until it is green (AGENTS.md / skill define-done).
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$PWD}" || exit 0

status=0
summary=""

run() {
  local label="$1"; shift
  if "$@" >/tmp/typegate-$$.log 2>&1; then
    summary+="  PASS  $label"$'\n'
  else
    summary+="  FAIL  $label"$'\n'
    summary+="        $(tail -3 /tmp/typegate-$$.log | tr '\n' ' ')"$'\n'
    status=1
  fi
}

run "ruff check"   uv run ruff check .
run "ruff format"  uv run ruff format --check .
run "mypy app"     uv run mypy app
run "pytest"       uv run pytest -q -x

rm -f /tmp/typegate-$$.log
echo "=== typegate (end of session) ==="
printf '%s' "$summary"
if [ "$status" -ne 0 ]; then
  echo "GATE IS RED — do not start a new task until green."
else
  echo "GATE IS GREEN."
fi
exit 0
