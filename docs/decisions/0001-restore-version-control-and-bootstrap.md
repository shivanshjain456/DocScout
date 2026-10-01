# ADR-0001: Re-initialise version control and make the environment reproducible

- **Status:** accepted
- **Date:** 2026-10-01
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Related:** `SPEC.md` §2.3 and U-15 · `docs/MILESTONES.md` M0 · `docs/QUALITY_BAR.md` Q-1, Q-3 · SETUP_REPORT K-14

## Context

Phase 0 finished on 2026-10-01 with a verified environment and two commits (`695e0f4` → `c88f59b`),
a clean `gitleaks` scan over the full history, and `make verify-setup` at PASS=15 / FAIL=0 /
BLOCKED=2.

Work resumed in a fresh sandbox. The tracked working tree was intact — every source file, the
20-document corpus sample, and all of `docs/setup/verify/` survived. Everything else did not:

| Lost | Observed |
|---|---|
| `.git/` | `git rev-parse` → *fatal: not a git repository*; the Phase 0 history is unrecoverable |
| Toolchain | `uv`, `docker`, `psql`, `k6`, `gitleaks`, `pre-commit`, `gh`, `aws`, `pnpm` all absent from PATH |
| `.venv/` (1.8 GB), Hugging Face cache, `node_modules/` | absent |
| Empty directories | `evals/`, `evals/reports/`, `tests/eval/`, `docs/deploys/` absent — consistent with K-14 |

This is consistent with the platform's snapshot rules: virtualenvs, caches, build output, and
credential paths such as `.git/config` are excluded from persistence.

The forces in play:

1. **Unversioned work is one `rm` from gone.** The seven specification documents and all Phase 0
   evidence were sitting in a tree with no version control.
2. **The repository documented an environment nobody could re-create.** Every VERIFIED claim
   pointed at an evidence file, but no path existed from a clean machine back to a state where
   those claims could be re-checked. A verification matrix that cannot be re-run decays into
   folklore.
3. **`docs/QUALITY_BAR.md` Q-1 forbids `--no-verify`.** Committing therefore required a working
   `uv`, `mypy`, `ruff`, `gitleaks` and `pre-commit` — i.e. the environment had to be rebuilt
   before the first commit could legitimately exist.

## Decision

We will do three things, in this order.

**1. Add `scripts/bootstrap.sh`** — an idempotent, version-pinned, tiered installer that
reconstructs the Phase 0 toolchain on Debian 13:

- Pins read from `docs/setup/SETUP_REPORT.md`: uv 0.12.21, CPython 3.12.14, pre-commit 4.6.2,
  gitleaks 8.30.1, Node 22.23.3, pnpm 12.8.1, k6 2.3.0, Compose 5.5.1, aws-cli 2.37.7.
- Two tiers: `core` installs exactly what is needed to commit with all 11 pre-commit hooks green;
  `full` adds Docker, Compose, Node/pnpm, k6 and the AWS CLI, i.e. everything `make verify-setup`
  exercises.
- A `--check` mode that installs nothing, prints a status table, and exits non-zero if anything
  required is missing.
- It fixes, permanently, the `fnm --skip-shell` defect that left non-login shells on a stale Node
  by writing a marked block into `~/.bashrc`.

**2. Re-initialise version control** with `git init -b master`, matching the Phase 0 branch name.
We will **not** attempt to reconstruct the lost history. The new repository begins with three
atomic commits that describe what each body of work actually is:

| # | Commit | Contents |
|---|---|---|
| 1 | `chore(repo): restore the Phase 0 tree under version control` | Everything Phase 0 produced |
| 2 | `build(tooling): add a pinned, idempotent environment bootstrap` | `scripts/bootstrap.sh`, this ADR, `.gitkeep` placeholders |
| 3 | `docs: add the seven durable project documents` | SPEC, SECURITY, QUALITY_BAR, MILESTONES, ARCHITECTURE, CORPUS_SPEC, EVAL_PROTOCOL + robots evidence |

Every commit passes through the full 11-hook chain. No `--no-verify`, at any point.

**3. Add `.gitkeep` files** to `tests/eval/` and `docs/deploys/` — the two empty directories that
existing `Makefile` targets reference by path (K-14). `evals/reports/` is deliberately *not*
tracked: it is gitignored generated output and the harness will `mkdir -p` it.

Commit authorship is recorded as a repository-local identity (`DocScout Agent
<agent@docscout.local>`) rather than a human's, because a human did not write these commits.

## Consequences

**Easier.** A clean Debian 13 machine reaches a committable state with one command. The
`--check` mode gives a truthful environment report in under a second. `uv sync --frozen` is now
exercised on every bootstrap, so lockfile rot surfaces immediately rather than at the next CI run
that never happens (U-6).

