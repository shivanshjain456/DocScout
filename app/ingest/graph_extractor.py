"""Knowledge Graph extractor for regulatory provisions and circular cross-references (P2-2).

Extracts span-grounded entities (documents, sections, provisions) and directed relationships
('cites', 'amends', 'supersedes', 'implements', 'references') from regulatory texts.
Zero ungrounded LLM invention: every node and edge cites an exact character span in the source.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.ingest.ids import CHUNK_ID_NAMESPACE

# Stable UUID namespace for graph edges
NAMESPACE_GRAPH = uuid.uuid5(CHUNK_ID_NAMESPACE, "knowledge_graph")


@dataclass(frozen=True)
class ExtractedNode:
    """An entity node in the regulatory knowledge graph."""

    node_id: str
    node_type: str  # 'document' | 'section' | 'provision'
    document_id: str
    label: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ExtractedEdge:
    """A grounded relationship edge in the regulatory knowledge graph."""

    edge_id: str
    source_node_id: str
    target_node_id: str
    relation: str  # 'cites' | 'amends' | 'supersedes' | 'implements' | 'references'
    source_document_id: str
    target_document_id: str | None
    chunk_id: str | None
    char_start: int
    char_end: int
    evidence_text: str


# Regex patterns for structural sections and provisions
_RE_PARAGRAPH = re.compile(
    r"\b(?:Paragraph|Para\.?)\s+(\d+[A-Z]?)\b",
    re.IGNORECASE,
)
_RE_SECTION = re.compile(
    r"\b(?:Section|Sec\.?)\s+(\d+[A-Z]?)\b",
    re.IGNORECASE,
)
_RE_CLAUSE = re.compile(
    r"\b(?:Clause|Cl\.?)\s+(\d+[A-Z]?)\b",
    re.IGNORECASE,
)
_RE_NUMBERED_PROVISION = re.compile(
    r"(?m)(?:^|\n)\s*(\d+)\.\s+([A-Za-z][A-Za-z0-9\s\-,/\(\)]{3,60}?)(?::|\s{2,}|\n)",
)

# Citation patterns for statutes and regulatory frameworks
_STATUTE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("statute:bra_1949", re.compile(r"\bBanking\s+Regulation\s+Act,?\s+1949\b", re.IGNORECASE)),
    (
        "statute:rbia_1934",
        re.compile(r"\bReserve\s+Bank\s+of\s+India\s+Act,?\s+1934\b", re.IGNORECASE),
    ),
    (
        "statute:uapa_1967",
        re.compile(r"\bUnlawful\s+Activities\s+\(Prevention\)\s+Act,?\s+1967\b", re.IGNORECASE),
    ),
    ("statute:fema_1999", re.compile(r"\bForeign\s+Exchange\s+Management\s+Act\b", re.IGNORECASE)),
    (
        "statute:sebi_invit_2014",
        re.compile(
            r"\bSEBI\s*\(Infrastructure\s+Investment\s+Trusts\)\s+Regulations,?\s+2014\b",
            re.IGNORECASE,
        ),
    ),
    (
        "statute:sebi_reit_2014",
        re.compile(
            r"\bSEBI\s*\(Real\s+Estate\s+Investment\s+Trusts\)\s+Regulations,?\s+2014\b",
            re.IGNORECASE,
        ),
    ),
    (
        "statute:sebi_lodr_2015",
        re.compile(
            r"\bSEBI\s*\(LODR\)\s+Regulations\b|\bListing\s+Obligations\s+and\s+Disclosure\s+Requirements\b",
            re.IGNORECASE,
        ),
    ),
]

# Action verbs indicating regulatory relationship
_RE_AMENDS = re.compile(
    r"\b(?:amends?|amended|amendment\s+directions?|in\s+partial\s+modification\s+of)\b",
    re.IGNORECASE,
)
_RE_SUPERSEDES = re.compile(
    r"\b(?:supersedes?|supersession|withdrawal\s+of\s+circulars?|withdraws?|repeals?)\b",
    re.IGNORECASE,
)
_RE_IMPLEMENTS = re.compile(r"\bpowers\s+conferred\s+by\s+Section\s+(\d+[A-Z]?)\b", re.IGNORECASE)


def make_edge_id(source_node_id: str, target_node_id: str, relation: str, char_start: int) -> str:
    """Generate a deterministic UUIDv5 for a graph edge based on its endpoints and offset."""
    key = f"{source_node_id}->{relation}->{target_node_id}@{char_start}"
    return str(uuid.uuid5(NAMESPACE_GRAPH, key))


def extract_graph_elements(
    document_id: str,
    text: str,
    doc_title: str | None = None,
    canonical_url: str | None = None,
    chunks: list[dict[str, Any]] | None = None,
) -> tuple[list[ExtractedNode], list[ExtractedEdge]]:
    """Extract grounded provision nodes and directed edges from a regulatory document text."""
    nodes: list[ExtractedNode] = []
    edges: list[ExtractedEdge] = []
    seen_nodes: set[str] = set()

    # 1. Document root node
    doc_node_id = f"doc:{document_id}"
    label = doc_title if doc_title else f"Document {document_id}"
    nodes.append(
        ExtractedNode(
            node_id=doc_node_id,
            node_type="document",
            document_id=document_id,
            label=label,
            char_start=0,
            char_end=min(len(text), 200),
        )
    )
    seen_nodes.add(doc_node_id)

    def find_chunk_id(start: int, end: int) -> str | None:
        """Find the chunk that covers or has maximum overlap with this character span."""
        if not chunks:
            return None
        for ch in chunks:
            c_start = int(ch.get("char_start", 0))
            c_end = int(ch.get("char_end", 0))
            if c_start <= start and c_end >= end:
                return str(ch["chunk_id"])
        # Fallback to any overlapping chunk
        for ch in chunks:
            c_start = int(ch.get("char_start", 0))
            c_end = int(ch.get("char_end", 0))
            if max(c_start, start) < min(c_end, end):
                return str(ch["chunk_id"])
        return str(chunks[0]["chunk_id"]) if chunks else None

    # 2. Extract structural sections and numbered provisions
    for match in _RE_NUMBERED_PROVISION.finditer(text):
        num = match.group(1).strip()
        prov_title = match.group(2).strip()
        node_id = f"prov:{document_id}:p{num}"
        if node_id not in seen_nodes:
            nodes.append(
                ExtractedNode(
                    node_id=node_id,
                    node_type="provision",
                    document_id=document_id,
                    label=f"Clause {num}: {prov_title}",
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
            seen_nodes.add(node_id)
            # Edge: Document implements/contains Provision
            cid = find_chunk_id(match.start(), match.end())
            edges.append(
                ExtractedEdge(
                    edge_id=make_edge_id(doc_node_id, node_id, "implements", match.start()),
                    source_node_id=doc_node_id,
                    target_node_id=node_id,
                    relation="implements",
                    source_document_id=document_id,
                    target_document_id=document_id,
                    chunk_id=cid,
                    char_start=match.start(),
                    char_end=match.end(),
                    evidence_text=text[match.start() : min(len(text), match.start() + 150)],
                )
            )

    # 3. Extract explicit Paragraph / Section insertions (common in amendments)
    for match in _RE_PARAGRAPH.finditer(text):
        para_num = match.group(1).strip()
        node_id = f"prov:{document_id}:para_{para_num}"
        if node_id not in seen_nodes:
            nodes.append(
                ExtractedNode(
                    node_id=node_id,
                    node_type="section",
                    document_id=document_id,
                    label=f"Paragraph {para_num}",
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
            seen_nodes.add(node_id)
            cid = find_chunk_id(match.start(), match.end())
            edges.append(
                ExtractedEdge(
                    edge_id=make_edge_id(doc_node_id, node_id, "implements", match.start()),
                    source_node_id=doc_node_id,
                    target_node_id=node_id,
                    relation="implements",
                    source_document_id=document_id,
                    target_document_id=document_id,
                    chunk_id=cid,
                    char_start=match.start(),
                    char_end=match.end(),
                    evidence_text=text[match.start() : min(len(text), match.start() + 100)],
                )
            )

    # 4. Extract citations to primary statutes and regulatory acts
    for stat_id, pattern in _STATUTE_PATTERNS:
        for match in pattern.finditer(text):
            stat_node_id = stat_id
            if stat_node_id not in seen_nodes:
                nodes.append(
                    ExtractedNode(
                        node_id=stat_node_id,
                        node_type="document",
                        document_id=document_id,
                        label=match.group(0).strip(),
                        char_start=match.start(),
                        char_end=match.end(),
                    )
                )
                seen_nodes.add(stat_node_id)

            cid = find_chunk_id(match.start(), match.end())
            # Determine whether this is an authorizing statute ("powers conferred by Section...")
            surrounding = text[max(0, match.start() - 60) : min(len(text), match.end() + 60)]
            rel = "implements" if "powers conferred" in surrounding.lower() else "cites"

            edges.append(
                ExtractedEdge(
                    edge_id=make_edge_id(doc_node_id, stat_node_id, rel, match.start()),
                    source_node_id=doc_node_id,
                    target_node_id=stat_node_id,
                    relation=rel,
                    source_document_id=document_id,
                    target_document_id=None,
                    chunk_id=cid,
                    char_start=match.start(),
                    char_end=match.end(),
                    evidence_text=surrounding.strip(),
                )
            )

    # 5. Extract Amendment and Supersession relationships
    for match in _RE_AMENDS.finditer(text):
        cid = find_chunk_id(match.start(), match.end())
        snippet = text[max(0, match.start() - 30) : min(len(text), match.end() + 100)]
        edges.append(
            ExtractedEdge(
                edge_id=make_edge_id(doc_node_id, doc_node_id, "amends", match.start()),
                source_node_id=doc_node_id,
                target_node_id=doc_node_id,
                relation="amends",
                source_document_id=document_id,
                target_document_id=document_id,
                chunk_id=cid,
                char_start=match.start(),
                char_end=match.end(),
                evidence_text=snippet.strip(),
            )
        )

    for match in _RE_SUPERSEDES.finditer(text):
        cid = find_chunk_id(match.start(), match.end())
        snippet = text[max(0, match.start() - 30) : min(len(text), match.end() + 100)]
        edges.append(
            ExtractedEdge(
                edge_id=make_edge_id(doc_node_id, doc_node_id, "supersedes", match.start()),
                source_node_id=doc_node_id,
                target_node_id=doc_node_id,
                relation="supersedes",
                source_document_id=document_id,
                target_document_id=document_id,
                chunk_id=cid,
                char_start=match.start(),
                char_end=match.end(),
                evidence_text=snippet.strip(),
            )
        )

    return nodes, edges
