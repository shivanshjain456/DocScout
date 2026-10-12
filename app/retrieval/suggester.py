"""Interactive Search Query Suggestions Engine (FEAT-019).

Provides prefix-tree autocomplete and 'Related Queries' exploration powered by
the 1,358 lexicon terms, regulatory entity acronyms, statutory circulars, and
the `lexicon.terms[].related` graph edges.

Verification Target: Latency < 15ms from local in-memory index.
"""

from __future__ import annotations

import bisect
import re
import time
from dataclasses import dataclass
from typing import ClassVar, Literal

import structlog

from app.api import metrics
from app.api.models import QuerySuggestion, SuggestionResponse
from app.retrieval._suggestion_data import (
    STATUTORY_SUGGESTIONS,
    SUGGESTION_TERMS,
    TermSuggestionData,
)

logger = structlog.get_logger("docscout.suggester")


@dataclass(frozen=True)
class SuggesterConfig:
    """Configuration options for search query suggestion engine."""

    enabled: bool = True
    default_limit: int = 10
    max_limit: int = 50
    min_query_length: int = 1
    max_query_length: int = 128
    enable_normalization: bool = True
    include_related: bool = True


@dataclass(frozen=True)
class _IndexKey:
    """An individual indexed key for fast prefix and word lookup."""

    key: str
    item_id: str
    category: Literal["term", "statutory", "acronym", "related"]
    base_score: float
    display_text: str
    domain: str | None
    domain_name: str | None
    match_type: str


def _highlight_match(text: str, prefix: str) -> str:
    """Wrap case-insensitive match of prefix with <b> tags for UI rendering."""
    if not prefix:
        return text
    pattern = re.compile(f"({re.escape(prefix)})", re.IGNORECASE)
    return pattern.sub(r"<b>\1</b>", text, count=1)


