"""Third-Party Vendor Risk Assessment Engine (FEAT-049).

Evaluates third-party SaaS, Cloud, Datacenter, and Payment Switch contracts against
RBI Outsourcing Guidelines and SEBI Cloud Framework mandates. Identifies missing statutory
audit rights, data sovereignty/localization violations, and sub-contracting deficiencies.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog

from app.api.metrics import (
    VENDOR_AUDIT_DURATION_SECONDS,
    VENDOR_CONTRACTS_AUDITED_TOTAL,
)
from app.api.models import (
    DetectedClauseModel,
    MissingClauseModel,
    VendorRiskReportResponse,
)

logger = structlog.get_logger("docscout.compliance.vendor_risk")

VendorType = Literal["CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass(frozen=True)
class StatutoryClauseRule:
    """Definition of a statutory contract clause required under RBI/SEBI regulations."""

    clause_id: str
    clause_name: str
    statutory_requirement: str
    rbi_circular_citation: str
    risk_level: RiskLevel
    weight: float
    positive_patterns: tuple[str, ...]
    negative_patterns: tuple[str, ...]
    remediation_guidance: str
    applicable_vendor_types: tuple[VendorType, ...]


# Catalog of 8 mandatory statutory clauses under RBI IT Outsourcing Directions (2023)
# and SEBI Cloud Security Framework (2023).
STATUTORY_CLAUSE_CATALOG: list[StatutoryClauseRule] = [
    StatutoryClauseRule(
        clause_id="RBI_AUDIT_ACCESS",
        clause_name="Unconditional Regulatory Audit & Inspection Access",
        statutory_requirement=(
            "Contract must explicitly grant Reserve Bank of India (RBI), SEBI, authorized officers, "
            "and external statutory auditors unconditional right to inspect books, systems, personnel, "
            "records, and datacenter premises without undue delay or hindrance."
        ),
        rbi_circular_citation="RBI Master Direction on Outsourcing of IT Services (2023), Chapter IV, Clause 15(a)",
        risk_level="CRITICAL",
        weight=25.0,
        positive_patterns=(
            r"(?:reserve\s+bank\s+of\s+india|rbi|sebi|regulat(?:or|ory)\s+authorit(?:y|ies)|supervisory\s+authorit(?:y|ies)).{0,150}(?:unconditional|full|unrestricted|unhindered|free)?\s*(?:access|right\s+to\s+inspect|inspect(?:ion)?|audit|examine)",
            r"(?:audit|inspect(?:ion)?)\s+(?:rights?|access).{0,150}(?:reserve\s+bank\s+of\s+india|rbi|supervisory\s+authorit(?:y|ies)|statutory\s+auditors?)",
            r"(?:unrestricted|unhindered|unconditional)\s+(?:access|entry|inspection)\s+for\s+(?:the\s+)?(?:regulator|reserve\s+bank|rbi)",
        ),
        negative_patterns=(
            r"(?:no|exclude|prohibit|disclaim).{0,60}(?:regulatory|rbi|supervisory)\s+(?:audit|inspection|access)",
            r"regulator.{0,50}(?:may\s+not|cannot|shall\s+not)\s+(?:access|inspect|audit)",
        ),
        remediation_guidance=(
            "Insert mandatory clause: 'The Service Provider covenants that the Reserve Bank of India (RBI), "
            "SEBI, and their appointed authorized auditors shall have unconditional and unrestricted right of "
            "access to inspect, audit, and examine all books, accounts, systems, records, operations, and "
            "datacenter facilities relating to the outsourced services.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="DATA_LOCALIZATION",
        clause_name="Indian Sovereign Data Localization",
        statutory_requirement=(
            "All regulated financial data, customer personal identifiable information (PII), payment logs, "
            "and transaction records must be stored and processed exclusively in datacenters located within "
            "the geographic boundaries of India, with zero offshore mirroring or transit."
        ),
        rbi_circular_citation="RBI Directive DPSS.CO.OD.No.2785/06.08.005/2017-18 & SEBI Cloud Framework Clause 3.2",
        risk_level="CRITICAL",
        weight=25.0,
        positive_patterns=(
            r"(?:store|stored|storage|process|processed|processing|host|hosted|hosting).{0,120}(?:exclusively|solely|entirely|only)?\s*(?:within|in)\s+(?:the\s+territory\s+of\s+)?(?:india|indian\s+territory|onshore\s+datacenters?)",
            r"(?:data\s+localization|onshore\s+storage|indian\s+sovereignty).{0,120}(?:mandate|complian(?:t|ce)|guarantee|covenant)",
            r"(?:servers?|datacenters?|infrastructure)\s+(?:located|situated|residing)\s+(?:within|in)\s+india",
        ),
        negative_patterns=(
            r"(?:transfer|replicate|mirror|route|store|back\s*up).{0,100}(?:outside|overseas|cross-border|offshore)\s*(?:of\s+)?india",
            r"data\s+may\s+be\s+transferred\s+to.{0,60}(?:united\s+states|ireland|europe|singapore|foreign|overseas)",
            r"reserves?\s+the\s+right\s+to\s+process\s+data\s+(?:globally|internationally|in\s+any\s+country)",
        ),
        remediation_guidance=(
            "Insert mandatory clause: 'The Service Provider covenants that all customer data, transaction records, "
            "audit logs, and metadata shall be stored, processed, and maintained exclusively on servers physically "
            "located within the territory of India, and shall not be transferred or mirrored offshore under any circumstances.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="SUB_CONTRACTING_CONTROL",
        clause_name="Sub-Contracting Prior Consent & Oversight",
        statutory_requirement=(
            "The service provider shall not sub-contract or delegate any material component of the outsourced "
            "services without obtaining prior written approval from the regulated entity, and must pass through "
            "all statutory audit, security, and confidentiality obligations."
        ),
        rbi_circular_citation="RBI Master Direction on Outsourcing of IT Services (2023), Chapter IV, Clause 16",
        risk_level="HIGH",
        weight=15.0,
        positive_patterns=(
            r"(?:sub-?contract(?:ing)?|sub-?contractor|delegate|delegation).{0,140}(?:prior\s+written\s+(?:consent|approval|permission)|require\s+approval)",
            r"(?:no|shall\s+not)\s+(?:sub-?contract|delegate).{0,100}without\s+(?:the\s+)?(?:prior\s+written\s+consent|express\s+approval)",
            r"(?:sub-?contractors?|third-party\s+suppliers?)\s+shall\s+be\s+bound\s+by\s+the\s+same\s+obligations",
        ),
        negative_patterns=(
            r"vendor\s+(?:may|reserves\s+the\s+right\s+to)\s+sub-?contract.{0,80}without\s+(?:notice|prior\s+consent|approval)",
            r"consent\s+for\s+sub-?contracting\s+(?:is\s+not\s+required|deemed\s+given)",
        ),
        remediation_guidance=(
            "Insert mandatory clause: 'The Service Provider shall not sub-contract or delegate any part of the "
            "services without prior written approval from the Customer. All approved sub-contractors shall be bound "
            "by the same statutory compliance, audit access, and data security standards.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="INCIDENT_NOTIFICATION",
        clause_name="Security Incident Notification & CERT-In Reporting",
        statutory_requirement=(
            "The service provider must notify the regulated entity immediately, and in no event later than "
            "1 to 6 hours, upon detecting any cyber incident, unauthorized access, data breach, or operational outage."
        ),
        rbi_circular_citation="RBI Cyber Security Framework Annexure 1 & CERT-In Cyber Security Directions (2022)",
        risk_level="CRITICAL",
        weight=20.0,
        positive_patterns=(
            r"(?:security\s+incident|data\s+breach|cyber\s+attack|unauthorized\s+access|security\s+compromise|incidents?).{0,140}(?:notif(?:y|ication|ying)|report(?:ing|ed)?|inform).{0,80}(?:within\s+(?:[1-6]|one|six)\s+hours?|immediately|promptly)",
            r"(?:notif(?:y|ication|ying)|report(?:ing|ed)?|inform).{0,100}(?:security\s+incident|data\s+breach|cyber\s+attack|unauthorized\s+access|security\s+compromise|incidents?|breach).{0,80}(?:within\s+(?:[1-6]|one|six)\s+hours?|immediately|promptly)",
            r"(?:security\s+)?incidents?\s+(?:reported|notified)\s+within\s+(?:[1-6]|one|six)\s+hours?",
        ),
        negative_patterns=(
            r"(?:notif(?:y|ication)|inform).{0,60}(?:within\s+(?:30|60|90)\s+days|at\s+its\s+sole\s+discretion)",
            r"no\s+obligation\s+to\s+notify\s+security\s+incidents",
        ),
        remediation_guidance=(
            "Insert mandatory clause: 'In the event of any security breach, unauthorized access, data leakage, "
            "or material operational disruption, the Service Provider shall immediately, and no later than 6 hours "
            "from discovery, notify the Customer in writing with comprehensive forensic incident details.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="BCP_DR_TESTING",
        clause_name="Business Continuity & Disaster Recovery Joint Drills",
        statutory_requirement=(
            "Commitment to maintain robust Disaster Recovery (DR) and Business Continuity Plans (BCP), "
            "conduct joint annual testing drills, and adhere to statutory RPO (<= 15 min) and RTO (<= 2 hr) metrics."
        ),
        rbi_circular_citation="RBI Master Direction on IT Outsourcing, Chapter V, Clause 21",
        risk_level="HIGH",
        weight=15.0,
        positive_patterns=(
            r"(?:business\s+continuity|disaster\s+recovery|bcp|dr).{0,140}(?:test(?:ing)?|drill|exercise|plan).{0,80}(?:annual(?:ly)?|periodic(?:ally)?|at\s+least\s+once\s+a\s+year)",
            r"(?:annual(?:ly)?|periodic(?:ally)?).{0,80}(?:business\s+continuity|disaster\s+recovery|bcp|dr|failover).{0,60}(?:test(?:ing)?|drill|exercise)",
            r"(?:rto|recovery\s+time\s+objective).{0,100}(?:rpo|recovery\s+point\s+objective)",
            r"(?:high\s+availability|failover).{0,80}(?:tested|verified|dr\s+drill)",
            r"rto\s*<=\s*2\s*hours?",
        ),
        negative_patterns=(
            r"no\s+warranty\s+for\s+(?:business\s+continuity|disaster\s+recovery)",
            r"disclaims?\s+all\s+liability\s+for\s+outages\s+and\s+data\s+loss",
        ),
        remediation_guidance=(
            "Insert clause: 'The Service Provider shall maintain an active Business Continuity and Disaster "
            "Recovery Plan, participate in joint annual DR drills with the Customer, and guarantee a Recovery Time "
            "Objective (RTO) of <= 2 hours and Recovery Point Objective (RPO) of <= 15 minutes.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="TERMINATION_ASSISTANCE",
        clause_name="Orderly Exit & Post-Termination Transition Assistance",
        statutory_requirement=(
            "Obligation to provide transition assistance for a minimum of 90 to 180 days upon contract termination, "
            "return all customer data in industry standard formats, and issue certificate of cryptographic sanitization."
        ),
        rbi_circular_citation="RBI Master Direction on IT Outsourcing, Chapter IV, Clause 18",
        risk_level="HIGH",
        weight=15.0,
        positive_patterns=(
            r"(?:transition\s+assistance|exit\s+assistance|orderly\s+exit|orderly\s+handover|termination\s+assistance)",
            r"(?:upon\s+termination|on\s+expiry).{0,200}(?:return|transfer|handover)",
            r"(?:return|handover|transfer).{0,80}(?:all\s+)?(?:customer\s+data|bank\s+data|records|data)",
            r"(?:crypto(?:graphic)?|secure)\s+(?:erasure|deletion|destruction|sanitization)",
            r"(?:certifi(?:ed|cate|cation)).{0,80}(?:crypto(?:graphic)?|secure)?\s*(?:erasure|deletion|destruction|sanitization)",
        ),
        negative_patterns=(
            r"(?:immediate\s+deletion|destroy\s+immediately)\s+without\s+(?:transition|data\s+return)",
            r"vendor\s+has\s+no\s+obligation\s+to\s+assist\s+in\s+transition",
        ),
        remediation_guidance=(
            "Insert clause: 'Upon termination or expiry of this Agreement, the Service Provider shall provide "
            "orderly exit and transition assistance for up to 180 days, return all Customer data in standard formats, "
            "and provide written certification of cryptographic sanitization of all remaining copies.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="CONFIDENTIALITY_SECURITY",
        clause_name="Confidentiality & Statutory Data Protection (DPDPA)",
        statutory_requirement=(
            "Contractual covenants binding vendor and personnel to non-disclosure, confidentiality, "
            "and statutory data protection under the Digital Personal Data Protection Act (DPDPA 2023) and IT Act."
        ),
        rbi_circular_citation="RBI Master Direction on IT Outsourcing, Chapter IV, Clause 17 & DPDPA 2023",
        risk_level="MEDIUM",
        weight=10.0,
        positive_patterns=(
            r"(?:confidential(?:ity)?|non-disclosure).{0,120}(?:indefinite(?:ly)?|survives?\s+termination|strict\s+confidence)",
            r"(?:data\s+protection|dpdpa|digital\s+personal\s+data\s+protection|it\s+act).{0,100}(?:complian(?:t|ce)|obligation|safeguard)",
            r"(?:protect|safeguard)\s+(?:customer|personal|financial)\s+data\s+from\s+unauthorized\s+disclosure",
            r"strict\s+confidentiality\s+survives?\s+termination",
        ),
        negative_patterns=(
            r"confidentiality\s+obligations\s+shall\s+terminate\s+immediately\s+upon\s+expiry",
            r"vendor\s+may\s+monetize\s+or\s+share\s+customer\s+data",
        ),
        remediation_guidance=(
            "Insert clause: 'The Service Provider and its personnel shall preserve the confidentiality of all Customer "
            "and Bank data in perpetuity, implement robust technological safeguards in compliance with DPDPA 2023, "
            "and ensure confidentiality obligations survive contract termination.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
    StatutoryClauseRule(
        clause_id="SOC2_ISO_AUDIT_RIGHTS",
        clause_name="Third-Party Security Certifications (SOC-2 & ISO 27001)",
        statutory_requirement=(
            "Obligation to furnish annual independent third-party assurance reports, including SOC-2 Type II "
            "and ISO/IEC 27001 certifications conducted by qualified independent auditors."
        ),
        rbi_circular_citation="SEBI Cloud Security Framework Clause 5.1 & RBI Cyber Security Guidelines",
        risk_level="MEDIUM",
        weight=10.0,
        positive_patterns=(
            r"(?:soc\s*2|soc-2|service\s+organization\s+control\s+2).{0,80}(?:type\s+(?:2|ii)|report|audit)",
            r"(?:iso\s*\/?\s*iec\s*27001|iso\s*27001).{0,80}(?:certifi(?:ed|cate|cation)|standard|compliance)",
            r"(?:independent|third-party)\s+(?:audit|certifi(?:ed|cate|cation)|security\s+assessment).{0,80}(?:annually|annual\s+basis)",
        ),
        negative_patterns=(r"vendor\s+does\s+not\s+provide\s+third-party\s+audit\s+reports",),
        remediation_guidance=(
            "Insert clause: 'The Service Provider shall maintain active ISO/IEC 27001 certification and annually "
            "provide the Customer with an unqualified SOC-2 Type II independent audit report covering the operational "
            "and security controls of the services.'"
        ),
        applicable_vendor_types=("CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"),
    ),
]


@dataclass(frozen=True)
class VendorRiskConfig:
    """Configuration for Vendor Risk Assessment Engine."""

    strict_localization: bool = True
    min_score_threshold: float = 75.0


class VendorRiskAssessmentEngine:
    """Evaluates third-party vendor contracts against Indian regulatory outsourcing mandates."""

    def __init__(self, config: VendorRiskConfig | None = None) -> None:
        self.config = config or VendorRiskConfig()
        # Compile regular expressions for sub-millisecond execution
        self._compiled_positive: dict[str, list[re.Pattern[str]]] = {}
        self._compiled_negative: dict[str, list[re.Pattern[str]]] = {}

        for rule in STATUTORY_CLAUSE_CATALOG:
            self._compiled_positive[rule.clause_id] = [
                re.compile(p, re.IGNORECASE | re.DOTALL) for p in rule.positive_patterns
            ]
            self._compiled_negative[rule.clause_id] = [
                re.compile(p, re.IGNORECASE | re.DOTALL) for p in rule.negative_patterns
            ]

    def _extract_matched_snippet(self, text: str, match: re.Match[str], max_len: int = 160) -> str:
        """Extract clean snippet centered around pattern match."""
        start = max(0, match.start() - 30)
        end = min(len(text), match.end() + 30)
        snippet = " ".join(text[start:end].split())
        if len(snippet) > max_len:
            snippet = snippet[:max_len] + "..."
        return snippet

    def evaluate_contract(
        self,
        contract_text: str,
        vendor_type: VendorType,
        vendor_name: str | None = None,
        strict_localization: bool | None = None,
    ) -> VendorRiskReportResponse:
        """Audit third-party vendor contract text against mandatory statutory clauses."""
        t0 = time.perf_counter()

        text = contract_text.strip()
        if len(text) < 100 or len(text) > 150000:
            raise ValueError(
                f"Contract text length ({len(text)} characters) must be between 100 and 150,000 characters."
            )

        effective_strict_loc = (
            strict_localization
            if strict_localization is not None
            else self.config.strict_localization
        )

        applicable_rules = [
            rule for rule in STATUTORY_CLAUSE_CATALOG if vendor_type in rule.applicable_vendor_types
        ]

        present_clauses: list[str] = []
        missing_clauses: list[MissingClauseModel] = []
        detected_clauses: list[DetectedClauseModel] = []

        total_weight = sum(rule.weight for rule in applicable_rules)
        achieved_weight = 0.0
        critical_missing_count = 0

        for rule in applicable_rules:
            # Check for negative patterns that negate the clause
            has_negative = False
            for neg_pat in self._compiled_negative[rule.clause_id]:
                if neg_pat.search(text):
                    has_negative = True
                    break

            # If strict localization is enforced, offshore transfer keywords automatically negate DATA_LOCALIZATION
            if rule.clause_id == "DATA_LOCALIZATION" and effective_strict_loc and has_negative:
                missing_clauses.append(
                    MissingClauseModel(
                        clause_name=rule.clause_name,
                        statutory_requirement=rule.statutory_requirement,
                        rbi_circular_citation=rule.rbi_circular_citation,
                        risk_level=rule.risk_level,
                        remediation_guidance=(
                            "Offshore data transfer language detected. " + rule.remediation_guidance
                        ),
                    )
                )
                critical_missing_count += 1
                continue

            # Check for positive matches
            found_match: re.Match[str] | None = None
            for pos_pat in self._compiled_positive[rule.clause_id]:
                m = pos_pat.search(text)
                if m:
                    found_match = m
                    break

            if found_match and not has_negative:
                present_clauses.append(rule.clause_id)
                achieved_weight += rule.weight
                snippet = self._extract_matched_snippet(text, found_match)
                detected_clauses.append(
                    DetectedClauseModel(
                        clause_name=rule.clause_name,
                        confidence=0.98,
                        matched_snippet=snippet,
                    )
                )
            else:
                if rule.risk_level == "CRITICAL":
                    critical_missing_count += 1
                missing_clauses.append(
                    MissingClauseModel(
                        clause_name=rule.clause_name,
                        statutory_requirement=rule.statutory_requirement,
                        rbi_circular_citation=rule.rbi_circular_citation,
                        risk_level=rule.risk_level,
                        remediation_guidance=rule.remediation_guidance,
                    )
                )

        # Calculate compliance score
        if total_weight > 0:
            raw_score = (achieved_weight / total_weight) * 100.0
        else:
            raw_score = 0.0

        # Cap score if critical statutory clauses are missing
        if critical_missing_count >= 2:
            raw_score = min(raw_score, 45.0)
        elif critical_missing_count == 1:
            raw_score = min(raw_score, 65.0)

        compliance_score = round(raw_score, 2)

        # Determine risk rating
        if critical_missing_count >= 2 or compliance_score < 50.0:
            risk_rating: RiskLevel = "CRITICAL"
        elif critical_missing_count == 1 or compliance_score < 75.0:
            risk_rating = "HIGH"
        elif compliance_score < 90.0:
            risk_rating = "MEDIUM"
        else:
            risk_rating = "LOW"

        # Record metrics
        duration = time.perf_counter() - t0
        VENDOR_AUDIT_DURATION_SECONDS.observe(duration)
        VENDOR_CONTRACTS_AUDITED_TOTAL.labels(risk_level=risk_rating).inc()

        logger.info(
            "vendor_contract_audited",
            vendor_type=vendor_type,
            vendor_name=vendor_name,
            score=compliance_score,
            risk_rating=risk_rating,
            present_count=len(present_clauses),
            missing_count=len(missing_clauses),
            duration_ms=round(duration * 1000, 2),
        )

        return VendorRiskReportResponse(
            vendor_name=vendor_name,
            vendor_type=vendor_type,
            compliance_score=compliance_score,
            risk_rating=risk_rating,
            mandatory_clauses_present=present_clauses,
            missing_clauses=missing_clauses,
            detected_clauses=detected_clauses,
            contract_char_count=len(text),
            audit_timestamp=datetime.now(UTC),
            strict_localization_enforced=effective_strict_loc,
        )


_DEFAULT_VENDOR_RISK_ENGINE: VendorRiskAssessmentEngine | None = None


def get_default_vendor_risk_engine() -> VendorRiskAssessmentEngine:
    """Return singleton instance of VendorRiskAssessmentEngine."""
    global _DEFAULT_VENDOR_RISK_ENGINE
    if _DEFAULT_VENDOR_RISK_ENGINE is None:
        _DEFAULT_VENDOR_RISK_ENGINE = VendorRiskAssessmentEngine()
    return _DEFAULT_VENDOR_RISK_ENGINE
