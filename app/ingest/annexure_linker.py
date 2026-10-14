"""Annexure, Schedule & FAQ Relational Association (FEAT-066).

Detects and preserves relational hierarchies between primary statutory circulars
and their subsidiary technical annexures, schedules, appendices, and explanatory FAQs.

Ensures procedural guidelines and compliance reporting templates in annexures are
reliably linked to primary policy obligations for cross-section retrieval expansion.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
import structlog

from app.api.metrics import ANNEXURES_LINKED_TOTAL

logger = structlog.get_logger(__name__)

SectionType = Literal["MAIN", "ANNEXURE", "SCHEDULE", "FAQ", "APPENDIX"]
RelationshipType = Literal["ANNEXURE", "SCHEDULE", "FAQ", "APPENDIX"]


@dataclass
class DocumentSection:
    """Represents a structural division within a regulatory document."""

    section_id: str
    section_identifier: str
    section_title: str
    section_type: SectionType
    char_start: int
    char_end: int
    document_id: str | None = None
    version_id: str | None = None
    parent_section_id: str | None = None


@dataclass
class SectionRelationship:
    """Relational parent-child link between policy directives and subsidiary instruments."""

    parent_section_id: str
    child_section_id: str
    relationship_type: RelationshipType
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnnexureLinkerConfig:
    """Configuration toggles for automatic relational linking."""

    auto_link_faqs: bool = True
    auto_link_annexures: bool = True
    auto_link_schedules: bool = True
    auto_link_appendices: bool = True


# ==============================================================================
# Compiled Section Header Patterns
# ==============================================================================

UNIFIED_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"(?P<ANNEXURE>ANNEX(?:URE)?(?:\s+([0-9IVXLCDM]+|[A-Z]))?(?:\s*[:\-\.]\s*([^\n\r]+))?)|"
    r"(?P<SCHEDULE>(?:SCHEDULE\s+([0-9IVXLCDM]+|[A-Z])|(?:FIRST|SECOND|THIRD|FOURTH|FIFTH)\s+SCHEDULE)(?:\s*[:\-\.]\s*([^\n\r]+))?)|"
    r"(?P<FAQ>(?:FREQUENTLY\s+ASKED\s+QUESTIONS|FAQs?|CLARIFICATORY\s+FAQs?)(?:\s*[:\-\.]\s*([^\n\r]+))?)|"
    r"(?P<APPENDIX>APPENDIX(?:\s+([0-9IVXLCDM]+|[A-Z]))?(?:\s*[:\-\.]\s*([^\n\r]+))?)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


class AnnexureLinker:
    """High-performance structural section parser and relational association engine."""

    def __init__(self, config: AnnexureLinkerConfig | None = None) -> None:
        self.config = config or AnnexureLinkerConfig()

    def detect_sections(
        self,
        text: str,
        document_id: str | None = None,
        version_id: str | None = None,
    ) -> list[DocumentSection]:
        """Parse text for structural section headers and delimit character spans.

        Guarantees that the root circular body is delimited as section 'MAIN'.
        """
        if not text or not text.strip():
            return []

        doc_len = len(text)
        matches: list[dict[str, Any]] = []

        # Single high-performance C-level regex pass over text
        for m in UNIFIED_HEADING_RE.finditer(text):
            m_type = m.lastgroup or "ANNEXURE"
            raw_m = m.group(0).strip()
            if ":" in raw_m:
                parts = raw_m.split(":", 1)
                ident = parts[0].strip()
                title = parts[1].strip()
            elif "-" in raw_m:
                parts = raw_m.split("-", 1)
                ident = parts[0].strip()
                title = parts[1].strip()
            else:
                ident = raw_m
                title = raw_m if m_type != "FAQ" else "Frequently Asked Questions"

            # Normalize canonical identifier for standard matching
            if m_type == "FAQ":
                ident = "Frequently Asked Questions"

            matches.append(
                {
                    "start": m.start(),
                    "type": m_type,
                    "identifier": ident,
                    "title": title,
                }
            )

        sections: list[DocumentSection] = []

        # If no subsidiary headings found, entire text is MAIN
        if not matches:
            main_sec = DocumentSection(
                section_id=str(uuid.uuid4()),
                section_identifier="MAIN",
                section_title="Primary Circular Directives",
                section_type="MAIN",
                char_start=0,
                char_end=doc_len,
                document_id=document_id,
                version_id=version_id,
                parent_section_id=None,
            )
            return [main_sec]

        # Create root MAIN section from index 0 to first matched boundary
        first_start = matches[0]["start"]
        main_id = str(uuid.uuid4())
        sections.append(
            DocumentSection(
                section_id=main_id,
                section_identifier="MAIN",
                section_title="Primary Circular Directives",
                section_type="MAIN",
                char_start=0,
                char_end=first_start,
                document_id=document_id,
                version_id=version_id,
                parent_section_id=None,
            )
        )

        # Build subsidiary sections
        for i, curr in enumerate(matches):
            sec_start = curr["start"]
            sec_end = matches[i + 1]["start"] if (i + 1 < len(matches)) else doc_len
            sections.append(
                DocumentSection(
                    section_id=str(uuid.uuid4()),
                    section_identifier=curr["identifier"],
                    section_title=curr["title"] or curr["identifier"],
                    section_type=curr["type"],
                    char_start=sec_start,
                    char_end=sec_end,
                    document_id=document_id,
                    version_id=version_id,
                    parent_section_id=main_id,
                )
            )

        return sections

    def link_sections(
        self,
        sections: list[DocumentSection],
        config: AnnexureLinkerConfig | None = None,
    ) -> list[SectionRelationship]:
        """Establish directed parent-child relationships from MAIN to subsidiary sections."""
        cfg = config or self.config
        if not sections:
            return []

        # Find main parent section
        main_sec = next((s for s in sections if s.section_type == "MAIN"), None)
        if not main_sec:
            return []

        relationships: list[SectionRelationship] = []

        for sec in sections:
            if sec.section_type == "MAIN":
                continue

            rel_type: RelationshipType | None = None
            if sec.section_type == "ANNEXURE" and cfg.auto_link_annexures:
                rel_type = "ANNEXURE"
            elif sec.section_type == "SCHEDULE" and cfg.auto_link_schedules:
                rel_type = "SCHEDULE"
            elif sec.section_type == "FAQ" and cfg.auto_link_faqs:
                rel_type = "FAQ"
            elif sec.section_type == "APPENDIX" and cfg.auto_link_appendices:
                rel_type = "APPENDIX"

            if rel_type is not None:
                relationships.append(
                    SectionRelationship(
                        parent_section_id=main_sec.section_id,
                        child_section_id=sec.section_id,
                        relationship_type=rel_type,
                        metadata={
                            "child_identifier": sec.section_identifier,
                            "child_title": sec.section_title,
                            "char_start": sec.char_start,
                            "char_end": sec.char_end,
                        },
                    )
                )
                try:
                    ANNEXURES_LINKED_TOTAL.labels(type=rel_type).inc()
                except Exception as m_err:
                    logger.debug("annexure_linker.metric_error", error=str(m_err))

        return relationships

    def process_document(
        self,
        text: str,
        document_id: str | None = None,
        version_id: str | None = None,
        config: AnnexureLinkerConfig | None = None,
    ) -> tuple[list[DocumentSection], list[SectionRelationship]]:
        """Convenience method to detect sections and generate relational links."""
        sections = self.detect_sections(text, document_id=document_id, version_id=version_id)
        relationships = self.link_sections(sections, config=config)
        return sections, relationships

    def save_sections_and_relationships(
        self,
        conn: psycopg.Connection[Any],
        document_id: str,
        version_id: str,
        sections: list[DocumentSection],
        relationships: list[SectionRelationship],
    ) -> None:
        """Persist sections and relationships into PostgreSQL schema."""
        with conn.cursor() as cur:
            # Upsert sections
            for sec in sections:
                cur.execute(
                    """
                    INSERT INTO document_sections (
                        section_id, document_id, version_id, section_identifier,
                        section_title, section_type, char_start, char_end, parent_section_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (section_id) DO UPDATE SET
                        section_identifier = EXCLUDED.section_identifier,
                        section_title = EXCLUDED.section_title,
                        char_start = EXCLUDED.char_start,
                        char_end = EXCLUDED.char_end,
                        parent_section_id = EXCLUDED.parent_section_id
                    """,
                    (
                        sec.section_id,
                        document_id,
                        version_id,
                        sec.section_identifier,
                        sec.section_title,
                        sec.section_type,
                        sec.char_start,
                        sec.char_end,
                        sec.parent_section_id,
                    ),
                )

            # Insert relationships
            for rel in relationships:
                cur.execute(
                    """
                    INSERT INTO section_relationships (
                        document_id, version_id, parent_section_id,
                        child_section_id, relationship_type, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (parent_section_id, child_section_id, relationship_type)
                    DO UPDATE SET
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        document_id,
                        version_id,
                        rel.parent_section_id,
                        rel.child_section_id,
                        rel.relationship_type,
                        json.dumps(rel.metadata),
                    ),
                )

    def get_document_relationships(
        self,
        conn: psycopg.Connection[Any],
        document_id: str,
    ) -> list[SectionRelationship]:
        """Fetch all stored section relationships for a document."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT parent_section_id, child_section_id, relationship_type, metadata
                FROM section_relationships
                WHERE document_id = %s
                ORDER BY created_at ASC
                """,
                (document_id,),
            )
            rows = cur.fetchall()

        results: list[SectionRelationship] = []
        for row in rows:
            meta = row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}")
            results.append(
                SectionRelationship(
                    parent_section_id=str(row[0]),
                    child_section_id=str(row[1]),
                    relationship_type=row[2],
                    metadata=meta,
                )
            )
        return results

    def get_document_sections(
        self,
        conn: psycopg.Connection[Any],
        document_id: str,
    ) -> list[DocumentSection]:
        """Fetch all sections belonging to a document ordered by start offset."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT section_id, document_id, version_id, section_identifier,
                       section_title, section_type, char_start, char_end, parent_section_id
                FROM document_sections
                WHERE document_id = %s
                ORDER BY char_start ASC
                """,
                (document_id,),
            )
            rows = cur.fetchall()

        sections: list[DocumentSection] = []
        for r in rows:
            sections.append(
                DocumentSection(
                    section_id=str(r[0]),
                    document_id=str(r[1]) if r[1] else None,
                    version_id=str(r[2]) if r[2] else None,
                    section_identifier=r[3],
                    section_title=r[4],
                    section_type=r[5],
                    char_start=r[6],
                    char_end=r[7],
                    parent_section_id=str(r[8]) if r[8] else None,
                )
            )
        return sections


_DEFAULT_LINKER: AnnexureLinker | None = None


def get_default_annexure_linker() -> AnnexureLinker:
    """Return default singleton instance of AnnexureLinker."""
    global _DEFAULT_LINKER
    if _DEFAULT_LINKER is None:
        _DEFAULT_LINKER = AnnexureLinker()
    return _DEFAULT_LINKER


def link_annexures_and_schedules(
    text: str,
    document_id: str | None = None,
    version_id: str | None = None,
    config: AnnexureLinkerConfig | None = None,
) -> tuple[list[DocumentSection], list[SectionRelationship]]:
    """Convenience helper to parse and link document sections."""
    linker = AnnexureLinker(config) if config else get_default_annexure_linker()
    return linker.process_document(
        text, document_id=document_id, version_id=version_id, config=config
    )
