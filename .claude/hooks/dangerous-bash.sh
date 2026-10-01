#!/usr/bin/env bash
# PreToolUse(Bash) hook — deterministic denylist. Skills suggest; hooks enforce.
#
# Reads the tool call as JSON on stdin, extracts .tool_input.command, and exits 2 to DENY
# (exit 2 = block + feed stderr back to the agent; exit 0 = allow).
#
# Standalone test:  echo '{"tool_input":{"command":"rm -rf /"}}' | bash .claude/hooks/dangerous-bash.sh
set -uo pipefail

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"
[ -z "$CMD" ] && exit 0

WORKDIR="${CLAUDE_PROJECT_DIR:-$PWD}"

deny() {
  echo "DENIED by dangerous-bash hook: $1" >&2
  echo "command: $CMD" >&2
  exit 2
}

# 1. Recursive delete outside the working directory (or at a root-ish path).
if printf '%s' "$CMD" | grep -qE '\brm\b[^|;]*\s-[a-zA-Z]*r[a-zA-Z]*f|\brm\b[^|;]*\s-[a-zA-Z]*f[a-zA-Z]*r'; then
  if printf '%s' "$CMD" | grep -qE '\brm\b[^|;]*\s+(/|~|\$HOME|/\*|\.\./)'; then
    deny "recursive delete targeting a path outside the project workdir ($WORKDIR)"
  fi
fi

# 2. Force push.
printf '%s' "$CMD" | grep -qE 'git\s+push\b.*(--force\b|-f\b)' \
  && deny "force push (use --force-with-lease on your own branch, never on main)"

# 3. Pipe-to-shell from a non-allowlisted host.
if printf '%s' "$CMD" | grep -qE '(curl|wget)\b.*\|\s*(sudo\s+)?(ba)?sh'; then
  HOSTS="$(printf '%s' "$CMD" | grep -oE 'https?://[^/ "'"'"']+' | sed -E 's#https?://##' || true)"
  ALLOW='^(astral\.sh|sh\.rustup\.rs|get\.docker\.com|fnm\.vercel\.app|deb\.nodesource\.com)$'
  for h in $HOSTS; do
    printf '%s' "$h" | grep -qE "$ALLOW" || deny "pipe-to-shell from non-allowlisted host: $h"
  done
fi

# 4. History rewrite / repo destruction.
printf '%s' "$CMD" | grep -qE 'git\s+(reset\s+--hard\s+HEAD~|filter-branch|update-ref\s+-d)' \
  && deny "destructive git history operation"

# 5. Writing outside the workdir (crude but catches the common cases).
printf '%s' "$CMD" | grep -qE '>\s*(/etc/|/usr/|/bin/|/boot/|~/\.ssh/|/root/)' \
  && deny "write outside the project workdir"

# 6. Secret exfiltration shapes: reading .env / keys and sending them somewhere.
if printf '%s' "$CMD" | grep -qE '(\.env|id_rsa|\.ssh/|credentials)'; then
  printf '%s' "$CMD" | grep -qE '(curl|wget|nc|mail|ssh|scp)\b' \
    && deny "reads a credential file and pipes it to a network command (exfiltration shape)"
fi

# 7. chmod 777 / world-writable.
printf '%s' "$CMD" | grep -qE 'chmod\s+(-R\s+)?777' && deny "chmod 777"

exit 0