**Harder / accepted costs.** The Phase 0 commit SHAs are gone, so `docs/setup/SETUP_REPORT.md` and
`CHANGELOG.md` reference commit identifiers that no longer resolve. We keep those references and
annotate them rather than rewriting history we cannot verify. `bootstrap.sh` is now a maintenance
surface: a pin drifts whenever upstream removes a release artefact, and the script will fail loudly
rather than silently install something else. That is the intended trade.

**To monitor.** The pinned-version block in `bootstrap.sh` must stay in sync with SETUP_REPORT; the
two are currently consistent by hand, not by test. A future `verify_setup.sh` assertion should
compare them.

**Measured effect of this decision.** `bash scripts/bootstrap.sh core` completed in ~14 s and
reproduced the environment exactly: `uv.lock` SHA-256 `600c9001…1b98d` unchanged, 164 packages
installed on linux-x86_64 from 169 locked entries, and all four CI `quality` gates green
(`ruff check`, `ruff format --check`, `mypy app` strict, `pytest`).

## Rejected alternatives

### A. Reconstruct the Phase 0 history

- **What it is.** Recreate `695e0f4` and `c88f59b` as new commits with back-dated timestamps and
  the original messages, so the log looks continuous.
- **The honest case for it.** History continuity is genuinely useful: `CHANGELOG.md` and
  SETUP_REPORT already cite those SHAs, and a log starting at "restore everything" loses the
  narrative of how Phase 0 was built.
- **Why rejected.** The content of those commits cannot be reproduced — the intermediate tree state
  no longer exists — so any reconstruction would be a plausible fiction with fabricated SHAs and
  false dates. The project's first operating rule is *evidence or it didn't happen*; manufacturing
  provenance to make a log look tidy is precisely the failure mode the rule exists to prevent.
- **What would change our mind.** Nothing short of recovering the actual `.git` directory.

### B. Commit with `--no-verify` and skip the toolchain rebuild

- **What it is.** `git init && git add -A && git commit --no-verify`. Thirty seconds, no installs.
- **The honest case for it.** The immediate risk was data loss, and the files had already passed
  the hooks once in Phase 0. Speed has real value when work is unprotected.
- **Why rejected.** Three reasons, in increasing order of seriousness. (1) It directly violates
  Q-1. (2) The files had *not* all passed the hooks — the seven new specification documents and
  `bootstrap.sh` had never been linted by anything. (3) Most importantly, it would have concealed
  the actual finding. Rebuilding the environment is what proved `uv.lock` still reproduces and the
  gates still pass; `--no-verify` would have produced a repository that merely *claimed* a verified
  environment, which is the exact condition this ADR exists to end.
- **What would change our mind.** An emergency where the tree is actively being destroyed. Even
  then, the follow-up commit would have to re-run the hooks.

### C. Vendor the toolchain into the repository

- **What it is.** Commit the `uv`, `gitleaks` and `k6` binaries so the tools travel with the code.
- **The honest case for it.** It is the only approach immune to a missing network, and it makes
  provenance exact — the bytes that were verified are the bytes that ship.
- **Why rejected.** `check-added-large-files` caps additions at 5 MB and these binaries exceed it
  several times over; git stores every future version forever; and it hard-codes linux-x86_64 into
  a repository that should build elsewhere. Redistributing third-party binaries also raises
  licensing questions nobody has answered.
- **What would change our mind.** An air-gapped deployment requirement. The answer then is a
  pre-built image, not committed binaries.

### D. A Dockerfile or devcontainer instead of a shell script

- **What it is.** Express the environment as a container image; developers attach to it.
- **The honest case for it.** Strictly better reproducibility than a shell script — pinned base
  image, layer caching, no reliance on the host distribution. This is the conventional answer and
  it is a good one.
- **Why rejected, for now.** Docker is itself one of the things that disappeared. The core tier has
  to work on a host with no container runtime, because installing the container runtime is part of
  the problem being solved. A bootstrap script that works before Docker exists is a prerequisite
  for, not a competitor to, a container image.
- **What would change our mind.** Once `bootstrap.sh full` is proven on a clean machine, a
  Dockerfile that simply runs it becomes nearly free, and should be written at M6 when a deploy
  image is needed anyway.

### E. One squashed commit containing everything

- **What it is.** A single "initial commit".
- **The honest case for it.** It is accurate in a narrow sense: all of it did arrive in the tree at
  the same moment.
- **Why rejected.** Three genuinely different kinds of change are present — restored prior output,
  new tooling, new specification. The commit protocol bans bulk multi-feature commits precisely so
  that `git log` stays a usable explanation. A reader six months out should be able to see that the
  specification set was authored separately from the tooling that made it committable.
- **What would change our mind.** Nothing; the three-commit split costs almost nothing.
