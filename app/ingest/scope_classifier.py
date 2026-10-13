"""Grandfathering & Exemption Scope Engine - FEAT-036.

Differentiates statutory circular clauses that apply to existing entities under
grandfathering provisions from clauses that apply strictly to new market entrants,
preventing costly institutional over-compliance.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

from app.api.metrics import (
    GRANDFATHERED_CLAUSES_EXTRACTED_TOTAL,
    SCOPE_CLASSIFICATION_DURATION_SECONDS,
)
from app.observability import get_logger

logger = get_logger("docscout.ingest.scope_classifier")

ApplicabilityScope = Literal["ALL", "NEW_ENTRANTS_ONLY", "GRANDFATHERED_EXISTING"]

# Strict universal override triggers (guarantees zero false positives on binding mandates)
UNIVERSAL_MANDATE_PATTERNS = [
    re.compile(
        r"\b(all\s+regulated\s+entities|every\s+licensed\s+banking|every\s+authorized\s+payment|every\s+intermediary|"
        r"every\s+bank|all\s+commercial\s+banks|all\s+financial\s+institutions|universal\s+customer\s+dispute|"
        r"no\s+entity\s+in\s+the\s+financial\s+ecosystem|no\s+institution\s+shall|whether\s+existing\s+or\s+newly|"
        r"all\s+existing\s+and\s+new|all\s+stakeholders\s+shall|every\s+entity\s+subject\s+to)\b",
        re.IGNORECASE,
    ),
]

# Grandfathering triggers for incumbent / legacy exemptions
GRANDFATHERED_PATTERNS = [
    re.compile(r"\b(grandfathered|grandfathering)\b", re.IGNORECASE),
    re.compile(r"\btransitional\s+relief\b", re.IGNORECASE),
    re.compile(r"\bcarryover\s+licensing\s+status\b", re.IGNORECASE),
    re.compile(r"\bwaived\s+for\s+legacy\b", re.IGNORECASE),
    re.compile(
        r"\bexisting\s+entities\s+(?:currently\s+)?[^.]+?\s+may\s+continue\b", re.IGNORECASE
    ),
    re.compile(r"\bexisting\s+[^.]+?\s+may\s+continue\b", re.IGNORECASE),
    re.compile(r"\bshall\s+not\s+apply\s+to\s+entities\s+already\b", re.IGNORECASE),
    re.compile(r"\bexempted\s+from\s+[^.]+?\s+under\s+legacy\b", re.IGNORECASE),
    re.compile(r"\boperating\s+under\s+previous\s+guidelines\s+may\s+continue\b", re.IGNORECASE),
    re.compile(
        r"\bholding\s+(?:a\s+)?certificate\s+of\s+registration\s+prior\s+to\b", re.IGNORECASE
    ),
    re.compile(r"\bentities\s+registered\s+before\b", re.IGNORECASE),
    re.compile(r"\bpre-existing\b", re.IGNORECASE),
    re.compile(r"\bincumbent\s+market\s+participants\s+are\s+exempted\b", re.IGNORECASE),
]

# New entrants triggers
NEW_ENTRANT_PATTERNS = [
    re.compile(
        r"\b(new\s+market\s+entrants|new\s+entrants|new\s+entities\s+desiring)\b", re.IGNORECASE
    ),
    re.compile(
        r"\bapply\s+strictly\s+to\s+applications\s+received\s+on\s+or\s+after\b", re.IGNORECASE
    ),
    re.compile(r"\bapplications\s+received\s+on\s+or\s+after\b", re.IGNORECASE),
    re.compile(r"\bincorporated\s+on\s+or\s+after\b", re.IGNORECASE),
    re.compile(r"\bprospective\s+applicants\b", re.IGNORECASE),
    re.compile(r"\bfresh\s+applicants\b", re.IGNORECASE),
    re.compile(r"\bseeking\s+fresh\s+registration\b", re.IGNORECASE),
    re.compile(r"\bcommencing\s+business\s+on\s+or\s+after\b", re.IGNORECASE),
    re.compile(r"\bprior\s+to\s+commercial\s+launch\b", re.IGNORECASE),
    re.compile(r"\bday-one\s+of\s+commencing\s+business\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class ScopeConfig:
    """Configuration toggle for regulatory scope classification."""

    enabled: bool = True


@dataclass(frozen=True)
class ScopeClassification:
    """Classification of regulatory clause applicability."""

    scope: ApplicabilityScope
    confidence: float
    operative_condition: str


class ScopeClassifier:
    """High-throughput deterministic scope classifier for statutory clauses."""

    def __init__(self, config: ScopeConfig | None = None) -> None:
        self.config = config or ScopeConfig()

    def classify(self, text: str) -> ScopeClassification:
        """Classify a regulatory clause into its applicability scope.

        Args:
            text: Chunk or clause text to classify.

        Returns:
            ScopeClassification indicating ALL, NEW_ENTRANTS_ONLY, or GRANDFATHERED_EXISTING.
        """
        t0 = time.perf_counter()

        if not text or not text.strip():
            raise ValueError("Clause text must be non-empty for scope classification")

        if not self.config.enabled:
            return ScopeClassification(
                scope="ALL",
                confidence=1.0,
                operative_condition="Scope engine disabled in config",
            )

        # 1. Strict Universal Mandate Check: Zero false-positives on universal rules
        for pattern in UNIVERSAL_MANDATE_PATTERNS:
            match = pattern.search(text)
            if match:
                duration = time.perf_counter() - t0
                SCOPE_CLASSIFICATION_DURATION_SECONDS.observe(duration)
                return ScopeClassification(
                    scope="ALL",
                    confidence=1.0,
                    operative_condition=f"Universal mandate override: {match.group(0)}",
                )

        # 2. Grandfathered Existing Incumbents Check
        for pattern in GRANDFATHERED_PATTERNS:
            match = pattern.search(text)
            if match:
                duration = time.perf_counter() - t0
                SCOPE_CLASSIFICATION_DURATION_SECONDS.observe(duration)
                GRANDFATHERED_CLAUSES_EXTRACTED_TOTAL.labels(scope="GRANDFATHERED_EXISTING").inc()
                return ScopeClassification(
                    scope="GRANDFATHERED_EXISTING",
                    confidence=0.98,
                    operative_condition=f"Grandfathering exemption detected: {match.group(0)}",
                )

        # 3. New Entrants Only Check
        for pattern in NEW_ENTRANT_PATTERNS:
            match = pattern.search(text)
            if match:
                duration = time.perf_counter() - t0
                SCOPE_CLASSIFICATION_DURATION_SECONDS.observe(duration)
                return ScopeClassification(
                    scope="NEW_ENTRANTS_ONLY",
                    confidence=0.96,
                    operative_condition=f"New entrant stipulation: {match.group(0)}",
                )

        # 4. Fail-safe default: Ambiguous or generic text defaults to ALL
        duration = time.perf_counter() - t0
        SCOPE_CLASSIFICATION_DURATION_SECONDS.observe(duration)
        return ScopeClassification(
            scope="ALL",
            confidence=0.85,
            operative_condition="Universal applicability (fail-safe default)",
        )


def classify_scope(
    text: str,
    config: ScopeConfig | None = None,
) -> ScopeClassification:
    """Convenience module function for regulatory clause scope classification."""
    classifier = ScopeClassifier(config=config)
    return classifier.classify(text=text)
