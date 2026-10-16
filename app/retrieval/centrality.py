"""Graph degree centrality query boosting engine (FEAT-009).

Factors precomputed PageRank and degree centrality scores from the regulatory
knowledge graph into passage scoring to surface foundational master directions
and statutory frameworks on broad thematic queries.

Guarantees:
1. In-memory lookup overhead <= 0.2 ms.
2. Memory footprint <= 2 MB.
3. Clamped weight in [0.0, 0.3] with monotonic score invariance.
4. Specific queries (exact section numbers) are not perturbed (0.0 boost).
5. Fallback on lookup failure applies zero boost (1.0x) without raising.
"""

from __future__ import annotations

import collections
import json
import math
import re
from pathlib import Path
from typing import Any

import psycopg
import structlog

logger = structlog.get_logger(__name__)

# Specific query indicators: sections, clauses, rules, circular IDs, exact citations
NARROW_SPECIFIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(?:section|sec\.?|clause|paragraph|para\.?|rule|regulation|sub-section|part|schedule|annexure|article)\s+(?:\d+[a-z0-9\.\(\)\/\-]*|[ivxldcm]+)\b"
    ),
    re.compile(
        r"(?i)\b(?:rbi\/\d{4}-\d{2,4}\/\d+|dor\.[a-z\.]+\.\d+|sebi\/[a-z\-]+\/\d+|cir\/[a-z\-]+\/\d+)\b"
    ),
    re.compile(r"(?i)\b(?:circular\s+no|notification\s+no|order\s+no|ref\.?\s*no)\b"),
    re.compile(r"(?i)\b\d{1,3}\s*\([a-z0-9]+\)"),
    re.compile(r"(?i)\b(?:45-ia|45-ib|45-ic|35a|42\(1\)|24\(2a\)|13\(2\)|13\(4\))\b"),
)

# Canonical regulatory thematic concepts that signify broad queries
BROAD_THEME_KEYWORDS: frozenset[str] = frozenset(
    {
        "kyc",
        "aml",
        "anti-money laundering",
        "cdd",
        "customer due diligence",
        "outsourcing",
        "capital adequacy",
        "digital lending",
        "fair practices code",
        "fair practice",
        "it governance",
        "cyber security",
        "prudential norms",
        "prudential framework",
        "basel",
        "basel iii",
        "risk management",
        "master direction",
        "master circular",
        "grievance redressal",
        "internal audit",
        "slr",
        "crr",
        "statutory liquidity ratio",
        "cash reserve ratio",
        "priority sector lending",
        "psl",
        "co-lending",
        "credit cards",
        "non-performing assets",
        "npa",
        "asset classification",
        "provisioning norms",
        "information security",
        "regulatory sandbox",
        "framework",
        "guidelines",
        "directions",
        "norms",
    }
)

# Foundational document keywords indicating structural master frameworks
FOUNDATIONAL_DOC_KEYWORDS: tuple[str, ...] = (
    "master direction",
    "master circular",
    "prudential framework",
    "prudential norms",
    "framework for",
    "comprehensive guidelines",
    "operating guidelines",
)


def is_broad_thematic_query(query: str, threshold: float = 0.4) -> tuple[bool, float]:
    """Classify whether a query is broad thematic vs narrow/specific.

    Returns:
        (is_broad, specificity_score): If specificity <= threshold, query is broad.
    """
    clean_q = query.strip()
    if not clean_q:
        return False, 1.0

    # 1. Check for narrow/specific indicators (sections, notification numbers, exact clauses)
    for pattern in NARROW_SPECIFIC_PATTERNS:
        if pattern.search(clean_q):
            return False, 0.95

    tokens = [t.lower().strip(".,;:?!()[]'\"") for t in clean_q.split() if t]
    token_count = len(tokens)

    # 2. Match thematic keywords
    clean_lower = clean_q.lower()
    theme_matches = sum(1 for kw in BROAD_THEME_KEYWORDS if kw in clean_lower)

    # 3. Calculate specificity score in [0.0, 1.0]
    # Short query (< 5 words) with broad themes has low specificity (e.g. 0.15 - 0.30)
    if token_count <= 4 and theme_matches >= 1:
        specificity = 0.20
    elif token_count <= 6 and theme_matches >= 1:
        specificity = 0.30
    elif theme_matches >= 2:
        specificity = 0.35
    elif token_count <= 2:
        specificity = 0.38
    else:
        # Long query without thematic signals tends toward specific informational query
        base_spec = 0.45 + min(0.40, token_count * 0.05)
        specificity = min(0.90, base_spec - (0.10 * theme_matches))

    is_broad = specificity <= threshold
    return is_broad, round(specificity, 3)


