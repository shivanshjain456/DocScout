"""Statutory Deprecation and Supersession Engine (FEAT-031).

Tracks superseded circulars, repealed guidelines, and deprecated engineering/compliance
practices using the deprecations schema (outdated, status, reason, replacement, guidance).
Resolves recursive supersession chains, monitors sunset deadlines, and checks grandfathering provisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger("docscout.compliance.deprecation_engine")


class DeprecationStatus(StrEnum):
    """Statutory status of circular or practice."""

    REPEALED = "repealed"
    SUPERSEDED = "superseded"
    MAINTENANCE_MODE = "maintenance_mode"
    INFORMALLY_DEPRECATED = "informally_deprecated"
    ANTI_PATTERN = "anti_pattern"
    AMENDED_OUTDATED = "amended_outdated"
    SUNSET_EXPIRED = "sunset_expired"


class SubjectType(StrEnum):
    """Classification of the deprecated subject."""

    CIRCULAR = "circular"
    TECHNICAL_PRACTICE = "technical_practice"
    METRIC = "metric"
    COMPLIANCE_STANDARD = "compliance_standard"


class RegulatorCode(StrEnum):
    """Regulatory or standard-setting body."""

    RBI = "RBI"
    SEBI = "SEBI"
    PMLA = "PMLA"
    DORA = "DORA"
    BASEL = "BASEL"
    INDUSTRY_STANDARD = "INDUSTRY_STANDARD"
    GLOBAL = "GLOBAL"


class DeprecationSeverity(StrEnum):
    """Audit severity for non-compliance with deprecation."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class StatutoryDeprecation:
    """Canonical representation of a deprecated circular or practice."""

    id: str
    subject: str
    subject_type: SubjectType
    regulator: RegulatorCode
    status: DeprecationStatus
    reason: str
    effective_date: str  # YYYY-MM-DD
    guidance: str
    replacement: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    sunset_date: str | None = None
    grandfathering_clause: str | None = None
    severity: DeprecationSeverity = DeprecationSeverity.HIGH
    citation_patterns: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def is_sunset_passed(self, as_of: str | date | None = None) -> bool:
        """Return True if sunset deadline has passed as of the specified date."""
        if not self.sunset_date:
            return False
        check_date = (
            date.fromisoformat(as_of) if isinstance(as_of, str) else (as_of or date.today())
        )
        return check_date > date.fromisoformat(self.sunset_date)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "subject": self.subject,
            "subject_type": self.subject_type.value,
            "regulator": self.regulator.value,
            "status": self.status.value,
            "reason": self.reason,
            "superseded_by": self.superseded_by,
            "effective_date": self.effective_date,
            "sunset_date": self.sunset_date,
            "grandfathering_clause": self.grandfathering_clause,
            "replacement": self.replacement,
            "guidance": self.guidance,
            "severity": self.severity.value,
            "citation_patterns": self.citation_patterns,
            "aliases": self.aliases,
            "is_sunset_passed": self.is_sunset_passed(),
        }


@dataclass
class SupersessionNode:
    """Single link in an evolutionary supersession chain."""

    instrument_id: str
    title: str
    regulator: str
    status: str
    effective_date: str
    is_currently_active: bool


@dataclass
class SupersessionChain:
    """Full path from historical circular to currently active master direction."""

    root_instrument: str
    active_authority: str
    depth: int
    chain: list[SupersessionNode]
    has_cycle: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_instrument": self.root_instrument,
            "active_authority": self.active_authority,
            "depth": self.depth,
            "has_cycle": self.has_cycle,
            "chain": [
                {
                    "instrument_id": node.instrument_id,
                    "title": node.title,
                    "regulator": node.regulator,
                    "status": node.status,
                    "effective_date": node.effective_date,
                    "is_currently_active": node.is_currently_active,
                }
                for node in self.chain
            ],
        }


@dataclass
class DeprecationDetection:
    """Individual match when scanning regulatory text or policy document."""

    deprecation_id: str
    matched_text: str
    subject: str
    subject_type: str
    regulator: str
    status: str
    severity: str
    reason: str
    replacement: list[str]
    guidance: str
    effective_date: str
    superseded_by: str | None = None
    active_authority: str | None = None
    supersession_chain: list[str] = field(default_factory=list)
    sunset_date: str | None = None
    is_sunset_passed: bool = False
    grandfathering_clause: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deprecation_id": self.deprecation_id,
            "matched_text": self.matched_text,
            "subject": self.subject,
            "subject_type": self.subject_type,
            "regulator": self.regulator,
            "status": self.status,
            "severity": self.severity,
            "superseded_by": self.superseded_by,
            "active_authority": self.active_authority,
            "supersession_chain": self.supersession_chain,
            "reason": self.reason,
            "replacement": self.replacement,
            "guidance": self.guidance,
            "effective_date": self.effective_date,
            "sunset_date": self.sunset_date,
            "is_sunset_passed": self.is_sunset_passed,
            "grandfathering_clause": self.grandfathering_clause,
        }


