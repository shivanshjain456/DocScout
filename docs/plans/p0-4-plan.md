# P0-4 Plan — Runnable Production Deploy Artifact

- **Task:** P0-4 (master-todo §P0-4). Status in master TODO: `IN_PROGRESS`.
- **Baseline:** `32b4271`. Corpus 21 docs / 170 chunks. Triple-pin pgvector `0.8.6-pg18-trixie` guarded by `tests/test_config_coherence.py`.
- **Rule for this file:** WHAT + WHAT GOOD LOOKS LIKE. No implementation prescription beyond the constraints already fixed by the quality bar.

---

## Sub-task 1 — Container image that serves the API

- **Scope:** One `Dockerfile` at repo root that builds a runnable DocScout API image from a clean checkout.
- **Inputs it reads:** `pyproject.toml` (`requires-python >=3.12,<3.13`, `tool.uv.index pytorch-cpu`), `uv.lock` (169-lock), `app/api/app.py` (lifespan: pool, embedder warmup, BM25 scan, manifest digest), `app/config.py` (fail-closed `DATABASE_URL`/`DOCSCOUT_API_KEY`), `infra/initdb/`, `corpus/raw/manifest.json`.
- **Outputs it produces:** `Dockerfile`, `.dockerignore`.
- **Quality bar:** Reproducibility coherent with the measured pairing (pgvector pairing untouched; `uv sync --frozen` honored; pinned base digest; non-root runtime; `HEALTHCHECK` hitting the service; no secret in image layers or history; model cache handled explicitly via a volume/env rather than a silent download at boot).
- **Success criteria (falsifiable):** `docker build -t docscout:<sha> .` succeeds with no secret in the build context; image runs as non-root (`whoami` ≠ root); `HEALTHCHECK` present in image config.
- **Testing / assurance gates:** Static (Dockerfile lint-equivalent review: no `ADD` remote, no secret `ARG`/`ENV`, digest pinned); Security (no credential in `docker history`, `gitleaks` green); Supply-chain (`uv sync --frozen` inside build, no unpinned fetch).
- **Risks:** Base-image drift invalidates the measured pairing — mitigated by digest pin + coherence test. Model download at boot masks cold-start cost — mitigated by explicit cache volume.
- **Non-goals:** Helm/K8s/ECS/Terraform; multi-arch publishing; registry push.

## Sub-task 2 — One-command local service (db + api) with documented path

- **Scope:** Compose wiring so one documented command yields a locally running service answering `/healthz`, plus the runbook that states it.
- **Inputs it reads:** `docker-compose.yml` (current single `db` service), `.env.example`, `app/api/app.py::healthz`, `scripts/dev_db_native.sh` + `infra/initdb/` (source of truth for roles/extensions).
- **Outputs it produces:** Updated `docker-compose.yml` (adds a runnable `api` service bound to the same `db` + initdb contract), updated `docs/` runbook section + `README.md` Quickstart/Limitations deltas, `.env.example` deltas only if a new variable is required.
- **Quality bar:** From a clean checkout with only `.env` edited, the documented sequence succeeds where a daemon exists. The `db` service definition (image, mount, healthcheck) is unchanged in behavior; the new service reuses `DATABASE_URL` semantics (app role, not owner) and fails closed without a key.
- **Success criteria:** Reviewer runs the documented commands, then `curl -s localhost:8000/healthz` returns `status: ok` with `corpus_chunks: 170`. `docker compose ps` shows `db` healthy and `api` healthy.
- **Testing / assurance gates:** System (clean-checkout path exercised); API contract (`/healthz` shape `HealthResponse`); Configuration (three provisioning paths still agree — coherence test green); Installation (only `.env` edited).
- **Risks:** Compose drift from native/CI paths — mitigated by leaving `db` image + initdb mount identical. Port/env mismatch on reviewer machines — mitigated by documenting the exact ports and required `.env` keys.
- **Non-goals:** Production cloud topology; TLS termination; multi-worker scaling (remains `single_process: true`).

## Sub-task 3 — Entrypoint coherence (dead `app.main:app` address)

- **Scope:** One true entrypoint story across `Makefile`, docs, and code (rides with P0-4 per master-TODO dependency note).
- **Inputs it reads:** `Makefile:16-18` (`dev: uv run uvicorn app.main:app --reload`), `AGENTS.md:6` (`app.main:app`), `SPEC.md §2.2` pre-build `app/**` snapshot, `app/api/app.py:app` (runnable).
- **Outputs it produces:** Corrected `Makefile` + `AGENTS.md` (+ `SPEC.md` stale snapshot note if touched), plus either a re-export alias or no new module — exactly one story.
- **Quality bar:** One story, not both/none. No second dead path introduced. `make dev` and `make serve` agree on the served object.
- **Success criteria:** `make dev` starts the service from a clean checkout (or its compose-gated equivalent is documented as requiring a daemon); a test or `verify_setup` step asserts the referenced module object exists and exposes `app`.
- **Testing / assurance gates:** Installation (dev path from clean checkout); Static (`ruff`/`mypy` if a new alias module is added); Regression (new test fails before the fix, passes after).
- **Risks:** Fixing docs but leaving the target broken (or vice versa) — mitigated by the single-story acceptance test.
- **Non-goals:** New dev-only features; reload-policy changes.

