# DocScout Setup Report — 2026-10-01

**Phase:** 0 (environment only — no feature code written)
**Agent:** setup agent (Arena.ai)
**Result:** `make verify-setup` → **PASS=15, FAIL=0, BLOCKED=2**
**Headline:** the environment is working and verified. Two items are blocked by a deliberate human
decision (no paid API keys, no GitHub PAT), and **three defects in the brief itself were found and
corrected** — one of them a credential-exposing supply-chain risk (§5.1).

Verification evidence lives under `docs/setup/verify/`, `docs/setup/mcp-verify/`,
`docs/setup/model-smoke/`, `docs/security/`, `corpus/raw/manifest.json`, and
`loadtests/reports/verify/`.

---

## 1. Inventory (Step 0 output)

Raw: `docs/setup/verify/step0-inventory.txt`

| Property | Value |
|---|---|
| OS | Debian GNU/Linux 13 (trixie) |
| Kernel / arch | 6.1.158+ , x86_64 |
| PID 1 | systemd (microVM, **not** a nested container — this is why Docker could be installed) |
| CPU | 2 vCPU |
| RAM | 1.9 GiB total |
| Disk | 25 G total, 15 G free after setup (41% used) |
| User | `user` (uid 1000), passwordless sudo available |

**Pre-existing:** `git 2.47.3`, `python3 3.13.14`, `node v20.20.2`, `npm 10.8.2`, `curl 8.14.1`,
`jq 1.7`, `make 4.4.1`, `openssl 3.5.6`.
**Missing at Step 0:** `uv`, `pnpm`, `docker`, `docker-compose`, `k6`, `gh`, `gcloud`, `aws`,
`psql`, `redis-cli`, `pre-commit`, `gitleaks`, `uvx`.

**Network egress (all reachable):** pypi 200 · npm 200 · huggingface 200 · github 200 · astral.sh
200 · rbi.org.in 200 · sebi.gov.in 200. `api.openai.com` returned 421 and `api.anthropic.com` 404
to unauthenticated `GET /` — expected for those endpoints, not an outage.

**Docker gate:** Docker was absent and is a hard requirement. Because PID 1 is systemd (a Firecracker
microVM rather than a container), `docker.io` installed cleanly and the daemon started —
`26.1.5+dfsg1`, storage driver `overlay2`. **Gate passed; Phase 0 proceeded.**

## 2. Installed tools + versions

| Tool | Version | Install method |
|---|---|---|
| uv | 0.12.21 | `astral.sh/uv/install.sh` |
| Python | 3.12.14 | `uv python install 3.12` (system python untouched) |
| Docker | 26.1.5+dfsg1 | `apt-get install docker.io` (Debian trixie main) |
| Docker Compose | **v5.5.1** | official `docker/compose` release binary → `/usr/libexec/docker/cli-plugins` |
| Node | **v22.23.3** | fnm (no sudo), per brief's preferred route |
| pnpm | 12.8.1 | `corepack prepare pnpm@latest --activate` |
| k6 | **v2.3.0** | official `grafana/k6` release tarball |
| gh | 2.46.0 | `apt-get install gh` |
| psql | 17.11 | `apt-get install postgresql-client` |
| redis-cli | 8.0.2 | `apt-get install redis-tools` |
| gitleaks | 8.30.1 | official `gitleaks/gitleaks` release binary |
| pre-commit | 4.6.2 | `uv tool install pre-commit` |
| AWS CLI | 2.37.7 | official `awscli-exe-linux-x86_64.zip` (human chose AWS) |
| Playwright browsers | chromium 1243 + 1247, headless-shell, ffmpeg (657 MB) | `playwright install` + `@playwright/mcp install-browser` |

**Note (fixed during setup):** fnm was installed with `--skip-shell`, so a plain non-login shell
still resolved the old `node v20`. `~/.bashrc` now exports `~/.local/bin` + fnm and evaluates
`fnm env`; a fresh shell reports `node v22.23.3`, `pnpm 12.8.1`, `uv 0.12.21`.

## 3. Services

Raw: `docs/setup/verify/step2-services.txt`, `docs/setup/verify/step2-services-hnsw.txt`

