"""Sunset clause & mandatory cutover deadline extraction engine - FEAT-035.

Extracts statutory transition windows, cutover dates, and sunset milestones
from regulatory circulars (RBI, SEBI, etc.) with sub-millisecond deterministic
precision, zero false-positive historical dates, and strict exclusion of
unnotified speculative dates.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from dateutil import parser as date_parser

from app.api.metrics import (
    DEADLINE_EXTRACTION_DURATION_SECONDS,
    UPCOMING_DEADLINES_COUNT,
)
from app.observability import get_logger

logger = get_logger("docscout.ingest.deadline_extractor")

UrgencyLevel = Literal["CRITICAL", "WARNING", "INFO"]

# Regex pattern to identify explicit exclusion of date notification
UNNOTIFIED_PATTERN = re.compile(
    r"\b(to\s+be\s+notified\s+separately|shall\s+be\s+notified\s+separately|will\s+be\s+notified\s+separately)\b",
    re.IGNORECASE,
)

# Date candidate pattern matching common Indian gazette / circular formats
CALENDAR_DATE_REGEX = (
    r"(?:"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December),?\s+\d{4}"
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{4}"
    r")"
)

# Trigger patterns representing operative statutory transition windows
CUTOVER_PATTERNS = [
    # 1. with effect from / w.e.f. / on and from
    re.compile(
        rf"(?:with\s+effect\s+from|w\.e\.f\.|applicable\s+with\s+effect\s+from|on\s+and\s+from)\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 2. shall transition by / transition by
    re.compile(
        rf"(?:shall\s+transition\s+by|transition\s+by|shall\s+transition\s+to\s+[^.]+?\s+by)\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 3. come into force on / with effect from
    re.compile(
        rf"(?:shall\s+come\s+into\s+force\s+(?:on|with\s+effect\s+from)|come\s+into\s+force\s+(?:on|with\s+effect\s+from)|comes\s+into\s+force\s+(?:on|with\s+effect\s+from))\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 4. mandatory cutover date / cut-off date / deadline
    re.compile(
        rf"(?:mandatory\s+cutover\s+date|cut-off\s+date|deadline)(?:\s+for\s+[^.]+?)?\s+(?:is|shall\s+be)?\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 5. extended up to / extended till
    re.compile(
        rf"(?:timeline\s+for\s+[^.]+?\s+is\s+extended\s+up\s+to|extended\s+up\s+to|extended\s+till)\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 6. on or before / comply by / ensure compliance on or before
    re.compile(
        rf"(?:on\s+or\s+before|compliance\s+shall\s+be\s+ensured\s+on\s+or\s+before|compliance\s+by|shall\s+comply\s+by|comply\s+by|must\s+be\s+furnished\s+on\s+or\s+before|regularized\s+on\s+or\s+before)\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 7. sunset on / sunset date
    re.compile(
        rf"(?:shall\s+sunset\s+on|sunset\s+date\s+(?:is|shall\s+be)?)\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 8. on or after prohibition cutovers (e.g. no entity shall store on or after DATE)
    re.compile(
        rf"(?:on\s+or\s+after|shall\s+store\s+[^.]+?\s+on\s+or\s+after)\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
    # 9. by <date> in transition/mandate clauses
    re.compile(
        rf"\bby\s+({CALENDAR_DATE_REGEX})",
        re.IGNORECASE,
    ),
]


@dataclass(frozen=True)
class DeadlineAlertConfig:
    """Configuration thresholds for regulatory cutover and deadline alerts."""

    critical_threshold_days: int = 15
    warning_threshold_days: int = 45


@dataclass(frozen=True)
class RegulatoryDeadline:
    """An extracted regulatory cutover milestone, sunset date, or transition deadline."""

    doc_id: str
    mandate_description: str
    effective_date: date
    days_remaining: int
    urgency_level: UrgencyLevel
    extracted_snippet: str | None = None
    confidence: float = 1.0


def _clean_date_string(raw: str) -> str:
    """Clean ordinal suffixes from date strings for robust parsing."""
    cleaned = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", raw)
    cleaned = re.sub(r"\bday\s+of\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _protect_abbreviations(text: str) -> str:
    """Protect statutory abbreviations with periods from breaking sentence split."""
    protected = re.sub(r"\bRs\.\s*", "Rs ", text)
    protected = re.sub(r"\bNo\.\s*", "No ", protected)
    protected = re.sub(r"\bw\.e\.f\.\s*", "wef ", protected, flags=re.IGNORECASE)
    protected = re.sub(r"\bi\.e\.\s*", "ie ", protected, flags=re.IGNORECASE)
    protected = re.sub(r"\be\.g\.\s*", "eg ", protected, flags=re.IGNORECASE)
    return protected


class DeadlineExtractor:
    """Deterministic extractor for regulatory cutover windows and sunset dates."""

    def __init__(self, config: DeadlineAlertConfig | None = None) -> None:
        self.config = config or DeadlineAlertConfig()

    def extract(
        self,
        text: str,
        doc_id: str,
        reference_date: date | None = None,
    ) -> list[RegulatoryDeadline]:
        """Extract transition deadlines and cutover dates from document text.

        Args:
            text: Full text of circular or regulatory directive.
            doc_id: Stable identifier of the document.
            reference_date: Effective date against which to calculate remaining days.
                            Defaults to current UTC date.

        Returns:
            List of validated upcoming RegulatoryDeadline objects.
        """
        t0 = time.perf_counter()

        if not text or not text.strip():
            raise ValueError("Document text must be non-empty")
        if len(text) < 100:
            raise ValueError(
                "Document text must be at least 100 characters for deadline extraction"
            )

        ref = reference_date or datetime.now(UTC).date()
        deadlines: list[RegulatoryDeadline] = []
        seen_keys: set[tuple[str, date]] = set()

        # Protect abbreviations before sentence splitting
        protected_text = _protect_abbreviations(text)

        # Split text into sentences for scoped context extraction
        sentences = re.split(r"(?<=[.!?])\s+", protected_text)

        for sentence in sentences:
            sentence_clean = sentence.strip()
            if not sentence_clean:
                continue

            # SPEC EXCLUSION: If the sentence specifies "to be notified separately",
            # do not guess or emit any speculative dates.
            if UNNOTIFIED_PATTERN.search(sentence_clean):
                continue

            for pattern in CUTOVER_PATTERNS:
                for match in pattern.finditer(sentence_clean):
                    raw_date = match.group(1)
                    cleaned_date = _clean_date_string(raw_date)

                    try:
                        parsed_dt = date_parser.parse(cleaned_date, dayfirst=True)
                        parsed_date = parsed_dt.date()
                    except (ValueError, OverflowError):
                        continue

                    # Validate reasonable statutory year bounds
                    if parsed_date.year < 2000 or parsed_date.year > 2099:
                        continue

                    # REGRESSION GUARD: Historical dates are not upcoming deadlines
                    days_remaining = (parsed_date - ref).days
                    if days_remaining < 0:
                        continue

                    key = (doc_id, parsed_date)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    # Urgency classification
                    if days_remaining <= self.config.critical_threshold_days:
                        urgency: UrgencyLevel = "CRITICAL"
                    elif days_remaining <= self.config.warning_threshold_days:
                        urgency = "WARNING"
                    else:
                        urgency = "INFO"

                    # Surrounding sentence or clause as mandate description
                    mandate = sentence_clean[:300].strip()

                    deadlines.append(
                        RegulatoryDeadline(
                            doc_id=doc_id,
                            mandate_description=mandate,
                            effective_date=parsed_date,
                            days_remaining=days_remaining,
                            urgency_level=urgency,
                            extracted_snippet=match.group(0),
                            confidence=1.0,
                        )
                    )

        # Sort chronologically by effective date
        deadlines.sort(key=lambda d: d.effective_date)

        duration = time.perf_counter() - t0
        DEADLINE_EXTRACTION_DURATION_SECONDS.observe(duration)

        # Update gauge metrics
        crit_count = sum(1 for d in deadlines if d.urgency_level == "CRITICAL")
        warn_count = sum(1 for d in deadlines if d.urgency_level == "WARNING")
        info_count = sum(1 for d in deadlines if d.urgency_level == "INFO")

        UPCOMING_DEADLINES_COUNT.labels(urgency="CRITICAL").set(crit_count)
        UPCOMING_DEADLINES_COUNT.labels(urgency="WARNING").set(warn_count)
        UPCOMING_DEADLINES_COUNT.labels(urgency="INFO").set(info_count)

        return deadlines


def extract_regulatory_deadlines(
    text: str,
    doc_id: str,
    reference_date: date | None = None,
    config: DeadlineAlertConfig | None = None,
) -> list[RegulatoryDeadline]:
    """Convenience module function for regulatory deadline extraction."""
    extractor = DeadlineExtractor(config=config)
    return extractor.extract(text=text, doc_id=doc_id, reference_date=reference_date)
