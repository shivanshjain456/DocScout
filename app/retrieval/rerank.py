"""Cross-encoder reranking of fused candidates.

What a reranker can and cannot do, stated first because it determines whether the latency
is worth paying. A reranker reorders a list it is given; it can never introduce a chunk
retrieval failed to return. On this corpus the serving configuration already reaches
recall@10 = 1.000 (ADR-0007), so a reranker cannot improve recall at depth 10 by
construction. Its entire possible contribution is at the top of the list, where recall@1
is 0.695 — that is the headroom, and that is what the ablation measures.

Why a cross-encoder rather than a second bi-encoder pass: the dense arm already embeds the
query and the passage independently, so a second independent embedding adds no information.
A cross-encoder reads query and passage together in one forward pass and can therefore
model term interaction — which is the only reason it is worth 100x the cost per pair.

Determinism matters here as much as anywhere else in this project. The model runs in
inference mode with a fixed batch size, and ties in the score are broken by the candidate's
pre-rerank position and then by chunk_id, so two runs of the same configuration produce
byte-identical ordering. A ranking that reshuffles between runs cannot support the 1pp
regression gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cost paid only when the reranker is used
    from sentence_transformers import CrossEncoder

# The model named in ARCHITECTURE.md §3 and measured during Phase 0. Small on purpose: a
# 6-layer MiniLM is the largest cross-encoder that fits the latency budget on 2 vCPU.
MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Pairs scored per forward batch. 16 matched the per-pair cost of 32 in measurement while
# holding less memory, which matters on a 1.9 GiB host.
BATCH_SIZE = 16

# Hard cap on the tokens the cross-encoder reads per pair. Set explicitly rather than left
# to the checkpoint default: this model was trained at 512, and silently inheriting a
# different value from a future sentence-transformers release would change every score
# without changing a line of this repository.
MAX_LENGTH = 512


class RerankError(RuntimeError):
    """The reranker could not produce a usable ordering."""


@dataclass(frozen=True)
class Candidate:
    """Minimal view of a retrieved chunk. Keeps this module independent of Retrieved."""

    chunk_id: str
    text: str


class CrossEncoderReranker:
    """Scores (query, passage) pairs and returns a new ordering.

    Loaded lazily and intended to be constructed once per process: the weights take about
    eleven seconds to load, which would dominate any per-request measurement.
    """

    def __init__(self, model_id: str = MODEL_ID, *, batch_size: int = BATCH_SIZE) -> None:
        self.model_id = model_id
        self.batch_size = batch_size
        self._model: CrossEncoder | None = None

    def _load(self) -> CrossEncoder:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_id, device="cpu", max_length=MAX_LENGTH)
        return self._model

    def warm(self) -> None:
        """Force the weights to load now.

        Called at server startup for the same reason the embedder is: a model that loads
        inside the first request makes that request's latency a measurement of disk I/O.
        """
        self._load().predict(
            [("warmup query", "warmup passage")],
            batch_size=1,
            show_progress_bar=False,
        )

    def score(self, query: str, candidates: list[Candidate]) -> list[float]:
        """Relevance scores, one per candidate, in the order given."""
        if not candidates:
            return []
        pairs = [(query, candidate.text) for candidate in candidates]
        raw = self._load().predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        scores = [float(value) for value in raw]
        if len(scores) != len(candidates):
            raise RerankError(
                f"reranker returned {len(scores)} scores for {len(candidates)} candidates"
            )
        return scores

    def order(self, query: str, candidates: list[Candidate]) -> list[tuple[int, float]]:
        """Return (original_index, score) sorted best first.

        Returning indices rather than rebuilt objects keeps this module free of any
        dependency on the retrieval result type, and lets the caller carry through fields
        the reranker knows nothing about.

        Ties break on the original index, so a reranker that cannot distinguish two
        candidates preserves the fusion order rather than imposing an arbitrary one. That
        is the conservative choice: fusion's ordering is evidence, and a coin flip is not.
        """
        scores = self.score(query, candidates)
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda pair: (-pair[1], pair[0]))
        return indexed