```
NAME             IMAGE                          STATUS                   PORTS
docscout_db      pgvector/pgvector:0.8.2-pg18   Up (healthy)   0.0.0.0:5432->5432/tcp
docscout_redis   redis:7-alpine                 Up (healthy)   0.0.0.0:6379->6379/tcp
```

| Check | Expected | Actual |
|---|---|---|
| pgvector `extversion` | 0.8.2 | **0.8.2** |
| Postgres server | 18 | **18.4** (Debian 18.4-1.pgdg12+1) |
| cosine distance `<=>` | id=1, cos=0 | **id=1, cos=0** |
| HNSW index + plan | index used | `Index Scan using idx_setup_hnsw`, `Order By: (e <=> '…')` |
| `hnsw.iterative_scan` | off | **off** |
| `hnsw.max_scan_tuples` | 20000 | **20000** |
| `hnsw.ef_search` | — | 40 |
| `SET hnsw.iterative_scan = relaxed_order` | settable | **relaxed_order** ✔ |
| `halfvec` type | available | `[1,2,3]` ✔ |
| FTS (BM25 arm) | `t` | **t** |
| least-privilege role | exists, non-super | `docscout_app` — rolsuper=f, createdb=f, createrole=f; **login verified** |
| Redis | PONG | **PONG** |

Two sub-checks needed correcting during verification, both my own harness errors, not environment
faults: a `\d+` psql meta-command inside `-c` (invalid), and `SHOW hnsw.iterative_scan` issued in a
session that had not yet loaded pgvector's library (the GUCs register lazily — a fresh session
errors with *unrecognized configuration parameter*). Both re-tested correctly; this lazy-GUC
behavior is worth knowing before anyone debugs it in production.

## 4. Python environment

Raw: `docs/setup/verify/step3-python.txt`, full list: `docs/setup/dependency-report.txt`

- Interpreter **3.12.14**; venv **1.8 GB**; `uv.lock` **169 packages**
- `uv.lock` sha256: `600c90010345412c62226029af2b86419b26821ab0a9cca30b3172fc6ee1b98d`
- `uv sync --frozen` → exit 0 (V5)
- **torch 2.14.1+cpu**, `cuda.is_available() = False` (expected and correct on this box),
  `get_num_threads() = 1`; cosine smoke computed
- Key versions: fastapi 0.142.2 · psycopg 3.x · sentence-transformers 6.1.0 · transformers 5.17.0 ·
  openai **2.54.0** · anthropic 1.11.0 · ragas **0.4.3** · deepeval 4.2.7 · pypdf 6.19.0 ·
  trafilatura 2.2.0 · ruff 0.16.9 · mypy 2.3.1

**A CPU-only torch index was pinned deliberately** (`[[tool.uv.index]] pytorch-cpu` +
`[tool.uv.sources] torch`): default PyPI resolution pulls multi-GB CUDA runtimes, which this
2-vCPU/1.9 GiB/25 GB box cannot afford and would never use.

**Dependency conflict resolved (see Known issue K-4):** the brief's exact `uv add` line silently
resolved `ragas` to **0.3.1**, which fails at import (`langchain_community.chat_models.vertexai`
was removed in langchain-community 0.4.x). Root cause is a real ecosystem conflict: `ragas ≥0.4`
pulls `instructor`, which requires `jiter<0.15`, while `openai ≥3.22` requires `jiter>=0.16`.
Resolution: pin `openai>=2.0,<3.0` and `langchain-community>=0.3,<0.4`, giving a coherent
`ragas 0.4.3 + instructor 1.17.0 + openai 2.54.0` stack. Verified by constructing real RAGAS metric
objects offline (`Faithfulness`, `LLMContextPrecisionWithoutReference`, `ResponseRelevancy`).

**Brief correction:** §5's verification imports `ruff`. `ruff` is a Rust binary and exposes no
importable module; `import ruff` always fails. Verified via CLI instead (`ruff 0.16.9`). `mypy` does
import.

## 5. MCP servers

Full audit: `docs/security/mcp-server-audit.md` · per-server evidence: `docs/setup/mcp-verify/*.txt`
Config: `.mcp.json` (no secret values — env-var reference only)

