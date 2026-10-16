"""Automated Regulatory Metadata and Notification ID Extractor (FEAT-069).

Extracts circular reference numbers (e.g., 'RBI/2026-27/273', 'SEBI/HO/DDHS/...'),
department names ('Department of Regulation'), subject lines, publication dates, and
signoff authority names from official Indian regulatory publications.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog

from app.api.metrics import METADATA_FIELDS_EXTRACTED_TOTAL

logger = structlog.get_logger(__name__)

# Minimum characters required for valid metadata extraction (FEAT-069 specification)
MIN_METADATA_TEXT_LENGTH = 100

# Compiled statutory circular identifier patterns
_RE_RBI_CIRCULAR = re.compile(
    r"\b(RBI\/\d{4}-(?:20)?\d{2,4}\/\d+)\b",
    re.IGNORECASE,
)

_RE_FEMA_NOTI = re.compile(
    r"\b(?:Notification\s+No\.\s+)?(FEMA\s+\d+\(R\)\/(?:\([0-9]+\)\/)?\d{4}-RB)\b",
    re.IGNORECASE,
)

_RE_AP_DIR_CIRCULAR = re.compile(
    r"\b(A\.P\.\s*\(DIR\s+Series\)\s+Circular\s+No\.\s+\d+)\b",
    re.IGNORECASE,
)

_RE_SEBI_HO = re.compile(
    r"\b(SEBI\/HO\/[A-Za-z0-9_\-\/]+)\b",
    re.IGNORECASE,
)

_RE_SEBI_CIRCULAR_CODE = re.compile(
    r"\b(?:CIRCULAR\s+)?(HO\/[A-Za-z0-9_\-\/\(\)\s]+?\/\s*[I1]\/\d+\/\d{4})\b",
    re.IGNORECASE,
)


_RE_SEBI_CIR = re.compile(
    r"\b(CIR\/[A-Za-z0-9_\-\/]+)\b",
    re.IGNORECASE,
)

_RE_RBI_DEPT_CIRCULAR = re.compile(
    r"\b((?:DOR|DCM|FIDD|DoS|DOS|FED|DPSS)[A-Za-z0-9\.\s\(\)_\-\/]+?No\.[A-Za-z0-9\.\-\/\(\)\s]+?\d{4}-\d{2,4})\b",
    re.IGNORECASE,
)

# Department patterns (full name)
_DEPARTMENT_PATTERNS = [
    (re.compile(r"Department\s+of\s+Regulation", re.IGNORECASE), "Department of Regulation"),
    (
        re.compile(r"Department\s+of\s+Currency\s+Management", re.IGNORECASE),
        "Department of Currency Management",
    ),
    (
        re.compile(r"Foreign\s+Exchange\s+Department", re.IGNORECASE),
        "Foreign Exchange Department",
    ),
    (
        re.compile(r"Department\s+of\s+Information\s+Technology", re.IGNORECASE),
        "Department of Information Technology",
    ),
    (
        re.compile(r"Financial\s+Inclusion\s+and\s+Development\s+Department", re.IGNORECASE),
        "Financial Inclusion and Development Department",
    ),
    (
        re.compile(r"Department\s+of\s+Debt\s+and\s+Hybrid\s+Securities", re.IGNORECASE),
        "Department of Debt and Hybrid Securities",
    ),
    (
        re.compile(r"Investment\s+Management\s+Department", re.IGNORECASE),
        "Investment Management Department",
    ),
    (
        re.compile(r"Corporation\s+Finance\s+Department", re.IGNORECASE),
        "Corporation Finance Department",
    ),
    (
        re.compile(r"Market\s+Regulation\s+Department", re.IGNORECASE),
        "Market Regulation Department",
    ),
    (
        re.compile(r"Office\s+of\s+Investor\s+Assistance\s+and\s+Education", re.IGNORECASE),
        "Office of Investor Assistance and Education",
    ),
    (
        re.compile(
            r"Alternative\s+Investment\s+Fund\s+and\s+Foreign\s+Portfolio\s+Investors\s+Department",
            re.IGNORECASE,
        ),
        "Alternative Investment Fund and Foreign Portfolio Investors Department",
    ),
    (
        re.compile(
            r"Market\s+Intermediaries\s+Regulation\s+and\s+Supervision\s+Department",
            re.IGNORECASE,
        ),
        "Market Intermediaries Regulation and Supervision Department",
    ),
    (
        re.compile(r"Department\s+of\s+Supervision", re.IGNORECASE),
        "Department of Supervision",
    ),
    (
        re.compile(r"Department\s+of\s+Payment\s+and\s+Settlement\s+Systems", re.IGNORECASE),
        "Department of Payment and Settlement Systems",
    ),
]

# Department patterns (acronym fallback)
_ACRONYM_DEPARTMENTS = [
    (re.compile(r"\b(DOR|DoR)\b"), "Department of Regulation"),
    (re.compile(r"\b(DCM)\b"), "Department of Currency Management"),
    (re.compile(r"\b(FED|FEMA)\b"), "Foreign Exchange Department"),
    (re.compile(r"\b(FIDD)\b"), "Financial Inclusion and Development Department"),
    (re.compile(r"\b(DoS|DOS)\b"), "Department of Supervision"),
    (re.compile(r"\b(DDHS)\b"), "Department of Debt and Hybrid Securities"),
    (re.compile(r"\b(IMD)\b"), "Investment Management Department"),
    (re.compile(r"\b(CFD)\b"), "Corporation Finance Department"),
    (re.compile(r"\b(MRD)\b"), "Market Regulation Department"),
    (re.compile(r"\b(MIRSD)\b"), "Market Intermediaries Regulation and Supervision Department"),
    (
        re.compile(r"\b(AFD)\b"),
        "Alternative Investment Fund and Foreign Portfolio Investors Department",
    ),
    (re.compile(r"\b(ITD)\b"), "Information Technology Department"),
    (re.compile(r"\b(OIAE)\b"), "Office of Investor Assistance and Education"),
    (
        re.compile(r"A\.P\.\s*\(DIR\s+Series\)", re.IGNORECASE),
        "Foreign Exchange Department",
    ),
]


# Date patterns in regulatory header
_DATE_PATTERNS = [
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2})[\.\/\-](\d{1,2})[\.\/\-](\d{4})\b"),
]

_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_TITLE_HIERARCHY_RE = re.compile(
    r"(Chief\s+General\s+Manager(?:-in-Charge)?|Deputy\s+General\s+Manager|Assistant\s+General\s+Manager|General\s+Manager|Executive\s+Director)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MetadataExtractorConfig:
    """Configuration for automated regulatory metadata extraction."""

    strict_pattern_matching: bool = True


@dataclass(frozen=True)
class DocumentMetadata:
    """Structured administrative metadata extracted from regulatory text."""

    circular_no: str | None = None
    department: str | None = None
    subject: str | None = None
    date_issued: date | None = None
    signoff_officer: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary with serialized date."""
        return {
            "circular_no": self.circular_no,
            "department": self.department,
            "subject": self.subject,
            "date_issued": self.date_issued.isoformat() if self.date_issued else None,
            "signoff_officer": self.signoff_officer,
        }


