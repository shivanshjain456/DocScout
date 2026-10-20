"""Multi-stage sanitizer for concealed and smuggled character channels (O2).

Neutralizes instructions concealed in characters a human reader does not see:
1. Zero-width and invisible formatting characters.
2. Unicode Tag characters (ASCII smuggling via U+E0000 block).
3. Bidirectional text override controls (Trojan Source attacks).
4. Non-printable control characters and terminal escape codes.
5. Homoglyph normalization (NFKC mapping of mathematical and fullwidth symbols).
6. Combining diacritic flood (Zalgo text mitigation).

Legitimate legal text discussing prompt injection remains 100% intact and answerable.
"""

from __future__ import annotations

import re
import unicodedata

CONCEALED_CLASSES = (
    "zero_width",
    "unicode_tags",
    "bidi_overrides",
    "control_chars",
    "homoglyph_alphanumerics",
    "zalgo_combining",
)

# 1. Zero-width and invisible codepoints
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff\u2060\u180e\u00ad\u2061-\u2064\ufe00-\ufe0f]")

# 2. Unicode Tag characters (U+E0000 to U+E007F) used for invisible ASCII smuggling
_UNICODE_TAGS_RE = re.compile(r"[\U000e0000-\U000e007f]")

# 3. Bidirectional text overrides
_BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f]")

# 4. ANSI terminal escape sequences and non-printable control characters (excluding \t, \n, \r)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def sanitize_hidden_channels(text: str) -> str:
    """Neutralize all concealed character channels from input text without over-blocking."""
    if not text:
        return ""

    # Pass 1: Strip ANSI escapes
    out = _ANSI_ESCAPE_RE.sub("", text)

    # Pass 2: Strip Unicode Tag smuggling characters
    out = _UNICODE_TAGS_RE.sub("", out)

    # Pass 3: Strip bidirectional overrides
    out = _BIDI_RE.sub("", out)

    # Pass 4: Strip zero-width and invisible codepoints
    out = _ZERO_WIDTH_RE.sub("", out)

    # Pass 5: Strip non-printable control characters
    out = _CONTROL_CHARS_RE.sub("", out)

    # Pass 6: Homoglyph and fullwidth/math alphanumeric normalization (NFKC)
    # Normalizes fullwidth (e.g. Ｓｙｓｔｅｍ -> System) and mathematical bold/script -> ASCII
    out = unicodedata.normalize("NFKC", out)

    # Pass 7: Zalgo / excessive stacked combining diacritics mitigation
    # Limit consecutive combining characters to at most 2 per base character
    res_chars: list[str] = []
    consecutive_combining = 0
    for ch in out:
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Mc", "Me"):
            consecutive_combining += 1
            if consecutive_combining <= 2:
                res_chars.append(ch)
        else:
            consecutive_combining = 0
            res_chars.append(ch)

    return "".join(res_chars)


def detect_concealed_characters(text: str) -> list[str]:
    """Inspect text and return list of detected concealed/smuggled character classes."""
    detected: list[str] = []
    if _ZERO_WIDTH_RE.search(text):
        detected.append("zero_width")
    if _UNICODE_TAGS_RE.search(text):
        detected.append("unicode_tags")
    if _BIDI_RE.search(text):
        detected.append("bidi_overrides")
    if _ANSI_ESCAPE_RE.search(text):
        detected.append("ansi_escapes")
    if _CONTROL_CHARS_RE.search(text):
        detected.append("control_chars")
    return detected
