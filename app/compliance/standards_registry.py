"""Unified Standards Registry & Authority Engine (FEAT-025 & FEAT-041).

Maintains an indexed catalog of 53+ international standards (ISO, NIST, FIPS,
IEC, RTCA, OWASP) and national regulatory frameworks (RBI Master Directions,
Basel III, SEBI Regulations).

Supports exact, alias, and fuzzy statutory reference resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StandardDefinition:
    """Specification of an international or national regulatory standard."""

    id: str
    name: str
    governing_body: str
    domain: str
    jurisdiction: str = "global"
    category: str = "technical"
    description: str | None = None
    official_reference_url: str | None = None
    note: str | None = None
    aliases: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalog of 53+ International & National Standards
# ---------------------------------------------------------------------------

_STANDARDS_CATALOG: list[StandardDefinition] = [
    StandardDefinition(
        id="DO-178C",
        name="Software Considerations in Airborne Systems and Equipment Certification",
        governing_body="RTCA/EUROCAE",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="safety-critical",
        note="MC/DC required at Level A; Table A-7 objectives.",
        aliases=["do178c", "do-178c", "ed-12c", "do 178c"],
    ),
    StandardDefinition(
        id="DO-254",
        name="Design Assurance Guidance for Airborne Electronic Hardware",
        governing_body="RTCA/EUROCAE",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="hardware-safety",
        note="Hardware counterpart to DO-178C; Level A/B elemental analysis.",
        aliases=["do254", "do-254", "ed-80"],
    ),
    StandardDefinition(
        id="DO-326A",
        name="Airworthiness Security Process Specification",
        governing_body="RTCA/EUROCAE",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="avionics-security",
        note="Aviation cyber security process; pairs with DO-356A.",
        aliases=["do326a", "do-326a", "ed-202a"],
    ),
    StandardDefinition(
        id="DO-330",
        name="Software Tool Qualification Considerations",
        governing_body="RTCA/EUROCAE",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="tool-qualification",
        note="Tool qualification levels TQL-1 to TQL-5.",
        aliases=["do330", "do-330", "ed-215"],
    ),
    StandardDefinition(
        id="DO-331",
        name="Model-Based Development and Verification Supplement to DO-178C",
        governing_body="RTCA/EUROCAE",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="formal-methods",
        aliases=["do-331", "do331", "do-332", "do-333"],
    ),
    StandardDefinition(
        id="ISO 26262",
        name="Road vehicles - Functional safety",
        governing_body="ISO",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="automotive-safety",
        note="ASIL A-D risk classification; Part 6 Table 9 for software unit testing.",
        aliases=["iso26262", "iso-26262", "iso 26262 part 6"],
    ),
    StandardDefinition(
        id="ISO 21448",
        name="Road vehicles - Safety of the intended functionality (SOTIF)",
        governing_body="ISO",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="automotive-safety",
        note="Addresses safety hazards without system hardware/software faults.",
        aliases=["iso21448", "iso-21448", "sotif"],
    ),
    StandardDefinition(
        id="ISO 22301",
        name="Security and resilience - Business continuity management systems",
        governing_body="ISO",
        domain="reliability-resilience-chaos",
        jurisdiction="global",
        category="resilience",
        note="RTO/RPO requirements, invocation thresholds, testing schedule.",
        aliases=["iso22301", "iso-22301", "bcms"],
    ),
    StandardDefinition(
        id="IEC 61508",
        name="Functional safety of electrical/electronic/programmable electronic safety-related systems",
        governing_body="IEC",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="functional-safety",
        note="SIL 1-4 classification; parent standard for automotive, rail, medical.",
        aliases=["iec61508", "iec-61508"],
    ),
    StandardDefinition(
        id="IEC 62304",
        name="Medical device software - Software life cycle processes",
        governing_body="IEC",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="medical-safety",
        note="Class A/B/C software safety classes; SOUP management.",
        aliases=["iec62304", "iec-62304"],
    ),
    StandardDefinition(
        id="EN 50128",
        name="Railway applications - Software for railway control and protection systems",
        governing_body="CENELEC",
        domain="embedded-safety-critical",
        jurisdiction="eu",
        category="railway-safety",
        note="SIL 0-4 for railway software; formal methods at SIL 3/4.",
        aliases=["en50128", "en-50128"],
    ),
    StandardDefinition(
        id="ECE R155 / R156",
        name="UN regulations on cybersecurity (CSMS) and software updates (SUMS)",
        governing_body="UNECE",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="automotive-cybersecurity",
        note="Mandatory for type approval in EU and UNECE-contracting states.",
        aliases=["ece r155", "ece r156", "un r155", "un r156"],
    ),
    StandardDefinition(
        id="ISO/IEC 25010",
        name="Systems and software Quality Requirements and Evaluation - Quality models",
        governing_body="ISO/IEC",
        domain="performance-capacity-engineering",
        jurisdiction="global",
        category="software-quality",
        note="8 product quality characteristics: functional suitability, reliability, efficiency, etc.",
        aliases=["iso 25010", "iso/iec 25010", "square"],
    ),
    StandardDefinition(
        id="ISO/IEC/IEEE 29119",
        name="Software and systems engineering - Software testing",
        governing_body="ISO/IEC/IEEE",
        domain="test-design-oracles-generative",
        jurisdiction="global",
        category="testing-standards",
        note="Parts 1-5 covering concepts, test processes, documentation, techniques.",
        aliases=["iso 29119", "iso/iec 29119"],
    ),
    StandardDefinition(
        id="ISO/IEC 27001",
        name="Information security management systems - Requirements",
        governing_body="ISO/IEC",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="infosec-management",
        note="Annex A 93 controls (2022 edition).",
        aliases=["iso 27001", "iso/iec 27001", "iso27001"],
    ),
    StandardDefinition(
        id="ISO/IEC 21031:2024",
        name="Information technology - Software Carbon Intensity (SCI) specification",
        governing_body="ISO/IEC",
        domain="sustainability",
        jurisdiction="global",
        category="green-software",
        note="SCI rate equation: SCI = (E * I + M) / R. Rate, not total.",
        aliases=["iso 21031", "iso/iec 21031", "sci specification", "gsf sci", "iso 21031:2024"],
    ),
    StandardDefinition(
        id="ISO/IEC 42001",
        name="Information technology - Artificial intelligence - Management system",
        governing_body="ISO/IEC",
        domain="ai-ml-llm-assurance",
        jurisdiction="global",
        category="ai-governance",
        note="First certifiable AI management system standard.",
        aliases=["iso 42001", "iso/iec 42001", "aims"],
    ),
    StandardDefinition(
        id="ISO/IEC 5259",
        name="Data quality for analytics and machine learning",
        governing_body="ISO/IEC",
        domain="ai-ml-llm-assurance",
        jurisdiction="global",
        category="data-quality",
        note="Series covering data quality measures and life cycle for ML training data.",
        aliases=["iso 5259", "iso/iec 5259"],
    ),
    StandardDefinition(
        id="ISO/IEC 23894",
        name="Guidance on AI risk management",
        governing_body="ISO/IEC",
        domain="ai-ml-llm-assurance",
        jurisdiction="global",
        category="ai-risk",
        note="Risk management guidance tailored to AI systems, based on ISO 31000.",
        aliases=["iso 23894", "iso/iec 23894"],
    ),
    StandardDefinition(
        id="NIST AI RMF 1.0",
        name="Artificial Intelligence Risk Management Framework",
        governing_body="NIST",
        domain="ai-ml-llm-assurance",
        jurisdiction="us",
        category="ai-risk",
        note="Govern, Map, Measure, Manage core functions.",
        aliases=["nist ai rmf", "ai rmf 1.0", "ai rmf"],
    ),
    StandardDefinition(
        id="NIST SP 800-53",
        name="Security and Privacy Controls for Information Systems and Organizations",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="federal-controls",
        note="Rev 5 catalog; basis for FedRAMP and many regulatory baselines.",
        aliases=["nist 800-53", "sp 800-53", "nist sp 800 53"],
    ),
    StandardDefinition(
        id="NIST SP 800-218",
        name="Secure Software Development Framework (SSDF)",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="secure-sdlc",
        note="PO, PS, PW, RV practice groups; required by US EO 14028.",
        aliases=["nist ssdf", "sp 800-218", "ssdf"],
    ),
    StandardDefinition(
        id="NIST SP 800-208",
        name="Recommendation for Stateful Hash-Based Signature Schemes",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="cryptography",
        note="LMS and XMSS stateful hash-based signature guidance.",
        aliases=["sp 800-208", "nist 800-208"],
    ),
    StandardDefinition(
        id="NIST SP 1270",
        name="Towards a Standard for Identifying and Managing Bias in Artificial Intelligence",
        governing_body="NIST",
        domain="ai-ml-llm-assurance",
        jurisdiction="us",
        category="ai-bias",
        note="Three categories of bias: systemic, statistical/computational, human-cognitive.",
        aliases=["nist sp 1270", "sp 1270", "nist 1270"],
    ),
    StandardDefinition(
        id="NIST CSF 2.0",
        name="Cybersecurity Framework 2.0",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="cybersecurity",
        note="Govern, Identify, Protect, Detect, Respond, Recover functions.",
        aliases=["nist csf", "csf 2.0", "nist csf 2"],
    ),
    StandardDefinition(
        id="FIPS 140-3",
        name="Security Requirements for Cryptographic Modules",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="cryptography",
        note="Levels 1-4; transitional successor to FIPS 140-2.",
        aliases=["fips 140-3", "fips 140", "fips140-3"],
    ),
    StandardDefinition(
        id="FIPS 203",
        name="ML-KEM (Module-Lattice-Based Key-Encapsulation Mechanism)",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="post-quantum",
        note="Primary post-quantum key encapsulation standard based on Kyber.",
        aliases=["fips 203", "ml-kem", "kyber"],
    ),
    StandardDefinition(
        id="FIPS 204",
        name="ML-DSA (Module-Lattice-Based Digital Signature Algorithm)",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="post-quantum",
        note="Primary post-quantum general-purpose signature based on Dilithium.",
        aliases=["fips 204", "ml-dsa", "dilithium"],
    ),
    StandardDefinition(
        id="FIPS 205",
        name="SLH-DSA (Stateless Hash-Based Digital Signature Algorithm)",
        governing_body="NIST",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="post-quantum",
        note="Post-quantum signature backup not reliant on lattice assumptions; based on SPHINCS+.",
        aliases=["fips 205", "slh-dsa", "sphincs+"],
    ),
    StandardDefinition(
        id="SLSA",
        name="Supply-chain Levels for Software Artifacts",
        governing_body="OpenSSF",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="supply-chain",
        note="Tracks provenance integrity across build and packaging pipelines.",
        aliases=["slsa", "slsa v1.0", "slsa level 3"],
    ),
    StandardDefinition(
        id="in-toto",
        name="Supply chain attestation framework",
        governing_body="CNCF",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="supply-chain",
        note="Cryptographic layout policy and link attestations across pipeline steps.",
        aliases=["in-toto", "intoto"],
    ),
    StandardDefinition(
        id="SPDX / CycloneDX",
        name="SBOM interchange formats",
        governing_body="Linux Foundation / OWASP",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="sbom",
        note="ISO/IEC 5962 (SPDX) and OWASP CycloneDX formats for software bill of materials.",
        aliases=["spdx", "cyclonedx", "sbom standard"],
    ),
    StandardDefinition(
        id="OWASP ASVS",
        name="Application Security Verification Standard",
        governing_body="OWASP",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="appsec",
        note="Levels 1-3 requirements for application security architecture, verification, code review.",
        aliases=["asvs", "owasp asvs"],
    ),
    StandardDefinition(
        id="OWASP Top 10 for LLM Applications 2025",
        name="LLM01 Prompt Injection through LLM10 Unbounded Consumption",
        governing_body="OWASP",
        domain="ai-ml-llm-assurance",
        jurisdiction="global",
        category="llm-security",
        note="LLM01 Prompt Injection through LLM10 Unbounded Consumption.",
        aliases=["owasp llm", "owasp top 10 llm", "owasp llm 2025"],
    ),
    StandardDefinition(
        id="MITRE ATT&CK",
        name="Adversarial tactics, techniques and procedures knowledge base",
        governing_body="MITRE",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="threat-intel",
        note="Enterprise matrix of adversary behaviors across attack lifecycle.",
        aliases=["mitre att&ck", "att&ck", "mitre attack"],
    ),
    StandardDefinition(
        id="MITRE ATLAS",
        name="Adversarial threat landscape for AI systems",
        governing_body="MITRE",
        domain="ai-ml-llm-assurance",
        jurisdiction="global",
        category="ai-security",
        note="TTP matrix specialized for machine learning and LLM threats.",
        aliases=["mitre atlas", "atlas"],
    ),
    StandardDefinition(
        id="CVSS",
        name="Common Vulnerability Scoring System",
        governing_body="FIRST",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="vulnerability-scoring",
        note="v3.1 and v4.0 metrics for technical severity scoring.",
        aliases=["cvss", "cvss v3.1", "cvss v4.0"],
    ),
    StandardDefinition(
        id="EPSS",
        name="Exploit Prediction Scoring System",
        governing_body="FIRST",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="vulnerability-scoring",
        note="Empirical probability of exploitation in the wild within 30 days.",
        aliases=["epss", "epss score"],
    ),
    StandardDefinition(
        id="CISA KEV",
        name="Known Exploited Vulnerabilities catalog",
        governing_body="CISA",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="vulnerability-scoring",
        note="Mandatory remediation deadlines for federal agencies under BOD 22-01.",
        aliases=["cisa kev", "kev catalog", "kev"],
    ),
    StandardDefinition(
        id="WCAG 2.2",
        name="Web Content Accessibility Guidelines 2.2",
        governing_body="W3C",
        domain="human-interface-accessibility",
        jurisdiction="global",
        category="accessibility",
        note="Levels A, AA, AAA; AA is the default regulatory target in US/EU/UK.",
        aliases=["wcag", "wcag 2.2", "wcag22", "wcag aa"],
    ),
    StandardDefinition(
        id="EN 301 549",
        name="Accessibility requirements for ICT products and services",
        governing_body="CEN/CENELEC/ETSI",
        domain="human-interface-accessibility",
        jurisdiction="eu",
        category="accessibility",
        note="European standard harmonized under European Accessibility Act.",
        aliases=["en 301 549", "en301549"],
    ),
    StandardDefinition(
        id="PCI DSS 4.0",
        name="Payment Card Industry Data Security Standard v4.0",
        governing_body="PCI SSC",
        domain="security-appsec-testing",
        jurisdiction="global",
        category="payment-security",
        note="12 principal requirements with customized approach option.",
        aliases=["pci dss", "pci dss 4.0", "pci-dss"],
    ),
    StandardDefinition(
        id="SOC 2",
        name="Trust Services Criteria attestation",
        governing_body="AICPA",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="audit-attestation",
        note="Security, Availability, Processing Integrity, Confidentiality, Privacy.",
        aliases=["soc 2", "soc2", "soc 2 type ii"],
    ),
    StandardDefinition(
        id="FedRAMP",
        name="Federal Risk and Authorization Management Program",
        governing_body="GSA",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="cloud-authorization",
        note="Low, Moderate, High baselines mapped to NIST SP 800-53.",
        aliases=["fedramp", "fedramp moderate", "fedramp high"],
    ),
    StandardDefinition(
        id="GDPR",
        name="General Data Protection Regulation",
        governing_body="European Union",
        domain="regulatory-compliance-privacy",
        jurisdiction="eu",
        category="privacy",
        note="Regulation (EU) 2016/679.",
        aliases=["gdpr", "eu gdpr"],
    ),
    StandardDefinition(
        id="Regulation (EU) 2024/2847 (CRA)",
        name="Cyber Resilience Act",
        governing_body="European Union",
        domain="security-appsec-testing",
        jurisdiction="eu",
        category="product-cybersecurity",
        note="Mandatory cybersecurity requirements for hardware and software products.",
        aliases=["cra", "cyber resilience act", "eu cra"],
    ),
    StandardDefinition(
        id="Regulation (EU) 2024/1689 (AI Act)",
        name="EU Artificial Intelligence Act",
        governing_body="European Union",
        domain="ai-ml-llm-assurance",
        jurisdiction="eu",
        category="ai-governance",
        note="Risk-tiered obligations: prohibited, high-risk, GPAI with systemic risk.",
        aliases=["eu ai act", "ai act", "eu 2024/1689"],
    ),
    StandardDefinition(
        id="Regulation (EU) 2022/2554 (DORA)",
        name="Digital Operational Resilience Act",
        governing_body="European Union",
        domain="reliability-resilience-chaos",
        jurisdiction="eu",
        category="financial-resilience",
        note="Mandates ICT risk management, incident reporting, TLPT testing for financial entities.",
        aliases=["dora", "eu dora", "digital operational resilience act"],
    ),
    StandardDefinition(
        id="NIS2",
        name="Directive on measures for a high common level of cybersecurity",
        governing_body="European Union",
        domain="security-appsec-testing",
        jurisdiction="eu",
        category="critical-infrastructure",
        note="Directive (EU) 2022/2555; essential and important entities scope.",
        aliases=["nis2", "nis 2", "directive 2022/2555"],
    ),
    StandardDefinition(
        id="SR 11-7",
        name="Guidance on Model Risk Management",
        governing_body="Federal Reserve / OCC",
        domain="ai-ml-llm-assurance",
        jurisdiction="us",
        category="banking-model-risk",
        note="Three elements: development/implementation, objective review, outcomes analysis.",
        aliases=["sr 11-7", "sr11-7", "occ 2011-12"],
    ),
    StandardDefinition(
        id="CMMC",
        name="Cybersecurity Maturity Model Certification",
        governing_body="DoD",
        domain="security-appsec-testing",
        jurisdiction="us",
        category="defense-supply-chain",
        note="Levels 1-3 aligned with FAR and NIST SP 800-171.",
        aliases=["cmmc", "cmmc 2.0"],
    ),
    StandardDefinition(
        id="MISRA C/C++",
        name="Guidelines for the use of the C/C++ language in critical systems",
        governing_body="MISRA",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="code-safety",
        note="Mandatory, required, advisory rules; standard static analysis target.",
        aliases=["misra", "misra c", "misra c++"],
    ),
    StandardDefinition(
        id="AUTOSAR",
        name="Automotive Open System Architecture",
        governing_body="AUTOSAR",
        domain="embedded-safety-critical",
        jurisdiction="global",
        category="automotive-architecture",
        note="Classic (hard real-time OSEK) and Adaptive (POSIX/C++14 SOA) platforms.",
        aliases=["autosar", "autosar classic", "autosar adaptive"],
    ),
    # -----------------------------------------------------------------------
    # Core Banking, RBI Master Directions & Basel Frameworks
    # -----------------------------------------------------------------------
    StandardDefinition(
        id="BASEL_III",
        name="Basel III International Regulatory Framework for Banks",
        governing_body="BCBS",
        domain="banking-prudential-capital",
        jurisdiction="global",
        category="banking-solvency",
        description="Global regulatory standard on bank capital adequacy, stress testing, and market liquidity risk.",
        official_reference_url="https://www.bis.org/bcbs/basel3.htm",
        note="Pillar 1 minimum capital (CRAR, Tier 1, Common Equity Tier 1), Pillar 2 supervisory review, Pillar 3 market discipline.",
        aliases=["basel 3", "basel iii", "bcbs basel iii", "basel accord"],
    ),
    StandardDefinition(
        id="RBI_BASEL_III_CAPITAL",
        name="RBI Master Direction - Basel III Capital Regulations",
        governing_body="RBI",
        domain="banking-prudential-capital",
        jurisdiction="india",
        category="banking-solvency",
        description="Reserve Bank of India Master Direction governing regulatory capital requirements, risk weights, and solvency ratios for Scheduled Commercial Banks and NBFCs.",
        official_reference_url="https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=10000",
        note="Requires min 9% CRAR for commercial banks, 15% for NBFC-SI, 7% Tier 1 capital, and 2.5% Capital Conservation Buffer.",
        aliases=[
            "rbi master direction - basel iii capital regulations",
            "rbi basel iii capital",
            "rbi basel 3",
            "rbi capital regulations",
            "dbod.no.bp.bc.9/21.04.048/2014-15",
        ],
    ),
    StandardDefinition(
        id="RBI_LIQUIDITY_RISK",
        name="RBI Liquidity Risk Management Framework - LCR and NSFR",
        governing_body="RBI",
        domain="banking-liquidity-risk",
        jurisdiction="india",
        category="liquidity-risk",
        description="RBI guidelines on Liquidity Coverage Ratio (LCR), Net Stable Funding Ratio (NSFR), and monitoring tools.",
        official_reference_url="https://www.rbi.org.in/",
        note="Mandatory minimum 100% LCR and 100% NSFR to withstand acute 30-day liquidity stress.",
        aliases=[
            "rbi liquidity risk management framework",
            "rbi lcr",
            "rbi nsfr",
            "rbi liquidity framework",
        ],
    ),
    StandardDefinition(
        id="RBI_PCA_FRAMEWORK",
        name="RBI Prompt Corrective Action (PCA) Framework",
        governing_body="RBI",
        domain="banking-prudential-capital",
        jurisdiction="india",
        category="regulatory-supervision",
        description="Early intervention matrix triggered by breaches in CRAR, Net NPA, or Leverage Ratio.",
        note="Risk Thresholds 1, 2, and 3 impose mandatory restrictions on dividend distribution, branch expansion, and capital expenditure.",
        aliases=["rbi pca", "prompt corrective action", "pca framework", "rbi pca framework"],
    ),
    StandardDefinition(
        id="RBI_PSL_FRAMEWORK",
        name="RBI Master Directions - Priority Sector Lending (PSL)",
        governing_body="RBI",
        domain="banking-priority-sector",
        jurisdiction="india",
        category="statutory-lending",
        description="Mandatory 40% ANBC credit target to priority sectors (Agriculture, SMF, Micro Enterprises, Weaker Sections).",
        aliases=["rbi psl", "priority sector lending", "psl master directions"],
    ),
    StandardDefinition(
        id="SRE_RELIABILITY_FRAMEWORK",
        name="Site Reliability Engineering (SRE) Service Level & Error Budget Standard",
        governing_body="Industry SRE / USENIX",
        domain="reliability-resilience-chaos",
        jurisdiction="global",
        category="site-reliability",
        description="Operational standard governing SLOs, Error Budgets, Multi-Window Burn Rates, and Toil Budgets.",
        note="Burn rate > 14.4 (1h window) triggers immediate paging alerts; toil capped at 50% of engineering time.",
        aliases=["sre", "sre error budget", "google sre", "error budget framework"],
    ),
]


class StandardsRegistry:
    """Thread-safe, high-speed lookup registry for governance and technical standards."""

    def __init__(self, standards: list[StandardDefinition] | None = None) -> None:
        self._standards_list = list(standards or _STANDARDS_CATALOG)
        self._by_id: dict[str, StandardDefinition] = {}
        self._by_alias: dict[str, StandardDefinition] = {}
        self._by_domain: dict[str, list[StandardDefinition]] = {}
        self._by_body: dict[str, list[StandardDefinition]] = {}

        self._build_indexes()

    def _build_indexes(self) -> None:
        for std in self._standards_list:
            self._by_id[std.id] = std
            # Normalize ID for fast case-insensitive lookup
            norm_id = self._normalize_key(std.id)
            self._by_alias[norm_id] = std

            # Index aliases
            for a in std.aliases:
                norm_a = self._normalize_key(a)
                self._by_alias[norm_a] = std

            # Index by domain
            self._by_domain.setdefault(std.domain.lower(), []).append(std)

            # Index by governing body
            self._by_body.setdefault(std.governing_body.lower(), []).append(std)

    @staticmethod
    def _normalize_key(k: str) -> str:
        """Strip punctuation and whitespace for resilient alias lookup."""
        return re.sub(r"[\s\-_/:\.]+", "", k).lower()

    def get_standard(self, standard_id: str) -> StandardDefinition | None:
        """Lookup standard by exact ID or normalized alias."""
        if not standard_id:
            return None
        # Exact ID match
        if standard_id in self._by_id:
            return self._by_id[standard_id]

        # Normalized lookup
        norm = self._normalize_key(standard_id)
        return self._by_alias.get(norm)

    def resolve_standard(self, text_or_ref: str) -> StandardDefinition | None:
        """Resolve a fuzzy text mention or standard reference string to a registered standard."""
        if not text_or_ref or not text_or_ref.strip():
            return None

        # 1. Direct lookup
        direct = self.get_standard(text_or_ref.strip())
        if direct is not None:
            return direct

        # 2. Substring matching against known aliases & IDs
        norm_ref = self._normalize_key(text_or_ref)
        for alias, std in self._by_alias.items():
            if len(alias) >= 4 and (alias in norm_ref or norm_ref in alias):
                return std

        # 3. Known domain mappings
        lower_raw = text_or_ref.lower()
        if "basel" in lower_raw or "crar" in lower_raw or "tier 1" in lower_raw:
            return self.get_standard("RBI_BASEL_III_CAPITAL") or self.get_standard("BASEL_III")
        if "lcr" in lower_raw or "liquidity coverage" in lower_raw or "nsfr" in lower_raw:
            return self.get_standard("RBI_LIQUIDITY_RISK")
        if "sci" in lower_raw or "carbon intensity" in lower_raw or "21031" in lower_raw:
            return self.get_standard("ISO/IEC 21031:2024")
        if "mc/dc" in lower_raw or "mcdc" in lower_raw or "do-178" in lower_raw:
            return self.get_standard("DO-178C")
        if "burn rate" in lower_raw or "error budget" in lower_raw or "slo" in lower_raw:
            return self.get_standard("SRE_RELIABILITY_FRAMEWORK")

        return None

    def list_standards(
        self,
        domain: str | None = None,
        governing_body: str | None = None,
    ) -> list[StandardDefinition]:
        """Filter and return list of registered standards."""
        results = self._standards_list

        if domain:
            dom_key = domain.strip().lower()
            results = [s for s in results if s.domain.lower() == dom_key]

        if governing_body:
            gb_key = governing_body.strip().lower()
            results = [s for s in results if s.governing_body.lower() == gb_key]

        return results

    def search_standards(self, query: str) -> list[StandardDefinition]:
        """Search standards by query in id, name, domain, or governing body."""
        if not query or not query.strip():
            return list(self._standards_list)

        q = query.strip().lower()
        matches: list[StandardDefinition] = []
        for std in self._standards_list:
            if (
                q in std.id.lower()
                or q in std.name.lower()
                or q in std.governing_body.lower()
                or q in std.domain.lower()
                or (std.category and q in std.category.lower())
                or (std.note and q in std.note.lower())
                or (std.description and q in std.description.lower())
                or any(q in a.lower() for a in std.aliases)
            ):
                matches.append(std)
        return matches

    def count(self) -> int:
        """Return total registered standards count."""
        return len(self._standards_list)


_DEFAULT_STANDARDS_REGISTRY: StandardsRegistry | None = None


def get_default_standards_registry() -> StandardsRegistry:
    """Singleton getter for default standards registry."""
    global _DEFAULT_STANDARDS_REGISTRY
    if _DEFAULT_STANDARDS_REGISTRY is None:
        _DEFAULT_STANDARDS_REGISTRY = StandardsRegistry()
    return _DEFAULT_STANDARDS_REGISTRY
