"""Host allowlist for corpus fetching  -  SPEC FR-1 / CORPUS_SPEC C-1.

The allowlist is exactly three hosts. Anything else is a hard error, not a skip, and the
check runs before any socket is opened. Adding a host requires an ADR (C-1).

Two bypasses this has to survive, because an allowlist that only inspects the string a
caller handed it is decoration:

* **Userinfo.** `https://www.rbi.org.in@evil.example/x` has hostname `evil.example`.
  Parsing and comparing the *parsed hostname* defeats this; the explicit userinfo
  rejection below exists so the refusal names the real reason.
* **Redirects.** An allowed host can answer 302 to anywhere. `app.ingest.fetch` therefore
  disables automatic redirects and re-validates every hop through this module.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.ingest.errors import DisallowedHostError

#: CORPUS_SPEC.md §2. Exactly these three hosts; extending this set requires an ADR (C-1).
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "www.rbi.org.in",
        "rbidocs.rbi.org.in",
        "www.sebi.gov.in",
    }
)

#: Both regulators serve the corpus over TLS and Phase 0 fetched all 20 documents that
#: way, so plaintext is refused rather than silently downgraded.
ALLOWED_SCHEMES: frozenset[str] = frozenset({"https"})

#: The injection canary is authored locally, never fetched. It carries this scheme so that
#: a synthetic record can never be confused with something retrieved from a regulator.
SYNTHETIC_SCHEME = "synthetic"


def is_synthetic(url: str) -> bool:
    """True for the locally authored injection canary (`synthetic://…`)."""
    return urlsplit(url).scheme == SYNTHETIC_SCHEME


def assert_allowed(url: str) -> str:
    """Validate `url` against the allowlist and return its hostname.

    Raises `DisallowedHostError` for anything not served over HTTPS by one of the three
    permitted hosts. Pure and side-effect free, so it is always safe to call before a
    fetch  -  which is the point: FR-1's test asserts an off-list URL raises *before any
    network call*.
    """
    parts = urlsplit(url)

    if parts.scheme == SYNTHETIC_SCHEME:
        raise DisallowedHostError(
            f"{url!r} is a synthetic record and must never be fetched over the network; "
            "synthetic documents are injected from the local corpus only."
        )

    if parts.scheme not in ALLOWED_SCHEMES:
        raise DisallowedHostError(
            f"scheme {parts.scheme or '(none)'!r} is not permitted for {url!r}; "
            f"allowed: {', '.join(sorted(ALLOWED_SCHEMES))}"
        )

    if parts.username or parts.password:
        raise DisallowedHostError(
            f"{url!r} carries userinfo before the host, which is a classic allowlist "
            "bypass; refusing regardless of the host it parses to."
        )

    host = parts.hostname
    if not host:
        raise DisallowedHostError(f"{url!r} has no host component")

    if host not in ALLOWED_HOSTS:
        raise DisallowedHostError(
            f"host {host!r} is not in the CORPUS_SPEC §2 allowlist "
            f"({', '.join(sorted(ALLOWED_HOSTS))}). Adding a host requires an ADR (C-1)."
        )

    return host
