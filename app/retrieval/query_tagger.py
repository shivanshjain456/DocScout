"""Query Tagging and Metadata Constrained Retrieval (FEAT-016).

Extracts domain tags from incoming queries against the 45 taxonomy tags
(security, compliance, apis, audit, etc.) to automatically apply strict
SQL WHERE clauses, boosting precision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.api import metrics
from app.retrieval._tag_data import TAG_KEYWORDS, TAG_TO_LAYERS
from app.retrieval.types import MetadataFilter

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class QueryTaggerConfig:
    """Configuration schema for query domain tagging and filtering (FEAT-016)."""

    auto_constrain: bool = False
    min_tag_confidence: float = 0.90


class QueryTagger:
    """Extracts taxonomy domain tags from queries and constructs metadata constraints."""

    def __init__(self, config: QueryTaggerConfig | None = None) -> None:
        self.config = config or QueryTaggerConfig()
        self._single_map: dict[str, list[tuple[str, float]]] = {}
        self._multi_map: dict[str, list[tuple[str, str, float]]] = {}
        self._build_index()

    def _build_index(self) -> None:
        """Build inverted vocabulary index for sub-0.3ms extraction."""
        for tag, kws in TAG_KEYWORDS.items():
            # Exact tag name yields confidence 1.0
            self._single_map.setdefault(tag, []).append((tag, 1.0))
            if "-" in tag:
                clean_tag = tag.replace("-", " ")
                first = clean_tag.split()[0]
                self._multi_map.setdefault(first, []).append((clean_tag, tag, 1.0))

            for kw in kws:
                kw_clean = kw.strip().lower()
                if not kw_clean or kw_clean == tag:
                    continue
                if " " in kw_clean or "-" in kw_clean:
                    first = re.split(r"[\s\-]+", kw_clean)[0]
                    self._multi_map.setdefault(first, []).append((kw_clean, tag, 0.95))
                else:
                    self._single_map.setdefault(kw_clean, []).append((tag, 0.90))

    def tag_scores(self, query: str) -> dict[str, float]:
        """Compute confidence scores per taxonomy tag for the given query."""
        if not query or len(query.strip()) < 3:
            raise ValueError("Query length must be at least 3 characters")

        q_lower = query.strip().lower()
        q_words = set(re.findall(r"[a-z0-9]+", q_lower))
        q_words.update(re.findall(r"[a-z0-9\-]+", q_lower))

        scores: dict[str, float] = {}

        for w in q_words:
            # Check single-word tokens
            if w in self._single_map:
                for tag, conf in self._single_map[w]:
                    if conf > scores.get(tag, 0.0):
                        scores[tag] = conf

            # Check multi-word phrases starting with w
            if w in self._multi_map:
                for phrase, tag, conf in self._multi_map[w]:
                    if phrase in q_lower:
                        if conf > scores.get(tag, 0.0):
                            scores[tag] = conf

        # Exclude low confidence (< 0.85) to prevent premature elimination of valid results
        return {tag: conf for tag, conf in scores.items() if conf >= 0.85}

    def extract_tags(self, query: str, auto_constrain: bool | None = None) -> list[str]:
        """Extract matched taxonomy tags meeting minimum confidence threshold."""
        scores = self.tag_scores(query)
        min_conf = self.config.min_tag_confidence
        extracted = sorted([tag for tag, conf in scores.items() if conf >= min_conf])
        return extracted

    def translate_to_filter(
        self,
        tags: list[str],
        base_filter: MetadataFilter | None = None,
    ) -> MetadataFilter:
        """Translate extracted domain tags into SQL MetadataFilter parameters."""
        layers: set[str] = set()
        for tag in tags:
            for lyr in TAG_TO_LAYERS.get(tag, ()):
                layers.add(lyr)

        target_layers = list(sorted(layers)) if layers else None

        if base_filter is None:
            return MetadataFilter(
                tags=tags,
                taxonomy_layers=target_layers,
            )

        # Merge with existing filter
        combined_layers = base_filter.taxonomy_layers
        if target_layers:
            if combined_layers:
                combined_set = set(combined_layers) | set(target_layers)
                combined_layers = list(sorted(combined_set)) if combined_set else combined_layers
            else:
                combined_layers = target_layers

        return base_filter.model_copy(
            update={
                "tags": tags,
                "taxonomy_layers": combined_layers,
            }
        )

    def record_metrics(self, tags: list[str]) -> None:
        """Increment Prometheus counters for extracted tags."""
        for tag in tags:
            try:
                metrics.TAGS_EXTRACTED_TOTAL.labels(tag=tag).inc()
            except Exception as exc:  # noqa: BLE001
                logger.debug("tag_metric_failed", tag=tag, error=str(exc))


_DEFAULT_QUERY_TAGGER: QueryTagger | None = None


def get_default_query_tagger() -> QueryTagger:
    """Return singleton QueryTagger instance."""
    global _DEFAULT_QUERY_TAGGER
    if _DEFAULT_QUERY_TAGGER is None:
        _DEFAULT_QUERY_TAGGER = QueryTagger()
    return _DEFAULT_QUERY_TAGGER
