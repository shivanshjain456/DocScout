"""Semantic Terminology Drift Tracker (FEAT-037).

Tracks how statutory and regulatory definitions drift across circular amendments over time
(e.g., evolving definitions of 'Critical IT Infrastructure', 'Significant Beneficial Owner',
or 'Material Outsourcee').
Computes cosine distance and token differences between sequential definitions, alerting
when semantic drift exceeds configured thresholds.
"""

from __future__ import annotations

import re
import zlib
from datetime import date
from typing import Any, Protocol

import numpy as np
import structlog
from pydantic import BaseModel, Field

from app.api.metrics import TERMINOLOGY_DRIFTS_FLAGGED_TOTAL

logger = structlog.get_logger("docscout.compliance.drift_tracker")

STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "s",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "t",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "whose",
}


class HistoricalDef(BaseModel):
    """Historical version of a statutory definition."""

    version_date: date
    doc_id: str
    definition_text: str


class DriftConfig(BaseModel):
    """Configuration for terminology drift evaluation."""

    alert_threshold_distance: float = Field(default=0.25, ge=0.0, le=1.0)


class TermDriftReport(BaseModel):
    """Report summarizing semantic drift for a statutory term across circular versions."""

    term_id: str
    canonical_term: str
    historical_definitions: list[HistoricalDef]
    semantic_distance_from_origin: float
    key_diff_tokens: list[str]
    drift_alert: bool = False


class EmbedderProtocol(Protocol):
    """Protocol for optional vector embedders."""

    def embed_query(self, text: str) -> np.ndarray: ...


def _tokenize_content_words(text: str) -> list[str]:
    """Tokenize and filter stop words and non-alphanumeric punctuation."""
    raw_tokens = re.findall(r"\b[a-zA-Z0-9][a-zA-Z0-9_-]*\b", text.lower())
    return [t for t in raw_tokens if t not in STOPWORDS and len(t) > 2]


def _fast_deterministic_vector(text: str, dim: int = 384) -> np.ndarray:
    """Compute deterministic unit-norm text embedding in pure Python/NumPy."""
    cleaned = text.strip()
    if not cleaned:
        vec = np.zeros(dim, dtype=np.float32)
        vec[0] = 1.0
        return vec

    words = re.findall(r"\b[a-zA-Z0-9_-]+\b", cleaned.lower())
    vec = np.zeros(dim, dtype=np.float32)
    for w in words:
        h = zlib.crc32(w.encode("utf-8")) % dim
        vec[h] += 1.0
        for i in range(len(w) - 2):
            gh = zlib.crc32(w[i : i + 3].encode("utf-8")) % dim
            vec[gh] += 0.5

    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        return vec / norm
    vec[0] = 1.0
    return vec