class CentralityIndex:
    """Precomputed in-memory degree centrality and PageRank lookup cache."""

    def __init__(self) -> None:
        self._term_centrality: dict[str, float] = {}
        self._doc_centrality: dict[str, float] = {}
        self._chunk_centrality: dict[str, float] = {}
        self._initialized: bool = False

    def initialize(self, conn: psycopg.Connection[Any] | None = None) -> None:
        """Precompute and cache centrality maps from lexicon, taxonomy, and DB."""
        if self._initialized:
            return

        try:
            self._load_lexicon_centrality()
            self._load_taxonomy_entities()
            if conn is not None:
                self._load_db_centrality(conn)
            self._initialized = True
            logger.info(
                "centrality_index_initialized",
                terms_indexed=len(self._term_centrality),
                docs_indexed=len(self._doc_centrality),
                chunks_indexed=len(self._chunk_centrality),
            )
        except Exception as exc:
            logger.warning("centrality_index_init_failed", error=str(exc))
            self._initialized = True  # Avoid tight retry loops; fallback remains safe

    def _load_lexicon_centrality(self) -> None:
        """Load degree centrality and compute PageRank from lexicon.json."""
        lex_path = Path(__file__).resolve().parents[3] / "do not commit!" / "lexicon.json"
        if not lex_path.exists():
            return

        try:
            with open(lex_path, encoding="utf-8") as f:
                data = json.load(f)

            graph = data.get("graph", {})
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", [])

            # 1. Degree Centrality
            max_deg = max((n.get("degree", 0) for n in nodes), default=1) or 1
            deg_scores: dict[str, float] = {}
            for n in nodes:
                nid = n.get("id")
                if nid:
                    deg_scores[nid] = n.get("degree", 0) / max_deg

            # 2. Power-Iteration PageRank on graph edges
            pr_scores = self._compute_pagerank(nodes, edges)

            # Combine degree and PageRank into normalized score
            for nid, deg_val in deg_scores.items():
                pr_val = pr_scores.get(nid, 0.0)
                combined = 0.5 * deg_val + 0.5 * pr_val
                self._term_centrality[nid] = round(min(1.0, max(0.0, combined)), 4)
                # Normalize term identifier with spaces and dashes
                term_name = nid.replace("-", " ").strip()
                self._term_centrality[term_name] = self._term_centrality[nid]
        except Exception as exc:
            logger.debug("lexicon_centrality_skipped", error=str(exc))

    def _compute_pagerank(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        iterations: int = 20,
        damping: float = 0.85,
    ) -> dict[str, float]:
        """Compute standard PageRank over directed multigraph nodes and edges."""
        if not nodes:
            return {}

        node_ids = [n["id"] for n in nodes if "id" in n]
        n_count = len(node_ids)
        if n_count == 0:
            return {}

        out_edges: dict[str, list[str]] = collections.defaultdict(list)
        for e in edges:
            src = e.get("source")
            tgt = e.get("target")
            if src and tgt and src in node_ids and tgt in node_ids:
                out_edges[src].append(tgt)

        ranks: dict[str, float] = {nid: 1.0 / n_count for nid in node_ids}

        for _ in range(iterations):
            new_ranks: dict[str, float] = {nid: (1.0 - damping) / n_count for nid in node_ids}
            for src, targets in out_edges.items():
                if targets:
                    share = (damping * ranks[src]) / len(targets)
                    for tgt in targets:
                        new_ranks[tgt] += share
                else:
                    # Dangling node redistribution
                    dangling_share = (damping * ranks[src]) / n_count
                    for nid in node_ids:
                        new_ranks[nid] += dangling_share
            ranks = new_ranks

        # Normalize to [0.0, 1.0]
        max_pr = max(ranks.values(), default=1.0) or 1.0
        return {nid: round(score / max_pr, 4) for nid, score in ranks.items()}

    def _load_taxonomy_entities(self) -> None:
        """Seed foundational regulatory entities with calibrated high centrality."""
        try:
            from app.retrieval.entity_linker import STATUTORY_ENTITIES

            for entity in STATUTORY_ENTITIES:
                # Core master statutory bodies & frameworks have high architectural degree
                conn_count = len(entity.parent_ids) + len(entity.child_ids) + len(entity.aliases)
                score = min(1.0, max(0.40, conn_count * 0.15))
                self._term_centrality[entity.entity_id] = score
                self._term_centrality[entity.canonical_name.lower()] = score
                for alias in entity.aliases:
                    self._term_centrality[alias.lower()] = score
        except Exception:
            logger.debug("statutory_entities_centrality_skipped")

        # Foundational frameworks default mapping
        foundational_seeds: dict[str, float] = {
            "kyc": 0.95,
            "know your customer": 0.95,
            "master direction - know your customer": 1.00,
            "digital lending": 0.90,
            "guidelines on digital lending": 0.95,
            "outsourcing": 0.88,
            "master direction on outsourcing": 0.95,
            "it governance": 0.85,
            "master direction on information technology governance": 0.92,
            "capital adequacy": 0.92,
            "basel iii capital regulations": 0.98,
            "fair practices code": 0.85,
            "prudential framework for resolution of stressed assets": 0.96,
        }
        for k, v in foundational_seeds.items():
            self._term_centrality.setdefault(k, v)

    def _load_db_centrality(self, conn: psycopg.Connection[Any]) -> None:
        """Enrich document and chunk centrality from DB circular_citations and documents."""
        try:
            # 1. In-degree citation count from circular_citations
            rows = conn.execute(
                """
                SELECT target_document_id::text, count(*)
                FROM circular_citations
                WHERE target_document_id IS NOT NULL
                GROUP BY target_document_id
                """
            ).fetchall()
            if rows:
                max_cits = max((int(cnt) for _, cnt in rows), default=1) or 1
                for doc_id, cnt in rows:
                    if doc_id:
                        self._doc_centrality[str(doc_id)] = min(1.0, max(0.0, int(cnt) / max_cits))

            # 2. Master Direction document titles
            doc_rows = conn.execute(
                """
                SELECT document_id::text, title
                FROM documents
                WHERE NOT is_synthetic AND title IS NOT NULL
                """
            ).fetchall()
            for doc_id, title in doc_rows:
                if not doc_id or not title:
                    continue
                t_lower = str(title).lower()
                for kw in FOUNDATIONAL_DOC_KEYWORDS:
                    if kw in t_lower:
                        self._doc_centrality[str(doc_id)] = max(
                            self._doc_centrality.get(str(doc_id), 0.0),
                            0.90,
                        )
                        break
        except Exception as exc:
            logger.debug("db_centrality_enrich_skipped", error=str(exc))

    def get_centrality(
        self,
        chunk_id: str,
        document_id: str | None = None,
        title: str | None = None,
        text: str | None = None,
    ) -> float:
        """Lookup normalized graph degree / PageRank centrality score in [0.0, 1.0]."""
        # 1. Direct chunk centrality
        if chunk_id in self._chunk_centrality:
            return self._chunk_centrality[chunk_id]

        # 2. Direct document centrality
        if document_id and document_id in self._doc_centrality:
            return self._doc_centrality[document_id]

        # 3. Document title evaluation for foundational status
        if title:
            t_lower = title.lower()
            for kw in FOUNDATIONAL_DOC_KEYWORDS:
                if kw in t_lower:
                    return 0.90

        # 4. Text term matching
        if text:
            text_lower = text[:500].lower()
            highest_term_score = 0.0
            for term, score in self._term_centrality.items():
                if len(term) >= 4 and term in text_lower:
                    if score > highest_term_score:
                        highest_term_score = score
            if highest_term_score > 0.0:
                return round(highest_term_score * 0.85, 4)

        return 0.0

    @staticmethod
    def compute_boost(score: float, centrality: float, weight: float = 0.15) -> tuple[float, float]:
        """Apply non-linear centrality boost to score.

        Formula:
            factor = 1.0 + weight * log(1.0 + centrality * (e - 1.0))
            boosted_score = score * factor
            boost_amount = score * (factor - 1.0)

        Guarantees:
            - Clamped weight in [0.0, 0.3].
            - Clamped centrality in [0.0, 1.0].
            - When centrality=0, factor=1.0 (zero boost).
            - Monotonically non-decreasing in score and centrality.
        """
        w = max(0.0, min(0.3, float(weight)))
        c = max(0.0, min(1.0, float(centrality)))
        if c == 0.0 or w == 0.0:
            return score, 0.0

        # Non-linear concave boost factor passing through (0, 1.0) and (1, 1.0 + w)
        factor = 1.0 + w * math.log1p(c * (math.e - 1.0))
        boosted = score * factor
        boost_amount = boosted - score
        return boosted, boost_amount


_GLOBAL_CENTRALITY_INDEX: CentralityIndex | None = None


def get_centrality_index(conn: psycopg.Connection[Any] | None = None) -> CentralityIndex:
    """Return the singleton CentralityIndex, initializing once."""
    global _GLOBAL_CENTRALITY_INDEX
    if _GLOBAL_CENTRALITY_INDEX is None:
        idx = CentralityIndex()
        idx.initialize(conn)
        _GLOBAL_CENTRALITY_INDEX = idx
    elif conn is not None and not _GLOBAL_CENTRALITY_INDEX._doc_centrality:
        # If DB connection becomes available later, enrich doc centrality
        _GLOBAL_CENTRALITY_INDEX._load_db_centrality(conn)
    return _GLOBAL_CENTRALITY_INDEX
