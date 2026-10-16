# ADR-0088: Differential / Patch Coverage Gating (100% Diff Coverage)

## Context
Traditional code coverage frameworks measure repository-wide statement or branch coverage percentages. This blunt whole-repository approach suffers from significant flaws in enterprise software development:
1. Coverage Gaming: Developers can add assertions to trivial utility functions to inflate whole-repo coverage while leaving newly committed, complex business logic completely untested.
2. Legacy Debt Tax: Demanding high whole-repo coverage discourages small, surgical bug fixes in older modules because fixing a one-line bug forces developers to write hundreds of tests for pre-existing legacy code.
3. Untested Regressions: Even when whole-repository coverage remains above 90%, new lines in a pull request can be 0% covered, introducing severe production bugs.

To eliminate coverage gaming and enforce uncompromising testing discipline on new code, we require a differential patch coverage gate that mandates 100% test coverage on every modified or newly added executable line in a pull request.

## Decision
1. Implement Differential Coverage Evaluator in `scripts/diff_coverage.py`:
   - Define `DiffCoverageConfig(required_percentage: float = 100.0)` and `DiffCoverageResult(lines_modified: int, lines_covered: int, diff_coverage_pct: float, uncovered_lines: list[int], passed: bool)`.
   - Unified git diff parser `parse_diff_lines` extracting altered lines in Python source files under `app/`.
   - Cobertura XML parser `parse_coverage_xml` extracting exact hit counts per line across target source files.
   - Diff coverage mapping:
     - Only executable source lines recorded in Cobertura XML are evaluated; comments, blank lines, and docstrings are excluded from the denominator.
     - Strictly checks that every modified executable line has `hits > 0`.
     - Fails gate if any executable line in the pull request diff has `hits == 0`.
2. Integration Points:
   - Makefile target `diff-coverage` (`uv run python scripts/diff_coverage.py`).
   - GitHub Actions CI workflow in `.github/workflows/ci.yml`:
     - Generates Cobertura coverage XML via `uv run pytest --cov=app --cov-report=xml:coverage.xml -q`.
     - Executes differential coverage gate step with inline GitHub PR error annotations for any uncovered lines (`::error file=...,line=...`).
3. Committed Artifact:
   - Output summary and details persisted to `docs/verification/diff-coverage-report.json`.
4. Verification Suite in `tests/test_diff_coverage.py`:
   - 23 unit and integration tests including the evaluation dataset of 20 simulated PR diff scenarios (single/multi-line modifications, covered/uncovered branches, exception handlers, comment/docstring exclusions, non-python diffs, multi-file PRs, legacy module diffs without whole-repo penalty, custom threshold validations, and deletions).

## Consequences
- **Positive:**
  - Guarantees 100% test execution for all new or modified code before merging.
  - Eliminates coverage gaming and stops untested edge cases from reaching production.
  - Decouples pull request quality from legacy repository technical debt.
  - Sub-second calculation overhead ($\le 0.1\text{ ms}$ processing, $\le 3\text{ seconds}$ CI total).
- **Neutral:**
  - Developers must ensure unit or integration tests exercise all newly introduced branches and statements.
