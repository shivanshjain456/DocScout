"""Regulatory HyDE (Hypothetical Document Embeddings) Engine (FEAT-014).

Synthesizes structured statutory hypothesis passages mirroring official RBI and SEBI
circular formatting for low-overlap queries before dense vector search.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import structlog

from app.api.metrics import HYDE_GENERATION_SECONDS, HYDE_INVOCATIONS_TOTAL

logger = structlog.get_logger("docscout.hyde")


@dataclass(frozen=True)
class HyDEConfig:
    """Configuration for Regulatory HyDE passage synthesis."""

    enabled: bool = False
    max_tokens: int = 120
    temperature: float = 0.0


# Domain clause patterns to map query terms to official statutory context
_STATUTORY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(capital|crar|tier 1|tier 2|net worth|basel)\b", re.IGNORECASE),
        "minimum regulatory capital adequacy requirements, risk-weighted assets, and prudential limits",
    ),
    (
        re.compile(
            r"\b(payment|settlement|aggregator|gateway|upi|wallet|ppi|tpap)\b", re.IGNORECASE
        ),
        "payment system operator governance, escrow accounts, dispute resolution, and settlement cycles",
    ),
    (
        re.compile(
            r"\b(cyber|security|incident|soc|ciso|vulnerability|ransomware)\b", re.IGNORECASE
        ),
        "cyber security frameworks, mandatory incident reporting within 6 hours, and business continuity",
    ),
    (
        re.compile(r"\b(kyc|aml|pmla|cdd|edd|pep|str|ctr|fiu)\b", re.IGNORECASE),
        "customer identification procedures, beneficial ownership verification, and suspicious transaction reporting",
    ),
    (
        re.compile(r"\b(nbfc|shadow bank|scale based|upper layer|middle layer)\b", re.IGNORECASE),
        "scale-based regulatory framework, asset classification norms, and corporate governance for NBFCs",
    ),
    (
        re.compile(r"\b(outsource|third party|vendor|service provider|cloud)\b", re.IGNORECASE),
        "prudential norms on outsourcing of financial services and IT systems to external service providers",
    ),
    (
        re.compile(r"\b(audit|compliance|internal control|inspection|sro)\b", re.IGNORECASE),
        "statutory audit procedures, self-regulatory standards, and compliance certification by the Board",
    ),
    (
        re.compile(r"\b(grievance|complaint|ombudsman|consumer|investor|odr)\b", re.IGNORECASE),
        "integrated ombudsman scheme, turnaround timelines for customer grievances, and conciliation",
    ),
)


class RegulatoryHyDEGenerator:
    """Deterministic, sub-millisecond statutory hypothesis passage synthesizer."""

    def __init__(self, config: HyDEConfig | None = None) -> None:
        self.config = config or HyDEConfig()

    def generate_hypothesis(
        self,
        query: str,
        config: HyDEConfig | None = None,
    ) -> str:
        """Generate a structured regulatory circular passage for dense query embedding.

        If query length does not satisfy validation rules (10-256 chars) or generation fails,
        falls back gracefully to the original query.
        """
        cfg = config or self.config
        clean_query = query.strip() if query else ""

        # Input validation rules: length between 10 and 256 characters
        if not (10 <= len(clean_query) <= 256):
            return query

        t0 = time.perf_counter()
        try:
            HYDE_INVOCATIONS_TOTAL.inc()
        except Exception:
            logger.debug("metric_inc_failed", exc_info=True)

        try:
            # 1. Determine relevant regulatory authority and statutory clauses
            is_sebi = bool(
                re.search(
                    r"\b(sebi|stock|broker|depository|shares|listed|brsr|scores|odr)\b",
                    clean_query,
                    re.IGNORECASE,
                )
            )
            authority = (
                "SECURITIES AND EXCHANGE BOARD OF INDIA" if is_sebi else "RESERVE BANK OF INDIA"
            )
            department = (
                "DEPARTMENT OF REGULATION / MARKET INTERMEDIARIES"
                if is_sebi
                else "DEPARTMENT OF REGULATION"
            )

            # 2. Extract matching statutory context hints
            hints: list[str] = []
            for pat, hint in _STATUTORY_HINTS:
                if pat.search(clean_query):
                    hints.append(hint)

            context_clause = (
                "; ".join(hints)
                if hints
                else "operational standards, governance norms, and prudential compliance"
            )

            # 3. Format structured regulatory circular clause
            hypothesis = (
                f"{authority} / {department} / NOTIFICATION. "
                f"Master Direction regarding {clean_query}. "
                f"In exercise of statutory powers, all Regulated Entities and Market Intermediaries "
                f"are hereby directed to ensure full compliance with directions governing {context_clause}. "
                f"Entities shall implement Board-approved policies, robust internal audit controls, "
                f"and adhere to prescribed supervisory reporting schedules without deviation."
            )

            # 4. Enforce max token / character boundary (capped at 120 tokens, ~500 chars)
            max_chars = min(cfg.max_tokens * 4, 480)
            if len(hypothesis) > max_chars:
                # Truncate at last complete word boundary
                truncated = hypothesis[:max_chars]
                last_space = truncated.rfind(" ")
                hypothesis = (truncated[:last_space] if last_space > 0 else truncated) + "..."

            duration = time.perf_counter() - t0
            try:
                HYDE_GENERATION_SECONDS.observe(duration)
            except Exception:
                logger.debug("metric_observe_failed", exc_info=True)

            logger.debug(
                "hyde.generated",
                query=clean_query,
                length=len(hypothesis),
                duration_ms=round(duration * 1000.0, 3),
            )

            return hypothesis

        except Exception:
            logger.warning("hyde.generation_failed", query=clean_query, exc_info=True)
            return clean_query


_DEFAULT_HYDE_GENERATOR = RegulatoryHyDEGenerator()


def get_default_hyde_generator() -> RegulatoryHyDEGenerator:
    return _DEFAULT_HYDE_GENERATOR