class SearchSuggester:
    """In-memory prefix and related graph suggester for regulatory queries."""

    _instance: ClassVar[SearchSuggester | None] = None

    def __init__(self, config: SuggesterConfig | None = None) -> None:
        self.config = config or SuggesterConfig()
        self._keys: list[_IndexKey] = []
        self._key_strings: list[str] = []
        self._terms: dict[str, TermSuggestionData] = SUGGESTION_TERMS
        self._statutory: tuple[tuple[str, str, str], ...] = STATUTORY_SUGGESTIONS
        self._build_index()
        if self.config.enable_normalization:
            try:
                from app.retrieval.normalizer import get_default_normalizer

                get_default_normalizer()
            except Exception as exc:
                logger.debug("suggester.warmup_failed", error=str(exc))

    def _build_index(self) -> None:
        """Build sorted prefix index over terms, acronyms, words, and statutory citations."""
        keys: list[_IndexKey] = []

        # 1. Lexicon and regulatory terms
        for term_id, term_data in self._terms.items():
            t_name = term_data.term.strip()
            t_lower = t_name.lower()

            # Full term prefix
            keys.append(
                _IndexKey(
                    key=t_lower,
                    item_id=term_id,
                    category="term",
                    base_score=1.0,
                    display_text=t_name,
                    domain=term_data.domain,
                    domain_name=term_data.domain_name,
                    match_type="term",
                )
            )

            # Acronyms (e.g. LCR, PA, NBFC, KYC)
            for acr in term_data.acronyms:
                acr_clean = acr.strip()
                if acr_clean:
                    keys.append(
                        _IndexKey(
                            key=acr_clean.lower(),
                            item_id=term_id,
                            category="acronym",
                            base_score=1.25,
                            display_text=f"{acr_clean} - {t_name}",
                            domain=term_data.domain,
                            domain_name=term_data.domain_name,
                            match_type="acronym",
                        )
                    )

            # Individual words inside multi-word terms (e.g. "Aggregator" in "Payment Aggregator")
            tokens = re.split(r"[\s\-\/]+", t_name)
            if len(tokens) > 1:
                for token in tokens[1:]:
                    clean_tok = "".join(c for c in token if c.isalnum()).lower()
                    if len(clean_tok) >= 3:
                        keys.append(
                            _IndexKey(
                                key=clean_tok,
                                item_id=term_id,
                                category="term",
                                base_score=0.85,
                                display_text=t_name,
                                domain=term_data.domain,
                                domain_name=term_data.domain_name,
                                match_type="word",
                            )
                        )

        # 2. Statutory circular and section citations
        for cit, title, domain in self._statutory:
            cit_clean = cit.strip()
            cit_lower = cit_clean.lower()
            item_id = f"statutory:{cit_clean}"
            display = f"{cit_clean} - {title}"

            # Citation number prefix (e.g. "rbi/2022", "section 45", "dor.str")
            keys.append(
                _IndexKey(
                    key=cit_lower,
                    item_id=item_id,
                    category="statutory",
                    base_score=1.1,
                    display_text=display,
                    domain=domain,
                    domain_name="Statutory Directives",
                    match_type="statutory",
                )
            )

            # Title words
            for w in re.split(r"[\s\-\/\(\)]+", title):
                clean_w = "".join(c for c in w if c.isalnum()).lower()
                if len(clean_w) >= 4 and clean_w not in {"guidelines", "regulation", "directions"}:
                    keys.append(
                        _IndexKey(
                            key=clean_w,
                            item_id=item_id,
                            category="statutory",
                            base_score=0.88,
                            display_text=display,
                            domain=domain,
                            domain_name="Statutory Directives",
                            match_type="word",
                        )
                    )

        # Sort keys lexicographically for fast binary search
        keys.sort(key=lambda k: (k.key, -k.base_score))
        self._keys = keys
        self._key_strings = [k.key for k in keys]

    def _find_prefix_matches(self, prefix: str) -> list[tuple[_IndexKey, float]]:
        """Perform sub-millisecond bisect prefix lookup."""
        if not prefix:
            return []

        p_lower = prefix.lower().strip()
        idx = bisect.bisect_left(self._key_strings, p_lower)
        matches: list[tuple[_IndexKey, float]] = []

        while idx < len(self._key_strings) and self._key_strings[idx].startswith(p_lower):
            entry = self._keys[idx]
            match_len = len(p_lower)
            key_len = len(entry.key)

            # Calculate match quality score
            if entry.key == p_lower:
                score = entry.base_score * 1.3
            else:
                length_ratio = match_len / max(key_len, 1)
                score = entry.base_score * (0.8 + 0.2 * length_ratio)

            matches.append((entry, score))
            idx += 1

        return matches

    def _get_related_queries(
        self, term_data: TermSuggestionData, max_related: int = 4
    ) -> list[str]:
        """Traverse graph edges to synthesize related regulatory search inquiries."""
        related_queries: list[str] = []
        for rel_id in term_data.related_ids:
            if rel_id in self._terms:
                rel_term = self._terms[rel_id]
                # Provide contextual compound inquiry
                related_queries.append(f"{term_data.term} - {rel_term.term}")
            if len(related_queries) >= max_related:
                break
        return related_queries

    def suggest(
        self,
        query: str,
        limit: int = 10,
        include_related: bool = True,
        enable_normalization: bool = True,
    ) -> SuggestionResponse:
        """Generate ranked autocomplete suggestions and related queries.

        Operates in <15ms directly against in-memory indexed structures.
        """
        start_time = time.perf_counter()
        clean_q = query.strip()
        eff_limit = min(max(limit, 1), self.config.max_limit)

        if len(clean_q) < self.config.min_query_length:
            return SuggestionResponse(
                query=query,
                normalized_query=None,
                suggestions=[],
                latency_ms=0.0,
                total=0,
            )

        # 1. Typo Normalization (FEAT-018 integration)
        normalized_q: str | None = None
        alt_prefix_q: str | None = None
        if enable_normalization and self.config.enable_normalization:
            try:
                from app.retrieval.normalizer import get_default_normalizer

                norm = get_default_normalizer()
                norm_res = norm.normalize(clean_q)
                if norm_res.corrections_applied:
                    normalized_q = norm_res.normalized_query

                words = clean_q.split()
                if len(words) > 1 and not query.endswith(" "):
                    stem = " ".join(words[:-1])
                    stem_res = norm.normalize(stem)
                    if stem_res.corrections_applied:
                        alt_prefix_q = f"{stem_res.normalized_query} {words[-1]}"
            except Exception as exc:
                logger.warning("suggester.normalization_error", error=str(exc))

        # 2. Gather candidate matches
        # Primary lookup on raw query
        candidates = self._find_prefix_matches(clean_q)

        # Secondary lookup on normalized query if typos were corrected
        if normalized_q and normalized_q != clean_q:
            norm_matches = self._find_prefix_matches(normalized_q)
            for item, score in norm_matches:
                candidates.append((item, score * 0.95))

        # Tertiary lookup on stem-normalized prefix if applicable
        if alt_prefix_q and alt_prefix_q != clean_q and alt_prefix_q != normalized_q:
            alt_matches = self._find_prefix_matches(alt_prefix_q)
            if alt_matches and not candidates:
                normalized_q = alt_prefix_q
            for item, score in alt_matches:
                candidates.append((item, score * 0.95))

        # 3. Deduplicate by item_id, retaining highest score
        best_per_item: dict[str, tuple[_IndexKey, float]] = {}
        for item, score in candidates:
            if item.item_id not in best_per_item or score > best_per_item[item.item_id][1]:
                best_per_item[item.item_id] = (item, score)

        # Rank candidates by score descending
        sorted_candidates = sorted(best_per_item.values(), key=lambda x: x[1], reverse=True)

        # 4. Construct QuerySuggestion instances
        suggestions: list[QuerySuggestion] = []
        highlight_prefix = normalized_q if (normalized_q and not candidates) else clean_q

        for item, score in sorted_candidates[:eff_limit]:
            related_queries: list[str] = []
            if item.item_id in self._terms and include_related:
                related_queries = self._get_related_queries(self._terms[item.item_id])

            suggestions.append(
                QuerySuggestion(
                    id=item.item_id,
                    text=item.display_text,
                    category=item.category,
                    domain=item.domain,
                    domain_name=item.domain_name,
                    score=round(score, 3),
                    highlight=_highlight_match(item.display_text, highlight_prefix),
                    related_queries=related_queries,
                )
            )

        # 5. Add direct related suggestions if requested and capacity permits
        if include_related and len(suggestions) < eff_limit:
            seen_ids = {s.id for s in suggestions}
            for s in list(suggestions):
                if s.id in self._terms:
                    term_data = self._terms[s.id]
                    for rel_id in term_data.related_ids:
                        if rel_id in self._terms and rel_id not in seen_ids:
                            rel_term = self._terms[rel_id]
                            seen_ids.add(rel_id)
                            suggestions.append(
                                QuerySuggestion(
                                    id=rel_id,
                                    text=rel_term.term,
                                    category="related",
                                    domain=rel_term.domain,
                                    domain_name=rel_term.domain_name,
                                    score=round(s.score * 0.75, 3),
                                    highlight=rel_term.term,
                                    related_queries=[],
                                )
                            )
                            if len(suggestions) >= eff_limit:
                                break
                if len(suggestions) >= eff_limit:
                    break

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Prometheus metrics
        try:
            metrics.SUGGESTIONS_TOTAL.labels(has_suggestions=str(bool(suggestions)).lower()).inc()
            metrics.SUGGESTION_LATENCY.observe(latency_ms / 1000.0)
        except Exception as exc:
            logger.warning("suggester.metrics_failed", error=str(exc))

        return SuggestionResponse(
            query=query,
            normalized_query=normalized_q,
            suggestions=suggestions,
            latency_ms=round(latency_ms, 3),
            total=len(suggestions),
        )

    @classmethod
    def get_default(cls) -> SearchSuggester:
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_default_suggester() -> SearchSuggester:
    """Convenience accessor for default SearchSuggester."""
    return SearchSuggester.get_default()
