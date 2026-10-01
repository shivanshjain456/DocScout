# DocScout — Quality Bar

**Status:** authoritative definition of done and of the gates every change must clear.
Last updated **2026-10-01**.
**Implementation status:** the repository-level gates below are **live and enforced today**
(VERIFIED). The product-level gates (evaluation, load, deploy) are specified and **not yet
enforceable**, because the product does not exist (`SPEC.md` §2.2).

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9.

**Relationship to the `define-done` skill:** `.claude/skills/define-done/SKILL.md` is the
agent-facing checklist, loaded before any completion claim. This document is the normative bar and
adds the evidence rules and the gate inventory. The two agree; if they diverge, this document
governs.

---

## 1. The two rules everything else serves

**Q-0 — Evidence or it didn't happen.** Every claim of working behaviour names the command output,
file path, or report directory that proves it. "It runs" is not "it works"; a green import proves
nothing about behaviour.

**Q-0b — Unmarked partial completion is a lie.** "Done except X" is acceptable and normal. Silently
omitting X is not. Gaps go into Known issues with an ID.

These two rules are why Phase 0 shipped with an honest **PASS=15 / FAIL=0 / BLOCKED=2** rather than
a cosmetic all-green.

---

## 2. Gates enforced today — VERIFIED

### 2.1 Pre-commit — 11 hooks, demonstrated on real commits

From `.pre-commit-config.yaml` (`default_install_hook_types: [pre-commit, pre-push]`):

| Hook | Source |
|---|---|
| `trailing-whitespace`, `end-of-file-fixer`, `check-added-large-files` (max 5 MB), `check-merge-conflict`, `check-yaml`, `check-json`, `detect-private-key` | `pre-commit-hooks` v6.0.0 |
| `ruff` (`--fix`), `ruff-format` | `ruff-pre-commit` v0.16.9 |
| `gitleaks` — `gitleaks git --pre-commit --redact --staged --verbose` | local hook, pinned binary |
| `mypy` — `uv run mypy app` | local hook |

Two deliberate configuration choices that must not be "cleaned up":

- `check-json` excludes `^ui/tsconfig.*\.json$` — Vite emits JSONC, where comments are legal.
  Stripping the comments from generated config was rejected.
- `gitleaks` is a **local** hook using a pinned binary rather than a fetched toolchain: secret
  scanning must not depend on a network fetch succeeding.

**Q-1 — SPECIFIED.** `--no-verify` is forbidden, without exception.

**VERIFIED, and not merely asserted.** The chain is known to bite: on 2026-10-01 the first attempt
at the version-control restoration commit was **rejected** by `trailing-whitespace` and
`end-of-file-fixer`, which modified six files; the commit only succeeded after re-staging. Every
commit in this repository has passed all 11 hooks, including `gitleaks` and strict `mypy`. A hook
chain that has never failed a commit is a hook chain nobody has tested.

### 2.2 CI — `.github/workflows/ci.yml`

| Job | Steps | State |
|---|---|---|
| `quality` | `uv sync --frozen` → `ruff check .` → `ruff format --check .` → `mypy app` → `pytest -q` | Defined; **never executed on a remote** (no GitHub remote — K-2, U-6, matrix item V10 BLOCKED) |
| `secrets` | `gitleaks-action@v2` with `fetch-depth: 0` (full history) | Defined, same caveat |
| `eval-smoke` | stub | **`if: false`** — activates when the gold set exists |

**Q-2 — VERIFIED locally, BLOCKED remotely.** All four `quality` commands are green on the current
tree: `ruff check` clean, `ruff format --check` clean across 89 files, `mypy app` clean in strict
mode over 6 files, `pytest` 1 passed. The honest statement is: *the gates pass locally and have
never run in CI.*

### 2.3 Static analysis configuration — VERIFIED

- **ruff**: `line-length = 100`, `target-version = py312`, rules `["E","F","I","B","UP","S","ASYNC"]`,
  `ignore = ["E501"]`; per-file ignores `tests/** = ["S101"]`, `scripts/** = ["S101","S310"]`.
  Note `S` (bandit) and `ASYNC` are on — security and async-correctness lint are part of the bar.
- **mypy**: `strict = true`, `warn_unused_ignores = true`, `ignore_missing_imports = true`,
  `python_version = 3.12`. Strict mode applies to `app/` from the first line of code written.
- **pytest**: `testpaths = ["tests"]`, `addopts = "-q"`.

### 2.4 Environment verification — VERIFIED

`make verify-setup` runs the V1–V17 matrix (`scripts/verify_setup.sh`). Last result:
**PASS=15, FAIL=0, BLOCKED=2** (V10 CI run, V11 hosted models).

**Q-3 — SPECIFIED.** `make verify-setup` must still be green after any change.

*Caveat, VERIFIED 2026-10-01:* the matrix has **not** been re-run since Phase 0. `scripts/bootstrap.sh`
restores the `core` toolchain — enough for every gate in §2.1 to 2.3 — but the `full` tier (Docker,
Compose, Node/pnpm, k6, AWS CLI) that V2, V3, V12, V14 and V15 depend on has not been exercised
here. Closing that is `docs/MILESTONES.md` M0 exit criterion 2, and the remaining scope of U-15.

---

## 3. Definition of done — SPECIFIED

A unit of work is done only when every line below has a stated result. Work the list top to bottom.

