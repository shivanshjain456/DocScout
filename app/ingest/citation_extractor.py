"""Circular Citation Graph Extractor (FEAT-005).

Extracts and formalizes cross-document statutory references (e.g., "in terms of Circular
DBOD.No.BP.BC...", "RBI/2024-25/111", "SEBI/HO/...") during document ingestion to construct
an explicit circular lineage graph across RBI, SEBI, and regulatory frameworks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.api.metrics import CITATIONS_EXTRACTED_TOTAL, UNRESOLVED_CITATIONS_TOTAL

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CitationEdge:
    """Directed citation reference from a source document to a target regulatory circular."""

    source_doc_id: str
    target_circular_no: str
    target_doc_id: str | None
    raw_citation_span: str
    char_start: int = 0
    char_end: int = 0


@dataclass(frozen=True)
class CitationExtractorConfig:
    """Configuration for circular citation extraction."""

    enabled: bool = True
    resolve_unmanifested: bool = True


# Pre-compiled statutory citation patterns
_RE_RBI_CODE = re.compile(
    r"\b(RBI\/\d{4}-\d{2,4}\/\d+)\b",
    re.IGNORECASE,
)

_RE_CIRCULAR_PREFIX = re.compile(
    r"\b((?:DBOD|RPCD|DOR|FIDD|DNBR|FMD|DGBA|FMOD|IDMD|DPSS|FEMA)"
    r"(?:\.[A-Za-z0-9_\-]+)+"
    r"(?:\/[A-Za-z0-9_\-\.\(\)]+)*)\b",
    re.IGNORECASE,
)

_RE_CIRCULAR_NO = re.compile(
    r"\b((?:DBOD|RPCD|DOR|FIDD|DNBR|FMD|DGBA|FMOD|IDMD|DPSS)"
    r"(?:\.CO)?(?:\.[A-Za-z0-9_\-]+)*"
    r"\.No\.[A-Za-z0-9\.\-\/\(\)\s]+?"
    r"(?=\s+(?:dated|dated\s+|January|February|March|April|May|June|July|August|September|October|November|December|\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}|\n|$)))",
    re.IGNORECASE,
)

_RE_SEBI_CIRCULAR = re.compile(
    r"\b(SEBI\/[A-Za-z0-9_\-\/]+|CIR\/[A-Za-z0-9_\-\/]+|HO\/\([0-9]+\)[A-Za-z0-9_\-\/]+)\b",
    re.IGNORECASE,
)

_RE_MASTER_DIRECTION = re.compile(
    r"\b(?:Master\s+Direction|Master\s+Circular)\s*[-:\u2013\u2014]\s*([A-Za-z0-9\.\-\/\(\)]+)\b",
    re.IGNORECASE,
)


def _clean_circular_id(raw: str) -> str:
    """Normalize circular identifier for uniform hashing and matching."""
    s = raw.strip().rstrip(".,;:)")
    # Collapse multiple whitespace
    s = re.sub(r"\s+", " ", s)
    return s


class CircularCitationExtractor:
    """Extractor and manifest resolver for statutory circular citations."""

    def __init__(
        self,
        config: CitationExtractorConfig | None = None,
        manifest_path: Path | str | None = None,
    ) -> None:
        self.config = config or CitationExtractorConfig()
        self.manifest_index: dict[str, str] = {}
        self._load_manifest(manifest_path)

    def _load_manifest(self, manifest_path: Path | str | None) -> None:
        """Load manifest documents and build lookup index for circular identifiers."""
        path: Path | None = None
        if manifest_path is not None:
            path = Path(manifest_path)
        else:
            default_p = Path(__file__).resolve().parents[2] / "corpus" / "raw" / "manifest.json"
            if default_p.is_file():
                path = default_p

        if path and path.is_file():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                docs = data.get("documents", []) if isinstance(data, dict) else []
                for doc in docs:
                    doc_id = str(doc.get("n", ""))
                    local_path = str(doc.get("local_path", ""))
                    url = str(doc.get("url", ""))

                    # Index by clean filename stem
                    stem = Path(local_path).stem.upper()
                    self.manifest_index[stem] = doc_id

                    # Extract any embedded circular number in local path or URL
                    for match in _RE_RBI_CODE.finditer(local_path + " " + url):
                        self.manifest_index[_clean_circular_id(match.group(1)).upper()] = doc_id
                    for match in _RE_CIRCULAR_PREFIX.finditer(local_path + " " + url):
                        self.manifest_index[_clean_circular_id(match.group(1)).upper()] = doc_id
            except Exception as exc:
                logger.warning("citation_extractor_manifest_load_failed", error=str(exc))

    def resolve_target(self, circular_no: str) -> str | None:
        """Resolve a circular identifier to internal corpus document ID."""
        clean = _clean_circular_id(circular_no).upper()
        # Direct index lookup
        if clean in self.manifest_index:
            return self.manifest_index[clean]

        # Substring / partial key matching
        for k, doc_id in self.manifest_index.items():
            if k in clean or clean in k:
                return doc_id

        return None

    def extract_citations(self, text: str, doc_id: str) -> list[CitationEdge]:
        """Extract statutory circular citations from document text with provenance offsets."""
        if not self.config.enabled:
            return []

        if not isinstance(text, str) or len(text) < 100:
            raise ValueError("text must be non-empty string >= 100 characters")

        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("doc_id must be non-empty string")

        edges: list[CitationEdge] = []
        seen_spans: set[tuple[str, int]] = set()

        patterns = [
            _RE_RBI_CODE,
            _RE_CIRCULAR_PREFIX,
            _RE_CIRCULAR_NO,
            _RE_SEBI_CIRCULAR,
            _RE_MASTER_DIRECTION,
        ]

        for pat in patterns:
            try:
                for match in pat.finditer(text):
                    raw_circ = match.group(1) if match.groups() else match.group(0)
                    clean_circ = _clean_circular_id(raw_circ)

                    # Validate length of circular number (ignore trivial false positives like "FEMA.1")
                    if len(clean_circ) < 5 or "." not in clean_circ and "/" not in clean_circ:
                        continue

                    start = match.start()
                    end = match.end()

                    key = (clean_circ, start)
                    if key in seen_spans:
                        continue
                    seen_spans.add(key)

                    # Extract surrounding context span (up to 60 chars before and after)
                    span_start = max(0, start - 40)
                    span_end = min(len(text), end + 40)
                    raw_span = text[span_start:span_end].strip()

                    target_doc_id = self.resolve_target(clean_circ)
                    if target_doc_id is None and not self.config.resolve_unmanifested:
                        continue

                    edges.append(
                        CitationEdge(
                            source_doc_id=doc_id,
                            target_circular_no=clean_circ,
                            target_doc_id=target_doc_id,
                            raw_citation_span=raw_span,
                            char_start=start,
                            char_end=end,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "citation_extraction_pattern_error",
                    pattern=str(pat.pattern),
                    doc_id=doc_id,
                    error=str(exc),
                )

        # Update telemetry
        CITATIONS_EXTRACTED_TOTAL.inc(len(edges))
        unresolved = sum(1 for e in edges if e.target_doc_id is None)
        UNRESOLVED_CITATIONS_TOTAL.set(unresolved)

        return edges
