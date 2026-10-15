"""Dense retrieval over pgvector and Discriminative Indexing Calibration (FEAT-079).

Only chunks belonging to the **current** version of a document are returned. Superseded
versions are retained in the database -- FR-4 makes retention a guarantee and the
application role holds no DELETE -- so without this predicate an amended circular keeps
answswering questions as though it were in force. That is the worst failure available to a
compliance tool, and it was reachable: measured before this filter existed, marking one
version superseded left all ten of its chunks in the top ten.

Scaling note, stated rather than discovered later: this is a post-filter on a column the
HNSW index does not cover, so at corpus scale pgvector may have to over-fetch to fill k.
At 170 chunks the planner chooses a sequential scan regardless. The fix when that stops
being true is `hnsw.iterative_scan = relaxed_order`, or denormalising `is_current` onto
`chunks` so a partial index can carry it -- not removing the predicate.

Why cosine distance (`<=>`) when ADR-0002 guarantees unit-norm vectors and inner product
would be marginally cheaper: with L2-normalised vectors the two give identical rankings,
so the only difference is failure behaviour. If normalisation ever regresses, cosine keeps
ranking by angle while inner product silently starts ranking by magnitude -- a bug that
produces plausible-looking results and no error. The schema's HNSW index is built with
vector_cosine_ops, and an opclass only accelerates its own operator, so the choice is also
the only one that uses the index.

FEAT-079 introduces Hard Negative Mining and Discriminative Indexing Calibration:
- Mined negative dataset schema `HardNegativeDataset` and config `NegativeMiningConfig`.
- `DiscriminativeCalibrator` and `DiscriminativeProjector` that penalize cross-entity
  false positive retrieval (e.g. Housing Finance Companies vs Microfinance NBFCs)
  without altering raw frozen base embedding weights.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import psycopg

from app.retrieval.types import MetadataFilter
from app.rowtypes import as_float, as_str

# Default parameters for hard negative mining and discriminative calibration (FEAT-079)
DEFAULT_MAX_NEGATIVES_PER_POSITIVE = 5
DEFAULT_MIN_LEXICAL_SIMILARITY = 0.60
DEFAULT_DISCRIMINATIVE_MARGIN_PENALTY = 0.20


@dataclass(frozen=True)
class NegativeMiningConfig:
    """Configuration schema for hard negative mining (FEAT-079)."""

    max_negatives_per_positive: int = DEFAULT_MAX_NEGATIVES_PER_POSITIVE
    min_lexical_similarity: float = DEFAULT_MIN_LEXICAL_SIMILARITY
    min_corpus_chunks: int = 1000

    def __post_init__(self) -> None:
        if self.max_negatives_per_positive < 1:
            raise ValueError(
                f"max_negatives_per_positive must be >= 1, got {self.max_negatives_per_positive}"
            )
        if not (0.0 <= self.min_lexical_similarity <= 1.0):
            raise ValueError(
                f"min_lexical_similarity must be in [0.0, 1.0], got {self.min_lexical_similarity}"
            )


@dataclass
class HardNegativeDataset:
    """Dataset of mined hard negative triplets (FEAT-079).

    Each triplet represents (query, positive_chunk_id, negative_chunk_id).
    """

    triplets: list[tuple[str, str, str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.triplets)

    def __getitem__(self, index: int) -> tuple[str, str, str]:
        return self.triplets[index]

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": "docscout.dataset.hard_negatives/1",
            "triplet_count": len(self.triplets),
            "triplets": [
                {"query": q, "positive_chunk_id": pos, "negative_chunk_id": neg}
                for q, pos, neg in self.triplets
            ],
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> HardNegativeDataset:
        p = Path(path)
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        triplets: list[tuple[str, str, str]] = [
            (item["query"], item["positive_chunk_id"], item["negative_chunk_id"])
            for item in data.get("triplets", [])
        ]
        return cls(triplets=triplets)


# Statutory Entity Taxonomy & Cross-Entity Mutual Exclusion Confining Matrix
ENTITY_TAXONOMY: dict[str, dict[str, Any]] = {
    "hfc": {
        "canonical": "Housing Finance Company",
        "patterns": [
            r"\bhfcs?\b",
            r"\bhousing finance compan(?:y|ies)\b",
            r"\bnhb\b",
        ],
        "conflicts": {
            "nbfc_mfi",
            "nbfc_icc",
            "cic",
            "payments_bank",
            "small_finance_bank",
            "commercial_bank",
        },
    },
    "nbfc_mfi": {
        "canonical": "Microfinance Institution",
        "patterns": [
            r"\bnbfc[- ]mfis?\b",
            r"\bmicro[- ]?finance institutions?\b",
            r"\bmicro finance\b",
        ],
        "conflicts": {"hfc", "cic", "nbfc_icc", "payments_bank", "commercial_bank"},
    },
    "nbfc_icc": {
        "canonical": "Investment and Credit Company",
        "patterns": [
            r"\bnbfc[- ]iccs?\b",
            r"\binvestment and credit compan(?:y|ies)\b",
            r"\bloan compan(?:y|ies)\b",
            r"\basset finance compan(?:y|ies)\b",
        ],
        "conflicts": {"hfc", "nbfc_mfi", "payments_bank"},
    },
    "cic": {
        "canonical": "Core Investment Company",
        "patterns": [
            r"\bcics?\b",
            r"\bcore investment compan(?:y|ies)\b",
            r"\bsystemically important core investment\b",
        ],
        "conflicts": {"hfc", "nbfc_mfi", "payments_bank", "cic_bureau"},
    },
    "commercial_bank": {
        "canonical": "Commercial Bank",
        "patterns": [
            r"\bcommercial banks?\b",
            r"\bscheduled commercial banks?\b",
            r"\bscbs?\b",
            r"\bpublic sector banks?\b",
            r"\bprivate sector banks?\b",
            r"\bforeign banks?\b",
        ],
        "conflicts": {
            "payments_bank",
            "small_finance_bank",
            "urban_coop_bank",
            "regional_rural_bank",
            "hfc",
            "nbfc_mfi",
        },
    },
    "payments_bank": {
        "canonical": "Payments Bank",
        "patterns": [
            r"\bpayments? banks?\b",
            r"\bpbs?\b",
        ],
        "conflicts": {
            "commercial_bank",
            "small_finance_bank",
            "urban_coop_bank",
            "hfc",
            "nbfc_mfi",
        },
    },
    "small_finance_bank": {
        "canonical": "Small Finance Bank",
        "patterns": [
            r"\bsmall finance banks?\b",
            r"\bsfbs?\b",
        ],
        "conflicts": {
            "commercial_bank",
            "payments_bank",
            "urban_coop_bank",
            "hfc",
            "nbfc_mfi",
        },
    },
    "urban_coop_bank": {
        "canonical": "Urban Co-operative Bank",
        "patterns": [
            r"\burban co[- ]?operative banks?\b",
            r"\bucbs?\b",
            r"\bprimary co[- ]?operative banks?\b",
        ],
        "conflicts": {"commercial_bank", "payments_bank", "small_finance_bank", "hfc"},
    },
    "regional_rural_bank": {
        "canonical": "Regional Rural Bank",
        "patterns": [
            r"\bregional rural banks?\b",
            r"\brrbs?\b",
            r"\bgramin banks?\b",
        ],
        "conflicts": {"commercial_bank", "payments_bank", "small_finance_bank", "hfc"},
    },
    "payment_aggregator": {
        "canonical": "Payment Aggregator",
        "patterns": [
            r"\bpayment aggregators?\b",
            r"\bnon-bank payment aggregators?\b",
            r"\bpas?\b",
        ],
        "conflicts": {"commercial_bank", "hfc", "arc", "cic_bureau"},
    },
    "arc": {
        "canonical": "Asset Reconstruction Company",
        "patterns": [
            r"\basset reconstruction compan(?:y|ies)\b",
            r"\barcs?\b",
            r"\bsecuritisation compan(?:y|ies)\b",
        ],
        "conflicts": {"cic_bureau", "commercial_bank", "hfc", "nbfc_mfi"},
    },
    "cic_bureau": {
        "canonical": "Credit Information Company",
        "patterns": [
            r"\bcredit information compan(?:y|ies)\b",
            r"\bcredit bureau\b",
        ],
        "conflicts": {"arc", "commercial_bank", "hfc", "nbfc_mfi", "cic"},
    },
}

ENTITY_REGEXES = {
    entity_key: re.compile("|".join(info["patterns"]), re.IGNORECASE)
    for entity_key, info in ENTITY_TAXONOMY.items()
}


def detect_entities(text: str) -> set[str]:
    """Detect canonical regulatory entity classifications present in text."""
    if not text:
        return set()
    found: set[str] = set()
    for entity_key, regex in ENTITY_REGEXES.items():
        if regex.search(text):
            found.add(entity_key)
    return found


@dataclass(frozen=True)
class DiscriminativeConfig:
    """Configuration for discriminative indexing and cross-entity calibration (FEAT-079)."""

    enabled: bool = True
    entity_margin_penalty: float = DEFAULT_DISCRIMINATIVE_MARGIN_PENALTY
    min_lexical_similarity: float = DEFAULT_MIN_LEXICAL_SIMILARITY


class DiscriminativeProjector:
    """Projects dense embedding vectors to separate conflicting entity subspaces."""

    def __init__(
        self,
        dimension: int = 384,
        projection_matrix: np.ndarray | None = None,
    ) -> None:
        self.dimension = dimension
        if projection_matrix is not None:
            self._matrix = np.asarray(projection_matrix, dtype=np.float32)
        else:
            self._matrix = np.eye(dimension, dtype=np.float32)

    def project(self, vector: np.ndarray) -> np.ndarray:
        """Apply linear discriminative projection and L2-normalize."""
        v = np.asarray(vector, dtype=np.float32)
        projected: np.ndarray = np.asarray(np.dot(v, self._matrix), dtype=np.float32)
        norm = float(np.linalg.norm(projected))
        if norm > 0:
            return np.asarray(projected / norm, dtype=np.float32)
        return projected


class DiscriminativeCalibrator:
    """Calibrates dense similarity scores to eliminate cross-entity false positives."""

    def __init__(self, config: DiscriminativeConfig | None = None) -> None:
        self.config = config if config is not None else DiscriminativeConfig()

    def detect_entities(self, text: str) -> set[str]:
        return detect_entities(text)

    def calibrate_candidates(
        self,
        query: str,
        candidates: list[tuple[str, float, str]],
    ) -> list[tuple[str, float]]:
        """Calibrate candidate scores by applying discriminative entity margin penalties.

        candidates: list of (chunk_id, raw_similarity, chunk_text)
        Returns: list of (chunk_id, calibrated_similarity) sorted descending.
        """
        if not self.config.enabled or not query:
            return [(cid, sim) for cid, sim, _ in candidates]

        query_entities = self.detect_entities(query)
        if not query_entities:
            # General query with no specific entity scope -> retain raw scores
            return [(cid, sim) for cid, sim, _ in candidates]

        # Gather conflicting entities across all entities mentioned in the query
        conflicting_entities: set[str] = set()
        for q_ent in query_entities:
            conflicts = ENTITY_TAXONOMY.get(q_ent, {}).get("conflicts", set())
            conflicting_entities.update(conflicts)

        # Do not penalize an entity if the query explicitly requested it
        conflicting_entities.difference_update(query_entities)

        if not conflicting_entities:
            return [(cid, sim) for cid, sim, _ in candidates]

        calibrated: list[tuple[str, float]] = []
        for cid, raw_sim, chunk_text in candidates:
            chunk_entities = self.detect_entities(chunk_text)

            # If chunk mentions the queried entity, no penalty
            if query_entities.intersection(chunk_entities):
                calibrated.append((cid, raw_sim))
            elif conflicting_entities.intersection(chunk_entities):
                # Chunk discusses conflicting entity without mentioning queried entity
                calibrated_sim = max(0.0, raw_sim - self.config.entity_margin_penalty)
                calibrated.append((cid, round(calibrated_sim, 4)))
            else:
                # Neutral or umbrella chunk
                calibrated.append((cid, raw_sim))

        calibrated.sort(key=lambda x: -x[1])
        return calibrated


_DEFAULT_CALIBRATOR = DiscriminativeCalibrator()


def get_default_calibrator() -> DiscriminativeCalibrator:
    """Return singleton instance of DiscriminativeCalibrator."""
    return _DEFAULT_CALIBRATOR


def search(
    conn: psycopg.Connection[tuple[object, ...]],
    query_vector: np.ndarray,
    k: int,
    filter: MetadataFilter | None = None,
    *,
    query_text: str | None = None,
    calibrator: DiscriminativeCalibrator | None = None,
) -> list[tuple[str, float]]:
    """Return the top-k (chunk_id, similarity), highest similarity first.

    Similarity is 1 - cosine distance, so it rises with relevance like the BM25 score
    does. Fusion is rank-based and does not care, but a report that prints raw scores
    should not print one column where bigger is better next to one where it is not.

    Filtering (P1-2) is executed in-query so Postgres can leverage index scans on
    documents (source, published_date) and document_versions (is_current, fetch_ts).

    When calibrator is active and query_text is provided, candidates are calibrated
    against statutory entity boundaries to eliminate cross-entity false positives (FEAT-079).
    """
    effective_k = k
    apply_calibration = (
        calibrator is not None and calibrator.config.enabled and query_text is not None
    )
    if apply_calibration:
        effective_k = max(k * 2, k + 10)

    vector = np.asarray(query_vector, dtype=np.float32).tolist()
    params: dict[str, Any] = {"vector": vector, "k": effective_k}
    where_clauses: list[str] = []

    # Version currency filter (only when point-in-time as_of_date is not active)
    if filter is None or filter.as_of_date is None:
        is_curr = filter.is_current if filter is not None else True
        if is_curr is True:
            where_clauses.append("v.is_current")
        elif is_curr is False:
            where_clauses.append("NOT v.is_current")

    # Synthetic artifact exclusion invariant
    inc_synth = filter.include_synthetic if filter is not None else False
    if not inc_synth:
        where_clauses.append("NOT d.is_synthetic")

    if filter is not None:
        if filter.source is not None:
            if isinstance(filter.source, str):
                where_clauses.append("d.source = %(source)s")
                params["source"] = filter.source
            else:
                where_clauses.append("d.source = ANY(%(sources)s)")
                params["sources"] = list(filter.source)

        if filter.date_from is not None:
            where_clauses.append("COALESCE(d.published_date, v.fetch_ts::date) >= %(date_from)s")
            params["date_from"] = filter.date_from

        if filter.date_to is not None:
            where_clauses.append("COALESCE(d.published_date, v.fetch_ts::date) <= %(date_to)s")
            params["date_to"] = filter.date_to

        if filter.document_ids is not None:
            where_clauses.append("c.document_id = ANY(%(document_ids)s::uuid[])")
            params["document_ids"] = filter.document_ids

        if filter.canonical_url is not None:
            where_clauses.append("d.canonical_url = %(canonical_url)s")
            params["canonical_url"] = filter.canonical_url

        if filter.taxonomy_layers is not None:
            where_clauses.append("c.taxonomy_layer = ANY(%(taxonomy_layers)s)")
            params["taxonomy_layers"] = list(filter.taxonomy_layers)

        if filter.tags is not None:
            where_clauses.append("c.tags && %(tags)s")
            params["tags"] = list(filter.tags)

        if filter.as_of_date is not None:
            where_clauses.append(
                "COALESCE(d.published_date, v.fetch_ts::date) <= %(as_of_date)s "
                "AND (d.superseded_date IS NULL OR d.superseded_date > %(as_of_date)s)"
            )
            params["as_of_date"] = filter.as_of_date

    join_clauses = [
        "JOIN document_versions AS v ON v.version_id = c.version_id",
        "JOIN documents AS d ON d.document_id = c.document_id",
    ]

    if filter is not None and filter.standard is not None:
        from app.compliance.standards_registry import get_default_standards_registry

        std = get_default_standards_registry().get_standard(filter.standard)
        match_keys = {
            filter.standard,
            filter.standard.lower(),
            filter.standard.upper(),
            filter.standard.replace("-", "_"),
            filter.standard.replace("_", " "),
        }
        if std is not None:
            match_keys.add(std.id)
            match_keys.add(std.name)
            for a in std.aliases:
                match_keys.add(a)
        clean_keys = list({k for k in match_keys if k})
        join_clauses.append("JOIN framework_control_crosswalk AS fc ON fc.chunk_id = c.chunk_id")
        where_clauses.append(
            "(fc.standard_id = ANY(%(std_keys)s) OR fc.source_framework = ANY(%(std_keys)s) OR fc.target_framework = ANY(%(std_keys)s))"
        )
        params["std_keys"] = clean_keys

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    joins_sql = "\n        ".join(join_clauses)

    if apply_calibration:
        query = f"""
            SELECT c.chunk_id::text, 1.0 - (c.embedding <=> %(vector)s::vector) AS similarity, c.text
            FROM chunks AS c
            {joins_sql}
            {where_sql}
            GROUP BY c.chunk_id, c.embedding, c.text
            ORDER BY c.embedding <=> %(vector)s::vector
            LIMIT %(k)s
        """  # noqa: S608
        rows = conn.execute(query, params).fetchall()
        candidates = [(as_str(r[0]), as_float(r[1]), as_str(r[2])) for r in rows]
        if calibrator is not None and query_text is not None:
            calibrated = calibrator.calibrate_candidates(query_text, candidates)
            return calibrated[:k]
        return [(cid, sim) for cid, sim, _ in candidates[:k]]

    query = f"""
        SELECT c.chunk_id::text, 1.0 - (c.embedding <=> %(vector)s::vector) AS similarity
        FROM chunks AS c
        {joins_sql}
        {where_sql}
        GROUP BY c.chunk_id, c.embedding
        ORDER BY c.embedding <=> %(vector)s::vector
        LIMIT %(k)s
    """  # noqa: S608 - predicate templates are fixed literals; all dynamic values are securely bound in params
    rows = conn.execute(query, params).fetchall()

    return [(as_str(r[0]), as_float(r[1])) for r in rows]
