#!/usr/bin/env python
"""Summarise a mutmut run into a committed JSON artifact.

`mutmut results` prints only the survivors, which is why a naive count of its output reads
as a 0% score: there is nothing in it to divide by. The total comes from the generated
sandbox instead, where every mutant exists as a numbered function.

Why a mutation score at all, when the project already measures line coverage: coverage
records that a line executed, not that anything checked the result, so a test calling a
function without asserting on it still counts as covered. A mutation score cannot be
earned that way -- a mutant only dies if some assertion actually fails. Measured here:
`app/evals/scorers.py` sat at 99% line coverage and 83.7% mutation score, so 25 deliberate
behaviour changes slipped past a suite that executed essentially every line.

Run via `make mutation`, which invokes `mutmut run` first. This script only reads results;
it never runs the mutants, so it is safe to re-run.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = REPO_ROOT / "mutants" / "app" / "evals"
OUTPUT = REPO_ROOT / "evals" / "mutation" / "latest.json"

#: Modules under mutation. Kept in step with `[tool.mutmut] source_paths` in pyproject.
MODULES = ("scorers", "stats")

_ANSI = re.compile(r"\x1B\[[0-9;]*[mGKHF]")
_MUTANT_DEF = re.compile(r"^def (x_\w+__mutmut_\d+)\(", re.MULTILINE)
_SURVIVOR = re.compile(r"app\.evals\.(\w+)\.(x_\w+__mutmut_\d+):\s*survived")


def mutmut_results() -> str:
    """Raw `mutmut results`, with the spinner's escape codes stripped."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no user input
        ["mutmut", "results"],  # noqa: S607 - resolved from the active virtualenv
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "`mutmut results` failed. Run `make mutation` first; it generates the "
            f"sandbox this report reads.\n{completed.stderr.strip()}"
        )
    return _ANSI.sub("", completed.stdout).replace("\r", "\n")


def main() -> int:
    if not SANDBOX.is_dir():
        raise SystemExit(
            f"no mutmut sandbox at {SANDBOX.relative_to(REPO_ROOT)}. Run `make mutation`."
        )

    results = mutmut_results()
    survivors = _SURVIVOR.findall(results)

    modules: dict[str, dict[str, object]] = {}
    for module in MODULES:
        source = SANDBOX / f"{module}.py"
        if not source.is_file():
            raise SystemExit(f"{source} is missing; the sandbox is incomplete")
        generated = set(_MUTANT_DEF.findall(source.read_text()))
        survived = {name for mod, name in survivors if mod == module}
        unknown = survived - generated
        if unknown:
            raise SystemExit(
                f"{module}: results name mutants absent from the sandbox ({sorted(unknown)[:3]}). "
                "The sandbox and the results are out of step; re-run `make mutation`."
            )
        killed = len(generated) - len(survived)
        modules[module] = {
            "mutants": len(generated),
            "killed": killed,
            "survived": len(survived),
            "score_pct": round(100 * killed / len(generated), 1) if generated else 0.0,
            "survivors_by_function": dict(
                Counter(re.sub(r"__mutmut_\d+$", "", n) for n in sorted(survived))
            ),
        }

    total = sum(int(m["mutants"]) for m in modules.values())  # type: ignore[arg-type]
    killed_total = sum(int(m["killed"]) for m in modules.values())  # type: ignore[arg-type]

    payload = {
        "schema": "docscout.mutation/1",
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": "mutmut",
        "source_paths": [f"app/evals/{m}.py" for m in MODULES],
        "test_selection": ["tests/test_scorers.py"],
        "total": {
            "mutants": total,
            "killed": killed_total,
            "survived": total - killed_total,
            "score_pct": round(100 * killed_total / total, 1) if total else 0.0,
        },
        "modules": modules,
        "survivors": sorted(f"{mod}.{name}" for mod, name in survivors),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"  {'module':<9} {'mutants':>8} {'killed':>7} {'survived':>9} {'score':>7}")
    for module, row in modules.items():
        print(
            f"  {module:<9} {row['mutants']:>8} {row['killed']:>7} "
            f"{row['survived']:>9} {row['score_pct']:>6}%"
        )
    print(
        f"  {'TOTAL':<9} {total:>8} {killed_total:>7} {total - killed_total:>9} "
        f"{payload['total']['score_pct']:>6}%"
    )
    print(f"\n  raw: {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
