"""The retriever: one entry point, three configurations, no hidden state.

Why a class holding a connection and a lazily built BM25 index rather than a function:
both the embedding model (~13 s to load) and the BM25 term table are expensive to build
and identical across the 153 gold-set queries. Rebuilding either per query would make the
eval run twenty minutes long and the latency numbers meaningless -- they would measure
model loading, not retrieval.

Why the arms are fetched independently and fused afterwards, rather than one SQL statement
doing both: the ablation in ADR-0006 needs dense-only and bm25-only to be the *same code
path* as hybrid minus a step. A single fused query would mean the single-arm numbers came
from different code than the hybrid number, and the comparison would not be clean.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from app.ingest.embed import Embedder
from app.retrieval import dense, fusion
from app.retrieval.lexical import BM25Index
from app.retrieval.types import RetrievalConfig, Retrieved
from app.rowtypes import as_int, as_str


@dataclass
class _ChunkRow:
    document_id: str
    source: str
    text: str
    canonical_url: str | None
    char_start: int
    char_end: int


class Retriever:
    """Executes a RetrievalConfig against the corpus."""

    def __init__(
        self,
        conn: psycopg.Connection[tuple[object, ...]],
        *,
        embedder: Embedder | None = None,
        bm25: BM25Index | None = None,
    ) -> None:
        self._conn = conn
        self._embedder = embedder if embedder is not None else Embedder()
        # Injectable because building the term table costs a full scan of chunks. A server
        # builds it once at startup and shares it across requests; rebuilding per request
        # would make every query pay for the corpus.
        self._bm25 = bm25
        self._meta: dict[str, _ChunkRow] = {}

    @property
    def bm25(self) -> BM25Index:
        if self._bm25 is None:
            self._bm25 = BM25Index(self._conn)
        return self._bm25

    def _metadata(self, chunk_ids: list[str]) -> dict[str, _ChunkRow]:
        """Fetch display metadata for ids not already cached."""
        missing = [c for c in chunk_ids if c not in self._meta]
        if missing:
            rows = self._conn.execute(
                """
                SELECT c.chunk_id::text, c.document_id::text, d.source, c.text,
                       d.canonical_url, c.char_start, c.char_end
                FROM chunks AS c JOIN documents AS d ON d.document_id = c.document_id
                WHERE c.chunk_id = ANY(%s::uuid[])
                """,
                (missing,),
            ).fetchall()
            for chunk_id, document_id, source, text, url, start, end in rows:
                self._meta[as_str(chunk_id)] = _ChunkRow(
                    document_id=as_str(document_id),
                    source=as_str(source),
                    text=as_str(text),
                    canonical_url=None if url is None else as_str(url),
                    char_start=as_int(start),
                    char_end=as_int(end),
                )
        return self._meta

    def retrieve(self, query: str, config: RetrievalConfig) -> list[Retrieved]:
        arms: dict[str, list[str]] = {}
        raw_scores: dict[str, float] = {}

        if config.mode in ("dense", "hybrid"):
            vector = self._embedder.encode_query(query)
            hits = dense.search(self._conn, vector, config.k_dense)
            arms["dense"] = [cid for cid, _ in hits]
            raw_scores.update({cid: score for cid, score in hits})

        if config.mode in ("bm25", "hybrid"):
            hits = self.bm25.search(self._conn, query, config.k_lexical)
            arms["lexical"] = [cid for cid, _ in hits]
            for cid, score in hits:
                raw_scores.setdefault(cid, score)

        if config.mode == "hybrid":
            fused = fusion.reciprocal_rank_fusion(
                arms,
                weights={"dense": config.weight_dense, "lexical": config.weight_lexical},
                rrf_k=config.rrf_k,
            )
        else:
            arm = "dense" if config.mode == "dense" else "lexical"
            # Single-arm runs keep the raw score, not a fused one. Reporting an RRF score
            # for a configuration that never fused anything would be a fabricated number.
            fused = [(cid, raw_scores[cid], {arm: i + 1}) for i, cid in enumerate(arms[arm])]

        top = fused[: config.k_final]
        if config.anchor_arm_top1 and config.mode == "hybrid":
            top = _anchor_arm_leaders(top, arms, fused, config.k_final)
        meta = self._metadata([cid for cid, _, _ in top])
        results: list[Retrieved] = []
        for index, (chunk_id, score, arm_ranks) in enumerate(top):
            row = meta.get(chunk_id)
            results.append(
                Retrieved(
                    chunk_id=chunk_id,
                    rank=index + 1,
                    score=float(score),
                    document_id=row.document_id if row else "",
                    source=row.source if row else "",
                    text=row.text if row else "",
                    arm_ranks=dict(arm_ranks),
                    canonical_url=row.canonical_url if row else None,
                    char_start=row.char_start if row else 0,
                    char_end=row.char_end if row else 0,
                )
            )
        return results


def _anchor_arm_leaders(
    top: list[tuple[str, float, dict[str, int]]],
    arms: dict[str, list[str]],
    fused: list[tuple[str, float, dict[str, int]]],
    k_final: int,
) -> list[tuple[str, float, dict[str, int]]]:
    """Ensure every arm's own rank-1 chunk survives into the returned k.

    Fusion by rank alone cannot express certainty: an arm that put a chunk first contributes
    the same 1/(k+1) whether it was certain or barely preferred it. When the other arm
    disagrees, consensus beats conviction and the confident arm's best answer can fall out of
    the result set entirely -- measured on g-038, where BM25 ranked the correct chunk first
    and the fused rank was 14.

    A reserved seat is the narrowest possible fix: it changes nothing about how the other
    results are scored or ordered, and it is bounded -- at most one chunk per arm. Any chunk
    inserted keeps its real fused score, so the report never shows a fabricated number.
    """
    present = {chunk_id for chunk_id, _, _ in top}
    scores = {chunk_id: (score, ranks) for chunk_id, score, ranks in fused}
    missing = [ids[0] for ids in arms.values() if ids and ids[0] not in present]
    if not missing:
        return top
    # Drop from the tail to make room, so the highest-fused results are never displaced.
    keep = top[: max(0, k_final - len(missing))]
    for chunk_id in missing:
        score, ranks = scores.get(chunk_id, (0.0, {}))
        keep.append((chunk_id, score, ranks))
    return keep[:k_final]
