"""Tests for the Strict QA Content and Typography Assurance Gates.

Ensures no recruiter framing, senior-engineer expectations, resume terminology,
or unwanted em-dashes ever enter DocScout code, docs, or release notes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.qa_content_gate import (
    REPO_ROOT,
    check_forbidden_terms,
    check_typography,
    get_tracked_files,
)


def test_repo_has_zero_forbidden_recruiter_terms() -> None:
    """Assert zero recruiter / resume / hiring-loop patterns exist across the repository."""
    files = get_tracked_files()
    assert len(files) > 100, f"Expected >100 tracked files, got {len(files)}"
    violations = check_forbidden_terms(files)
    assert not violations, "Forbidden term violations detected:\n" + "\n".join(violations)


def test_repo_has_zero_em_dashes_in_documentation_and_code() -> None:
    """Assert zero em-dashes exist across repository code, documentation, and config."""
    files = get_tracked_files()
    violations = check_typography(files)
    assert not violations, "Em-dash violations detected:\n" + "\n".join(violations)


def test_qa_gate_scanner_catches_synthetic_forbidden_term(tmp_path: Path, monkeypatch) -> None:
    """Verify the QA gate detector correctly flags forbidden resume/recruiter language."""
    synthetic_file = tmp_path / "synthetic_bad_doc.md"
    synthetic_file.write_text(
        "# Proposal\nThis ensures maximum recruiter signal for hiring loops.\n",
        encoding="utf-8",
    )
    rel_path = synthetic_file.relative_to(tmp_path).as_posix()

    monkeypatch.setattr("scripts.qa_content_gate.REPO_ROOT", tmp_path)
    violations = check_forbidden_terms([rel_path])
    assert len(violations) >= 1
    assert any("recruiter" in v for v in violations)


def test_qa_gate_scanner_catches_synthetic_em_dash(tmp_path: Path, monkeypatch) -> None:
    """Verify the QA gate detector correctly flags em-dashes."""
    synthetic_file = tmp_path / "synthetic_em_dash.md"
    synthetic_file.write_text(
        "# Heading\nTitle \u2014 Description\n",
        encoding="utf-8",
    )
    rel_path = synthetic_file.relative_to(tmp_path).as_posix()

    monkeypatch.setattr("scripts.qa_content_gate.REPO_ROOT", tmp_path)
    violations = check_typography([rel_path])
    assert len(violations) == 1
    assert "[EM_DASH_VIOLATION]" in violations[0]


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