Every server below was verified with a **real MCP handshake** (`initialize` → `tools/list`) using
`scripts/mcp_probe.py`, and **every tool description was read in full** and passed through a
red-flag regex (exfiltration verbs, `~/.ssh`, `id_rsa`, `.env`, `curl`, `base64`, `<IMPORTANT>`,
"ignore previous…"). I confirm I read and approved every tool description (guardrail §1.1).

| Server | Source | Version | Transport | Credential (name/scope) | Tools | Red flags | Verify evidence |
|---|---|---|---|---|---|---|---|
| playwright | `@playwright/mcp` (Microsoft, official) | **0.0.83** (pinned) | stdio | none | 25 | 0 | `mcp-verify/playwright.txt` — navigated `about:blank`, snapshot, screenshot ✔ |
| context7 | `mcp.context7.com/mcp` (Upstash, official) | server v4.1.1 | http | none (free tier) | 2 | 0 | `mcp-verify/context7.txt` — resolved `/websites/fastapi_tiangolo`, retrieved real `Depends` docs ✔ |
| memory | `@modelcontextprotocol/server-memory` (official MCP reference) | **2026.8.31** (pinned) | stdio | none | 9 | 0 | `mcp-verify/memory.txt` — create → read → delete → read-empty cycle ✔ |
| github | `ghcr.io/github/github-mcp-server` (official) | image pulled | stdio/docker | `GITHUB_PAT` — *not issued* | 48 listed | 0 | **BLOCKED** — no PAT; tools enumerated but no authenticated call |
| postgres | — | — | — | — | — | — | **REJECTED — see §5.1** |

Not installed, per §6.1/§12: filesystem, sequential-thinking, brave-search/perplexity, and any
other community server.

### 5.1 REJECTED: the brief's Postgres MCP server — **requires a human decision**

The brief (§6.2) specifies:
`"command": "uvx", "args": ["mcp-server-postgres", "postgresql://docscout:${DB_PASSWORD}@localhost:5432/docscout"]`

**I did not run this.** PyPI metadata for `mcp-server-postgres` (fetched 2026-10-01):

```
version: 0.1.0 | summary: "Add your description here"   <-- unedited `uv init` default
author: a personal gmail address, unaffiliated | home_page: none | project_urls: {} | license: none
requires: []  <-- a Postgres MCP server with zero dependencies | first upload: 2025-02-28
```

This is not an Anthropic/MCP reference server. The official Postgres reference server shipped on
**npm** as `@modelcontextprotocol/server-postgres` (now carrying an npm deprecation notice) and
never on PyPI under this name. An unaffiliated, undocumented, zero-dependency package squatting an
official-sounding name is precisely the guardrail-§1.1 / postmark-mcp pattern.

The risk is amplified by the brief's own invocation: it passes the **database superuser password as
a command-line argument** to that package, and `uvx` would fetch the latest release at every launch
(no pin), so the executed code could change at any time. Nothing was downloaded or executed.

Separately, `mcp-server-memory` on PyPI is also **not** the reference server — it is version 0.0.1,
`"This package is reserved."`, an Amazon defensive namespace placeholder. The genuine memory server
was used from npm instead.

**Decision needed from the human — pick one:**
- **(A) No Postgres MCP server (recommended).** `psql` is installed and shell access exists, so
  schema inspection already works with zero added trust boundary and no credential hand-off.
- **(B) Approve the maintained community server** `postgres-mcp` (crystaldba, PyPI 0.3.0) — needs
  explicit approval under §6, must be version-pinned, and must connect as the least-privilege
  `docscout_app` role via env var, never the superuser via argv.
- **(C) Use the deprecated official** `@modelcontextprotocol/server-postgres@0.6.2` — official
  provenance, but archived and unmaintained.

### 5.2 Notes on approved servers

- **playwright** exposes `browser_run_code_unsafe` (arbitrary JS in page). Honestly named, inherent
  to browser automation, but a real capability risk — mitigated by running `--headless --isolated`
  (ephemeral profile) and the standing rule that corpus documents are never rendered in it.
- **context7** descriptions contain imperatives ("You MUST call this function before…"). Read in
  full and judged **in scope** — they order calls to the server's own tools; no external URLs to
  fetch, no file or credential access, no concealment. Accepted; results remain untrusted data.
