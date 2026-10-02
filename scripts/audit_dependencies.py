#!/usr/bin/env python
"""Scan the locked dependency set for known advisories and emit an SBOM.

Run with `make audit-deps`. Exit code 1 means a *runtime* dependency has a known
advisory; development-only findings are reported and do not fail the build.

Design decisions, each of which has a reason:

**pip-audit, and only pip-audit.** It is maintained by the Python Packaging Authority,
Apache-2.0, and matches against OSV and the PyPI Advisory Database using ecosystem-specific
version comparison, which produces fewer false positives than CPE matching. The obvious
alternative, Safety, was rejected on licensing: the tool is open source but its vulnerability
data is not free for commercial use. Running both as gates was also rejected -- two
databases means two sets of false positives to triage, and alert fatigue is the documented
failure mode of this kind of tooling.

**The lockfile, not the installed environment.** Auditing `pip-audit` with no arguments
reads whatever happens to be installed, which is neither reproducible nor separable into
runtime and development. Exporting `uv.lock` gives the exact pinned set, lets CI check a
pull request without installing anything, and makes the runtime/dev split possible.

**Local version identifiers are stripped before auditing.** `uv.lock` pins
`torch==2.14.1+cpu`, a wheel from the PyTorch CPU index that does not exist on PyPI. Left
alone, pip-audit reports `Dependency not found on PyPI and could not be audited` and moves
on -- silently skipping the single largest dependency in the project while still printing
"No known vulnerabilities found". `torch==2.14.1` is the same upstream source revision, so
auditing that is both possible and correct. Skips are counted and reported either way.

**Phantom packages are identified, not counted.** Stripping `+cpu` buys torch coverage at a
price: pip-audit reads the *upstream* torch metadata and so audits sixteen `nvidia-*` and
`cuda-*` packages that a CPU build never installs. Those are phantom dependencies, and an
advisory against one of them is by definition not exploitable here. Every audited package is
therefore checked against the set actually installed by `uv sync`, and anything absent is
labelled; a finding against a phantom package is reported but does not fail the gate, with
the reason recorded in the artifact rather than left for someone to rediscover.

**Runtime findings fail the build; development findings do not.** A vulnerability in
`mutmut` cannot reach a user. Gating on it trains everyone to ignore the gate. Both are
reported; only one is fatal.

What a green run does **not** mean, stated here because the opposite assumption is how this
kind of gate becomes false comfort:

* It means no *published* advisory matched these pins at this moment. New advisories appear
  for unchanged code, so a scan is only as fresh as its last run.
* pip-audit matches at package granularity, with no reachability analysis. An empirical
  study of SBOM-based scanners (arXiv:2511.20313) measured a 92% false-positive rate driven
  largely by vulnerabilities in code paths the dependent never calls; the inverse also
  holds, in that a matched advisory is not automatically an exploitable one.
* It cannot detect a malicious package that has no CVE -- a typosquat or a hostile
  `setup.py` is invisible to an advisory database.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from app.config import sha256_file  # noqa: E402 - needs REPO_ROOT on the path first

OUTPUT_DIR = REPO_ROOT / "docs" / "security"
AUDIT_JSON = OUTPUT_DIR / "dependency-audit.json"
SBOM_PATH = OUTPUT_DIR / "sbom.cdx.json"

#: PEP 440 local version identifier, e.g. the "+cpu" in "torch==2.14.1+cpu".
LOCAL_VERSION = re.compile(r"^([A-Za-z0-9._-]+==[^+\s;]+)\+[A-Za-z0-9.]+(.*)$")

#: Advisories accepted as not actionable. Each entry needs an id, the package, a reason and
#: a review date -- a suppression without an expiry is a permanent blind spot. Empty today;
#: the only finding this scanner has produced so far was remediated by removing the
#: dependency that carried it rather than by suppressing it.
SUPPRESSIONS: dict[str, dict[str, str]] = {}


class Finding(TypedDict):
    """One advisory against one pinned package."""

    package: str
    version: str
    id: str
    aliases: list[str]
    fix_versions: list[str]
    description: str
    installed: bool


class Skipped(TypedDict):
    package: str
    reason: str


@dataclass(frozen=True)
class AuditResult:
    """Outcome for one dependency set. A dataclass rather than a dict so the fields are
    checked: the first version used `dict[str, object]` and mypy could not tell that
    `result["findings"]` was iterable."""

    packages_audited: int
    packages_installed: int
    phantom_packages: list[str]
    findings: list[Finding]
    skipped: list[Skipped]

    def as_dict(self) -> dict[str, object]:
        return {
            "packages_audited": self.packages_audited,
            "packages_installed": self.packages_installed,
            "phantom_packages": self.phantom_packages,
            "findings": self.findings,
            "skipped": self.skipped,
        }


def installed_distributions() -> set[str]:
    """Normalised names of everything actually present in the environment.

    The comparison basis for phantom detection. Uses importlib.metadata rather than parsing
    the lockfile again, because what matters is what `uv sync` really installed.
    """
    import importlib.metadata as metadata

    names: set[str] = set()
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            names.add(normalise(name))
    return names


def normalise(name: str) -> str:
    """PEP 503 normalisation, so `nvidia_cublas` and `nvidia-cublas` compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv built in this module
        argv, capture_output=True, text=True, cwd=REPO_ROOT, check=False
    )


