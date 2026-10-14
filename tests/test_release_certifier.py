"""Unit, integration, and performance test suite for Regulated Release Certification Pipeline (FEAT-056).

Validates:
1. 10 simulated deployment builds with varying quality bar results:
   - Build 1: Golden clean build (100% test pass, 92% coverage, 85% mutation, 0 SAST).
   - Build 2: Failing tests in JUnit XML report (rejection with failure count).
   - Build 3: Coverage regression below 85% threshold (rejection).
   - Build 4: Mutation score below 78% minimum threshold (rejection).
   - Build 5: Critical/High SAST security vulnerabilities (rejection).
   - Build 6: Compound failure (failed tests and low coverage).
   - Build 7: Format parity: JSON test report vs XML JUnit test report.
   - Build 8: Format parity: JSON coverage report vs Cobertura XML report.
   - Build 9: Input validation: invalid commit SHA (non-40-hex rejected).
   - Build 10: Input validation: missing or empty report paths.
2. CLI verification: scripts/certify_release.py exits 0 on pass, 1 on failure.
3. Cryptographic attestation: SHA-256 signature sensitivity to GSN mutation.
4. Performance benchmark: compilation and signing latency <= 1.5 seconds.
5. REST API endpoints: POST /v1/compliance/certify-release and GET certificate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.models import CertifyReleaseRequest
from app.api.security import load_keys
from app.workflows.release_certifier import (
    ReleaseCertConfig,
    ReleaseCertifier,
    compute_safety_case_signature,
    parse_coverage_report,
    parse_test_report,
)
from tests.conftest import PRIMARY_KEY, auth

VALID_SHA = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    rep_dir = tmp_path / "ci_reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    return rep_dir


@pytest.fixture
def clean_reports(reports_dir: Path) -> dict[str, str]:
    test_xml = reports_dir / "junit.xml"
    test_xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="core-suite" tests="45" failures="0" errors="0" skipped="1">
    <testcase classname="test_payments" name="test_switch" time="0.05" />
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    cov_json = reports_dir / "coverage.json"
    cov_json.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": 91.5,
                    "covered_lines": 915,
                    "num_statements": 1000,
                }
            }
        ),
        encoding="utf-8",
    )

    mut_json = reports_dir / "mutation.json"
    mut_json.write_text(
        json.dumps({"mutation_score": 0.84, "killed": 84, "total": 100}),
        encoding="utf-8",
    )

    sast_json = reports_dir / "sast.json"
    sast_json.write_text(
        json.dumps({"critical_count": 0, "high_count": 0, "total_vulnerabilities": 0}),
        encoding="utf-8",
    )

    return {
        "test": str(test_xml),
        "coverage": str(cov_json),
        "mutation": str(mut_json),
        "sast": str(sast_json),
    }


# --- Build 1: Golden Clean Build Verification ---


def test_build_1_golden_clean_build_certified(
    clean_reports: dict[str, str], tmp_path: Path
) -> None:
    config = ReleaseCertConfig(
        min_mutation_score=0.78,
        min_coverage=0.85,
        fallback_dir=str(tmp_path / "certs"),
    )
    certifier = ReleaseCertifier(config=config)

    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-prod-20261014-01",
        test_report_path=clean_reports["test"],
        coverage_report_path=clean_reports["coverage"],
        mutation_report_path=clean_reports["mutation"],
        sast_report_path=clean_reports["sast"],
    )

    cert = certifier.certify_release(req)

    assert cert.is_certified
    assert len(cert.rejection_reasons) == 0
    assert cert.commit_sha == VALID_SHA
    assert cert.build_id == "build-prod-20261014-01"
    assert len(cert.signature_sha256) == 64

    # Validate GSN structure
    gsn = cert.gsn_safety_case_json
    assert gsn["root_goal"]["id"] == "G1"
    assert gsn["root_goal"]["is_satisfied"] is True
    assert len(gsn["sub_goals"]) == 4


# --- Build 2: Failing Tests in JUnit Report ---


def test_build_2_failing_tests_rejected(clean_reports: dict[str, str], reports_dir: Path) -> None:
    bad_test = reports_dir / "junit_failed.xml"
    bad_test.write_text(
        """<testsuite name="failing-suite" tests="50" failures="3" errors="1" skipped="0">
  <testcase name="test_settlement"><failure message="AssertionError" /></testcase>
