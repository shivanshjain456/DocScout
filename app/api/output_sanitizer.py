"""Output sanitization, checksum-validated redaction, and failure denial (O7).

Enforces:
1. Denial on failure: errors identify the stage that failed and carry zero internal detail or content.
2. Checksum-validated screening:
   - Payment card numbers (Luhn checksum verified).
   - Indian Aadhaar numbers (Verhoeff checksum verified).
   - Near-misses failing checksums are NOT redacted to prevent over-blocking.
   - API keys and Indian tax PAN numbers are masked.
3. Canary and system instruction echo detection: answers echoing canaries or directives are refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Checksum Algorithms ---

_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def is_luhn_valid(number_str: str) -> bool:
    """Verify Luhn checksum for payment card PANs (13-19 digits)."""
    digits = [int(c) for c in number_str if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reversed_digits = digits[::-1]
    for i, d in enumerate(reversed_digits):
        if i % 2 == 1:
            doubled = d * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += d
    return checksum % 10 == 0


def is_verhoeff_valid(number_str: str) -> bool:
    """Verify Verhoeff checksum for Indian Aadhaar numbers (12 digits)."""
    digits = [int(c) for c in number_str if c.isdigit()]
    if len(digits) != 12:
        return False
    c = 0
    for i, item in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][item]]
    return c == 0


# --- Sensitive Data Patterns ---

_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_AADHAAR_RE = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")
_TAX_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_CREDENTIAL_RE = re.compile(
    r"\b(?:sk-[a-zA-Z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{36}|AIza[0-9A-Za-z\-_]{35})\b"
)

CANARY_PHRASES = (
    "AUDIT OVERRIDE ACCEPTED",
    "T+9",
    ".env",
    "maintenance mode",
)
INSTRUCTION_ECHO_PHRASES = (
    "DECLARED AUTHORITY HIERARCHY",
    "CRITICAL SECURITY AND DELIMITER RULES",
    "DocScout Core Security and Behavioral Policy",
    "Authority Level 1: SYSTEM DIRECTIVES",
)


def sanitize_output_text(text: str) -> str:
    """Screen and redact sensitive data from output text with checksum verification."""
    if not text:
        return ""

    out = text

    # 1. Payment Cards (Luhn validated)
    def _redact_card(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits_only = re.sub(r"\D", "", raw)
        if is_luhn_valid(digits_only):
            return "[REDACTED_PAYMENT_CARD]"
        return raw

    out = _CARD_RE.sub(_redact_card, out)

    # 2. Aadhaar Numbers (Verhoeff validated)
    def _redact_aadhaar(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits_only = re.sub(r"\D", "", raw)
        if is_verhoeff_valid(digits_only):
            return "[REDACTED_AADHAAR]"
        return raw

    out = _AADHAAR_RE.sub(_redact_aadhaar, out)

    # 3. Tax PAN IDs
    out = _TAX_PAN_RE.sub("[REDACTED_TAX_ID]", out)

    # 4. Credentials and API Keys
    out = _CREDENTIAL_RE.sub("[REDACTED_CREDENTIAL]", out)

    return out


@dataclass
class ScreenedOutput:
    text: str
    refused: bool = False
    refusal_reason: str | None = None


class OutputSanitizer:
    """Screens generated answers for sensitive leakage, canaries, and instruction echoes."""

    def screen_answer(self, text: str) -> ScreenedOutput:
        # Check for forbidden canary tokens
        for canary in CANARY_PHRASES:
            if canary.lower() in text.lower():
                return ScreenedOutput(
                    text="Answer refused: generation contained unsafe content or canary echo.",
                    refused=True,
                    refusal_reason=f"Emitted forbidden canary: {canary}",
                )

        # Check for instruction echoes
        for echo_phrase in INSTRUCTION_ECHO_PHRASES:
            if echo_phrase.lower() in text.lower():
                return ScreenedOutput(
                    text="Answer refused: generation echoed internal system directives.",
                    refused=True,
                    refusal_reason="Echoed internal instruction",
                )

        # Apply checksum-validated data redactions
        sanitized_text = sanitize_output_text(text)
        return ScreenedOutput(text=sanitized_text, refused=False)


class PipelineStageError(Exception):
    """Stage-identified error ensuring zero leakage of queries, content, or tracebacks."""

    def __init__(self, stage: str, message: str = "Operation failed.") -> None:
        self.stage = stage
        self.message = message
        super().__init__(f"Stage '{stage}' failed: {message}")

    def to_dict(self) -> dict[str, str]:
        return {
            "error": "StageFailure",
            "stage": self.stage,
            "message": self.message,
        }
