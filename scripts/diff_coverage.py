#!/usr/bin/env python
"""FEAT-097: Differential / Patch Coverage Gating (100% Diff Coverage).

Enforces 100% test coverage on modified lines in pull requests instead of tracking
blunt whole-repository statement coverage, preventing coverage gaming and untested code paths.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE_XML = REPO_ROOT / "coverage.xml"
DEFAULT_REPORT = REPO_ROOT / "docs" / "verification" / "diff-coverage-report.json"


@dataclass
class DiffCoverageConfig:
    """Configuration schema for differential coverage gating."""

    required_percentage: float = 100.0
    coverage_xml_path: Path = DEFAULT_COVERAGE_XML
    report_path: Path = DEFAULT_REPORT
    target_branch: str = "main"


@dataclass
class DiffCoverageResult:
    """Output schema for differential coverage gating."""

    lines_modified: int
    lines_covered: int
    diff_coverage_pct: float
    uncovered_lines: list[int]
    passed: bool
    uncovered_by_file: dict[str, list[int]] = field(default_factory=dict)
    files_evaluated: list[str] = field(default_factory=list)
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
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                current_file = parts[3][2:].strip()
                if current_file not in modified_lines:
                    modified_lines[current_file] = set()
            else:
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


def parse_coverage_xml(xml_source: str | Path) -> dict[str, dict[int, int]]:
    """Parse Cobertura coverage XML into a mapping of relative_path -> {line_number: hits}."""
    if isinstance(xml_source, Path):
        if not xml_source.is_file():
            return {}
        xml_text = xml_source.read_text(encoding="utf-8")
    else:
        xml_text = xml_source

    if not xml_text.strip():
        return {}

    try:
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError:
        return {}

    sources = [
        s.text.strip().replace("\\", "/") for s in root.findall(".//sources/source") if s.text
    ]

    file_coverage: dict[str, dict[int, int]] = {}

    for cls in root.findall(".//class"):
        raw_filename = cls.get("filename", "")
        if not raw_filename:
            continue

        raw_filename = raw_filename.replace("\\", "/")

        matched_rel = None
        # Try finding relative path from sources
        for src in sources:
            combined = f"{src}/{raw_filename}".replace("//", "/")
            if "app/" in combined:
                idx = combined.find("app/")
                matched_rel = combined[idx:]
                break

        if not matched_rel:
            if "app/" in raw_filename:
                matched_rel = raw_filename[raw_filename.find("app/") :]
            else:
                matched_rel = f"app/{raw_filename}"

        matched_rel = matched_rel.replace("\\", "/")
        lines_dict: dict[int, int] = {}

        for line_elem in cls.findall(".//lines/line"):
            num_str = line_elem.get("number")
            hits_str = line_elem.get("hits", "0")
            if num_str:
                try:
                    num = int(num_str)
                    hits = int(hits_str)
                    lines_dict[num] = hits
                except ValueError:
                    continue

        file_coverage[matched_rel] = lines_dict

    return file_coverage


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


def evaluate_diff_coverage(
    config: DiffCoverageConfig,
    diff_text: str | None = None,
    coverage_data: dict[str, dict[int, int]] | None = None,
) -> DiffCoverageResult:
    """Evaluate differential coverage against modified diff lines."""
    if coverage_data is None:
        coverage_data = parse_coverage_xml(config.coverage_xml_path)

    if diff_text is None:
        diff_text = get_git_diff(config.target_branch)

    diff_map = parse_diff_lines(diff_text)

    total_modified_executable = 0
    total_covered_executable = 0
    all_uncovered_lines: list[int] = []
    uncovered_by_file: dict[str, list[int]] = {}
    files_evaluated: list[str] = []

    for rel_file, changed_lines in diff_map.items():
        norm_path = rel_file.replace("\\", "/")
        if not (norm_path.startswith("app/") and norm_path.endswith(".py")):
            continue

        files_evaluated.append(norm_path)

        # Look up file in coverage data
        file_lines = coverage_data.get(norm_path, {})
        if not file_lines:
            # Fallback search by suffix
            for k, v in coverage_data.items():
                if norm_path.endswith(k) or k.endswith(norm_path):
                    file_lines = v
                    break

        file_uncovered: list[int] = []

        for line_num in sorted(changed_lines):
            # Only executable lines recorded in coverage.xml count towards denominator
            if line_num in file_lines:
                total_modified_executable += 1
                hits = file_lines[line_num]
                if hits > 0:
                    total_covered_executable += 1
                else:
                    total_covered_executable += 0
                    file_uncovered.append(line_num)
                    all_uncovered_lines.append(line_num)

        if file_uncovered:
            uncovered_by_file[norm_path] = file_uncovered

    if total_modified_executable == 0:
        pct = 100.0
        passed = True
    else:
        pct = round(100.0 * total_covered_executable / total_modified_executable, 2)
        if config.required_percentage >= 100.0:
            passed = (pct >= 100.0) and (len(all_uncovered_lines) == 0)
        else:
            passed = pct >= config.required_percentage

    summary = (
        f"Diff coverage: {pct:.1f}% ({total_covered_executable}/{total_modified_executable} "
        f"executable lines covered). Required: {config.required_percentage:.1f}%."
    )

    result = DiffCoverageResult(
        lines_modified=total_modified_executable,
        lines_covered=total_covered_executable,
        diff_coverage_pct=pct,
        uncovered_lines=all_uncovered_lines,
        passed=passed,
        uncovered_by_file=uncovered_by_file,
        files_evaluated=sorted(files_evaluated),
        summary=summary,
    )

    # Persist JSON report
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(
        json.dumps(result.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FEAT-097: Differential / Patch Coverage Gating (100% Diff Coverage)"
    )
    parser.add_argument("--base", default="main", help="Target base branch (default: main)")
    parser.add_argument(
        "--required-pct",
        type=float,
        default=100.0,
        help="Required diff coverage percentage (default: 100.0)",
    )
    parser.add_argument(
        "--coverage-xml",
        type=Path,
        default=DEFAULT_COVERAGE_XML,
        help="Path to coverage.xml",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Path for diff-coverage-report.json",
    )
    parser.add_argument("--diff-file", type=Path, default=None, help="Read diff from file")

    args = parser.parse_args()

    diff_text = None
    if args.diff_file and args.diff_file.is_file():
        diff_text = args.diff_file.read_text(encoding="utf-8")

    config = DiffCoverageConfig(
        required_percentage=args.required_pct,
        coverage_xml_path=args.coverage_xml,
        report_path=args.report,
        target_branch=args.base,
    )

    print("Running Differential / Patch Coverage Gate...")
    result = evaluate_diff_coverage(config, diff_text=diff_text)
    print(result.summary)

    if not result.passed:
        print("\n::error::Differential coverage gate FAILED (below 100% diff coverage)!")
        for fpath, lines in result.uncovered_by_file.items():
            for ln in lines:
                print(f"::error file={fpath},line={ln}::Uncovered executable modified line {ln}")
        return 1

    print("\nDifferential coverage gate PASSED (100% diff coverage).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
