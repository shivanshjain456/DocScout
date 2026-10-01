# DocScout — Security

**Status:** authoritative security policy and threat model. Last updated **2026-10-01**.
**Implementation status:** the application does not exist (`app/**` is empty, VERIFIED), so no
application-level control is implemented. The controls that *are* live today are repository and
environment controls, and they are marked VERIFIED with their evidence.

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9. Audit records live in `docs/security/`.

---

## 1. What is being protected

| Asset | Why it matters | Exposure |
|---|---|---|
| **Answer integrity** | The product is a cited answer a compliance analyst will rely on. A plausible wrong answer is the worst outcome in this system | Prompt injection, retrieval failure, silent extraction loss |
| **Credentials** | Database, future LLM API keys, future cloud deploy credentials | Repository history, logs, CI, agent tool surfaces |
| **The corpus pipeline** | Ingests untrusted third-party content into a model's context | Hostile or malformed documents |
| **The gold set** | The project's only quality evidence | Tampering or silent drift |
| **Spend** | No budget exists for this project | Unbounded LLM or cloud usage |

Not protected, because it is public: the corpus content itself. RBI and SEBI circulars are public
documents (`docs/corpus/CORPUS_SPEC.md` §6).

---

## 2. Threat model

| ID | Threat | Realistic? | Control | Status |
|---|---|---|---|---|
| T-1 | **Indirect prompt injection** via a corpus document instructing the model to ignore its instructions, exfiltrate, or fabricate a citation | **Yes — this is the primary threat.** The pipeline is designed to put third-party PDF text into a model context | S-7, S-8 | Controls SPECIFIED; canary detection VERIFIED |
| T-2 | **Secret committed to git** | Yes — routine | S-1, S-2 | **VERIFIED enforced** |
| T-3 | **Fabricated or unresolvable citation** reaching a user | Yes — the failure mode LLMs produce most readily | S-9 | SPECIFIED |
| T-4 | **Supply-chain compromise** via a dependency, an MCP server, or a vendored agent skill | Yes | S-10, S-11, S-12 | Partly VERIFIED; no automated verdict (K-9, U-4) |
| T-5 | **Credential bleed between stages** — ingestion code running with deploy credentials in its environment | Yes, by accident | S-4 | SPECIFIED |
| T-6 | **API abuse** — unauthenticated or unbounded use of a deployed endpoint, driving cost | Yes, once deployed | S-5, S-6 | SPECIFIED, not built |
| T-7 | **Data exfiltration through logs** — retrieved context or keys written to logs | Yes | S-13 | SPECIFIED |
| T-8 | **Unbounded cloud spend** after deploy | Yes | S-14 | SPECIFIED, BLOCKED on U-7 |
| T-9 | **SQL injection** via question text reaching a query | Yes if string-built | S-15 | SPECIFIED |
| T-10 | **Agent-caused damage** — an autonomous agent running destructive commands or exfiltrating via tool calls | Yes, this repo is agent-developed | S-16 | **VERIFIED enforced** |
| T-11 | **Denial of service against the regulators' sites** by an aggressive crawler | Yes | S-17 | SPECIFIED; polite-fetch posture VERIFIED in Phase 0 |

Out of threat model for v1: multi-tenant isolation, user accounts, and PII handling — DocScout
stores no user data (`SPEC.md` OUT-4).

---

## 3. Trust boundaries

The normative table is in `docs/architecture/system-diagram.md` and is not duplicated. In summary,
five boundaries each require an explicit control: **Internet → ingestion** (data, never
instructions), **ingestion → deploy** (no shared credentials), **retrieved chunk → generator**
(delimited, declared untrusted), **API → public** (key-gated, rate-limited), **MCP tool result →
agent** (untrusted input, pinned servers).

---

## 4. Controls

### 4.1 Secrets — VERIFIED

| ID | Control | Evidence |
|---|---|---|
| **S-1** | No secret in the repository or its history. `gitleaks` runs as a pre-commit hook and as a CI job with `fetch-depth: 0` | A deliberately planted secret was **blocked at commit time** — `docs/setup/verify/step6-precommit-secret-block.txt` (V9). Full-history scans clean twice: Phase 0 (2 commits, 995.39 KB, V16) and again over the re-initialised history on 2026-10-01 (**3 commits, 1.03 MB, no leaks**) |
| **S-2** | `.env` and `.env.*` are gitignored; `.env.example` is tracked and contains no values; `*.pem` and `*.key` are gitignored | `.gitignore`, VERIFIED on 2026-10-01 **per path with `git check-ignore -v`**, not by reading the patterns; 0 tracked `.env` files |
| **S-3** | Secrets are referred to by **name and scope only** in documentation — never by value | `docs/setup/SETUP_REPORT.md` |

