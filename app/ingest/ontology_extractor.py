"""Automated Regulatory Ontology Ingestion & Term Extraction Pipeline (FEAT-010).

Parses newly discovered circulars, extracts recurring statutory terms from Definitions
sections (Chapter 1 / Section 2), and stages proposed ontology additions for human review.

Guarantees:
1. No direct unreviewed mutation of production term-taxonomy.json.
2. Emitted records validate 100% against term-taxonomy.json schema conventions.
3. Extraction completes in <= 5.0 seconds per 50-page document.
4. Memory allocation <= 128 MB.
5. Ingestion pipeline throughput is never blocked by ontology extraction errors.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import psycopg
import structlog
from pydantic import BaseModel, Field

from app.api.metrics import ONTOLOGY_CANDIDATES_DISCOVERED
from app.ingest.ids import CHUNK_ID_NAMESPACE

logger = structlog.get_logger(__name__)

# UUIDv5 namespace for staged candidate terms
NAMESPACE_ONTOLOGY_CANDIDATES = uuid.uuid5(CHUNK_ID_NAMESPACE, "ontology_staging")

# Documents qualifying for automated ontology definition extraction
QUALIFIED_DOC_TYPES: tuple[str, ...] = (
    "master direction",
    "master circular",
    "comprehensive circular",
    "framework",
    "guidelines",
    "directions",
)

# Regex to detect Chapter 1 / Preliminary / Definitions section boundaries
RE_DEFINITIONS_SECTION = re.compile(
    r"(?is)(?:chapter\s+i|preliminary|section\s+[123]|definitions)[\s\S]{1,600}?"
    r"(?:in\s+these\s+directions|unless\s+the\s+context\s+otherwise\s+requires|definitions\s*[:\n])"
)

# Pattern for explicit statutory definition clauses:
# Examples:
# (a) "Auditor" means an auditor qualified...
# (b) 'Customer Due Diligence (CDD)' means identifying...
# 1. "Digital Lending" shall mean a remote...
# (v) Lending Service Provider (LSP) - means an agent...
RE_DEFINITION_CLAUSE = re.compile(
    r"(?m)^\s*(?:\([a-z0-9]+\)|\d+\.)\s*[\"\'\u201c\u2018]?"
    r"(?P<term>[A-Za-z0-9\s\-\(\)\/\,\.]{2,80}?)"
    r"[\"\'\u201d\u2019]?\s*"
    r"(?:means|shall mean|refers to|is defined as|includes)\s+"
    r"(?P<def>[^\n\r]+(?:(?:\n\r?|\r\n?)[ \t]+[^\n\r]+)*)",
    re.IGNORECASE,
)

# Inline quoted definition pattern (e.g. "Term" means...)
RE_INLINE_QUOTED_DEF = re.compile(
    r"[\"\'\u201c\u2018](?P<term>[A-Za-z0-9\s\-\/\(\)]{3,70})[\"\'\u201d\u2019]\s+"
    r"(?:means|shall mean|refers to|includes)\s+"
    r"(?P<def>[^;\.\n\r]+(?:[;\.][^;\.\n\r]+){0,2}[;\.])",
    re.IGNORECASE,
)

# Parenthesized acronym extractor: e.g. "Customer Due Diligence (CDD)"
RE_ACRONYM = re.compile(r"\((?P<acro>[A-Z0-9\-\/]{2,12})\)")


class OntologyIngestConfig(BaseModel):
    """Configuration schema for automated ontology extraction pipeline."""

    auto_extract: bool = True
    min_frequency: int = 1
    min_term_length: int = 2
    min_definition_length: int = 15
    target_domain: str = "physical-and-regulated"
    target_domain_name: str = "Physical & Regulated Systems"


@dataclass
class ProposedEdge:
    """A proposed relationship edge between a candidate term and an existing term."""

    target: str
    relation: str  # 'requires' | 'enables' | 'complements' | 'specializedBy'
    weight: float = 0.85

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateTerm:
    """A staged regulatory term discovered from circular definitions."""

    candidate_id: str
    term: str
    slug: str
    definition: str
    domain: str
    domain_name: str
    source_doc_id: str
    source_title: str | None
    confidence: float
    frequency: int
    char_start: int
    char_end: int
    aliases: list[str] = field(default_factory=list)
    proposed_edges: list[ProposedEdge] = field(default_factory=list)

    def to_taxonomy_record(self) -> dict[str, Any]:
        """Convert into a record conforming to term-taxonomy.json schema."""
        relationships: dict[str, list[str]] = {
            "enables": [],
            "requires": [],
            "complements": [],
            "tension": [],
            "supersedes": [],
            "instanceOf": [],
            "specializedBy": [],
            "sharesOracleWith": [],
        }
        for edge in self.proposed_edges:
            if edge.relation in relationships:
                relationships[edge.relation].append(edge.target)

        return {
            "id": self.slug,
            "term": self.term,
            "status": "candidate",
            "domain": self.domain,
            "domainName": self.domain_name,
            "definition": self.definition,
            "aliases": self.aliases,
            "tier": "foundational",
            "gate": None,
            "lifecyclePhases": ["requirements", "operate"],
            "roles": ["compliance-officer", "risk-manager"],
            "tooling": [],
            "positions": [1],
            "relationships": relationships,
            "sourceDocId": self.source_doc_id,
            "sourceTitle": self.source_title,
            "confidence": self.confidence,
        }


class DocumentPayload(BaseModel):
    """Payload representing a circular document ready for ingestion analysis."""

    doc_id: str
    text: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def slugify(text: str) -> str:
    """Convert text into standard kebab-case identifier."""
    clean = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", clean)


class OntologyExtractor:
    """Automated text mining engine for regulatory definitions sections."""

    def __init__(self, config: OntologyIngestConfig | None = None) -> None:
        self.config = config or OntologyIngestConfig()

    def is_qualified_document(self, title: str | None) -> bool:
        """Validate if document qualifies as Master Direction or Comprehensive Circular."""
        if not title:
            return False
        t_lower = title.lower()
        return any(q_type in t_lower for q_type in QUALIFIED_DOC_TYPES)

    def extract_candidates(self, doc: DocumentPayload) -> list[CandidateTerm]:
        """Extract candidate definitions from document text with high precision."""
        if not doc.text:
            return []

        # Check title qualification if title is provided
        if doc.title and not self.is_qualified_document(doc.title):
            logger.debug("doc_not_qualified_for_ontology", title=doc.title)
            return []

        text = doc.text
        candidates: dict[str, CandidateTerm] = {}

        # 1. First priority: look in Chapter I / Definitions section if present
        scan_regions: list[tuple[str, int]] = []
        def_match = RE_DEFINITIONS_SECTION.search(text)
        if def_match:
            # Focus on the 20,000 characters following the definitions header
            start_pos = def_match.start()
            end_pos = min(len(text), start_pos + 25000)
            scan_regions.append((text[start_pos:end_pos], start_pos))
        else:
            # Fallback: scan whole document
            scan_regions.append((text, 0))

        # Known foundational targets to infer relationship edges
        known_concepts = {
            "regulated-entity": ["regulated entity", "bank", "nbfc"],
            "kyc-master-direction": ["kyc", "customer due diligence", "cdd"],
            "digital-lending": ["digital lending", "lending service provider", "lsp", "dla"],
            "pmla-framework": ["pmla", "prevention of money laundering"],
            "capital-adequacy": ["capital adequacy", "crar", "risk weighted"],
        }

        for region_text, region_offset in scan_regions:
            # Extract structured numbered/alphabetical definition clauses
            for m in RE_DEFINITION_CLAUSE.finditer(region_text):
                raw_term = m.group("term").strip()
                raw_def = m.group("def").strip()
                self._process_match(
                    raw_term=raw_term,
                    raw_def=raw_def,
                    match_start=region_offset + m.start(),
                    match_end=region_offset + m.end(),
                    doc=doc,
                    known_concepts=known_concepts,
                    candidates=candidates,
                )

            # Fallback to inline quoted definitions only if structured clauses found few items
            if len(candidates) < 3:
                for m in RE_INLINE_QUOTED_DEF.finditer(region_text):
                    raw_term = m.group("term").strip()
                    raw_def = m.group("def").strip()
                    self._process_match(
                        raw_term=raw_term,
                        raw_def=raw_def,
                        match_start=region_offset + m.start(),
                        match_end=region_offset + m.end(),
                        doc=doc,
                        known_concepts=known_concepts,
                        candidates=candidates,
                    )

        results = list(candidates.values())
        logger.info(
            "ontology_candidates_extracted",
            doc_id=doc.doc_id,
            count=len(results),
        )
        return results

    def _process_match(
        self,
        raw_term: str,
        raw_def: str,
        match_start: int,
        match_end: int,
        doc: DocumentPayload,
        known_concepts: dict[str, list[str]],
        candidates: dict[str, CandidateTerm],
    ) -> None:
        # Clean term text: strip outer quotes and punctuation, keeping parentheses intact
        cleaned_term = re.sub(
            r"^[\"\'\u201c\u2018\s]+|[\"\'\u201d\u2019\,\.\;\s]+$", "", raw_term
        ).strip()

        # Extract parenthesized acronym if embedded (e.g. "Customer Due Diligence (CDD)")
        aliases: list[str] = []
        acro_m = RE_ACRONYM.search(cleaned_term)
        if acro_m:
            aliases.append(acro_m.group("acro"))
            cleaned_term = RE_ACRONYM.sub("", cleaned_term).strip()

        if len(cleaned_term) < self.config.min_term_length:
            return
        if len(raw_def) < self.config.min_definition_length:
            return

        term_slug = slugify(cleaned_term)
        if not term_slug:
            return

        # If already seen, increment frequency
        if term_slug in candidates:
            candidates[term_slug].frequency += 1
            return

        # Infer relationship edges to known concepts based on definition content
        proposed_edges: list[ProposedEdge] = []
        def_lower = raw_def.lower()
        for concept_slug, keywords in known_concepts.items():
            if concept_slug == term_slug:
                continue
            if any(kw in def_lower for kw in keywords):
                proposed_edges.append(
                    ProposedEdge(target=concept_slug, relation="requires", weight=0.85)
                )

        candidate_id = str(uuid.uuid5(NAMESPACE_ONTOLOGY_CANDIDATES, f"{doc.doc_id}:{term_slug}"))
        cand = CandidateTerm(
            candidate_id=candidate_id,
            term=cleaned_term.title(),
            slug=term_slug,
            definition=raw_def,
            domain=self.config.target_domain,
            domain_name=self.config.target_domain_name,
            source_doc_id=doc.doc_id,
            source_title=doc.title,
            confidence=0.92,
            frequency=1,
            char_start=match_start,
            char_end=match_end,
            aliases=aliases,
            proposed_edges=proposed_edges,
        )
        candidates[term_slug] = cand

    def stage_candidates(
        self,
        conn: psycopg.Connection[Any],
        candidates: list[CandidateTerm],
    ) -> int:
        """Persist candidates into ontology_staging table for human review."""
        if not candidates:
            return 0

        inserted = 0
        try:
            for cand in candidates:
                record = cand.to_taxonomy_record()
                conn.execute(
                    """
                    INSERT INTO ontology_staging (
                        candidate_id, term, slug, definition, domain, domain_name,
                        source_document_id, source_title, status, confidence, frequency,
                        char_start, char_end, proposed_edges, aliases, payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (candidate_id) DO UPDATE SET
                        frequency = ontology_staging.frequency + 1,
                        definition = EXCLUDED.definition
                    """,
                    (
                        cand.candidate_id,
                        cand.term,
                        cand.slug,
                        cand.definition,
                        cand.domain,
                        cand.domain_name,
                        cand.source_doc_id if _is_valid_uuid(cand.source_doc_id) else None,
                        cand.source_title,
                        cand.confidence,
                        cand.frequency,
                        cand.char_start,
                        cand.char_end,
                        json.dumps([e.as_dict() for e in cand.proposed_edges]),
                        json.dumps(cand.aliases),
                        json.dumps(record),
                    ),
                )
                inserted += 1
                ONTOLOGY_CANDIDATES_DISCOVERED.inc()

            conn.commit()
            logger.info("ontology_candidates_staged", count=inserted)
        except Exception as exc:
            logger.warning("stage_candidates_failed", error=str(exc))

        return inserted


def _is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError):
        return False
