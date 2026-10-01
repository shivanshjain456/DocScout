"""Chunk geometry — ADR-0003, serving FR-7 and ADR-0002's 512-token ceiling.

Fixed-width 1,000 characters with 150 characters of overlap, broken at whitespace where
one is available in the overlap zone. ADR-0003 chose this over 800 and 1,200 and over
clause-aware splitting; the measurements are in `docs/decisions/evidence/u8-chunking-sweep.json`.

Three invariants this module is responsible for, all checked rather than assumed:

1. **FR-7.** `text[chunk.char_start:chunk.char_end] == chunk.text` for every chunk. The
   natural way to break this is to strip whitespace off a window without moving its start
   offset by the same amount, which is why `_window_body` returns both together and
   `chunk_document` re-verifies the result against the source before returning it.
2. **Coverage.** Every non-whitespace character of the source lands in at least one
   chunk. The window loop advances by exactly `size - overlap` and a boundary search can
   only pull an end *back* as far as the next window's start, so a gap is unreachable.
3. **ADR-0002's ceiling.** No chunk exceeds 512 tokens. The encoder would silently
   truncate anything longer, leaving `char_end` claiming coverage of text the vector never
   saw — a citation that points at words the retrieval never read.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

#: ADR-0003. Changing either value invalidates the sweep that chose them.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

#: ADR-0002: `bge-small-en-v1.5` has a 512-token context window.
MAX_TOKENS = 512

#: Depth limit for the token-ceiling split. Each level halves the text, so even a
#: pathological 1,000-character chunk is resolved in ~10 levels; this only exists so a
#: future bug cannot turn into unbounded recursion on a production ingest.
_MAX_SPLIT_DEPTH = 24

#: Counts the tokens the embedder will actually see, including special tokens.
TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class Chunk:
    """One retrievable span, with offsets that bracket exactly its own stored text."""

    ordinal: int
    text: str
    char_start: int
    char_end: int
    token_count: int


def _windows(text: str, size: int, overlap: int) -> Iterator[tuple[int, int]]:
    """Yield `(start, end)` character windows over `text`.

    The boundary search is restricted to the overlap zone — the last `overlap` characters
    of the window — so that an end can never be pulled back past where the next window
    begins. That is what makes a coverage gap impossible rather than merely unlikely: the
    experiment harness that produced ADR-0003's numbers searched back as far as the
    window's midpoint and advanced by `max(pos + step, end - overlap)`, which can skip
    text when a window ends early.
    """
    step = size - overlap
    length = len(text)
    pos = 0
    while pos < length:
        end = min(pos + size, length)
        if end < length:
            cut = text.rfind(" ", pos + step, end)
            if cut > pos:
                end = cut
        yield pos, end
        if end >= length:
            break
        pos += step


def _window_body(text: str, start: int, end: int) -> tuple[int, str] | None:
    """Strip a window and return its true start offset with its text, or None if blank."""
    window = text[start:end]
    body = window.strip()
    if not body:
        return None
    lead = len(window) - len(window.lstrip())
    return start + lead, body


def _split_to_token_limit(
    body: str,
    start: int,
    token_counter: TokenCounter,
    max_tokens: int,
    depth: int = 0,
) -> list[tuple[int, str, int]]:
    """Split `body` until every piece fits `max_tokens`, preserving absolute offsets.

    Returns `(start, text, token_count)` triples. Splits at the whitespace nearest the
    midpoint so the halves stay close in size; falls back to a hard character cut only
    when the text contains no whitespace at all, which for regulatory prose means a single
    enormous token sequence that has to be broken somewhere.
    """
    count = token_counter(body)
    if count <= max_tokens or len(body) < 2 or depth >= _MAX_SPLIT_DEPTH:
        return [(start, body, count)]

    mid = len(body) // 2
    cut = body.rfind(" ", 0, mid)
    if cut <= 0:
        cut = body.find(" ", mid)
    if cut <= 0:
        cut = mid

    pieces: list[tuple[int, str, int]] = []
    for raw, offset in ((body[:cut], 0), (body[cut:], cut)):
        stripped = raw.strip()
        if not stripped:
            continue
        lead = len(raw) - len(raw.lstrip())
        pieces.extend(
            _split_to_token_limit(
                stripped, start + offset + lead, token_counter, max_tokens, depth + 1
            )
        )
    return pieces


def chunk_document(
    text: str,
    token_counter: TokenCounter,
    *,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    max_tokens: int = MAX_TOKENS,
) -> list[Chunk]:
    """Split cleaned document text into chunks obeying ADR-0003 and ADR-0002.

    `token_counter` is injected rather than imported so this module stays free of torch:
    the geometry is testable, and tested, without loading a 128 MB model.
    """
    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be smaller than size ({size})")
    if overlap < 0 or size <= 0:
        raise ValueError(f"size ({size}) must be positive and overlap ({overlap}) non-negative")

    chunks: list[Chunk] = []
    for start, end in _windows(text, size, overlap):
        placed = _window_body(text, start, end)
        if placed is None:
            continue
        body_start, body = placed
        for piece_start, piece_text, piece_tokens in _split_to_token_limit(
            body, body_start, token_counter, max_tokens
        ):
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=piece_text,
                    char_start=piece_start,
                    char_end=piece_start + len(piece_text),
                    token_count=piece_tokens,
                )
            )

    verify_offsets(text, chunks)
    return chunks


def verify_offsets(text: str, chunks: list[Chunk]) -> None:
    """Assert FR-7 for every chunk: its offsets must re-extract its stored text.

    Raises `ValueError` naming the first offending chunk. This runs on every ingest
    because it costs one string comparison per chunk and because the alternative —
    discovering it from a citation that quotes the wrong span — is a trust failure in the
    product's core promise.
    """
    for chunk in chunks:
        extracted = text[chunk.char_start : chunk.char_end]
        if extracted != chunk.text:
            raise ValueError(
                f"FR-7 violated at ordinal {chunk.ordinal}: "
                f"text[{chunk.char_start}:{chunk.char_end}] does not equal the stored text "
                f"({extracted[:60]!r} != {chunk.text[:60]!r})"
            )


def uncovered_characters(text: str, chunks: list[Chunk]) -> int:
    """Count non-whitespace characters of `text` covered by no chunk.

    Used by the ingest report as evidence for invariant 2 rather than as a claim about it.
    """
    covered = bytearray(len(text))
    for chunk in chunks:
        covered[chunk.char_start : chunk.char_end] = b"\x01" * (chunk.char_end - chunk.char_start)
    return sum(1 for index, flag in enumerate(covered) if not flag and not text[index].isspace())
