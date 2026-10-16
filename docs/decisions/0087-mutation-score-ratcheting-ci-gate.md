# ADR-0087: Mutation Score Ratcheting CI Gate

## Context
Code coverage alone is an insufficient quality metric: line and branch coverage record whether a line executed during testing, but not whether tests actually asserted or verified correct behavior. Tests without assertions or with weak checks can achieve high line coverage while allowing critical bugs and behavioural regressions to slip into production undetected.

Mutation testing introduces synthetic faults (mutants) into source code to verify that the test suite detects and kills them. However, running mutation testing over an entire monolithic repository on every pull request takes hours and exceeds continuous integration time budgets.

To prevent weak assertion-free tests and ensure test quality strictly improves over time, we require a fast, differential mutation score ratcheting gate that executes in under 90 seconds in CI and guarantees the mutation score never decreases ($\Delta \ge 0.000$) below the baseline of 78.4% across 278 mutants.

## Decision
1. Implement Diff Mutation Gate in `scripts/diff_mutation.py`:
   - Define `MutationGateConfig(min_score: float = 0.784, diff_only: bool = True, max_mutants_per_run: int = 50)` and `MutationReport` output schema.
   - Unified git diff parser `parse_diff_lines` extracting altered lines in Python source files under `app/`.
   - AST-based mutation generator `generate_mutations_for_file` targeting modified lines:
     - Binary operators (`+` <-> `-`, `*` <-> `/`).
     - Comparison operators (`==` <-> `!=`, `<` <-> `>=`, `<=` <-> `>`).
     - Boolean operators (`and` <-> `or`).
     - Boolean constants (`True` <-> `False`).
   - Scoped mutation test execution mapping modified source files to associated test suites running fast unit tests (`-m not slow`).
   - Ratchet score calculation:
     - Accumulates baseline mutants (278 mutants, 218 killed = 78.4%) with pull request diff mutants.
     - Enforces ratchet floor: fails gate if any surviving mutant exists in modified lines or if cumulative score drops below baseline floor.
2. Integration Points:
   - Added `test-mutation` target to `Makefile` (`uv run python scripts/diff_mutation.py`).
   - Added pull request quality step in `.github/workflows/ci.yml` (`uv run python scripts/diff_mutation.py --base origin/main`).
3. Committed Artifact:
   - Persists execution report to `docs/verification/mutation-report.json`.
4. Verification Suite in `tests/test_mutation_gate.py`:
   - 14 test cases including the evaluation dataset of 10 simulated PR scenarios (uncovered logic rejection, arithmetic/comparison/boolean mutant kills, documentation/non-python diff passes, boundary check mutant detection, ratchet regression rejection, and score improvement).

## Consequences
- **Positive:**
  - Prevents assertion-free tests and untested code paths in all pull requests.
  - Ratchet policy guarantees mutation adequacy score strictly never decreases ($\Delta \ge 0.000$).
  - Diff scoping limits execution overhead to $\le 5\text{ seconds}$ locally and $\le 90\text{ seconds}$ in CI runners.
  - Cross-platform support (Linux CI and Windows development) without WSL requirements.
- **Neutral:**
  - Pull requests modifying core algorithmic logic must include rigorous assertions to kill generated mutants.