## Sub-task 4 — Coherence and verification-matrix alignment

- **Scope:** Keep the build-failure guards truthful after the new artifact lands.
- **Inputs it reads:** `tests/test_config_coherence.py` (expects one pgvector image, compose==CI, no unused service), `scripts/verify_setup.sh` (V2 expects `0.8.2`, V3/V17 expect `redis`), `.github/workflows/ci.yml` (`eval-gate` image + `quality` job).
- **Outputs it produces:** Extended `tests/test_config_coherence.py` (covers the new image/service without weakening the triple-pin), corrected `scripts/verify_setup.sh` checks, no weakened assertion.
- **Quality bar:** No gate removed or loosened to make the task pass. The `0.8.6-pg18-trixie` invariant still fails the build on drift. Verify-matrix expectations match the shipped topology (extension version, service list).
- **Success criteria:** `pytest tests/test_config_coherence.py -q` green; `make verify-setup` matrix green or explicitly BLOCKED with a named external input (never silently broken). Stale `0.8.2`/`redis` expectations no longer assert.
- **Testing / assurance gates:** Static + Configuration + Installation (the three provisioning paths). Regression discipline: coherence test fails on a deliberately drifted tag.
- **Risks:** Over-fitting the test to the new file (e.g., asserting exact Dockerfile text) — mitigated by asserting properties (pin, non-root, healthcheck, frozen sync), not bytes.
- **Non-goals:** Rewriting the whole V1–V17 matrix; adding cloud checks.

## Sub-task 5 — Deploy/destroy as real local operations + decision record

- **Scope:** Replace the `exit 1` stubs with real, tested local operations and record the decision.
- **Inputs it reads:** `Makefile:104-115` stubs, `.claude/skills/deploy-protocol/SKILL.md`, `docs/deploys/` (currently `.gitkeep` only), ADR template `docs/decisions/0000-template.md`.
- **Outputs it produces:** Real `make deploy` / `make destroy` (local compose build+run / teardown, with preflight checks), `docs/decisions/0010-*.md` (rejected alternatives + evidence), `docs/deploys/<ts>.md` evidence pattern, updated `README.md` Limitations + Commands.
- **Quality bar:** If it is committed, it runs. `make deploy` and `make destroy` are both tested (not just deploy). No cloud resources outlive a dev session by default. ADR has a non-empty Rejected alternatives section with evidence.
- **Success criteria:** `make deploy` brings the service to `ok`/`170`; `make destroy` tears it down; both verified by a CI job or a committed verify log (`docs/setup/verify/` or `docs/deploys/`). `README.md` no longer describes deploy as a stub.
- **Testing / assurance gates:** System + Recovery (`destroy` leaves no container/volume unless documented); Documentation (ADR + runbook + CHANGELOG in the same series); Security (no secret echoed by either target).
- **Risks:** `deploy` that only works on the author's machine — mitigated by CI `deploy-smoke` or a clean-checkout verify log. Cloud-scope creep — mitigated by keeping both targets local-compose scoped.
- **Non-goals:** Cloud IAM, billing alarms, registry publishing (documented as future, not scaffolded).

## Sub-task 6 — Evidence and final verification for P0-4

- **Scope:** Prove the artifact, not just ship it.
- **Inputs it reads:** All outputs above, plus `app/api/models.py::HealthResponse`, `evals/bench/` + `scripts/bench_api.py` conventions for raw-output placement.
- **Outputs it produces:** Committed verify log (build + run + `curl /healthz` output showing `status: ok`, `corpus_chunks: 170`), updated `CHANGELOG.md`, master-TODO status `DONE → VERIFIED`.
- **Quality bar:** Every claimed number has its raw artifact. `make verify-setup` green/BLOCKED-named, `make test` green (DB-gated skips documented), `ruff` + `mypy` clean, `gitleaks` green, coherence green. `README.md` Limitations honestly reflects the new state (what is now deployable locally vs what remains undeployed).
- **Success criteria:** From the commit, a reviewer reproduces: `docker build .` → documented run → `curl /healthz | jq .` → `status: ok`, `corpus_chunks: 170`; CI `deploy-smoke` (or committed log where no daemon exists in CI) backs the claim.
- **Testing / assurance gates:** Full P0-4-applicable taxonomy: Unit (new test helpers), Integration (api+db over compose), System (clean checkout), API contract + error-body shape, Configuration, Installation, Regression. N/A marked with reason where inapplicable (e.g., Accessibility/Localization for a Dockerfile).
- **Risks:** Claiming a verify the host cannot run (no daemon) — mitigated by committing the log from the host that can, and marking CI accordingly.
- **Non-goals:** Performance/cost claims beyond `/healthz` liveness (bench stays retrieval-only until P0-1).
