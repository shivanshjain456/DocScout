"""Token-Budget Dynamic Context Packing (FEAT-073).

Packs retrieved passages dynamically to fill up to a configured token budget ceiling
(target 95% utilization). Trims boundary chunks strictly at sentence boundaries to
preserve statutory clauses and legal integrity, discarding remaining overflow chunks.
Tracks token utilization via Prometheus metrics.
"""

from __future__ import annotations

import copy
import glob
import os
import re
from collections.abc import Callable, Sequence
from typing import Any

import structlog

from app.api.metrics import (
    CONTEXT_PACKS_COMPLETED_TOTAL,
    CONTEXT_TOKEN_UTILIZATION_RATIO,
)
from app.retrieval.types import ContextPackerConfig, PackedContext

logger = structlog.get_logger(__name__)

# Regex pattern matching sentence boundaries (terminal punctuation followed by whitespace or linebreaks)
# Preserves clauses ending in '.', '!', '?', ';'
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?;\n])(?:\s+|$)")

_CACHED_TOKENIZER: Any = None
_TOKENIZER_INITIALIZED: bool = False


def _get_fast_tokenizer() -> Any:
    """Load cached fast HuggingFace tokenizer without loading heavy model weights."""
    global _CACHED_TOKENIZER, _TOKENIZER_INITIALIZED
    if _TOKENIZER_INITIALIZED:
        return _CACHED_TOKENIZER

    _TOKENIZER_INITIALIZED = True
    try:
        from tokenizers import Tokenizer

        candidate_roots = [
            os.environ.get("HF_HOME"),
            os.path.expanduser("~/.cache/huggingface"),
            os.path.join(os.getcwd(), ".cache", "huggingface"),
        ]
        for root in candidate_roots:
            if not root or not os.path.exists(root):
                continue
            pattern = os.path.join(root, "hub", "**", "tokenizer.json")
            matches = glob.glob(pattern, recursive=True)
            if matches:
                bge_matches = [m for m in matches if "bge-small" in m]
                chosen = bge_matches[0] if bge_matches else matches[0]
                _CACHED_TOKENIZER = Tokenizer.from_file(chosen)
                return _CACHED_TOKENIZER
    except Exception as exc:
        logger.debug("fast_tokenizer_discovery_failed", error=str(exc))

    return None


def _fast_sort_key(item: Any, original_index: int) -> tuple[float, int]:
    """Deterministic tie-breaking key: (-score, original_index)."""
    try:
        val = item["score"] if isinstance(item, dict) else item.score
        return (-float(val), original_index)
    except Exception:
        return (0.0, original_index)


def _get_passage_text(item: Any) -> str:
    """Extract text attribute or dictionary key from passage."""
    if isinstance(item, dict):
        return str(item.get("text", ""))
    return str(getattr(item, "text", ""))


def _with_trimmed_text[T](item: T, new_text: str) -> T:
    """Return a non-mutating copy of item with text replaced by new_text."""
    if isinstance(item, dict):
        updated = dict(item)
        updated["text"] = new_text
        return updated  # type: ignore[return-value]

    try:
        cloned = copy.copy(item)
        object.__setattr__(cloned, "text", new_text)
        return cloned
    except Exception:
        return item


