## Description

Please provide a concise summary of the changes introduced in this pull request and the motivation behind them.

---

## Related Issue / Ticket

Fixes #(issue)
Relates to FEAT-XXX / Pillar X

---

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing behavior to change)
- [ ] Regulatory data or gold set update
- [ ] Architecture Decision Record (ADR) or documentation update
- [ ] Performance optimization or CI/CD enhancement

---

## Verification & Quality Gates Checklist

Please ensure all gates are satisfied before requesting review:

- [ ] **Lint and Format:** `uv run ruff check .` and `uv run ruff format --check .` pass with zero warnings.
- [ ] **Strict Typing:** `uv run mypy app tests` passes in strict mode with zero errors.
- [ ] **Test Suite:** `uv run pytest -q` passes without unhandled failures or regressions.
- [ ] **Diff Coverage:** 100% differential test coverage on newly added or modified lines in `app/` (`make diff-coverage`).
- [ ] **Mutation Score Ratcheting:** Test assertions are verified against AST mutations (`make test-mutation`).
- [ ] **Evaluation Gate:** Retrieval accuracy and regression gate pass against gold set v2.0.0 (`make eval-gate`).
- [ ] **Content Quality Gate:** `uv run python scripts/qa_content_gate.py` passes cleanly with zero violations.
- [ ] **Secret Scanning:** `make secret-scan` passes clean across repository history.
- [ ] **Documentation:** `README.md`, `SPEC.md`, `CHANGELOG.md`, and relevant ADRs updated if interfaces or behaviors changed.
