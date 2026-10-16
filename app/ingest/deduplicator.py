"""Duplicate and reprint deduplication engine for regulatory documents (FEAT-070).

Detects exact reprints, cross-department identical publications, and gazette
re-issues using content SHA-256, cleaned text SHA-256, and MinHash Locality-Sensitive
Hashing (LSH) similarity over word shingles.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

from app.api.metrics import DUPLICATE_DOCUMENTS_DETECTED_TOTAL
from app.ingest.furniture_stripper import strip_furniture

logger = structlog.get_logger(__name__)

# Prime modulus larger than 2^32 for 32-bit linear congruential hashing
_M32: int = 4294967311
_RE_WORD = re.compile(r"\b[A-Za-z0-9_\-\/]+\b")
_RE_DOWNLOAD = re.compile(r"(?i)\bdownloaded\s+from\s+[^\n\r]+")
_RE_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class DeduplicationConfig:
    """Configuration for MinHash LSH deduplication engine."""

    min_similarity_threshold: float = 0.98
    num_perm: int = 128
    shingle_size: int = 3
    num_bands: int = 16
    rows_per_band: int = 8  # 16 * 8 = 128
    min_token_length: int = 5


@dataclass(frozen=True)
class DeduplicationResult:
    """Outcome of duplicate and reprint inspection."""

    is_duplicate: bool
    canonical_doc_id: str | None = None
    similarity_score: float = 0.0
    match_type: str = "none"  # "exact_content", "exact_text", "minhash_lsh", "none"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_duplicate": self.is_duplicate,
            "canonical_doc_id": self.canonical_doc_id,
            "similarity_score": round(self.similarity_score, 4),
            "match_type": self.match_type,
            "detail": self.detail,
        }


def _normalize_dedup_text(text: str) -> str:
    """Strip official furniture, download notices, and collapse whitespace once."""
    cleaned, _ = strip_furniture(text)
    cleaned = _RE_DOWNLOAD.sub(" ", cleaned)
    cleaned = _RE_URL.sub(" ", cleaned)
    return cleaned


class MinHashGenerator:
    """Vectorized deterministic MinHash signature generator."""

    def __init__(self, num_perm: int = 128, shingle_size: int = 3) -> None:
        self.num_perm = num_perm
        self.shingle_size = shingle_size
        # Deterministic fixed seed ensures repeatable hashes across nodes
        rng = np.random.RandomState(42)
        self._a = rng.randint(1, _M32, size=(num_perm, 1), dtype=np.int64)
        self._b = rng.randint(0, _M32, size=(num_perm, 1), dtype=np.int64)

    def shingle_hashes(self, text: str, already_cleaned: bool = False) -> np.ndarray:
        """Tokenize and return unique 32-bit integer shingle hashes."""
        if not text or not text.strip():
            raise ValueError("Document text cannot be empty for deduplication")

        cleaned = text if already_cleaned else _normalize_dedup_text(text)

        tokens = _RE_WORD.findall(cleaned.lower())
        if len(tokens) < self.shingle_size:
            # Fallback for very short texts
            if not tokens:
                tokens = [cleaned.strip().lower()]
            shingles = {" ".join(tokens)}
        else:
            k = self.shingle_size
            shingles = {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}

        hashes = [zlib.crc32(s.encode("utf-8")) for s in shingles]
        return np.array(hashes, dtype=np.int64).reshape(1, -1)

    def compute_signature(self, text: str, already_cleaned: bool = False) -> np.ndarray:
        """Compute vectorized MinHash signature array of length `num_perm`."""
        x = self.shingle_hashes(text, already_cleaned=already_cleaned)
        # Vectorized hashing across permutations
        h = (self._a * x + self._b) % _M32
        sig = np.min(h, axis=1)
        return sig


class MinHashLSHIndex:
    """In-memory LSH band index for rapid candidate retrieval."""

    def __init__(self, config: DeduplicationConfig | None = None) -> None:
        self.config = config or DeduplicationConfig()
        self.generator = MinHashGenerator(
            num_perm=self.config.num_perm,
            shingle_size=self.config.shingle_size,
        )
        self.num_bands = self.config.num_bands
        self.rows_per_band = self.config.rows_per_band

        # 16 band hash tables mapping (band_idx, band_key_tuple) -> set of doc_ids
        self._bands: list[dict[tuple[int, ...], set[str]]] = [{} for _ in range(self.num_bands)]
        self._signatures: dict[str, np.ndarray] = {}
        self._content_hashes: dict[str, str] = {}  # sha256 -> doc_id
        self._text_hashes: dict[str, str] = {}  # text_sha256 -> doc_id

    def add_document(
        self,
        doc_id: str,
        text: str,
        content_sha256: str | None = None,
        signature: np.ndarray | None = None,
    ) -> np.ndarray:
        """Index a document and return its computed MinHash signature."""
        cleaned = _normalize_dedup_text(text)
        if signature is None:
            signature = self.generator.compute_signature(cleaned, already_cleaned=True)

        text_sha = compute_text_sha256(cleaned, already_cleaned=True)
        self._text_hashes[text_sha] = doc_id
        if content_sha256:
            self._content_hashes[content_sha256] = doc_id

        self._signatures[doc_id] = signature

        # Insert into LSH bands
        for b in range(self.num_bands):
            start = b * self.rows_per_band
            end = start + self.rows_per_band
            key = tuple(int(v) for v in signature[start:end])
            bucket = self._bands[b].setdefault(key, set())
            bucket.add(doc_id)

        return signature

    def query(
        self,
        text: str,
        content_sha256: str | None = None,
        min_threshold: float | None = None,
    ) -> DeduplicationResult:
        """Check whether text or content hash matches an existing document."""
        threshold = (
            min_threshold if min_threshold is not None else self.config.min_similarity_threshold
        )

        # Tier 1: Exact raw content SHA-256 match
        if content_sha256 and content_sha256 in self._content_hashes:
            canon_id = self._content_hashes[content_sha256]
            return DeduplicationResult(
                is_duplicate=True,
                canonical_doc_id=canon_id,
                similarity_score=1.0,
                match_type="exact_content",
                detail=f"Exact content payload SHA-256 match to canonical doc {canon_id}",
            )

        cleaned = _normalize_dedup_text(text)

        # Tier 2: Exact extracted text SHA-256 match
        text_sha = compute_text_sha256(cleaned, already_cleaned=True)
        if text_sha in self._text_hashes:
            canon_id = self._text_hashes[text_sha]
            return DeduplicationResult(
                is_duplicate=True,
                canonical_doc_id=canon_id,
                similarity_score=1.0,
                match_type="exact_text",
                detail=f"Exact text SHA-256 match to canonical doc {canon_id}",
            )

        # Tier 3: MinHash LSH near-duplicate search
        sig = self.generator.compute_signature(cleaned, already_cleaned=True)
        candidates: set[str] = set()

        for b in range(self.num_bands):
            start = b * self.rows_per_band
            end = start + self.rows_per_band
            key = tuple(int(v) for v in sig[start:end])
            if key in self._bands[b]:
                candidates.update(self._bands[b][key])

        if not candidates:
            return DeduplicationResult(
                is_duplicate=False,
                canonical_doc_id=None,
                similarity_score=0.0,
                match_type="none",
                detail="No candidate near-duplicates found in LSH bands",
            )

        # Calculate exact Jaccard similarity across candidates
        cand_list = [cid for cid in candidates if cid in self._signatures]
        if not cand_list:
            return DeduplicationResult(
                is_duplicate=False,
                canonical_doc_id=None,
                similarity_score=0.0,
                match_type="none",
                detail="No candidate near-duplicates found in LSH bands",
            )

        cand_matrix = np.array([self._signatures[cid] for cid in cand_list])
        sims = np.mean(cand_matrix == sig.reshape(1, -1), axis=1)
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])
        best_doc_id = cand_list[best_idx]

        if best_score >= threshold and best_doc_id is not None:
            return DeduplicationResult(
                is_duplicate=True,
                canonical_doc_id=best_doc_id,
                similarity_score=best_score,
                match_type="minhash_lsh",
                detail=f"MinHash near-duplicate (similarity {best_score:.4f}) of canonical doc {best_doc_id}",
            )

        return DeduplicationResult(
            is_duplicate=False,
            canonical_doc_id=None,
            similarity_score=best_score,
            match_type="none",
            detail=f"Highest similarity {best_score:.4f} below threshold {threshold:.4f}",
        )


class RegulatoryDeduplicator:
    """High-level deduplication engine coordinating exact and LSH checks."""

    def __init__(self, config: DeduplicationConfig | None = None) -> None:
        self.config = config or DeduplicationConfig()
        self.index = MinHashLSHIndex(config=self.config)

    def find_duplicate(
        self,
        text: str,
        content_sha256: str | None = None,
    ) -> DeduplicationResult:
        """Find duplicate within in-memory index."""
        try:
            return self.index.query(
                text=text,
                content_sha256=content_sha256,
                min_threshold=self.config.min_similarity_threshold,
            )
        except Exception as exc:
            logger.warning("Deduplication in-memory query failed", error=str(exc))
            return DeduplicationResult(is_duplicate=False, detail=f"Query error: {exc}")

    def check_duplicate_in_db(
        self,
        conn: Any,
        text: str,
        content_sha256: str | None = None,
    ) -> DeduplicationResult:
        """Inspect PostgreSQL database for exact or near-duplicate documents."""
        try:
            if not text or not text.strip():
                raise ValueError("Document text cannot be empty for deduplication")

            # Check 1: Exact raw content SHA-256 in document_versions
            if content_sha256:
                row = conn.execute(
                    """
                    SELECT v.document_id::text
                      FROM document_versions v
                     WHERE v.sha256 = %s
                     LIMIT 1
                    """,
                    (content_sha256,),
                ).fetchone()
                if row is not None:
                    canon_id = str(row[0])
                    DUPLICATE_DOCUMENTS_DETECTED_TOTAL.labels(match_type="exact_content").inc()
                    return DeduplicationResult(
                        is_duplicate=True,
                        canonical_doc_id=canon_id,
                        similarity_score=1.0,
                        match_type="exact_content",
                        detail=f"Exact content payload match to document {canon_id}",
                    )

            cleaned = _normalize_dedup_text(text)

            # Check 2: Exact cleaned text SHA-256 in documents
            text_sha = compute_text_sha256(cleaned, already_cleaned=True)
            row = conn.execute(
                """
                SELECT d.document_id::text
                  FROM documents d
                 WHERE d.text_sha256 = %s
                 LIMIT 1
                """,
                (text_sha,),
            ).fetchone()
            if row is not None:
                canon_id = str(row[0])
                DUPLICATE_DOCUMENTS_DETECTED_TOTAL.labels(match_type="exact_text").inc()
                return DeduplicationResult(
                    is_duplicate=True,
                    canonical_doc_id=canon_id,
                    similarity_score=1.0,
                    match_type="exact_text",
                    detail=f"Exact text SHA-256 match to document {canon_id}",
                )

            # Check 3: MinHash LSH similarity against existing documents
            sig = self.index.generator.compute_signature(cleaned, already_cleaned=True)

            rows = conn.execute(
                """
                SELECT d.document_id::text, d.minhash_signature
                  FROM documents d
                 WHERE d.minhash_signature IS NOT NULL
                """
            ).fetchall()

            if not rows:
                return DeduplicationResult(
                    is_duplicate=False,
                    canonical_doc_id=None,
                    similarity_score=0.0,
                    match_type="none",
                )

            best_doc_id: str | None = None
            best_score = 0.0

            for doc_id_raw, sig_raw in rows:
                if not sig_raw:
                    continue
                cand_sig = np.array(sig_raw, dtype=np.int64)
                sim = float(np.mean(sig == cand_sig))
                if sim > best_score:
                    best_score = sim
                    best_doc_id = str(doc_id_raw)

            if best_score >= self.config.min_similarity_threshold and best_doc_id is not None:
                DUPLICATE_DOCUMENTS_DETECTED_TOTAL.labels(match_type="minhash_lsh").inc()
                return DeduplicationResult(
                    is_duplicate=True,
                    canonical_doc_id=best_doc_id,
                    similarity_score=best_score,
                    match_type="minhash_lsh",
                    detail=f"MinHash near-duplicate (similarity {best_score:.4f}) of document {best_doc_id}",
                )

            return DeduplicationResult(
                is_duplicate=False,
                canonical_doc_id=None,
                similarity_score=best_score,
                match_type="none",
                detail=f"Highest similarity {best_score:.4f} below threshold",
            )

        except Exception as exc:
            logger.warning(
                "Database deduplication check error; defaulting to non-duplicate", error=str(exc)
            )
            return DeduplicationResult(
                is_duplicate=False,
                canonical_doc_id=None,
                similarity_score=0.0,
                match_type="none",
                detail=f"Check failed: {exc}",
            )


def compute_text_sha256(text: str, already_cleaned: bool = False) -> str:
    """Return hex-encoded SHA-256 digest of normalized text."""
    cleaned = text if already_cleaned else _normalize_dedup_text(text)
    norm = " ".join(cleaned.lower().split())
    if not norm:
        norm = " ".join(text.lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def compute_minhash_signature(text: str, config: DeduplicationConfig | None = None) -> list[int]:
    """Compute 128-integer MinHash signature list for document text."""
    cfg = config or DeduplicationConfig()
    gen = MinHashGenerator(num_perm=cfg.num_perm, shingle_size=cfg.shingle_size)
    sig = gen.compute_signature(text)
    return [int(v) for v in sig]
