#!/usr/bin/env python
"""FEAT-096: Mutation Score Ratcheting CI Gate.

Gating check enforcing that no pull request can lower DocScout's mutation testing score
(baseline 78.4% across 278 mutants). Evaluates mutation adequacy on modified code diffs
to prevent weak assertion-free tests from slipping into production.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "evals" / "mutation" / "latest.json"
DEFAULT_REPORT = REPO_ROOT / "docs" / "verification" / "mutation-report.json"


@dataclass
class MutationGateConfig:
    """Configuration for mutation score ratcheting CI gate."""

    min_score: float = 0.784
    diff_only: bool = True
    baseline_path: Path = DEFAULT_BASELINE
    report_path: Path = DEFAULT_REPORT
    target_branch: str = "main"
    timeout_per_mutant: float = 15.0
    max_mutants_per_run: int = 50


@dataclass
class MutationReport:
    """Outcome report for mutation testing gate."""

    mutants_generated: int
    mutants_killed: int
    mutants_survived: int
    mutation_score: float
    gate_passed: bool
    baseline_score: float = 0.784
    baseline_mutants: int = 278
    cumulative_score: float = 0.784
    survivors: list[dict[str, Any]] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_diff_lines(diff_text: str) -> dict[str, set[int]]:
    """Parse unified git diff output into a mapping of filename -> set of modified line numbers."""
    modified_lines: dict[str, set[int]] = {}
    current_file: str | None = None
    current_line = 0

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current_file = None
        elif line.startswith("+++ b/"):
            raw_path = line[6:].strip()
            if raw_path != "/dev/null":
                current_file = raw_path
                if current_file not in modified_lines:
                    modified_lines[current_file] = set()
        elif line.startswith("@@ ") and current_file:
            match = re.search(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                current_line = int(match.group(1))
        elif current_file and not line.startswith("--- "):
            if line.startswith("+"):
                modified_lines[current_file].add(current_line)
                current_line += 1
            elif not line.startswith("-"):
                current_line += 1

    return {k: v for k, v in modified_lines.items() if v}


def get_git_diff(base_branch: str = "main") -> str:
    """Fetch git diff against base branch, upstream remote, or HEAD~1 fallback."""
    gh_base = os.environ.get("GITHUB_BASE_REF")
    candidates = []
    if gh_base:
        candidates.append(["git", "diff", f"origin/{gh_base}...HEAD"])
    candidates.extend(
        [
            ["git", "diff", "HEAD"],
            ["git", "diff", "HEAD~1...HEAD"],
            ["git", "diff", f"origin/{base_branch}...HEAD"],
            ["git", "diff", f"{base_branch}...HEAD"],
        ]
    )
    for cmd in candidates:
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                cwd=REPO_ROOT,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout
        except Exception:  # noqa: S112
            continue
    return ""


class MutantCandidate:
    """Description of an AST mutation candidate."""

    def __init__(
        self,
        file_path: Path,
        lineno: int,
        col_offset: int,
        description: str,
        mutated_ast: ast.AST,
        original_source: str,
    ):
        self.file_path = file_path
        self.lineno = lineno
        self.col_offset = col_offset
        self.description = description
        self.mutated_ast = mutated_ast
        self.original_source = original_source


def generate_mutations_for_file(
    file_path: Path, target_lines: set[int] | None = None
) -> list[MutantCandidate]:
    """Generate subtle syntax/logic mutations for nodes on target lines."""
    if not file_path.is_file():
        return []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except Exception:
        return []

    candidates: list[MutantCandidate] = []

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is None:
            continue
        if target_lines is not None and lineno not in target_lines:
            continue

        mutations = _get_node_mutations(node)
        for desc, mutated_node in mutations:
            cloned_tree = copy.deepcopy(tree)
            target = _find_matching_node(cloned_tree, node)
            if target is not None:
                _replace_node_in_tree(cloned_tree, target, mutated_node)
                ast.fix_missing_locations(cloned_tree)
                candidates.append(
                    MutantCandidate(
                        file_path=file_path,
                        lineno=lineno,
                        col_offset=getattr(node, "col_offset", 0),
                        description=desc,
                        mutated_ast=cloned_tree,
                        original_source=source,
                    )
                )

    return candidates


def _get_node_mutations(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """Determine potential mutation operations for an AST node."""
    mutations: list[tuple[str, ast.AST]] = []

    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            mutations.append(("+ -> -", ast.BinOp(left=node.left, op=ast.Sub(), right=node.right)))
        elif isinstance(node.op, ast.Sub):
            mutations.append(("- -> +", ast.BinOp(left=node.left, op=ast.Add(), right=node.right)))
        elif isinstance(node.op, ast.Mult):
            mutations.append(("* -> /", ast.BinOp(left=node.left, op=ast.Div(), right=node.right)))
        elif isinstance(node.op, ast.Div):
            mutations.append(("/ -> *", ast.BinOp(left=node.left, op=ast.Mult(), right=node.right)))

    elif isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        op = node.ops[0]
        right = node.comparators[0]
        if isinstance(op, ast.Eq):
            mutations.append(
                ("== -> !=", ast.Compare(left=node.left, ops=[ast.NotEq()], comparators=[right]))
            )
        elif isinstance(op, ast.NotEq):
            mutations.append(
                ("!= -> ==", ast.Compare(left=node.left, ops=[ast.Eq()], comparators=[right]))
            )
        elif isinstance(op, ast.Lt):
            mutations.append(
                ("< -> >=", ast.Compare(left=node.left, ops=[ast.GtE()], comparators=[right]))
            )
        elif isinstance(op, ast.LtE):
            mutations.append(
                ("<= -> >", ast.Compare(left=node.left, ops=[ast.Gt()], comparators=[right]))
            )
        elif isinstance(op, ast.Gt):
            mutations.append(
                ("> -> <=", ast.Compare(left=node.left, ops=[ast.LtE()], comparators=[right]))
            )
        elif isinstance(op, ast.GtE):
            mutations.append(
                (">= -> <", ast.Compare(left=node.left, ops=[ast.Lt()], comparators=[right]))
            )

    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            mutations.append(("and -> or", ast.BoolOp(op=ast.Or(), values=node.values)))
        elif isinstance(node.op, ast.Or):
            mutations.append(("or -> and", ast.BoolOp(op=ast.And(), values=node.values)))

    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            mutations.append(
                (
                    f"{node.value} -> {not node.value}",
                    ast.Constant(value=not node.value),
                )
            )

    return mutations


def _find_matching_node(tree: ast.AST, target: ast.AST) -> ast.AST | None:
    """Find the exact node in cloned tree matching line and column offset."""
    t_line = getattr(target, "lineno", None)
    t_col = getattr(target, "col_offset", None)
    t_type = type(target)

    for node in ast.walk(tree):
        if (
            type(node) is t_type
            and getattr(node, "lineno", None) == t_line
            and getattr(node, "col_offset", None) == t_col
        ):
            return node
    return None


def _replace_node_in_tree(tree: ast.AST, old_node: ast.AST, new_node: ast.AST) -> None:
    """Replace an AST node within its parent structure."""
    for parent in ast.walk(tree):
        for field_name, value in ast.iter_fields(parent):
            if isinstance(value, list):
                for idx, item in enumerate(value):
                    if item is old_node:
                        value[idx] = new_node
                        return
            elif value is old_node:
                setattr(parent, field_name, new_node)
                return


def find_associated_tests(file_path: Path) -> list[str]:
    """Map an altered source file to its corresponding test suite modules."""
    rel = file_path.relative_to(REPO_ROOT) if file_path.is_absolute() else file_path
    rel_str = str(rel).replace("\\", "/")

    stem = file_path.stem
    direct_test = REPO_ROOT / "tests" / f"test_{stem}.py"
    if direct_test.is_file():
        return [str(direct_test.relative_to(REPO_ROOT))]

    # Heuristic mapping for core packages
    if "evals" in rel_str:
        return ["tests/test_scorers.py"]
    if "retrieval" in rel_str:
        return ["tests/test_dense.py", "tests/test_hybrid.py"]
    if "api" in rel_str:
        return ["tests/test_api_app.py", "tests/test_metrics.py"]

    return ["tests/test_scorers.py"]


def run_test_command(test_args: list[str], timeout: float = 15.0) -> bool:
    """Run pytest command; returns True if tests passed, False if any failed."""
    cmd = [sys.executable, "-m", "pytest", "-q", "-m", "not slow"] + test_args
    env = os.environ.copy()
    env["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=REPO_ROOT,
            timeout=timeout,
            env=env,
            check=False,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        # Timeouts also mean the mutant disrupted execution or hung -> treated as killed
        return False
    except Exception:
        return False


def load_baseline(baseline_path: Path) -> tuple[int, int, float]:
    """Load baseline total mutants, killed count, and baseline score."""
    if baseline_path.is_file():
        try:
            data = json.loads(baseline_path.read_text(encoding="utf-8"))
            tot = data.get("total", {})
            mutants = int(tot.get("mutants", 278))
            killed = int(tot.get("killed", 218))
            score_pct = float(tot.get("score_pct", 78.4))
            return mutants, killed, score_pct / 100.0
        except Exception:  # noqa: S110
            pass
    return 278, 218, 0.784


def evaluate_mutation_gate(
    config: MutationGateConfig,
    diff_text: str | None = None,
    custom_candidates: list[MutantCandidate] | None = None,
) -> MutationReport:
    """Run mutation ratcheting gate over diff or candidates."""
    base_mutants, base_killed, base_score = load_baseline(config.baseline_path)

    if custom_candidates is not None:
        candidates = custom_candidates
        modified_files = sorted({str(c.file_path) for c in candidates})
    else:
        if diff_text is None:
            diff_text = get_git_diff(config.target_branch)

        diff_map = parse_diff_lines(diff_text)
        candidates = []
        modified_files = []

        for rel_file, lines in diff_map.items():
            norm_path = rel_file.replace("\\", "/")
            if not (norm_path.startswith("app/") and norm_path.endswith(".py")):
                continue
            fpath = REPO_ROOT / norm_path
            if fpath.is_file():
                modified_files.append(norm_path)
                candidates.extend(
                    generate_mutations_for_file(
                        fpath, target_lines=lines if config.diff_only else None
                    )
                )

    if len(candidates) > config.max_mutants_per_run:
        candidates = candidates[: config.max_mutants_per_run]

    mutants_generated = len(candidates)
    mutants_killed = 0
    survivors: list[dict[str, Any]] = []

    for _idx, candidate in enumerate(candidates, start=1):
        test_suites = find_associated_tests(candidate.file_path)
        mutated_code = ast.unparse(candidate.mutated_ast)

        # Write mutated code temporarily
        try:
            candidate.file_path.write_text(mutated_code, encoding="utf-8")
            passed = run_test_command(test_suites, timeout=config.timeout_per_mutant)
            if not passed:
                mutants_killed += 1
            else:
                survivors.append(
                    {
                        "file": str(
                            candidate.file_path.relative_to(REPO_ROOT)
                            if candidate.file_path.is_absolute()
                            else candidate.file_path
                        ),
                        "line": candidate.lineno,
                        "description": candidate.description,
                    }
                )
        finally:
            # Revert unconditionally
            candidate.file_path.write_text(candidate.original_source, encoding="utf-8")

    mutants_survived = mutants_generated - mutants_killed

    if mutants_generated > 0:
        diff_score = mutants_killed / mutants_generated
        cumulative_mutants = base_mutants + mutants_generated
        cumulative_killed = base_killed + mutants_killed
        cumulative_score = cumulative_killed / cumulative_mutants
    else:
        diff_score = 1.0
        cumulative_score = base_score

    # Gate logic:
    # 1. No surviving mutants in the modified code diff.
    # 2. Cumulative score must not regress below min_score (78.4%) or baseline score.
    ratchet_floor = max(config.min_score, base_score)
    gate_passed = (mutants_survived == 0) and (cumulative_score >= ratchet_floor - 1e-4)

    summary = (
        f"Diff mutants: {mutants_generated} generated, {mutants_killed} killed, "
        f"{mutants_survived} survived. Diff score: {diff_score * 100:.1f}%. "
        f"Cumulative score: {cumulative_score * 100:.1f}% (Ratchet floor: {ratchet_floor * 100:.1f}%)."
    )

    report = MutationReport(
        mutants_generated=mutants_generated,
        mutants_killed=mutants_killed,
        mutants_survived=mutants_survived,
        mutation_score=round(cumulative_score, 4),
        gate_passed=gate_passed,
        baseline_score=base_score,
        baseline_mutants=base_mutants,
        cumulative_score=round(cumulative_score, 4),
        survivors=survivors,
        modified_files=modified_files,
        summary=summary,
    )

    # Persist report
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="FEAT-096: Mutation Score Ratcheting CI Gate")
    parser.add_argument("--base", default="main", help="Target base branch (default: main)")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.784,
        help="Minimum mutation score floor (default: 0.784)",
    )
    parser.add_argument("--diff-only", action="store_true", default=True, help="Evaluate diff only")
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Output path for mutation-report.json",
    )
    parser.add_argument("--diff-file", type=Path, default=None, help="Read diff from file")

    args = parser.parse_args()

    diff_text = None
    if args.diff_file and args.diff_file.is_file():
        diff_text = args.diff_file.read_text(encoding="utf-8")

    config = MutationGateConfig(
        min_score=args.min_score,
        diff_only=args.diff_only,
        report_path=args.report,
        target_branch=args.base,
    )

    print("Running Mutation Score Ratcheting CI Gate...")
    report = evaluate_mutation_gate(config, diff_text=diff_text)
    print(report.summary)

    if not report.gate_passed:
        print("\n::error::Mutation score ratcheting gate FAILED!")
        if report.survivors:
            print("Surviving mutants in modified lines:")
            for s in report.survivors:
                print(f"  - {s['file']}:{s['line']} -> {s['description']}")
        return 1

    print("\nMutation score ratcheting gate PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