- **Scanner:** the brief's `mcp-scan` has been **renamed to `snyk-agent-scan`**. Its full threat
  `scan` now requires a `SNYK_TOKEN`, which is outside the §10.1 credential list, so it was not
  requested — **no automated verdict is available**. The token-free `inspect` mode was run
  (`docs/security/mcp-scan-servers.txt`) and the manual description audit above compensates.

## 6. Skills

Full audit: `docs/security/skills-audit.md`

| Set | Source | Pin | Count |
|---|---|---|---|
| Superpowers | `github.com/obra/superpowers` (MIT, 293k stars) | commit **`8ca22dba9a94f28898bbce59f2537ff4d87c747d`** = Release **v6.4.2**, 2026-09-25 | 15 |
| DocScout project skills | written in-repo (§7.4c) | n/a | 6 |

**Install-method deviation:** no Claude Code plugin client exists here, so
`/plugin marketplace add` was unavailable. Used the documented fallback: clone at a pinned commit
and vendor `skills/` into `.claude/skills/`. No auto-update is active.
`security-guidance` (§7.4b) could **not** be installed for the same reason — recorded, not skipped
silently.

**Pre-install audit (ClawHavoc-aware), all 2.4 MB of the tree:**

| Check | Result |
|---|---|
| Writes to memory/instruction files (`CLAUDE.md`, `AGENTS.md`, `.claude/settings`) | **none** |
| pipe-to-shell / `base64` / `nc` / `/dev/tcp` / `eval $(…)` in executable code | **none** (one `curl` example inside prose docs) |
| Credential access (`~/.ssh`, `id_rsa`, `.env`, api keys) | **none** |
| Outbound hosts in executable code | 2 only — a docs link, and the beacon below |
| Auto-executing hooks | one `SessionStart` hook; read in full — it `cat`s a SKILL.md into context. No network, no writes. Benign |

**Finding (low, accepted):** `skills/brainstorming/scripts/server.cjs` renders a remote branding
image from `primeradiant.com` — a usage/IP beacon, not exfiltration (no project data leaves).
Mitigated by `SUPERPOWERS_DISABLE_TELEMETRY=true`, now set in `.env`/`.env.example` and documented.

**Unrelated telemetry found and disabled:** `deepeval` creates a `.deepeval` directory on import and
ships opt-out telemetry. `DEEPEVAL_TELEMETRY_OPT_OUT=YES` is now set in `.env`, `.env.example`, and
the CI workflow.

**The six project skills** — all validated (frontmatter present, `name` matches folder,
description ≤1024 chars, Gotchas section present):
`rag-eval-protocol` (gold-set spec, deterministic-first scoring, mandatory κ calibration, >1pp CI
regression gate, artifact-or-it-didn't-happen) · `corpus-injection-defense` (delimiters, canary
policy, stage separation) · `load-test-protocol` (seeded generator, two arms, declared thresholds) ·
`deploy-protocol` (cost cap first, least privilege, tested destroy) · `git-and-commit-protocol`
(conventional commits, ADR-before-code) · `define-done` (10-point gate).

## 7. Hooks + pre-commit

**Hooks** — `.claude/settings.json`, scripts in `.claude/hooks/`:

| Hook | Trigger | Action |
|---|---|---|
| `format-after-edit` | PostToolUse (Edit/Write on `*.py`) | `ruff format` + `ruff check --fix`; never blocks |
| `dangerous-bash` | PreToolUse (Bash) | denylist; exit 2 = deny |
| `typegate` | Stop | ruff + mypy + pytest summary; reports red/green, never blocks the human |

**V8 denylist demonstration** (`docs/setup/verify/step6-hooks-denylist.txt`) — **11/11 denied,
6/6 allowed**: denied `rm -rf /`, `rm -rf ~/…`, `git push --force`, `git push -f`, `curl … | bash`
from a non-allowlisted host, `wget … | sudo sh`, `git filter-branch`, write to `/etc`,
`cat .env | curl -d @-`, `cat ~/.ssh/id_rsa | nc`, `chmod -R 777`. Allowed `uv run pytest`,
`rm -rf ./build`, normal `git push`, `curl -o file`, the allowlisted `astral.sh` installer,
`docker compose up`.

