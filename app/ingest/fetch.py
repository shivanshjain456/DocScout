"""HTTP fetching for the corpus  -  FR-1 / CORPUS_SPEC C-1, §2.1.

Phase 0 discovered the access behaviour this has to respect (CORPUS_SPEC §2.1): RBI embeds
absolute PDF links in plain HTML, SEBI answers 403 to directory-style paths but 200 to
individual documents, and every request carries a descriptive User-Agent.

The security-relevant part is redirect handling. `assert_allowed` on the URL a caller
passes in is worth little on its own, because an allowed host can answer `302 Location:
https://evil.example/x` and httpx will follow it by default, fetching off-allowlist content
through a check that passed. Automatic redirects are therefore disabled and each hop is
re-validated through the same allowlist before it is followed.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.ingest.allowlist import assert_allowed
from app.ingest.errors import IngestError

#: Identifies the crawler and gives a contact address, matching the User-Agent Phase 0
#: used successfully against both regulators (`scripts/verify_corpus_fetch.py`).
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36 (DocScout research crawler; contact: setup@docscout.local)"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf",
}

DEFAULT_TIMEOUT = 30.0
MAX_REDIRECTS = 5

#: Refuse absurdly large payloads rather than reading them into memory. The largest real
#: corpus document is well under 1 MiB; this is a backstop against a pathological or
#: hostile response, not a tuning parameter.
MAX_CONTENT_BYTES = 64 * 1024 * 1024


class FetchError(IngestError):
    """A fetch failed for a reason that is not an allowlist violation."""


@dataclass(frozen=True)
class FetchResult:
    """A successfully fetched payload and the provenance FR-2 requires recording."""

    url: str
    status_code: int
    content: bytes
    media_type: str

    @property
    def bytes_len(self) -> int:
        return len(self.content)


def fetch_url(
    url: str,
    *,
    client: httpx.Client,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
) -> FetchResult:
    """Fetch `url`, enforcing the host allowlist on the request and on every redirect.

    Raises `DisallowedHostError` before opening any socket if the URL is off-allowlist,
    and again mid-flight if a redirect tries to leave it.
    """
    current = url
    for _ in range(max_redirects + 1):
        assert_allowed(current)
        response = client.get(
            current, headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=False
        )

        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise FetchError(f"{current} returned {response.status_code} with no Location")
            # Resolve relative redirects against the current URL before re-validating,
            # so a relative Location cannot sidestep the host check.
            current = urljoin(current, location)
            continue

        if response.status_code != httpx.codes.OK:
            raise FetchError(f"{current} returned HTTP {response.status_code}")

        if len(response.content) > MAX_CONTENT_BYTES:
            raise FetchError(
                f"{current} returned {len(response.content)} bytes, over the "
                f"{MAX_CONTENT_BYTES} byte ceiling"
            )

        return FetchResult(
            url=current,
            status_code=response.status_code,
            content=response.content,
            media_type=response.headers.get("content-type", "application/octet-stream"),
        )

    raise FetchError(f"{url} exceeded {max_redirects} redirects")
