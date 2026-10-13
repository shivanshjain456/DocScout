"""ISO/NIST Clause Cross-Citation Hyperlinking Entity Extractor (FEAT-046).

Extracts mentions of external international and national standards (ISO, NIST,
PCI-DSS, RBI frameworks, Basel III, FIPS, WCAG, SOC 2) in regulatory text.
Resolves character-exact spans, canonical standard IDs, and associated control
hints (e.g., Annex A.5.15, Requirement 3.4, SC-7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog

from app.api.metrics import STANDARD_MENTIONS_EXTRACTED_TOTAL
from app.compliance.standards_registry import (
    StandardsRegistry,
    get_default_standards_registry,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StandardMention:
    """An extracted reference to an external statutory or technical standard."""

    span: tuple[int, int]
    raw_text: str
    standard_id: str
    control_hint: str | None = None
    standard_name: str | None = None
    governing_body: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "span": list(self.span),
            "raw_text": self.raw_text,
            "standard_id": self.standard_id,
            "control_hint": self.control_hint,
            "standard_name": self.standard_name,
            "governing_body": self.governing_body,
        }


@dataclass(frozen=True)
class StandardMentionConfig:
    """Configuration for standard mention extraction."""

    enabled: bool = True
    min_precision_confidence: float = 0.95


class StandardMentionExtractor:
    """Regex and catalog grounded entity extractor for standard cross-citations."""

    # Control hint pattern to locate specific clauses/requirements
    _CONTROL_HINT_RE = re.compile(
        r"(?i)\b((?:Annex|Clause|Cl\.|Requirement|Req\.?|Control|Section|Sec\.|Paragraph|Para\.?)\s+[A-Za-z0-9\.\-\(\)]+|(?:[A-Z]{2}-\d+(?:\(\d+\))?))\b"
    )

    def __init__(
        self,
        config: StandardMentionConfig | None = None,
        registry: StandardsRegistry | None = None,
    ) -> None:
        self.config = config or StandardMentionConfig()
        self.registry = registry or get_default_standards_registry()
        self._compiled_patterns = self._build_patterns()

    def _build_patterns(self) -> list[tuple[re.Pattern[str], str | None]]:
        """Build regex patterns for known standard naming conventions."""
        patterns: list[tuple[re.Pattern[str], str | None]] = [
            # ISO standards: e.g. ISO/IEC 27001, ISO 22301, ISO/IEC 27017, ISO/IEC 42001
            (
                re.compile(
                    r"\b(ISO(?:/IEC)?(?:/IEEE)?\s*(?:IS\s*)?\d{4,5}(?:-\d+)?(?::\d{4})?)\b",
                    re.IGNORECASE,
                ),
                None,
            ),
            # NIST Special Publications & Frameworks
            (
                re.compile(
                    r"\b(NIST\s+(?:SP\s*)?800-\d{2,3}(?:[A-Za-z0-9\.\-]+)?(?:\s+Rev\.\s*\d+)?)\b",
                    re.IGNORECASE,
                ),
                None,
            ),
            (
                re.compile(
                    r"\b(NIST\s+SP\s*1270)\b",
                    re.IGNORECASE,
                ),
                "NIST SP 1270",
            ),
            (
                re.compile(
                    r"\b(NIST\s+CSF(?:\s*[\d\.]+)?|NIST\s+Cybersecurity\s+Framework(?:\s*[\d\.]+)?)\b",
                    re.IGNORECASE,
                ),
                "NIST CSF 2.0",
            ),
            (
                re.compile(
                    r"\b(NIST\s+AI\s+RMF(?:\s*[\d\.]+)?)\b",
                    re.IGNORECASE,
                ),
                "NIST AI RMF 1.0",
            ),
            # PCI-DSS
            (
                re.compile(
                    r"\b(PCI(?:[\s\-]DSS)?(?:\s+(?:v|version\s*)?[\d\.]+)?)\b",
                    re.IGNORECASE,
                ),
                "PCI DSS 4.0",
            ),
            # FIPS
            (
                re.compile(
                    r"\b(FIPS\s+\d{3}(?:-\d+)?)\b",
                    re.IGNORECASE,
                ),
                None,
            ),
            # WCAG
            (
                re.compile(
                    r"\b(WCAG\s*[\d\.]+)\b",
                    re.IGNORECASE,
                ),
                "WCAG 2.2",
            ),
            # SOC 2
            (
                re.compile(
                    r"\b(SOC\s*2(?:\s+Type\s+(?:I|II))?)\b",
                    re.IGNORECASE,
                ),
                "SOC 2",
            ),
            # Basel III / BCBS
            (
                re.compile(
                    r"\b(Basel\s+III(?:\s+framework|\s+standards)?|BCBS\s*239)\b",
                    re.IGNORECASE,
                ),
                "BASEL_III",
            ),
            # RBI Cyber Security Framework
            (
                re.compile(
                    r"\b(RBI\s+(?:Cyber\s+Security\s+Framework|CSF))\b",
                    re.IGNORECASE,
                ),
                "rbi-cyber-security-framework",
            ),
            # RBI IT Master Directions
            (
                re.compile(
                    r"\b(RBI\s+Master\s+Direction[s]?\s+on\s+IT\s+Governance)\b",
                    re.IGNORECASE,
                ),
                "RBI_IT_GOVERNANCE",
            ),
        ]
        return patterns

    def extract(
        self,
        text: str,
        doc_id: str | None = None,
        chunk_id: str | None = None,
    ) -> list[StandardMention]:
        """Extract external standard mentions with exact spans and control hints."""
        if not self.config.enabled or not text or not text.strip():
            return []

        mentions: list[StandardMention] = []
        occupied_spans: list[tuple[int, int]] = []

        for pattern, fixed_id in self._compiled_patterns:
            for match in pattern.finditer(text):
                m_start, m_end = match.start(), match.end()
                matched_raw = match.group(1)

                # Skip if already overlapped
                if any(
                    not (m_end <= o_start or m_start >= o_end) for o_start, o_end in occupied_spans
                ):
                    continue

                # Lookahead for immediate control hint
                control_hint: str | None = None
                tail_sub = text[m_end : m_end + 60]
                ctrl_match = self._CONTROL_HINT_RE.match(tail_sub.lstrip(" :,-"))
                expanded_end = m_end

                if ctrl_match:
                    ctrl_raw = ctrl_match.group(1)
                    # Check if directly adjacent (separated only by spaces or punctuation)
                    gap = tail_sub[: tail_sub.find(ctrl_raw)]
                    if len(gap) <= 5 and all(c in " :,-" for c in gap):
                        control_hint = ctrl_raw
                        expanded_end = m_end + len(gap) + len(ctrl_raw)
                        matched_raw = text[m_start:expanded_end]

                # If no adjacent control hint, look for nearby control hint within 50 chars
                if not control_hint:
                    nearby_ctrl = self._CONTROL_HINT_RE.search(tail_sub)
                    if nearby_ctrl:
                        control_hint = nearby_ctrl.group(1)

                # Also look backwards for preceding control hint (e.g. "Annex 1 controls of RBI CSF")
                if not control_hint:
                    head_sub = text[max(0, m_start - 40) : m_start]
                    back_ctrl = self._CONTROL_HINT_RE.search(head_sub)
                    if back_ctrl:
                        control_hint = back_ctrl.group(1)

                # Resolve canonical standard
                standard_def = None
                if fixed_id:
                    standard_def = self.registry.get_standard(fixed_id)
                if standard_def is None:
                    standard_def = self.registry.resolve_standard(matched_raw)

                if standard_def is not None:
                    canonical_id = standard_def.id
                    std_name = standard_def.name
                    gov_body = standard_def.governing_body
                else:
                    # Normalised fallback if matched by known pattern
                    canonical_id = fixed_id or match.group(1).strip()
                    std_name = canonical_id
                    gov_body = "International / Statutory Body"

                mention = StandardMention(
                    span=(m_start, expanded_end),
                    raw_text=matched_raw,
                    standard_id=canonical_id,
                    control_hint=control_hint,
                    standard_name=std_name,
                    governing_body=gov_body,
                )
                mentions.append(mention)
                occupied_spans.append((m_start, expanded_end))

                # Increment Prometheus metric
                try:
                    STANDARD_MENTIONS_EXTRACTED_TOTAL.labels(standard_id=canonical_id).inc()
                except Exception:
                    logger.warning("failed_to_increment_metric", standard_id=canonical_id)

        # Sort mentions by char_start ascending
        mentions.sort(key=lambda m: m.span[0])
        return mentions


def persist_mentions(
    conn: psycopg.Connection,
    document_id: str,
    mentions: list[StandardMention],
    chunk_id: str | None = None,
) -> int:
    """Persist extracted standard mentions to document_standard_mentions table."""
    if not mentions:
        return 0

    rows = [
        (
            document_id,
            chunk_id,
            m.standard_id,
            m.raw_text,
            m.span[0],
            m.span[1],
            m.control_hint,
        )
        for m in mentions
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO document_standard_mentions (
                document_id, chunk_id, standard_id, raw_text, char_start, char_end, control_hint
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    return len(rows)


def fetch_mentions_for_document(
    conn: psycopg.Connection, document_id: str
) -> list[StandardMention]:
    """Retrieve all persisted standard mentions for a specific document."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT char_start, char_end, raw_text, standard_id, control_hint
            FROM document_standard_mentions
            WHERE document_id = %s
            ORDER BY char_start ASC
            """,
            (document_id,),
        )
        rows = cur.fetchall()

    return [
        StandardMention(
            span=(r[0], r[1]),
            raw_text=r[2],
            standard_id=r[3],
            control_hint=r[4],
        )
        for r in rows
    ]