class StatutoryDeprecationEngine:
    """Core engine managing statutory deprecations and circular supersession chains."""

    def __init__(self) -> None:
        self._deprecations: dict[str, StatutoryDeprecation] = {}
        self._subject_index: dict[str, str] = {}  # lowercase subject/alias -> id
        self._regex_matchers: list[tuple[re.Pattern[str], str]] = []
        self._predecessor_to_successor: dict[str, str] = {}
        self._instrument_metadata: dict[str, dict[str, Any]] = {}
        self._load_canonical_deprecations()

    def register_deprecation(self, item: StatutoryDeprecation) -> None:
        """Register a deprecation and index its subjects, aliases, and citation patterns."""
        self._deprecations[item.id] = item
        self._subject_index[item.subject.lower()] = item.id

        for alias in item.aliases:
            self._subject_index[alias.lower()] = item.id

        if item.superseded_by:
            self._predecessor_to_successor[item.id] = item.superseded_by
            self._predecessor_to_successor[item.subject] = item.superseded_by

        # Compile citation patterns if present
        for pat in item.citation_patterns:
            try:
                rx = re.compile(pat, re.IGNORECASE)
                self._regex_matchers.append((rx, item.id))
            except re.error as err:
                logger.warning("invalid_citation_pattern", pattern=pat, error=str(err))

    def _register_instrument_meta(
        self,
        instrument_id: str,
        title: str,
        regulator: str,
        status: str,
        effective_date: str,
        is_currently_active: bool,
    ) -> None:
        """Register auxiliary metadata for circulars appearing in supersession chains."""
        self._instrument_metadata[instrument_id] = {
            "title": title,
            "regulator": regulator,
            "status": status,
            "effective_date": effective_date,
            "is_currently_active": is_currently_active,
        }

    def _load_canonical_deprecations(self) -> None:
        """Initialize built-in regulatory and technical deprecation catalogs."""
        # 1. RBI KYC Evolutionary Chain
        self.register_deprecation(
            StatutoryDeprecation(
                id="rbi-kyc-circular-2002",
                subject="RBI/2002-03/DBOD.AML.BC.18/14.01.001/2002-03",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.RBI,
                status=DeprecationStatus.SUPERSEDED,
                reason="Legacy KYC guidelines replaced by Master Circular and subsequently codified Master Directions.",
                effective_date="2002-08-16",
                superseded_by="rbi-kyc-master-circular-2013",
                sunset_date="2013-07-01",
                grandfathering_clause="Pre-existing low-risk accounts permitted transitional identification update window.",
                replacement=[
                    "RBI Master Direction - Know Your Customer (KYC) Direction, 2016 (Updated 2024)"
                ],
                guidance="Adopt RBI Master Direction KYC 2016 provisions including Video-based Customer Identification Process (V-CIP) and Central KYC Records Registry (CKYCR) seeding.",
                severity=DeprecationSeverity.CRITICAL,
                citation_patterns=[
                    r"DBOD\.AML\.BC\.18\/14\.01\.001\/2002-03",
                    r"RBI\s+KYC\s+Guidelines\s+2002",
                ],
                aliases=["RBI KYC 2002", "DBOD.AML.BC.18/14.01.001/2002-03"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="rbi-kyc-master-circular-2013",
                subject="RBI/2013-14/94 DBOD.AML.BC.No.11/14.01.001/2013-14",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.RBI,
                status=DeprecationStatus.SUPERSEDED,
                reason="Master Circular on KYC replaced by standalone Master Direction pursuant to Banking Regulation Act Section 35A.",
                effective_date="2013-07-01",
                superseded_by="rbi-kyc-master-direction-2016",
                sunset_date="2016-02-25",
                grandfathering_clause=None,
                replacement=["RBI/DBR/2015-16/18 Master Direction - KYC Direction, 2016"],
                guidance="Rely exclusively on RBI Master Direction - KYC Direction 2016 as continually amended.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"DBOD\.AML\.BC\.No\.11\/14\.01\.001\/2013-14",
                    r"RBI\/2013-14\/94",
                ],
                aliases=["RBI KYC Master Circular 2013", "DBOD.AML.BC.No.11/14.01.001/2013-14"],
            )
        )
        self._register_instrument_meta(
            instrument_id="rbi-kyc-master-direction-2016",
            title="RBI Master Direction - Know Your Customer (KYC) Direction, 2016 (Updated 2024)",
            regulator="RBI",
            status="active",
            effective_date="2016-02-25",
            is_currently_active=True,
        )

        # 2. RBI Fair Practices Code -> Digital Lending Guidelines
        self.register_deprecation(
            StatutoryDeprecation(
                id="rbi-fair-practices-2003",
                subject="RBI/2002-03/DBOD.Leg.BC.104/09.07.007/2002-03",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.RBI,
                status=DeprecationStatus.SUPERSEDED,
                reason="Original Fair Practices Code superseded by consolidated Master Directions and Digital Lending regulatory framework.",
                effective_date="2003-05-05",
                superseded_by="rbi-digital-lending-2022",
                sunset_date="2022-11-30",
                grandfathering_clause="Existing bilateral loans granted before Nov 2022 protected until tenor maturity.",
                replacement=[
                    "RBI Guidelines on Digital Lending (DOR.CRE.REC.66/21.07.001/2022-23)"
                ],
                guidance="Execute loan disbursals directly to borrower bank accounts without pass-through pool accounts of Lending Service Providers (LSPs). Ensure Key Fact Statement (KFS) delivery with Annual Percentage Rate (APR).",
                severity=DeprecationSeverity.CRITICAL,
                citation_patterns=[
                    r"DBOD\.Leg\.BC\.104\/09\.07\.007\/2002-03",
                    r"Fair\s+Practices\s+Code\s+for\s+Lenders\s+2003",
                ],
                aliases=["Fair Practices Code 2003", "DBOD.Leg.BC.104/09.07.007/2002-03"],
            )
        )
        self._register_instrument_meta(
            instrument_id="rbi-digital-lending-2022",
            title="RBI Guidelines on Digital Lending (DOR.CRE.REC.66/21.07.001/2022-23)",
            regulator="RBI",
            status="active",
            effective_date="2022-09-02",
            is_currently_active=True,
        )

        # 3. Card-on-File Storage -> CoFT
        self.register_deprecation(
            StatutoryDeprecation(
                id="rbi-card-storage-legacy",
                subject="RBI Card-on-File Plaintext Storage Mandate",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.RBI,
                status=DeprecationStatus.SUNSET_EXPIRED,
                reason="Prohibition on merchant or payment aggregator storage of actual card data (Card Number/PAN, Expiry Date) following Tokenization mandate.",
                effective_date="2021-09-07",
                superseded_by="rbi-coft-framework-2021",
                sunset_date="2022-09-30",
                grandfathering_clause="Zero grandfathering. All merchants and non-card network entities required to purge stored PAN data.",
                replacement=[
                    "Card-on-File Tokenization (CoFT) via Authorized Card Networks",
                    "Alternative Guest Checkout",
                ],
                guidance="Purge all card PANs from internal databases. Adopt Network Tokenization with cryptographic cryptograms for recurring and 1-click checkouts.",
                severity=DeprecationSeverity.CRITICAL,
                citation_patterns=[
                    r"CO\.DPSS\.Auth\s+Tokenisation",
                    r"Card-on-File\s+plain\s+text\s+storage",
                    r"DPSS\.CO\.PD\s+No\.447\/02\.14\.003\/2021-22",
                ],
                aliases=[
                    "Plaintext Card-on-File",
                    "DPSS.CO.PD.No.447/02.14.003/2021-22",
                    "Card data storage on merchant server",
                ],
            )
        )
        self._register_instrument_meta(
            instrument_id="rbi-coft-framework-2021",
            title="RBI Master Framework for Card-on-File Tokenization (CoFT)",
            regulator="RBI",
            status="active",
            effective_date="2021-09-07",
            is_currently_active=True,
        )

        # 4. RBI Outsourcing of Financial Services 2006 -> Master Direction 2023
        self.register_deprecation(
            StatutoryDeprecation(
                id="rbi-outsourcing-2006",
                subject="RBI/2006-07/DBOD.No.BP.40/21.04.158/2006-07",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.RBI,
                status=DeprecationStatus.SUPERSEDED,
                reason="Replaced by comprehensive RBI Master Direction on Outsourcing of Information Technology Services 2023.",
                effective_date="2006-11-03",
                superseded_by="rbi-it-outsourcing-md-2023",
                sunset_date="2023-10-01",
                grandfathering_clause="Existing vendor contracts allowed to run until renewal or Oct 2023, whichever is earlier.",
                replacement=[
                    "RBI Master Direction on Outsourcing of IT Services (RBI/2023-24/102)"
                ],
                guidance="Mandate right-to-audit clauses, zero-concentration offshore restrictions, and comprehensive business continuity failover drills for Material IT services.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"DBOD\.No\.BP\.40\/21\.04\.158\/2006-07",
                    r"Outsourcing\s+of\s+Financial\s+Services\s+2006",
                ],
                aliases=["RBI Outsourcing Guidelines 2006", "DBOD.No.BP.40/21.04.158/2006-07"],
            )
        )
        self._register_instrument_meta(
            instrument_id="rbi-it-outsourcing-md-2023",
            title="RBI Master Direction on Outsourcing of IT Services (RBI/2023-24/102 DoS.CO.CSITE.SEC.No.1852/33-01-003/2023-24)",
            regulator="RBI",
            status="active",
            effective_date="2023-04-10",
            is_currently_active=True,
        )

        # 5. RBI Cyber Security Framework 2016 -> IT Governance Master Direction 2023
        self.register_deprecation(
            StatutoryDeprecation(
                id="rbi-cyber-framework-2016",
                subject="RBI/2015-16/418 DBS.CO/CSITE/BC.11/33.01.001/2015-16",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.RBI,
                status=DeprecationStatus.SUPERSEDED,
                reason="Subsumed into the consolidated RBI Master Direction on IT Governance, Risk, Controls and Assurance Practices 2023.",
                effective_date="2016-06-02",
                superseded_by="rbi-it-governance-md-2023",
                sunset_date="2024-04-01",
                grandfathering_clause=None,
                replacement=["RBI Master Direction on IT Governance and Risk (RBI/2023-24/107)"],
                guidance="Establish Board-level IT Strategy Committee, Chief Information Security Officer (CISO) direct reporting line, and continuous SOC operations with 2-hour RBI CERT-In incident reporting.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"DBS\.CO\/CSITE\/BC\.11\/33\.01\.001\/2015-16",
                    r"RBI\/2015-16\/418",
                    r"Cyber\s+Security\s+Framework\s+in\s+Banks\s+2016",
                ],
                aliases=[
                    "RBI Cyber Security Framework 2016",
                    "DBS.CO/CSITE/BC.11/33.01.001/2015-16",
                ],
            )
        )
        self._register_instrument_meta(
            instrument_id="rbi-it-governance-md-2023",
            title="RBI Master Direction on IT Governance, Risk, Controls and Assurance Practices, 2023 (RBI/2023-24/107)",
            regulator="RBI",
            status="active",
            effective_date="2023-11-07",
            is_currently_active=True,
        )

        # 6. SEBI Clause 49 -> LODR 2015
        self.register_deprecation(
            StatutoryDeprecation(
                id="sebi-clause-49",
                subject="SEBI Clause 49 of Equity Listing Agreement",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.SEBI,
                status=DeprecationStatus.REPEALED,
                reason="Repealed upon notification of statutory SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015.",
                effective_date="2015-12-01",
                superseded_by="sebi-lodr-regulations-2015",
                sunset_date="2015-12-01",
                grandfathering_clause="Disclosures made under prior fiscal periods remain legally valid.",
                replacement=[
                    "SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015 (LODR)"
                ],
                guidance="Map all corporate governance, Board independence, and Audit Committee charters to SEBI LODR Regulation 17 to 27.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"Clause\s+49\s+of\s+(?:the\s+)?Listing\s+Agreement",
                    r"Clause\s+49\s+corporate\s+governance",
                ],
                aliases=["Clause 49", "Equity Listing Agreement Clause 49"],
            )
        )
        self._register_instrument_meta(
            instrument_id="sebi-lodr-regulations-2015",
            title="SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015 (LODR)",
            regulator="SEBI",
            status="active",
            effective_date="2015-09-02",
            is_currently_active=True,
        )

        # 7. SEBI Cybersecurity Framework 2015 -> CSCRF 2024
        self.register_deprecation(
            StatutoryDeprecation(
                id="sebi-cyber-framework-2015",
                subject="SEBI/CIR/MIRSD/1/2015 Cybersecurity Framework",
                subject_type=SubjectType.CIRCULAR,
                regulator=RegulatorCode.SEBI,
                status=DeprecationStatus.SUPERSEDED,
                reason="Superceded by SEBI Consolidated Cybersecurity and Cyber Resilience Framework (CSCRF) 2024.",
                effective_date="2015-07-06",
                superseded_by="sebi-cscrf-2024",
                sunset_date="2025-01-01",
                grandfathering_clause="Qualified entities given graded timeline to complete CSCRF Tier audit.",
                replacement=[
                    "SEBI Cybersecurity and Cyber Resilience Framework (CSCRF) 2024 (SEBI/HO/ITD-1/ITD_APC/P/CIR/2024/98)"
                ],
                guidance="Implement ISO 27001, continuous red-teaming, API security controls, and mandatory 6-hour SEBI cyber incident notification window.",
                severity=DeprecationSeverity.CRITICAL,
                citation_patterns=[
                    r"CIR\/MIRSD\/1\/2015",
                    r"SEBI\s+Cybersecurity\s+Framework\s+2015",
                ],
                aliases=["CIR/MIRSD/1/2015", "SEBI 2015 Cyber Circular"],
            )
        )
        self._register_instrument_meta(
            instrument_id="sebi-cscrf-2024",
            title="SEBI Consolidated Cybersecurity and Cyber Resilience Framework (CSCRF) 2024",
            regulator="SEBI",
            status="active",
            effective_date="2024-06-27",
            is_currently_active=True,
        )

        # 8. PMLA 25% Beneficial Ownership Threshold -> 10% Amendment 2023
        self.register_deprecation(
            StatutoryDeprecation(
                id="pmla-bo-threshold-25pct",
                subject="PMLA Rule 9(3)(a) 25% Beneficial Ownership Threshold",
                subject_type=SubjectType.COMPLIANCE_STANDARD,
                regulator=RegulatorCode.PMLA,
                status=DeprecationStatus.AMENDED_OUTDATED,
                reason="Prevention of Money-laundering (Maintenance of Records) Amendment Rules 2023 lowered controlling ownership threshold from 25% to 10%.",
                effective_date="2023-03-07",
                superseded_by="pmla-amendment-rules-2023",
                sunset_date="2023-05-01",
                grandfathering_clause="Existing client accounts required to be re-screened at 10% threshold during periodic review.",
                replacement=[
                    "PMLA Beneficial Ownership 10% Threshold (Rule 9(3))",
                    "FATF Recommendation 24 Compliance",
                ],
                guidance="Identify natural persons holding controlling ownership interest equal to or exceeding 10% in corporate clients (previously 25%).",
                severity=DeprecationSeverity.CRITICAL,
                citation_patterns=[
                    r"25%\s+(?:or\s+more\s+)?beneficial\s+ownership\s+threshold",
                    r"PMLA\s+25%\s+controlling\s+ownership",
                ],
                aliases=["25% beneficial ownership threshold", "PMLA Rule 9(3) 25%"],
            )
        )
        self._register_instrument_meta(
            instrument_id="pmla-amendment-rules-2023",
            title="Prevention of Money-laundering (Maintenance of Records) Amendment Rules, 2023 (G.S.R. 178(E))",
            regulator="PMLA",
            status="active",
            effective_date="2023-03-07",
            is_currently_active=True,
        )

        # 9. Basel II Standardized Credit Risk -> Basel III Final Reforms
        self.register_deprecation(
            StatutoryDeprecation(
                id="basel2-standardized-credit",
                subject="Basel II Standardized Approach for Credit Risk",
                subject_type=SubjectType.COMPLIANCE_STANDARD,
                regulator=RegulatorCode.BASEL,
                status=DeprecationStatus.SUPERSEDED,
                reason="Replaced by Basel III Final Reforms revised standardized approach with output floor and granular loan-to-value risk weights.",
                effective_date="2023-01-01",
                superseded_by="basel3-final-reforms-cre20",
                sunset_date="2028-01-01",
                grandfathering_clause="Output floor phased in progressively from 50% in 2023 to 72.5% by 2028.",
                replacement=[
                    "Basel III Final Reforms CRE20 Standardised Approach",
                    "Output Floor Framework",
                ],
                guidance="Apply loan-to-value (LTV) sensitive risk weights for real estate exposures and eliminate internal ratings based approach for equity exposures.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"Basel\s+II\s+Standardised\s+Approach\s+for\s+Credit\s+Risk",
                    r"BCBS\s+128\s+Credit\s+Risk",
                ],
                aliases=["Basel II Credit Risk", "BCBS 128"],
            )
        )
        self._register_instrument_meta(
            instrument_id="basel3-final-reforms-cre20",
            title="Basel III Final Reforms - CRE20: Standardised Approach for Credit Risk",
            regulator="BASEL",
            status="active",
            effective_date="2023-01-01",
            is_currently_active=True,
        )

        # 10. Taxonomy Built-in Technical Deprecations (from term-taxonomy.json)
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-dread",
                subject="DREAD",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.INFORMALLY_DEPRECATED,
                reason="Scores are subjective, dimensions overlap, inter-reviewer variance is high, and it produces no enumeration behind the numbers.",
                effective_date="2020-01-01",
                superseded_by=None,
                replacement=[
                    "Threat Modeling (STRIDE)",
                    "Attack Tree Analysis",
                    "CVSS (Common Vulnerability Scoring System)",
                ],
                guidance="Use STRIDE for enumeration, attack trees for multi-step realism, CVSS for known-CVE scoring and FAIR for dollar-denominated risk.",
                severity=DeprecationSeverity.MEDIUM,
                citation_patterns=[r"\bDREAD\b(?:\s+threat\s+model)?", r"\bDREAD\s+scoring\b"],
                aliases=["DREAD methodology", "DREAD Threat Modeling"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-hystrix",
                subject="Hystrix",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.MAINTENANCE_MODE,
                reason="Netflix stopped active development; the library is maintained in archive but not recommended for new projects.",
                effective_date="2018-11-01",
                superseded_by=None,
                replacement=[
                    "Bulkhead Isolation Verification",
                    "Backpressure Verification",
                    "Resilience4j",
                ],
                guidance="Use Resilience4j (JVM) or Polly (.NET) for circuit breaking, bulkheads and bulkhead-style concurrency limits.",
                severity=DeprecationSeverity.MEDIUM,
                citation_patterns=[
                    r"\bNetflix\s+Hystrix\b",
                    r"\bhystrix-core\b",
                    r"\bHystrixCircuitBreaker\b",
                ],
                aliases=["Netflix Hystrix", "com.netflix.hystrix"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-mttr-stability",
                subject="MTTR as a stability metric",
                subject_type=SubjectType.METRIC,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.AMENDED_OUTDATED,
                reason="DORA renamed it 'failed deployment recovery time' and moved it from stability to throughput.",
                effective_date="2023-01-01",
                superseded_by=None,
                replacement=["DORA Metrics (five keys)", "Failed Deployment Recovery Time"],
                guidance="Report 'failed deployment recovery time' and include 'deployment rework rate' as the fifth metric.",
                severity=DeprecationSeverity.LOW,
                citation_patterns=[
                    r"\bMTTR\s+as\s+a\s+stability\s+metric\b",
                    r"\bMean\s+Time\s+To\s+Recovery\s+KPI\b",
                ],
                aliases=["MTTR stability KPI", "DORA MTTR stability"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-line-coverage-quality",
                subject="Line coverage as a quality target",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.ANTI_PATTERN,
                reason="Statement coverage is the weakest structural criterion and is trivially gamed by assertion-free tests.",
                effective_date="2022-01-01",
                superseded_by=None,
                replacement=[
                    "Diff / Patch Coverage",
                    "Mutation Score / Mutation Adequacy",
                    "Coverage Ratcheting",
                ],
                guidance="Use coverage to find untested code, not to certify tested code. Gate on diff coverage; measure adequacy with mutation score.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"\b(?:target|require|mandate)\s+(?:80%|90%|100%)\s+line\s+coverage\b",
                    r"\bLine\s+coverage\s+as\s+a\s+quality\s+target\b",
                ],
                aliases=["Line coverage target", "Statement coverage target"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-blind-retries",
                subject="Blind test retries as a flake remedy",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.ANTI_PATTERN,
                reason="Retries convert genuine defects into intermittent production incidents with no owner.",
                effective_date="2021-01-01",
                superseded_by=None,
                replacement=[
                    "Flaky Test Detection and Quarantine",
                    "Retry Semantics and Masking Risk",
                    "Nondeterminism Auditing",
                ],
                guidance="Retry only for infrastructure faults, with telemetry. Quarantine and repair flaky tests rather than papering over them.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"\bblind\s+(?:test\s+)?retries\b",
                    r"\bretrying\s+flaky\s+tests\s+in\s+CI\b",
                ],
                aliases=["Blind retries", "Flake retries in CI"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-checkbox-accessibility",
                subject="Checkbox accessibility scanning",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.ANTI_PATTERN,
                reason="Automated scanners detect roughly 30-40% of WCAG issues and are blind to judgment calls like meaningful alt text.",
                effective_date="2022-01-01",
                superseded_by=None,
                replacement=[
                    "Screen Reader Compatibility Testing",
                    "Keyboard-Only Navigation Testing",
                    "Focus Management and Focus Trap Testing",
                ],
                guidance="Automated scanning is the floor, not the standard. Critical flows require manual assistive-technology passes.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"\bcheckbox\s+accessibility\s+scanning\b",
                    r"\bonly\s+automated\s+accessibility\s+scanners\b",
                ],
                aliases=["Checkbox accessibility", "Automated-only accessibility audit"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-annual-pentest",
                subject="Annual point-in-time penetration testing",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.ANTI_PATTERN,
                reason="PCI DSS 4.0, SOC 2 Type II and FedRAMP require evidence of controls operating across an observation window; point-in-time scans leave provable gaps.",
                effective_date="2023-01-01",
                superseded_by=None,
                replacement=["Continuous Compliance", "Purple Teaming", "Adversary Emulation"],
                guidance="Run continuous or quarterly testing that accumulates timestamped evidence across the audit period.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"\bannual\s+(?:point-in-time\s+)?penetration\s+testing\b",
                    r"\bannual\s+pen\s*test\s+only\b",
                ],
                aliases=["Annual pen-test", "Point-in-time pentesting"],
            )
        )
        self.register_deprecation(
            StatutoryDeprecation(
                id="dep-json-no-contract",
                subject="JSON-over-the-wire without contract testing",
                subject_type=SubjectType.TECHNICAL_PRACTICE,
                regulator=RegulatorCode.INDUSTRY_STANDARD,
                status=DeprecationStatus.ANTI_PATTERN,
                reason="JSON has no built-in compatibility rules, so a removed or renamed field silently breaks consumers.",
                effective_date="2022-01-01",
                superseded_by=None,
                replacement=[
                    "Consumer-Driven Contract Testing",
                    "Breaking Change Detection",
                    "Serialization Backward Compatibility Testing",
                ],
                guidance="Protobuf gives partial natural protection; JSON gives none. Enforce via contracts or schema diffing.",
                severity=DeprecationSeverity.HIGH,
                citation_patterns=[
                    r"\bJSON-over-the-wire\s+without\s+contract\s+testing\b",
                    r"\bunverified\s+JSON\s+payloads\s+across\s+services\b",
                ],
                aliases=["JSON without contracts", "Untyped JSON over the wire"],
            )
        )

    def get_deprecation(self, id_or_subject: str) -> StatutoryDeprecation | None:
        """Lookup deprecation by ID or exact canonical subject/alias."""
        if id_or_subject in self._deprecations:
            return self._deprecations[id_or_subject]
        norm = id_or_subject.lower()
        if norm in self._subject_index:
            dep_id = self._subject_index[norm]
            return self._deprecations.get(dep_id)
        return None

    def list_deprecations(
        self,
        regulator: str | None = None,
        status: str | None = None,
        subject_type: str | None = None,
    ) -> list[StatutoryDeprecation]:
        """List registered deprecations with optional filtering."""
        results = list(self._deprecations.values())
        if regulator:
            results = [d for d in results if d.regulator.value.upper() == regulator.upper()]
        if status:
            results = [d for d in results if d.status.value.lower() == status.lower()]
        if subject_type:
            results = [d for d in results if d.subject_type.value.lower() == subject_type.lower()]
        return sorted(results, key=lambda x: (x.regulator.value, x.id))

    def get_supersession_chain(self, instrument_id: str) -> SupersessionChain:
        """Trace recursive supersession chain from predecessor instrument to active master authority.

        Detects cycles to guarantee termination.
        """
        chain: list[SupersessionNode] = []
        visited: set[str] = set()
        curr_id = instrument_id
        has_cycle = False

        while curr_id:
            if curr_id in visited:
                has_cycle = True
                break
            visited.add(curr_id)

            dep = self.get_deprecation(curr_id)
            meta = self._instrument_metadata.get(curr_id)

            if dep:
                chain.append(
                    SupersessionNode(
                        instrument_id=dep.id,
                        title=dep.subject,
                        regulator=dep.regulator.value,
                        status=dep.status.value,
                        effective_date=dep.effective_date,
                        is_currently_active=False,
                    )
                )
                curr_id = dep.superseded_by or ""
            elif meta:
                chain.append(
                    SupersessionNode(
                        instrument_id=curr_id,
                        title=meta["title"],
                        regulator=meta["regulator"],
                        status=meta["status"],
                        effective_date=meta["effective_date"],
                        is_currently_active=meta["is_currently_active"],
                    )
                )
                curr_id = self._predecessor_to_successor.get(curr_id, "")
            else:
                # Terminal or unknown identifier
                chain.append(
                    SupersessionNode(
                        instrument_id=curr_id,
                        title=curr_id,
                        regulator="UNKNOWN",
                        status="active",
                        effective_date="UNKNOWN",
                        is_currently_active=True,
                    )
                )
                break

        active_authority = chain[-1].title if chain else instrument_id
        return SupersessionChain(
            root_instrument=instrument_id,
            active_authority=active_authority,
            depth=len(chain),
            chain=chain,
            has_cycle=has_cycle,
        )

    def scan_text(
        self,
        text: str,
        as_of_date: str | None = None,
        regulator_filter: str | None = None,
    ) -> list[DeprecationDetection]:
        """Scan input regulatory text, audit finding, or policy document for deprecated items.

        Returns list of structured deprecation findings with replacements and supersession chains.
        """
        detections: list[DeprecationDetection] = []
        found_dep_ids: set[str] = set()

        if not text or not text.strip():
            return detections

        text_lower = text.lower()

        # 1. Exact string / alias matching
        for subject_norm, dep_id in self._subject_index.items():
            if dep_id in found_dep_ids:
                continue
            if subject_norm in text_lower:
                dep = self._deprecations[dep_id]
                if regulator_filter and dep.regulator.value.upper() != regulator_filter.upper():
                    continue

                chain = self.get_supersession_chain(dep.id)
                is_expired = dep.is_sunset_passed(as_of_date)

                detections.append(
                    DeprecationDetection(
                        deprecation_id=dep.id,
                        matched_text=subject_norm,
                        subject=dep.subject,
                        subject_type=dep.subject_type.value,
                        regulator=dep.regulator.value,
                        status=dep.status.value,
                        severity=dep.severity.value,
                        superseded_by=dep.superseded_by,
                        active_authority=chain.active_authority,
                        supersession_chain=[node.title for node in chain.chain],
                        reason=dep.reason,
                        replacement=dep.replacement,
                        guidance=dep.guidance,
                        effective_date=dep.effective_date,
                        sunset_date=dep.sunset_date,
                        is_sunset_passed=is_expired,
                        grandfathering_clause=dep.grandfathering_clause,
                    )
                )
                found_dep_ids.add(dep_id)

        # 2. Regex pattern matching
        for rx, dep_id in self._regex_matchers:
            if dep_id in found_dep_ids:
                continue
            m = rx.search(text)
            if m:
                dep = self._deprecations[dep_id]
                if regulator_filter and dep.regulator.value.upper() != regulator_filter.upper():
                    continue

                chain = self.get_supersession_chain(dep.id)
                is_expired = dep.is_sunset_passed(as_of_date)

                detections.append(
                    DeprecationDetection(
                        deprecation_id=dep.id,
                        matched_text=m.group(0),
                        subject=dep.subject,
                        subject_type=dep.subject_type.value,
                        regulator=dep.regulator.value,
                        status=dep.status.value,
                        severity=dep.severity.value,
                        superseded_by=dep.superseded_by,
                        active_authority=chain.active_authority,
                        supersession_chain=[node.title for node in chain.chain],
                        reason=dep.reason,
                        replacement=dep.replacement,
                        guidance=dep.guidance,
                        effective_date=dep.effective_date,
                        sunset_date=dep.sunset_date,
                        is_sunset_passed=is_expired,
                        grandfathering_clause=dep.grandfathering_clause,
                    )
                )
                found_dep_ids.add(dep_id)

        # Sort detections by severity priority
        severity_order = {
            DeprecationSeverity.CRITICAL.value: 0,
            DeprecationSeverity.HIGH.value: 1,
            DeprecationSeverity.MEDIUM.value: 2,
            DeprecationSeverity.LOW.value: 3,
        }
        detections.sort(key=lambda d: severity_order.get(d.severity, 4))
        return detections


# Singleton accessor
_DEFAULT_DEPRECATION_ENGINE: StatutoryDeprecationEngine | None = None


def get_default_deprecation_engine() -> StatutoryDeprecationEngine:
    """Retrieve or initialize singleton StatutoryDeprecationEngine instance."""
    global _DEFAULT_DEPRECATION_ENGINE
    if _DEFAULT_DEPRECATION_ENGINE is None:
        _DEFAULT_DEPRECATION_ENGINE = StatutoryDeprecationEngine()
    return _DEFAULT_DEPRECATION_ENGINE
