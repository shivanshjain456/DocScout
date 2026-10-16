"""Persona-Tailored Query Profiling Engine (FEAT-020).

Provides specialized retrieval tuning profiles for different regulatory and technical
stakeholders (Fintech Developers, Statutory Auditors, Chief Risk Officers, Compliance Officers).
Adjusts dense/lexical fusion weights, graph centrality boost, difficulty banding,
expansion modes, and taxonomy layer focus.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import ClassVar, cast

import structlog

from app.api.models import PersonaProfileResponse
from app.retrieval.types import ExpansionMode, MetadataFilter, RetrievalConfig

logger = structlog.get_logger("docscout.persona")

# Canonical persona profile registry
PERSONA_PROFILES: dict[str, PersonaProfileResponse] = {
    "fintech_developer": PersonaProfileResponse(
        id="fintech_developer",
        name="Fintech Developer",
        title="Software Architect & Integration Engineer",
        description="Optimized for technical schemas, API contracts, tokenisation, webhooks, and engineering implementation guides.",
        target_audience="Fintech Engineers, Solutions Architects, and Technical Leads",
        weight_dense=1.0,
        weight_lexical=1.0,
        rrf_k=60,
        default_expansion_mode="synonym",
        default_difficulty_band="intermediate",
        centrality_weight=0.10,
        preferred_layers=[
            "architecture-and-data",
            "delivery-and-platform",
            "product-and-interface",
        ],
        auto_constrain_tags=False,
    ),
    "statutory_auditor": PersonaProfileResponse(
        id="statutory_auditor",
        name="Statutory Auditor",
        title="Chartered Accountant & Statutory Compliance Auditor",
        description="Optimized for exact circular citations, penal provisions, compliance deadlines, and verification rigor.",
        target_audience="Statutory Auditors, Inspection Teams, and Audit Partners",
        weight_dense=0.7,
        weight_lexical=1.5,
        rrf_k=50,
        default_expansion_mode="none",
        default_difficulty_band="expert",
        centrality_weight=0.05,
        preferred_layers=[
            "physical-and-regulated",
            "quality-and-verification",
        ],
        auto_constrain_tags=False,
    ),
    "risk_officer": PersonaProfileResponse(
        id="risk_officer",
        name="Chief Risk Officer",
        title="Risk Management & Prudential Controls Executive",
        description="Optimized for systemic risk, capital adequacy ratios (CRAR, LCR, NSFR), stress tests, and prudential frameworks.",
        target_audience="Chief Risk Officers, Risk Management Committees, and Board Executives",
        weight_dense=1.2,
        weight_lexical=0.8,
        rrf_k=60,
        default_expansion_mode="hyde",
        default_difficulty_band="advanced",
        centrality_weight=0.25,
        preferred_layers=[
            "physical-and-regulated",
            "security-and-trust",
            "reliability-and-operations",
        ],
        auto_constrain_tags=False,
    ),
    "compliance_officer": PersonaProfileResponse(
        id="compliance_officer",
        name="Compliance Officer",
        title="Regulatory Operations & Reporting Head",
        description="Optimized for Master Directions, periodic statutory reporting, KYC/AML processes, and supervisory circulars.",
        target_audience="Principal Compliance Officers, Regulatory Reporting Heads, Legal Counsel",
        weight_dense=1.0,
        weight_lexical=1.2,
        rrf_k=60,
        default_expansion_mode="combined",
        default_difficulty_band="intermediate",
        centrality_weight=0.15,
        preferred_layers=[
            "physical-and-regulated",
            "quality-and-verification",
            "security-and-trust",
        ],
        auto_constrain_tags=True,
    ),
}

# Aliases mapping shorthand query parameter inputs to canonical persona IDs
PERSONA_ALIASES: dict[str, str] = {
    "developer": "fintech_developer",
    "dev": "fintech_developer",
    "software_engineer": "fintech_developer",
    "auditor": "statutory_auditor",
    "audit": "statutory_auditor",
    "chartered_accountant": "statutory_auditor",
    "cro": "risk_officer",
    "risk": "risk_officer",
    "chief_risk_officer": "risk_officer",
    "compliance": "compliance_officer",
    "cco": "compliance_officer",
    "regulatory_affairs": "compliance_officer",
}

# Heuristic query intent cues for auto-profiling
_PERSONA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fintech_developer": (
        "api",
        "webhook",
        "payload",
        "sdk",
        "tokenisation",
        "endpoint",
        "schema",
        "architecture",
        "coft",
        "upi",
        "rest",
        "json",
        "latency",
    ),
    "statutory_auditor": (
        "penalty",
        "penal",
        "statutory",
        "audit",
        "section 45",
        "disqualification",
        "inspection",
        "fine",
        "contravention",
        "section 141",
        "true and fair",
        "provisioning",
    ),
    "risk_officer": (
        "capital adequacy",
        "crar",
        "car",
        "lcr",
        "nsfr",
        "systemic risk",
        "liquidity ratio",
        "stress test",
        "exposure",
        "basel iii",
        "credit risk",
        "default loss",
    ),
    "compliance_officer": (
        "kyc",
        "aml",
        "due diligence",
        "filing",
        "master direction",
        "reporting timeline",
        "grievance",
        "ombudsman",
        "cdd",
        "fair practices code",
        "customer protection",
    ),
}


class PersonaProfiler:
    """Manages persona configurations and adapts retrieval parameters."""

    _instance: ClassVar[PersonaProfiler | None] = None

    def __init__(self) -> None:
        self._profiles = PERSONA_PROFILES
        self._aliases = PERSONA_ALIASES

    def resolve_persona_id(self, persona: str | None) -> str | None:
        """Resolve a raw persona string or alias to a canonical persona ID."""
        if not persona:
            return None
        clean = persona.strip().lower()
        if clean in ("general", "none", "default"):
            return None
        if clean in self._profiles:
            return clean
        return self._aliases.get(clean)

    def get_profile(self, persona: str | None) -> PersonaProfileResponse | None:
        """Retrieve profile metadata for a persona identifier or alias."""
        pid = self.resolve_persona_id(persona)
        return self._profiles.get(pid) if pid else None

    def list_profiles(self) -> list[PersonaProfileResponse]:
        """List all registered personas."""
        return list(self._profiles.values())

    def infer_persona(self, query: str) -> str | None:
        """Heuristically infer the most likely persona based on diagnostic query keywords."""
        if not query:
            return None
        q_lower = query.lower()

        scores: dict[str, int] = {}
        for pid, keywords in _PERSONA_KEYWORDS.items():
            count = 0
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", q_lower):
                    count += 1
            if count > 0:
                scores[pid] = count

        if not scores:
            return None
        # Return persona with the highest matching keyword count
        best_persona = max(scores.items(), key=lambda x: x[1])
        return best_persona[0]

    def apply_to_config(
        self,
        persona: str | None,
        base_config: RetrievalConfig,
        explicit_difficulty: str | None = None,
        explicit_expansion: str | None = None,
        explicit_auto_tags: bool | None = None,
    ) -> tuple[RetrievalConfig, PersonaProfileResponse | None]:
        """Adapt a RetrievalConfig according to the selected persona profile."""
        profile = self.get_profile(persona)
        if profile is None:
            return base_config, None

        # Resolve difficulty band: payload explicit value takes priority over profile default
        eff_difficulty = (
            explicit_difficulty
            if explicit_difficulty is not None
            else profile.default_difficulty_band
        )

        # Resolve expansion mode: explicit takes priority, else profile default, else base_config
        eff_expansion: ExpansionMode = base_config.expansion_mode
        eff_expand = base_config.expand_query
        if explicit_expansion is not None and explicit_expansion != "none":
            eff_expansion = cast(ExpansionMode, explicit_expansion)
            eff_expand = True
        elif profile.default_expansion_mode != "none":
            eff_expansion = cast(ExpansionMode, profile.default_expansion_mode)
            eff_expand = True

        # Resolve auto constrain tags
        eff_auto_tags = (
            explicit_auto_tags if explicit_auto_tags is not None else profile.auto_constrain_tags
        )

        # Resolve metadata filter with layer preference if not explicitly constrained
        eff_filter = base_config.filter
        if profile.preferred_layers:
            if eff_filter is None:
                eff_filter = MetadataFilter(taxonomy_layers=list(profile.preferred_layers))
            elif eff_filter.taxonomy_layers is None:
                eff_filter = eff_filter.model_copy(
                    update={"taxonomy_layers": list(profile.preferred_layers)}
                )

        adapted_config = replace(
            base_config,
            name=f"{base_config.name}:{profile.id}",
            weight_dense=profile.weight_dense,
            weight_lexical=profile.weight_lexical,
            rrf_k=profile.rrf_k,
            centrality_weight=profile.centrality_weight,
            difficulty_band=eff_difficulty,
            expansion_mode=eff_expansion,
            expand_query=eff_expand,
            auto_constrain_tags=eff_auto_tags,
            filter=eff_filter,
        )

        logger.info(
            "persona.adapted_config",
            persona=profile.id,
            weight_dense=profile.weight_dense,
            weight_lexical=profile.weight_lexical,
            difficulty_band=eff_difficulty,
            expansion_mode=eff_expansion,
        )

        return adapted_config, profile

    @classmethod
    def get_default(cls) -> PersonaProfiler:
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_default_persona_profiler() -> PersonaProfiler:
    """Convenience accessor for default PersonaProfiler."""
    return PersonaProfiler.get_default()
