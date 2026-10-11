"""Regulatory domain query understanding and expansion engine (P1-3).

Regulatory texts from the RBI and SEBI rely heavily on domain acronyms (e.g., PA, KYC,
NBFC, FPI, RE, ODR, PPI) and statutory phrases ("payment aggregator", "know your customer",
"regulated entity", "settlement cycle").

Because BM25 uses standard English stemming without domain awareness, vocabulary mismatches
in user queries ("What are the net worth criteria for PA?") cause lexical retrieval failure
whenever the statute uses the canonical term ("payment aggregator") instead of the abbreviation.
Conversely, dense vector representations benefit when domain-specific definitions and
canonical concepts clarify abbreviated queries.

This module provides:
1. High-precision bidirectional expansion (acronym <-> canonical phrases) across RBI/SEBI domains.
2. Word-boundary and case-guarded matching to eliminate false positives on common words.
3. Hypothetical Document Embeddings (HyDE) formulation generating regulatory excerpt hypotheses.
4. Clean separation of lexical enrichment (for BM25) and dense query formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import structlog
from pydantic import BaseModel

from app.api.metrics import ACRONYMS_EXPANDED_TOTAL
from app.retrieval._acronym_data import ACRONYM_INDEX_296

logger = structlog.get_logger(__name__)

ExpansionMode = Literal["none", "synonym", "hyde", "combined"]


class ExpansionConfig(BaseModel):
    """Configuration schema for regulatory and systems query expansion (FEAT-012)."""

    enabled: bool = True
    max_expansions_per_query: int = 5


@dataclass(frozen=True)
class RegulatoryConcept:
    """A canonical regulatory concept with its abbreviations and synonyms."""

    canonical: str
    acronyms: tuple[str, ...]
    synonyms: tuple[str, ...]
    case_sensitive_acronym: bool = False
    context_hint: str = ""


# Authoritative dictionary of financial regulatory terminology covering RBI, SEBI,
# PMLA, and Indian payment and capital market frameworks.
REGULATORY_CONCEPTS: tuple[RegulatoryConcept, ...] = (
    RegulatoryConcept(
        canonical="payment aggregator",
        acronyms=("PA", "PAs"),
        synonyms=(
            "payment aggregator",
            "payment aggregators",
            "online payment aggregator",
            "payment intermediary",
            "merchant acquiring entity",
        ),
        case_sensitive_acronym=True,
        context_hint="entities facilitating e-commerce payments between merchants and customers",
    ),
    RegulatoryConcept(
        canonical="payment gateway",
        acronyms=("PG", "PGs"),
        synonyms=("payment gateway", "payment gateways", "payment technology provider"),
        case_sensitive_acronym=True,
        context_hint="technology infrastructure provider routing digital payment transactions",
    ),
    RegulatoryConcept(
        canonical="non-banking financial company",
        acronyms=("NBFC", "NBFCs"),
        synonyms=(
            "non-banking financial company",
            "non-banking financial companies",
            "non-bank financial institution",
            "non-banking financial institution",
        ),
        case_sensitive_acronym=False,
        context_hint="financial institutions providing credit and financial services without full banking license",
    ),
    RegulatoryConcept(
        canonical="regulated entity",
        acronyms=("RE", "REs"),
        synonyms=("regulated entity", "regulated entities"),
        case_sensitive_acronym=True,
        context_hint="banks, NBFCs, payment system operators, and financial market intermediaries",
    ),
    RegulatoryConcept(
        canonical="credit information company",
        acronyms=("CIC", "CICs"),
        synonyms=(
            "credit information company",
            "credit information companies",
            "credit bureau",
            "credit bureaus",
        ),
        case_sensitive_acronym=False,
        context_hint="entities collecting and maintaining credit records under CICRA",
    ),
    RegulatoryConcept(
        canonical="alternative investment fund",
        acronyms=("AIF", "AIFs"),
        synonyms=(
            "alternative investment fund",
            "alternative investment funds",
            "privately pooled investment vehicle",
        ),
        case_sensitive_acronym=False,
        context_hint="privately pooled investment vehicles regulated under SEBI AIF Regulations",
    ),
    RegulatoryConcept(
        canonical="foreign portfolio investor",
        acronyms=("FPI", "FPIs"),
        synonyms=(
            "foreign portfolio investor",
            "foreign portfolio investors",
            "foreign institutional investor",
            "foreign institutional investors",
            "FII",
        ),
        case_sensitive_acronym=False,
        context_hint="foreign entities investing in Indian capital markets under SEBI FPI Regulations",
    ),
    RegulatoryConcept(
        canonical="online dispute resolution",
        acronyms=("ODR",),
        synonyms=(
            "online dispute resolution",
            "dispute resolution mechanism",
            "conciliation and arbitration portal",
        ),
        case_sensitive_acronym=False,
        context_hint="digital conciliation and arbitration framework for securities market disputes",
    ),
    RegulatoryConcept(
        canonical="prepaid payment instrument",
        acronyms=("PPI", "PPIs"),
        synonyms=(
            "prepaid payment instrument",
            "prepaid payment instruments",
            "prepaid wallet",
            "prepaid card",
            "stored value instrument",
        ),
        case_sensitive_acronym=False,
        context_hint="instruments facilitating purchase of goods and funds transfer against stored value",
    ),
    RegulatoryConcept(
        canonical="kyc registration agency",
        acronyms=("KRA", "KRAs"),
        synonyms=(
            "kyc registration agency",
            "kyc registration agencies",
            "centralized kyc record agency",
        ),
        case_sensitive_acronym=False,
        context_hint="agencies maintaining centralized KYC records for securities market intermediaries",
    ),
    RegulatoryConcept(
        canonical="depository participant",
        acronyms=("DP", "DPs"),
        synonyms=("depository participant", "depository participants"),
        case_sensitive_acronym=True,
        context_hint="agents of the depository offering depository services to investors",
    ),
    RegulatoryConcept(
        canonical="self-regulatory organisation",
        acronyms=("SRO", "SROs"),
        synonyms=(
            "self-regulatory organisation",
            "self-regulatory organisations",
            "self-regulatory organization",
            "self regulatory organization",
        ),
        case_sensitive_acronym=False,
        context_hint="industry body recognized for setting and enforcing industry standards",
    ),
    RegulatoryConcept(
        canonical="know your customer",
        acronyms=("KYC",),
        synonyms=(
            "know your customer",
            "customer identification procedure",
            "customer due diligence",
        ),
        case_sensitive_acronym=False,
        context_hint="mandatory customer verification procedures under PMLA and RBI Master Direction",
    ),
    RegulatoryConcept(
        canonical="central kyc records registry",
        acronyms=("CKYC", "CKYCR"),
        synonyms=(
            "central kyc",
            "central kyc records registry",
            "central know your customer",
        ),
        case_sensitive_acronym=False,
        context_hint="single registry to receive, store, safeguard and retrieve KYC records of an investor",
    ),
    RegulatoryConcept(
        canonical="prevention of money laundering act",
        acronyms=("PMLA",),
        synonyms=(
            "prevention of money laundering act",
            "anti-money laundering",
            "anti money laundering",
            "aml",
        ),
        case_sensitive_acronym=False,
        context_hint="statutory legislation governing money laundering prevention and reporting in India",
    ),
    RegulatoryConcept(
        canonical="legal entity identifier",
        acronyms=("LEI",),
        synonyms=("legal entity identifier", "20-digit lei code", "lei code"),
        case_sensitive_acronym=False,
        context_hint="20-character global identifier for legal entities participating in financial transactions",
    ),
    RegulatoryConcept(
        canonical="liberalised remittance scheme",
        acronyms=("LRS",),
        synonyms=(
            "liberalised remittance scheme",
            "liberalized remittance scheme",
            "outward remittance facility",
        ),
        case_sensitive_acronym=False,
        context_hint="RBI facility permitting resident individuals to remit funds abroad up to USD 250,000",
    ),
    RegulatoryConcept(
        canonical="differential rate of interest",
        acronyms=("DRI",),
        synonyms=(
            "differential rate of interest",
            "differential rate of interest scheme",
            "dri scheme",
        ),
        case_sensitive_acronym=False,
        context_hint="concessional 4 percent interest credit scheme for low-income and vulnerable borrowers",
    ),
    RegulatoryConcept(
        canonical="credit enhancement guarantee scheme for scheduled castes",
        acronyms=("CEGSSC",),
        synonyms=(
            "credit enhancement guarantee scheme for scheduled castes",
            "credit enhancement guarantee scheme",
        ),
        case_sensitive_acronym=False,
        context_hint="guarantee scheme promoting entrepreneurship among Scheduled Castes",
    ),
    RegulatoryConcept(
        canonical="foreign exchange management act",
        acronyms=("FEMA",),
        synonyms=("foreign exchange management act", "foreign exchange regulations"),
        case_sensitive_acronym=False,
        context_hint="statute regulating cross-border payments, export realisation, and foreign exchange",
    ),
    RegulatoryConcept(
        canonical="customer due diligence",
        acronyms=("CDD",),
        synonyms=("customer due diligence", "client due diligence"),
        case_sensitive_acronym=False,
        context_hint="identifying and verifying the customer and beneficial owner",
    ),
    RegulatoryConcept(
        canonical="enhanced due diligence",
        acronyms=("EDD",),
        synonyms=("enhanced due diligence", "enhanced customer due diligence"),
        case_sensitive_acronym=False,
        context_hint="stricter verification measures applied to high-risk customers and PEPs",
    ),
    RegulatoryConcept(
        canonical="politically exposed person",
        acronyms=("PEP", "PEPs"),
        synonyms=("politically exposed person", "politically exposed persons"),
        case_sensitive_acronym=False,
        context_hint="individuals entrusted with prominent public functions",
    ),
    RegulatoryConcept(
        canonical="suspicious transaction report",
        acronyms=("STR", "STRs"),
        synonyms=("suspicious transaction report", "suspicious transaction reporting"),
        case_sensitive_acronym=False,
        context_hint="mandatory report filed with FIU-IND on transactions suspected of crime proceeds",
    ),
    RegulatoryConcept(
        canonical="cash transaction report",
        acronyms=("CTR", "CTRs"),
        synonyms=("cash transaction report", "cash transaction reporting"),
        case_sensitive_acronym=False,
        context_hint="monthly reporting of cash transactions exceeding ten lakh rupees to FIU-IND",
    ),
    RegulatoryConcept(
        canonical="financial intelligence unit",
        acronyms=("FIU", "FIU-IND"),
        synonyms=("financial intelligence unit", "financial intelligence unit india"),
        case_sensitive_acronym=False,
        context_hint="national agency receiving and analyzing financial transaction information under PMLA",
    ),
    RegulatoryConcept(
        canonical="securities contracts regulation act",
        acronyms=("SCRA",),
        synonyms=(
            "securities contracts regulation act",
            "securities contracts (regulation) act",
        ),
        case_sensitive_acronym=False,
        context_hint="legislation governing stock exchanges and transactions in securities",
    ),
    RegulatoryConcept(
        canonical="securities contracts regulation rules",
        acronyms=("SCRR",),
        synonyms=(
            "securities contracts regulation rules",
            "securities contracts (regulation) rules",
        ),
        case_sensitive_acronym=False,
        context_hint="rules framed under SCRA prescribing listing and public shareholding norms",
    ),
    RegulatoryConcept(
        canonical="sebi complaints redress system",
        acronyms=("SCORES",),
        synonyms=("sebi complaints redress system", "scores portal", "scores platform"),
        case_sensitive_acronym=False,
        context_hint="centralized online platform for investor grievances redressal by SEBI",
    ),
    RegulatoryConcept(
        canonical="trade settlement cycle",
        acronyms=("T+1", "T+2"),
        synonyms=(
            "settlement cycle",
            "trade settlement",
            "settlement timeline",
            "rolling settlement",
        ),
        case_sensitive_acronym=False,
        context_hint="settlement of trades within one trading day from transaction execution",
    ),
    RegulatoryConcept(
        canonical="unified payments interface",
        acronyms=("UPI",),
        synonyms=("unified payments interface", "instant real-time payment"),
        case_sensitive_acronym=False,
        context_hint="NPCI real-time payment system powering mobile peer-to-peer and merchant payments",
    ),
    RegulatoryConcept(
        canonical="bharat bill payment system",
        acronyms=("BBPS",),
        synonyms=("bharat bill payment system", "interoperable bill payment"),
        case_sensitive_acronym=False,
        context_hint="interoperable platform for recurring utility bill payments under NPCI",
    ),
    RegulatoryConcept(
        canonical="central bank digital currency",
        acronyms=("CBDC", "e-Rupee", "eRupee"),
        synonyms=("central bank digital currency", "digital rupee", "sovereign digital currency"),
        case_sensitive_acronym=False,
        context_hint="digital form of currency issued by RBI as legal tender",
    ),
    RegulatoryConcept(
        canonical="merchant discount rate",
        acronyms=("MDR",),
        synonyms=("merchant discount rate", "merchant processing charge"),
        case_sensitive_acronym=False,
        context_hint="fee charged to merchant for processing debit and credit card digital transactions",
    ),
    RegulatoryConcept(
        canonical="virtual payment address",
        acronyms=("VPA",),
        synonyms=("virtual payment address", "upi id"),
        case_sensitive_acronym=False,
        context_hint="unique identifier allowing users to send and receive funds on UPI",
    ),
    RegulatoryConcept(
        canonical="business responsibility and sustainability reporting",
        acronyms=("BRSR", "ESG"),
        synonyms=(
            "business responsibility and sustainability reporting",
            "esg reporting",
            "environmental social governance",
        ),
        case_sensitive_acronym=False,
        context_hint="mandatory ESG reporting framework prescribed by SEBI for top 1000 listed entities",
    ),
    RegulatoryConcept(
        canonical="third-party application provider",
        acronyms=("TPAP", "TPAPs"),
        synonyms=(
            "third-party application provider",
            "third party application provider",
            "upi application provider",
            "upi app provider",
        ),
        case_sensitive_acronym=False,
        context_hint="entities providing UPI payment applications to end users under NPCI guidelines",
    ),
)


@dataclass(frozen=True)
class _CompiledPattern:
    concept: RegulatoryConcept
    acronym_regexes: tuple[re.Pattern[str], ...]
    synonym_regexes: tuple[re.Pattern[str], ...]


def _compile_patterns(
    concepts: tuple[RegulatoryConcept, ...],
) -> tuple[_CompiledPattern, ...]:
    compiled: list[_CompiledPattern] = []
    for c in concepts:
        flags_acr = 0 if c.case_sensitive_acronym else re.IGNORECASE
        acr_res = tuple(
            re.compile(r"\b" + re.escape(acr) + r"\b", flags=flags_acr) for acr in c.acronyms
        )
        # Match multi-word synonyms with word boundaries, case-insensitive
        syn_res = tuple(
            re.compile(r"\b" + re.escape(syn) + r"\b", flags=re.IGNORECASE) for syn in c.synonyms
        )
        compiled.append(
            _CompiledPattern(
                concept=c,
                acronym_regexes=acr_res,
                synonym_regexes=syn_res,
            )
        )
    return tuple(compiled)


_PATTERNS: tuple[_CompiledPattern, ...] = _compile_patterns(REGULATORY_CONCEPTS)


@dataclass(frozen=True)
class _CompiledAcronym:
    acronym: str
    canonical_terms: tuple[str, ...]
    pattern: re.Pattern[str]
    reverse_patterns: tuple[re.Pattern[str], ...]
    is_case_sensitive: bool


CASE_SENSITIVE_SHORT_ACRONYMS: frozenset[str] = frozenset(
    {
        "PA",
        "RE",
        "DP",
        "PG",
        "AI",
        "CI",
        "CK",
        "DC",
        "DO",
        "DX",
        "EN",
        "GC",
        "II",
        "KL",
        "KS",
        "KV",
        "MC",
        "ML",
        "QA",
        "UI",
        "XR",
        "PR",
        "RAM",
        "ROM",
        "DOM",
        "MAC",
        "NAT",
        "NIC",
        "PIN",
        "POS",
        "SPA",
        "CAN",
    }
)


def _compile_acronym_index() -> tuple[_CompiledAcronym, ...]:
    compiled: list[_CompiledAcronym] = []
    full_map: dict[str, tuple[str, ...]] = dict(ACRONYM_INDEX_296)
    for c in REGULATORY_CONCEPTS:
        for acr in c.acronyms:
            if acr not in full_map:
                full_map[acr] = (c.canonical, *c.synonyms[:2])

    for acr, canonicals in full_map.items():
        is_case_sens = (len(acr) <= 2) or (acr in CASE_SENSITIVE_SHORT_ACRONYMS)
        flags = 0 if is_case_sens else re.IGNORECASE
        acr_pat = re.compile(r"\b" + re.escape(acr) + r"\b", flags=flags)

        rev_pats = []
        for cand in canonicals:
            if cand.lower() != acr.lower():
                rev_pats.append(re.compile(r"\b" + re.escape(cand) + r"\b", flags=re.IGNORECASE))

        compiled.append(
            _CompiledAcronym(
                acronym=acr,
                canonical_terms=canonicals,
                pattern=acr_pat,
                reverse_patterns=tuple(rev_pats),
                is_case_sensitive=is_case_sens,
            )
        )
    return tuple(compiled)


_FULL_ACRONYM_MAP: dict[str, tuple[str, ...]] = dict(ACRONYM_INDEX_296)
for _c in REGULATORY_CONCEPTS:
    for _acr in _c.acronyms:
        if _acr not in _FULL_ACRONYM_MAP:
            _FULL_ACRONYM_MAP[_acr] = (_c.canonical, *_c.synonyms[:2])

_CASE_SENS_ACRS = [
    _acr
    for _acr in sorted(_FULL_ACRONYM_MAP.keys(), key=len, reverse=True)
    if len(_acr) <= 2 or _acr in CASE_SENSITIVE_SHORT_ACRONYMS
]
_CASE_INSENS_ACRS = [
    _acr
    for _acr in sorted(_FULL_ACRONYM_MAP.keys(), key=len, reverse=True)
    if not (len(_acr) <= 2 or _acr in CASE_SENSITIVE_SHORT_ACRONYMS)
]

_RE_ACR_SENS = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in _CASE_SENS_ACRS) + r")\b")
_RE_ACR_INSENS = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _CASE_INSENS_ACRS) + r")\b", re.IGNORECASE
)

_REVERSE_ACRONYM_MAP: dict[str, str] = {}
for _acr, _canonicals in _FULL_ACRONYM_MAP.items():
    for _cand in _canonicals:
        if _cand.lower() != _acr.lower():
            _REVERSE_ACRONYM_MAP[_cand.lower()] = _acr

_RE_ACR_REV = re.compile(
    r"\b(?:"
    + "|".join(re.escape(k) for k in sorted(_REVERSE_ACRONYM_MAP.keys(), key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)
_UPPER_ACRONYM_MAP: dict[str, tuple[str, ...]] = {
    k.upper(): v for k, v in _FULL_ACRONYM_MAP.items()
}


_ACRONYM_PATTERNS: tuple[_CompiledAcronym, ...] = _compile_acronym_index()


@dataclass(frozen=True)
class ExpandedQuery:
    """The outcome of query understanding and expansion."""

    original_query: str
    lexical_query: str
    dense_query: str
    matched_terms: tuple[str, ...]
    added_terms: tuple[str, ...]
    mode: ExpansionMode
    hypothetical_passage: str | None = None
    expansions_applied: list[str] = field(default_factory=list)


class DomainQueryExpander:
    """Rule-based domain query expansion and hypothetical passage synthesizer.

    Provides deterministic, sub-millisecond expansion of regulatory and systems terms for both
    lexical (BM25) and dense (vector embedding) retrieval arms without external API overhead.
    """

    def __init__(
        self,
        patterns: tuple[_CompiledPattern, ...] = _PATTERNS,
        acronym_patterns: tuple[_CompiledAcronym, ...] = _ACRONYM_PATTERNS,
        config: ExpansionConfig | None = None,
        *,
        max_added_terms: int = 8,
    ) -> None:
        self._patterns = patterns
        self._acronym_patterns = acronym_patterns
        self.config = config or ExpansionConfig()
        self._max_added_terms = max_added_terms

    def expand(
        self,
        query: str,
        mode: ExpansionMode = "synonym",
        config: ExpansionConfig | None = None,
    ) -> ExpandedQuery:
        """Expand a query for both lexical and dense retrieval."""
        cfg = config or self.config
        if not cfg.enabled or mode == "none" or not query or not query.strip():
            return ExpandedQuery(
                original_query=query,
                lexical_query=query,
                dense_query=query,
                matched_terms=(),
                added_terms=(),
                mode=mode,
                expansions_applied=[],
            )

        max_add = min(cfg.max_expansions_per_query, self._max_added_terms)
        matched_terms: list[str] = []
        added_terms: list[str] = []
        matched_concepts: list[RegulatoryConcept] = []
        seen_added: set[str] = set()

        # Tokenize query words in lowercase for quick membership check
        query_words = set(re.findall(r"\w+", query.lower()))

        # 1. First pass: regulatory concepts (for detailed synonyms and HyDE hints)
        for pat in self._patterns:
            c = pat.concept
            matched_acr = False
            matched_syn = False

            for acr_re in pat.acronym_regexes:
                m = acr_re.search(query)
                if m:
                    matched_acr = True
                    matched_terms.append(m.group(0))
                    try:
                        ACRONYMS_EXPANDED_TOTAL.labels(acronym=m.group(0)).inc()
                    except Exception:
                        logger.debug("acronym_metric_failed", exc_info=True)
                    break

            for syn_re in pat.synonym_regexes:
                m = syn_re.search(query)
                if m:
                    matched_syn = True
                    matched_terms.append(m.group(0))
                    break

            if matched_acr or matched_syn:
                matched_concepts.append(c)

                # If acronym was matched, expand with canonical full name and top synonyms
                if matched_acr:
                    candidates = [c.canonical, *c.synonyms[:2]]
                else:
                    # If full term was matched, expand with primary acronym
                    candidates = list(c.acronyms[:2])

                for candidate in candidates:
                    cand_lower = candidate.lower()
                    cand_words = set(re.findall(r"\w+", cand_lower))
                    if cand_words.issubset(query_words):
                        continue
                    if cand_lower not in seen_added:
                        seen_added.add(cand_lower)
                        added_terms.append(candidate)
                        if len(added_terms) >= max_add:
                            break

            if len(added_terms) >= max_add:
                break

        # 2. Second pass: 296-term systems & regulatory acronym catalog (master compiled regexes)
        if len(added_terms) < max_add:
            # Case-sensitive acronyms
            for m in _RE_ACR_SENS.finditer(query):
                token = m.group(0)
                matched_terms.append(token)
                try:
                    ACRONYMS_EXPANDED_TOTAL.labels(acronym=token).inc()
                except Exception:
                    logger.debug("acronym_metric_failed", exc_info=True)
                for cand in _FULL_ACRONYM_MAP.get(token, ()):
                    cand_lower = cand.lower()
                    cand_words = set(re.findall(r"\w+", cand_lower))
                    if cand_words.issubset(query_words):
                        continue
                    if cand_lower not in seen_added:
                        seen_added.add(cand_lower)
                        added_terms.append(cand)
                        if len(added_terms) >= max_add:
                            break
                if len(added_terms) >= max_add:
                    break

        if len(added_terms) < max_add:
            # Case-insensitive acronyms
            for m in _RE_ACR_INSENS.finditer(query):
                token = m.group(0)
                matched_terms.append(token)
                canonical_key = _UPPER_ACRONYM_MAP.get(token.upper())
                try:
                    ACRONYMS_EXPANDED_TOTAL.labels(acronym=token.upper()).inc()
                except Exception:
                    logger.debug("acronym_metric_failed", exc_info=True)
                if canonical_key:
                    for cand in canonical_key:
                        cand_lower = cand.lower()
                        cand_words = set(re.findall(r"\w+", cand_lower))
                        if cand_words.issubset(query_words):
                            continue
                        if cand_lower not in seen_added:
                            seen_added.add(cand_lower)
                            added_terms.append(cand)
                            if len(added_terms) >= max_add:
                                break
                if len(added_terms) >= max_add:
                    break

        if len(added_terms) < max_add:
            # Reverse match: canonical phrase -> acronym
            for m in _RE_ACR_REV.finditer(query):
                matched_phrase = m.group(0).lower()
                matched_terms.append(m.group(0))
                acr = _REVERSE_ACRONYM_MAP.get(matched_phrase)
                if acr:
                    acr_lower = acr.lower()
                    if acr_lower not in query_words and acr_lower not in seen_added:
                        seen_added.add(acr_lower)
                        added_terms.append(acr)
                        try:
                            ACRONYMS_EXPANDED_TOTAL.labels(acronym=acr).inc()
                        except Exception:
                            logger.debug("acronym_metric_failed", exc_info=True)
                        if len(added_terms) >= max_add:
                            break

        if added_terms:
            logger.debug(
                "query.expanded", query=query, expansions=added_terms, count=len(added_terms)
            )

        # Construct lexical query (original query + added domain terms for BM25 term enrichment)
        if added_terms:
            lexical_query = f"{query} {' '.join(added_terms)}"
        else:
            lexical_query = query

        # Construct dense query / hypothetical passage
        hypothetical: str | None = None
        if mode in ("hyde", "combined") and matched_concepts:
            hypothetical = self._synthesize_hyde_passage(query, matched_concepts)
            dense_query = hypothetical
        elif mode in ("synonym", "combined") and added_terms:
            dense_query = f"{query} ({', '.join(added_terms)})"
        else:
            dense_query = query

        return ExpandedQuery(
            original_query=query,
            lexical_query=lexical_query,
            dense_query=dense_query,
            matched_terms=tuple(dict.fromkeys(matched_terms)),
            added_terms=tuple(added_terms),
            mode=mode,
            hypothetical_passage=hypothetical,
            expansions_applied=list(added_terms),
        )

    def _synthesize_hyde_passage(
        self,
        query: str,
        concepts: list[RegulatoryConcept],
    ) -> str:
        """Deterministic regulatory excerpt synthesis for hypothetical document embedding."""
        context_clauses = [c.context_hint for c in concepts if c.context_hint]
        clause_str = "; ".join(context_clauses) if context_clauses else "specified regulatory norms"
        canonical_str = ", ".join(c.canonical for c in concepts)

        return (
            f"Reserve Bank of India and Securities and Exchange Board of India regulatory directions: "
            f"Regarding {query}, all regulated entities and market intermediaries pertaining to "
            f"{canonical_str} shall comply with statutory directions governing {clause_str}. "
            f"Such entities are required to fulfill specified capital requirements, operational standards, "
            f"and compliance reporting timelines."
        )


_DEFAULT_EXPANDER = DomainQueryExpander()


def get_default_expander() -> DomainQueryExpander:
    return _DEFAULT_EXPANDER
