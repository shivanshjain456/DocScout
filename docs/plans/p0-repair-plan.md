# P0-REPAIR — Evidence & Gate Coherence Implementation Plan

> **Task ID:** P0-REPAIR
> **Status:** IN_PROGRESS
> **Target Baseline:** `69021ef2a6cee2041e9f39690162fc9b5de9c0b6`
> **Objective:** Restore complete evidence graph coherence so all 5 remote CI jobs (`quality`, `secrets`, `supply-chain`, `eval-gate`, `deploy-smoke`) turn GREEN at HEAD, eliminate cross-platform CRLF/LF digest discrepancies, normalize baseline paths to POSIX, and align deploy-smoke with the `/healthz` vs `/readyz` operational contract.

---

## 1. Problem Diagnosis & Evidence Baseline

At pinned commit `69021ef`, GitHub Actions run `37933392448` failed across 3 jobs:
1. **`quality` job:** Fails in `uv run pytest -q` at `tests/test_goldset.py::test_metadata_matches_the_committed_file`.
   - *Root cause:* On Linux CI, git checks out `evals/gold/v1/gold.jsonl` with LF line endings, yielding SHA-256 `1a640cce7d27bf2de3a1390e858cd7537cfd8e25fe03bea1260d12f8c4e9a3b5`. But `metadata.json` committed on Windows recorded the CRLF digest `ea148e329453e820b036f972f0f688c2d36c0b54b69fac092478d8d075d07582`.
2. **`eval-gate` job:** Fails in `uv run python -m app.evals.gate` with two invariant failures:
   - `[FAIL] gold set 2.0.0 changed content without a version bump; baselines are not comparable` (`1a640cce...` vs baseline `ea148e32...`).
   - `[FAIL] corpus manifest changed since the last baseline; retrieval metrics measured over different corpora are not comparable` (`78f8f08b...` vs baseline `7fad4b6e...`).
   - Baseline `evals/baselines/20261009T063630Z.json` also has Windows backslashes in `report_dir`: `"evals\\reports\\20261009T063624Z"`.
3. **`deploy-smoke` job:** Fails at `start api and prove /healthz serves the full corpus`:
   - `curl -s http://localhost:8000/healthz | python -c "assert h['corpus_chunks']==170"` fails with `KeyError: 'corpus_chunks'`.
   - *Root cause:* P0-5 (commit `8de129a`) properly split `/healthz` (pure process liveness, 0 DB I/O, does not query chunk count) from `/readyz` (traffic readiness, reports `corpus_chunks`). CI script was not updated to query `/readyz` and retained a stale `170` chunk assertion (current corpus is 230 chunks).

---

## 2. Sub-tasks Breakdown

### Sub-task P0-REPAIR-1: Cross-Platform Line-Ending & Digest Normalization
- **Scope:** Enforce deterministic LF line-endings across all text files repository-wide via `.gitattributes`, re-normalize git working tree, and ensure canonical LF digests for `gold.jsonl` and `manifest.json` match `metadata.json`.
- **Inputs:** `evals/gold/v1/gold.jsonl`, `corpus/raw/manifest.json`, `evals/gold/v1/metadata.json`, `app/config.py`.
- **Outputs:**
  - `.gitattributes` at repository root defining `* text=auto eol=lf`, `*.json text eol=lf`, `*.jsonl text eol=lf`, `*.py text eol=lf`, `*.md text eol=lf`, `*.txt text eol=lf`, `*.sql text eol=lf`, `*.yml text eol=lf`, `*.yaml text eol=lf`, `*.sh text eol=lf`.
  - `evals/gold/v1/metadata.json` updated with canonical LF digests:
    - `sha256_of_gold_jsonl`: `1a640cce7d27bf2de3a1390e858cd7537cfd8e25fe03bea1260d12f8c4e9a3b5`
    - `corpus_manifest_digest`: `78f8f08b243c7d9fddbe0fab939a1d51159480de6d29caa175d1abcefdf548e3`
  - Canonical line-ending handling in `app/config.py:sha256_file` or canonical reader to guarantee hash stability across environments.
- **Quality bar:** Invariant checked, not assumed. Digests derived from the committed files must match on Linux, Windows, and macOS without manual patching.
- **Success criteria:**
  - `python -c "import hashlib,json,pathlib; assert hashlib.sha256(pathlib.Path('evals/gold/v1/gold.jsonl').read_bytes()).hexdigest()==json.load(open('evals/gold/v1/metadata.json'))['sha256_of_gold_jsonl']"` passes.
  - `python -c "import hashlib,json,pathlib; assert hashlib.sha256(pathlib.Path('corpus/raw/manifest.json').read_bytes()).hexdigest()==json.load(open('evals/gold/v1/metadata.json'))['corpus_manifest_digest']"` passes.
  - `pytest tests/test_goldset.py::test_metadata_matches_the_committed_file` passes.

---