class RegulatoryMetadataExtractor:
    """High-speed layout and regex metadata extractor for official gazette documents."""

    def __init__(self, config: MetadataExtractorConfig | None = None) -> None:
        self.config = config or MetadataExtractorConfig()

    def extract(self, text: str, filename: str = "") -> DocumentMetadata:
        """Extract structured administrative metadata from document text and optional filename."""
        if len(text.strip()) < MIN_METADATA_TEXT_LENGTH:
            raise ValueError(
                f"Document text length ({len(text.strip())}) is less than required minimum ({MIN_METADATA_TEXT_LENGTH} chars)"
            )

        header = text[:4000]

        # 1. Circular number extraction
        circular_no = self._extract_circular_no(header, filename=filename)

        # 2. Department extraction
        department = self._extract_department(header, circular_no=circular_no, filename=filename)

        # 3. Date issued extraction
        date_issued = self._extract_date_issued(header)

        # 4. Subject line extraction
        subject = self._extract_subject(header)

        # 5. Signoff officer extraction
        signoff_officer = self._extract_signoff_officer(text)

        # Observability accounting
        if circular_no:
            METADATA_FIELDS_EXTRACTED_TOTAL.labels(field_name="circular_no").inc()
        if department:
            METADATA_FIELDS_EXTRACTED_TOTAL.labels(field_name="department").inc()
        if subject:
            METADATA_FIELDS_EXTRACTED_TOTAL.labels(field_name="subject").inc()
        if date_issued:
            METADATA_FIELDS_EXTRACTED_TOTAL.labels(field_name="date_issued").inc()
        if signoff_officer:
            METADATA_FIELDS_EXTRACTED_TOTAL.labels(field_name="signoff_officer").inc()

        if circular_no is None or department is None:
            logger.warning(
                "regulatory_metadata_unresolved",
                circular_no=circular_no,
                department=department,
                filename=filename,
            )

        return DocumentMetadata(
            circular_no=circular_no,
            department=department,
            subject=subject,
            date_issued=date_issued,
            signoff_officer=signoff_officer,
        )

    def _extract_circular_no(self, header: str, filename: str = "") -> str | None:
        # Check canonical patterns in order of specificity
        if m := _RE_RBI_CIRCULAR.search(header):
            return m.group(1).strip()
        if m := _RE_SEBI_HO.search(header):
            return m.group(1).strip()
        if m := _RE_SEBI_CIRCULAR_CODE.search(header):
            return m.group(1).strip()
        if m := _RE_FEMA_NOTI.search(header):
            return m.group(1).strip()
        if m := _RE_AP_DIR_CIRCULAR.search(header):
            return m.group(1).strip()
        if m := _RE_SEBI_CIR.search(header):
            return m.group(1).strip()
        if m := _RE_RBI_DEPT_CIRCULAR.search(header):
            return " ".join(m.group(1).split())

        # Fallback to filename patterns if not in strict pattern matching mode
        if not self.config.strict_pattern_matching and filename:
            if m := _RE_RBI_CIRCULAR.search(filename):
                return m.group(1).strip()
            if m := _RE_SEBI_HO.search(filename):
                return m.group(1).strip()

        return None

    def _extract_department(
        self, header: str, circular_no: str | None = None, filename: str = ""
    ) -> str | None:
        # First match full statutory department name
        for pattern, dept_name in _DEPARTMENT_PATTERNS:
            if pattern.search(header):
                return dept_name

        # Second match from circular identifier or header acronym
        if circular_no:
            for pattern, dept_name in _ACRONYM_DEPARTMENTS:
                if pattern.search(circular_no):
                    return dept_name

        for pattern, dept_name in _ACRONYM_DEPARTMENTS:
            if pattern.search(header[:1500]):
                return dept_name

        # Fallback to filename if allowed
        if not self.config.strict_pattern_matching and filename:
            for pattern, dept_name in _ACRONYM_DEPARTMENTS:
                if pattern.search(filename):
                    return dept_name

        return None

    def _extract_date_issued(self, header: str) -> date | None:
        for pattern in _DATE_PATTERNS:
            dm = pattern.search(header)
            if not dm:
                continue
            groups = dm.groups()
            try:
                if groups[0].lower() in _MONTH_MAP:
                    m_num = _MONTH_MAP[groups[0].lower()]
                    d_num = int(groups[1])
                    y_num = int(groups[2])
                    return date(y_num, m_num, d_num)
                if groups[1].lower() in _MONTH_MAP:
                    d_num = int(groups[0])
                    m_num = _MONTH_MAP[groups[1].lower()]
                    y_num = int(groups[2])
                    return date(y_num, m_num, d_num)
                d_num = int(groups[0])
                m_num = int(groups[1])
                y_num = int(groups[2])
                return date(y_num, m_num, d_num)
            except (ValueError, KeyError):
                continue
        return None

    def _extract_subject(self, header: str) -> str | None:
        # 1. Explicit Subject: / Sub: pattern
        subj_match = re.search(
            r"(?:Subject|Sub|Sub\.)\s*:\s*(.+?)(?=\n\s*(?:1\.|Dear|To,|Yours|This|Please)|\r|\Z)",
            header,
            re.DOTALL | re.IGNORECASE,
        )
        if subj_match:
            subject = " ".join(subj_match.group(1).split())
            for delim in [" 1. ", " 2. ", " Madam", " Dear"]:
                if delim in subject:
                    subject = subject.split(delim)[0].strip()
            return subject

        # 2. Madam / Dear Sir pattern
        alt_subj = re.search(
            r"(?:Madam\s*\/\s*Dear\s+Sir|Dear\s+Sir\s*\/\s*Madam|Madam\/Sir)[,\s]+(.+?)(?=\nPlease\s+refer|\s+Please\s+refer|\nIn\s+pursuance|\s+In\s+pursuance|\n1\.|\s+1\.)",
            header,
            re.DOTALL | re.IGNORECASE,
        )
        if alt_subj:
            return " ".join(alt_subj.group(1).split())

        # 3. Direct document caption following date
        alt2 = re.search(
            r"(?:September|October|August|July|June|May|April|March|February|January)\s+\d{1,2},\s+\d{4}\s+(?:The\s+Chairman|All\s+|To\b)?.*?(?:Madam\s*\/\s*Dear\s+Sir|Madam\/Sir)?\s*(Master\s+Direction\s*(?:[-:]|\s+on|\s+for).+?|Master\s+Circular\s*(?:[-:]|\s+on|\s+for).+?|Guidelines\s+on\s+.+?|Framework\s+for\s+.+?|Scale\s+Based\s+Regulation.+?|SEBI\s*\(LODR\)\s*Regulations.+?|Online\s+Dispute\s+Resolution.+?)(?=\s+1\.|\n1\.)",
            header,
            re.DOTALL | re.IGNORECASE,
        )

        if alt2:
            return " ".join(alt2.group(1).split())

        return None

    def _extract_signoff_officer(self, text: str) -> str | None:
        # Search for Yours faithfully across the document
        yf_matches = list(re.finditer(r"(?:Yours\s+faithfully|Yours\s+Faithfully)", text))
        for m in yf_matches:
            snippet = text[m.start() : m.start() + 250]
            tm = _TITLE_HIERARCHY_RE.search(snippet)
            if tm:
                title = " ".join(tm.group(1).split())
                before = snippet[: tm.start()]
                # Check for parenthesized name first
                parens = re.findall(r"\(([A-Za-z\.\s]+?)\)", before)
                if parens:
                    name = parens[-1].strip()
                    return f"{name} ({title})"
                # Strip Yours faithfully prefix
                clean_before = re.sub(
                    r"^(?:Yours\s+faithfully|Yours\s+Faithfully)[,\s:]*",
                    "",
                    before,
                    flags=re.IGNORECASE,
                ).strip()
                # Remove non-ascii or non-latin prefix tokens
                clean_before = re.sub(r"^[^\w\s]+", "", clean_before).strip()
                names = re.findall(r"\b([A-Z][a-zA-Z\.]*(?:\s+[A-Z][a-zA-Z\.]*)+)\b", clean_before)
                if names:
                    return f"{names[-1].strip()} ({title})"
                if clean_before:
                    return f"{clean_before} ({title})"
                return title

        # Fallback: check closing signature block in the last 1500 chars if Yours faithfully absent
        tail = text[-1500:]
        if tm_tail := _TITLE_HIERARCHY_RE.search(tail):
            title = " ".join(tm_tail.group(1).split())
            before_tail = tail[: tm_tail.start()]
            parens = re.findall(r"\(([A-Za-z\.\s]+?)\)", before_tail)
            if parens:
                return f"{parens[-1].strip()} ({title})"
            names = re.findall(r"\b([A-Z][a-zA-Z\.]*(?:\s+[A-Z][a-zA-Z\.]*)+)\b", before_tail)
            if names:
                return f"{names[-1].strip()} ({title})"

        return None


def extract_regulatory_metadata(
    text: str, filename: str = "", config: MetadataExtractorConfig | None = None
) -> DocumentMetadata:
    """Convenience helper to extract structured regulatory metadata."""
    extractor = RegulatoryMetadataExtractor(config=config)
    return extractor.extract(text, filename=filename)
