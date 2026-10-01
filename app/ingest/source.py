"""Where documents come from — the local corpus manifest.

`corpus/raw/manifest.json` is the corpus's provenance anchor and the only part of the
corpus git tracks (`.gitignore`, ADR-0001). It records identity, content hash, fetch
timestamp and HTTP status for every attempt, which is exactly the provenance FR-2 requires
`document_versions` to carry, so ingestion reads it rather than re-deriving any of it.

**Scope, stated plainly.** This module reads documents Phase 0 already fetched. Re-crawling
the regulators' listing pages — RBI's ASP.NET pagination and SEBI's detail-page-to-iframe
hop — is verified separately in `scripts/verify_corpus_fetch.py` and is not reimplemented
here. Ingesting from the manifest makes the pipeline deterministic and offline-reproducible
and avoids hammering two regulators on every run; `app.ingest.fetch` is what the crawling
path uses when documents are refreshed.

Two integrity checks run on every record, because a manifest is a claim about files and
claims decay:

* The bytes on disk are re-hashed and compared with the manifest's `sha256`. A mismatch
  means the file was edited or truncated after it was recorded, and ingesting it would
  attach Phase 0's provenance to different content.
* Every non-synthetic URL is re-validated against the host allowlist. Nothing is fetched
  here, but a document whose recorded origin is off-allowlist must not enter the index
  through the back door of a hand-edited manifest (FR-1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import REPO_ROOT
from app.ingest.allowlist import assert_allowed, is_synthetic
from app.ingest.errors import IngestError

DEFAULT_MANIFEST = REPO_ROOT / "corpus" / "raw" / "manifest.json"

#: Authority names for FR-14 citations. Derived from `source`, which the schema already
#: constrains to these three values, so this mapping cannot silently miss a case.
AUTHORITY_BY_SOURCE = {
    "RBI": "Reserve Bank of India",
    "SEBI": "Securities and Exchange Board of India",
    "SYNTHETIC": "DocScout (synthetic injection canary)",
}

_MEDIA_TYPE_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".htm": "text/html",
    ".html": "text/html",
    ".txt": "text/plain",
}


class ManifestError(IngestError):
    """The manifest is unusable or disagrees with the files on disk."""


@dataclass(frozen=True)
class SourceDocument:
    """One document to ingest, with the provenance FR-2 requires."""

    url: str
    source: str
    sha256: str
    content: bytes
    media_type: str
    fetch_ts: datetime
    http_status: int | None
    detail_page: str | None
    authority: str
    is_injection_canary: bool

    @property
    def bytes_len(self) -> int:
        return len(self.content)


def _media_type_for(path: Path) -> str:
    media_type = _MEDIA_TYPE_BY_SUFFIX.get(path.suffix.lower())
    if media_type is None:
        raise ManifestError(f"no media type known for {path.name!r}")
    return media_type


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[dict[str, object]]:
    """Read the manifest and return its document records."""
    if not path.is_file():
        raise ManifestError(
            f"{path} does not exist. Run `uv run python scripts/verify_corpus_fetch.py` "
            "to fetch the corpus first."
        )
    payload = json.loads(path.read_text())
    records = payload.get("documents")
    if not isinstance(records, list):
        raise ManifestError(f"{path} has no 'documents' list")
    return records


def iter_manifest_documents(
    path: Path = DEFAULT_MANIFEST,
    *,
    repo_root: Path = REPO_ROOT,
    limit: int | None = None,
) -> Iterator[SourceDocument]:
    """Yield every successfully fetched document recorded in the manifest.

    Records with `ok: false` are skipped: the manifest keeps failed attempts deliberately
    (C-22) and they have no payload to ingest.
    """
    yielded = 0
    for record in load_manifest(path):
        if limit is not None and yielded >= limit:
            return
        if not record.get("ok", False):
            continue

        url = str(record["url"])
        source = str(record["source"])
        if not is_synthetic(url):
            assert_allowed(url)

        local_path = repo_root / str(record["local_path"])
        if not local_path.is_file():
            raise ManifestError(
                f"{url} is recorded in the manifest but {local_path} is missing. The "
                "corpus payloads are not git-tracked; re-fetch before ingesting."
            )

        content = local_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        expected = str(record["sha256"])
        if digest != expected:
            raise ManifestError(
                f"{local_path.name} hashes to {digest} but the manifest records "
                f"{expected}. The file changed after it was fetched; ingesting it would "
                "attach recorded provenance to different content."
            )

        yield SourceDocument(
            url=url,
            source=source,
            sha256=digest,
            content=content,
            media_type=_media_type_for(local_path),
            fetch_ts=datetime.fromisoformat(str(record["fetch_ts"])),
            http_status=(
                int(str(record["http_status"])) if record.get("http_status") is not None else None
            ),
            detail_page=(
                str(record["detail_page"]) if record.get("detail_page") is not None else None
            ),
            authority=AUTHORITY_BY_SOURCE.get(source, source),
            is_injection_canary=bool(record.get("is_injection_canary", False)),
        )
        yielded += 1
