"""Knowledge-Graph Augmented Retrieval (GAR) engine (FEAT-001).

Traverses statutory concept relationships ('requires', 'enables', 'supersedes',
'specializedBy', 'complements') across regulatory provisions and circulars up to
depth N <= 2 with edge-weighted scoring and decay.
"""

from __future__ import annotations

import collections
import time

import structlog

from app.api.metrics import GAR_INVOCATIONS, GAR_TRAVERSAL_DURATION

logger = structlog.get_logger(__name__)

ALLOWED_EDGE_TYPES: frozenset[str] = frozenset(
    {"requires", "enables", "supersedes", "complements", "specializedBy"}
)

DEFAULT_ALLOWED_EDGES: list[str] = [
    "requires",
    "enables",
    "supersedes",
    "specializedBy",
]

RELATION_WEIGHTS: dict[str, float] = {
    "supersedes": 1.0,
    "requires": 0.95,
    "enables": 0.90,
    "specializedBy": 0.85,
    "complements": 0.80,
}

MAX_EXPANDED_CHUNKS: int = 64


class StatutoryGraph:
    """In-memory directed multigraph of statutory provisions and concept dependencies."""

    def __init__(self) -> None:
        # source_node -> list of (target_node, relation)
        self._adj: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
        # node_id -> list of (chunk_id, is_synthetic)
        self._node_chunks: dict[str, list[tuple[str, bool]]] = collections.defaultdict(list)

    def add_edge(self, source: str, target: str, relation: str) -> None:
        """Add directed relationship between two statutory concept nodes."""
        self._adj[source].append((target, relation))

    def bind_chunk(self, node: str, chunk_id: str, is_synthetic: bool = False) -> None:
        """Associate a chunk with a statutory concept node."""
        self._node_chunks[node].append((chunk_id, is_synthetic))

    def traverse(
        self,
        seed_nodes: list[str],
        max_hops: int = 1,
        allowed_edge_types: set[str] | frozenset[str] | None = None,
        decay_factor: float = 0.5,
        include_synthetic: bool = False,
    ) -> list[tuple[str, float]]:
        """Perform cycle-safe breadth-first traversal up to max_hops with proximity score decay."""
        if not seed_nodes or max_hops < 1:
            return []

        allowed = allowed_edge_types if allowed_edge_types is not None else ALLOWED_EDGE_TYPES

        visited: set[str] = set(seed_nodes)
        # queue stores (node, current_hop, path_score)
        queue: collections.deque[tuple[str, int, float]] = collections.deque()
        for seed in seed_nodes:
            queue.append((seed, 0, 1.0))

        chunk_scores: dict[str, float] = {}

        while queue:
            curr_node, hop, parent_score = queue.popleft()
            if hop >= max_hops:
                continue

            for neighbor, relation in self._adj.get(curr_node, []):
                if relation not in allowed:
                    continue

                rel_weight = RELATION_WEIGHTS.get(relation, 0.70)
                # Proximity score with decay per hop
                edge_score = rel_weight * (decay_factor**hop)

                # Bind candidate chunks from the neighbor node
                for cid, is_syn in self._node_chunks.get(neighbor, []):
                    if not include_synthetic and is_syn:
                        continue
                    if cid not in chunk_scores or edge_score > chunk_scores[cid]:
                        chunk_scores[cid] = min(1.0, max(0.0, edge_score))

                if neighbor not in visited and hop + 1 < max_hops:
                    visited.add(neighbor)
                    queue.append((neighbor, hop + 1, edge_score))

        sorted_chunks = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_chunks[:MAX_EXPANDED_CHUNKS]


def traverse_statutory_graph(
    graph: StatutoryGraph,
    seed_nodes: list[str],
    max_hops: int = 1,
    allowed_edge_types: set[str] | frozenset[str] | None = None,
    decay_factor: float = 0.5,
    include_synthetic: bool = False,
) -> list[tuple[str, float]]:
    """Functional wrapper around StatutoryGraph.traverse."""
    return graph.traverse(
        seed_nodes=seed_nodes,
        max_hops=max_hops,
        allowed_edge_types=allowed_edge_types,
        decay_factor=decay_factor,
        include_synthetic=include_synthetic,
    )


