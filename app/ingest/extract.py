"""Text extraction and the short-extraction guard — ARCHITECTURE §3.1, FR-3 / C-11.

`pypdf` for PDFs and `trafilatura` for HTML, matching what Phase 0 verified on all 20
fetched documents (`scripts/verify_corpus_fetch.py`).

The guard is the important part of this module. CORPUS_SPEC K-17 records the single most
dangerous failure mode in the pipeline: a SEBI circular's detail page extracts roughly 227
characters of navigation furniture and *looks like a successful fetch*. HTTP 200, non-empty
text, no exception. Without a floor on extracted length that document enters the index as a
stub that can never answer anything, and nothing anywhere reports a problem.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.ingest.clean import clean_char_count
from app.ingest.errors import ExtractionError, ShortExtractionError

#: FR-3 / C-11. The threshold Phase 0 used, which all 20 real documents cleared.
MIN_CLEAN_CHARS = 500

_WHITESPACE_RUN = re.compile(r"\s+")


def normalise_whitespace(text: str) -> str:
    """Collapse whitespace runs to single spaces and trim — the canonical document text.

    This is the one transformation in the pipeline that is deliberately *not*
    offset-preserving, which is why it lives in extraction rather than in
    `app.ingest.clean`. Character offsets are assigned after it and index into its output,
    so the ordering is load-bearing: normalise first, then never move a character again.

    It is not cosmetic. A PDF extracted page by page carries hard line breaks mid-sentence
    wherever the original had a line box, so without this a chunk boundary search for a
    space would treat layout as structure, and a citation's quoted span would be peppered
    with newlines that exist nowhere in the document a reader sees.

    It is also the definition Phase 0 used (`scripts/verify_corpus_fetch.py`): the
    `corpus/raw/*.txt` extractions and every `char_count` in the manifest are the output
    of exactly this expression, and ADR-0003's chunking sweep measured this text. Changing
    it would silently invalidate that evidence, so `tests/test_ingest.py` pins extraction
    against the manifest's recorded counts.
    """
    return _WHITESPACE_RUN.sub(" ", text).strip()


@dataclass(frozen=True)
class Extraction:
    """Canonical document text plus the provenance needed by `document_versions`.

    `text` is always whitespace-normalised: every constructor below goes through
    `normalise_whitespace`, so there is no path that yields un-normalised text and no way
    for an offset to be assigned against the wrong string.
    """

    text: str
    pages: int | None
    extractor: str


def extract_pdf(data: bytes) -> Extraction:
    """Extract text from PDF bytes with pypdf, joining pages with newlines."""
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide, undocumented range
        raise ExtractionError(
            f"pypdf could not read the document: {type(exc).__name__}: {exc}"
        ) from exc
    return Extraction(
        text=normalise_whitespace("\n".join(pages)), pages=len(pages), extractor="pypdf"
    )


def extract_html(data: bytes) -> Extraction:
    """Extract the main body of an HTML page with trafilatura."""
    import trafilatura

    try:
        decoded = data.decode("utf-8", errors="replace")
        text = trafilatura.extract(decoded) or ""
    except Exception as exc:  # noqa: BLE001 - trafilatura wraps several parser backends
        raise ExtractionError(
            f"trafilatura could not read the document: {type(exc).__name__}: {exc}"
        ) from exc
    return Extraction(text=normalise_whitespace(text), pages=None, extractor="trafilatura")


def extract_plain_text(data: bytes) -> Extraction:
    """Decode an already-textual payload.

    Used only for the locally authored injection canary, which has no source document to
    parse. Recording the extractor as `literal` keeps that visible in the database rather
    than letting a synthetic record claim it came out of pypdf.
    """
    return Extraction(
        text=normalise_whitespace(data.decode("utf-8", errors="replace")),
        pages=None,
        extractor="literal",
    )


def extract(data: bytes, *, media_type: str) -> Extraction:
    """Dispatch to the extractor for `media_type`."""
    normalised = media_type.split(";")[0].strip().lower()
    if normalised == "application/pdf":
        return extract_pdf(data)
    if normalised in {"text/html", "application/xhtml+xml"}:
        return extract_html(data)
    if normalised == "text/plain":
        return extract_plain_text(data)
    raise ExtractionError(f"no extractor for media type {media_type!r}")


def assert_extraction_long_enough(
    cleaned_text: str, *, url: str, minimum: int = MIN_CLEAN_CHARS
) -> int:
    """Enforce FR-3 on cleaned text and return the clean character count.

    Counts non-whitespace characters. A scanned or wholly Devanagari PDF extracts plenty
    of characters, every one of which `clean_preserving_offsets` blanks to a space; a
    total-length test would pass it as a large successful extraction whose stored text is
    empty, which is exactly the silent data loss M2 names as its main corpus risk.
    """
    count = clean_char_count(cleaned_text)
    if count < minimum:
        raise ShortExtractionError(
            f"{url} extracted {count} clean characters, below the {minimum} floor "
            "(FR-3, CORPUS_SPEC C-11). This is the stub-page failure mode: the fetch "
            "succeeded but the document carries no retrievable content."
        )
    return count
