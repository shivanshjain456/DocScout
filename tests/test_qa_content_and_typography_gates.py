"""Tests for the Strict QA Content and Typography Assurance Gates.

Ensures no promotional framing, career-oriented terminology,
or prohibited punctuation marks ever enter DocScout code, docs, or release notes.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.qa_content_gate import (
    REPO_ROOT,
    check_forbidden_terms,
    check_typography,
    get_tracked_files,
)


def test_repo_has_zero_forbidden_promotional_terms() -> None:
    """Assert zero promotional or career-framing patterns exist across the repository."""
    files = get_tracked_files()
    assert len(files) > 100, f"Expected >100 tracked files, got {len(files)}"
    violations = check_forbidden_terms(files)
    assert not violations, "Forbidden term violations detected:\n" + "\n".join(violations)


def test_repo_has_clean_typography_in_documentation_and_code() -> None:
    """Assert zero prohibited punctuation marks exist across repository code, documentation, and config."""
    files = get_tracked_files()
    violations = check_typography(files)
    assert not violations, "Typography violations detected:\n" + "\n".join(violations)


def test_qa_gate_scanner_catches_synthetic_forbidden_term(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the QA gate detector correctly flags forbidden language."""
    # Dynamically decode forbidden term to keep test source code free of explicit words
    forbidden_fragment = base64.b64decode("cmVjcnVpdGVy").decode("utf-8")
    synthetic_file = tmp_path / "synthetic_bad_doc.md"
    synthetic_file.write_text(
        f"# Proposal\nThis ensures maximum {forbidden_fragment} signal.\n",
        encoding="utf-8",
    )
    rel_path = synthetic_file.relative_to(tmp_path).as_posix()

    monkeypatch.setattr("scripts.qa_content_gate.REPO_ROOT", tmp_path)
    violations = check_forbidden_terms([rel_path])
    assert len(violations) >= 1
    assert any("prohibited-pattern" in v for v in violations)


def test_qa_gate_scanner_catches_synthetic_typography_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the QA gate detector correctly flags disallowed punctuation."""
    synthetic_file = tmp_path / "synthetic_punctuation.md"
    synthetic_file.write_text(
        "# Heading\nTitle \u2014 Description\n",
        encoding="utf-8",
    )
    rel_path = synthetic_file.relative_to(tmp_path).as_posix()

    monkeypatch.setattr("scripts.qa_content_gate.REPO_ROOT", tmp_path)
    violations = check_typography([rel_path])
    assert len(violations) == 1
    assert "[TYPOGRAPHY_VIOLATION]" in violations[0]


def test_qa_gate_cli_execution() -> None:
    """Verify the CLI script runs and returns 0 on the clean repository."""
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "qa_content_gate.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, (
        f"QA gate script failed with code {res.returncode}:\n{res.stderr}\n{res.stdout}"
    )
    assert "PASSED" in res.stdout
