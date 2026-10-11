"""Audience and Difficulty Banding Filter (FEAT-015).

Enables audience-specific snippet granularity and summary depth by tagging content
and filtering queries according to the 4 taxonomy difficulty levels:
foundational, intermediate, advanced, expert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import structlog

from app.retrieval._difficulty_data import TERM_DIFFICULTY_MAP

logger = structlog.get_logger(__name__)

DifficultyBand = Literal["foundational", "intermediate", "advanced", "expert"]
VALID_DIFFICULTY_BANDS: tuple[str, ...] = (
    "foundational",
    "intermediate",
    "advanced",
    "expert",
)

_LEVEL_PRIORITY: dict[str, int] = {
    "expert": 4,
    "advanced": 3,
    "intermediate": 2,
    "foundational": 1,
}

# Pre-index lowercase terms by their first token for sub-millisecond classification
_BY_FIRST_WORD: dict[str, list[tuple[str, str]]] = {}
_LOWER_MAP: dict[str, str] = {}

for _term, _lvl in TERM_DIFFICULTY_MAP.items():
    _term_lower = _term.lower()
    _LOWER_MAP[_term_lower] = _lvl
    _first = _term_lower.split()[0]
    _BY_FIRST_WORD.setdefault(_first, []).append((_term_lower, _lvl))


@dataclass(frozen=True)
class DifficultyConfig:
    """Configuration for audience and difficulty banding (FEAT-015)."""

    default_level: str = "intermediate"
    max_expert_tokens: int = 512
    max_foundational_tokens: int = 150
    max_intermediate_tokens: int = 250
    max_advanced_tokens: int = 400

    def get_max_tokens(self, band: str | None) -> int:
        """Resolve maximum token budget for the given difficulty band."""
        if band == "foundational":
            return self.max_foundational_tokens
        if band == "intermediate":
            return self.max_intermediate_tokens
        if band == "advanced":
            return self.max_advanced_tokens
        if band == "expert":
            return self.max_expert_tokens
        return self.max_expert_tokens


_DEFAULT_CONFIG = DifficultyConfig()


def get_term_difficulty(term: str) -> str | None:
    """Return taxonomy difficulty level for a term if registered."""
    return _LOWER_MAP.get(term.lower().strip())


def classify_difficulty(text: str, config: DifficultyConfig | None = None) -> str:
    """Classify the difficulty level of a text snippet based on regulatory terms.

    Uses an inverted index over the first word of 1,357 canonical taxonomy terms to
    achieve sub-0.1ms classification latency.
    """
    cfg = config or _DEFAULT_CONFIG
    if not text or not text.strip():
        return cfg.default_level

    text_lower = text.lower()
    words = set(re.findall(r"[a-z0-9\-]+", text_lower))

    highest_level = cfg.default_level
    highest_prio = 0

    for w in words:
        if w in _BY_FIRST_WORD:
            for term, lvl in _BY_FIRST_WORD[w]:
                if term in text_lower:
                    prio = _LEVEL_PRIORITY.get(lvl, 0)
                    if prio > highest_prio:
                        highest_prio = prio
                        highest_level = lvl

    return highest_level


def adapt_snippet(
    text: str,
    band: str | None,
    config: DifficultyConfig | None = None,
) -> str:
    """Adapt snippet token window size based on difficulty level.

    Foundational requests return concise <= 150-token summaries;
    Expert requests retain full statutory multi-clause extracts up to 512 tokens.
    Omission (band=None) returns the full text unchanged.
    """
    if not band or not text:
        return text

    cfg = config or _DEFAULT_CONFIG
    max_tokens = cfg.get_max_tokens(band)
    tokens = text.split()

    if len(tokens) <= max_tokens:
        return text

    return " ".join(tokens[:max_tokens])
