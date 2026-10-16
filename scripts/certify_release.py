#!/usr/bin/env python3
"""CLI driver for Regulated Release Certification Pipeline (FEAT-056).

Executable CI gate script for evaluating test evidence, structural coverage,
and mutation testing scores, generating a GSN Safety Case, and issuing a signed
Release Certificate. Exits 0 on certification pass, 1 on quality bar rejection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.models import CertifyReleaseRequest
from app.workflows.release_certifier import (
    ReleaseCertConfig,
    ReleaseCertifier,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Statutory Release Certification Gate & GSN Safety Case Generator",
    )
    parser.add_argument(
        "--commit-sha",
        required=True,
        help="40-character hexadecimal git commit SHA",
    )
    parser.add_argument(
        "--build-id",
        required=True,
        help="CI pipeline build identifier",
    )
    parser.add_argument(
        "--test-report",
        required=True,
        help="Path to JUnit XML or JSON test report",
    )
    parser.add_argument(
        "--coverage-report",
        required=True,
        help="Path to structural code coverage report (XML or JSON)",
    )
    parser.add_argument(
        "--mutation-report",
        default=None,
        help="Path to mutation testing score report (optional)",
    )
    parser.add_argument(
        "--sast-report",
        default=None,
        help="Path to SAST vulnerability scan report (optional)",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.85,
        help="Minimum required structural coverage ratio (default: 0.85)",
    )
    parser.add_argument(
        "--min-mutation",
        type=float,
        default=0.78,
        help="Minimum required mutation score ratio (default: 0.78)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional destination path for output ReleaseCertificate JSON",
    )

    args = parser.parse_args()

    config = ReleaseCertConfig(
        min_coverage=args.min_coverage,
        min_mutation_score=args.min_mutation,
    )
    certifier = ReleaseCertifier(config=config)

    try:
        request = CertifyReleaseRequest(
            commit_sha=args.commit_sha,
            build_id=args.build_id,
            test_report_path=args.test_report,
            coverage_report_path=args.coverage_report,
            mutation_report_path=args.mutation_report,
            sast_report_path=args.sast_report,
        )
    except Exception as err:
        sys.stderr.write(f"Validation Error: {err}\n")
        return 1

    try:
        certificate = certifier.certify_release(request)
    except Exception as err:
        sys.stderr.write(f"Certification Evaluation Error: {err}\n")
        return 1

    cert_json = certificate.model_dump(mode="json")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(cert_json, indent=2), encoding="utf-8")

    if certificate.is_certified:
        sys.stdout.write("=================================================================\n")
        sys.stdout.write("  REGULATED RELEASE CERTIFICATION: APPROVED\n")
        sys.stdout.write("=================================================================\n")
        sys.stdout.write(f"Certificate ID : {certificate.certificate_id}\n")
        sys.stdout.write(f"Commit SHA     : {certificate.commit_sha}\n")
        sys.stdout.write(f"Build ID       : {certificate.build_id}\n")
        sys.stdout.write(f"Signature      : {certificate.signature_sha256}\n")
        sys.stdout.write(f"Certified At   : {certificate.certified_at.isoformat()}\n")
        sys.stdout.write("GSN Safety Case: VALIDATED\n")
        return 0
    else:
        sys.stderr.write("=================================================================\n")
        sys.stderr.write("  REGULATED RELEASE CERTIFICATION: REJECTED\n")
        sys.stderr.write("=================================================================\n")
        sys.stderr.write(f"Commit SHA     : {certificate.commit_sha}\n")
        sys.stderr.write(f"Build ID       : {certificate.build_id}\n")
        sys.stderr.write("Quality Gate Rejection Reasons:\n")
        for reason in certificate.rejection_reasons:
            sys.stderr.write(f"  * {reason}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
