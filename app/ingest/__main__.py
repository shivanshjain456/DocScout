"""Ingestion CLI — `python -m app.ingest`, or `make ingest`.

Ingestion is a CLI entrypoint and never an API route: nothing in `app/api/` may trigger it
(ARCHITECTURE §3.1, OUT-5). A corpus rebuild is an operator action with a cost and a
duration, not something an unauthenticated request can start.

The first thing this does, before the database and before any network call, is refuse to
run if deploy credentials are in the environment (SECURITY S-4, FR-6).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import REPO_ROOT, database_url
from app.ingest.embed import Embedder
from app.ingest.errors import CredentialBleedError, IngestError
from app.ingest.guards import assert_no_deploy_credentials
from app.ingest.pipeline import (
    DocumentResult,
    run_ingest,
    verify_stored_chunks,
)
from app.ingest.source import DEFAULT_MANIFEST, iter_manifest_documents
from app.ingest.store import connect, row_counts

DEFAULT_REPORT_ROOT = REPO_ROOT / "corpus" / "reports"


def display_path(path: Path) -> str:
    """Show a path relative to the repo when it is inside it, absolute when it is not.

    `Path.relative_to` raises for any path outside the repository *and* for a relative
    path that does not literally start with the repo prefix — which is what a user-supplied
    `--report-dir docs/...` is. Resolving first makes the common case relative; the
    fallback keeps an out-of-tree report directory from crashing a run that has already
    written all of its data.
    """
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def _progress(result: DocumentResult) -> None:
    mark = "FAIL" if result.status == "failed" else (result.action or "")
    name = result.url if len(result.url) <= 72 else result.url[:69] + "..."
    line = f"  {mark:<26} {name}"
    if result.chunks:
        line += f"  ({result.chunks} chunks, {result.elapsed_ms} ms)"
    elif result.status == "failed":
        line += f"\n      {result.detail}"
    print(line, flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingest",
        description="Ingest the DocScout corpus into Postgres.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "verify", "status"),
        help="run: ingest. verify: re-check stored offsets. status: row counts only.",
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST, help="corpus manifest to read"
    )
    parser.add_argument("--limit", type=int, default=None, help="ingest at most N documents")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="extract, chunk and embed but write nothing",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="where to write ingest.json (default: corpus/reports/<UTC timestamp>/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # SECURITY S-4 / FR-6, first, before the database and before any network call.
    try:
        assert_no_deploy_credentials()
    except CredentialBleedError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2

    try:
        conn = connect(database_url())
    except Exception as exc:  # noqa: BLE001 - surface any connection failure as exit 1
        print(f"could not connect to the database: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "status":
            for name, count in row_counts(conn).items():
                print(f"  {name:<20} {count}")
            return 0

        try:
            documents = list(iter_manifest_documents(args.manifest, limit=args.limit))
        except IngestError as exc:
            print(f"corpus is not ingestable: {exc}", file=sys.stderr)
            return 1

        if args.command == "verify":
            print(f"verifying stored chunks for {len(documents)} manifest documents...")
            verification = verify_stored_chunks(documents, conn)
            print(
                f"  versions checked {verification.versions_checked}, "
                f"chunks checked {verification.chunks_checked}"
            )
            if verification.missing_versions:
                print(f"  NOT STORED: {len(verification.missing_versions)}")
                for url in verification.missing_versions:
                    print(f"    {url}")
            if verification.offset_mismatches:
                print(f"  FR-7 MISMATCHES: {len(verification.offset_mismatches)}")
                for ref in verification.offset_mismatches:
                    print(f"    {ref}")
                return 1
            if verification.missing_versions:
                return 1
            print("  OK: every stored chunk's offsets re-extract to its stored text (FR-7)")
            return 0

        embedder = Embedder()
        print(
            f"ingesting {len(documents)} documents "
            f"({'dry run, nothing will be written' if args.dry_run else 'writing'})..."
        )
        report = run_ingest(documents, conn, embedder, dry_run=args.dry_run, on_progress=_progress)

        report_dir = args.report_dir or (
            DEFAULT_REPORT_ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        path = report.write(report_dir)

        totals = report.totals
        print()
        print(f"  documents seen   {totals['documents_seen']}")
        print(f"  chunks written   {totals['chunks_written']}")
        for key in ("inserted", "superseded", "skipped_unchanged", "skipped_duplicate_content"):
            if totals.get(key):
                print(f"  {key:<16} {totals[key]}")
        if totals["failed"]:
            print(f"  FAILED           {totals['failed']}")
        print(f"  rows before      {report.counts_before}")
        print(f"  rows after       {report.counts_after}")
        print(f"  duration         {report.duration_s:.1f}s")
        print(f"  report           {display_path(path)}")

        return 1 if totals["failed"] else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
