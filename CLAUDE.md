@AGENTS.md

<!--
Claude-specific notes only. AGENTS.md is the single source of truth — keep this file a thin
import so the two cannot drift (guardrail §7.2).
-->

## Claude-specific
- Project skills live in `.claude/skills/`; hooks in `.claude/settings.json`.
- MCP servers are defined in `.mcp.json` (playwright, context7, memory; github is configured but
  BLOCKED pending a PAT). Read `docs/security/mcp-server-audit.md` before enabling any new server —
  the Postgres MCP server named in the original brief was **rejected** as an unvetted PyPI package.
- Set `SUPERPOWERS_DISABLE_TELEMETRY=true` when using the vendored Superpowers brainstorming skill.