| # | Item | Pass condition |
|---|---|---|
| 1 | **Tests** | New behaviour has tests written **before** the implementation. Every bug fix ships a regression test **demonstrated to fail before the fix**. No untested public function. `uv run pytest -q` green |
| 2 | **Types** | `uv run mypy app` clean. No new `# type: ignore` without a comment saying why |
| 3 | **Lint/format** | `uv run ruff check .` and `uv run ruff format --check .` clean |
| 4 | **Docs** | Docstrings on public functions; `README.md` / `AGENTS.md` updated if commands or behaviour changed; `.env.example` updated for any new config key |
| 5 | **Architecture** | `docs/architecture/ARCHITECTURE.md` **and** `docs/architecture/system-diagram.md` updated if a boundary, component, or data flow changed |
| 6 | **ADR** | Written and committed **before** the code if the change involved a decision with a rejected alternative |
| 7 | **Artifacts** | Any metric, latency, or cost number stated anywhere has its raw report directory committed and referenced |
| 8 | **Environment** | `make verify-setup` green |
| 9 | **Security** | No secret added; corpus text still treated as data; any new external input delimited; `make secret-scan` passes |
| 10 | **Clean state** | No debug prints, commented-out code, TODOs without an issue reference, or scratch files. **No cloud resource left running** |
| 11 | **Spec consistency** | If the change closes an Unresolved Register item, `SPEC.md` §9 is updated with the evidence that closed it |

Item 11 is this document set's addition to the skill checklist: the register is only useful if it
shrinks.

---

## 4. Evidence rules

**Q-7 — SPECIFIED. No metric without an artifact.** A quality, latency, or cost number may appear
in a README, commit message, ADR, report, UI, or conversation **only** if its raw output file exists
and is referenced:

| Claim type | Required artifact |
|---|---|
| Retrieval or answer quality | `evals/reports/<UTC-ts>/{results.json, report.md, raw-judge-outputs/}` (`docs/eval/EVAL_PROTOCOL.md` E-13) |
| Latency or throughput | `loadtests/reports/<UTC-ts>/{summary.json, k6-stdout.txt, conditions.md}` |
| Environment capability | `docs/setup/verify/<step>.txt` and the V-matrix row |
| Security control | The audit or log file under `docs/security/` |

**Q-8 — SPECIFIED. Every performance number carries its conditions.** Hardware, concurrency, what
was on the other end, and whether it was the real service. The Phase 0 hardware floor is
**2 vCPU / 1.9 GiB RAM** (K-15), and it materially affects every measurement taken on it.

**Q-9 — SPECIFIED. A number measured against a stub is not a product number.** The existing k6 run
(301 iterations at 10.03/s, 0 failed requests, 512/512 checks, p95 **1.71 ms**) was taken against a
**constant-returning dummy server sharing the same 2 vCPUs**. It demonstrates that the load harness
works. It is **not** DocScout latency and must never be quoted as such. Evidence:
`loadtests/reports/verify/20261001T101742Z/`.

**Q-10 — SPECIFIED. Decisions are written before the code.** Any decision with a rejected
alternative gets an ADR in `docs/decisions/` (template: `docs/decisions/0000-template.md`) before
implementation. Security-relevant changes additionally trigger the review list in `SECURITY.md` §7.

**Q-11 — SPECIFIED. Commits.** Conventional, atomic, imperative. No "final", no "wip", no bulk
multi-feature commits. `make secret-scan` passes over full history before push.

---

## 5. Product quality gates — SPECIFIED, not yet enforceable

| ID | Gate | Threshold | Blocked by |
|---|---|---|---|
| Q-12 | Evaluation regression gate | Fail the build on **> 1 pp** regression on any threshold metric vs the mean of the last 3 baseline runs | Gold set (M3); CI job is `if: false` today |
| Q-13 | Citation precision | **≥ 0.90** | Same |
| Q-14 | Faithfulness | **≥ 0.85** | Judge availability — **BLOCKED (U-1)** |
| Q-15 | Context precision | **≥ 0.70** | Same |
| Q-16 | Canary resistance | Injected instruction not followed, every run | Gold set |
| Q-17 | End-to-end latency | **p95 < 3 s** against the real service | Service existence; feasibility unmeasured (U-14) |
| Q-18 | Gold set size and composition | **≥ 120** hand-built items, **≥ 10 %** unanswerable (refusal scored as PASS), **≥ 1** injection canary | Gold set (M3) |

Thresholds are quoted identically in `docs/eval/EVAL_PROTOCOL.md` §6. Changing one is an ADR, never
a quiet edit, and never after seeing the result you want.

---

## 6. Known traps

- **A skipped test is a failing test wearing a disguise.** Count skips and justify each.
- **Re-run the check *after* the last edit.** Claiming done from a stale run is the most common
  failure mode.
- **A warm environment hides missing dependencies.** `uv sync --frozen` in a clean virtualenv is
  the real check. `scripts/bootstrap.sh` now performs exactly that on every run, which is how the
  lockfile was confirmed to still reproduce (same SHA-256, 164 packages) after the environment was
  lost and rebuilt.
- **Tooling that lives outside the repository is not part of the repository.** The entire Phase 0
  toolchain vanished with one snapshot while every source file survived. If a capability is not
  reconstructible by a committed script, the project does not really have it (`SPEC.md` §2.3).
- **An unanchored `.gitignore` pattern excludes silently.** `corpus/` matched `docs/corpus/` at a
  different depth and would have dropped a required deliverable from the repository with no error
  of any kind (ADR-0001). Anchor directory patterns with a leading slash, verify with
  `git check-ignore -v` rather than by reading them, and read `git status` before every commit —
  not after.
- **Green local gates are not CI.** Nothing in this repository has ever been verified by CI (U-6).
- **The gold set becomes a training set** the moment configuration is tuned by watching its score
  (`EVAL_PROTOCOL.md` E-17).
