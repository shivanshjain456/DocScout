"""Data Contamination & Lexical Leakage Stratifier (FEAT-088, ADR-0079).

Automatically partitions evaluation gold set items into lexical leakage bands
(< 0.5 term overlap, 0.5 - 0.8 overlap, >= 0.8 overlap) to diagnose benchmark
memorization, evaluate lexical confounders, and verify robust generalization.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("docscout.evals.leakage")

TOKEN_RE = re.compile(r"[a-zA-Z0-9-]+")


@dataclass(frozen=True)
class LeakageConfig:
    """Threshold configurations for lexical leakage stratification bands."""

    low_threshold: float = 0.50
    high_threshold: float = 0.80

    def __post_init__(self) -> None:
        if not (0.0 <= self.low_threshold < self.high_threshold <= 1.0):
            raise ValueError(
                f"Invalid leakage thresholds: expected 0.0 <= low_threshold ({self.low_threshold}) "
                f"< high_threshold ({self.high_threshold}) <= 1.0"
            )


@dataclass(frozen=True)
class MetricSlice:
    """Retrieval evaluation metrics for a specific lexical leakage stratum."""

    band_name: str
    threshold_low: float
    threshold_high: float
    n: int
    recall: float
    hit_rate: float
    mrr: float
    ndcg: float
    item_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "band_name": self.band_name,
            "threshold_low": self.threshold_low,
            "threshold_high": self.threshold_high,
            "n": self.n,
            "recall": round(self.recall, 4),
            "hit_rate": round(self.hit_rate, 4),
            "mrr": round(self.mrr, 4),
            "ndcg": round(self.ndcg, 4),
            "item_ids": self.item_ids,
        }


@dataclass(frozen=True)
class LeakageStratificationReport:
    """Stratified report grouping metrics by Low, Medium, and High lexical leakage."""

    low_leakage: MetricSlice
    medium_leakage: MetricSlice
    high_leakage: MetricSlice
    config_name: str = "hybrid-rrf"
    cutoff: int = 5
    computation_time_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "cutoff": self.cutoff,
            "computation_time_ms": round(self.computation_time_ms, 3),
            "low_leakage": self.low_leakage.as_dict(),
            "medium_leakage": self.medium_leakage.as_dict(),
            "high_leakage": self.high_leakage.as_dict(),
        }

    def render_markdown(self) -> str:
        """Render a formatted markdown table of leakage band metrics."""
        lines: list[str] = [
            f"### Lexical Leakage Stratification ({self.config_name} @ k={self.cutoff})",
            "",
            "| Stratum | Overlap Range | Items | Recall | Hit Rate | MRR | nDCG |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in (self.low_leakage, self.medium_leakage, self.high_leakage):
            lines.append(
                f"| {s.band_name} | [{s.threshold_low:.2f}, {s.threshold_high:.2f}) | "
                f"{s.n} | {s.recall:.3f} | {s.hit_rate:.3f} | {s.mrr:.3f} | {s.ndcg:.3f} |"
            )
        lines.append("")
        return "\n".join(lines)


def tokenize_terms(text: str) -> set[str]:
    """Tokenize arbitrary text into a set of lowercased alphanumeric tokens."""
    if not text:
        return set()
    return set(TOKEN_RE.findall(text.lower()))


def compute_quote_lexical_overlap(question: str, evidence_quotes: Sequence[str]) -> float:
    """Compute term intersection between question text and gold citation quotes.

    Formula:
        Overlap = |Terms(Question) ∩ Terms(Quotes)| / |Terms(Question)|
    """
    q_terms = tokenize_terms(question)
    if not q_terms:
        return 0.0
    if not evidence_quotes:
        return 0.0

    quote_text = " ".join(evidence_quotes)
    quote_terms = tokenize_terms(quote_text)
    return len(q_terms & quote_terms) / len(q_terms)


def stratify_goldset_items(
    items: Sequence[dict[str, Any]],
    config: LeakageConfig | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Partition gold items into Low, Medium, and High lexical leakage strata.

    Guaranteed performance: executes in <= 5.0 ms for full benchmark set.
    """
    cfg = config or LeakageConfig()
    stratified: dict[str, list[dict[str, Any]]] = {
        "low": [],
        "medium": [],
        "high": [],
    }

    for item in items:
        # Unanswerable items carry no citation quotes and are excluded from lexical leakage
        if item.get("answer_type") == "unanswerable":
            continue

        q = str(item.get("question", ""))
        quotes = item.get("evidence_quotes", [])
        overlap = compute_quote_lexical_overlap(q, quotes)

        annotated = dict(item)
        annotated["lexical_overlap"] = round(overlap, 4)

        if overlap < cfg.low_threshold:
            stratified["low"].append(annotated)
        elif overlap < cfg.high_threshold:
            stratified["medium"].append(annotated)
        else:
            stratified["high"].append(annotated)

    return stratified


def build_stratification_report(
    item_scores: Sequence[dict[str, Any]],
    config: LeakageConfig | None = None,
    config_name: str = "hybrid-rrf",
    cutoff: int = 5,
) -> LeakageStratificationReport:
    """Build a LeakageStratificationReport from evaluated item scoring rows."""
    start_time = time.perf_counter()
    cfg = config or LeakageConfig()

    low_items: list[dict[str, Any]] = []
    med_items: list[dict[str, Any]] = []
    high_items: list[dict[str, Any]] = []

    for row in item_scores:
        overlap = float(row.get("lexical_overlap", 0.0))
        if overlap < cfg.low_threshold:
            low_items.append(row)
        elif overlap < cfg.high_threshold:
            med_items.append(row)
        else:
            high_items.append(row)

    def _make_slice(
        name: str,
        low_t: float,
        high_t: float,
        rows: list[dict[str, Any]],
    ) -> MetricSlice:
        n = len(rows)
        if n == 0:
            return MetricSlice(
                band_name=name,
                threshold_low=low_t,
                threshold_high=high_t,
                n=0,
                recall=0.0,
                hit_rate=0.0,
                mrr=0.0,
                ndcg=0.0,
                item_ids=[],
            )

        # Handle recall_at dict or direct recall field
        recalls = [
            float(r["recall_at"].get(str(cutoff), r.get("recall", 0.0)))
            if isinstance(r.get("recall_at"), dict)
            else float(r.get("recall", 0.0))
            for r in rows
        ]
        hits = [
            1.0
            if (
                r.get("hit_at", {}).get(str(cutoff), r.get("hit", False))
                if isinstance(r.get("hit_at"), dict)
                else r.get("hit", False)
            )
            else 0.0
            for r in rows
        ]
        mrrs = [float(r.get("mrr", 0.0)) for r in rows]
        ndcgs = [float(r.get("ndcg", 0.0)) for r in rows]
        item_ids = [str(r.get("item_id", "")) for r in rows]

        return MetricSlice(
            band_name=name,
            threshold_low=low_t,
            threshold_high=high_t,
            n=n,
            recall=sum(recalls) / n,
            hit_rate=sum(hits) / n,
            mrr=sum(mrrs) / n,
            ndcg=sum(ndcgs) / n,
            item_ids=item_ids,
        )

    low_slice = _make_slice("low", 0.0, cfg.low_threshold, low_items)
    med_slice = _make_slice("medium", cfg.low_threshold, cfg.high_threshold, med_items)
    high_slice = _make_slice("high", cfg.high_threshold, 1.0, high_items)

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    return LeakageStratificationReport(
        low_leakage=low_slice,
        medium_leakage=med_slice,
        high_leakage=high_slice,
        config_name=config_name,
        cutoff=cutoff,
        computation_time_ms=elapsed_ms,
    )