</testsuite>""",
        encoding="utf-8",
    )

    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-failed-tests",
        test_report_path=str(bad_test),
        coverage_report_path=clean_reports["coverage"],
        mutation_report_path=clean_reports["mutation"],
    )

    cert = certifier.certify_release(req)
    assert not cert.is_certified
    assert any("3 failures" in r for r in cert.rejection_reasons)


# --- Build 3: Coverage Regression Below 85% ---


def test_build_3_coverage_regression_rejected(
    clean_reports: dict[str, str], reports_dir: Path
) -> None:
    low_cov = reports_dir / "low_cov.json"
    low_cov.write_text(
        json.dumps({"totals": {"percent_covered": 73.4}}),
        encoding="utf-8",
    )

    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-low-cov",
        test_report_path=clean_reports["test"],
        coverage_report_path=str(low_cov),
    )

    cert = certifier.certify_release(req)
    assert not cert.is_certified
    assert any("73.4%" in r for r in cert.rejection_reasons)


# --- Build 4: Mutation Score Below 78% ---


def test_build_4_low_mutation_score_rejected(
    clean_reports: dict[str, str], reports_dir: Path
) -> None:
    low_mut = reports_dir / "low_mut.json"
    low_mut.write_text(
        json.dumps({"mutation_score": 0.64}),
        encoding="utf-8",
    )

    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-low-mut",
        test_report_path=clean_reports["test"],
        coverage_report_path=clean_reports["coverage"],
        mutation_report_path=str(low_mut),
    )

    cert = certifier.certify_release(req)
    assert not cert.is_certified
    assert any("64.0%" in r for r in cert.rejection_reasons)


# --- Build 5: Critical/High SAST Vulnerabilities ---


def test_build_5_sast_vulnerabilities_rejected(
    clean_reports: dict[str, str], reports_dir: Path
) -> None:
    sast_bad = reports_dir / "sast_bad.json"
    sast_bad.write_text(
        json.dumps({"critical_count": 2, "high_count": 1}),
        encoding="utf-8",
    )

    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-sast-cve",
        test_report_path=clean_reports["test"],
        coverage_report_path=clean_reports["coverage"],
        sast_report_path=str(sast_bad),
    )

    cert = certifier.certify_release(req)
    assert not cert.is_certified
    assert any("2 critical and 1 high" in r for r in cert.rejection_reasons)


# --- Build 6: Compound Failure ---


def test_build_6_compound_failures_recorded(
    reports_dir: Path,
) -> None:
    fail_test = reports_dir / "fail_test.json"
    fail_test.write_text(
        json.dumps({"summary": {"total": 10, "failed": 2, "errors": 0}}),
        encoding="utf-8",
    )
    low_cov = reports_dir / "low_cov_xml.xml"
    low_cov.write_text(
        '<coverage line-rate="0.65" lines-valid="100" lines-covered="65" />',
        encoding="utf-8",
    )

    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-compound",
        test_report_path=str(fail_test),
        coverage_report_path=str(low_cov),
    )

    cert = certifier.certify_release(req)
    assert not cert.is_certified
    assert len(cert.rejection_reasons) >= 2


# --- Build 7: Test Report Parity (JSON vs XML) ---


def test_build_7_test_report_format_parity(reports_dir: Path) -> None:
    xml_path = reports_dir / "suite.xml"
    xml_path.write_text(
        '<testsuite tests="20" failures="0" errors="0" skipped="2" />',
        encoding="utf-8",
    )
    json_path = reports_dir / "suite.json"
    json_path.write_text(
        json.dumps({"summary": {"total": 20, "failed": 0, "errors": 0, "skipped": 2}}),
        encoding="utf-8",
    )

    xml_metrics = parse_test_report(xml_path)
    json_metrics = parse_test_report(json_path)

    assert xml_metrics["total"] == json_metrics["total"]
    assert xml_metrics["is_clean"] == json_metrics["is_clean"] is True


# --- Build 8: Coverage Report Parity (Cobertura XML vs JSON) ---


def test_build_8_coverage_format_parity(reports_dir: Path) -> None:
    cobertura_xml = reports_dir / "cobertura.xml"
    cobertura_xml.write_text(
        '<coverage line-rate="0.885" lines-valid="200" lines-covered="177" />',
        encoding="utf-8",
    )
    cov_json = reports_dir / "coverage_totals.json"
    cov_json.write_text(
        json.dumps({"totals": {"percent_covered": 88.5}}),
        encoding="utf-8",
    )

    xml_cov = parse_coverage_report(cobertura_xml)
    json_cov = parse_coverage_report(cov_json)

    assert abs(xml_cov["coverage_ratio"] - json_cov["coverage_ratio"]) < 0.001
    assert xml_cov["percent_covered"] == json_cov["percent_covered"] == 88.5


# --- Build 9: Invalid Commit SHA Validation ---


def test_build_9_invalid_commit_sha_rejected(clean_reports: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        CertifyReleaseRequest(
            commit_sha="not-a-valid-40-char-hex-sha",
            build_id="build-bad-sha",
            test_report_path=clean_reports["test"],
            coverage_report_path=clean_reports["coverage"],
        )


# --- Build 10: Missing Report Files ---


def test_build_10_missing_report_file_raises(clean_reports: dict[str, str]) -> None:
    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-missing-file",
        test_report_path="non_existent_file_path_xyz.xml",
        coverage_report_path=clean_reports["coverage"],
    )

    with pytest.raises(FileNotFoundError):
        certifier.certify_release(req)


# --- Cryptographic Attestation Sensitivity ---


def test_cryptographic_signature_tamper_sensitivity(
    clean_reports: dict[str, str],
) -> None:
    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-tamper-check",
        test_report_path=clean_reports["test"],
        coverage_report_path=clean_reports["coverage"],
    )

    cert = certifier.certify_release(req)
    sig1 = cert.signature_sha256

    # Tamper with GSN statement and recompute signature
    tampered_gsn = dict(cert.gsn_safety_case_json)
    tampered_gsn["root_goal"] = dict(tampered_gsn["root_goal"])
    tampered_gsn["root_goal"]["statement"] = "TAMPERED STATUTORY STATEMENT"

    sig2 = compute_safety_case_signature(
        tampered_gsn, commit_sha=VALID_SHA, build_id="build-tamper-check"
    )
    assert sig1 != sig2


# --- Performance Benchmark: <= 1.5 seconds ---


def test_certification_latency_benchmark(clean_reports: dict[str, str]) -> None:
    certifier = ReleaseCertifier()
    req = CertifyReleaseRequest(
        commit_sha=VALID_SHA,
        build_id="build-perf-test",
        test_report_path=clean_reports["test"],
        coverage_report_path=clean_reports["coverage"],
    )

    t0 = time.perf_counter()
    cert = certifier.certify_release(req)
    elapsed = time.perf_counter() - t0

    assert cert.is_certified
    # Performance limit from specification: <= 1.5 seconds
    assert elapsed <= 1.5, f"Compilation took {elapsed:.4f}s (limit: 1.5s)"


# --- CLI Script Execution Verification ---


def test_cli_script_execution(clean_reports: dict[str, str], tmp_path: Path) -> None:
    script_path = str(Path(__file__).resolve().parent.parent / "scripts" / "certify_release.py")
    out_file = tmp_path / "cli_cert.json"

    # Pass case -> exit 0
    cmd_pass = [
        sys.executable,
        script_path,
        "--commit-sha",
        VALID_SHA,
        "--build-id",
        "cli-build-pass",
        "--test-report",
        clean_reports["test"],
        "--coverage-report",
        clean_reports["coverage"],
        "--output",
        str(out_file),
    ]

    res_pass = subprocess.run(cmd_pass, capture_output=True, text=True)
    assert res_pass.returncode == 0
    assert "REGULATED RELEASE CERTIFICATION: APPROVED" in res_pass.stdout
    assert out_file.exists()

    # Fail case (low coverage threshold 0.99) -> exit 1
    cmd_fail = [
        sys.executable,
        script_path,
        "--commit-sha",
        VALID_SHA,
        "--build-id",
        "cli-build-fail",
        "--test-report",
        clean_reports["test"],
        "--coverage-report",
        clean_reports["coverage"],
        "--min-coverage",
        "0.99",
    ]

    res_fail = subprocess.run(cmd_fail, capture_output=True, text=True)
    assert res_fail.returncode == 1
    assert "REGULATED RELEASE CERTIFICATION: REJECTED" in res_fail.stderr


# --- REST API Endpoints Integration ---


def test_api_certify_release_endpoint(
    test_client: TestClient, api_headers: dict[str, str], clean_reports: dict[str, str]
) -> None:
    payload = {
        "commit_sha": VALID_SHA,
        "build_id": "api-build-001",
        "test_report_path": clean_reports["test"],
        "coverage_report_path": clean_reports["coverage"],
        "mutation_report_path": clean_reports["mutation"],
    }

    resp = test_client.post(
        "/v1/compliance/certify-release?tenant_id=default",
        json=payload,
        headers=api_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_certified"] is True
    assert data["commit_sha"] == VALID_SHA
    assert "signature_sha256" in data
    cert_id = data["certificate_id"]

    # GET /v1/compliance/release-certificates/{certificate_id}
    get_resp = test_client.get(
        f"/v1/compliance/release-certificates/{cert_id}?tenant_id=default",
        headers=api_headers,
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["certificate_id"] == cert_id


def test_api_certify_release_strict_mode_rejection(
    test_client: TestClient,
    api_headers: dict[str, str],
    clean_reports: dict[str, str],
    reports_dir: Path,
) -> None:
    # Low coverage
    bad_cov = reports_dir / "bad_cov.json"
    bad_cov.write_text(
        json.dumps({"totals": {"percent_covered": 40.0}}),
        encoding="utf-8",
    )

    payload = {
        "commit_sha": VALID_SHA,
        "build_id": "api-build-fail",
        "test_report_path": clean_reports["test"],
        "coverage_report_path": str(bad_cov),
    }

    # In strict mode, fails with 422
    resp = test_client.post(
        "/v1/compliance/certify-release?enforce_strict=true&tenant_id=default",
        json=payload,
        headers=api_headers,
    )
    assert resp.status_code == 422
    assert "Release certification rejected" in resp.text
