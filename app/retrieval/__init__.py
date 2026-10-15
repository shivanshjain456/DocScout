"""Retrieval over the ingested corpus: a dense arm, a BM25 arm, and RRF over both."""

from __future__ import annotations

from app.retrieval.confidence import (
    ConfidenceConfig,
    assess_passages,
)
from app.retrieval.context_packer import ContextPacker, pack_context
from app.retrieval.dense import (
    DiscriminativeCalibrator,
    DiscriminativeConfig,
    DiscriminativeProjector,
    HardNegativeDataset,
    NegativeMiningConfig,
    get_default_calibrator,
)
from app.retrieval.multilingual_dense import (
    CrossLingualProjector,
    MultilingualDenseStore,
)
from app.retrieval.search import Retriever, anchor_arm_leaders
from app.retrieval.section_expander import (
    ExpandedPassage,
    SectionExpander,
    SiblingChunk,
    expand_section_context,
)
from app.retrieval.span_pinpoint import (
    HighlightConfig,
    SpanPinpointer,
    decorate_retrieved_highlights,
    pinpoint_highlights,
)
from app.retrieval.types import (
    DEFAULT_RRF_K,
    SERVING_CONFIG,
    ContextPackerConfig,
    PackedContext,
    RetrievalConfig,
    Retrieved,
)

__all__ = [
    "ConfidenceConfig",
    "ContextPacker",
    "ContextPackerConfig",
    "CrossLingualProjector",
    "DEFAULT_RRF_K",
    "DiscriminativeCalibrator",
    "DiscriminativeConfig",
    "DiscriminativeProjector",
    "ExpandedPassage",
    "HardNegativeDataset",
    "HighlightConfig",
    "MultilingualDenseStore",
    "NegativeMiningConfig",
    "PackedContext",
    "RetrievalConfig",
    "Retrieved",
    "Retriever",
    "SERVING_CONFIG",
    "SectionExpander",
    "SiblingChunk",
    "SpanPinpointer",
    "anchor_arm_leaders",
    "assess_passages",
    "decorate_retrieved_highlights",
    "expand_section_context",
    "get_default_calibrator",
    "pack_context",
    "pinpoint_highlights",
]