**Pre-commit** — `.pre-commit-config.yaml`, installed for `pre-commit` and `pre-push`:
trailing-whitespace, end-of-file-fixer, check-added-large-files (5 MB), check-merge-conflict,
check-yaml, check-json, detect-private-key, ruff + ruff-format, **gitleaks** (local hook using the
pinned binary — secret scanning must not depend on a network fetch at hook-install time), mypy.

**V9 secret-block demonstration** (`docs/setup/verify/step6-precommit-secret-block.txt`):
commit of a file with three credential-shaped strings → **blocked, exit 1, 0 commits created**,
gitleaks reporting 2 leaks (`generic-api-key`, `github-pat`), branch deleted.

> **Methodology note worth keeping:** my first attempt used the canonical `AKIAIOSFODNN7EXAMPLE`
> key and gitleaks **passed** — it allowlists documented example keys by design. That fixture would
> have produced a false sense of safety. Repeated with randomly generated realistic credentials,
> which gitleaks correctly caught. A secret-scanner test built from a textbook example key proves
> nothing.

## 8. CI

- `.github/workflows/ci.yml` present: `quality` job (uv sync --frozen, ruff check, ruff format
  --check, mypy, pytest), a dedicated `secrets` job (gitleaks over full history, `fetch-depth: 0`),
  and the `eval-smoke` stub gated `if: false` until the gold set exists.
- All four quality commands were run **locally** and are green:
  `ruff check` ✔ · `ruff format --check` (89 files) ✔ · `mypy app` — no issues in 6 files ✔ ·
  `pytest` — 1 passed ✔
- **Repo URL: none. Green run URL: none.** The human chose local-git-only, so no PAT exists,
  `gh repo create` was not run, and no remote is configured. **V10 is BLOCKED, not passed.**
- `.mcp.json` is committed. It contains no secret values (env-var reference only). Per §8.3 the
  final call on committing it is the human's — flagged for sign-off.

## 9. Models

`config/models.json` · evidence `docs/setup/model-smoke/`

**Hosted roles: UNPINNED / BLOCKED.** The human declined paid API keys. Guardrail §1.6 forbids
guessing a model ID, so every hosted `id` in `config/models.json` is **`null`**, with the brief's
September-2026 candidate recorded separately as `brief_candidate_sep2026` — a starting point for
live verification, never a pin. The §10.2 procedure was executed anyway to record the真 API
response: `OpenAIError: Missing credentials` / `TypeError: Could not resolve authentication method`
(`docs/setup/model-smoke/VERIFICATION-BLOCKED.txt`).

**Local models: VERIFIED** (`docs/setup/model-smoke/local-models.json`):

| Role | Model | Measured on this box |
|---|---|---|
| Embeddings (local) | `BAAI/bge-small-en-v1.5` | **384 dims**; load 5.06 s; **1k sentences in 8.90 s = 112.4/s**; 129 MB |
| Reranker (local) | `cross-encoder/ms-marco-MiniLM-L-6-v2` | **4.56 ms/pair** over 50 pairs (0.228 s); sample score −2.233; 88 MB |

Reranker threshold check (§10.2: >50 ms/pair ⇒ downgrade): **4.56 ms/pair — PASS with wide margin**,
so the heavier `bge-reranker-v2-m3` stays viable as a build-phase A/B arm rather than being excluded
on latency. `HF_HOME=/home/user/.hf_cache` (217 MB) is outside the repo and gitignored.

**Phase 0 API spend: $0.00** — zero authenticated calls were made to any paid provider.
(Budget was <$5; actual $0.00.)

## 10. Corpus machinery

`docs/corpus-provenance.md` · `corpus/raw/manifest.json` · `docs/setup/verify/step8-corpus.txt`

**Result: 20/20 documents extracted >500 clean chars** (criterion ≥18/20) — 10 RBI + 10 SEBI,
2,269–47,603 chars each, every one `http 200`, each recorded with URL + SHA-256 + byte count +
page count + extractor + fetch timestamp.

Access patterns had to be **discovered, not assumed**:
- **RBI** index pages are ASP.NET `__doPostBack`, but notification listings embed absolute
  `rbidocs.rbi.org.in/*.pdf` URLs — plain HTTP fetch suffices.
