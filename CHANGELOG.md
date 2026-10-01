# Changelog

All notable changes to DocScout are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Project documentation set, each document readable alone and cross-referenced into one source of
  truth: `SPEC.md`, `SECURITY.md`, `docs/QUALITY_BAR.md`, `docs/MILESTONES.md`,
  `docs/architecture/ARCHITECTURE.md`, `docs/corpus/CORPUS_SPEC.md`, `docs/eval/EVAL_PROTOCOL.md`.
  Includes a shared status vocabulary (VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED) and
  a global Unresolved Register, U-1 … U-17.
- `scripts/bootstrap.sh`: pinned, idempotent, tiered (`core` / `full`) reconstruction of the
  Phase 0 toolchain, with a `--check` mode that installs nothing and exits non-zero on a gap.
- `ADR-0001`: re-initialise version control without fabricating the lost Phase 0 history, and make
  the environment reproducible by script.
- Primary-source `robots.txt` evidence for both corpus sources
  (`docs/setup/verify/robots-txt-evidence.txt`), partially closing Known issue K-16.
- Phase 0 environment: Docker Compose data layer (Postgres 18 + pgvector 0.8.2, Redis 7),
  uv-managed Python 3.12 environment, Node 22 / pnpm, k6, gitleaks, AWS CLI.
- Agent configuration: `AGENTS.md`, `CLAUDE.md`, six project skills, vendored Superpowers v6.4.2.
- Enforcement: pre-commit (ruff, mypy, gitleaks, large-file and private-key checks), Claude Code
  hooks (format-after-edit, dangerous-bash denylist, end-of-session typegate), CI skeleton.
- Security documentation: MCP server audit, skills audit, injection canary log, memory write log.
- Setup tooling: `scripts/mcp_probe.py`, `scripts/verify_corpus_fetch.py`, `scripts/verify_setup.sh`.

### Fixed
- `.gitignore`: anchored `corpus/` to `/corpus/`. Unanchored, it matched any directory named
  `corpus` at any depth and silently excluded `docs/corpus/` — the new `CORPUS_SPEC.md` would not
  have been committed, with no error reported.
- `.gitignore`: `corpus/raw/manifest.json` is now tracked, implementing what
  `docs/corpus-provenance.md` already stated. The manifest is the provenance anchor that makes the
  fetched bytes re-derivable; it was being ignored along with them.
- Added `.gitkeep` to `tests/eval/` and `docs/deploys/`, the two empty directories existing
  `Makefile` targets reference by path (Known issue K-14).

### Security
- Rejected the Postgres MCP server named in the original brief: the PyPI package
  `mcp-server-postgres` is an unvetted third-party upload, and the brief's invocation would have
  passed the live database superuser password to it as a command-line argument.
- `.gitignore` is treated as a security control and is now verified per path with
  `git check-ignore -v` rather than by reading the patterns.
- `gitleaks` clean over the full re-initialised history (3 commits, 1.03 MB, no leaks).

### Notes
- No feature code. No metrics published. No cloud resources created.
- The Phase 0 git history (`695e0f4` → `c88f59b`) was lost with the sandbox snapshot and was
  deliberately **not** reconstructed; see ADR-0001.
