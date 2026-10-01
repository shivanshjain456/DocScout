"""Offset-preserving cleaning — ADR-0003, serving FR-7.

The rule that makes the rest of the citation machinery work: cleaning may *blank* a
character but may never move one. `char_start`/`char_end` recorded on a chunk index into
this cleaned text, and FR-7 requires `source[char_start:char_end] == chunk.text`. Deleting
a single character anywhere upstream silently shifts every offset after it, so each
substitution here is exactly as long as what it replaces, and `clean_preserving_offsets`
re-checks that invariant on every call rather than trusting it.

What gets blanked, from the Phase 0 corpus survey (ADR-0003):

* Devanagari — the regulators publish bilingual PDFs and the Hindi text is not retrievable
  by an English-only embedder and tokeniser.
* Latin Extended-B and spacing-modifier blocks — where `pypdf` deposits mojibake from
  mis-mapped font encodings.
* `U+FFFD` replacement characters — decode failures.
* Page furniture, which repeats on every page and dilutes BM25 term statistics.
"""

from __future__ import annotations

import re

#: Unicode ranges blanked by `clean_preserving_offsets`, as a single character class so
#: the substitution is one pass and provably one-character-for-one-character.
NOISE_PATTERN = re.compile(
    "["
    "\u0900-\u097f"  # Devanagari
    "\u0180-\u024f"  # Latin Extended-B (pypdf mojibake)
    "\u02b0-\u02ff"  # Spacing modifier letters (pypdf mojibake)
    "\ufffd"  # replacement character
    "]"
)

#: Running headers and footers.
#:
#: The Devanagari alternative below is unreachable in the current pass order — Devanagari
#: has already been blanked by `NOISE_PATTERN` before this runs — and is retained verbatim
#: because the order is the one ADR-0003 measured. Reordering the two passes would be a
#: strict improvement in cleaning, but it would also change the text the chunking sweep
#: scored, so it belongs with a re-measurement rather than in a quiet edit here.
PAGE_FURNITURE_PATTERN = re.compile(r"(?i)\bPage\s+\d+\s+of\s+\d+\b|\bपृ.{0,3}ठ\s*सं\.?\s*\d+")


def _blank(match: re.Match[str]) -> str:
    """Replace a match with exactly as many spaces as it consumed."""
    return " " * (match.end() - match.start())


def clean_preserving_offsets(text: str) -> str:
    """Blank non-English furniture without moving any character position.

    Raises `RuntimeError` if the result is not the same length as the input. That can only
    happen if someone edits a pattern above into something non-length-preserving, and it
    is worth a cheap check on every call because the symptom otherwise shows up far away,
    as citations that quote the wrong span.
    """
    cleaned = NOISE_PATTERN.sub(" ", text)
    cleaned = PAGE_FURNITURE_PATTERN.sub(_blank, cleaned)
    if len(cleaned) != len(text):
        raise RuntimeError(
            "cleaning changed the text length "
            f"({len(text)} -> {len(cleaned)}); offsets would be invalidated (ADR-0003)"
        )
    return cleaned


def clean_char_count(text: str) -> int:
    """Number of non-whitespace characters, which is what FR-3's threshold counts.

    Counting non-whitespace rather than total length is what makes the guard catch the
    case M2 flags as its main corpus risk: a scanned or fully Devanagari PDF extracts
    thousands of characters, every one of which this module blanks to a space. Measuring
    total length would wave such a document through as a large successful extraction
    whose stored text is empty.
    """
    return sum(1 for ch in text if not ch.isspace())
