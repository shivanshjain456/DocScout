"""Shared value types for retrieval.

Why a separate module rather than defining these beside the retriever: the dense arm, the
lexical arm and the fusion step all need the same result shape, and importing that shape
from whichever arm happened to define it would make the arms depend on each other. They
must stay independent -- the A/B in ADR-0006 only means something if dense-only can run
with the lexical arm entirely absent from the call graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.retrieval.rerank import MODEL_ID as RERANK_MODEL_ID

Mode = Literal["dense", "bm25", "hybrid"]

# Reciprocal Rank Fusion's smoothing constant. 60 is the value from Cormack et al. (2009),
# which is also what every mainstream implementation defaults to. It is not tuned here: it
# is held fixed so the dense/lexical/hybrid comparison varies one thing at a time.
DEFAULT_RRF_K = 60


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

    def __post_init__(self) -> None:
        if self.rerank and self.rerank_top_n < self.k_final:
            raise ValueError(
                f"rerank_top_n ({self.rerank_top_n}) must be >= k_final ({self.k_final}); "
                "reranking fewer candidates than are returned pays for the model without "
                "giving it anything to reorder"
            )

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
