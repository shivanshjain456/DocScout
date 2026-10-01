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
- Verification evidence for the rebuild: `docs/setup/verify/m0-bootstrap-and-vcs.txt` and
  `docs/setup/verify/m0-verify-setup-rerun.txt`. The V1–V17 matrix was re-run for the first time
  since Phase 0 and reproduced **PASS=15 / FAIL=0 / BLOCKED=2** on a toolchain rebuilt entirely by
  `scripts/bootstrap.sh full`, with every version matching its Phase 0 pin.
- Primary-source `robots.txt` evidence for both corpus sources
  (`docs/setup/verify/robots-txt-evidence.txt`), partially closing Known issue K-16.
- Phase 0 environment: Docker Compose data layer (Postgres 18 + pgvector 0.8.2, Redis 7),
  uv-managed Python 3.12 environment, Node 22 / pnpm, k6, gitleaks, AWS CLI.
- Agent configuration: `AGENTS.md`, `CLAUDE.md`, six project skills, vendored Superpowers v6.4.2.
- Enforcement: pre-commit (ruff, mypy, gitleaks, large-file and private-key checks), Claude Code
  hooks (format-after-edit, dangerous-bash denylist, end-of-session typegate), CI skeleton.
- Security documentation: MCP server audit, skills audit, injection canary log, memory write log.
- Setup tooling: `scripts/mcp_probe.py`, `scripts/verify_corpus_fetch.py`, `scripts/verify_setup.sh`.

### Decided
- **ADR-0002 pins the embedding model and vector dimension: `BAAI/bge-small-en-v1.5`, `D = 384`.**
  Closes U-9 and unblocks the schema. The decision rests on a five-arm bake-off over the real
  RBI/SEBI corpus (149 chunks, 21 documents) with a BM25 lexical control, two independent probe
  sets, a harness sanity control, and paired significance testing. Evidence:
  `docs/decisions/evidence/u9-embedding-bakeoff.json`, harness
  `scripts/experiments/u9_embedding_bakeoff.py`.
  - No candidate was significantly better than another (all McNemar p >= 0.42; every 95% CI
    straddles zero), so the choice is made on structural and cost grounds and says so.
  - `all-MiniLM-L6-v2` is rejected on evidence rather than leaderboard reputation: its 256-token
    window truncates **72 of 149 chunks**. It still scored 1.0 on the easy document-level probe,
    which is exactly how such a defect survives a casual benchmark.
  - BM25 alone matched or beat every neural embedder, which makes the hybrid retriever an
    evidence-backed requirement rather than an assumption.
- **ADR-0003 pins the chunking strategy: fixed-width 1,000 characters with 150-character (15%)
  overlap, over offset-preserved cleaned text.** Closes U-8 and, with U-9, completes every
  decision gating the database schema. Chosen from a 14-configuration sweep scored with
  character-span gold fixed before any chunker runs, plus paired McNemar and 10,000-sample
  bootstrap tests on identical probes. Evidence:
  `docs/decisions/evidence/u8-chunking-sweep.json` and `u8-chunking-focus.json`, harness
  `scripts/experiments/u8_chunking_sweep.py`.
  - Overlap is the cheapest quality in the sweep: it raises span integrity from 0.855 to 0.965
    (p = 0.0001) for 21 extra chunks and no loss of citation tightness.
  - 1,200-character chunks scored the best recall (+0.070, p = 0.0125) and were still rejected:
    they produced 524-token chunks against ADR-0002's 512-token ceiling, and silent encoder
    truncation would leave `char_end` claiming coverage of text the embedding never saw.
  - Clause-aware chunking was built and tested rather than assumed. It gives the tightest
    citations of any 1,000-char configuration but loses span integrity (p = 0.0433), because
    pypdf preserved no layout: every real document extracts to zero newlines.
  - Cleaning turns out not to improve retrieval at all; it earns its place purely by buying token
    headroom (447 vs 484 peak tokens), which is what keeps 1,000 characters inside the ceiling.
- **Offset-preserving cleaning is now a normative ingest requirement** (`ARCHITECTURE.md` §3):
  noise is blanked with equal-length spaces, never deleted, so `char_start`/`char_end` stay valid
  against the original extracted text as FR-7 requires.

### Fixed
- **Corrected a ~16x error in the embedding-throughput extrapolation.** `CORPUS_SPEC.md` C-5 read
  112.4 *sentences*/s as "~10,000 chunks is ~90 s". Measured on real 1,000-char regulatory chunks
  the rate is 6.9 chunks/s, so 10k chunks is ~24 minutes. The Phase 0 measurement was sound; only
  the extrapolation to chunks was not. `SETUP_REPORT.md` keeps its signed wording with a pointer
  to the correction.
- **Restored the executable bit on all 16 shebang scripts.** A workspace snapshot stripped it and
  the loss was committed unnoticed, because file modes are invisible in a diff. One of the affected
  files is `.claude/hooks/dangerous-bash.sh`, the agent command denylist — a security control that
  was present, correct and **not running**. Found by V8 on the first re-run of the verification
  matrix. Guarded by a new `check-shebang-scripts-are-executable` pre-commit hook.
- `scripts/bootstrap.sh` full tier: added `jq`, `postgresql-client` and `gh`, which V1 of the
  verification matrix requires and the script did not install.
- `.gitignore`: `loadtests/reports/verify/` is now tracked. V15 asserts that report exists, so the
  matrix depended on an artifact git would not keep. Ad-hoc `make load` runs remain ignored.
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
