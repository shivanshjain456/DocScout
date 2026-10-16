"""Multi-Turn Conversational Coreference Resolver (FEAT-017).

Resolves anaphoric pronouns and conversational ellipses across chat turns
by anchoring context to previously cited circulars, regulatory notification numbers,
and domain entities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from app.api import metrics

logger = structlog.get_logger(__name__)


# Circular ID regex pattern matching RBI and SEBI official publication formats
CIRCULAR_ID_REGEX = re.compile(
    r"\b(?:"
    r"RBI/(?:20\d{2}-\d{2,4})/\d+|"
    r"SEBI/[A-Z0-9\/\-\.]+|"
    r"(?:DOR|FIDD|DPSS|DOS|FMRD|IDMD|DGBA|CO)\.[A-Z0-9\.\-\/]+"
    r")\b",
    re.IGNORECASE,
)

# Known high-frequency regulatory concepts catalog for antecedent extraction
REGULATORY_CONCEPTS: tuple[str, ...] = (
    "Digital Lending",
    "Default Loss Guarantee",
    "First Loss Default Guarantee",
    "FLDG",
    "Payment Aggregator",
    "Payment Gateway",
    "Prudential Norms",
    "Capital Adequacy Ratio",
    "Liquidity Coverage Ratio",
    "Net Stable Funding Ratio",
    "Cash Reserve Ratio",
    "Statutory Liquidity Ratio",
    "Priority Sector Lending",
    "Non-Performing Assets",
    "Asset Reconstruction Company",
    "Know Your Customer",
    "Anti-Money Laundering",
    "Customer Due Diligence",
    "Cyber Security Framework",
    "Outsourcing of Financial Services",
    "Scale Based Regulation",
    "Large Exposures Framework",
    "Foreign Portfolio Investor",
    "Central KYC Records Registry",
    "CKYCR",
    "Self-Regulatory Organisation",
    "Legal Entity Identifier",
    "Business Responsibility and Sustainability Reporting",
    "BRSR",
    "Account Aggregator",
    "Urban Co-operative Banks",
    "Microfinance Loans",
    "Internal Ombudsman",
    "Wilful Defaulters",
    "Credit Information Companies",
    "Co-Lending Model",
    "Core Banking Solution",
    "UPI",
    "Tokenisation",
    "Prepaid Payment Instruments",
    "PPI",
    "Trade Receivables Discounting System",
    "TReDS",
    "Credit Card",
    "Debit Card",
    "Master Direction",
)


class ChatMessage(BaseModel):
    """A single turn in conversational multi-turn chat."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=1000)
    circular_ids: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class CoreferenceResolution(BaseModel):
    """Result of conversational coreference resolution."""

    rewritten_query: str
    resolved_entities: list[str] = Field(default_factory=list)
    referenced_circular_ids: list[str] = Field(default_factory=list)
    was_rewritten: bool = False


@dataclass(frozen=True)
class ChatConfig:
    """Configuration schema for chat coreference resolution (FEAT-017)."""

    max_history_turns: int = 5
    coreference_model: str = "fast-rule"
    max_query_chars: int = 512


