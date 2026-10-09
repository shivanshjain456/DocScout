"""Shared value types for retrieval.

Why a separate module rather than defining these beside the retriever: the dense arm, the
lexical arm and the fusion step all need the same result shape, and importing that shape
from whichever arm happened to define it would make the arms depend on each other. They
must stay independent -- the A/B in ADR-0006 only means something if dense-only can run
with the lexical arm entirely absent from the call graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.retrieval.rerank import MODEL_ID as RERANK_MODEL_ID

Mode = Literal["dense", "bm25", "hybrid"]
ExpansionMode = Literal["none", "synonym", "hyde", "combined"]

# Reciprocal Rank Fusion's smoothing constant. 60 is the value from Cormack et al. (2009),
# which is also what every mainstream implementation defaults to. It is not tuned here: it
# is held fixed so the dense/lexical/hybrid comparison varies one thing at a time.
DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class ChunkMeta:
    """Core metadata stored alongside chunks for filtering and attribution."""

    chunk_id: str
    document_id: str
    source: str
    published_date: date | None
    fetch_ts: datetime | None
    is_current: bool
    canonical_url: str | None = None


class MetadataFilter(BaseModel):
    """Declarative metadata filter specification for in-query pruning (P1-2).

    Enables bounding regulatory retrieval by authority (RBI, SEBI), issuance
    date windows (date_from, date_to), version status (is_current), or specific
    document UUIDs / canonical URLs.
    """

    model_config = ConfigDict(extra="forbid")

    source: str | list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    is_current: bool | None = True
    document_ids: list[str] | None = None
    canonical_url: str | None = None

    def canonical_tuple(self) -> tuple[Any, ...]:
        """Deterministic hashable representation for query caching."""
        src: tuple[str, ...] | None = None
        if isinstance(self.source, str):
            src = (self.source,)
        elif isinstance(self.source, (list, tuple, set)):
            src = tuple(sorted(self.source))

        doc_ids: tuple[str, ...] | None = None
        if self.document_ids:
            doc_ids = tuple(sorted(self.document_ids))

        return (
            src,
            self.date_from.isoformat() if self.date_from else None,
            self.date_to.isoformat() if self.date_to else None,
            self.is_current,
            doc_ids,
            self.canonical_url,
        )

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def matches(self, meta: ChunkMeta | None) -> bool:
        """Predicate evaluation against in-memory chunk metadata for BM25 pruning."""
        if meta is None:
            return False

        if self.is_current is not None and meta.is_current != self.is_current:
            return False

        if self.source is not None:
            allowed = {self.source} if isinstance(self.source, str) else set(self.source)
            if meta.source not in allowed:
                return False

        doc_date = meta.published_date
        if doc_date is None and meta.fetch_ts is not None:
            doc_date = meta.fetch_ts.date()

        if doc_date is not None:
            if self.date_from is not None and doc_date < self.date_from:
                return False
            if self.date_to is not None and doc_date > self.date_to:
                return False
        elif self.date_from is not None or self.date_to is not None:
            return False

        if self.document_ids is not None and meta.document_id not in self.document_ids:
            return False

        if self.canonical_url is not None and meta.canonical_url != self.canonical_url:
            return False

        return True


@dataclass(frozen=True)
class Retrieved:
    """One chunk returned by a retriever, with the provenance needed to explain its rank."""

    chunk_id: str
    rank: int
    score: float
    document_id: str
    source: str
    text: str
    # Rank this chunk held in each contributing arm, 1-based. Empty for single-arm runs.
    # Kept because "why did hybrid beat dense here" is unanswerable without it, and that
    # question is the entire point of the ablation.
    arm_ranks: dict[str, int] = field(default_factory=dict)
    # The span this chunk occupies in its source document, and the document's public URL.
    # A citation that cannot be resolved back to specific bytes in a specific document is
    # not a citation; ADR-0005 made chunk ids stable so this stays true across re-ingests.
    # Defaulted so existing callers that only need ranking are unaffected.
    canonical_url: str | None = None
    char_start: int = 0
    char_end: int = 0


@dataclass(frozen=True)
class RetrievalConfig:
    """A named, fully-specified retrieval configuration.

    Every field that can change a result appears here, and the runner serialises this
    object verbatim into results.json. E-14 requires a report to carry the parameters that
    produced it; a config that is partly implicit in code cannot satisfy that.
    """

    name: str
    mode: Mode = "hybrid"
    # Depth of each arm BEFORE fusion. Deeper arms give fusion more to work with and cost
    # more; held equal across arms so neither is handicapped by candidate count.
    k_dense: int = 50
    k_lexical: int = 50
    # Results returned after fusion. Metrics are reported at k <= this.
    k_final: int = 10
    rrf_k: int = DEFAULT_RRF_K
    # Per-arm fusion weights. 1.0/1.0 is unweighted RRF.
    weight_dense: float = 1.0
    weight_lexical: float = 1.0
    # Guarantee each arm's own top hit a seat in the final k, even if fusion ranked it out.
    # RRF scores by 1/(k + rank), so at rrf_k=60 the gap between rank 1 and rank 41 is only
    # 1.66x: a chunk both arms rank near the top outranks a chunk one arm is CERTAIN about.
    # Measured on gold item g-038, where BM25 ranked the answer first and fusion buried it at
    # 14. This reserves a seat rather than re-weighting, so no other result is reordered.
    anchor_arm_top1: bool = False
    # Cross-encoder reranking of the fused candidates. Off by default: it is the single
    # most expensive stage in the pipeline and ADR-0009 decides when it earns that cost.
    rerank: bool = False
    # How many fused candidates the cross-encoder scores. Must be >= k_final, or the
    # reranker would be asked to choose the top k from fewer than k candidates, which
    # quietly degrades to "no reranking" while still charging for the model.
    rerank_top_n: int = 20
    filter: MetadataFilter | None = None
    expand_query: bool = False
    expansion_mode: ExpansionMode = "none"

    def __post_init__(self) -> None:
        if self.rerank and self.rerank_top_n < self.k_final:
            raise ValueError(
                f"rerank_top_n ({self.rerank_top_n}) must be >= k_final ({self.k_final}); "
                "reranking fewer candidates than are returned pays for the model without "
                "giving it anything to reorder"
            )
        if self.expand_query and self.expansion_mode == "none":
            object.__setattr__(self, "expansion_mode", "synonym")
        elif self.expansion_mode != "none" and not self.expand_query:
            object.__setattr__(self, "expand_query", True)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "mode": self.mode,
            "k_dense": self.k_dense,
            "k_lexical": self.k_lexical,
            "k_final": self.k_final,
            "rrf_k": self.rrf_k,
            "weight_dense": self.weight_dense,
            "weight_lexical": self.weight_lexical,
            "anchor_arm_top1": self.anchor_arm_top1,
            "rerank": self.rerank,
            "rerank_top_n": self.rerank_top_n if self.rerank else None,
            "rerank_model": RERANK_MODEL_ID if self.rerank else None,
            "filter": self.filter.as_dict() if self.filter else None,
            "expand_query": self.expand_query,
            "expansion_mode": self.expansion_mode,
        }


# The configuration DocScout actually serves, defined once so the eval runner, the
# regression gate and any future API cannot drift apart. A bare RetrievalConfig(mode=
# "hybrid") is deliberately NOT the serving shape: it omits the arm-anchor fix, and a
# caller who forgets it would silently ship the g-038 defect again.
SERVING_CONFIG = RetrievalConfig(
    name="hybrid-rrf",
    mode="hybrid",
    k_dense=50,
    k_lexical=50,
    k_final=10,
    rrf_k=DEFAULT_RRF_K,
    anchor_arm_top1=True,
)
