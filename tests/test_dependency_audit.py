"""Tests for the dependency audit and its artifacts.

Split deliberately. The scan itself needs the network to reach the advisory database, so
it is not run here — a test suite that fails when PyPI is slow trains people to ignore it.
What *is* tested is everything that can be wrong without the network: the normalisation
that decides which packages get audited at all, the rule that separates a real finding
from a phantom one, the suppression policy, and whether the committed artifacts still
describe the current lockfile.

The scan is verified by `make audit-deps` and its committed output; `docs/security/` holds
the evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_dependencies import (  # noqa: E402 - needs the path above
    LOCAL_VERSION,
    SUPPRESSIONS,
    normalise,
)

AUDIT = REPO_ROOT / "docs" / "security" / "dependency-audit.json"
SBOM = REPO_ROOT / "docs" / "security" / "sbom.cdx.json"


# --- local version normalisation --------------------------------------------------------
@pytest.mark.parametrize(
    ("pinned", "expected"),
    [
        ("torch==2.14.1+cpu", "torch==2.14.1"),
        ("torch==2.14.1+cu121", "torch==2.14.1"),
        ("some-pkg==1.0.0+local.build.7", "some-pkg==1.0.0"),
    ],
)
def test_local_version_identifiers_are_stripped(pinned: str, expected: str) -> None:
    """Without this, the largest dependency in the project is silently never scanned.

    `uv.lock` pins `torch==2.14.1+cpu`, a wheel from the PyTorch CPU index that does not
    exist on PyPI. pip-audit reports it as unauditable and carries on printing "No known
    vulnerabilities found", which is true and deeply misleading.
    """
    match = LOCAL_VERSION.match(pinned)
    assert match is not None, f"{pinned} should have matched"
    assert match.group(1) == expected


@pytest.mark.parametrize(
    "pinned", ["fastapi==0.142.2", "numpy==2.1.0", "pkg==1.0.0rc1", "pkg==1.0.0.post1"]
)
def test_ordinary_pins_are_left_alone(pinned: str) -> None:
    """Pre-release and post-release segments are not local versions and must survive."""
    assert LOCAL_VERSION.match(pinned) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("nvidia_cublas", "nvidia-cublas"),
        ("Nvidia.Cublas", "nvidia-cublas"),
        ("pip__audit", "pip-audit"),
        ("already-normal", "already-normal"),
    ],
)
def test_names_are_pep503_normalised(raw: str, expected: str) -> None:
    """Phantom detection compares names; an unnormalised compare invents phantoms."""
    assert normalise(raw) == expected


# --- suppression policy -----------------------------------------------------------------
def test_every_suppression_is_justified_and_expires() -> None:
    """A suppression without an expiry is a permanent blind spot with a comment on it."""
    for advisory_id, entry in SUPPRESSIONS.items():
        assert advisory_id.strip(), "suppression key must be an advisory id"
        for field in ("package", "reason", "review_by"):
            assert entry.get(field), f"{advisory_id} is missing '{field}'"
        assert len(str(entry["reason"])) > 30, f"{advisory_id}: reason is not a justification"


# --- the committed artifacts ------------------------------------------------------------
def test_audit_artifact_exists_and_records_a_verdict() -> None:
    assert AUDIT.is_file(), "run `make audit-deps`"
    report = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert report["schema"] == "docscout.dependency-audit/1"
    assert report["tool"] == "pip-audit"
    assert report["gate"]["fails_on"]
    assert isinstance(report["gate"]["passed"], bool)


def test_audit_artifact_matches_the_current_lockfile() -> None:
    """Fails when uv.lock moved and the scan was not re-run.

    An audit is a statement about a specific dependency set. Against a changed lockfile it
    is not a weaker claim, it is a claim about something else.
    """
    from app.config import sha256_file

    report = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert report["lockfile_sha256"] == sha256_file(REPO_ROOT / "uv.lock"), (
        "docs/security/dependency-audit.json describes a different uv.lock. "
        "Run `make audit-deps` and commit the result."
    )


def test_recorded_runtime_findings_agree_with_the_verdict() -> None:
    """Guards against an artifact that lists advisories while claiming to have passed."""
    report = json.loads(AUDIT.read_text(encoding="utf-8"))
    blocking = [
        f for f in report["runtime"]["findings"] if f["installed"] and f["id"] not in SUPPRESSIONS
    ]
    assert report["gate"]["runtime_findings"] == len(blocking)
    assert report["gate"]["passed"] is (not blocking)


def test_phantom_packages_are_recorded_not_silently_dropped() -> None:
    """Stripping `+cpu` makes pip-audit read upstream torch metadata, which lists CUDA
    packages a CPU build never installs. They must be named, so a finding against one is
    recognisable as inapplicable rather than mysterious."""
    report = json.loads(AUDIT.read_text(encoding="utf-8"))
    phantom = report["runtime"]["phantom_packages"]
    assert isinstance(phantom, list)
    assert report["runtime"]["packages_audited"] >= report["runtime"]["packages_installed"]
    if phantom:
        assert any(p.startswith(("nvidia-", "cuda-")) for p in phantom), phantom


def test_sbom_is_valid_cyclonedx_and_covers_the_audited_set() -> None:
    assert SBOM.is_file(), "run `make audit-deps`"
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"]
    components = sbom["components"]
    assert components, "SBOM lists no components"
    report = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert len(components) == report["runtime"]["packages_audited"]
    for component in components[:5]:
        assert component["name"] and component["version"]


def test_sbom_contains_the_direct_runtime_dependencies() -> None:
    """A bill of materials that omits what the application imports is not one."""
    names = {
        normalise(c["name"]) for c in json.loads(SBOM.read_text(encoding="utf-8"))["components"]
    }
    for required in ("fastapi", "psycopg", "sentence-transformers", "pgvector", "torch"):
        assert required in names, f"{required} missing from the SBOM"


def test_removed_vulnerable_packages_are_absent() -> None:
    """Regression guard for the finding this scanner was built and immediately caught.

    `ragas` was declared but imported nowhere, and dragged in `diskcache`. Both carried
    advisories with no fix available (CVE-2026-6587 and CVE-2025-69872, the latter an
    arbitrary-code-execution issue in pickle-based cache deserialisation). The remediation
    was removal, since U-1 had already withdrawn the judge layer that was the only reason
    to depend on them. This fails if either returns.
    """
    names = {
        normalise(c["name"]) for c in json.loads(SBOM.read_text(encoding="utf-8"))["components"]
    }
    assert "ragas" not in names
    assert "diskcache" not in names


# --- the SBOM must be reviewable, which means deterministic -----------------------------
def test_sbom_has_no_volatile_timestamp() -> None:
    """CycloneDX stamps a generation time by default.

    Committed, that makes the file change on every run even when no dependency moved: the
    diff becomes useless for review and the CI staleness check can never pass.
    """
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    assert "timestamp" not in sbom.get("metadata", {})


def test_sbom_serial_number_is_derived_from_the_component_set() -> None:
    """A random serial per run defeats the point of committing the file."""
    import uuid as uuid_module

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from audit_dependencies import SBOM_NAMESPACE

    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    fingerprint = "\n".join(
        sorted(f"{c.get('name')}=={c.get('version')}" for c in sbom["components"])
    )
    expected = f"urn:uuid:{uuid_module.uuid5(SBOM_NAMESPACE, fingerprint)}"
    assert sbom["serialNumber"] == expected, (
        "SBOM serial does not match its components; regenerate with `make audit-deps`"
    )


def test_sbom_refs_identify_packages_not_random_numbers() -> None:
    """cyclonedx-python-lib emits refs like `BomRef.74974887.30280564`, which differ on
    every run. A bom-ref is supposed to identify the component, so they are re-keyed on
    the purl."""
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    refs = [c["bom-ref"] for c in sbom["components"] if "bom-ref" in c]
    assert refs, "no bom-refs present"
    assert all(r.startswith("pkg:pypi/") for r in refs), [r for r in refs if "pkg:" not in r][:3]
    assert len(set(refs)) == len(refs), "bom-refs are not unique"


def test_sbom_dependency_graph_references_resolve() -> None:
    """Rewriting refs must not leave the graph pointing at identifiers that no longer exist."""
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    known = {c["bom-ref"] for c in sbom["components"] if "bom-ref" in c}
    for node in sbom.get("dependencies", []):
        for target in node.get("dependsOn", []):
            assert target in known, f"dangling dependency reference: {target}"


def test_sbom_components_are_sorted() -> None:
    """Stable ordering is what makes a dependency change show up as one line in review."""
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    pairs = [(c["name"], c["version"]) for c in sbom["components"]]
    assert pairs == sorted(pairs)
