"""Cross-Lingual Semantic Regulatory Search (FEAT-076).

Official Indian regulatory frameworks and gazettes published by the Reserve Bank of India
(RBI), Securities and Exchange Board of India (SEBI), and the Ministry of Finance are
bilingually drafted in English and Hindi (Devanagari script).

This module implements a dedicated `MultilingualDenseStore` adapter conforming to the
`VectorStore` Protocol in `app/retrieval/port.py`. It projects cross-lingual query embeddings
into the shared 384-dimensional unit-norm vector space (matching chunks.embedding per ADR-0002),
enabling zero-shot retrieval of English regulatory circulars from Devanagari Hindi queries
and vice-versa without destructive automated translation.
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import psycopg
import structlog

from app.api.metrics import CROSS_LINGUAL_QUERIES_TOTAL
from app.ingest.devanagari import has_devanagari, normalize_devanagari
from app.ingest.embed import Embedder
from app.retrieval import dense
from app.retrieval.port import ChunkRow, PgVectorStore, VectorStore
from app.retrieval.types import MetadataFilter

logger = structlog.get_logger(__name__)

# Core regulatory bilingual phrase alignment map (Hindi Devanagari to English statutory concepts)
REGULATORY_BILINGUAL_MAP: dict[str, str] = {
    # Payment Systems & Aggregators
    "भुगतान एग्रीगेटर": "payment aggregator",
    "भुगतान गेटवे": "payment gateway",
    "पूंजी आवश्यकता": "capital net worth requirement",
    "पूंजी पर्याप्तता": "capital adequacy ratio",
    "शुद्ध मूल्य": "net worth",
    "शुद्ध स्वामित्व निधि": "net owned funds",
    "प्रीपेड भुगतान साधन": "prepaid payment instruments ppi",
    "अंतर-संचालनीयता": "interoperability",
    # Non-Banking Financial Companies & Categorization
    "गैर-बैंकिंग वित्तीय कंपनी": "non-banking financial company nbfc",
    "गैर बैंकिंग वित्तीय कंपनी": "non-banking financial company nbfc",
    "पंजीकरण दिशानिर्देश": "registration guidelines",
    "स्केल आधारित विनियमन": "scale based regulation",
    "विनियामक ढांचा": "regulatory framework",
    "परिसंपत्ति पुनर्निर्माण कंपनी": "asset reconstruction company arc",
    "आवास वित्त कंपनी": "housing finance company hfc",
    "शहरी सहकारी बैंक": "urban cooperative bank ucb",
    # KYC & Customer Due Diligence
    "केवाईसी सत्यापन": "kyc verification customer due diligence",
    "केवाईसी": "know your customer kyc",
    "पैन लिंकिंग": "pan linking aadhaar",
    "ग्राहक देयता": "customer liability",
    "सीमित ग्राहक देयता": "limiting customer liability",
    "अनधिकृत इलेक्ट्रॉनिक लेनदेन": "unauthorized electronic banking transactions",
    "धोखाधड़ी रिपोर्टिंग": "fraud reporting",
    # Cyber Security & Digital Lending
    "साइबर सुरक्षा": "cyber security framework",
    "साइबर घटना": "cyber incident reporting",
    "डिजिटल ऋण": "digital lending guidelines",
    "डिफ़ॉल्ट हानि गारंटी": "default loss guarantee dlg",
    "ऋण सेवा प्रदाता": "lending service provider lsp",
    # Basel III, Liquidity & Capital
    "तरलता कवरेज अनुपात": "liquidity coverage ratio lcr",
    "उच्च गुणवत्ता वाली तरल संपत्ति": "high quality liquid assets hqla",
    "बड़ी एक्सपोजर रूपरेखा": "large exposures framework single group borrower limits",
    "त्वरित सुधारात्मक कार्रवाई": "prompt corrective action pca framework",
    # Lending, Recovery & Customer Protection
    "प्राथमिकता प्राप्त क्षेत्र": "priority sector lending psl targets",
    "समझौता निपटान": "compromise settlement technical write-off",
    "तकनीकी राइट-ऑफ": "technical write-offs",
    "इरादतन चूककर्ता": "wilful defaulters identification classification",
    "सूक्ष्म वित्त ऋण": "microfinance loans collateral free",
    "निष्पक्ष व्यवहार संहिता": "fair practices code transparency interest rates",
    "सोने के आभूषणों के बदले ऋण": "loans against gold jewellery bullet repayment",
    "बुलेट पुनर्भुगतान": "bullet repayment scheme",
    "आंतरिक लोकपाल": "internal ombudsman scheme grievance redressal",
    "शिकायत निवारण तंत्र": "grievance redressal mechanism",
    "वित्तीय समावेशन": "financial inclusion plan basic savings bank deposit account",
    "क्रेडिट कार्ड और डेबिट कार्ड": "credit card and debit card issuance conduct directions",
    "विदेशी मुद्रा प्रबंधन": "foreign exchange management external commercial borrowings ecb",
    "बाह्य वाणिज्यिक उधारी": "external commercial borrowings ecb",
    "जलवायु जोखिम": "climate risk sustainable finance disclosures",
    "संधारणीय वित्त": "sustainable finance green deposits",
    "आउटसोर्सिंग": "outsourcing financial services risk management",
    "वित्तीय सेवाओं का आउटसोर्सिंग": "outsourcing of financial services risk management code of conduct",
}

# Individual Hindi statutory terms fallback lexicon
HINDI_TERM_LEXICON: dict[str, str] = {
    "दिशानिर्देश": "guidelines",
    "निर्देश": "directions",
    "सर्कुलर": "circular",
    "अधिसूचना": "notification",
    "मास्टर": "master",
    "ढांचा": "framework",
    "विनियमन": "regulation",
    "प्रावधान": "provision",
    "शर्तें": "conditions",
    "अनिवार्य": "mandatory",
    "बैंक": "bank",
    "बैंकों": "banks",
    "उधारकर्ता": "borrower",
    "ऋण": "loan",
    "ऋणदाता": "lender",
    "जमा": "deposit",
    "खाता": "account",
    "सीमा": "limit",
    "लक्ष्य": "target",
    "संपार्श्विक": "collateral",
    "छूट": "exemption",
    "अनुपालन": "compliance",
    "जोखिम": "risk",
    "शासन": "governance",
    "निगरानी": "supervision",
    "स्वीकृति": "approval",
    "लाइसेंस": "license",
}

# Regex for retaining alphanumeric codes, section citations, and English terms
ALPHANUM_PRESERVE_RE = re.compile(r"\b[A-Za-z0-9\-\.\/]+\b")


def validate_query_string(query: str) -> None:
    """Validate query input per FEAT-076 input validation rules.

    Rules:
    - Must be a valid UTF-8 string.
    - Length must be between 3 and 512 characters inclusive.
    """
    if not isinstance(query, str):
        raise ValueError(f"Query must be a string, got {type(query).__name__}")
    try:
        query.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"Query contains invalid UTF-8: {exc}") from exc

    stripped = query.strip()
    if len(stripped) < 3 or len(query) > 512:
        raise ValueError(
            f"Query length must be between 3 and 512 characters, got length {len(query)} (stripped: {len(stripped)})"
        )


def detect_language(query: str) -> str:
    """Classify query language as Hindi ('hi') or English ('en')."""
    if has_devanagari(query):
        return "hi"
    return "en"


class CrossLingualProjector:
    """Stateless cross-lingual projection engine into the 384-dimensional vector space."""

    def __init__(self, embedder: Embedder | None = None) -> None:
        self._embedder = embedder if embedder is not None else Embedder()

    def translate_and_align_query(self, query: str) -> str:
        """Map Hindi Devanagari regulatory terms to aligned English statutory concepts."""
        normalized = normalize_devanagari(query)
        working_text = unicodedata.normalize("NFC", normalized)

        # Preserve English tokens, acronyms (RBI, KYC, NBFC, LCR) and section numbers
        preserved_tokens = ALPHANUM_PRESERVE_RE.findall(working_text)
        english_context = " ".join(t for t in preserved_tokens if not t.isdigit() or len(t) > 3)

        aligned_concepts: list[str] = []

        # Sort compound phrases by length descending for greedy longest-match substitution
        sorted_phrases = sorted(REGULATORY_BILINGUAL_MAP.keys(), key=len, reverse=True)
        residual_text = working_text
        for phrase in sorted_phrases:
            if phrase in residual_text:
                aligned_concepts.append(REGULATORY_BILINGUAL_MAP[phrase])
                residual_text = residual_text.replace(phrase, " ")

        # Process remaining standalone tokens
        for token in residual_text.split():
            clean_token = token.strip(".,;:?!'\"()[]{}")
            if clean_token in HINDI_TERM_LEXICON:
                aligned_concepts.append(HINDI_TERM_LEXICON[clean_token])

        # Combine aligned statutory concepts with preserved English context
        combined = " ".join(aligned_concepts)
        if english_context:
            combined = f"{english_context} {combined}".strip()

        # If no terms matched in lexicon, fallback to preserved English or normalized text
        if not combined.strip():
            combined = working_text

        return combined.strip()

    def project_query(self, query: str) -> np.ndarray:
        """Encode and project query into the canonical 384-dimensional unit-norm vector."""
        validate_query_string(query)
        lang = detect_language(query)

        try:
            if lang == "hi":
                aligned_query = self.translate_and_align_query(query)
                vector = self._embedder.encode_query(aligned_query)
            else:
                vector = self._embedder.encode_query(query)

            # Ensure strict L2 unit-norm
            vec = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec = vec / norm
            return vec
        except Exception as exc:
            logger.warning(
                "cross_lingual_projection_failed_fallback_to_english_embedder",
                query=query,
                error=str(exc),
            )
            # Fail-closed fallback: standard English BGE embedder
            fallback_vec = np.asarray(self._embedder.encode_query(query), dtype=np.float32)
            fallback_norm = float(np.linalg.norm(fallback_vec))
            if fallback_norm > 0:
                fallback_vec = fallback_vec / fallback_norm
            return fallback_vec


class MultilingualDenseStore:
    """VectorStore adapter implementing cross-lingual semantic regulatory search (FEAT-076).

    Plugs into the VectorStore Protocol. Operates seamlessly with PostgreSQL pgvector in
    production, with an injected backing store, or as a hermetic in-memory store in unit tests.
    """

    def __init__(
        self,
        conn: psycopg.Connection[tuple[object, ...]] | None = None,
        *,
        backing_store: VectorStore | None = None,
        projector: CrossLingualProjector | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._conn = conn
        self._projector = projector if projector is not None else CrossLingualProjector(embedder)
        self._backing_store = backing_store
        if self._backing_store is None and conn is not None:
            self._backing_store = PgVectorStore(conn)

        # In-memory storage for test double and hermetic execution
        self._in_memory_vectors: dict[str, np.ndarray] = {}
        self._in_memory_metadata: dict[str, ChunkRow] = {}

    @property
    def projector(self) -> CrossLingualProjector:
        return self._projector

    def register_chunk(
        self,
        chunk_id: str,
        vector: np.ndarray,
        meta: ChunkRow,
    ) -> None:
        """Register a chunk in the internal in-memory index for testing or hermetic operation."""
        v = np.asarray(vector, dtype=np.float32)
        v_norm = float(np.linalg.norm(v))
        if v_norm > 0:
            v = v / v_norm
        self._in_memory_vectors[chunk_id] = v
        self._in_memory_metadata[chunk_id] = meta

    def search(
        self,
        query_vector: np.ndarray,
        k: int,
        filter: MetadataFilter | None = None,
        query_text: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return top-k (chunk_id, similarity) tuples sorted descending by similarity.

        If `query_text` is supplied and contains Devanagari Hindi, executes cross-lingual
        projection to project the Hindi query into the shared 384-dimensional vector space.
        Increments the `docscout_cross_lingual_queries_total{lang}` metric.
        """
        effective_vector = query_vector
        lang = "en"

        if query_text is not None:
            validate_query_string(query_text)
            lang = detect_language(query_text)
            CROSS_LINGUAL_QUERIES_TOTAL.labels(lang=lang).inc()

            if lang == "hi":
                effective_vector = self._projector.project_query(query_text)
        else:
            # When no query_text is provided, default to recording English metric
            CROSS_LINGUAL_QUERIES_TOTAL.labels(lang="en").inc()

        # Delegate to backing store if present
        if self._backing_store is not None:
            return self._backing_store.search(effective_vector, k, filter=filter)

        # Delegate to active database connection if backing_store not explicitly injected
        if self._conn is not None:
            return dense.search(self._conn, effective_vector, k, filter=filter)

        # Hermetic in-memory search
        hits: list[tuple[str, float]] = []
        q = np.asarray(effective_vector, dtype=np.float32)
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0.0:
            return []

        for cid, vec in self._in_memory_vectors.items():
            meta = self._in_memory_metadata.get(cid)
            if filter is not None and not filter.matches(meta):  # type: ignore[arg-type]
                continue
            v = np.asarray(vec, dtype=np.float32)
            v_norm = float(np.linalg.norm(v))
            if v_norm == 0.0:
                sim = 0.0
            else:
                sim = float(np.dot(q, v) / (q_norm * v_norm))
            hits.append((cid, sim))

        hits.sort(key=lambda x: x[1], reverse=True)
        return hits[:k]

    def fetch_metadata(
        self,
        chunk_ids: list[str],
        is_current: bool | None = True,
    ) -> dict[str, ChunkRow]:
        """Fetch display and attribution metadata for a set of chunk IDs."""
        if not chunk_ids:
            return {}

        if self._backing_store is not None:
            return self._backing_store.fetch_metadata(chunk_ids, is_current=is_current)

        if self._conn is not None:
            return PgVectorStore(self._conn).fetch_metadata(chunk_ids, is_current=is_current)

        # Hermetic in-memory lookup
        result: dict[str, ChunkRow] = {}
        for cid in chunk_ids:
            if cid in self._in_memory_metadata:
                result[cid] = self._in_memory_metadata[cid]
        return result
