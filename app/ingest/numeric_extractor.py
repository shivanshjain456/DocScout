"""Numerical Regulatory Evidence & Statutory Parameters Extractor for DocScout.

High-precision extractor extracting quantitative statutory parameters
(penalty amounts, filing windows, net worth thresholds, interest rate caps,
haircut percentages, capital ratios) into structured, queryable data.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any

# Normalization constants for Indian financial units
CRORE_MULTIPLIER = 10_000_000.0  # 1 Crore = 10^7
LAKH_MULTIPLIER = 100_000.0  # 1 Lakh = 10^5
THOUSAND_MULTIPLIER = 1_000.0

HOURS_TO_DAYS = 1.0 / 24.0
WEEKS_TO_DAYS = 7.0
MONTHS_TO_DAYS = 30.0
YEARS_TO_DAYS = 365.0


@dataclass(frozen=True)
class StatutoryParameter:
    """Structured statutory parameter extracted from regulatory prose or tables."""

    id: str
    document_id: str
    parameter_name: str
    parameter_type: str
    numeric_value: float
    unit: str
    normalized_value: float
    normalized_unit: str
    comparison_operator: str
    statutory_context: str
    threshold_ceiling: float | None = None
    section_reference: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    confidence_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_indian_number(raw_num_str: str) -> float:
    """Parse numbers formatted with Western or Indian comma groupings."""
    clean_str = raw_num_str.replace(",", "").strip()
    return float(clean_str)


# Regex patterns for comparison operators
_OPERATOR_PATTERNS = [
    (
        re.compile(r"\b(?:not\s+less\s+than|at\s+least|minimum\s+of|minimum)\b", re.IGNORECASE),
        "gte",
    ),
    (
        re.compile(
            r"\b(?:not\s+exceeding|not\s+more\s+than|maximum\s+of|maximum|up\s+to|within\s+a\s+ceiling\s+of)\b",
            re.IGNORECASE,
        ),
        "lte",
    ),
    (re.compile(r"\b(?:exceeding|greater\s+than|more\s+than|above)\b", re.IGNORECASE), "gt"),
    (re.compile(r"\b(?:below|less\s+than|under)\b", re.IGNORECASE), "lt"),
    (re.compile(r"\bbetween\b", re.IGNORECASE), "between"),
]

# Section header detection pattern
_SECTION_PATTERN = re.compile(
    r"\b(?:Section|Clause|Regulation|Rule|Paragraph|Para|Annexure|Schedule)\s+([A-Za-z0-9\.\-\(\)]+)",
    re.IGNORECASE,
)


class NumericalRegulatoryEvidenceExtractor:
    """Parser extracting quantitative statutory parameters from regulatory text."""

    def __init__(self) -> None:
        self._init_rules()

    def _init_rules(self) -> None:
        """Initialize extraction regex rules."""
        # Currency: INR / Rs / Rupees
        self._currency_pattern = re.compile(
            r"(?P<operator>not\s+less\s+than|not\s+exceeding|at\s+least|minimum|maximum|exceeding|penalty\s+of|fine\s+of)?\s*"
            r"(?P<prefix>Rs\.?|INR|₹|Rupees)?\s*"
            r"(?P<amount>\d+(?:,\d+)*(?:\.\d+)?)\s*"
            r"(?P<scale>crore|cr\.?|lakh|lakhs|lac|lacs|thousand|k)?\b",
            re.IGNORECASE,
        )

        # Time Windows:
        self._time_pattern = re.compile(
            r"\b(?P<context_prefix>within|cooling-off\s+period\s+of|moratorium\s+of|filing\s+window\s+of|period\s+of|not\s+later\s+than)?\s*"
            r"(?P<operator>not\s+less\s+than|not\s+exceeding|at\s+least|up\s+to)?\s*"
            r"(?P<value>\d+(?:\.\d+)?)\s*"
            r"(?P<unit>calendar\s+days|working\s+days|days|hours|weeks|months|years)\b",
            re.IGNORECASE,
        )

        # Percentages, Ratios & Basis Points:
        self._ratio_pattern = re.compile(
            r"(?:(?P<prefix_op>not\s+less\s+than|not\s+below|at\s+least|minimum|maximum|not\s+exceeding)\s+)?"
            r"(?:(?P<concept>CRAR|Tier\s+1|Tier\s+2|haircut|LCR|NSFR|leverage\s+ratio|interest\s+rate\s+cap|margin|spread|slippage)\s+)?"
            r"(?:(?P<suffix_op>not\s+less\s+than|not\s+below|at\s+least|minimum|maximum|not\s+exceeding|of)\s+)?"
            r"(?P<value>\d+(?:\.\d+)?)\s*"
            r"(?P<unit>%|percent|percentage|bps|basis\s+points)(?![a-zA-Z0-9])",
            re.IGNORECASE,
        )

    def _determine_operator(self, text_snippet: str) -> str:
        """Identify comparison operator from text snippet."""
        for pattern, op in _OPERATOR_PATTERNS:
            if pattern.search(text_snippet):
                return op
        return "eq"

    def _find_closest_section(self, text: str, pos: int) -> str | None:
        """Locate the closest regulatory section heading prior to position."""
        preceding = text[:pos]
        matches = list(_SECTION_PATTERN.finditer(preceding))
        if matches:
            last = matches[-1]
            return last.group(0).strip().rstrip(".")
        return None

    def extract_from_text(
        self,
        text: str,
        document_id: str = "doc-generic",
        version_id: str | None = None,
    ) -> list[StatutoryParameter]:
        """Extract all statutory parameters from given regulatory prose or table."""
        if not text or not text.strip():
            return []

        parameters: list[StatutoryParameter] = []

        # 1. Extract Monetary Parameters (Penalties, Net Worth, Limits)
        for m in self._currency_pattern.finditer(text):
            amount_str = m.group("amount")
            scale_str = (m.group("scale") or "").lower()
            prefix_str = m.group("prefix")
            operator_raw = m.group("operator") or ""

            if not prefix_str and not scale_str:
                continue

            try:
                base_num = _parse_indian_number(amount_str)
            except ValueError:
                continue

            # Calculate normalized INR
            normalized_inr = base_num
            unit = "INR"
            if "cr" in scale_str:
                normalized_inr = base_num * CRORE_MULTIPLIER
                unit = "crore"
            elif "lakh" in scale_str or "lac" in scale_str:
                normalized_inr = base_num * LAKH_MULTIPLIER
                unit = "lakh"
            elif "thousand" in scale_str or scale_str == "k":
                normalized_inr = base_num * THOUSAND_MULTIPLIER
                unit = "thousand"

            start, end = m.span()
            ctx_start = max(0, start - 40)
            ctx_end = min(len(text), end + 40)
            context_snip = text[ctx_start:ctx_end].replace("\n", " ").strip()

            operator = self._determine_operator(operator_raw or text[max(0, start - 25) : start])

            # Classify parameter type: prioritize leading qualifiers
            leading_ctx = f"{text[max(0, start - 35) : start]} {operator_raw}".lower()
            trailing_ctx = text[end : min(len(text), end + 35)].lower()

            if any(w in leading_ctx for w in ["net worth", "capital", "turnover", "paid-up"]):
                param_type = "net_worth_threshold"
                param_name = "Net Worth / Capital Threshold"
            elif any(w in leading_ctx for w in ["penalty", "fine", "penal"]):
                param_type = "penalty"
                param_name = "Statutory Penalty / Fine"
            elif any(w in leading_ctx for w in ["exposure", "limit", "ceiling"]):
                param_type = "exposure_limit"
                param_name = "Statutory Exposure Limit"
            elif any(w in trailing_ctx for w in ["penalty", "fine", "penal"]):
                param_type = "penalty"
                param_name = "Statutory Penalty / Fine"
            elif any(w in trailing_ctx for w in ["net worth", "capital", "turnover", "paid-up"]):
                param_type = "net_worth_threshold"
                param_name = "Net Worth / Capital Threshold"
            else:
                param_type = "financial_amount"
                param_name = "Statutory Monetary Threshold"

            section_ref = self._find_closest_section(text, start)
            param_id = hashlib.sha256(
                f"{document_id}:{param_type}:{start}:{end}:{normalized_inr}".encode()
            ).hexdigest()[:16]

            parameters.append(
                StatutoryParameter(
                    id=param_id,
                    document_id=document_id,
                    parameter_name=param_name,
                    parameter_type=param_type,
                    numeric_value=base_num,
                    unit=unit,
                    normalized_value=normalized_inr,
                    normalized_unit="INR",
                    comparison_operator=operator,
                    statutory_context=context_snip,
                    section_reference=section_ref,
                    char_start=start,
                    char_end=end,
                    confidence_score=0.98 if prefix_str else 0.90,
                )
            )

        # 2. Extract Time & Filing Windows
        for m in self._time_pattern.finditer(text):
            val_str = m.group("value")
            unit_raw = m.group("unit").lower()
            context_pfx = (m.group("context_prefix") or "").lower()
            operator_raw = m.group("operator") or ""

            try:
                numeric_val = float(val_str)
            except ValueError:
                continue

            if "hour" in unit_raw:
                norm_days = numeric_val * HOURS_TO_DAYS
                unit_label = "hours"
            elif "week" in unit_raw:
                norm_days = numeric_val * WEEKS_TO_DAYS
                unit_label = "weeks"
            elif "month" in unit_raw:
                norm_days = numeric_val * MONTHS_TO_DAYS
                unit_label = "months"
            elif "year" in unit_raw:
                norm_days = numeric_val * YEARS_TO_DAYS
                unit_label = "years"
            else:
                norm_days = numeric_val
                unit_label = "days"

            start, end = m.span()
            ctx_start = max(0, start - 40)
            ctx_end = min(len(text), end + 40)
            context_snip = text[ctx_start:ctx_end].replace("\n", " ").strip()

            operator = self._determine_operator(operator_raw or text[max(0, start - 25) : start])

            leading_text = text[max(0, start - 35) : start].lower()

            if "cooling" in context_pfx or "cooling" in leading_text:
                param_type = "cooling_off_period"
                param_name = "Cooling-Off Period"
            elif "moratorium" in context_pfx or "moratorium" in leading_text:
                param_type = "moratorium_period"
                param_name = "Statutory Moratorium Period"
            elif (
                "filing" in leading_text
                or "disclose" in leading_text
                or "report" in leading_text
                or "submit" in leading_text
                or "within" in leading_text
                or context_pfx == "within"
            ):
                param_type = "filing_window"
                param_name = "Statutory Filing Window"
            else:
                param_type = "time_window"
                param_name = "Statutory Time Window"

            section_ref = self._find_closest_section(text, start)
            param_id = hashlib.sha256(
                f"{document_id}:{param_type}:{start}:{end}:{norm_days}".encode()
            ).hexdigest()[:16]

            parameters.append(
                StatutoryParameter(
                    id=param_id,
                    document_id=document_id,
                    parameter_name=param_name,
                    parameter_type=param_type,
                    numeric_value=numeric_val,
                    unit=unit_label,
                    normalized_value=norm_days,
                    normalized_unit="days",
                    comparison_operator=operator,
                    statutory_context=context_snip,
                    section_reference=section_ref,
                    char_start=start,
                    char_end=end,
                    confidence_score=0.95 if context_pfx else 0.88,
                )
            )

        # 3. Extract Ratios, Percentages & Haircuts
        for m in self._ratio_pattern.finditer(text):
            val_str = m.group("value")
            unit_str = m.group("unit").lower()
            concept_str = (m.group("concept") or "").strip()
            prefix_op = m.group("prefix_op") or ""
            suffix_op = m.group("suffix_op") or ""

            try:
                numeric_val = float(val_str)
            except ValueError:
                continue

            if "bps" in unit_str or "basis" in unit_str:
                normalized_ratio = numeric_val / 10_000.0
                unit_label = "bps"
            else:
                normalized_ratio = numeric_val / 100.0
                unit_label = "percent"

            start, end = m.span()
            ctx_start = max(0, start - 40)
            ctx_end = min(len(text), end + 40)
            context_snip = text[ctx_start:ctx_end].replace("\n", " ").strip()

            operator_raw = f"{prefix_op} {suffix_op}".strip()
            operator = self._determine_operator(operator_raw or text[max(0, start - 25) : start])

            local_window = text[max(0, start - 35) : min(len(text), end + 25)].lower()

            if (
                any(k in local_window for k in ["crar", "capital adequacy"])
                or concept_str.upper() == "CRAR"
            ):
                param_type = "capital_adequacy"
                param_name = "Capital Adequacy Ratio (CRAR)"
            elif "haircut" in local_window or "haircut" in concept_str.lower():
                param_type = "haircut"
                param_name = "Statutory Regulatory Haircut"
            elif any(k in local_window for k in ["leverage", "tier 1", "tier 2"]):
                param_type = "capital_ratio"
                param_name = f"{concept_str or 'Capital'} Ratio"
            elif any(k in local_window for k in ["lcr", "liquidity coverage"]):
                param_type = "liquidity_ratio"
                param_name = "Liquidity Coverage Ratio (LCR)"
            elif any(k in local_window for k in ["interest rate", "margin", "spread"]):
                param_type = "interest_rate_cap"
                param_name = "Interest Rate / Margin Cap"
            else:
                param_type = "percentage_threshold"
                param_name = "Statutory Percentage Threshold"

            section_ref = self._find_closest_section(text, start)
            param_id = hashlib.sha256(
                f"{document_id}:{param_type}:{start}:{end}:{normalized_ratio}".encode()
            ).hexdigest()[:16]

            parameters.append(
                StatutoryParameter(
                    id=param_id,
                    document_id=document_id,
                    parameter_name=param_name,
                    parameter_type=param_type,
                    numeric_value=numeric_val,
                    unit=unit_label,
                    normalized_value=normalized_ratio,
                    normalized_unit="ratio",
                    comparison_operator=operator,
                    statutory_context=context_snip,
                    section_reference=section_ref,
                    char_start=start,
                    char_end=end,
                    confidence_score=0.96 if concept_str else 0.85,
                )
            )

        parameters.sort(key=lambda p: p.char_start or 0)
        return parameters
