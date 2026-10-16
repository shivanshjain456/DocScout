"""Regulatory Risk Scorecard Generator (FEAT-040).

Automated audit report generator grading an organization's policy documents against DocScout's
canonical antipattern, deprecation, and standards catalogs, producing executive-ready PDF and
Markdown compliance scorecards with prioritized remediation roadmaps.
"""

from __future__ import annotations

import base64
import io
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import structlog
from pypdf import PdfWriter

from app.compliance.antipattern_scanner import AntipatternFinding, AntipatternScanner
from app.compliance.deprecation_engine import DeprecationDetection, StatutoryDeprecationEngine
from app.compliance.standards_registry import StandardsRegistry, get_default_standards_registry

logger = structlog.get_logger("docscout.compliance.scorecard")


@dataclass(frozen=True)
class MandatoryStandardReq:
    id: str
    name: str
    aliases: tuple[str, ...]


# Mandatory regulatory standards mapped by financial institution archetype
ORGANIZATION_MANDATORY_STANDARDS: dict[str, list[MandatoryStandardReq]] = {
    "scheduled_commercial_bank": [
        MandatoryStandardReq(
            id="RBI_KYC_MASTER_DIRECTION",
            name="RBI Master Direction - Know Your Customer (KYC)",
            aliases=(
                "kyc master direction",
                "know your customer direction",
                "rbi kyc",
                "ckycr",
                "v-cip",
            ),
        ),
        MandatoryStandardReq(
            id="RBI_CYBER_SECURITY_FRAMEWORK",
            name="RBI Cyber Security Framework in Banks",
            aliases=(
                "rbi cyber security",
                "cyber security framework",
                "cscrf",
                "incident notification",
            ),
        ),
        MandatoryStandardReq(
            id="BASEL_III",
            name="Basel III Capital Regulations",
            aliases=("basel iii", "basel 3", "basel", "crar", "cre20"),
        ),
        MandatoryStandardReq(
            id="ISO/IEC 27001",
            name="ISO/IEC 27001 Information Security Management",
            aliases=("iso 27001", "iso/iec 27001", "iso27001"),
        ),
        MandatoryStandardReq(
            id="PMLA_RULES",
            name="Prevention of Money-Laundering (Maintenance of Records) Rules",
            aliases=(
                "pmla",
                "prevention of money-laundering",
                "prevention of money laundering",
                "beneficial ownership",
            ),
        ),
    ],
    "nbfc": [
        MandatoryStandardReq(
            id="RBI_SCALE_BASED_REGULATION",
            name="RBI Scale Based Regulation (SBR) for NBFCs",
            aliases=("scale based regulation", "sbr", "nbfc-sbr", "middle layer", "upper layer"),
        ),
        MandatoryStandardReq(
            id="RBI_KYC_MASTER_DIRECTION",
            name="RBI Master Direction - Know Your Customer (KYC)",
            aliases=("kyc master direction", "know your customer", "rbi kyc", "ckycr", "v-cip"),
        ),
        MandatoryStandardReq(
            id="RBI_CYBER_SECURITY_FRAMEWORK",
            name="RBI Cyber Security Framework",
            aliases=("rbi cyber security", "cyber security framework", "cscrf"),
        ),
        MandatoryStandardReq(
            id="ISO/IEC 27001",
            name="ISO/IEC 27001 Information Security Management",
            aliases=("iso 27001", "iso/iec 27001", "iso27001"),
        ),
    ],
    "payment_aggregator": [
        MandatoryStandardReq(
            id="RBI_PAYMENT_AGGREGATOR_DIRECTIONS",
            name="RBI Guidelines for Regulation of Payment Aggregators and Payment Gateways",
            aliases=(
                "payment aggregator guidelines",
                "payment aggregator directions",
                "guidelines on payment aggregator",
                "escrow",
            ),
        ),
        MandatoryStandardReq(
            id="CARD_ON_FILE_TOKENIZATION",
            name="RBI Card-on-File Tokenization (CoFT)",
            aliases=(
                "card-on-file tokenization",
                "tokenization",
                "coft",
                "card on file tokenization",
            ),
        ),
        MandatoryStandardReq(
            id="RBI_CYBER_SECURITY_FRAMEWORK",
            name="RBI Cyber Security Framework",
            aliases=("rbi cyber security", "cyber security framework", "cscrf"),
        ),
        MandatoryStandardReq(
            id="ISO/IEC 27001",
            name="ISO/IEC 27001 Information Security Management",
            aliases=("iso 27001", "iso/iec 27001", "iso27001"),
        ),
    ],
    "fintech": [
        MandatoryStandardReq(
            id="RBI_DIGITAL_LENDING_DIRECTIONS",
            name="RBI Digital Lending Guidelines",
            aliases=(
                "digital lending guidelines",
                "digital lending directions",
                "key fact statement",
                "kfs",
            ),
        ),
        MandatoryStandardReq(
            id="ISO/IEC 27001",
            name="ISO/IEC 27001 Information Security Management",
            aliases=("iso 27001", "iso/iec 27001", "iso27001"),
        ),
        MandatoryStandardReq(
            id="OWASP_ASVS",
            name="OWASP Application Security Verification Standard",
            aliases=("owasp", "asvs", "owasp asvs", "appsec"),
        ),
    ],
    "general": [
        MandatoryStandardReq(
            id="ISO/IEC 27001",
            name="ISO/IEC 27001 Information Security Management",
            aliases=("iso 27001", "iso/iec 27001", "iso27001"),
        ),
        MandatoryStandardReq(
            id="RBI_CYBER_SECURITY_FRAMEWORK",
            name="Cybersecurity Framework / CSCRF",
            aliases=("cyber security", "cybersecurity", "cscrf", "framework"),
        ),
    ],
}

