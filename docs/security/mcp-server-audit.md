# MCP server audit — Phase 0 (guardrail §1.1)

Date: 2026-10-01. Auditor: setup agent. Method: real MCP handshake (`initialize` → `tools/list`)
against each candidate server using `scripts/mcp_probe.py`, then manual read of **every** tool
description, plus a red-flag regex pass (exfiltration verbs, `~/.ssh`, `id_rsa`, `.env`, `curl`,
`base64`, `<IMPORTANT>`, "ignore previous…", "do not tell…").

Raw evidence: `docs/setup/mcp-verify/*.txt` (full tool lists with complete descriptions).

| Server | Source | Pinned version | Transport | Tools | Red flags | Verdict |
|---|---|---|---|---|---|---|
| playwright | `@playwright/mcp` (Microsoft, official npm) | `0.0.83` | stdio | 25 | 0 | **APPROVED** |
| context7 | `https://mcp.context7.com/mcp` (Upstash, official remote) | server v4.1.1 | http | 2 | 0 | **APPROVED** |
| memory | `@modelcontextprotocol/server-memory` (official MCP reference, npm) | `2026.8.31` (reports v0.6.3) | stdio | 9 | 0 | **APPROVED (with write-log rule)** |
| github | `ghcr.io/github/github-mcp-server` (GitHub, official) | not pulled | stdio/docker | n/a | n/a | **BLOCKED** — no PAT issued (human declined in Phase 0) |
| postgres | see rejection below | — | — | — | — | **REJECTED — awaiting human decision** |

---

## 1. REJECTED: `uvx mcp-server-postgres` (the brief's §6.2 config)

The brief instructs `"command": "uvx", "args": ["mcp-server-postgres", "postgresql://docscout:<pw>@localhost:5432/docscout"]`.
**This instruction was not followed.** Guardrail §1.1 requires verifying provenance before approving a
server; the package fails that check badly.

PyPI metadata for `mcp-server-postgres` (fetched 2026-10-01):

```
version:      0.1.0
summary:      "Add your description here"      <-- unedited `uv init` default
author:       truskovskiyk <truskovskiyk@gmail.com>   (personal address, unaffiliated)
home_page:    none
project_urls: {}                                <-- no repository, no issue tracker
license:      none
requires:     []                                <-- a Postgres MCP server with zero dependencies
first upload: 2025-02-28
```

Assessment: this is **not** an Anthropic/MCP reference server. The official reference Postgres server
was published to npm as `@modelcontextprotocol/server-postgres` (now carrying an npm deprecation
notice: *"Package no longer supported"*), never to PyPI under this name. An unaffiliated,
undocumented, zero-dependency package occupying an official-sounding PyPI name is the exact
typosquat/supply-chain shape described in guardrail §1.1 and the postmark-mcp incident.

Severity is amplified by the brief's own invocation: the live DB connection string — **including the
Postgres superuser password** — is passed as a command-line argument to that package. Executing it
would hand project credentials to unvetted third-party code, and `uvx` would fetch the newest
release at run time (no pinning), so the code could change under us at any invocation.

**Action taken:** not installed, not executed, not even downloaded. Escalated to the human.

### Options for the human (pick one; recorded in SETUP_REPORT §5)

- **(A) Do without a Postgres MCP server (recommended for Phase 0).** `psql` is installed and the
  agent has shell access, so schema inspection already works with no new trust boundary and no
  credential hand-off. Zero added supply-chain risk.
- **(B) Approve the maintained community server `postgres-mcp` (crystaldba, PyPI 0.3.0).** Actively
  maintained, real repo, used for tuning/analysis. Requires explicit human approval under §6
  ("any other community server → DO NOT INSTALL"), must be version-pinned, and should connect with
  the least-privilege `docscout_app` role — never the superuser — via env var, not argv.
- **(C) Use the deprecated official `@modelcontextprotocol/server-postgres@0.6.2`.** Official
  provenance, but unmaintained and archived; inherits any unpatched defects.

## 2. Note on APPROVED servers

- **playwright** exposes `browser_run_code_unsafe` (arbitrary JS in page context). Not a poisoned
  description — it is honestly named and the capability is inherent to browser automation — but it
  is a genuine capability risk when the browser visits untrusted pages. Mitigation: the server is
  configured `--headless --isolated` (ephemeral profile, no persistent cookies/credentials), and
  per guardrail §1.2 the DocScout corpus must never be rendered in this browser during dev.
- **context7** tool descriptions contain imperative text ("You MUST call this function before…",
  "Do not call this tool more than 3 times per question"). These were read in full and judged
  **in-scope**: they constrain the order and frequency of calls to the server's own tools. There are
  no instructions to fetch external URLs, read local files, touch credentials, or conceal activity.
  Accepted, with the standing rule that tool *results* remain untrusted data (guardrail §1.2).
- **memory** is approved subject to the §6.1 rule: every write is logged to
  `docs/security/memory-writes.md` and reviewed by the human. Rationale: ClawHavoc (2026) achieved
  persistence by rewriting agent memory, so memory is treated as an attack surface, not storage.
- **filesystem / sequential-thinking / brave-search / perplexity**: not installed, per §6.1 and §12.