def export_requirements(dev: bool) -> list[str]:
    """Pinned requirement lines from uv.lock, with local versions normalised."""
    argv = ["uv", "export", "--format", "requirements-txt", "--no-hashes", "--no-emit-project"]
    if not dev:
        argv.append("--no-dev")
    result = run(argv)
    if result.returncode != 0:
        raise SystemExit(f"`uv export` failed:\n{result.stderr.strip()}")

    lines: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Drop environment markers: the audit is for this interpreter's resolution.
        line = line.split(";", 1)[0].strip()
        match = LOCAL_VERSION.match(line)
        if match:
            line = match.group(1)
        lines.append(line)
    return sorted(set(lines))


def audit(requirements: list[str], label: str, installed: set[str]) -> AuditResult:
    """Run pip-audit over a pinned requirement list."""
    scratch = REPO_ROOT / f".audit-{label}.txt"
    scratch.write_text("\n".join(requirements) + "\n")
    try:
        result = run(
            [
                "pip-audit",
                "--no-deps",
                "--requirement",
                str(scratch),
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ]
        )
        if not result.stdout.strip():
            raise SystemExit(
                f"pip-audit produced no output for the {label} set. This usually means it "
                f"could not reach the advisory database.\n{result.stderr.strip()}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"pip-audit returned unparseable output for the {label} set: {exc}\n"
                f"{result.stdout[:400]}"
            ) from exc
    finally:
        scratch.unlink(missing_ok=True)

    dependencies = payload.get("dependencies", [])
    findings: list[Finding] = [
        {
            "package": dep["name"],
            "version": dep["version"],
            "id": vuln["id"],
            "aliases": vuln.get("aliases", []),
            "fix_versions": vuln.get("fix_versions", []),
            "description": (vuln.get("description") or "").strip()[:500],
            "installed": normalise(dep["name"]) in installed,
        }
        for dep in dependencies
        for vuln in dep.get("vulns", [])
    ]
    # pip-audit lists each advisory once per matching requirement line; de-duplicate.
    unique = {(f["package"], f["id"]): f for f in findings}
    skipped: list[Skipped] = [
        {"package": entry["name"], "reason": entry["skip_reason"]}
        for entry in payload.get("skipped", payload.get("dependencies_skipped", []))
        if isinstance(entry, dict) and "skip_reason" in entry
    ]
    audited_names = {normalise(dep["name"]) for dep in dependencies}
    return AuditResult(
        packages_audited=len(dependencies),
        packages_installed=len(audited_names & installed),
        phantom_packages=sorted(audited_names - installed),
        findings=sorted(unique.values(), key=lambda f: (f["package"], f["id"])),
        skipped=skipped,
    )


