"""Intent-Driven Query Classification & Routing Engine (FEAT-013).

Automatically classifies incoming diagnostic queries against the 21 taxonomy intents
and statutory incident readiness, enriching responses with prescriptive firstMove guidance.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from app.api.metrics import INTENT_ROUTING_LATENCY, QUERIES_BY_INTENT_TOTAL
from app.api.models import IntentClassification
from app.retrieval._intent_data import INTENT_DEFINITIONS, IntentDefinition

if TYPE_CHECKING:
    pass

logger = structlog.get_logger("docscout.intent_router")


@dataclass(frozen=True)
class IntentRouterConfig:
    """Configuration for query intent classification and routing."""

    enabled: bool = True
    min_confidence: float = 0.65


@dataclass(frozen=True)
class _CompiledIntent:
    definition: IntentDefinition
    utterance_lowers: tuple[str, ...]
    tokens: frozenset[str]
    utterance_patterns: tuple[re.Pattern[str], ...]


def _compile_intent(defn: IntentDefinition) -> _CompiledIntent:
    u_lowers = tuple(u.lower().strip() for u in defn.utterances)
    tokens: set[str] = set()
    for u in defn.utterances:
        tokens.update(re.findall(r"\b[a-z0-9_-]+\b", u.lower()))
    for r in defn.routes_to:
        tokens.update(re.findall(r"\b[a-z0-9_-]+\b", r.lower()))
    tokens.update(re.findall(r"\b[a-z0-9_-]+\b", defn.first_move.lower()))

    patterns: list[re.Pattern[str]] = []
    for u in u_lowers:
        patterns.append(re.compile(r"\b" + re.escape(u) + r"\b", re.IGNORECASE))

    return _CompiledIntent(
        definition=defn,
        utterance_lowers=u_lowers,
        tokens=frozenset(tokens),
        utterance_patterns=tuple(patterns),
    )


_COMPILED_INTENTS: tuple[_CompiledIntent, ...] = tuple(
    _compile_intent(defn) for defn in INTENT_DEFINITIONS
)


class IntentRouter:
    """Classifies user queries against diagnostic intents in sub-millisecond latency."""

    def __init__(
        self,
        intents: tuple[_CompiledIntent, ...] = _COMPILED_INTENTS,
        config: IntentRouterConfig | None = None,
    ) -> None:
        self._intents = intents
        self.config = config or IntentRouterConfig()

    def classify(
        self,
        query: str,
        config: IntentRouterConfig | None = None,
    ) -> IntentClassification | None:
        """Classify a query into a diagnostic intent if confidence exceeds threshold."""
        cfg = config or self.config
        if not cfg.enabled or not query:
            return None

        clean_query = query.strip()
        # Input validation rules: length between 5 and 512 characters
        if len(clean_query) < 5 or len(clean_query) > 512:
            return None

        t0 = time.perf_counter()
        q_lower = clean_query.lower()
        q_tokens = set(re.findall(r"\b[a-z0-9_-]+\b", q_lower))

        best_intent: IntentDefinition | None = None
        best_score = 0.0

        for ci in self._intents:
            score = 0.0
            # 1. Exact or regex utterance match
            for pat in ci.utterance_patterns:
                if pat.search(clean_query):
                    score = 1.0
                    break

            if score < 1.0:
                for u in ci.utterance_lowers:
                    if q_lower == u:
                        score = 1.0
                        break
                    elif u in q_lower or q_lower in u:
                        score = max(score, 0.90)

            # 2. Token overlap similarity
            if q_tokens:
                overlap = len(q_tokens.intersection(ci.tokens))
                if overlap > 0:
                    token_score = overlap / (len(q_tokens) + 0.5)
                    score = max(score, min(token_score, 0.92))

            if score > best_score:
                best_score = score
                best_intent = ci.definition

        duration = time.perf_counter() - t0
        try:
            INTENT_ROUTING_LATENCY.observe(duration)
        except Exception:
            logger.debug("metric_observe_failed", exc_info=True)

        if best_intent is not None and best_score >= cfg.min_confidence:
            try:
                QUERIES_BY_INTENT_TOTAL.labels(intent_id=best_intent.id).inc()
            except Exception:
                logger.debug("metric_inc_failed", exc_info=True)

            logger.debug(
                "query.intent_classified",
                query=clean_query,
                intent_id=best_intent.id,
                confidence=round(best_score, 4),
                duration_ms=round(duration * 1000.0, 3),
            )

            return IntentClassification(
                intent_id=best_intent.id,
                label=best_intent.label,
                primary_domain=best_intent.primary_domain,
                first_move=best_intent.first_move,
                confidence=round(best_score, 4),
                recommended_terms=list(best_intent.routes_to),
            )

        return None


_DEFAULT_INTENT_ROUTER = IntentRouter()


def get_default_intent_router() -> IntentRouter:
    return _DEFAULT_INTENT_ROUTER
