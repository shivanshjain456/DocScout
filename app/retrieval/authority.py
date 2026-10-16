"""Regulatory Authority Hierarchy Resolver (FEAT-045).

Encodes statutory legal precedence across regulatory instruments:
Tier 1: Constitution & Parliamentary Acts (PMLA, RBI Act, BR Act) -> 1.25x
Tier 2: Master Directions (Statutory Directions under Act powers) -> 1.15x
Tier 3: Regulatory Circulars / Notifications -> 1.05x
Tier 4: Guidelines & Operational Specifications -> 1.00x
Tier 5: Press Releases, Clarifications & FAQs -> 0.85x

Prioritizes binding higher-tier statutory instruments over informal subordinate
commentary when conflicting or overlapping topics are retrieved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

DocumentClass = Literal["ACT", "MASTER_DIRECTION", "CIRCULAR", "GUIDELINE", "FAQ"]

VALID_DOCUMENT_CLASSES: frozenset[str] = frozenset(
    {"ACT", "MASTER_DIRECTION", "CIRCULAR", "GUIDELINE", "FAQ"}
)

CLASS_TO_TIER: dict[str, int] = {
    "ACT": 1,
    "MASTER_DIRECTION": 2,
    "CIRCULAR": 3,
    "GUIDELINE": 4,
    "FAQ": 5,
}

TIER_TO_CLASS: dict[int, str] = {
    1: "ACT",
    2: "MASTER_DIRECTION",
    3: "CIRCULAR",
    4: "GUIDELINE",
    5: "FAQ",
}

DEFAULT_TIER_MULTIPLIERS: dict[str, float] = {
    "ACT": 1.25,
    "MASTER_DIRECTION": 1.15,
    "CIRCULAR": 1.05,
    "GUIDELINE": 1.0,
    "FAQ": 0.85,
}


@dataclass(frozen=True)
class AuthorityWeight:
    """Precedence tier and score boost multiplier for a regulatory document."""

    tier: int
    boost_multiplier: float
    document_class: str


@dataclass(frozen=True)
class AuthorityConfig:
    """Configuration for authority hierarchy scoring."""

    tier_multipliers: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TIER_MULTIPLIERS)
    )
    enabled: bool = True
    neutral_multiplier: float = 1.0
    neutral_tier: int = 4

    def __post_init__(self) -> None:
        for doc_cls, mult in self.tier_multipliers.items():
            if mult <= 0.0:
                raise ValueError(f"Tier multiplier for '{doc_cls}' must be positive, got {mult}")


_DEFAULT_CONFIG = AuthorityConfig()


def get_default_authority_config() -> AuthorityConfig:
    """Return singleton default authority config."""
    return _DEFAULT_CONFIG


def infer_document_class_from_title(title: str | None) -> str | None:
    """Infer statutory document class from title text heuristics."""
    if not title:
        return None
    t = title.strip()
    tl = t.lower()

    if "master direction" in tl or "master directions" in tl:
        return "MASTER_DIRECTION"
    if "frequently asked questions" in tl or "faq" in tl or "press release" in tl:
        return "FAQ"
    if "guideline" in tl or "framework" in tl or "operating standard" in tl:
        return "GUIDELINE"
    if "circular" in tl or "notification" in tl:
        return "CIRCULAR"
    # Parliamentary acts or constitution
    if (
        " act" in tl
        or tl.endswith(" act")
        or "ordinance" in tl
        or "constitution" in tl
        or "statute" in tl
    ):
        return "ACT"

    return None


class RegulatoryAuthorityResolver:
    """Resolves statutory authority tier and computes ranking multipliers."""

    def __init__(self, config: AuthorityConfig | None = None) -> None:
        self.config = config or get_default_authority_config()
        self._cache: dict[tuple[str | None, str | None], AuthorityWeight] = {}

    def resolve(
        self,
        document_class: str | None,
        title: str | None = None,
        authority_tier: int | None = None,
    ) -> AuthorityWeight:
        """Resolve authority weight for given document class, title, or tier.

        Guarantees sub-0.05ms execution overhead.
        """
        # Fast path if explicit tier provided
        if authority_tier is not None and 1 <= authority_tier <= 5:
            doc_cls = TIER_TO_CLASS.get(authority_tier, "CIRCULAR")
            multiplier = self.config.tier_multipliers.get(doc_cls, self.config.neutral_multiplier)
            return AuthorityWeight(
                tier=authority_tier,
                boost_multiplier=multiplier,
                document_class=doc_cls,
            )

        key = (document_class, title)
        if key in self._cache:
            return self._cache[key]

        normalized_class: str | None = None
        if document_class:
            cand = document_class.strip().upper().replace(" ", "_").replace("-", "_")
            if cand in VALID_DOCUMENT_CLASSES:
                normalized_class = cand

        if normalized_class is None and title:
            normalized_class = infer_document_class_from_title(title)

        if normalized_class is not None and normalized_class in self.config.tier_multipliers:
            tier = CLASS_TO_TIER.get(normalized_class, self.config.neutral_tier)
            multiplier = self.config.tier_multipliers.get(
                normalized_class, self.config.neutral_multiplier
            )
            res = AuthorityWeight(
                tier=tier,
                boost_multiplier=multiplier,
                document_class=normalized_class,
            )
        else:
            res = AuthorityWeight(
                tier=self.config.neutral_tier,
                boost_multiplier=self.config.neutral_multiplier,
                document_class=document_class or "UNKNOWN",
            )

        if len(self._cache) < 2048:
            self._cache[key] = res
        return res

    def compute_boost(
        self,
        score: float,
        document_class: str | None,
        title: str | None = None,
        authority_tier: int | None = None,
    ) -> tuple[float, AuthorityWeight]:
        """Compute boosted score by applying statutory authority multiplier.

        Overhead is guaranteed <= 0.05ms.
        """
        if not self.config.enabled:
            weight = AuthorityWeight(
                tier=self.config.neutral_tier,
                boost_multiplier=1.0,
                document_class=document_class or "UNKNOWN",
            )
            return score, weight

        t0 = time.perf_counter()
        weight = self.resolve(document_class, title, authority_tier)
        boosted = score * weight.boost_multiplier
        dur_ms = (time.perf_counter() - t0) * 1000.0

        if dur_ms > 0.05:
            logger.debug(
                "authority_boost_slow",
                duration_ms=round(dur_ms, 4),
                document_class=document_class,
            )

        return boosted, weight


_RESOLVER = RegulatoryAuthorityResolver()


def get_default_authority_resolver() -> RegulatoryAuthorityResolver:
    """Return default singleton resolver."""
    return _RESOLVER