- **SEBI** returns **403** on directory paths (`/legal/circulars`) to non-browser clients, while
  individual circular pages return 200. Critically, **the detail page body is a near-empty stub
  (~227 extractable chars) — the real content is a PDF behind an `<iframe src=…file=…>`**. Extracting
  the HTML alone would have yielded almost nothing while looking like success.

**Injection canary (guardrail §1.2):** one synthetic document carrying injected instructions in
three positions (header, mid-paragraph, footnote) was ingested; it extracted normally
(1,524 raw / 1,458 normalized chars, sha256 `ef1f71aed2b9ac55…`) and is logged in
`docs/security/injection-canary-log.md`. It will ship in the eval gold set as a graded negative test.

**Corpus scanned for real injections:** all 20 documents checked against 11 patterns for
instructions *addressed to an assistant/agent* — **0 matches in real documents; 11 matches in the
canary**, confirming the detector is not silently returning clean
(`docs/setup/verify/step8-injection-scan.txt`).

No chunking, embedding, or gold-set work was done. Stopped exactly where §10.4 says to stop.

## 11. UI + load

- **UI:** Vite + React-TS scaffolded in `ui/` (vite 8.3.1, typescript 6.0.3), `pnpm install` clean,
  `pnpm build` succeeds (222 kB JS / 69 kB gzip). Playwright 1.63.0 + Chromium installed.
- **Browser smoke (V14):** `ui/tests/smoke.spec.ts` passed — launches Chromium, asserts the
  document, screenshots to **`docs/setup/ui-smoke.png`** (PNG 1280×720, 15 KB).
- **Load (V15):** k6 v2.3.0 against the local dummy (`loadtests/dummy_server.py`), 10 iters/s
  constant-arrival-rate for 30 s: **301 requests, 0 failures, 512/512 checks passed**, all declared
  thresholds met. Report dir: **`loadtests/reports/verify/20261001T101742Z/`** (`summary.json`,
  `k6-stdout.txt`, `conditions.md`).
  **These numbers measure the harness and the box, not DocScout, and are not claimable anywhere** —
  the target is a stub returning a constant, and load generator and target shared the same 2 vCPUs.

## 12. Verification matrix (V1–V17)

`make verify-setup` → **PASS=15 FAIL=0 BLOCKED=2** (`scripts/verify_setup.sh`, re-runnable)

| # | Check | Result | Evidence |
|---|---|---|---|
| V1 | Toolchain | **PASS** | all required tools report versions — §2 |
| V2 | Postgres + pgvector | **PASS** | pgvector=0.8.2, cosine=0, iterative_scan=off/20000, FTS=t — `verify/step2-services*.txt` |
| V3 | Redis | **PASS** | PONG |
| V4 | Python env | **PASS** | all imports, torch 2.14.1+cpu CPU smoke — `verify/step3-python.txt` |
| V5 | Lockfile | **PASS** | `uv sync --frozen` exit 0, 169 pkgs |
| V6 | MCP servers | **PASS** (3/3 verifiable) | real tool calls — `mcp-verify/*.txt`; github BLOCKED, postgres REJECTED |
| V7 | Skills | **PASS** | 6/6 project skills valid, 21 SKILL.md total — `security/skills-audit.md` |
| V8 | Hooks | **PASS** | 11/11 denied, 6/6 allowed — `verify/step6-hooks-denylist.txt` |
| V9 | Pre-commit | **PASS** | fake secret blocked, 0 commits — `verify/step6-precommit-secret-block.txt` |
| V10 | CI | **BLOCKED** | workflow present, commands green locally; no PAT ⇒ no repo, no run URL |
| V11 | Models (hosted) | **BLOCKED** | no keys; roles `null`; spend $0.00 — `model-smoke/VERIFICATION-BLOCKED.txt` |
| V12 | Local models | **PASS** | 384 dims, 4.56 ms/pair — `model-smoke/local-models.json` |
| V13 | Corpus machinery | **PASS** | 20/20 >500 chars + 1 canary — `corpus/raw/manifest.json` |
| V14 | UI/browser | **PASS** | `docs/setup/ui-smoke.png` |
| V15 | Load pipeline | **PASS** | `loadtests/reports/verify/20261001T101742Z/` |
| V16 | Secrets sweep | **PASS** | git-log pattern sweep 0 findings; gitleaks full history clean |
| V17 | Clean running state | **PASS** | only `db` + `redis`; no other containers; **0 cloud resources** |