def generate_sbom(requirements: list[str]) -> bool:
    """Write a CycloneDX SBOM for the runtime set. Returns True on success."""
    scratch = REPO_ROOT / ".sbom-input.txt"
    scratch.write_text("\n".join(requirements) + "\n")
    try:
        result = run(
            [
                "pip-audit",
                "--no-deps",
                "--requirement",
                str(scratch),
                "--format",
                "cyclonedx-json",
                "--progress-spinner",
                "off",
            ]
        )
        if result.returncode not in (0, 1) or not result.stdout.strip():
            print(f"  SBOM generation failed: {result.stderr.strip()[:300]}", file=sys.stderr)
            return False
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # Reformat so the committed file diffs line by line when a dependency changes.
        SBOM_PATH.write_text(json.dumps(json.loads(result.stdout), indent=2) + "\n")
        return True
    finally:
        scratch.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-sbom", action="store_true", help="audit only; do not regenerate the SBOM"
    )
    args = parser.parse_args(argv)

    runtime = export_requirements(dev=False)
    everything = export_requirements(dev=True)
    dev_only = sorted(set(everything) - set(runtime))

    print(f"  auditing {len(runtime)} runtime and {len(dev_only)} development-only pins...")
    installed = installed_distributions()
    runtime_result = audit(runtime, "runtime", installed)
    dev_result = audit(dev_only, "dev", installed) if dev_only else AuditResult(0, 0, [], [], [])

    # Only an advisory against a package that is genuinely installed can fail the build.
    # A phantom -- pulled in by upstream metadata but absent from this environment -- is
    # reported with its reason instead.
    runtime_findings = [
        f for f in runtime_result.findings if f["id"] not in SUPPRESSIONS and f["installed"]
    ]
    suppressed = [f for f in runtime_result.findings if f["id"] in SUPPRESSIONS]

    payload = {
        "schema": "docscout.dependency-audit/1",
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": "pip-audit",
        "source": "uv.lock (exported; PEP 440 local versions normalised)",
        # The artifact is only meaningful for the lockfile it was produced from. Recording
        # the digest lets a test fail when the lockfile moves and the scan was not re-run,
        # which is the difference between a stale report and a current one.
        "lockfile_sha256": sha256_file(REPO_ROOT / "uv.lock"),
        "runtime": runtime_result.as_dict(),
        "development_only": dev_result.as_dict(),
        "suppressed": suppressed,
        "gate": {
            "fails_on": "any advisory affecting a runtime dependency",
            "runtime_findings": len(runtime_findings),
            "passed": not runtime_findings,
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_JSON.write_text(json.dumps(payload, indent=2) + "\n")

    if not args.skip_sbom and generate_sbom(runtime):
        print(f"  SBOM     {SBOM_PATH.relative_to(REPO_ROOT)}")

    for label, result in (("runtime", runtime_result), ("dev-only", dev_result)):
        phantom = len(result.phantom_packages)
        suffix = f" ({phantom} phantom, not installed)" if phantom else ""
        print(
            f"  {label:<9} {result.packages_audited:>3} audited, "
            f"{result.packages_installed} installed{suffix}, "
            f"{len(result.findings)} advisories"
        )
        for finding in result.findings:
            fix = ", ".join(finding["fix_versions"]) or "no fix available"
            mark = "" if finding["installed"] else "  [phantom: not installed]"
            print(f"      {finding['package']}=={finding['version']} {finding['id']} ({fix}){mark}")
    for skip in runtime_result.skipped:
        print(f"  SKIPPED  {skip['package']}: {skip['reason']}")

    print(f"  report   {AUDIT_JSON.relative_to(REPO_ROOT)}")
    if runtime_findings:
        print(f"\n  FAIL: {len(runtime_findings)} advisory(ies) affect runtime dependencies.")
        return 1
    print("\n  PASS: no known advisory affects a runtime dependency.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
