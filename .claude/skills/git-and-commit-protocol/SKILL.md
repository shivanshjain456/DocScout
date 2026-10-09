---
name: git-and-commit-protocol
description: Use this skill for every git operation in DocScout - staging, committing, writing commit messages, branching, rebasing, merging, pushing, opening or reviewing pull requests, linking issues, tagging releases, and deciding whether a change needs an ADR first. Use it before any push, and whenever a decision has a plausible rejected alternative.
---

# Git and commit protocol

## Commits

- **Conventional commits**, imperative mood, scoped:
  `feat(retrieval): add HNSW index for chunks.embedding`
  `fix(ingest): handle scanned PDFs with zero extractable text`
  Types: `feat` `fix` `docs` `test` `refactor` `perf` `chore` `ci` `build`.
- **Atomic.** One logical change per commit. Code + its tests + its doc update belong together;
  two unrelated fixes do not.
- **Banned messages:** `wip`, `final`, `final2`, `fixes`, `update`, `asdf`, and any bulk
  multi-feature commit. If the message needs "and", split the commit.
- The body explains **why**, not what  -  the diff already says what.
- Never commit generated artifacts, `.env`, corpus files, model weights, or report directories
  (`.gitignore` covers these; do not `-f` past it).

## ADR trigger (hard rule)

**Any decision with a plausible rejected alternative gets an ADR *before* the code lands.**
Examples: embedding model choice, chunk size/strategy, hybrid fusion method, index type and
parameters, judge model, threshold values, SDK version pins, cloud provider.

ADR lives at `docs/decisions/NNNN-<slug>.md` using `docs/decisions/0000-template.md`, with sections
Context / Decision / Consequences / **Rejected alternatives**. The rejected-alternatives section is
mandatory and must name real options with real reasons  -  it is the portfolio's key AI-resistant
artifact. The ADR is referenced in the commit body (`Refs: ADR-0007`).

## Before every push

1. `make lint` `make typecheck` `make test`  -  all green.
2. `make secret-scan` (gitleaks)  -  must pass, on the **full history**, not just the diff.
3. `make verify-setup` still green.
4. Never `git push --force` to a shared branch. Use `--force-with-lease` on your own branch only,
   and never on `main`.

## Branches, issues, PRs

- Branch names: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`.
- Every non-trivial change links its issue (`Closes #12`).
- PRs state what changed, why, how it was verified (with artifact paths), and what was NOT done.
- Metric claims in a PR body require their report directory path (see `rag-eval-protocol`,
  `load-test-protocol`).

## Gotchas

- **A secret in history is a leaked secret**, even after a later commit removes it. If gitleaks
  fires on history: rotate the credential first, then rewrite history. Rotation is not optional
  and not deferrable.
- **`git add -A` is how `.env` files escape.** Stage deliberately; read `git status` before every
  commit.
- **Amending a pushed commit rewrites shared history.** Only amend what is still local.
- **Large files are permanent.** A committed model weight or corpus PDF bloats the repo forever;
  `check-added-large-files` is a guard, not a safety net.
- **Rebasing a branch someone reviewed invalidates the review comments.** Prefer merge commits once
  review has started.
- An ADR written *after* the code is a rationalization, not a decision record. Write it first.
