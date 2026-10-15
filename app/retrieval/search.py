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

from typing import TYPE_CHECKING, Any

import psycopg
import structlog

if TYPE_CHECKING:
    from app.retrieval.query_tagger import QueryTagger

from app.ingest.embed import Embedder
from app.retrieval import confidence as confidence_module
from app.retrieval import fusion
from app.retrieval.expansion import DomainQueryExpander, get_default_expander
from app.retrieval.graph_retriever import GraphRetriever
from app.retrieval.lexical import BM25Index
from app.retrieval.port import ChunkRow, VectorStore, get_vector_store
from app.retrieval.rerank import Candidate, CrossEncoderReranker
from app.retrieval.types import RetrievalConfig, Retrieved

# Backwards compatibility alias
_ChunkRow = ChunkRow

logger = structlog.get_logger(__name__)


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
        graph_retriever: GraphRetriever | None = None,
        authority_resolver: Any | None = None,
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
        self._graph_retriever = graph_retriever
        self._authority_resolver = authority_resolver
        self._meta: dict[str, ChunkRow] = {}

    @property
    def authority_resolver(self) -> Any:
        if self._authority_resolver is None:
            from app.retrieval.authority import get_default_authority_resolver

            self._authority_resolver = get_default_authority_resolver()
        return self._authority_resolver

    @property
    def graph_retriever(self) -> GraphRetriever:
        if self._graph_retriever is None:
            self._graph_retriever = GraphRetriever()
        return self._graph_retriever

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

    @property
    def query_tagger(self) -> QueryTagger:
        if getattr(self, "_query_tagger", None) is None:
            from app.retrieval.query_tagger import get_default_query_tagger

            self._query_tagger = get_default_query_tagger()
        return self._query_tagger

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
        # Clamp rerank_top_n to max 64 per FEAT-071
        effective_top_n = min(config.rerank_top_n, 64)
        pool_ids = [chunk_id for chunk_id, _, _ in fused[:effective_top_n]]
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
        fused_scores = {chunk_id: score for chunk_id, score, _ in fused}

        ordered_indices = self.reranker.order(
            query,
            candidates,
            batch_size=config.rerank_batch_size,
            timeout_ms=config.rerank_timeout_ms,
        )

        if getattr(self.reranker, "last_circuit_breaker_tripped", False):
            # Pre-rerank RRF candidate ranking returned without score disruption
            ordered = [
                (
                    pool_ids[index],
                    fused_scores.get(pool_ids[index], 0.0),
                    ranks.get(pool_ids[index], {}),
                )
                for index, _ in ordered_indices
            ]
        else:
            ordered = [
                (pool_ids[index], score, ranks.get(pool_ids[index], {}))
                for index, score in ordered_indices
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

    def _find_relationship_chunks(self, relation_type: str) -> set[str]:
        """Resolve chunk IDs matching the specified ontological relationship (FEAT-008)."""
        matching: set[str] = set()
        if self._conn is not None:
            # 1. Join taxonomy_edges on relation_type
            try:
                edge_rows = self._conn.execute(
                    """
                    SELECT e.chunk_id::text, c.chunk_id::text
                    FROM taxonomy_edges e
                    LEFT JOIN chunks c ON c.document_id = e.document_id
                    JOIN documents d ON d.document_id = COALESCE(e.document_id, c.document_id)
                    WHERE e.relation_type = %s AND NOT d.is_synthetic
                    """,
                    (relation_type,),
                ).fetchall()
                for e_cid, c_cid in edge_rows:
                    if e_cid:
                        matching.add(str(e_cid))
                    if c_cid:
                        matching.add(str(c_cid))
            except Exception:
                logger.debug("taxonomy_edges_query_skipped", exc_info=True)

            # 2. If 'supersedes', also join circular_citations
            if relation_type == "supersedes":
                try:
                    cit_rows = self._conn.execute(
                        """
                        SELECT c.chunk_id::text
                        FROM circular_citations cc
                        JOIN chunks c ON c.document_id = cc.source_document_id
                        JOIN documents d ON d.document_id = cc.source_document_id
                        WHERE (cc.relation_type = 'supersedes' OR cc.relation_type IS NULL)
                          AND NOT d.is_synthetic
                        """,
                    ).fetchall()
                    for (cid,) in cit_rows:
                        if cid:
                            matching.add(str(cid))
                except Exception:
                    logger.debug("circular_citations_query_skipped", exc_info=True)

        return matching

    def retrieve(self, query: str, config: RetrievalConfig) -> list[Retrieved]:
        arms: dict[str, list[str]] = {}
        raw_scores: dict[str, float] = {}
        filter_spec = config.filter

        working_query = query
        if getattr(config, "enable_normalization", True):
            try:
                from app.retrieval.normalizer import get_default_normalizer

                normalized_res = get_default_normalizer().normalize(query)
                working_query = normalized_res.normalized_query
            except Exception as exc:
                logger.warning("normalizer_failed", error=str(exc))

        if getattr(config, "auto_constrain_tags", False) and len(working_query.strip()) >= 3:
            try:
                extracted = self.query_tagger.extract_tags(working_query)
                if extracted:
                    self.query_tagger.record_metrics(extracted)
                    filter_spec = self.query_tagger.translate_to_filter(extracted, filter_spec)
                    logger.debug(
                        "search.auto_constrained_by_tags", query=working_query, tags=extracted
                    )
            except Exception as exc:
                logger.warning("query_tagger_failed", error=str(exc))

        dense_query = working_query
        lexical_query = working_query
        effective_query = working_query
        if getattr(config, "enable_disambiguation", True):
            from app.retrieval.disambiguation import get_token_disambiguator

            disambiguator = get_token_disambiguator()
            effective_query, _ = disambiguator.disambiguate_query(working_query)
            dense_query = effective_query
            lexical_query = effective_query

        if config.expand_query:
            if config.expansion_mode == "hyde":
                from app.retrieval.hyde import get_default_hyde_generator

                dense_query = get_default_hyde_generator().generate_hypothesis(effective_query)
                lexical_query = effective_query
            elif config.expansion_mode == "combined":
                from app.retrieval.hyde import get_default_hyde_generator

                expanded = self.expander.expand(effective_query, mode="synonym")
                dense_query = get_default_hyde_generator().generate_hypothesis(effective_query)
                lexical_query = expanded.lexical_query
            else:
                expanded = self.expander.expand(effective_query, mode=config.expansion_mode)
                dense_query = expanded.dense_query
                lexical_query = expanded.lexical_query

        store = self.get_vector_store(config.vector_store_adapter)

        if config.mode in ("dense", "hybrid", "graph-hybrid"):
            vector = self._embedder.encode_query(dense_query)
            try:
                hits = store.search(
                    vector, config.k_dense, filter=filter_spec, query_text=dense_query
                )
            except TypeError:
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

        # Relationship-filtered constraint (FEAT-008)
        if config.relationship_filter is not None:
            rel_chunks = self._find_relationship_chunks(config.relationship_filter)
            # If relationship join yields zero matches, return empty result list with confidence 0.0
            if not rel_chunks:
                return []
            for arm_name in list(arms.keys()):
                arms[arm_name] = [cid for cid in arms[arm_name] if cid in rel_chunks]
            if not any(arms.values()):
                return []

        if config.mode == "graph-hybrid" or (config.mode == "hybrid" and config.enable_gar):
            seed_ids: list[str] = []
            if "dense" in arms:
                seed_ids.extend(arms["dense"][:5])
            if "lexical" in arms:
                seed_ids.extend([cid for cid in arms["lexical"][:5] if cid not in seed_ids])

            if config.enable_gar:
                gar_candidates = self.graph_retriever.safe_traverse(
                    query=query,
                    max_hops=config.gar_max_hops,
                    decay_factor=config.gar_decay_factor,
                )
                if gar_candidates:
                    arms["graph"] = [cid for cid, _ in gar_candidates]

            if "graph" not in arms and self._conn is not None and seed_ids:
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

        # Graph Degree Centrality Query Boosting (FEAT-009)
        boost_records: dict[str, float] = {}
        if config.enable_centrality_boost:
            try:
                from app.retrieval.centrality import get_centrality_index, is_broad_thematic_query

                is_broad, spec_score = is_broad_thematic_query(query, config.broad_query_threshold)
                if is_broad:
                    centrality_idx = get_centrality_index(self._conn)
                    cand_ids = [cid for cid, _, _ in fused[: max(config.k_final * 2, 20)]]
                    cand_meta = self._metadata(
                        cand_ids,
                        is_current=filter_spec.is_current if filter_spec is not None else True,
                        adapter_name=config.vector_store_adapter,
                    )
                    boosted_fused: list[tuple[str, float, dict[str, int]]] = []
                    for cid, score, arm_ranks in fused:
                        row = cand_meta.get(cid)
                        c_val = centrality_idx.get_centrality(
                            chunk_id=cid,
                            document_id=row.document_id if row else None,
                            title=row.title if row else None,
                            text=row.text if row else None,
                        )
                        boosted_score, boost_amount = centrality_idx.compute_boost(
                            score, c_val, config.centrality_weight
                        )
                        boost_records[cid] = boost_amount
                        boosted_fused.append((cid, boosted_score, arm_ranks))

                    # Re-sort candidates by boosted score descending with deterministic tie-breaking
                    boosted_fused.sort(key=lambda item: (-item[1], item[0]))
                    fused = boosted_fused

                    mean_boost = (
                        sum(boost_records.values()) / len(boost_records) if boost_records else 0.0
                    )
                    logger.info(
                        "search_centrality_boost_applied",
                        query=query,
                        is_broad=True,
                        specificity=spec_score,
                        mean_centrality_boost=round(mean_boost, 6),
                        candidates_boosted=len(boost_records),
                    )
                    try:
                        from app.api.metrics import CENTRALITY_BOOSTED_QUERIES_TOTAL

                        CENTRALITY_BOOSTED_QUERIES_TOTAL.labels(query_type="broad").inc()
                    except Exception:
                        logger.debug("centrality_boost_metric_failed", exc_info=True)
                else:
                    logger.debug(
                        "search_centrality_boost_skipped",
                        query=query,
                        is_broad=False,
                        specificity=spec_score,
                        reason="narrow_specific_query",
                    )
            except Exception as exc:
                logger.warning("centrality_boost_failed", error=str(exc))

        # Regulatory Authority Hierarchy Resolver (FEAT-045)
        applied_authority: dict[str, Any] = {}
        if config.enable_authority_hierarchy:
            try:
                from app.retrieval.authority import AuthorityConfig, RegulatoryAuthorityResolver

                auth_cfg = (
                    AuthorityConfig(tier_multipliers=config.authority_multipliers)
                    if config.authority_multipliers
                    else None
                )
                resolver = (
                    RegulatoryAuthorityResolver(auth_cfg)
                    if auth_cfg is not None
                    else self.authority_resolver
                )

                cand_ids = [cid for cid, _, _ in fused[: max(config.k_final * 3, 30)]]
                cand_meta = self._metadata(
                    cand_ids,
                    is_current=filter_spec.is_current if filter_spec is not None else True,
                    adapter_name=config.vector_store_adapter,
                )

                auth_boosted: list[tuple[str, float, dict[str, int]]] = []
                for cid, score, arm_ranks in fused:
                    row = cand_meta.get(cid)
                    doc_cls = row.document_class if row else None
                    title_val = row.title if row else None
                    tier_val = row.authority_tier if row else None
                    boosted_score, weight = resolver.compute_boost(
                        score, doc_cls, title=title_val, authority_tier=tier_val
                    )
                    applied_authority[cid] = weight
                    auth_boosted.append((cid, boosted_score, arm_ranks))

                # Re-sort candidates by boosted score descending with deterministic tie-breaking
                auth_boosted.sort(key=lambda item: (-item[1], item[0]))
                fused = auth_boosted

                if fused:
                    top_cid = fused[0][0]
                    top_weight = applied_authority.get(top_cid)
                    if top_weight:
                        logger.info(
                            "search_authority_hierarchy_applied",
                            query=query,
                            top_chunk_id=top_cid,
                            applied_authority_tier=top_weight.tier,
                            document_class=top_weight.document_class,
                            boost_multiplier=top_weight.boost_multiplier,
                        )
            except Exception as exc:
                logger.warning("authority_hierarchy_boost_failed", error=str(exc))

        top = fused[: config.k_final]
        anchored_provenance: dict[str, str] = {}
        if (
            config.anchor_arm_top1 or getattr(config, "anchor_arm_leaders", False)
        ) and config.mode in (
            "hybrid",
            "graph-hybrid",
        ):
            top = _anchor_arm_leaders(
                top,
                arms,
                fused,
                config.k_final,
                anchored_out=anchored_provenance,
            )
        is_curr = filter_spec.is_current if filter_spec is not None else True
        meta = self._metadata(
            [cid for cid, _, _ in top],
            is_current=is_curr,
            adapter_name=config.vector_store_adapter,
        )

        results: list[Retrieved] = []
        for index, (chunk_id, score, arm_ranks) in enumerate(top):
            row = meta.get(chunk_id)
            matching_rels = [config.relationship_filter] if config.relationship_filter else []
            boost_val = boost_records.get(chunk_id, 0.0)
            text_val = row.text if row else ""
            if config.difficulty_band and text_val:
                from app.retrieval.difficulty import adapt_snippet

                text_val = adapt_snippet(text_val, config.difficulty_band)

            auth_w = applied_authority.get(chunk_id)
            tier_val = auth_w.tier if auth_w else (row.authority_tier if row else None)
            mult_val = auth_w.boost_multiplier if auth_w else 1.0
            doc_cls_val = (
                auth_w.document_class
                if auth_w and auth_w.document_class != "UNKNOWN"
                else (row.document_class if row else None)
            )

            results.append(
                Retrieved(
                    chunk_id=chunk_id,
                    rank=index + 1,
                    score=float(score),
                    document_id=row.document_id if row else "",
                    source=row.source if row else "",
                    text=text_val,
                    arm_ranks=dict(arm_ranks),
                    canonical_url=row.canonical_url if row else None,
                    char_start=row.char_start if row else 0,
                    char_end=row.char_end if row else 0,
                    title=row.title if row else None,
                    published_date=row.published_date if row else None,
                    matching_relationships=matching_rels,
                    centrality_boost=float(boost_val),
                    difficulty_level=config.difficulty_band,
                    authority_tier=tier_val,
                    applied_authority_multiplier=mult_val,
                    document_class=doc_cls_val,
                    is_arm_anchor=chunk_id in anchored_provenance,
                    anchored_arm=anchored_provenance.get(chunk_id),
                    clause_hierarchy=row.clause_hierarchy if row else [],
                    is_proviso=row.is_proviso if row else False,
                )
            )

        if getattr(config, "expand_section_context", False) and self._conn is not None and results:
            try:
                import dataclasses

                from app.retrieval.section_expander import SectionExpander

                expander = SectionExpander(self._conn)
                top_cand = results[0]
                expanded_env = expander.expand(
                    top_cand.chunk_id,
                    max_sibling_clauses=getattr(config, "max_sibling_clauses", 2),
                )
                if expanded_env.sibling_chunks:
                    results[0] = dataclasses.replace(
                        top_cand, expanded_text=expanded_env.expanded_text
                    )
                    logger.info(
                        "section_expansion_applied",
                        core_chunk_id=top_cand.chunk_id,
                        siblings_count=len(expanded_env.sibling_chunks),
                        total_chars=expanded_env.total_chars,
                    )
            except Exception as exc:
                logger.warning("section_expansion_in_retrieval_failed", error=str(exc))

        if getattr(config, "enable_lost_in_middle_reordering", False):
            try:
                from app.retrieval.context_reorder import reorder_context

                results = reorder_context(results)
                logger.info(
                    "context_reordering_applied",
                    context_reordering_applied=True,
                    count=len(results),
                )
            except Exception as exc:
                logger.warning("context_reorder_failed", error=str(exc))

        return results


def anchor_arm_leaders(
    candidates: list[Candidate],
    arm_leaders: dict[str, Candidate],
    k: int,
) -> list[Candidate]:
    """Ensure every retrieval arm's top-1 candidate survives into top-k candidates (FEAT-074).

    Inputs:
        candidates: Reranked or fused candidate list.
        arm_leaders: Mapping from arm name ("lexical", "dense", "graph") to its rank-1 Candidate.
        k: Final desired cutoff depth (must be >= 1).
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not candidates:
        raise ValueError("candidates must not be empty")

    try:
        present = {c.chunk_id for c in candidates[:k]}
        missing: list[tuple[str, Candidate]] = []
        seen_missing: set[str] = set()
        for arm_name, leader in arm_leaders.items():
            if (
                leader is not None
                and leader.chunk_id not in present
                and leader.chunk_id not in seen_missing
            ):
                missing.append((arm_name, leader))
                seen_missing.add(leader.chunk_id)

        if not missing:
            return list(candidates[:k])

        keep = list(candidates[: max(0, k - len(missing))])
        for arm_name, leader in missing:
            try:
                from app.api.metrics import ARM_LEADERS_ANCHORED_TOTAL

                ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name=arm_name).inc()
            except Exception:
                logger.debug("arm_anchoring_metric_failed", exc_info=True)

            anchored_c = Candidate(
                chunk_id=leader.chunk_id,
                text=leader.text,
                score=leader.score,
                arm_ranks=dict(leader.arm_ranks),
                is_arm_anchor=True,
                anchored_arm=arm_name,
            )
            keep.append(anchored_c)

        return keep[:k]
    except Exception as exc:
        logger.warning("arm_anchoring_failed", error=str(exc))
        return list(candidates[:k])


def _anchor_arm_leaders(
    top: Any,
    arms: Any,
    fused: Any = None,
    k_final: int | None = None,
    *,
    k: int | None = None,
    anchored_out: dict[str, str] | None = None,
) -> Any:
    """Ensure every arm's own rank-1 chunk survives into the returned k (FEAT-074, ADR-0007).

    Fusion by rank alone cannot express certainty: an arm that put a chunk first contributes
    the same 1/(k+1) whether it was certain or barely preferred it. When the other arm
    disagrees, consensus beats conviction and the confident arm's best answer can fall out of
    the result set entirely -- measured on g-038, where BM25 ranked the correct chunk first
    and the fused rank was 14.

    A reserved seat is the narrowest possible fix: it changes nothing about how the other
    results are scored or ordered, and it is bounded -- at most one chunk per arm. Any chunk
    inserted keeps its real fused or reranked score, preserving provenance.
    """
    # If called with candidates: list[Candidate], arm_leaders: dict[str, Candidate], k: int
    if isinstance(top, list) and (
        (top and isinstance(top[0], Candidate))
        or (isinstance(arms, dict) and any(isinstance(v, Candidate) for v in arms.values()))
    ):
        target_k = k if k is not None else (k_final if k_final is not None else len(top))
        return anchor_arm_leaders(top, arms, target_k)

    target_k = k_final if k_final is not None else (k if k is not None else 10)
    if target_k < 1:
        raise ValueError(f"k_final must be >= 1, got {target_k}")
    if not top and not fused:
        return top

    try:
        present = {chunk_id for chunk_id, _, _ in top}
        scores = {chunk_id: (score, ranks) for chunk_id, score, ranks in (fused or top)}
        missing: list[tuple[str, str]] = []
        seen_missing: set[str] = set()
        for arm_name, ids in arms.items():
            if ids and ids[0] not in present and ids[0] not in seen_missing:
                missing.append((arm_name, ids[0]))
                seen_missing.add(ids[0])

        if not missing:
            return top

        # Drop from the tail to make room, so the highest-fused results are never displaced.
        keep = list(top[: max(0, target_k - len(missing))])
        for arm_name, chunk_id in missing:
            score, ranks = scores.get(chunk_id, (0.0, {}))
            keep.append((chunk_id, score, ranks))
            if anchored_out is not None:
                anchored_out[chunk_id] = arm_name
            try:
                from app.api.metrics import ARM_LEADERS_ANCHORED_TOTAL

                ARM_LEADERS_ANCHORED_TOTAL.labels(arm_name=arm_name).inc()
            except Exception:
                logger.debug("arm_anchoring_metric_failed", exc_info=True)

        return keep[:target_k]
    except Exception as exc:
        logger.warning("arm_anchoring_failed", error=str(exc))
        return top[:target_k]
