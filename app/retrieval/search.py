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

import psycopg

from app.ingest.embed import Embedder
from app.retrieval import confidence as confidence_module
from app.retrieval import fusion
from app.retrieval.expansion import DomainQueryExpander, get_default_expander
from app.retrieval.lexical import BM25Index
from app.retrieval.port import ChunkRow, VectorStore, get_vector_store
from app.retrieval.rerank import Candidate, CrossEncoderReranker
from app.retrieval.types import RetrievalConfig, Retrieved

# Backwards compatibility alias
_ChunkRow = ChunkRow


class Retriever:
    """Executes a RetrievalConfig against the corpus."""

    def __init__(
        self,
        conn: psycopg.Connection[tuple[object, ...]] | None = None,
        *,
        embedder: Embedder | None = None,
        bm25: BM25Index | None = None,
        reranker: CrossEncoderReranker | None = None,
        expander: DomainQueryExpander | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        if conn is None and vector_store is None:
            raise ValueError(
                "Retriever requires either an active database connection or a VectorStore adapter"
            )
        self._conn = conn
        self._embedder = embedder if embedder is not None else Embedder()
        # Injectable because building the term table costs a full scan of chunks. A server
        # builds it once at startup and shares it across requests; rebuilding per request
        # would make every query pay for the corpus.
        self._bm25 = bm25
        # Injectable and lazily constructed for the same reason as the BM25 index: the
        # cross-encoder weights take ~11 s to load and must be shared, not per request.
        self._reranker = reranker
        self._expander = expander
        self._vector_store = vector_store
        self._meta: dict[str, ChunkRow] = {}

    def get_vector_store(self, adapter_name: str = "pgvector") -> VectorStore:
        """Resolve vector store adapter from direct injection or registry."""
        if self._vector_store is not None:
            return self._vector_store
        return get_vector_store(adapter_name, conn=self._conn)

    @property
    def bm25(self) -> BM25Index:
        if self._bm25 is None:
            if self._conn is None:
                raise RuntimeError("BM25Index requires an active database connection")
            self._bm25 = BM25Index(self._conn)
        return self._bm25

    @property
    def reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = CrossEncoderReranker()
        return self._reranker

    @property
    def expander(self) -> DomainQueryExpander:
        if self._expander is None:
            self._expander = get_default_expander()
        return self._expander

    def _rerank(
        self,
        query: str,
        fused: list[tuple[str, float, dict[str, int]]],
        arms: dict[str, list[str]],
        config: RetrievalConfig,
    ) -> list[tuple[str, float, dict[str, int]]]:
        """Reorder the head of the fused list with the cross-encoder.

        The pool is the top `rerank_top_n` fused candidates UNION each arm's own rank-1
        chunk. Including the arm leaders matters for two reasons: ADR-0007 guarantees them
        a seat in the result, and if one were anchored in from outside the pool it would
        carry an RRF score while everything around it carried a cross-encoder score --
        two incomparable units in one `score` column.
        """
        pool_ids = [chunk_id for chunk_id, _, _ in fused[: config.rerank_top_n]]
        seen = set(pool_ids)
        for arm_ids in arms.values():
            if arm_ids and arm_ids[0] not in seen:
                seen.add(arm_ids[0])
                pool_ids.append(arm_ids[0])

        meta = self._metadata(
            pool_ids,
            is_current=config.filter.is_current if config.filter is not None else True,
            adapter_name=config.vector_store_adapter,
        )
        candidates = [
            Candidate(chunk_id=chunk_id, text=meta[chunk_id].text if chunk_id in meta else "")
            for chunk_id in pool_ids
        ]
        ranks = {chunk_id: arm_ranks for chunk_id, _, arm_ranks in fused}
        ordered = [
            (pool_ids[index], score, ranks.get(pool_ids[index], {}))
            for index, score in self.reranker.order(query, candidates)
        ]
        # The untouched tail keeps its RRF score. It is unreachable whenever
        # rerank_top_n >= k_final, which __post_init__ enforces, and is kept so the list
        # stays a complete ranking rather than a truncated one.
        tail = [entry for entry in fused if entry[0] not in seen]
        return ordered + tail

    def _metadata(
        self,
        chunk_ids: list[str],
        is_current: bool | None = True,
        adapter_name: str = "pgvector",
    ) -> dict[str, ChunkRow]:
        """Fetch display metadata for ids not already cached via the vector store port."""
        missing = [c for c in chunk_ids if c not in self._meta]
        if missing:
            store = self.get_vector_store(adapter_name)
            fetched = store.fetch_metadata(missing, is_current=is_current)
            self._meta.update(fetched)
        return self._meta

    def assess_confidence(
        self, query: str, results: list[Retrieved]
    ) -> confidence_module.Confidence:
        """How much of the question the returned passages actually cover.

        Separate from `retrieve` rather than folded into it: the eval harness sweeps the
        threshold over the whole gold set and needs the raw coverage, and a caller that
        does not want the extra BM25 lookups should not pay for them.
        """
        if self._conn is not None:
            terms = self.bm25.query_terms(self._conn, query)
        else:
            terms = [t for t in query.lower().split() if len(t) > 2]
        passage_terms = [self.bm25.lexemes_of(hit.chunk_id) for hit in results]
        return confidence_module.assess(terms, passage_terms)

    def retrieve(self, query: str, config: RetrievalConfig) -> list[Retrieved]:
        arms: dict[str, list[str]] = {}
        raw_scores: dict[str, float] = {}
        filter_spec = config.filter

        dense_query = query
        lexical_query = query
        if config.expand_query:
            expanded = self.expander.expand(query, mode=config.expansion_mode)
            dense_query = expanded.dense_query
            lexical_query = expanded.lexical_query

        store = self.get_vector_store(config.vector_store_adapter)

        if config.mode in ("dense", "hybrid", "graph-hybrid"):
            vector = self._embedder.encode_query(dense_query)
            hits = store.search(vector, config.k_dense, filter=filter_spec)
            arms["dense"] = [cid for cid, _ in hits]
            raw_scores.update({cid: score for cid, score in hits})

        if config.mode in ("bm25", "hybrid", "graph-hybrid"):
            if self._conn is None:
                raise RuntimeError("BM25 lexical search requires an active database connection")
            hits = self.bm25.search(self._conn, lexical_query, config.k_lexical, filter=filter_spec)
            arms["lexical"] = [cid for cid, _ in hits]
            for cid, score in hits:
                raw_scores.setdefault(cid, score)

        if config.mode == "graph-hybrid":
            seed_ids: list[str] = []
            if "dense" in arms:
                seed_ids.extend(arms["dense"][:5])
            if "lexical" in arms:
                seed_ids.extend([cid for cid in arms["lexical"][:5] if cid not in seed_ids])

            if self._conn is not None and seed_ids:
                from app.retrieval.graph import traverse_graph_neighbors

                graph_res = traverse_graph_neighbors(self._conn, seed_ids)
                if graph_res.expanded_chunks:
                    arms["graph"] = [cid for cid, _ in graph_res.expanded_chunks]

            weights = {
                "dense": config.weight_dense,
                "lexical": config.weight_lexical,
            }
            if "graph" in arms:
                weights["graph"] = 0.85

            fused = fusion.reciprocal_rank_fusion(
                arms,
                weights=weights,
                rrf_k=config.rrf_k,
            )
        elif config.mode == "hybrid":
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

        if config.rerank:
            fused = self._rerank(query, fused, arms, config)

        top = fused[: config.k_final]
        if config.anchor_arm_top1 and config.mode in ("hybrid", "graph-hybrid"):
            top = _anchor_arm_leaders(top, arms, fused, config.k_final)
        is_curr = filter_spec.is_current if filter_spec is not None else True
        meta = self._metadata(
            [cid for cid, _, _ in top],
            is_current=is_curr,
            adapter_name=config.vector_store_adapter,
        )

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
                    title=row.title if row else None,
                    published_date=row.published_date if row else None,
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
