"""Hierarchical Structure-Aware Circular Chunking (FEAT-061).

Replaces naive fixed sliding windows with statutory structure-aware semantic chunking
that mirrors the anatomical hierarchy of regulatory circulars:
- Gazette / Notification Header
- Preamble
- Section, Subsection, Clause, Subclause
- Proviso ("Provided that...", "Provided further that...")
- Schedule and Annexures

Guarantees:
1. FR-7: text[char_start:char_end] == chunk.text for 100% of chunks.
2. Invariant 2: 100% text coverage (uncovered_characters == 0).
3. ADR-0002: Context window ceiling <= 512 tokens.
4. Proviso retention: Provisos remain attached to parent operative rule (or linked via parent_chunk_id).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from app.api.metrics import CHUNK_TOKEN_COUNT, CHUNKS_CREATED_TOTAL
from app.observability import get_logger

logger = get_logger("docscout.ingest.hierarchical_chunker")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class ChunkingConfig:
    max_chunk_tokens: int = 512
    min_chunk_tokens: int = 64
    preserve_provisos: bool = True
    fallback_to_sliding_window: bool = True


@dataclass(frozen=True)
class HierarchicalChunk:
    """A retrievable semantic chunk with statutory hierarchical lineage."""

    chunk_id: UUID
    parent_chunk_id: UUID | None
    ordinal: int
    text: str
    char_start: int
    char_end: int
    token_count: int
    clause_hierarchy: list[str] = field(default_factory=list)
    is_proviso: bool = False
    chunk_type: str = "standard"


# Regex patterns matching Indian and global regulatory hierarchy structures
PAT_GAZETTE_HEADER = re.compile(
    r"^(?:THE\s+GAZETTE\s+OF\s+INDIA|RESERVE\s+BANK\s+OF\s+INDIA|DEPARTMENT\s+OF|"
    r"NOTIFICATION|CIRCULAR\s+NO\.|REF(?:ERENCE)?\s+NO\.|F\.\s*NO\.)",
    re.IGNORECASE | re.MULTILINE,
)

PAT_PREAMBLE = re.compile(
    r"^(?:WHEREAS|IN\s+EXERCISE\s+OF\s+THE\s+POWERS|PLEASE\s+REFER\s+TO|ATTENTION\s+OF\s+AUTHORI[SZ]ED)",
    re.IGNORECASE | re.MULTILINE,
)

PAT_SECTION = re.compile(
    r"^(?:PART\s+[IVXLCDM]+|CHAPTER\s+[IVXLCDM]+|SECTION\s+\d+|\d+\.)\s+",
    re.IGNORECASE | re.MULTILINE,
)

PAT_SUBSECTION = re.compile(
    r"^\s*(?:\((\d+)\)|\((\w)\)|\(([ivxlcdm]+)\))\s+",
    re.IGNORECASE | re.MULTILINE,
)

PAT_SCHEDULE = re.compile(
    r"^(?:SCHEDULE\s+[IVXLCDM\d]+|ANNEXURE\s+[IVXLCDM\d]+|APPENDIX\s+[IVXLCDM\d]+)",
    re.IGNORECASE | re.MULTILINE,
)

PAT_PROVISO = re.compile(
    r"\b(?:Provided\s+that|Provided\s+further\s+that|Provided\s+also\s+that)\b",
    re.IGNORECASE,
)


def _approx_token_count(text: str) -> int:
    """Fast whitespace-based token approximation when no tokenizer injected."""
    words = text.split()
    return max(1, len(words) * 4 // 3)


def _detect_structural_blocks(text: str) -> list[tuple[int, int, str, str]]:
    """Segment document into coarse structural blocks (start, end, block_type, title).

    Returns list of (char_start, char_end, block_type, label).
    """
    boundaries: list[tuple[int, str, str]] = []

    # Find section and schedule headers
    for match in PAT_SECTION.finditer(text):
        boundaries.append((match.start(), "section", match.group().strip()))

    for match in PAT_SCHEDULE.finditer(text):
        boundaries.append((match.start(), "schedule", match.group().strip()))

    for match in PAT_GAZETTE_HEADER.finditer(text):
        boundaries.append((match.start(), "gazette_header", match.group().strip()))

    for match in PAT_PREAMBLE.finditer(text):
        boundaries.append((match.start(), "preamble", match.group().strip()))

    # Sort boundaries by character offset
    boundaries.sort(key=lambda b: b[0])

    if not boundaries:
        return [(0, len(text), "standard", "Document Body")]

    # Eliminate duplicate or overlapping boundaries
    filtered: list[tuple[int, str, str]] = []
    last_pos = -1
    for pos, b_type, label in boundaries:
        if pos > last_pos:
            filtered.append((pos, b_type, label))
            last_pos = pos

    blocks: list[tuple[int, int, str, str]] = []
    # If text starts before first detected boundary, make a preamble / leading block
    if filtered[0][0] > 0:
        blocks.append((0, filtered[0][0], "preamble", "Preamble"))

    for i, (start, b_type, label) in enumerate(filtered):
        end = filtered[i + 1][0] if i + 1 < len(filtered) else len(text)
        if end > start:
            blocks.append((start, end, b_type, label))

    return blocks


def _split_into_paragraphs(
    block_text: str,
    block_start: int,
) -> list[tuple[int, int, str]]:
    """Split block text into non-blank paragraph spans (abs_start, abs_end, text)."""
    para_spans: list[tuple[int, int, str]] = []
    # Split on double newlines or standard newline boundaries
    pattern = re.compile(r"\n\s*\n|\r\n\s*\r\n")
    matches = list(pattern.finditer(block_text))

    if not matches:
        stripped = block_text.strip()
        if stripped:
            lead = len(block_text) - len(block_text.lstrip())
            para_spans.append((block_start + lead, block_start + lead + len(stripped), stripped))
        return para_spans

    last_idx = 0
    for m in matches:
        segment = block_text[last_idx : m.start()]
        stripped = segment.strip()
        if stripped:
            lead = len(segment) - len(segment.lstrip())
            para_spans.append(
                (
                    block_start + last_idx + lead,
                    block_start + last_idx + lead + len(stripped),
                    stripped,
                )
            )
        last_idx = m.end()

    if last_idx < len(block_text):
        segment = block_text[last_idx:]
        stripped = segment.strip()
        if stripped:
            lead = len(segment) - len(segment.lstrip())
            para_spans.append(
                (
                    block_start + last_idx + lead,
                    block_start + last_idx + lead + len(stripped),
                    stripped,
                )
            )

    return para_spans


def _split_subparagraph_to_ceiling(
    text_slice: str,
    start_offset: int,
    token_counter: TokenCounter,
    max_tokens: int,
    hierarchy: list[str],
    parent_id: UUID | None,
    chunk_type: str,
    is_proviso: bool,
) -> list[HierarchicalChunk]:
    """Halve paragraph slice recursively if it exceeds token limit, preserving exact offsets."""
    tokens = token_counter(text_slice)
    if tokens <= max_tokens or len(text_slice) < 4:
        c_id = uuid.uuid4()
        return [
            HierarchicalChunk(
                chunk_id=c_id,
                parent_chunk_id=parent_id,
                ordinal=0,  # Assigned later
                text=text_slice,
                char_start=start_offset,
                char_end=start_offset + len(text_slice),
                token_count=tokens,
                clause_hierarchy=hierarchy,
                is_proviso=is_proviso,
                chunk_type=chunk_type,
            )
        ]

    mid = len(text_slice) // 2
    # Try sentence cut first
    cut = text_slice.rfind(". ", 0, mid)
    if cut <= 0:
        cut = text_slice.rfind(" ", 0, mid)
    if cut <= 0:
        cut = text_slice.find(" ", mid)
    if cut <= 0:
        cut = mid

    results: list[HierarchicalChunk] = []
    left_raw = text_slice[:cut]
    right_raw = text_slice[cut:]

    left_stripped = left_raw.strip()
    if left_stripped:
        lead = len(left_raw) - len(left_raw.lstrip())
        results.extend(
            _split_subparagraph_to_ceiling(
                left_stripped,
                start_offset + lead,
                token_counter,
                max_tokens,
                hierarchy,
                parent_id,
                chunk_type,
                is_proviso,
            )
        )

    right_stripped = right_raw.strip()
    if right_stripped:
        lead = len(right_raw) - len(right_raw.lstrip())
        results.extend(
            _split_subparagraph_to_ceiling(
                right_stripped,
                start_offset + cut + lead,
                token_counter,
                max_tokens,
                hierarchy,
                parent_id,
                chunk_type,
                is_proviso,
            )
        )

    return results


class HierarchicalChunker:
    """Anatomical regulatory circular chunker preserving legal hierarchies and provisos."""

    def __init__(
        self,
        config: ChunkingConfig | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self.config = config or ChunkingConfig()
        self.token_counter = token_counter or _approx_token_count

    def chunk(self, text: str) -> list[HierarchicalChunk]:
        """Perform hierarchical structure-aware chunking on raw or cleaned regulatory text."""
        if not text or not text.strip():
            return []

        # 1. Structural block segmentation
        blocks = _detect_structural_blocks(text)

        # Fallback to sliding window if insufficient hierarchical indicators
        if len(blocks) <= 1 and self.config.fallback_to_sliding_window and len(text) > 2000:
            if not PAT_SECTION.search(text) and not PAT_PREAMBLE.search(text):
                return self._sliding_window_fallback(text)

        chunks: list[HierarchicalChunk] = []
        last_operative_parent_id: UUID | None = None

        for b_start, b_end, b_type, b_label in blocks:
            block_text = text[b_start:b_end]
            paragraphs = _split_into_paragraphs(block_text, b_start)

            current_hierarchy = [b_label]

            # Accumulator to merge small paragraphs up to min/max tokens
            accum_text = ""
            accum_start = -1
            accum_end = -1
            accum_is_proviso = False

            def flush_accumulator(curr_hier: list[str], block_type: str) -> None:
                nonlocal \
                    accum_text, \
                    accum_start, \
                    accum_end, \
                    accum_is_proviso, \
                    last_operative_parent_id
                if not accum_text:
                    return

                # Check if it fits ceiling
                sub_chunks = _split_subparagraph_to_ceiling(
                    accum_text,
                    accum_start,
                    self.token_counter,
                    self.config.max_chunk_tokens,
                    curr_hier,
                    last_operative_parent_id if accum_is_proviso else None,
                    "proviso" if accum_is_proviso else block_type,
                    accum_is_proviso,
                )

                primary_id: UUID | None = None
                for sc in sub_chunks:
                    chunks.append(sc)
                    if not sc.is_proviso and sc.chunk_type in {"section", "clause", "standard"}:
                        if primary_id is None:
                            primary_id = sc.chunk_id

                if primary_id is not None:
                    last_operative_parent_id = primary_id

                accum_text = ""
                accum_start = -1
                accum_end = -1
                accum_is_proviso = False

            for p_start, p_end, p_text in paragraphs:
                p_has_proviso = bool(PAT_PROVISO.search(p_text))

                # Check if paragraph has subsection pattern
                sub_match = PAT_SUBSECTION.match(p_text)
                if sub_match:
                    current_hierarchy = [b_label, sub_match.group().strip()]

                # If preserve_provisos is True, try to attach to existing accumulator
                if accum_text:
                    proposed_text = text[accum_start:p_end]
                    proposed_tokens = self.token_counter(proposed_text)

                    # If this is a proviso and preserve_provisos is true, prioritize keeping with parent
                    can_attach_proviso = (
                        p_has_proviso
                        and self.config.preserve_provisos
                        and proposed_tokens <= self.config.max_chunk_tokens
                    )

                    can_merge_standard = (
                        not p_has_proviso
                        and proposed_tokens <= self.config.max_chunk_tokens
                        and (self.token_counter(accum_text) < self.config.min_chunk_tokens)
                    )

                    if can_attach_proviso or can_merge_standard:
                        accum_text = proposed_text
                        accum_end = p_end
                        if p_has_proviso:
                            accum_is_proviso = True
                        continue

                    # Otherwise flush accumulator
                    flush_accumulator(current_hierarchy, b_type)

                # Start fresh accumulator with current paragraph
                accum_text = p_text
                accum_start = p_start
                accum_end = p_end
                accum_is_proviso = p_has_proviso

            flush_accumulator(current_hierarchy, b_type)

        # Final pass: assign sequential ordinals
        ordered_chunks: list[HierarchicalChunk] = []
        for idx, c in enumerate(chunks):
            ordered_chunks.append(
                HierarchicalChunk(
                    chunk_id=c.chunk_id,
                    parent_chunk_id=c.parent_chunk_id,
                    ordinal=idx,
                    text=c.text,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    token_count=c.token_count,
                    clause_hierarchy=c.clause_hierarchy,
                    is_proviso=c.is_proviso,
                    chunk_type=c.chunk_type,
                )
            )

        # Record metrics
        try:
            CHUNKS_CREATED_TOTAL.labels(strategy="hierarchical").inc(len(ordered_chunks))
            for c in ordered_chunks:
                CHUNK_TOKEN_COUNT.observe(c.token_count)
        except Exception as err:
            logger.debug("chunking.metric_error", error=str(err))

        return ordered_chunks

    def _sliding_window_fallback(self, text: str) -> list[HierarchicalChunk]:
        """Sliding window fallback respecting exact offsets and token boundaries."""
        from app.ingest.chunk import chunk_document

        legacy_chunks = chunk_document(
            text,
            token_counter=self.token_counter,
            max_tokens=self.config.max_chunk_tokens,
        )

        converted: list[HierarchicalChunk] = []
        for c in legacy_chunks:
            has_prov = bool(PAT_PROVISO.search(c.text))
            c_id = uuid.uuid4()
            converted.append(
                HierarchicalChunk(
                    chunk_id=c_id,
                    parent_chunk_id=None,
                    ordinal=c.ordinal,
                    text=c.text,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    token_count=c.token_count,
                    clause_hierarchy=["Sliding Window Body"],
                    is_proviso=has_prov,
                    chunk_type="proviso" if has_prov else "standard",
                )
            )

        try:
            CHUNKS_CREATED_TOTAL.labels(strategy="sliding_window").inc(len(converted))
            for hc in converted:
                CHUNK_TOKEN_COUNT.observe(hc.token_count)
        except Exception as err:
            logger.debug("chunking.metric_error", error=str(err))

        return converted


def get_default_hierarchical_chunker(
    config: ChunkingConfig | None = None,
    token_counter: TokenCounter | None = None,
) -> HierarchicalChunker:
    """Initialize or return default HierarchicalChunker."""
    return HierarchicalChunker(config=config, token_counter=token_counter)
