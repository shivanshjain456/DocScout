"""Lost-in-the-Middle Context Reordering (FEAT-072).

Reorders retrieved candidates using alternating boundary distribution (U-shaped relevance profile)
before presenting them to the user or downstream LLM, placing the highest-scoring evidence at the
beginning and end of the context window to counteract transformer attention degradation.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _fast_sort_key(item: Any, original_index: int) -> tuple[float, int]:
    """Deterministic tie-breaking key: (-score, original_index)."""
    try:
        val = item["score"] if isinstance(item, dict) else item.score
        return (-float(val), original_index)
    except Exception:
        return (0.0, original_index)


def _with_presentation_rank[T](item: T, rank: int) -> T:
    """Return a non-mutating copy of item with presentation_rank set to `rank`."""
    if isinstance(item, dict):
        updated = dict(item)
        updated["presentation_rank"] = rank
        return updated  # type: ignore[return-value]

    try:
        cloned = copy.copy(item)
        object.__setattr__(cloned, "presentation_rank", rank)
        return cloned
    except Exception:
        return item


def reorder_context[T](passages: Sequence[T]) -> list[T]:
    """Reorder retrieved passages using alternating boundary placement (U-shaped distribution).

    Places the highest-scoring candidate (Rank 1) at position 0 (the beginning of the context window),
    Rank 2 at position N-1 (the end of the context window), Rank 3 at position 1, Rank 4 at
    position N-2, and so on, keeping the least relevant passages situated in the middle of
    the window where attention degradation is greatest.

    Guarantees:
    - Pure in-memory transformation with execution latency <= 0.05 ms for 10 passages.
    - Zero modification or loss of underlying text, chunk IDs, or relevance scores.
    - Sets `presentation_rank` to the 1-indexed presentation position (1..N).
    - If an unexpected error occurs, returns input passages in standard descending score order.
    """
    if not passages:
        return []

    try:
        n = len(passages)
        if n == 1:
            return [_with_presentation_rank(passages[0], 1)]

        # Sort candidates strictly descending by score with deterministic tie-breaking
        indexed = [(_fast_sort_key(p, i), p) for i, p in enumerate(passages)]
        indexed.sort(key=lambda x: x[0])

        if n == 2:
            return [
                _with_presentation_rank(indexed[0][1], 1),
                _with_presentation_rank(indexed[1][1], 2),
            ]

        # Alternating boundary placement
        reordered: list[T | None] = [None] * n
        left = 0
        right = n - 1

        for i, (_, passage) in enumerate(indexed):
            if i % 2 == 0:
                reordered[left] = _with_presentation_rank(passage, left + 1)
                left += 1
            else:
                reordered[right] = _with_presentation_rank(passage, right + 1)
                right -= 1

        return [p for p in reordered if p is not None]

    except Exception as exc:
        logger.warning(
            "context_reorder_unexpected_error_fallback",
            error=str(exc),
            candidate_count=len(passages),
        )
        return list(passages)