class ContextPacker:
    """Greedy dynamic context packing under an explicit token budget ceiling."""

    def __init__(
        self,
        default_config: ContextPackerConfig | None = None,
        count_tokens_fn: Callable[[str], int] | None = None,
    ) -> None:
        self.default_config = default_config or ContextPackerConfig()
        self._custom_count_tokens = count_tokens_fn
        self._cached_tok = _get_fast_tokenizer()

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using custom counter, cached fast tokenizer, or fallback."""
        if not text:
            return 0
        if self._custom_count_tokens is not None:
            return self._custom_count_tokens(text)

        tok = self._cached_tok or _get_fast_tokenizer()
        if tok is not None:
            try:
                return len(tok.encode(text, add_special_tokens=False).ids) + 2
            except Exception as exc:
                logger.debug("fast_tokenizer_encode_failed", error=str(exc))

        try:
            from app.ingest.embed import Embedder

            return Embedder().count_tokens(text)
        except Exception:
            # Fallback heuristic: roughly 1 token per 4 characters or word count
            return max(1, len(text.split()))

    def count_tokens_batch(self, texts: Sequence[str]) -> list[int]:
        """Count tokens for a batch of texts using fast tokenization."""
        if not texts:
            return []
        if self._custom_count_tokens is not None:
            return [self._custom_count_tokens(t) for t in texts]

        tok = self._cached_tok or _get_fast_tokenizer()
        if tok is not None:
            try:
                return [len(tok.encode(t, add_special_tokens=False).ids) + 2 for t in texts]
            except Exception as exc:
                logger.debug("fast_tokenizer_batch_failed", error=str(exc))

        return [self.count_tokens(t) for t in texts]

    def trim_to_sentence_boundary(
        self, text: str, max_tokens: int, min_sentence_chars: int = 20
    ) -> tuple[str, int, bool]:
        """Trim text at a sentence boundary such that token count <= max_tokens.

        Returns (trimmed_text, token_count, was_trimmed).
        If the full text already fits, returns (text, token_count, False).
        If no complete sentence fits within max_tokens, returns ("", 0, False).
        """
        if not text or max_tokens <= 0:
            return ("", 0, False)

        full_tokens = self.count_tokens(text)
        if full_tokens <= max_tokens:
            return (text, full_tokens, False)

        splits = [m.end() for m in _SENTENCE_BOUNDARY_RE.finditer(text) if m.end() < len(text)]
        if not splits:
            return ("", 0, False)

        low = 0
        high = len(splits) - 1
        best_candidate: str | None = None
        best_tokens: int = 0

        while low <= high:
            mid = (low + high) // 2
            cand = text[: splits[mid]].strip()
            if len(cand) < min_sentence_chars:
                low = mid + 1
                continue
            cand_tokens = self.count_tokens(cand)
            if cand_tokens <= max_tokens:
                best_candidate = cand
                best_tokens = cand_tokens
                # Try longer candidate prefix to maximize context
                low = mid + 1
            else:
                # Exceeded max_tokens, try shorter prefix
                high = mid - 1

        if best_candidate is not None and best_tokens > 0:
            return (best_candidate, best_tokens, True)

        return ("", 0, False)

    def pack[T](
        self, passages: Sequence[T], config: ContextPackerConfig | None = None
    ) -> PackedContext:
        """Pack retrieved passages greedily up to token budget ceiling.

        Ceiling is calculated as: int(config.max_tokens * config.target_utilization).
        If the boundary chunk overflows the ceiling and sentence_boundary_trim is enabled,
        it is trimmed to sentence boundaries if >= 1 complete sentence fits remaining tokens.
        All subsequent overflow chunks are discarded.
        """
        cfg = config or self.default_config
        if not passages:
            CONTEXT_TOKEN_UTILIZATION_RATIO.set(0.0)
            CONTEXT_PACKS_COMPLETED_TOTAL.labels(status="success").inc()
            return PackedContext(
                packed_passages=[],
                total_tokens=0,
                utilization_ratio=0.0,
                truncated_boundary_chunk=False,
            )

        try:
            ceiling_tokens = int(cfg.max_tokens * cfg.target_utilization)

            # Sort descending by relevance score with deterministic tie-breaking
            indexed = [(_fast_sort_key(p, i), p) for i, p in enumerate(passages)]
            indexed.sort(key=lambda x: x[0])
            sorted_passages = [p for _, p in indexed]

            texts = [_get_passage_text(p) for p in sorted_passages]
            token_counts = self.count_tokens_batch(texts)

            packed: list[T] = []
            accumulated_tokens = 0
            truncated_boundary_chunk = False

            for passage, text, tokens in zip(sorted_passages, texts, token_counts, strict=False):
                if accumulated_tokens + tokens <= ceiling_tokens:
                    packed.append(passage)
                    accumulated_tokens += tokens
                else:
                    if cfg.sentence_boundary_trim and not truncated_boundary_chunk:
                        remaining_budget = ceiling_tokens - accumulated_tokens
                        if remaining_budget > 0:
                            trimmed_text, trimmed_tokens, did_trim = self.trim_to_sentence_boundary(
                                text, remaining_budget, cfg.min_sentence_chars
                            )
                            if did_trim and trimmed_tokens > 0:
                                trimmed_passage = _with_trimmed_text(passage, trimmed_text)
                                packed.append(trimmed_passage)
                                accumulated_tokens += trimmed_tokens
                                truncated_boundary_chunk = True
                    break

            utilization_ratio = accumulated_tokens / cfg.max_tokens if cfg.max_tokens > 0 else 0.0

            CONTEXT_TOKEN_UTILIZATION_RATIO.set(utilization_ratio)
            CONTEXT_PACKS_COMPLETED_TOTAL.labels(status="success").inc()

            return PackedContext(
                packed_passages=packed,
                total_tokens=accumulated_tokens,
                utilization_ratio=utilization_ratio,
                truncated_boundary_chunk=truncated_boundary_chunk,
            )

        except Exception as exc:
            logger.warning(
                "context_packing_unexpected_error_fallback",
                error=str(exc),
                candidate_count=len(passages),
            )
            CONTEXT_PACKS_COMPLETED_TOTAL.labels(status="fallback").inc()
            fallback_passages = list(passages[:3])
            try:
                fallback_tokens = sum(
                    self.count_tokens(_get_passage_text(p)) for p in fallback_passages
                )
            except Exception:
                fallback_tokens = sum(
                    max(1, len(_get_passage_text(p).split())) for p in fallback_passages
                )
            utilization_ratio = fallback_tokens / cfg.max_tokens if cfg.max_tokens > 0 else 0.0
            CONTEXT_TOKEN_UTILIZATION_RATIO.set(utilization_ratio)
            return PackedContext(
                packed_passages=fallback_passages,
                total_tokens=fallback_tokens,
                utilization_ratio=utilization_ratio,
                truncated_boundary_chunk=False,
            )


_DEFAULT_PACKER = ContextPacker()


def pack_context[T](
    passages: Sequence[T], config: ContextPackerConfig | None = None
) -> PackedContext:
    """Pack retrieved passages dynamically to fill up to the token budget ceiling."""
    return _DEFAULT_PACKER.pack(passages, config=config)