**Why S-2 now says "per path".** On 2026-10-01 an unanchored `corpus/` pattern was found to be
excluding `docs/corpus/` as well — a directory at a completely different depth — silently and with
no error. The pattern read correctly and behaved incorrectly. `.gitignore` is a security control
here (it is what keeps `.env` and the corpus out of history), and a security control is verified by
testing its effect on each path that matters, never by inspection. See ADR-0001.

**Operational note (VERIFIED):** an untracked `.env` exists in the working tree with locally
generated Postgres passwords. Those are **local development credentials only**; they MUST NOT be
reused in any deployed environment, and the deploy path MUST source credentials from a secrets
manager, not from a file (S-14).

**S-4 — SPECIFIED. Stage credential isolation.** The ingestion entrypoint MUST fail fast if deploy
or cloud credentials are present in its environment. *Test:* set a deploy-credential variable and
assert the ingester exits non-zero before any network call. (= `SPEC.md` FR-6.)

### 4.2 Application surface — SPECIFIED, not built

| ID | Control |
|---|---|
| **S-5** | Every endpoint except `/healthz` requires an API key. Key handling lives **only** in `app/api/` (`AGENTS.md` boundary) |
| **S-6** | Per-key rate limiting enforced via Redis; limit values are UNRESOLVED (U-13). A deployed endpoint without a limit is a cost incident waiting to happen |
| **S-9** | Citation validation is server-side and deterministic: an answer citing a chunk ID that was not in its supplied context is **rejected**, not returned with a warning (T-3) |
| **S-13** | Structured logs carry a request ID and MUST NOT contain the full retrieved context or any API key (T-7) |
| **S-15** | All SQL is parameterised; no query is built by string concatenation with user input. `psycopg` 3.3.6 is locked and supports this natively (T-9) |
| **S-18** | The database application role is least-privilege and distinct from the owner role. `infra/initdb/02-app-role.sh` already creates a separate app role at first boot (VERIFIED it exists) |

### 4.3 Prompt injection — the primary control

**S-7 — SPECIFIED. Delimiter discipline.** Retrieved chunks are wrapped in `<document>` delimiters,
and the system prompt declares that any instruction appearing inside them is invalid data. This is
the control. (= `SPEC.md` FR-12.)

**S-8 — SPECIFIED. Graded canary.** At least one injection canary ships in the corpus and in the
evaluation gold set, and canary resistance is scored on every evaluation run
(`docs/eval/EVAL_PROTOCOL.md` §3).

VERIFIED supporting evidence: the Phase 0 canary matched **11/11** injection patterns while the 20
real documents matched **0/20** (`docs/setup/verify/step8-injection-scan.txt`,
`docs/security/injection-canary-log.md`).

**Stated plainly:** 0/20 means the sample was clean, not that the corpus is safe. Pattern scanning
is detection, not defence. If the delimiter discipline fails, scanning will not save the answer.
Treat S-7 as the control and S-8 as the test of it.

### 4.4 Supply chain

| ID | Control | Status |
|---|---|---|
| **S-10** | Python dependencies are fully locked; CI installs with `uv sync --frozen` | **VERIFIED** — 169 packages, `uv.lock` sha256 `600c90010345412c62226029af2b86419b26821ab0a9cca30b3172fc6ee1b98d` |
| **S-11** | MCP servers are **pinned by version** and adding one requires a human-approved audit | **VERIFIED** — `.mcp.json` pins `@playwright/mcp@0.0.83` and `@modelcontextprotocol/server-memory@2026.8.31`; audit record in `docs/security/mcp-server-audit.md` |
| **S-12** | Vendored agent skills are pinned to a commit and reviewed | **VERIFIED** — Superpowers v6.4.2 at commit `8ca22db`; review in `docs/security/skills-audit.md` |
| **S-19** | Memory-server writes are logged | **VERIFIED** — `docs/security/memory-writes.md` |

Three honest gaps, carried from Phase 0:

- **The brief's suggested Postgres MCP server was rejected** after audit: the npm
  `@modelcontextprotocol/server-postgres` is deprecated and the PyPI names in the brief are not
  official packages (K-8). A maintained community alternative, `postgres-mcp` 0.3.0, exists. **No
  Postgres MCP server is configured** pending a human decision — U-2.
- **No automated MCP or skill scan verdict exists.** `mcp-scan` was renamed to `snyk-agent-scan`
  and requires a `SNYK_TOKEN` that was not issued (K-9, U-4). The current assurance is manual audit
  only, and this document does not pretend otherwise.
