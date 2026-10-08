"""Tests for scripts/git_history.sh, the history-persistence fallback.

Why a test for a shell script: this platform restores the working tree but rolls `.git`
back to a fixed baseline commit, so the bundle written by this script is the only copy of
the project's history that survives a session. A silent failure here loses the commit
thread permanently, and the failure mode is invisible until the next reset -- the worst
possible time to discover it.

Each test builds a throwaway repository in tmp_path, so nothing here can touch the real
one. The repository being tested is deliberately not DocScout's: these assertions are
about git mechanics, and a fixture repo makes the pre-conditions explicit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git_history.sh"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def run_script(repo: Path, command: str) -> subprocess.CompletedProcess[str]:
    """Invoke the COPY inside the fixture repo, through bash.

    The copy matters: the script resolves its own repository root from its own location,
    so running the original would operate on DocScout itself and the assertions would
    silently describe the real repo instead of the fixture. Through bash, not directly,
    because snapshots strip the executable bit.
    """
    local = repo / "scripts" / "git_history.sh"
    assert local.is_file(), "fixture must carry its own copy of the script"
    env = {**os.environ, "HOME": str(repo)}
    return subprocess.run(
        ["bash", "scripts/git_history.sh", command],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a baseline commit, then two further commits that ADD files.

    Commits that add files are the case that matters: the index bug this module pins only
    manifests when the branch pointer moves forward over newly added paths.
    """
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    git_dir = work
    subprocess.run(["git", "init", "-q", "-b", "master", str(work)], check=True)
    git(git_dir, "config", "user.name", "Test")
    git(git_dir, "config", "user.email", "test@example.invalid")

    # Mirror the real repository: the script is tracked, the bundle directory is not.
    shutil.copy(SCRIPT, work / "scripts" / "git_history.sh")
    (work / ".gitignore").write_text(".history/\n")
    (work / "baseline.txt").write_text("baseline\n")
    git(git_dir, "add", "-A")
    git(git_dir, "commit", "-qm", "baseline")

    for n in (1, 2):
        (work / f"added-{n}.txt").write_text(f"added {n}\n")
        (work / "scripts" / f"mod-{n}.txt").write_text(f"mod {n}\n")
        git(git_dir, "add", "-A")
        git(git_dir, "commit", "-qm", f"add set {n}")

    return work


def baseline_sha(repo: Path) -> str:
    return git(repo, "rev-list", "--max-parents=0", "HEAD")


def test_save_writes_a_verifiable_bundle_and_manifest(repo: Path) -> None:
    assert run_script(repo, "save").returncode == 0
    bundle = repo / ".history" / "docscout.bundle"
    assert bundle.is_file() and bundle.stat().st_size > 0
    subprocess.run(["git", "bundle", "verify", str(bundle)], check=True, capture_output=True)
    manifest = (repo / ".history" / "manifest.txt").read_text()
    assert "commits     3" in manifest
    assert git(repo, "rev-parse", "HEAD") in manifest


def test_restore_recovers_history_and_leaves_no_phantom_changes(repo: Path) -> None:
    """The regression this module exists for.

    A real restored session starts with BOTH the refs and the index at the baseline commit.
    Restoring with `git reset --soft` moves the branch pointer but leaves the index
    describing the baseline, so every file added by the recovered commits is reported as a
    staged deletion and as untracked at the same time -- on a tree that is byte-identical
    to the restored HEAD. The fix is --mixed, and this asserts the observable consequence:
    a clean status.
    """
    run_script(repo, "save")
    head = git(repo, "rev-parse", "HEAD")

    # Simulate the platform's rollback faithfully: refs AND index to baseline, tree kept.
    git(repo, "reset", "-q", "--mixed", baseline_sha(repo))
    assert git(repo, "rev-list", "--count", "HEAD") == "1"

    result = run_script(repo, "restore")
    assert result.returncode == 0, result.stderr

    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "rev-list", "--count", "HEAD") == "3"
    assert git(repo, "status", "--porcelain") == ""


def test_restore_preserves_uncommitted_working_tree_edits(repo: Path) -> None:
    """The tree is the surviving copy; restore must never overwrite it."""
    run_script(repo, "save")
    git(repo, "reset", "-q", "--mixed", baseline_sha(repo))
    (repo / "added-1.txt").write_text("edited after the reset\n")

    run_script(repo, "restore")

    assert (repo / "added-1.txt").read_text() == "edited after the reset\n"
    assert "added-1.txt" in git(repo, "status", "--porcelain")


def test_restore_refuses_to_discard_commits_the_bundle_lacks(repo: Path) -> None:
    """Fast-forward only. A restore that rewound local work would be worse than no restore."""
    run_script(repo, "save")
    (repo / "newer.txt").write_text("work done after the last save\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "newer than the bundle")
    head = git(repo, "rev-parse", "HEAD")

    result = run_script(repo, "restore")

    assert result.returncode == 0
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / "newer.txt").is_file()


def test_restore_without_a_bundle_is_a_no_op(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    result = run_script(repo, "restore")
    assert result.returncode == 0
    assert "nothing to restore" in result.stdout
    assert git(repo, "rev-parse", "HEAD") == head


def test_corrupt_bundle_is_refused_rather_than_half_applied(repo: Path) -> None:
    run_script(repo, "save")
    git(repo, "reset", "-q", "--mixed", baseline_sha(repo))
    (repo / ".history" / "docscout.bundle").write_bytes(b"not a bundle")

    result = run_script(repo, "restore")

    assert result.returncode != 0
    assert "corrupt" in (result.stderr + result.stdout)
    assert git(repo, "rev-list", "--count", "HEAD") == "1"


def test_status_reports_drift_in_both_directions(repo: Path) -> None:
    run_script(repo, "save")
    assert "in sync" in run_script(repo, "status").stdout

    (repo / "later.txt").write_text("later\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "later")
    assert "AHEAD" in run_script(repo, "status").stdout

    git(repo, "reset", "-q", "--mixed", baseline_sha(repo))
    assert (
        "behind" in run_script(repo, "status").stdout.lower()
        or "ahead or diverged" in run_script(repo, "status").stdout
    )