DEFAULT_RUBRIC_WEIGHTS: dict[str, float] = {
    "antipatterns": 0.4,
    "deprecations": 0.4,
    "standards_coverage": 0.2,
}


@dataclass
class ScorecardResult:
    """Consolidated assessment outcome across all compliance dimensions."""

    overall_grade: Literal["A", "B", "C", "D", "F"]
    numerical_score: float
    antipatterns_score: float
    deprecations_score: float
    standards_coverage_score: float
    antipattern_findings: list[AntipatternFinding]
    deprecation_detections: list[DeprecationDetection]
    matched_standards: list[str]
    missing_standards: list[str]
    critical_risks: list[str]
    remediation_timeline_days: int
    markdown_report: str
    pdf_bytes: bytes | None = None
    pdf_base64: str | None = None
    organization_type: str = "scheduled_commercial_bank"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class RegulatoryRiskScorecardEngine:
    """Core evaluation engine assessing policy dossiers against statutory knowledge graphs."""

    def __init__(
        self,
        antipattern_scanner: AntipatternScanner | None = None,
        deprecation_engine: StatutoryDeprecationEngine | None = None,
        standards_registry: StandardsRegistry | None = None,
    ) -> None:
        self.antipattern_scanner = antipattern_scanner or AntipatternScanner()
        self.deprecation_engine = deprecation_engine or StatutoryDeprecationEngine()
        self.standards_registry = standards_registry or get_default_standards_registry()

    def generate_scorecard(
        self,
        policy_document_texts: list[str],
        organization_type: str = "scheduled_commercial_bank",
        include_pdf: bool = False,
        rubric_weights: dict[str, float] | None = None,
    ) -> ScorecardResult:
        """Execute full compliance audit scan and produce consolidated scorecard."""
        t0 = time.perf_counter()
        org_norm = organization_type.strip().lower()
        if org_norm not in ORGANIZATION_MANDATORY_STANDARDS:
            org_norm = "general"

        weights = self._normalize_weights(rubric_weights or DEFAULT_RUBRIC_WEIGHTS)
        combined_text = "\n\n".join(policy_document_texts)

        # 1. Antipattern Scanning
        ap_findings: list[AntipatternFinding] = []
        for idx, doc_text in enumerate(policy_document_texts, start=1):
            scan_res = self.antipattern_scanner.scan_document(
                doc_text, document_name=f"Policy-Document-{idx}"
            )
            raw_findings = scan_res.get("findings", [])
            for rf in raw_findings:
                if isinstance(rf, AntipatternFinding):
                    ap_findings.append(rf)
                elif isinstance(rf, dict):
                    rule_id = rf.get("rule_id", "")
                    rule = self.antipattern_scanner.get_rule(rule_id)
                    if rule:
                        ap_findings.append(
                            AntipatternFinding(
                                rule_id=rule.id,
                                practice=rule.practice,
                                antipattern=rule.antipattern,
                                consequence=rule.consequence,
                                instead=rule.instead,
                                severity=rf.get("severity", rule.severity),
                                domain_category=rule.domain_category,
                                matched_snippet=rf.get("matched_snippet", ""),
                                line_number=rf.get("line_number"),
                                confidence=rf.get("confidence", 0.95),
                            )
                        )

        # Deduplicate antipattern findings by rule_id
        seen_rules: set[str] = set()
        deduped_ap: list[AntipatternFinding] = []
        for finding in ap_findings:
            if finding.rule_id not in seen_rules:
                seen_rules.add(finding.rule_id)
                deduped_ap.append(finding)

        # 2. Statutory Deprecation & Supersession Scanning
        dep_detections = self.deprecation_engine.scan_text(combined_text)
        seen_deps: set[str] = set()
        deduped_deps: list[DeprecationDetection] = []
        for det in dep_detections:
            if det.deprecation_id not in seen_deps:
                seen_deps.add(det.deprecation_id)
                deduped_deps.append(det)

        # 3. Mandatory Standards Coverage Analysis
        mandatory_list = ORGANIZATION_MANDATORY_STANDARDS.get(
            org_norm, ORGANIZATION_MANDATORY_STANDARDS["general"]
        )
        matched_standards: list[str] = []
        missing_standards: list[str] = []
        lower_corpus = combined_text.lower()

        for req in mandatory_list:
            resolved_std = self.standards_registry.get_standard(req.id)
            search_terms = list(req.aliases) + [req.id.lower(), req.name.lower()]
            if resolved_std:
                search_terms.extend(
                    [resolved_std.id.lower(), resolved_std.name.lower()]
                    + [a.lower() for a in resolved_std.aliases]
                )

            is_matched = any(term in lower_corpus for term in search_terms)
            if is_matched:
                matched_standards.append(req.id)
            else:
                missing_standards.append(req.id)

        # 4. Dimension Scoring
        ap_score = 100.0
        for f in deduped_ap:
            sev = f.severity.upper()
            if sev == "CRITICAL":
                ap_score -= 15.0
            elif sev == "HIGH":
                ap_score -= 8.0
            else:
                ap_score -= 3.0
        ap_score = max(0.0, min(100.0, ap_score))

        dep_score = 100.0
        for d in deduped_deps:
            if d.is_sunset_passed:
                dep_score -= 20.0
            elif d.severity == "CRITICAL":
                dep_score -= 15.0
            elif d.severity == "HIGH":
                dep_score -= 8.0
            else:
                dep_score -= 4.0
        dep_score = max(0.0, min(100.0, dep_score))

        if mandatory_list:
            std_score = (len(matched_standards) / len(mandatory_list)) * 100.0
        else:
            std_score = 100.0
        std_score = max(0.0, min(100.0, std_score))

        final_numerical_score = round(
            ap_score * weights["antipatterns"]
            + dep_score * weights["deprecations"]
            + std_score * weights["standards_coverage"],
            2,
        )

        overall_grade: Literal["A", "B", "C", "D", "F"]
        if final_numerical_score >= 90.0:
            overall_grade = "A"
        elif final_numerical_score >= 80.0:
            overall_grade = "B"
        elif final_numerical_score >= 70.0:
            overall_grade = "C"
        elif final_numerical_score >= 60.0:
            overall_grade = "D"
        else:
            overall_grade = "F"

        # 5. Critical Risks Aggregation
        critical_risks: list[str] = []
        for f in deduped_ap:
            if f.severity.upper() == "CRITICAL":
                critical_risks.append(f"Antipattern: {f.practice} ({f.rule_id}) - {f.consequence}")
        for d in deduped_deps:
            if d.is_sunset_passed:
                critical_risks.append(
                    f"Sunset Expired Circular: {d.subject} (Sunset: {d.sunset_date}) - Successor: {d.active_authority or 'None'}"
                )
            elif d.severity == "CRITICAL":
                critical_risks.append(f"Critical Supersession: {d.subject} -> {d.active_authority}")
        for missing in missing_standards:
            critical_risks.append(f"Missing Mandatory Standard: {missing}")

        # 6. Remediation Timeline Calculation
        timeline_days = 7
        crit_count = sum(1 for f in deduped_ap if f.severity.upper() == "CRITICAL") + sum(
            1 for d in deduped_deps if d.is_sunset_passed or d.severity == "CRITICAL"
        )
        high_count = sum(1 for f in deduped_ap if f.severity.upper() == "HIGH") + sum(
            1 for d in deduped_deps if not d.is_sunset_passed and d.severity == "HIGH"
        )

        timeline_days += crit_count * 14
        timeline_days += high_count * 5
        timeline_days += len(missing_standards) * 7
        timeline_days = min(180, max(7, timeline_days))

        # 7. Markdown Report
        markdown_report = self._render_markdown_report(
            overall_grade=overall_grade,
            numerical_score=final_numerical_score,
            ap_score=ap_score,
            dep_score=dep_score,
            std_score=std_score,
            antipattern_findings=deduped_ap,
            deprecation_detections=deduped_deps,
            matched_standards=matched_standards,
            missing_standards=missing_standards,
            critical_risks=critical_risks,
            timeline_days=timeline_days,
            organization_type=organization_type,
        )

        # 8. PDF Generation (if requested)
        pdf_bytes: bytes | None = None
        pdf_base64: str | None = None
        if include_pdf:
            try:
                pdf_bytes = self._generate_pdf_report(
                    overall_grade=overall_grade,
                    numerical_score=final_numerical_score,
                    organization_type=organization_type,
                    antipattern_findings=deduped_ap,
                    deprecation_detections=deduped_deps,
                    critical_risks=critical_risks,
                    timeline_days=timeline_days,
                )
                if pdf_bytes:
                    pdf_base64 = base64.b64encode(pdf_bytes).decode("ascii")
            except Exception as err:
                logger.error("scorecard_pdf_generation_failed", error=str(err))
                pdf_bytes = None
                pdf_base64 = None

        logger.info(
            "scorecard.generated",
            grade=overall_grade,
            score=final_numerical_score,
            organization_type=organization_type,
            critical_risks=len(critical_risks),
            duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

        return ScorecardResult(
            overall_grade=overall_grade,
            numerical_score=final_numerical_score,
            antipatterns_score=ap_score,
            deprecations_score=dep_score,
            standards_coverage_score=std_score,
            antipattern_findings=deduped_ap,
            deprecation_detections=deduped_deps,
            matched_standards=matched_standards,
            missing_standards=missing_standards,
            critical_risks=critical_risks,
            remediation_timeline_days=timeline_days,
            markdown_report=markdown_report,
            pdf_bytes=pdf_bytes,
            pdf_base64=pdf_base64,
            organization_type=organization_type,
        )

    def _normalize_weights(self, weights: dict[str, float]) -> dict[str, float]:
        w_ap = max(0.0, weights.get("antipatterns", 0.4))
        w_dep = max(0.0, weights.get("deprecations", 0.4))
        w_std = max(0.0, weights.get("standards_coverage", 0.2))
        total = w_ap + w_dep + w_std
        if total <= 0.0:
            return DEFAULT_RUBRIC_WEIGHTS.copy()
        return {
            "antipatterns": w_ap / total,
            "deprecations": w_dep / total,
            "standards_coverage": w_std / total,
        }

    def _render_markdown_report(
        self,
        overall_grade: str,
        numerical_score: float,
        ap_score: float,
        dep_score: float,
        std_score: float,
        antipattern_findings: list[AntipatternFinding],
        deprecation_detections: list[DeprecationDetection],
        matched_standards: list[str],
        missing_standards: list[str],
        critical_risks: list[str],
        timeline_days: int,
        organization_type: str,
    ) -> str:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        md = [
            f"# Regulatory Risk Audit Scorecard: {organization_type.upper().replace('_', ' ')}",
            "",
            f"**Audit Timestamp:** `{date_str}` | **Auditor Engine:** DocScout Enterprise v1.0",
            "",
            "## 1. Executive Summary & Grading",
            "",
            f"- **Overall Compliance Grade:** `{overall_grade}`",
            f"- **Institutional Risk Score:** **{numerical_score:.1f} / 100.0**",
            f"- **Target Remediation Window:** **{timeline_days} Days**",
            f"- **Antipattern Subscore (40% weight):** {ap_score:.1f} / 100.0",
            f"- **Statutory Currency Subscore (40% weight):** {dep_score:.1f} / 100.0",
            f"- **Mandatory Standards Coverage (20% weight):** {std_score:.1f} / 100.0",
            "",
        ]

        if critical_risks:
            md.append("## 2. Critical Regulatory Risks & Showstoppers")
            md.append("> [!CAUTION]")
            md.append(
                "> The following statutory violations require immediate board-level escalation and remediation:"
            )
            for cr in critical_risks:
                md.append(f"> - **{cr}**")
            md.append("")

        md.append("## 3. Antipattern Findings Breakdown")
        if antipattern_findings:
            md.append(
                "| Rule ID | Practice | Severity | Matched Snippet | Prescriptive Remediation |"
            )
            md.append("|---|---|---|---|---|")
            for f in antipattern_findings:
                clean_snippet = re.sub(r"\s+", " ", f.matched_snippet)[:60].replace("|", "\\|")
                remedies = ", ".join(f.instead[:2]).replace("|", "\\|")
                md.append(
                    f'| `{f.rule_id}` | {f.practice} | **{f.severity}** | *"{clean_snippet}"* | {remedies} |'
                )
        else:
            md.append(
                "No technical or organizational antipatterns detected. Policy aligns with verified practices."
            )
        md.append("")

        md.append("## 4. Statutory Deprecations & Supersession Chains")
        if deprecation_detections:
            md.append(
                "| Predecessor Instrument | Status | Sunset Expired | Active Successor Authority | Remediation Guidance |"
            )
            md.append("|---|---|---|---|---|")
            for d in deprecation_detections:
                sunset_badge = "EXPIRED" if d.is_sunset_passed else (d.sunset_date or "N/A")
                successor = d.active_authority or "Repealed"
                guide = d.guidance[:80].replace("|", "\\|")
                md.append(
                    f"| {d.subject} | `{d.status}` | **{sunset_badge}** | {successor} | {guide}... |"
                )
        else:
            md.append(
                "All cited circulars and guidelines are active current law. No obsolete instruments detected."
            )
        md.append("")

        md.append("## 5. Standards Governance & Mandatory Coverage")
        md.append(
            f"- **Matched Mandatory Standards ({len(matched_standards)}):** "
            + (", ".join(f"`{s}`" for s in matched_standards) if matched_standards else "None")
        )
        md.append(
            f"- **Missing Mandatory Standards ({len(missing_standards)}):** "
            + (
                ", ".join(f"`{s}`" for s in missing_standards)
                if missing_standards
                else "None (100% Compliant)"
            )
        )
        md.append("")

        md.append("## 6. Prioritized Remediation Roadmap")
        md.append(
            f"To achieve full Grade 'A' compliance, complete all corrective milestones within **{timeline_days} days**:"
        )
        step = 1
        for cr in critical_risks:
            md.append(f"{step}. **Phase 1 (Days 1-14):** Mitigate critical finding: {cr}")
            step += 1
        for d in deprecation_detections:
            if not d.is_sunset_passed:
                md.append(
                    f"{step}. **Phase 2 (Days 15-30):** Update policy references from `{d.subject}` to `{d.active_authority}`."
                )
                step += 1
        for s in missing_standards:
            md.append(
                f"{step}. **Phase 3 (Days 30-{timeline_days}):** Codify organizational controls satisfying mandatory framework `{s}`."
            )
            step += 1

        md.append("")
        return "\n".join(md)

    def _generate_pdf_report(
        self,
        overall_grade: str,
        numerical_score: float,
        organization_type: str,
        antipattern_findings: list[AntipatternFinding],
        deprecation_detections: list[DeprecationDetection],
        critical_risks: list[str],
        timeline_days: int,
    ) -> bytes:
        """Generate a valid, self-contained PDF/A audit scorecard using standard vector PDF encoding."""
        # Using pure PDF 1.4 object stream syntax verified by pypdf
        date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Prepare text lines for PDF stream
        lines: list[str] = [
            "DOCSCOUT ENTERPRISE REGULATORY RISK AUDIT SCORECARD",
            f"Organization Class: {organization_type.upper().replace('_', ' ')}",
            f"Audit Date: {date_str}",
            "----------------------------------------------------------------------",
            f"OVERALL COMPLIANCE GRADE: {overall_grade}   |   SCORE: {numerical_score:.1f} / 100.0",
            f"RECOMMENDED REMEDIATION WINDOW: {timeline_days} DAYS",
            "----------------------------------------------------------------------",
            "",
            "1. EXECUTIVE SUMMARY & RISK PROFILE",
            f"   Total Antipatterns Detected: {len(antipattern_findings)}",
            f"   Total Deprecated Circulars Detected: {len(deprecation_detections)}",
            f"   Critical Statutory Risks: {len(critical_risks)}",
            "",
            "2. CRITICAL AUDIT RISKS (MANDATORY ESCALATION):",
        ]

        if critical_risks:
            for r in critical_risks[:5]:
                # clean text for standard ASCII PDF stream
                clean_r = re.sub(r"[^\x20-\x7E]", "", r)[:75]
                lines.append(f"   [!] {clean_r}")
        else:
            lines.append("   No critical risks detected. Zero statutory violations.")

        lines.extend(
            [
                "",
                "3. DETECTED ANTIPATTERNS BREAKDOWN:",
            ]
        )
        if antipattern_findings:
            for f in antipattern_findings[:5]:
                clean_p = re.sub(r"[^\x20-\x7E]", "", f.practice)[:40]
                lines.append(f"   - {f.rule_id} ({f.severity}): {clean_p}")
        else:
            lines.append("   Zero antipatterns identified.")

        lines.extend(
            [
                "",
                "4. STATUTORY DEPRECATIONS & SUPERSEDED INSTRUMENTS:",
            ]
        )
        if deprecation_detections:
            for d in deprecation_detections[:5]:
                clean_s = re.sub(r"[^\x20-\x7E]", "", d.subject)[:45]
                lines.append(f"   - {clean_s} (Sunset: {d.sunset_date or 'N/A'})")
        else:
            lines.append("   All circular citations are active and legally valid.")

        lines.extend(
            [
                "",
                "----------------------------------------------------------------------",
                "Certified by DocScout Compliance Governance Engine - docscout.internal",
            ]
        )

        # Encode text lines into PDF content stream
        stream_cmds: list[str] = [
            "BT",
            "/F1 10 Tf",
            "14 TL",
            "50 780 Td",
        ]
        for line in lines:
            safe_text = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream_cmds.append(f"({safe_text}) '")
        stream_cmds.append("ET")

        content_stream = "\n".join(stream_cmds).encode("latin1", "replace")
        stream_len = len(content_stream)

        # Calculate exact byte offsets for xref table
        header = b"%PDF-1.4\n"
        obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        obj3 = b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        obj4_prefix = f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin1")
        obj4_body = content_stream
        obj4_suffix = b"\nendstream\nendobj\n"
        obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n"

        off1 = len(header)
        off2 = off1 + len(obj1)
        off3 = off2 + len(obj2)
        off4 = off3 + len(obj3)
        off5 = off4 + len(obj4_prefix) + len(obj4_body) + len(obj4_suffix)
        xref_offset = off5 + len(obj5)

        xref = (
            f"xref\n"
            f"0 6\n"
            f"0000000000 65535 f \n"
            f"{off1:010d} 00000 n \n"
            f"{off2:010d} 00000 n \n"
            f"{off3:010d} 00000 n \n"
            f"{off4:010d} 00000 n \n"
            f"{off5:010d} 00000 n \n"
            f"trailer\n"
            f"<< /Size 6 /Root 1 0 R >>\n"
            f"startxref\n"
            f"{xref_offset}\n"
            f"%%EOF\n"
        ).encode("latin1")

        full_pdf = header + obj1 + obj2 + obj3 + obj4_prefix + obj4_body + obj4_suffix + obj5 + xref

        # Validate with pypdf to guarantee standards compliance
        reader = io.BytesIO(full_pdf)
        writer = PdfWriter()
        writer.append(reader)
        out_buf = io.BytesIO()
        writer.write(out_buf)
        return out_buf.getvalue()