class TerminologyDriftTracker:
    """Evaluates longitudinal terminology drift across circular amendments."""

    def __init__(self, embedder: Any | None = None) -> None:
        self._embedder = embedder
        self._registry: dict[str, dict[str, Any]] = {}
        self._vector_cache: dict[str, np.ndarray] = {}
        self._init_benchmark_catalog()

    def register_definition(
        self,
        term_id: str,
        canonical_term: str,
        doc_id: str,
        version_date: date,
        definition_text: str,
    ) -> None:
        """Register a statutory definition version for a term."""
        norm_id = term_id.strip().lower()
        if norm_id not in self._registry:
            self._registry[norm_id] = {
                "term_id": norm_id,
                "canonical_term": canonical_term,
                "definitions": [],
            }

        hist_def = HistoricalDef(
            version_date=version_date,
            doc_id=doc_id,
            definition_text=definition_text.strip(),
        )

        existing_defs: list[HistoricalDef] = self._registry[norm_id]["definitions"]
        # Update canonical term if provided
        if canonical_term:
            self._registry[norm_id]["canonical_term"] = canonical_term

        # Avoid exact duplicate version insertion
        for idx, item in enumerate(existing_defs):
            if item.doc_id == doc_id and item.version_date == version_date:
                existing_defs[idx] = hist_def
                return

        existing_defs.append(hist_def)
        # Sort chronologically
        existing_defs.sort(key=lambda d: d.version_date)

    def get_canonical_term(self, term_id: str) -> str | None:
        """Return the canonical display term name."""
        norm_id = term_id.strip().lower()
        record = self._registry.get(norm_id)
        if record:
            return str(record["canonical_term"])
        return None

    def get_history(self, term_id: str) -> list[HistoricalDef]:
        """Return ordered historical definitions for a term."""
        norm_id = term_id.strip().lower()
        record = self._registry.get(norm_id)
        if not record:
            return []
        defs: list[HistoricalDef] = record["definitions"]
        return list(defs)

    def _get_vector(self, text: str) -> np.ndarray:
        """Get or compute embedding vector for definition text."""
        norm_text = text.strip()
        if norm_text in self._vector_cache:
            return self._vector_cache[norm_text]

        if self._embedder is not None and hasattr(self._embedder, "embed_query"):
            try:
                vec = np.asarray(self._embedder.embed_query(norm_text), dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    vec = vec / norm
                self._vector_cache[norm_text] = vec
                return vec
            except Exception as exc:
                logger.warning("external_embedder_failed_fallback_to_deterministic", error=str(exc))

        vec = _fast_deterministic_vector(norm_text)
        self._vector_cache[norm_text] = vec
        return vec

    def compute_drift(self, term_id: str, config: DriftConfig | None = None) -> TermDriftReport:
        """Compute semantic drift from origin definition to latest circular amendment."""
        cfg = config or DriftConfig()
        norm_id = term_id.strip().lower()
        record = self._registry.get(norm_id)
        if not record:
            raise KeyError(f"Term '{term_id}' not found in terminology registry")

        canonical_term = str(record["canonical_term"])
        definitions: list[HistoricalDef] = record["definitions"]

        if not definitions:
            return TermDriftReport(
                term_id=norm_id,
                canonical_term=canonical_term,
                historical_definitions=[],
                semantic_distance_from_origin=0.0,
                key_diff_tokens=[],
                drift_alert=False,
            )

        if len(definitions) == 1:
            return TermDriftReport(
                term_id=norm_id,
                canonical_term=canonical_term,
                historical_definitions=definitions,
                semantic_distance_from_origin=0.0,
                key_diff_tokens=[],
                drift_alert=False,
            )

        origin_def = definitions[0]
        latest_def = definitions[-1]

        # Exact text equality check (reprints, gazette republished)
        if origin_def.definition_text.strip() == latest_def.definition_text.strip():
            return TermDriftReport(
                term_id=norm_id,
                canonical_term=canonical_term,
                historical_definitions=definitions,
                semantic_distance_from_origin=0.0,
                key_diff_tokens=[],
                drift_alert=False,
            )

        # Compute cosine distance
        v_origin = self._get_vector(origin_def.definition_text)
        v_latest = self._get_vector(latest_def.definition_text)

        sim = float(np.dot(v_origin, v_latest))
        # Clamp similarity to [-1.0, 1.0]
        sim = max(-1.0, min(1.0, sim))
        dist = max(0.0, 1.0 - sim)

        # Compute token differences
        origin_tokens = set(_tokenize_content_words(origin_def.definition_text))
        latest_tokens = _tokenize_content_words(latest_def.definition_text)

        # Tokens in latest that were absent in origin
        new_tokens = [tok for tok in latest_tokens if tok not in origin_tokens]
        # Drop duplicates preserving order
        seen: set[str] = set()
        key_diff: list[str] = []
        for t in new_tokens:
            if t not in seen:
                seen.add(t)
                key_diff.append(t)

        drift_alert = dist >= cfg.alert_threshold_distance
        if drift_alert:
            TERMINOLOGY_DRIFTS_FLAGGED_TOTAL.inc()

        return TermDriftReport(
            term_id=norm_id,
            canonical_term=canonical_term,
            historical_definitions=definitions,
            semantic_distance_from_origin=round(dist, 4),
            key_diff_tokens=key_diff[:15],
            drift_alert=drift_alert,
        )

    def _init_benchmark_catalog(self) -> None:
        """Seed benchmark statutory terms with documented historical revisions."""
        benchmarks = [
            (
                "critical-it-infrastructure",
                "Critical IT Infrastructure",
                [
                    (
                        "RBI/2015-16/418",
                        date(2016, 6, 2),
                        "Information technology assets and systems hosting core banking solutions and customer accounts.",
                    ),
                    (
                        "RBI/2023-24/107",
                        date(2023, 11, 7),
                        "IT assets, services, cloud environments, third-party software supply chains, and network interconnects whose compromise impairs financial systemic stability or customer trust.",
                    ),
                ],
            ),
            (
                "significant-beneficial-owner",
                "Significant Beneficial Owner",
                [
                    (
                        "MCA/SBO-2018",
                        date(2018, 6, 13),
                        "An individual holding ultimate beneficial interest of not less than 25 percent in shares of a company.",
                    ),
                    (
                        "MCA/SBO-AMEND-2019",
                        date(2019, 2, 8),
                        "An individual who holds not less than 10 percent of shares, voting rights, or right to receive distributable dividends, or exercises significant influence or control.",
                    ),
                ],
            ),
            (
                "digital-payment-system",
                "Digital Payment System",
                [
                    (
                        "RBI/PSS/2010/01",
                        date(2010, 9, 1),
                        "Electronic funds transfer system enabling debit and credit clearing through magnetic tape and RTGS.",
                    ),
                    (
                        "RBI/2021-22/89",
                        date(2021, 8, 27),
                        "Interoperable multi-channel digital payment rails including UPI, tokenized cards, payment aggregators, biometric authentication, and offline digital wallets.",
                    ),
                ],
            ),
            (
                "material-outsourcee",
                "Material Outsourcee",
                [
                    (
                        "RBI/OUTSOURCE/2006",
                        date(2006, 11, 3),
                        "Third-party vendors delivering physical data entry, cheque processing, and back-office customer support.",
                    ),
                    (
                        "RBI/2023-24/10",
                        date(2023, 4, 10),
                        "Any third-party or sub-contracted entity providing critical IT services, cloud infrastructure, AI models, or cybersecurity operations where failure impacts business continuity.",
                    ),
                ],
            ),
            (
                "small-value-digital-payment",
                "Small Value Digital Payment",
                [
                    (
                        "RBI/2019-20/127",
                        date(2019, 12, 30),
                        "Semi-closed prepaid payment instruments with monthly wallet loading limit up to Rs. 10,000 for essential digital payments.",
                    ),
                    (
                        "RBI/2023-24/53",
                        date(2023, 8, 10),
                        "Contactless offline payment transactions up to Rs. 500 per transaction and overall wallet threshold of Rs. 2,000 without requiring two-factor SMS OTP.",
                    ),
                ],
            ),
            (
                "systemically-important-nbfc",
                "Systemically Important NBFC",
                [
                    (
                        "RBI/DNBS/2006/184",
                        date(2006, 12, 12),
                        "Non-banking financial companies not accepting public deposits with asset size of Rs. 100 crore and above.",
                    ),
                    (
                        "RBI/2022-23/Scale-Based",
                        date(2022, 10, 19),
                        "NBFC Upper Layer entities identified through multi-factor scoring including asset size exceeding Rs. 10,000 crore, interconnectedness, complexity, and systemic risk weight.",
                    ),
                ],
            ),
            (
                "designated-non-financial-business",
                "Designated Non-Financial Business",
                [
                    (
                        "PMLA/GUIDELINES/2013",
                        date(2013, 2, 15),
                        "Casinos, real estate agents, dealers in precious metals, and dealers in precious stones.",
                    ),
                    (
                        "PMLA/SO-2036E/2023",
                        date(2023, 5, 3),
                        "Virtual asset service providers, crypto exchanges, peer-to-peer custodial wallet providers, trust and company service providers, and practicing chartered accountants acting as financial intermediaries.",
                    ),
                ],
            ),
            (
                "beneficial-ownership-threshold",
                "Beneficial Ownership Threshold",
                [
                    (
                        "RBI/KYC/2016/MD",
                        date(2016, 1, 1),
                        "Controlling ownership interest threshold of 25 percent for company shares and 15 percent for partnership firms.",
                    ),
                    (
                        "PMLA/AMEND/2023/10PCT",
                        date(2023, 9, 4),
                        "Controlling ownership interest threshold reduced strictly to 10 percent for companies and trusts, mandating look-through to natural persons.",
                    ),
                ],
            ),
            (
                "senior-management-personnel",
                "Senior Management Personnel",
                [
                    (
                        "SEBI/LODR/2015",
                        date(2015, 9, 2),
                        "Core management team comprising personnel who are one level below the executive directors, including the company secretary and CFO.",
                    ),
                    (
                        "SEBI/LODR/2023/AMEND",
                        date(2023, 1, 17),
                        "Officers and personnel heading functional departments, including all key managerial personnel, chief information security officer, chief risk officer, and ESG head, excluding administrative support.",
                    ),
                ],
            ),
            (
                "financial-creditor",
                "Financial Creditor",
                [
                    (
                        "IBC/ACT/2016",
                        date(2016, 12, 1),
                        "Any person to whom a financial debt is owed, including an assignee or transferee of such debt under commercial lending contracts.",
                    ),
                    (
                        "IBC/AMEND/2018",
                        date(2018, 6, 6),
                        "Any person to whom financial debt is owed, explicitly including all home-buyers and allottees of real estate projects as deemed financial creditors with statutory voting representation in the committee of creditors.",
                    ),
                ],
            ),
        ]

        for term_id, canon, def_list in benchmarks:
            for doc_id, vdate, text in def_list:
                self.register_definition(
                    term_id=term_id,
                    canonical_term=canon,
                    doc_id=doc_id,
                    version_date=vdate,
                    definition_text=text,
                )


_DEFAULT_TRACKER: TerminologyDriftTracker | None = None


def get_default_drift_tracker() -> TerminologyDriftTracker:
    """Return the global default TerminologyDriftTracker instance."""
    global _DEFAULT_TRACKER
    if _DEFAULT_TRACKER is None:
        _DEFAULT_TRACKER = TerminologyDriftTracker()
    return _DEFAULT_TRACKER