- **`.mcp.json` is committed** and contains `"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}"` — an
  environment reference, **not** a secret value, so S-1 is not violated. Whether the file should
  stay tracked is U-3.

### 4.5 Agent safety — VERIFIED

**S-16.** A command denylist hook blocks destructive and exfiltration-prone commands before
execution. Measured in Phase 0: **11/11 dangerous commands denied, 6/6 benign commands allowed**
(`docs/setup/verify/step6-hooks-denylist.txt`, V8). MCP tool results are treated as untrusted input
(`AGENTS.md`).

> **Incident, 2026-10-01 — this control was inert and nobody could see it.**
> A workspace snapshot stripped the executable bit from every shebang script in the repository,
> including `.claude/hooks/dangerous-bash.sh`. The file was present, tracked, and byte-for-byte
> correct; its logic still returned exit 2 for `rm -rf /` when invoked explicitly. But a hook
> without the executable bit is not run by the agent runtime, so the denylist was **not enforcing
> anything**. The loss was then committed in `c2eeb90` without anyone noticing, because a file
> mode does not appear when you read a diff.
>
> Detected by V8 of the verification matrix on its first re-run — not by review, and not by
> reading the repository, both of which showed a perfectly healthy control.
>
> Fixed: executable bits restored on all 16 affected files. Guarded: the pre-commit hook
> `check-shebang-scripts-are-executable` now rejects any shebang script that is not executable,
> and was tested by deliberately re-breaking the file and confirming the hook fires.
>
> **The transferable lesson:** a security control is only "enforced" if something executes it and
> reports. Presence in the repository is not enforcement, and a control whose failure mode is
> *silent absence* needs an automated check that it is still live.

### 4.6 Deployment and spend — SPECIFIED, BLOCKED

**S-14.** Before any cloud resource is created: a dedicated account, a hard cost cap, and a billing
alarm — **configured first, not after**. Runtime identity is least-privilege, never admin. Image
digest and IaC hash are recorded to `docs/deploys/<ts>.md`. `make destroy` MUST be tested before
anything outlives a development session. This is enforced today only by the `deploy` and `destroy`
Makefile targets, which **exit 1 as deliberate stubs** (VERIFIED).

**S-17.** Fetching stays polite: low volume, rate-limited, descriptive User-Agent, no authentication
bypass (`CORPUS_SPEC.md` C-15).

Current cloud state — VERIFIED: AWS CLI 2.37.7 installed and **unconfigured**; **zero cloud
resources exist**; Phase 0 API spend **$0.00** (V17, K-3). Deployment is BLOCKED on U-7.

---

## 5. Verification status summary

| Control area | Enforced today | Evidence |
|---|---|---|
| Secret scanning (pre-commit + CI, full history) | **Yes** | V9, V16 |
| Dependency pinning | **Yes** | V5, `uv.lock` |
| Agent command denylist | **Yes** — re-verified 2026-10-01 after being found inert (see S-16) | V8, `docs/setup/verify/m0-verify-setup-rerun.txt` |
| Executable-bit integrity of hooks and scripts | **Yes** — `check-shebang-scripts-are-executable` pre-commit hook | `.pre-commit-config.yaml` |
| MCP/skill pinning + manual audit | **Yes** (manual only) | V6, V7, `docs/security/` |
| Injection canary detection | **Yes** (detection only) | V13 |
| Least-privilege DB role | Partial — role is created; application does not use it yet | `infra/initdb/02-app-role.sh` |
| API auth, rate limiting, log redaction, citation validation, SQL parameterisation | **No — no application code exists** | `SPEC.md` §2.2 |
| Cloud guardrails | **No cloud resources exist** | V17 |
| Automated supply-chain scanning | **No** | K-9, U-4 |

---

## 6. Vulnerability disclosure — PROPOSED

No disclosure process exists. Proposed for when anything is deployed: a named contact in this
document, acknowledgement within a stated window, and no public issue for an unpatched flaw.
**UNRESOLVED** — needs an owner, and is grouped with U-7 because it only becomes live at deployment.

---

## 7. Security review triggers

A security review is required before merging any change that: adds an MCP server or agent skill;
alters prompt assembly or the delimiter discipline (S-7); introduces a new data source or host
(`CORPUS_SPEC.md` C-1); touches authentication, rate limiting, or logging; adds a dependency that
executes at import time; or creates any cloud resource. The review is recorded in
`docs/decisions/` or `docs/security/`, per `docs/QUALITY_BAR.md` Q-10.