### Sub-task P0-REPAIR-2: Baseline Digest & Path Coherence
- **Scope:** Update baseline records in `evals/baselines/` and report provenance in `evals/reports/` to reflect canonical LF digests and POSIX paths. Ensure `gate.py` produces zero invariant failures when evaluating `hybrid-rrf` at k=5 against baselines.
- **Inputs:** `evals/baselines/20261009T063630Z.json`, `evals/reports/20261009T063624Z/results.json`, `app/evals/gate.py`.
- **Outputs:**
  - `evals/baselines/20261009T063630Z.json`:
    - `goldset_sha256`: `1a640cce7d27bf2de3a1390e858cd7537cfd8e25fe03bea1260d12f8c4e9a3b5`
    - `corpus_manifest_digest`: `78f8f08b243c7d9fddbe0fab939a1d51159480de6d29caa175d1abcefdf548e3`
    - `report_dir`: `evals/reports/20261009T063624Z` (POSIX path with forward slashes)
  - `evals/reports/20261009T063624Z/results.json`: provenance digests updated to match canonical LF digests.
  - `evals/reports/20261009T111050Z/results.json`: provenance digests checked and verified coherent.
  - `app/evals/gate.py`: ensure baseline serialization uses POSIX formatting (`as_posix()`) so future baselines generated on Windows do not introduce backslashes.
- **Quality bar:** No backslashes in any JSON artifact under `evals/baselines/`. `app.evals.gate` invariant checks pass without warning or failure.
- **Success criteria:**
  - `python -m app.evals.gate` executes without invariant failures.
  - Regression gate passes with `minimum_detectable_effect_pp <= 1.0`.

---

### Sub-task P0-REPAIR-3: CI deploy-smoke & API Probe Alignment
- **Scope:** Correct `.github/workflows/ci.yml` `deploy-smoke` to test `/healthz` (liveness: `status=="ok"`) and `/readyz` (readiness: `status in ("ok", "degraded")`, `corpus_chunks==230`), eliminating `KeyError` and updating 170-era assertions.
- **Inputs:** `.github/workflows/ci.yml`, `app/api/app.py`, `app/api/models.py`.
- **Outputs:**
  - `.github/workflows/ci.yml`:
    - Test `/healthz` for liveness: verify `{"status": "ok", "model_loaded": true, "single_process": true}`.
    - Test `/readyz` for readiness: verify `{"status": "ok", "database": true, "corpus_chunks": 230}`.
    - Dynamically verify that `corpus_chunks` matches expected count from database and manifest.
- **Quality bar:** Respects the architectural split from ADR-0014 (liveness probe has 0 DB I/O; readiness probe verifies traffic capability).
- **Success criteria:**
  - `grep -n "170" .github/workflows/ci.yml` contains zero stale chunk assertions.
  - Smoke curl assertions succeed against local or containerized instance.

---

### Sub-task P0-REPAIR-4: 170-Era Hardcoded Test & Doc Assumption Sweep
- **Scope:** Audit tests and documentation for any remaining hard-coded 170-era assumptions that could mask defects or create confusion.
- **Inputs:** `tests/test_api_answer.py:72`, `tests/test_gate.py`, `docs/plans/p0-4-plan.md`, `README.md`.
- **Outputs:**
  - Update `tests/test_api_answer.py` line 72 provenance stub to clearly label 170 as historical fixture or update to 230.
  - Audit `tests/test_gate.py` mock fixtures.
- **Quality bar:** All tests pass, linting and typechecking clean.
- **Success criteria:**
  - `uv run ruff check .` clean.
  - `uv run ruff format --check .` clean.
  - `uv run mypy app tests` clean.
  - `uv run pytest -q` passes without errors.

---

### Sub-task P0-REPAIR-5: Commit, Remote Push, and CI Verification
- **Scope:** Atomic commit under `fix(P0-REPAIR):`, verification before push, non-fast-forward check, push to `origin/master`, and live verification of all 5 CI jobs turning GREEN on GitHub Actions.
- **Inputs:** All outputs from Sub-tasks 1–4.
- **Outputs:**
  - Atomic git commit.
  - Pushed to `origin/master`.
  - GitHub Actions run verified GREEN: `quality` (PASS), `secrets` (PASS), `supply-chain` (PASS), `eval-gate` (PASS), `deploy-smoke` (PASS).
  - Update `docs/plans/master-todo.md`: mark P0-REPAIR as `VERIFIED (<run-id>)`, mark P1-GUARD as `DONE/VERIFIED`.
- **Quality bar:** Never force-push. CI run on GitHub Actions is 100% green across all 5 jobs.
- **Success criteria:**
  - `gh run list --limit 1` shows `completed success`.
  - `git rev-parse HEAD == origin/master`.

---

## 3. Risks & Non-Goals

- **Non-Goals:**
  - Do NOT modify any retrieval logic, indexing logic, or gold set questions/answers.
  - Do NOT batch P2 work into this task.
  - Do NOT weaken the 1pp gate threshold or noise floor calculation.
  - Do NOT force-push to `origin/master`.
- **Risks & Mitigation:**
  - *Risk:* Git on Windows might convert LF to CRLF again during commit.
  - *Mitigation:* Pin `.gitattributes` with `* text=auto eol=lf` and explicit extension rules, run `git add --renormalize .`, and verify `git ls-files --eol` shows `i/lf w/lf` before committing.
