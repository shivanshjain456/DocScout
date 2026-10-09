---
name: define-done
description: Use this skill before claiming any DocScout task, ticket, feature, bug fix, or refactor is done, finished, complete, or ready for review, and when asked "is this done", "can we close this", "what is left", or "ship it". Use it as the final gate at the end of every unit of work, and when deciding whether a change is safe to hand back to the human.
---

# Define done

"Done" is a checklist, not a feeling. Work the list top to bottom and state the result of each item.
If an item cannot be satisfied, say so explicitly  -  an honest "done except X" is acceptable; a
silent omission is not.

## The checklist

1. **Tests**
   - New behavior has tests written **before** the implementation (skill `test-driven-development`).
   - Every bug fix ships a regression test that **failed before the fix**  -  demonstrate it did.
   - No untested public function. `uv run pytest -q` is green.
2. **Types**  -  `uv run mypy app` clean. No new `# type: ignore` without a comment explaining why.
3. **Lint/format**  -  `uv run ruff check .` and `uv run ruff format --check .` clean.
4. **Docs**  -  docstrings on public functions; README/AGENTS.md updated if commands or behavior
   changed; `.env.example` updated if a new config key exists.
5. **Architecture diagram**  -  `docs/architecture/system-diagram.md` updated if boundaries,
   components, or data flow changed.
6. **ADR**  -  written and committed if the change involved a decision with a rejected alternative
   (skill `git-and-commit-protocol`).
7. **Artifacts for every claim**  -  any metric, latency, or cost number stated anywhere has its raw
   report directory committed and referenced (skills `rag-eval-protocol`, `load-test-protocol`).
8. **`make verify-setup` green**  -  the environment still works; nothing was broken in passing.
9. **Security**  -  no secret added to code/docs/history; corpus text still treated as data; new
   external input is delimited; `make secret-scan` passes.
10. **Clean state**  -  no stray debug prints, commented-out code, TODOs without an issue number, or
    leftover scratch files. No cloud resource left running.

## How to report completion

State, briefly and concretely: what changed, the command outputs that prove it works (paths, not
prose), what is explicitly **not** covered, and any known issue created along the way. Do not say
"everything works"  -  say which command returned what.

## Gotchas

- **"It runs" is not "it works."** A green import proves nothing about behavior.
- **Tests passing locally on a warm environment** can hide a missing dependency; `uv sync --frozen`
  in a clean venv is the real check.
- **A skipped test is a failing test wearing a disguise.** Count skips and justify each.
- **Verification before completion** (the Superpowers skill of that name) applies: re-run the check
  after the last edit, not before it. The most common failure is claiming done from a stale run.
- **Partial done is fine; unmarked partial done is a lie.** Write the gap into Known issues.
