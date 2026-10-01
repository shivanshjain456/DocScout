# Agent skills audit (guardrail §1.3)

Context: Snyk's Feb 2026 audit of 3,984 published agent skills found 36.8% with ≥1 security flaw
and 76 confirmed malicious; the ClawHavoc campaign poisoned 1,184 skills and persisted by rewriting
the agent's memory file. Skills are a supply chain and are treated as one.

## Installed skills and their provenance

| Skill set | Source | Version / commit | Trust basis |
|---|---|---|---|
| Superpowers (15 skills) | `github.com/obra/superpowers` | `8ca22dba9a94f28898bbce59f2537ff4d87c747d` (Release v6.4.2, 2026-09-25) | Allowed source per §7.4(a); MIT; 293k stars; active |
| DocScout project skills (6) | written in-repo for this project | n/a | Allowed source per §7.4(c) |

Nothing was installed from ClawHub or any third-party skill registry (§1.3, §12).
`security-guidance` (§7.4(b), official Claude Code marketplace plugin) was **not** installed — this
environment has no Claude Code plugin client, so `/plugin install` is unavailable. Recorded as a
Known issue, not silently skipped.

## Installation method deviation

The brief specifies `/plugin marketplace add obra/superpowers-marketplace`. No Claude Code plugin
client exists in this environment, so the documented fallback path was used: the repository was
cloned at a pinned commit and the `skills/` tree vendored into `.claude/skills/`. The commit hash
above is the pin. No auto-update mechanism is active.

## Manual audit performed before installation

Scanned the full tree (`skills/`, `hooks/`, `scripts/`, `index.js`) for:

| Check | Result |
|---|---|
| Writes to agent memory/instruction files (`CLAUDE.md`, `AGENTS.md`, `.claude/settings`, memory) — the ClawHavoc signature | **None found** |
| `curl`/`wget`/`base64`/`nc`/`/dev/tcp`/`eval $(...)`/pipe-to-shell in executable code | None in executable code. One `curl` example inside documentation prose (`diagnosing-superpowers/references/github-issues.md`) — a GitHub API example for the user to run, not auto-executed |
| Credential/secret access (`~/.ssh`, `id_rsa`, `.env`, API keys) | **None found** |
| Outbound hosts in executable code | Two only: `github.com/obra/superpowers` (docs link) and `primeradiant.com/brand/...png` (see finding below) |
| Auto-executing hooks | One: `hooks/session-start`. Read in full — it `cat`s the `using-superpowers` SKILL.md and emits it as JSON context. No network, no file writes, no credential access. Benign. |

### Finding (low severity, accepted with mitigation)

`skills/brainstorming/scripts/server.cjs` runs a **local** HTTP UI (binds `127.0.0.1`, per-session
token) and, when rendering, references a remote branding image at
`https://primeradiant.com/brand/superpowers-visual-brainstorming-logo.png`. This is a usage beacon:
it discloses to the author's domain that/when the skill is used, plus the requesting IP. It is not
exfiltration — no project data is transmitted — and it is opt-out.

**Mitigation:** set `SUPERPOWERS_DISABLE_TELEMETRY=true` (or `DISABLE_TELEMETRY=true`) in the dev
environment. Recorded in `.claude/skills/VENDORED-SUPERPOWERS.md` and `CLAUDE.md`.

## Automated scanner

The brief specifies `uvx mcp-scan@latest --skills`. **`mcp-scan` has been renamed to
`snyk-agent-scan`** (the old package prints a rename warning). The current tool's full `scan`
(threat analysis) requires a `SNYK_TOKEN`; obtaining one is outside the §10.1 credential list, so it
was not requested and the automated verdict is **not available**. The token-free `inspect` mode was
run instead, and the manual audit above was performed to compensate.

Evidence: `docs/security/mcp-scan-servers.txt`, `docs/security/skills-scan.txt`.

## Standing rules

- No skill may write to memory or instruction files without an explicit, audited action.
- Skill descriptions are trigger text injected into context — re-read them after any update.
- Updating the Superpowers pin is a reviewed action: diff the tree, re-run this audit, record the
  new commit hash.