## 13. Known issues

Every deviation, failure, and version drift. No omissions.

**Blocked by human decision (expected, not defects):**
- **K-1 — No LLM API keys.** Human declined paid keys. ⇒ V11 blocked; all hosted model roles
  unpinned; no generator/judge smoke calls. **Build-phase impact: the eval design in
  `rag-eval-protocol` (LLM-as-judge, cross-provider calibration, κ against human labels) cannot run
  at all without keys.** The deterministic scorer layer (citation precision/recall, key-point
  coverage, retrieval recall@k/MRR/nDCG) and the full local-model arm *can*. This needs a decision
  before the build phase: provide keys, or re-scope the eval harness to deterministic + local-judge
  metrics and drop the calibrated-judge claim from the portfolio narrative.
- **K-2 — No GitHub PAT.** ⇒ V10 blocked (no repo, no green CI run URL), github MCP enumerated but
  unauthenticated. Local git history exists and pre-commit/gitleaks are proven locally.
- **K-3 — AWS CLI installed but unconfigured.** Human chose AWS; no credentials were requested
  (Phase 0 creates nothing). `aws --version` works; no read-verification of a project was possible.
  Cost cap, billing alarm, and least-privilege role remain to be created in the deploy phase under
  `deploy-protocol`.

**Defects found in the brief (corrected; reality wins):**
- **K-4 — `ragas` dependency conflict.** The brief's `uv add` line yields a broken ragas 0.3.1
  (ImportError). True cause: `instructor` needs `jiter<0.15`, `openai≥3.22` needs `jiter>=0.16`.
  Fixed by pinning `openai>=2.0,<3.0` + `langchain-community>=0.3,<0.4`. **Consequence: the OpenAI
  SDK is held one major version behind**; revisit when instructor/ragas support openai 3.x. Worth
  an ADR in the build phase.
