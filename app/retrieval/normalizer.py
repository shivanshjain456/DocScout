"""Typo-Tolerant Regulatory Token Normalizer (FEAT-018).

Provides SymSpell / Damerau-Levenshtein distance matching (max distance 2)
calibrated against the 1,358 lexicon terms and official circular numbering syntax
to correct user misspellings without corrupting legal references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from app.api import metrics
from app.retrieval._normalizer_data import (
    CANONICAL_CASING,
    PROTECTED_WORDS,
    VOCABULARY_WORDS,
)

logger = structlog.get_logger(__name__)

# Circular ID regex pattern matching RBI and SEBI official publication formats
CIRCULAR_ID_REGEX = re.compile(
    r"\b(?:"
    r"RBI/(?:20\d{2}-\d{2,4})/\d+|"
    r"SEBI/[A-Z0-9\/\-\.]+|"
    r"(?:DOR|FIDD|DPSS|DOS|FMRD|IDMD|DGBA|CO)\.[A-Z0-9\.\-\/]+"
    r")\b",
    re.IGNORECASE,
)

# Section and rule citations that must never be altered
SECTION_CITATION_REGEX = re.compile(
    r"\b(?:"
    r"(?:section|sec|rule|clause|sub-clause|article|regulation|reg|para|paragraph)\s+[0-9]+[a-z0-9\(\)\/\-\.]*|"
    r"(?:schedule|order|part|chapter)\s+[ivxlcdm0-9]+[a-z0-9\(\)\/\-\.]*"
    r")\b",
    re.IGNORECASE,
)

# Specific alphanumeric statutory sub-clause notations (e.g. 45-IA, 144(xi), 3(a))
ALPHANUM_CODE_REGEX = re.compile(
    r"\b\d+[a-z0-9\(\)\/\-\.]+\b",
    re.IGNORECASE,
)


def damerau_levenshtein(s1: str, s2: str) -> int:
    """Compute optimal string alignment distance supporting transpositions."""
    if s1 == s2:
        return 0
    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > 2:
        return abs(len1 - len2)

    r1 = list(range(len2 + 1))
    r2 = list(range(len2 + 1))
    r0 = [0] * (len2 + 1)

    for i in range(1, len1 + 1):
        r0[0] = i
        ch1 = s1[i - 1]
        for j in range(1, len2 + 1):
            ch2 = s2[j - 1]
            cost = 0 if ch1 == ch2 else 1
            res = min(
                r1[j] + 1,
                r0[j - 1] + 1,
                r1[j - 1] + cost,
            )
            if i > 1 and j > 1 and ch1 == s2[j - 2] and s1[i - 2] == ch2:
                trans = r2[j - 2] + 1
                if trans < res:
                    res = trans
            r0[j] = res
        r2, r1, r0 = r1, r0, r2
    return r1[len2]


def get_deletes(word: str, max_distance: int = 2) -> set[str]:
    """Generate all delete variants of a word up to max_distance."""
    deletes: set[str] = set()
    queue = {word}
    for _ in range(max_distance):
        next_queue: set[str] = set()
        for w in queue:
            if len(w) > 2:
                for i in range(len(w)):
                    del_w = w[:i] + w[i + 1 :]
                    deletes.add(del_w)
                    next_queue.add(del_w)
        queue = next_queue
    return deletes


class NormalizedQuery(BaseModel):
    """Output schema for typo-normalized search query (FEAT-018)."""

    normalized_query: str
    corrections_applied: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class NormalizerConfig:
    """Configuration schema for typo-tolerant regulatory token normalizer."""

    enabled: bool = True
    max_edit_distance: int = 2
    min_token_len: int = 4
    max_query_chars: int = 512


class RegulatoryNormalizer:
    """Symmetric Delete / Damerau-Levenshtein fuzzy token normalizer."""

    _instance: ClassVar[RegulatoryNormalizer | None] = None

    def __init__(self, config: NormalizerConfig | None = None) -> None:
        self.config = config or NormalizerConfig()
        self._words_list: list[str] = list(VOCABULARY_WORDS.keys())
        self._word_to_id: dict[str, int] = {w: i for i, w in enumerate(self._words_list)}
        self._delete_map: dict[str, int | tuple[int, ...]] = {}
        self._build_symspell_index()

    def _build_symspell_index(self) -> None:
        raw_map: dict[str, list[int]] = {}
        for w in self._words_list:
            if len(w) >= self.config.min_token_len:
                wid = self._word_to_id[w]
                for d in get_deletes(w, self.config.max_edit_distance):
                    raw_map.setdefault(d, []).append(wid)

        self._delete_map = {
            d: tuple(wids) if len(wids) > 1 else wids[0] for d, wids in raw_map.items()
        }

    def is_protected_token(self, token: str) -> bool:
        """Check if an isolated token must be protected from correction."""
        t_lower = token.lower()
        if t_lower in PROTECTED_WORDS:
            return True
        if len(token) < self.config.min_token_len:
            return True
        if token.isdigit():
            return True
        if re.match(r"^\d+(?:\.\d+)?%?$", token):
            return True
        if ALPHANUM_CODE_REGEX.fullmatch(token):
            return True
        if t_lower in VOCABULARY_WORDS:
            return True
        return False

    def correct_token(self, token: str) -> tuple[str, bool]:
        """Fuzzy match a single token against the regulatory lexicon."""
        if self.is_protected_token(token):
            return token, False

        tok_lower = token.lower()

        # 1. Tier 1: Check distance 0 and 1 deletes first
        candidates: set[int] = set()
        if tok_lower in self._delete_map:
            val = self._delete_map[tok_lower]
            if isinstance(val, tuple):
                candidates.update(val)
            else:
                candidates.add(val)

        d1_list = [tok_lower[:i] + tok_lower[i + 1 :] for i in range(len(tok_lower))]
        for d in d1_list:
            if d in self._delete_map:
                val = self._delete_map[d]
                if isinstance(val, tuple):
                    candidates.update(val)
                else:
                    candidates.add(val)

        scored: list[tuple[int, int, str]] = []
        tok_len = len(tok_lower)
        for wid in candidates:
            cand_str = self._words_list[wid]
            if abs(len(cand_str) - tok_len) > 1:
                continue
            dist = damerau_levenshtein(tok_lower, cand_str)
            if dist <= 1:
                freq = VOCABULARY_WORDS.get(cand_str, 1)
                scored.append((dist, -freq, cand_str))

        # 2. Tier 2: Only if no distance-1 candidate found, expand to distance 2
        if not scored and self.config.max_edit_distance >= 2:
            d2_set: set[str] = set()
            for d1 in d1_list:
                for j in range(len(d1)):
                    d2_set.add(d1[:j] + d1[j + 1 :])
            for d2 in d2_set:
                if d2 in self._delete_map:
                    val = self._delete_map[d2]
                    if isinstance(val, tuple):
                        candidates.update(val)
                    else:
                        candidates.add(val)

            for wid in candidates:
                cand_str = self._words_list[wid]
                if abs(len(cand_str) - tok_len) > self.config.max_edit_distance:
                    continue
                dist = damerau_levenshtein(tok_lower, cand_str)
                if dist <= self.config.max_edit_distance:
                    freq = VOCABULARY_WORDS.get(cand_str, 1)
                    scored.append((dist, -freq, cand_str))

        if not scored:
            return token, False

        scored.sort()
        best_cand = scored[0][2]
        canon = CANONICAL_CASING.get(best_cand, best_cand)

        # Preserve caller's casing style
        if token.isupper():
            corrected = canon.upper()
        elif token[0].isupper():
            corrected = canon.capitalize()
        else:
            corrected = canon.lower()

        if corrected != token:
            self._record_metric(canon)
            return corrected, True

        return token, False

    def normalize(self, query: str) -> NormalizedQuery:
        """Normalize query string, recovering typos while preserving exact references."""
        if not self.config.enabled or not query or not query.strip():
            return NormalizedQuery(normalized_query=query or "")

        clean_query = query.strip()
        if len(clean_query) > self.config.max_query_chars:
            clean_query = clean_query[: self.config.max_query_chars]

        corrections: dict[str, str] = {}
        placeholders: list[str] = []

        def mask_span(match: re.Match[str]) -> str:
            idx = len(placeholders)
            placeholders.append(match.group(0))
            return f"__PROT_{idx}__"

        # 1. Mask exact circular IDs and statutory section citations
        q_masked = CIRCULAR_ID_REGEX.sub(mask_span, clean_query)
        q_masked = SECTION_CITATION_REGEX.sub(mask_span, q_masked)

        # 2. Tokenize keeping punctuation and spacing
        tokens = re.split(r"(\w+)", q_masked)
        new_tokens: list[str] = []

        for tok in tokens:
            if not tok or not tok.isalnum() or tok.startswith("__PROT_"):
                new_tokens.append(tok)
                continue

            corrected_tok, was_corrected = self.correct_token(tok)
            if was_corrected:
                corrections[tok] = corrected_tok
                new_tokens.append(corrected_tok)
            else:
                new_tokens.append(tok)

        reconstructed = "".join(new_tokens)

        # 3. Unmask protected spans
        for idx, orig in enumerate(placeholders):
            reconstructed = reconstructed.replace(f"__PROT_{idx}__", orig)

        return NormalizedQuery(
            normalized_query=reconstructed,
            corrections_applied=corrections,
        )

    def _record_metric(self, term: str) -> None:
        try:
            metrics.TYPOS_CORRECTED_TOTAL.labels(term=term).inc()
        except Exception as exc:
            logger.debug("normalizer.metric_failed", error=str(exc))


_DEFAULT_NORMALIZER: RegulatoryNormalizer | None = None


def get_default_normalizer() -> RegulatoryNormalizer:
    """Return singleton instance of RegulatoryNormalizer."""
    global _DEFAULT_NORMALIZER
    if _DEFAULT_NORMALIZER is None:
        _DEFAULT_NORMALIZER = RegulatoryNormalizer()
    return _DEFAULT_NORMALIZER
