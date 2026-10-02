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

### 2.1 Pre-commit — 12 hooks, demonstrated on real commits

From `.pre-commit-config.yaml` (`default_install_hook_types: [pre-commit, pre-push]`):

| Hook | Source |
|---|---|
| `trailing-whitespace`, `end-of-file-fixer`, `check-added-large-files` (max 5 MB), `check-merge-conflict`, `check-yaml`, `check-json`, `detect-private-key`, `check-shebang-scripts-are-executable` | `pre-commit-hooks` v6.0.0 |
| `ruff` (`--fix`), `ruff-format` | `ruff-pre-commit` v0.16.9 |
| `gitleaks` — `gitleaks git --pre-commit --redact --staged --verbose` | local hook, pinned binary |
| `mypy` — `uv run mypy app` | local hook |

Three deliberate configuration choices that must not be "cleaned up":

- `check-shebang-scripts-are-executable` was added on 2026-10-01 after a snapshot stripped the
  executable bit from all 16 shebang scripts and the loss was committed unnoticed — silently
  disabling the agent command denylist (`SECURITY.md` S-16). File modes do not show up when
  reading a diff, so the guard is the only reliable defence.

- `check-json` excludes `^ui/tsconfig.*\.json$` — Vite emits JSONC, where comments are legal.
  Stripping the comments from generated config was rejected.
- `gitleaks` is a **local** hook using a pinned binary rather than a fetched toolchain: secret
  scanning must not depend on a network fetch succeeding.

**Q-1 — SPECIFIED.** `--no-verify` is forbidden, without exception.

**VERIFIED, and not merely asserted.** The chain is known to bite: on 2026-10-01 the first attempt
at the version-control restoration commit was **rejected** by `trailing-whitespace` and
`end-of-file-fixer`, which modified six files; the commit only succeeded after re-staging. Every
commit in this repository has passed every hook, including `gitleaks` and strict `mypy`. A hook
chain that has never failed a commit is a hook chain nobody has tested.

### 2.2 CI — `.github/workflows/ci.yml`

| Job | Steps | State |
|---|---|---|
| `quality` | `uv sync --frozen` → `ruff check .` → `ruff format --check .` → `mypy app` → `pytest -q` | Defined; **never executed on a remote** (no GitHub remote — K-2, U-6, matrix item V10 BLOCKED) |
| `secrets` | `gitleaks-action@v2` with `fetch-depth: 0` (full history) | Defined, same caveat |
| `eval-smoke` | stub | **`if: false`** — activates when the gold set exists |

**Q-2 — VERIFIED locally, BLOCKED remotely.** All four `quality` commands are green on the current
tree: `ruff check` clean, `ruff format --check` clean across 101 files — 11 Python and 90
Markdown, since `ruff format` formats both. The total moves with every file added and with any
`.gitignore` change, so read it as a composition, not as a measure of project size — `mypy app`
clean in strict
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

**VERIFIED 2026-10-01, re-run and reproduced.** After `scripts/bootstrap.sh full` rebuilt the
toolchain from scratch, the matrix returned **PASS=15 / FAIL=0 / BLOCKED=2**, exit 0 — matching
Phase 0. Evidence: `docs/setup/verify/m0-verify-setup-rerun.txt`.

It is worth noting *how* that result was reached, because it is the clearest justification for
Q-0 in this document: the first run **failed** on V8, which turned out to be a disabled security
control rather than a flaky check. The matrix paid for itself the first time it was re-run.

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

## 5. Product quality gates — RECONCILED 2026-10-02

This table was written when nothing was built and every row said "blocked by". It has been
reconciled against what is now measured. A gate is only listed as ENFORCED if a command fails
the build when it is violated.

| ID | Gate | Threshold | State | Evidence |
|---|---|---|---|---|
| Q-12 | Evaluation regression gate | Fail the build on **> 1 pp** regression vs the mean of the last 3 baselines | **ENFORCED** — `make eval-gate`, exit 1, drilled against a real 1.90 pp degradation. Also fails on invariant breaches (gold set mutated without a version bump, corpus changed, items vanished) | `app/evals/gate.py`, `docs/setup/verify/m4-eval-gate.txt` |
| Q-13 | Citation precision | ≥ 0.90 | **WITHDRAWN (U-1, §4.2)** — an answer-level metric with no answers. Replaced by retrieval-side citation coverage: recall@5 0.966, recall@10 1.000 | `evals/reports/20261001T204628Z/` |
| Q-14 | Faithfulness | ≥ 0.85 | **WITHDRAWN (U-1, §4.2)** — no generator, so the metric has no subject. Replaced by a structural guarantee: every returned character is a substring of a stored chunk, asserted per response | ADR-0008, `tests/test_api.py` |
| Q-15 | Context precision | ≥ 0.70 | **WITHDRAWN (U-1, §4.2)** — judge metric. Replaced by deterministic recall/MRR/nDCG over quote groups | `app/evals/scorers.py` |
| Q-16 | Canary resistance | Injected instruction not followed, every run | **NOT APPLICABLE BY DESIGN** — no model reads retrieved text, so there is nothing to inject into. The 3 canary documents stay in the corpus and the gold set, and this gate reactivates the day a generator lands | ADR-0008 |
| Q-17 | End-to-end latency | **p95 < 3 s** against the real service | **MEASURED, PASS** — 48.11 ms cold / 2.11 ms warm over HTTP, 1.6 % of budget. Closes the single-client half of U-14; a multi-client k6 profile is still absent | `evals/bench/20261002T054058Z/bench.json` |
| Q-18 | Gold set size and composition | ≥ 120 items, ≥ 10 % unanswerable, ≥ 1 injection canary | **MET** — 153 items, 14.4 % unanswerable, 3 canaries | `evals/gold/v1/metadata.json`, `make gold-lint` |

Three of these seven are withdrawn rather than met, and that is the honest outcome of U-1 rather
than a failure to build something. What a withdrawal costs is written beside it: in every case
the replacement is a *weaker but real* measurement, not a silent gap.

Thresholds are quoted identically in `docs/eval/EVAL_PROTOCOL.md` §6. Changing one is an ADR, never
a quiet edit, and never after seeing the result you want. **Withdrawing one is also never quiet:**
`tests/test_rescope.py` fails the build if a withdrawn metric reappears as a published number.

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