- **K-5 — `docker-compose.yml` volume path is wrong for Postgres 18.** The brief mounts
  `pgdata:/var/lib/postgresql/data`; pg18 images store data in major-version subdirectories and
  **exit(1) on boot** with that mount. Corrected to `pgdata:/var/lib/postgresql`
  (docker-library/postgres#1259).
- **K-6 — `infra/initdb/01-extensions.sql` cannot expand `${DB_APP_PASSWORD}`.** Postgres does not
  expand env vars inside `.sql` files, so the brief's SQL would have created the app role with the
  **literal password** `${DB_APP_PASSWORD}`. Role creation moved to `02-app-role.sh`, where the
  variable really expands; login verified.
- **K-7 — `import ruff` is impossible** (Rust binary, no Python module). Verified by CLI.
- **K-8 — MCP server packages in §6.2 are wrong and one is dangerous.** See §5.1. `uvx
  mcp-server-postgres` is an unvetted PyPI package that would have received the DB superuser
  password via argv; `uvx mcp-server-memory` is an Amazon-reserved placeholder. **Awaiting human
  decision.**
- **K-9 — `mcp-scan` is now `snyk-agent-scan`** and its threat scan requires a `SNYK_TOKEN` (outside
  the §10.1 credential list, so not requested). **No automated skills/MCP verdict exists**; replaced
  by a manual audit. If an automated verdict is required, the human must decide whether to issue a
  Snyk token.
- **K-10 — `security-guidance` plugin not installed**: requires a Claude Code plugin client, which
  this environment lacks (same reason Superpowers was vendored by git clone rather than `/plugin`).

**Version drift from the brief (recorded, not silently "upgraded"):**
- **K-11 — pgvector image:** stayed on the pinned `0.8.2-pg18` as instructed. **`0.8.6-pg18` is the
  current upstream tag** (2026-08-13). Deliberately not upgraded in Phase 0.
- **K-12 — Docker Compose v5.5.1, k6 v2.3.0, gitleaks 8.30.1, pnpm 12.8.1, Node 22.23.3** are all
  newer than anything the brief implies; latest stable at install time, recorded here.
- **K-13 — Postgres server is 18.4**, psql client is **17.11** (Debian trixie ships 17). Client/server
  mismatch is harmless here, but `pg_dump` from a 17 client against an 18 server will refuse —
  relevant for backups later.
- **K-14 — Docker Compose warning**: the `ui/` directory was briefly deleted by a `git stash -u`
  during the V9 test (git does not track empty directories). Recreated; harmless, but a reminder
  that empty scaffold dirs do not survive git operations — add `.gitkeep` files if they must.

**Environment limits that will shape the build phase:**
- **K-15 — 2 vCPU / 1.9 GiB RAM.** Embedding throughput measured at **112 sentences/s**; a
  10k-chunk corpus is ~90 s of pure embedding, and anything larger will dominate iteration time.
  *(Correction, 2026-10-01, ADR-0002: the "~90 s" extrapolation is wrong by ~16×. Measured on real
  1,000-char corpus chunks the rate is 6.9 chunks/s, so 10k chunks is ~24 min. The 112 sentences/s
  measurement itself stands; only the extrapolation to chunks was unsound. Original wording kept
  because this report is the signed Phase 0 record.)*
  Memory is tight enough that Postgres + Redis + torch + Chromium should not run concurrently under
  load. Any latency/throughput number produced on this box must carry that caveat.
- **K-16 — No `robots.txt`/ToS audit performed** for rbi.org.in or sebi.gov.in, and no explicit
  machine-readable licence was located. Documents are public regulatory material and were fetched
  politely at low volume with an identifying UA, but **a terms review is outstanding before any
  public deployment**.
- **K-17 — SEBI extraction fragility:** attachment filenames are opaque timestamps and detail-page
  HTML is a stub. If SEBI changes the iframe pattern, extraction silently yields ~227 chars rather
  than failing loudly. The build-phase ingester needs a minimum-length assertion per document.

## 14. Cost record

| Item | Amount |
|---|---|
| OpenAI / Anthropic API (Phase 0 smoke) | **$0.00** — no keys, no authenticated calls |
| Cloud (AWS) | **$0.00** — no account configured, **zero resources created** |
| Context7 | $0.00 (free tier, no key) |
| Hugging Face model downloads | $0.00 (public, anonymous) |
| **Total Phase 0 spend** | **$0.00** (budget was <$5) |

Local resource consumption: 9.8 GB disk used (venv 1.8 GB, Playwright browsers 657 MB, HF cache
217 MB, ui/node_modules 105 MB), 15 GB free.

## 15. Sign-off

**Agent statement.** Every claim above is backed by a file in this repository. I did not fabricate
any result. Items that could not be completed are marked **BLOCKED** or **FAIL** rather than passed:
V10 (CI) and V11 (hosted models) are blocked by the deliberate absence of credentials, and the
Postgres MCP server was **rejected rather than installed** because its provenance failed the
guardrail-§1.1 check. Three defects in the brief itself (K-4, K-5, K-6) were found by execution and
corrected; the corrections are documented inline in the affected files.

I have **not** written any DocScout feature code, gold-set content, chunking, embedding, or
retrieval logic. Phase 0 stops here, as instructed.

Signed: setup agent — 2026-10-01

---

### Decisions requested from the human

1. **Postgres MCP server (§5.1)** — choose (A) none / (B) approve pinned `postgres-mcp` with the
   least-privilege role / (C) deprecated official npm server.
2. **Eval strategy under K-1** — provide API keys, or re-scope the harness to deterministic +
   local-judge metrics and adjust the portfolio claim accordingly.
3. **Commit `.mcp.json`?** It is currently committed and contains no secret values (§8.3 asks for an
   explicit decision).
4. **Snyk token (K-9)** — issue one for automated MCP/skill scanning, or accept the manual audit.
5. **Corpus ToS review (K-16)** — confirm who performs it before deployment.

### HUMAN SIGN-OFF

- [ ] **APPROVE** — environment accepted; proceed to the build phase on receipt of the implementation spec.
- [ ] **REJECT** — changes required (notes below).

Notes:

```
(human to complete)
```
