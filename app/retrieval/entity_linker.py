"""Regulatory Concept Hierarchy and Statutory Entity Linker (FEAT-002).

Maps financial and market entities into a formal 35-node statutory taxonomy hierarchy
(e.g. Regulated Entity -> NBFC -> NBFC-ND-SI -> Core Investment Company) to
support automated entity recognition, query expansion, and entity-scoped filtering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.api.metrics import ENTITIES_LINKED

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StatutoryEntity:
    """A canonical regulatory entity category defined in statutory circulars."""

    entity_id: str
    canonical_name: str
    parent_ids: tuple[str, ...]
    child_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    statutory_source: str = "RBI/SEBI"


@dataclass(frozen=True)
class EntityLinkResult:
    """Outcome of linking a query span to a canonical statutory entity."""

    entity_id: str
    canonical_name: str
    parent_ids: list[str]
    child_ids: list[str]
    confidence: float


@dataclass(frozen=True)
class EntityLinkingConfig:
    """Configuration for entity linking and hierarchy resolution."""

    enabled: bool = True
    min_confidence: float = 0.85
    expand_children: bool = True


# Authoritative 35 statutory entity classifications across RBI & SEBI frameworks
STATUTORY_ENTITIES: tuple[StatutoryEntity, ...] = (
    # 1. Root
    StatutoryEntity(
        entity_id="regulated_entity",
        canonical_name="Regulated Entity",
        parent_ids=(),
        child_ids=(
            "commercial_bank",
            "cooperative_bank",
            "nbfc",
            "all_india_financial_institution",
            "payment_system_operator",
            "sebi_market_intermediary",
        ),
        aliases=("RE", "REs", "Regulated Entities", "regulated entity"),
    ),
    # 2. Commercial Banks
    StatutoryEntity(
        entity_id="commercial_bank",
        canonical_name="Commercial Bank",
        parent_ids=("regulated_entity",),
        child_ids=(
            "public_sector_bank",
            "private_sector_bank",
            "foreign_bank",
            "small_finance_bank",
            "payments_bank",
            "regional_rural_bank",
        ),
        aliases=("Commercial Banks", "scheduled commercial bank", "SCB", "SCBs"),
    ),
    StatutoryEntity(
        entity_id="public_sector_bank",
        canonical_name="Public Sector Bank",
        parent_ids=("commercial_bank",),
        child_ids=(),
        aliases=(
            "PSB",
            "PSBs",
            "nationalised bank",
            "public sector banks",
            "State Bank of India",
            "SBI",
        ),
    ),
    StatutoryEntity(
        entity_id="private_sector_bank",
        canonical_name="Private Sector Bank",
        parent_ids=("commercial_bank",),
        child_ids=(),
        aliases=("private bank", "private sector banks", "private banks"),
    ),
    StatutoryEntity(
        entity_id="foreign_bank",
        canonical_name="Foreign Bank",
        parent_ids=("commercial_bank",),
        child_ids=(),
        aliases=("foreign banks", "wholly owned subsidiary of foreign bank", "WOS"),
    ),
    StatutoryEntity(
        entity_id="small_finance_bank",
        canonical_name="Small Finance Bank",
        parent_ids=("commercial_bank",),
        child_ids=(),
        aliases=("SFB", "SFBs", "small finance banks"),
    ),
    StatutoryEntity(
        entity_id="payments_bank",
        canonical_name="Payments Bank",
        parent_ids=("commercial_bank",),
        child_ids=(),
        aliases=("PB", "PBs", "payment bank", "payments banks"),
    ),
    StatutoryEntity(
        entity_id="regional_rural_bank",
        canonical_name="Regional Rural Bank",
        parent_ids=("commercial_bank",),
        child_ids=(),
        aliases=("RRB", "RRBs", "gramin bank", "regional rural banks"),
    ),
    # 3. Co-operative Banks
    StatutoryEntity(
        entity_id="cooperative_bank",
        canonical_name="Co-operative Bank",
        parent_ids=("regulated_entity",),
        child_ids=("urban_cooperative_bank", "rural_cooperative_bank"),
        aliases=(
            "cooperative banks",
            "co-op bank",
            "co-operative banks",
            "cooperative credit institution",
        ),
    ),
    StatutoryEntity(
        entity_id="urban_cooperative_bank",
        canonical_name="Urban Co-operative Bank",
        parent_ids=("cooperative_bank",),
        child_ids=(),
        aliases=("UCB", "UCBs", "primary urban cooperative bank", "urban cooperative banks"),
    ),
    StatutoryEntity(
        entity_id="rural_cooperative_bank",
        canonical_name="Rural Co-operative Bank",
        parent_ids=("cooperative_bank",),
        child_ids=(),
        aliases=("StCB", "DCCB", "State Co-operative Bank", "District Central Co-operative Bank"),
    ),
    # 4. NBFC Family
    StatutoryEntity(
        entity_id="nbfc",
        canonical_name="Non-Banking Financial Company",
        parent_ids=("regulated_entity",),
        child_ids=(
            "nbfc_d",
            "nbfc_nd",
            "nbfc_nd_si",
            "nbfc_icc",
            "nbfc_mfi",
            "cic",
            "nbfc_factor",
            "nbfc_p2p",
            "nbfc_aa",
            "housing_finance_company",
        ),
        aliases=(
            "NBFC",
            "NBFCs",
            "shadow bank",
            "non-banking finance company",
            "non-banking financial companies",
        ),
    ),
    StatutoryEntity(
        entity_id="nbfc_d",
        canonical_name="Deposit-Taking NBFC",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("NBFC-D", "NBFCs-D", "deposit accepting NBFC", "deposit-taking NBFC"),
    ),
    StatutoryEntity(
        entity_id="nbfc_nd",
        canonical_name="Non-Deposit Taking NBFC",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("NBFC-ND", "NBFCs-ND", "non-deposit taking NBFC"),
    ),
    StatutoryEntity(
        entity_id="nbfc_nd_si",
        canonical_name="Systemically Important Non-Deposit Taking NBFC",
        parent_ids=("nbfc",),
        child_ids=("cic",),
        aliases=("NBFC-ND-SI", "systemically important NBFC", "NBFC ND SI", "ND-SI"),
    ),
    StatutoryEntity(
        entity_id="nbfc_icc",
        canonical_name="Investment and Credit Company",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=(
            "NBFC-ICC",
            "asset finance company",
            "loan company",
            "investment and credit company",
        ),
    ),
    StatutoryEntity(
        entity_id="nbfc_mfi",
        canonical_name="Micro Finance Institution",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("NBFC-MFI", "microfinance institution", "micro finance institutions"),
    ),
    StatutoryEntity(
        entity_id="cic",
        canonical_name="Core Investment Company",
        parent_ids=("nbfc", "nbfc_nd_si"),
        child_ids=(),
        aliases=(
            "CIC",
            "CICs",
            "systemically important core investment company",
            "core investment companies",
        ),
    ),
    StatutoryEntity(
        entity_id="nbfc_factor",
        canonical_name="NBFC-Factor",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("NBFC-Factor", "NBFC Factor", "factoring company"),
    ),
    StatutoryEntity(
        entity_id="nbfc_p2p",
        canonical_name="Peer-to-Peer Lending Platform",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("NBFC-P2P", "P2P lending platform", "peer to peer lending", "P2P lender"),
    ),
    StatutoryEntity(
        entity_id="nbfc_aa",
        canonical_name="Account Aggregator",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("NBFC-AA", "account aggregator", "account aggregators", "AA ecosystem"),
    ),
    StatutoryEntity(
        entity_id="housing_finance_company",
        canonical_name="Housing Finance Company",
        parent_ids=("nbfc",),
        child_ids=(),
        aliases=("HFC", "HFCs", "housing finance institutions", "housing finance companies"),
    ),
    # 5. All India Financial Institutions
    StatutoryEntity(
        entity_id="all_india_financial_institution",
        canonical_name="All-India Financial Institution",
        parent_ids=("regulated_entity",),
        child_ids=(),
        aliases=("AIFI", "AIFIs", "NABARD", "NHB", "EXIM Bank", "SIDBI", "NaBFID"),
    ),
    # 6. Payment System Operators
    StatutoryEntity(
        entity_id="payment_system_operator",
        canonical_name="Payment System Operator",
        parent_ids=("regulated_entity",),
        child_ids=(
            "payment_aggregator",
            "payment_gateway",
            "prepaid_payment_instrument_issuer",
            "trade_receivables_discounting_system",
        ),
        aliases=("PSO", "PSOs", "payment system provider", "NPCI", "payment system operators"),
    ),
    StatutoryEntity(
        entity_id="payment_aggregator",
        canonical_name="Payment Aggregator",
        parent_ids=("payment_system_operator",),
        child_ids=(),
        aliases=(
            "PA",
            "PAs",
            "online payment aggregator",
            "PA-CB",
            "merchant acquiring entity",
            "payment aggregators",
        ),
    ),
    StatutoryEntity(
        entity_id="payment_gateway",
        canonical_name="Payment Gateway",
        parent_ids=("payment_system_operator",),
        child_ids=(),
        aliases=("PG", "PGs", "payment gateway provider", "payment gateways"),
    ),
    StatutoryEntity(
        entity_id="prepaid_payment_instrument_issuer",
        canonical_name="Prepaid Payment Instrument Issuer",
        parent_ids=("payment_system_operator",),
        child_ids=(),
        aliases=(
            "PPI",
            "PPIs",
            "PPI issuer",
            "wallet issuer",
            "prepaid card issuer",
            "prepaid payment instruments",
        ),
    ),
    StatutoryEntity(
        entity_id="trade_receivables_discounting_system",
        canonical_name="Trade Receivables Discounting System",
        parent_ids=("payment_system_operator",),
        child_ids=(),
        aliases=("TReDS", "TReDS platform", "receivables exchange"),
    ),
    # 7. SEBI Market Intermediaries
    StatutoryEntity(
        entity_id="sebi_market_intermediary",
        canonical_name="SEBI Regulated Intermediary",
        parent_ids=("regulated_entity",),
        child_ids=(
            "stock_broker",
            "depository_participant",
            "asset_management_company",
            "alternative_investment_fund",
            "portfolio_manager",
            "credit_rating_agency",
        ),
        aliases=(
            "market intermediary",
            "SEBI intermediary",
            "registered intermediary",
            "market intermediaries",
        ),
    ),
    StatutoryEntity(
        entity_id="stock_broker",
        canonical_name="Stock Broker",
        parent_ids=("sebi_market_intermediary",),
        child_ids=(),
        aliases=(
            "trading member",
            "clearing member",
            "stock broker",
            "stockbrokers",
            "stock brokers",
        ),
    ),
    StatutoryEntity(
        entity_id="depository_participant",
        canonical_name="Depository Participant",
        parent_ids=("sebi_market_intermediary",),
        child_ids=(),
        aliases=("DP", "DPs", "depository participant", "depository participants", "NSDL", "CDSL"),
    ),
    StatutoryEntity(
        entity_id="asset_management_company",
        canonical_name="Asset Management Company",
        parent_ids=("sebi_market_intermediary",),
        child_ids=(),
        aliases=("AMC", "AMCs", "mutual fund", "mutual funds", "fund house"),
    ),
    StatutoryEntity(
        entity_id="alternative_investment_fund",
        canonical_name="Alternative Investment Fund",
        parent_ids=("sebi_market_intermediary",),
        child_ids=(),
        aliases=(
            "AIF",
            "AIFs",
            "Category I AIF",
            "Category II AIF",
            "Category III AIF",
            "alternative investment funds",
        ),
    ),
    StatutoryEntity(
        entity_id="portfolio_manager",
        canonical_name="Portfolio Manager",
        parent_ids=("sebi_market_intermediary",),
        child_ids=(),
        aliases=("PMS", "portfolio management services", "portfolio managers"),
    ),
    StatutoryEntity(
        entity_id="credit_rating_agency",
        canonical_name="Credit Rating Agency",
        parent_ids=("sebi_market_intermediary",),
        child_ids=(),
        aliases=(
            "CRA",
            "CRAs",
            "rating agency",
            "credit rating agencies",
            "CRISIL",
            "ICRA",
            "CARE",
        ),
    ),
)


class EntityTrieNode:
    """Trie node for fast prefix/exact statutory entity phrase matching."""

    def __init__(self) -> None:
        self.children: dict[str, EntityTrieNode] = {}
        self.entity: StatutoryEntity | None = None
        self.confidence: float = 0.0


class EntityLinker:
    """High-speed Trie-based entity recognition and hierarchy resolver."""

    def __init__(self, entities: tuple[StatutoryEntity, ...] = STATUTORY_ENTITIES) -> None:
        self.entities_by_id: dict[str, StatutoryEntity] = {e.entity_id: e for e in entities}
        self.root = EntityTrieNode()
        self._build_trie()

    def _build_trie(self) -> None:
        """Populate trie with canonical names and statutory aliases."""
        for ent in self.entities_by_id.values():
            # Add canonical name (1.0 confidence)
            self._insert_phrase(ent.canonical_name.lower(), ent, confidence=1.0)
            # Add aliases (0.90 to 0.95 confidence)
            for alias in ent.aliases:
                conf = 0.95 if len(alias) > 3 else 0.88
                self._insert_phrase(alias.lower(), ent, confidence=conf)

    def _insert_phrase(self, phrase: str, entity: StatutoryEntity, confidence: float) -> None:
        words = phrase.split()
        curr = self.root
        for word in words:
            if word not in curr.children:
                curr.children[word] = EntityTrieNode()
            curr = curr.children[word]
        if curr.entity is None or confidence > curr.confidence:
            curr.entity = entity
            curr.confidence = confidence

    def is_in_scope(self, entity_id: str, scope_root: str) -> bool:
        """Check if an entity is identical to or a descendant of scope_root."""
        if entity_id == scope_root:
            return True
        visited: set[str] = set()
        stack = [entity_id]
        while stack:
            curr = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            ent = self.entities_by_id.get(curr)
            if not ent:
                continue
            if scope_root in ent.parent_ids:
                return True
            stack.extend(ent.parent_ids)
        return False

    def link(
        self,
        query: str,
        entity_scope: str | None = None,
        config: EntityLinkingConfig | None = None,
    ) -> list[EntityLinkResult]:
        """Parse query, match entity mentions, and return canonical links with hierarchy."""
        if len(query) > 512:
            raise ValueError(f"query length {len(query)} exceeds maximum 512 characters")

        cfg = config if config is not None else EntityLinkingConfig()
        if not cfg.enabled:
            return []

        # Tokenize query preserving alphanumeric and hyphens
        # Clean query tokens
        clean_q = re.sub(r"[^\w\s\-]", " ", query.lower())
        tokens = [t for t in clean_q.split() if t]

        matches: dict[str, EntityLinkResult] = {}

        n = len(tokens)
        for i in range(n):
            curr = self.root
            for j in range(i, min(n, i + 6)):  # max phrase length 6
                token = tokens[j]
                if token not in curr.children:
                    break
                curr = curr.children[token]
                if curr.entity is not None and curr.confidence >= cfg.min_confidence:
                    ent = curr.entity
                    # Check scope filter if specified
                    if entity_scope and not self.is_in_scope(ent.entity_id, entity_scope):
                        continue

                    # Record match
                    if (
                        ent.entity_id not in matches
                        or curr.confidence > matches[ent.entity_id].confidence
                    ):
                        matches[ent.entity_id] = EntityLinkResult(
                            entity_id=ent.entity_id,
                            canonical_name=ent.canonical_name,
                            parent_ids=list(ent.parent_ids),
                            child_ids=list(ent.child_ids),
                            confidence=curr.confidence,
                        )
                        ENTITIES_LINKED.labels(entity_type=ent.entity_id).inc()

        results = list(matches.values())
        logger.debug(
            "entity_linking_resolved",
            query_prefix=query[:32],
            linked_count=len(results),
            entity_ids=[r.entity_id for r in results],
        )
        return results