class GraphRetriever:
    """Graph-Augmented Retrieval (GAR) coordinator."""

    def __init__(self, graph: StatutoryGraph | None = None) -> None:
        self.graph = graph if graph is not None else StatutoryGraph()
        self._seed_default_regulatory_graph()

    def _seed_default_regulatory_graph(self) -> None:
        """Pre-populate core cross-circular regulatory dependencies from RBI/SEBI frameworks."""
        # Core RBI Digital Lending -> Compromise Settlements & Master Directions
        self.graph.add_edge("digital_lending_guidelines", "cooling_off_period", "requires")
        self.graph.add_edge("digital_lending_guidelines", "direct_disbursal", "requires")
        self.graph.add_edge(
            "digital_lending_guidelines", "compromise_settlement_framework", "complements"
        )
        self.graph.add_edge("compromise_settlement_framework", "cooling_off_period", "requires")
        self.graph.add_edge("kyc_master_direction", "v-cip_video_kyc", "specializedBy")
        self.graph.add_edge("v-cip_video_kyc", "liveness_detection", "requires")
        self.graph.add_edge(
            "payment_aggregator_cross_border", "payment_aggregator", "specializedBy"
        )
        self.graph.add_edge("payment_aggregator", "escrow_account_operation", "requires")

    def retrieve_candidates(
        self,
        query: str,
        seed_terms: list[str] | None = None,
        max_hops: int = 1,
        allowed_edge_types: list[str] | None = None,
        decay_factor: float = 0.5,
        include_synthetic: bool = False,
    ) -> list[tuple[str, float]]:
        """Retrieve graph-expanded chunk candidates with strict input validation."""
        # Input validation rules
        if not (1 <= max_hops <= 2):
            raise ValueError(f"max_hops must be 1 or 2, got {max_hops}")

        if not (3 <= len(query) <= 512):
            raise ValueError(f"query length must be between 3 and 512 characters, got {len(query)}")

        if allowed_edge_types is not None:
            invalid = set(allowed_edge_types) - ALLOWED_EDGE_TYPES
            if invalid:
                raise ValueError(
                    f"allowed_edge_types contains invalid relations: {invalid}. "
                    f"Allowed: {sorted(ALLOWED_EDGE_TYPES)}"
                )
            edges_to_use: frozenset[str] = frozenset(allowed_edge_types)
        else:
            edges_to_use = frozenset(DEFAULT_ALLOWED_EDGES)

        start_time = time.perf_counter()
        GAR_INVOCATIONS.inc()

        # Extract seed terms from query if not explicitly passed
        seeds = list(seed_terms) if seed_terms is not None else []
        if not seeds:
            q_lower = query.lower()
            if "digital lend" in q_lower:
                seeds.append("digital_lending_guidelines")
            if "cooling-off" in q_lower or "cooling off" in q_lower:
                seeds.append("cooling_off_period")
            if "settlement" in q_lower or "compromise" in q_lower:
                seeds.append("compromise_settlement_framework")
            if "kyc" in q_lower:
                seeds.append("kyc_master_direction")
            if "aggregator" in q_lower or "pa" in q_lower:
                seeds.append("payment_aggregator")

        results = self.graph.traverse(
            seed_nodes=seeds,
            max_hops=max_hops,
            allowed_edge_types=edges_to_use,
            decay_factor=decay_factor,
            include_synthetic=include_synthetic,
        )

        elapsed = time.perf_counter() - start_time
        GAR_TRAVERSAL_DURATION.observe(elapsed)

        logger.info(
            "gar_traversal_complete",
            gar_nodes_expanded=len(results),
            duration_ms=elapsed * 1000.0,
            seeds=seeds,
        )

        return results

    def safe_traverse(
        self,
        query: str,
        seed_terms: list[str] | None = None,
        max_hops: int = 1,
        allowed_edge_types: list[str] | None = None,
        decay_factor: float = 0.5,
        include_synthetic: bool = False,
    ) -> list[tuple[str, float]]:
        """Safe execution wrapper guaranteeing non-failing fallback on errors."""
        try:
            return self.retrieve_candidates(
                query=query,
                seed_terms=seed_terms,
                max_hops=max_hops,
                allowed_edge_types=allowed_edge_types,
                decay_factor=decay_factor,
                include_synthetic=include_synthetic,
            )
        except Exception as exc:
            logger.warning(
                "gar_traversal_failed_fallback",
                error=str(exc),
                query_prefix=query[:32] if query else "",
            )
            return []