class CoreferenceResolver:
    """Resolves anaphora and conversational ellipses in multi-turn dialogues."""

    def __init__(self, config: ChatConfig | None = None) -> None:
        self.config = config or ChatConfig()
        self._concept_map = {c.lower(): c for c in REGULATORY_CONCEPTS}

    def extract_context(self, history: list[ChatMessage]) -> tuple[list[str], list[str]]:
        """Extract referenced circular IDs and regulatory entities from chat history."""
        circular_ids: list[str] = []
        entities: list[str] = []
        seen_cids: set[str] = set()
        seen_ents: set[str] = set()

        # Scan turns in reverse (most recent turn first)
        recent_turns = history[-self.config.max_history_turns :]
        for turn in reversed(recent_turns):
            # 1. Explicit circular IDs attached to message
            for cid in turn.circular_ids:
                cid_clean = cid.strip()
                if cid_clean and cid_clean not in seen_cids:
                    seen_cids.add(cid_clean)
                    circular_ids.append(cid_clean)

            # 2. Text regex extraction for circular IDs
            for match in CIRCULAR_ID_REGEX.finditer(turn.content):
                cid_text = match.group(0).strip()
                if cid_text and cid_text not in seen_cids:
                    seen_cids.add(cid_text)
                    circular_ids.append(cid_text)

            # 3. Explicit entities attached to message
            for ent in turn.entities:
                ent_clean = ent.strip()
                if ent_clean and ent_clean.lower() not in seen_ents:
                    seen_ents.add(ent_clean.lower())
                    entities.append(ent_clean)

            # 4. Known regulatory concept extraction from message text
            content_lower = turn.content.lower()
            for key_lower, canonical in self._concept_map.items():
                if key_lower in content_lower and key_lower not in seen_ents:
                    seen_ents.add(key_lower)
                    entities.append(canonical)

        return circular_ids, entities

    def is_standalone(self, message: str) -> bool:
        """Determine whether a message is already self-contained."""
        m_lower = message.strip().lower()

        # Ellipsis opening checks
        ellipsis_prefixes = (
            "what about",
            "how about",
            "and what",
            "and does",
            "and how",
            "and if",
            "any exceptions",
            "are there exceptions",
            "who is exempt",
            "applicability to",
            "when does it",
            "when does this",
            "when does that",
            "when do these",
            "when will it",
            "what is its",
            "what are its",
            "does it apply",
            "does that apply",
            "does this apply",
            "is it applicable",
            "are these applicable",
        )
        if any(m_lower.startswith(pref) for pref in ellipsis_prefixes):
            return False

        # Short elliptical follow-ups (e.g., "And penal interest?", "Any penalties?")
        if (
            re.match(r"^(?:and\s+)?(?:any\s+)?[a-z0-9\s\-]{2,30}\?*$", m_lower)
            and len(m_lower.split()) <= 4
        ):
            if not any(
                k in m_lower for k in ("what is", "what are", "how does", "define", "explain")
            ):
                return False

        # Anaphoric pronouns with broad scope
        pronoun_patterns = (
            r"\b(?:it|its|this|that|they|them|these|those)\b",
            r"\b(?:this|that|such|said|the)\s+(?:circular|guidelines?|directions?|norms?|notification|framework|instructions?|rules?|policy|scheme|provisions?)\b",
            r"\b(?:the\s+same|said\s+mandate)\b",
        )
        for pat in pronoun_patterns:
            if re.search(pat, m_lower):
                # If pronoun is used without an antecedent in the same sentence, not standalone
                # Check if an explicit named regulatory concept is present in the message
                has_own_entity = any(k in m_lower for k in self._concept_map if len(k) > 4)
                # If it refers to "its exceptions" or "this circular" even with entity, might be relative
                if re.search(
                    r"\b(?:its|this circular|that circular|said circular|said directions)\b",
                    m_lower,
                ):
                    return False
                if re.search(r"\bwhen\s+does\s+(?:it|this|that)\b", m_lower):
                    return False
                if not has_own_entity:
                    return False

        return True

    def resolve(self, message: str, history: list[ChatMessage]) -> CoreferenceResolution:
        """Resolve coreference and ellipsis, returning rewritten standalone query."""
        if not message or not message.strip():
            return CoreferenceResolution(rewritten_query="")

        clean_message = message.strip()
        if len(clean_message) > self.config.max_query_chars:
            clean_message = clean_message[: self.config.max_query_chars]

        # If no history exists, message cannot be coreferenced
        if not history:
            self._record_metric("unmodified")
            return CoreferenceResolution(rewritten_query=clean_message)

        # Check if already standalone
        if self.is_standalone(clean_message):
            self._record_metric("unmodified")
            return CoreferenceResolution(rewritten_query=clean_message)

        # Extract context antecedents
        circular_ids, entities = self.extract_context(history)
        if not circular_ids and not entities:
            # No antecedent available in history
            self._record_metric("unmodified")
            return CoreferenceResolution(rewritten_query=clean_message)

        # Primary antecedent phrase for substitution
        primary_antecedent = entities[0] if entities else circular_ids[0]
        context_anchor = (
            f"{entities[0]} ({circular_ids[0]})"
            if (entities and circular_ids)
            else (entities[0] if entities else circular_ids[0])
        )

        rewritten = clean_message
        m_lower = clean_message.lower().rstrip("?.")

        # 1. Handle Ellipsis Patterns
        # "What about NBFCs?" / "How about cooperative banks?"
        clean_stripped = clean_message.rstrip("?.")
        what_about_match = re.match(r"^(?:what|how)\s+about\s+(.+)$", clean_stripped, re.IGNORECASE)
        if what_about_match:
            target = what_about_match.group(1).strip()
            rewritten = f"Does {context_anchor} apply to {target}?"
            return self._build_resolution(rewritten, entities, circular_ids)

        # "And penal interest?" / "And the disclosure requirements?"
        and_match = re.match(
            r"^and\s+(?:what\s+(?:is|are)\s+the\s+)?(.+)$", clean_stripped, re.IGNORECASE
        )
        if and_match:
            sub = and_match.group(1).strip()
            rewritten = f"What are the {sub} provisions under {context_anchor}?"
            return self._build_resolution(rewritten, entities, circular_ids)

        # "Any exceptions?" / "What are the exceptions?" / "Are there exceptions?"
        if re.search(r"\b(?:any|what\s+are\s+the|are\s+there\s+any)\s+exceptions\b", m_lower):
            rewritten = f"What are the exceptions under {context_anchor}?"
            return self._build_resolution(rewritten, entities, circular_ids)

        # "When does it come into effect?" / "When does it take effect?"
        if re.search(
            r"\bwhen\s+does\s+(?:it|this|that)\s+(?:come\s+into\s+effect|take\s+effect|apply)\b",
            m_lower,
        ):
            rewritten = f"When does {context_anchor} come into effect?"
            return self._build_resolution(rewritten, entities, circular_ids)

        # "Who is exempt?" / "Who is exempted?"
        if re.search(r"\bwho\s+is\s+exempt(?:ed)?\b", m_lower):
            rewritten = f"Who is exempt from {context_anchor}?"
            return self._build_resolution(rewritten, entities, circular_ids)

        # 2. Handle Anaphoric Pronoun / Phrase Substitutions
        # Replace "its exceptions" / "its guidelines" / "its penalties" -> "[context_anchor]'s exceptions"
        rewritten = re.sub(
            r"\b(?:its|it's)\b",
            f"{primary_antecedent}'s",
            rewritten,
            flags=re.IGNORECASE,
        )

        # Replace phrases: "this circular", "that circular", "the circular", "said directions", etc.
        circular_phrases = r"\b(?:this|that|such|the|said)\s+(?:circular|directions?|guidelines?|notification|framework|norms?|instructions?|rules?)\b"
        if re.search(circular_phrases, rewritten, flags=re.IGNORECASE):
            rewritten = re.sub(
                circular_phrases,
                context_anchor,
                rewritten,
                flags=re.IGNORECASE,
            )

        # Replace "does it apply to" / "is it applicable to" / "does that apply to"
        apply_pat = r"\b(?:does|is)\s+(?:it|that|this)\s+(?:apply|applicable)\s+to\b"
        if re.search(apply_pat, rewritten, flags=re.IGNORECASE):
            rewritten = re.sub(
                apply_pat,
                f"does {context_anchor} apply to",
                rewritten,
                flags=re.IGNORECASE,
            )

        # Replace remaining standalone singular pronouns ("it", "this", "that")
        # only where followed or preceded by verbs
        pronoun_verb_pat = (
            r"\b(?:it|this|that)\s+(say|state|mandate|require|prescribe|cover|mention|prohibit)s?\b"
        )
        if re.search(pronoun_verb_pat, rewritten, flags=re.IGNORECASE):
            rewritten = re.sub(
                pronoun_verb_pat,
                f"{primary_antecedent} \\1s",
                rewritten,
                flags=re.IGNORECASE,
            )

        # Plural references: "these rules", "these norms", "they", "them"
        rewritten = re.sub(
            r"\b(?:these|those)\s+(?:rules|norms|requirements|guidelines)\b",
            f"{context_anchor} rules",
            rewritten,
            flags=re.IGNORECASE,
        )

        # If rewritten hasn't changed but query was not standalone, anchor context at end
        if rewritten == clean_message:
            rewritten = f"{clean_message} regarding {context_anchor}"

        return self._build_resolution(rewritten, entities, circular_ids)

    def _build_resolution(
        self, rewritten: str, entities: list[str], circular_ids: list[str]
    ) -> CoreferenceResolution:
        self._record_metric("resolved")
        logger.debug(
            "coreference.resolved",
            rewritten_query=rewritten,
            resolved_entities=entities,
            referenced_circular_ids=circular_ids,
        )
        return CoreferenceResolution(
            rewritten_query=rewritten,
            resolved_entities=entities,
            referenced_circular_ids=circular_ids,
            was_rewritten=True,
        )

    def _record_metric(self, status: str) -> None:
        try:
            metrics.COREFERENCES_RESOLVED_TOTAL.labels(status=status).inc()
        except Exception as exc:
            logger.debug("coreference.metric_failed", error=str(exc))


_DEFAULT_RESOLVER: CoreferenceResolver | None = None


def get_default_coreference_resolver() -> CoreferenceResolver:
    """Return singleton CoreferenceResolver instance."""
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is None:
        _DEFAULT_RESOLVER = CoreferenceResolver()
    return _DEFAULT_RESOLVER
