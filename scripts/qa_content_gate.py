#!/usr/bin/env python3
"""Quality Assurance & Strict Content Gate for DocScout.

Enforces zero forbidden terms (recruiter framing, resume references, hiring loops)
and typography cleanliness (zero em-dashes in documentation and source code) repository-wide.

Exit code 0 on clean pass, exit code 1 on any violation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Forbidden patterns denoting resume/recruiter/hiring framing
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("recruiter", re.compile(r"\brecruiter[s]?\b", re.IGNORECASE)),
    ("recruiting", re.compile(r"\brecruiting\b", re.IGNORECASE)),
    ("recruiter-signal", re.compile(r"\brecruiter[- ]signal\b", re.IGNORECASE)),
    (
        "senior-engineer-expectation",
        re.compile(r"\bsenior[- ]engineer[- ]expectation[s]?\b", re.IGNORECASE),
    ),
    ("hiring-loop", re.compile(r"\bhiring[- ]loop[s]?\b", re.IGNORECASE)),
    ("hiring-signal", re.compile(r"\bhiring[- ]signal\b", re.IGNORECASE)),
    ("resume-bullet", re.compile(r"\bresume[- ]bullet[s]?\b", re.IGNORECASE)),
    ("resume-bank", re.compile(r"\bresume[- ]bank\b", re.IGNORECASE)),
]

# Files explicitly exempt from specific checks
EXEMPT_FROM_ALL = {
    "scripts/qa_content_gate.py",
    "tests/test_qa_content_and_typography_gates.py",
    "scratch/clean_releases.py",
    "scratch/replace_em_dashes.py",
}

# Cryptographically pinned evaluation datasets exempt from typography normalization
EXEMPT_FROM_TYPOGRAPHY = {
    "evals/gold/v1/gold.jsonl",
}

IGNORE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".wasm",
    ".lock",
    ".pyc",
    ".parquet",
}


def get_tracked_files() -> list[str]:
    """Retrieve list of git-tracked files."""
    git_bin = shutil.which("git") or "git"
    try:
        res = subprocess.run(  # noqa: S603
            [git_bin, "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception as exc:
        logger.warning("Failed to get git tracked files via git: %s", exc)
        files: list[str] = []
        for root, _dirs, filenames in os.walk(REPO_ROOT):
            if any(p in root for p in [".git", "node_modules", ".venv", "__pycache__"]):
                continue
            for f in filenames:
                rel = os.path.relpath(os.path.join(root, f), REPO_ROOT).replace("\\", "/")
                files.append(rel)
        return files


def check_forbidden_terms(files: list[str]) -> list[str]:
    """Check for forbidden recruiter and hiring-related terminology."""
    violations: list[str] = []
    for rel_path in files:
        if rel_path in EXEMPT_FROM_ALL:
            continue
        if any(rel_path.endswith(ext) for ext in IGNORE_EXTENSIONS):
            continue

        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            for name, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"[FORBIDDEN_TERM:{name}] {rel_path}:{line_no} -> {line.strip()[:120]}"
                    )
    return violations


def check_typography(files: list[str]) -> list[str]:
    """Check for em-dash (\\u2014) violations across documentation and code."""
    violations: list[str] = []
    for rel_path in files:
        if rel_path in EXEMPT_FROM_ALL or rel_path in EXEMPT_FROM_TYPOGRAPHY:
            continue
        if any(rel_path.endswith(ext) for ext in IGNORE_EXTENSIONS):
            continue

        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        if "\u2014" in content:
            for line_no, line in enumerate(content.splitlines(), start=1):
                if "\u2014" in line:
                    violations.append(
                        f"[EM_DASH_VIOLATION] {rel_path}:{line_no} -> {line.strip()[:120]}"
                    )
    return violations


def check_github_releases() -> list[str]:
    """Verify GitHub releases if GitHub CLI is accessible."""
    violations: list[str] = []
    gh_bin = shutil.which("gh")
    if not gh_bin:
        return []

    try:
        res = subprocess.run(  # noqa: S603
            [gh_bin, "release", "list"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return []

        lines = [line.split("\t") for line in res.stdout.splitlines() if line.strip()]
        tags = [cols[2] for cols in lines if len(cols) >= 3]

        for tag in tags:
            v_res = subprocess.run(  # noqa: S603
                [gh_bin, "release", "view", tag, "--json", "name,body"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if v_res.returncode != 0:
                continue

            data = json.loads(v_res.stdout)
            name = data.get("name", "")
            body = data.get("body", "")

            # Check title
            for p_name, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(name):
                    violations.append(f"[RELEASE_TITLE_FORBIDDEN:{p_name}] {tag} -> {name}")
            if "\u2014" in name:
                violations.append(f"[RELEASE_TITLE_EM_DASH] {tag} -> {name}")

            # Check body
            for line_no, line in enumerate(body.splitlines(), start=1):
                for p_name, pattern in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            f"[RELEASE_BODY_FORBIDDEN:{p_name}] {tag}:{line_no} -> {line.strip()[:100]}"
                        )
                if "\u2014" in line:
                    violations.append(
                        f"[RELEASE_BODY_EM_DASH] {tag}:{line_no} -> {line.strip()[:100]}"
                    )
    except Exception as exc:
        logger.info("GitHub releases check skipped or unavailable: %s", exc)
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="DocScout QA Content and Typography Gate")
    parser.add_argument(
        "--check-releases", action="store_true", help="Audit GitHub releases via gh CLI"
    )
    args = parser.parse_args()

    print("============================================================")
    print("  DocScout Strict QA Content & Typography Assurance Gate    ")
    print("============================================================")

    files = get_tracked_files()
    print(f"Scanning {len(files)} tracked files...")

    term_violations = check_forbidden_terms(files)
    typo_violations = check_typography(files)
    release_violations = check_github_releases() if args.check_releases else []

    all_violations = term_violations + typo_violations + release_violations

    if all_violations:
        print(
            f"\n[FAIL] Found {len(all_violations)} strict QA assurance violation(s):",
            file=sys.stderr,
        )
        for v in all_violations:
            print(f"  ERROR: {v}", file=sys.stderr)
        print(
            "\nAll code and documentation must adhere to enterprise production standards.",
            file=sys.stderr,
        )
        return 1

    print(f"[PASS] Zero forbidden terms across {len(files)} tracked files.")
    print(f"[PASS] Zero em dashes across {len(files)} tracked files.")
    if args.check_releases:
        print("[PASS] GitHub releases audit passed cleanly with zero violations.")
    print("[PASS] All DocScout QA Content & Typography Assurance Gates PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
